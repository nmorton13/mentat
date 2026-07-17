import os
from openai import OpenAI
import json
import re
import hashlib
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple, Union
from pathlib import Path

# Import centralized configuration
from .config import (
    get_current_model, OPENAI_API_KEY, OPENROUTER_API_KEY,
    OPENAI_BASE_URL, OPENROUTER_BASE_URL, EMBEDDING_MODEL,
    get_chat_api_key, get_chat_base_url,
    CURRENT_EMBEDDING_DIMENSIONS, EMBEDDING_CACHE_SIZE,
    PROJECT_PREVIEW_LENGTH, GENERAL_PREVIEW_LENGTH,
    DEFAULT_WEEKLY_DAYS, SYNTHESIS_ITEM_LIMIT, LLM_REQUEST_TIMEOUT,
    LLM_LOGGING_ENABLED, LLM_LOG_DIR
)

# Import shared utilities
from .utils import standardize_truncation
from .private_files import ensure_private_directory, open_private_text
from .llm import complete, complete_json, get_task_llm_route
from .prompts import (
    ENTITY_EXTRACTION_PROMPT, MULTI_TODO_EXTRACTION_PROMPT,
    SYNTHESIZE_NOTES_PROMPT, THOUGHT_ANALYSIS_PROMPT,
    TODO_EXTRACTION_PROMPT, WEEKLY_SUMMARY_PROMPT, get_capture_analysis_prompt,
    get_temporal_intent_prompt,
)

# =============================================================================
# LLM LOGGING UTILITIES
# =============================================================================

def log_llm_interaction(
    model: str,
    messages: List[Dict[str, str]],
    response: Optional[str] = None,
    function_name: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    """
    Log LLM prompts and responses to JSON files for debugging and analysis.

    Creates timestamped log files in LLM_LOG_DIR containing:
    - The model used
    - Full message history (system + user prompts)
    - The AI response
    - Function context and custom metadata

    Only logs when LLM_LOGGING_ENABLED is True in config.

    Parameters:
        model (str): The model identifier used for this request
        messages (List[Dict]): The messages sent to the LLM (with role/content)
        response (Optional[str]): The LLM's response text
        function_name (Optional[str]): Name of calling function for context
        metadata (Optional[Dict]): Additional context to log (e.g., user_id, tags)
    """
    if not LLM_LOGGING_ENABLED:
        return

    try:
        # Create log directory if it doesn't exist
        log_dir = ensure_private_directory(LLM_LOG_DIR)

        # Generate timestamped filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        function_prefix = f"{function_name}_" if function_name else ""
        log_file = log_dir / f"{function_prefix}{timestamp}.json"

        # Build log data
        log_data = {
            "timestamp": datetime.now().isoformat(),
            "model": model,
            "function": function_name or "unknown",
            "messages": messages,
            "response": response,
            "metadata": metadata or {}
        }

        # Calculate token counts for analysis (rough estimate)
        total_chars = sum(len(str(m.get('content', ''))) for m in messages)
        if response:
            total_chars += len(response)
        log_data["estimated_tokens"] = total_chars // 4  # Rough estimate: 1 token ≈ 4 chars

        # Write to file
        with open_private_text(log_file) as f:
            json.dump(log_data, f, indent=2, ensure_ascii=False)

    except Exception as e:
        # Don't let logging errors break the main functionality
        print(f"Warning: Failed to log LLM interaction: {e}")

# Lazy loading for local embedding model
local_embedding_model = None
embedding_model_initialized = False

def get_local_embedding_model():
    """Lazy load the local embedding model"""
    global local_embedding_model, embedding_model_initialized
    
    if not embedding_model_initialized:
        embedding_model_initialized = True
        try:
            from sentence_transformers import SentenceTransformer

            local_embedding_model = SentenceTransformer(EMBEDDING_MODEL)
            print(f"✓ Loaded local embedding model: {EMBEDDING_MODEL} ({CURRENT_EMBEDDING_DIMENSIONS} dimensions)")
        except Exception as e:
            print(f"✗ Failed to load embedding model {EMBEDDING_MODEL}: {e}")
            print("Please install sentence-transformers: pip install sentence-transformers")
            local_embedding_model = None
    
    return local_embedding_model

# Initialize chat client for LLM operations (OpenRouter by default, CHAT_* when configured)
_chat_api_key = get_chat_api_key()
if _chat_api_key:
    openrouter_client = OpenAI(
        api_key=_chat_api_key,
        base_url=get_chat_base_url(),
        timeout=LLM_REQUEST_TIMEOUT
    )
else:
    openrouter_client = None

# Note: Model selection now uses get_current_model() directly to ensure real-time updates

# Simple in-memory cache for embeddings with configurable size
_embedding_cache = {}

ENTITY_CATEGORIES = [
    "people",
    "organizations",
    "technologies",
    "projects",
    "concepts",
    "locations",
    "dates",
]


def _default_entities() -> Dict[str, List[str]]:
    return {category: [] for category in ENTITY_CATEGORIES}


def _normalize_entities(raw_entities: Any) -> Dict[str, List[str]]:
    """Return the canonical entity dictionary shape used in memory metadata."""
    entities = _default_entities()
    if not isinstance(raw_entities, dict):
        return entities

    for category in ENTITY_CATEGORIES:
        values = raw_entities.get(category, [])
        if isinstance(values, list):
            entities[category] = [str(value) for value in values if str(value).strip()]
    return entities


def clean_thought(content, model=None, client=None):
    """Use AI to clean up and improve a thought."""
    if not client:
        return content
    model_to_use = model or get_current_model()
    try:
        return complete(
            client,
            model_to_use,
            [
                {"role": "system", "content": "Clean up and improve this thought while keeping the core meaning intact. Make it clear and well-structured."},
                {"role": "user", "content": content}
            ]
        )
    except Exception:
        return content

def summarize_content(content, model=None, client=None):
    """Summarize content in 2-3 sentences."""
    if not client:
        return "Unable to summarize content."
    model_to_use = model or get_current_model()
    try:
        return complete(
            client,
            model_to_use,
            [
                {"role": "system", "content": "Summarize this content in 2-3 sentences, focusing on the key points."},
                {"role": "user", "content": content}
            ]
        )
    except Exception:
        return "Unable to summarize content."

def get_embedding_for_query(query):
    """Get embedding vector for a search query using local sentence-transformer model."""
    model = get_local_embedding_model()
    if not model:
        return None
    
    # Create cache key from query hash
    cache_key = hashlib.md5(f"query:{EMBEDDING_MODEL}:{query}".encode()).hexdigest()
    
    # Check cache first
    if cache_key in _embedding_cache:
        return _embedding_cache[cache_key]
    
    try:
        # Generate embedding using local model
        embedding = model.encode(query).tolist()
        
        # Cache the result (limit cache size to prevent memory issues)
        if len(_embedding_cache) < EMBEDDING_CACHE_SIZE:
            _embedding_cache[cache_key] = embedding
        
        return embedding
    except Exception as e:
        print(f"Error generating embedding for query: {e}")
        return None

def get_embedding_for_content(
    content: str, 
    client: Optional[Any] = None
) -> Optional[List[float]]:
    """
    Get embedding vector for content using local sentence-transformer model.
    
    Generates semantic embeddings for text content using local sentence-transformers,
    with intelligent caching to improve performance. Used throughout the system
    for semantic search, similarity calculations, and content connections.
    
    Parameters:
        content (str): The text content to generate embeddings for
        client (Optional[Any]): Unused parameter, kept for compatibility
    
    Returns:
        Optional[List[float]]: Vector embedding as a list of floats, or None if
            local model is unavailable or generation fails. Cached results are returned
            for repeated content to improve performance.
    """
    model = get_local_embedding_model()
    if not model:
        return None
    
    # Create cache key from content hash and model
    cache_key = hashlib.md5(f"content:{EMBEDDING_MODEL}:{content}".encode()).hexdigest()
    
    # Check cache first
    if cache_key in _embedding_cache:
        return _embedding_cache[cache_key]
    
    try:
        # Generate embedding using local model
        embedding = model.encode(content).tolist()
        
        # Cache the result (limit cache size to prevent memory issues)
        if len(_embedding_cache) < EMBEDDING_CACHE_SIZE:
            _embedding_cache[cache_key] = embedding
        
        return embedding
    except Exception as e:
        print(f"Error generating embedding for content: {e}")
        return None

def analyze_thoughts(content_list, query, model=None, client=None):
    """Analyze a list of thoughts/content using LLM."""
    if not client:
        return "Could not analyze thoughts: No LLM client."
    model_to_use = model or get_current_model()
    try:
        if isinstance(content_list[0], dict):
            combined_content = "\n\n".join([
                f"[{item.get('command_type', '').upper()}] {item.get('content', '')[:PROJECT_PREVIEW_LENGTH]}" for item in content_list
            ])
        else:
            combined_content = "\n\n".join([str(x)[:PROJECT_PREVIEW_LENGTH] for x in content_list])
        system_prompt = THOUGHT_ANALYSIS_PROMPT
        return complete(
            client,
            model_to_use,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Query: {query}\n\nContent to analyze:\n{combined_content}"}
            ]
        )
    except Exception as e:
        return f"Could not analyze thoughts: {e}"

def generate_weekly_summary(weekly_data, days_back=DEFAULT_WEEKLY_DAYS, model=None, client=None):
    """Generate AI-powered weekly summary from already-fetched weekly_data."""
    if not client:
        return "Could not generate weekly summary: No LLM client."
    
    # Use provided model or fall back to default
    model_to_use = model or get_current_model()
    try:
        if not weekly_data['all_content']:
            return f"No activity found in the last {days_back} days."
        analysis_content = []
        analysis_content.append(f"Weekly Summary (Last {days_back} days)")
        analysis_content.append(f"Total items: {len(weekly_data['all_content'])}")
        analysis_content.append(f"Links: {len(weekly_data['links'])}")
        analysis_content.append(f"Ideas: {len(weekly_data['ideas'])}")
        analysis_content.append(f"Questions: {len(weekly_data['questions'])}")
        analysis_content.append(f"Thoughts: {len(weekly_data['thoughts'])}")
        analysis_content.append(f"Insights: {len(weekly_data.get('insights', []))}")
        analysis_content.append(f"Notes: {len(weekly_data.get('notes', []))}")
        analysis_content.append(f"Goals: {len(weekly_data.get('goals', []))}")
        analysis_content.append("---")
        for item in weekly_data['all_content'][:SYNTHESIS_ITEM_LIMIT]:
            content_type = item['command_type'].upper()
            content_preview = standardize_truncation(item['content'], GENERAL_PREVIEW_LENGTH)
            timestamp = item['timestamp'] if item['timestamp'] else 'Unknown date'
            analysis_content.append(f"[{content_type}] {timestamp}: {content_preview}")
            if item['tags']:
                analysis_content.append(f"Tags: {', '.join(item['tags'])}")
            analysis_content.append("---")
        combined_content = "\n".join(analysis_content)
        system_prompt = WEEKLY_SUMMARY_PROMPT
        return complete(
            client,
            model_to_use,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Analyze this weekly activity:\n{combined_content}"}
            ]
        )
    except Exception as e:
        return f"Could not generate weekly summary: {e}"

def extract_tags(content):
    """Extract manual tags from content and return cleaned content and tags"""
    lines = content.split('\n')
    cleaned_lines = []
    manual_tags = []
    
    for line in lines:
        # Extract tags from this line
        words = line.split()
        cleaned_words = []
        
        for word in words:
            if word.startswith('#'):
                # This is a tag
                tag = word[1:]  # Remove the # symbol
                if tag:  # Only add non-empty tags
                    manual_tags.append(tag)
            else:
                # This is regular content
                cleaned_words.append(word)
        
        # Reconstruct the line without tags
        if cleaned_words:
            cleaned_lines.append(' '.join(cleaned_words))
    
    # Join lines back together
    cleaned_content = '\n'.join(cleaned_lines).strip()
    
    return cleaned_content, manual_tags

def analyze_capture_content(
    content: str, 
    user_hint: Optional[str] = None, 
    model: Optional[str] = None, 
    client: Optional[Any] = None
) -> Dict[str, Any]:
    """
    Comprehensive analysis of captured content to determine type, extract URLs, 
    generate summaries, and categorize all in one LLM call.
    
    The main AI analysis pipeline that intelligently processes any input content.
    Automatically classifies content type, extracts structured data, generates
    relevant tags, and identifies actionable items using a single LLM call for
    efficiency and consistency.
    
    Parameters:
        content (str): The text content to analyze and process
        user_hint (Optional[str]): Optional context hint for better tagging.
            Often used when web search provides additional context.
        model (Optional[str]): AI model name to use for analysis.
            Defaults to current configured model if None.
        client (Optional[Any]): OpenRouter client for LLM operations.
            Uses default client if None.
    
    Returns:
        Dict[str, Any]: Structured analysis results containing:
            - 'type': Content classification (e.g., 'idea', 'task', 'link')
            - 'confidence': Analysis confidence score (0.0-1.0)
            - 'enhanced_content': AI-enhanced version of the content
            - 'summary': Brief summary of the content
            - 'themes': List of relevant tags/themes
            - 'actionable_items': List of extracted todos/tasks
            - 'urls': List of URLs found in the content
    """
    if client is None:
        return {
            'type': 'dump',
            'urls': [],
            'summary': '',
            'themes': [],
            'actionable_items': [],
            'enhanced_content': content,
            'confidence': 0.5
        }
    
    route = get_task_llm_route("CAPTURE_ANALYSIS", client, model)
    if not route.client:
        return {
            'type': 'dump',
            'urls': [],
            'summary': '',
            'themes': [],
            'actionable_items': [],
            'enhanced_content': content,
            'confidence': 0.5
        }
    model_to_use = route.model
    try:
        system_prompt = get_capture_analysis_prompt(user_hint)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": content}
        ]
        result = complete_json(route.client, model_to_use, messages)
        response_content = json.dumps(result)
        log_llm_interaction(
            model=model_to_use,
            messages=messages,
            response=response_content,
            function_name="analyze_capture_content",
            metadata={"user_hint": user_hint}
        )

        # Validate and provide defaults
        valid_types = ['idea', 'ask', 'dump', 'link', 'task', 'reflection', 'research', 'insight', 'note', 'goal', 'observation', 'opinion', 'status', 'exploration']
        if result.get('type') not in valid_types:
            result['type'] = 'dump'
        # Ensure all required fields exist
        result.setdefault('urls', [])
        result.setdefault('enhanced_content', content)
        result.setdefault('summary', '')
        result.setdefault('themes', [])
        result.setdefault('actionable_items', [])
        result['entities'] = _normalize_entities(result.get('entities'))
        result.setdefault('confidence', 0.5)

        # FALLBACK: If AI didn't extract URLs, use regex detection
        # This handles models that don't reliably follow JSON format
        if not result['urls']:
            import re
            # Robust URL regex pattern
            url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
            found_urls = re.findall(url_pattern, content)
            if found_urls:
                result['urls'] = found_urls
                # If we found URLs and type is 'dump', upgrade to 'link'
                if result['type'] == 'dump':
                    result['type'] = 'link'
                    result['confidence'] = 0.7  # Moderate confidence for regex detection
        # Convert actionable_items to proper format if they're just strings
        if result['actionable_items'] and isinstance(result['actionable_items'][0], str):
            # Convert simple strings to structured format
            structured_items = []
            for item in result['actionable_items']:
                structured_items.append({
                    "action": item,
                    "context": "",
                    "priority": "medium",
                    "time_sensitive": False,
                    "project": ""
                })
            result['actionable_items'] = structured_items
        
        # --- URL extraction fallback ---
        # If AI didn't extract URLs, use regex as fallback  
        if not result.get('urls', []):
            url_pattern = r'https?://[^\s]+'
            found_urls = re.findall(url_pattern, content)
            if found_urls:
                result['urls'] = found_urls
        
        # --- Enhanced Post-processing heuristics ---
        content_stripped = content.strip().lower()
        content_original = content.strip()

        # If type is 'dump' but content fits a more specific category, override it
        if result['type'] == 'dump':
            # Check for question patterns → 'ask'
            if content_original.endswith('?') or re.match(r'^(who|what|when|where|why|how)\b', content_stripped, re.IGNORECASE):
                result['type'] = 'ask'

            # Check for status/progress patterns → 'status'
            elif any(pattern in content_stripped for pattern in [
                'working on', 'still working', 'currently working', 'been working',
                'just finished', 'just completed', 'implemented', 'added', 'changed to',
                'now using', 'switched to', 'migrated to', 'updated to'
            ]):
                result['type'] = 'status'

            # Check for exploration/wondering patterns → 'exploration'
            elif any(pattern in content_stripped for pattern in [
                'wondering', 'what if', 'thinking about', 'considering',
                'need to figure out', 'trying to decide', 'exploring',
                'what apps', 'what should i', 'how might i', 'could i'
            ]):
                result['type'] = 'exploration'

            # Check for opinion/commentary patterns → 'opinion'
            elif any(pattern in content_stripped for pattern in [
                'i like', 'i love', 'i hate', 'i think', 'i believe',
                'i agree', 'i disagree', 'in my opinion', 'my take',
                'interesting that', 'i find it', 'really fuck', 'amazing that'
            ]):
                result['type'] = 'opinion'

            # Check for observation patterns → 'observation'
            elif any(pattern in content_stripped for pattern in [
                "i've noticed", "i noticed", "it seems", "appears that",
                "looks like", "the internet is", "people are", "everyone is",
                "i got sidetracked", "this morning", "today i"
            ]):
                result['type'] = 'observation'

            # Check for todo/task patterns → 'task'
            else:
                todo_patterns = [
                    r'remind me to', r'reminder to', r'i need to', r'i should', r'check out', r'look at',
                    r'do this for', r'work on', r'don\'t forget to', r'remember to', r'for my project', r'for my essay',
                    r'take a look at', r'review', r'set up', r'configure', r'call', r'email', r'message',
                    r'buy', r'get', r'purchase', r'schedule', r'book', r'make appointment', r'finish', r'complete', r'wrap up', r'start', r'begin', r'initiate'
                ]
                for pat in todo_patterns:
                    if re.search(pat, content_stripped, re.IGNORECASE):
                        result['type'] = 'task'
                        break
        return result
    except Exception as e:
        # Fallback on any error (including JSON parsing failures)
        import re

        # Try to extract URLs even if JSON parsing failed
        url_pattern = r'https?://[^\s<>"{}|\\^`\[\]]+'
        found_urls = re.findall(url_pattern, content)

        # If we found URLs, classify as 'link' instead of 'dump'
        content_type = 'link' if found_urls else 'dump'
        confidence = 0.6 if found_urls else 0.3

        return {
            'type': content_type,
            'urls': found_urls,
            'summary': '',
            'themes': [],
            'actionable_items': [],
            'enhanced_content': content,
            'confidence': confidence,
            'entities': _default_entities(),
            'error': str(e)
        }

def process_content_with_ai(
    content,
    user_id,
    command_type,
    metadata=None,
    model=None,
    client=None,
    embedding_client=None,
    markdown_extra=None,
    precomputed_analysis=None,
):
    """
    Process and save content to the database with AI analysis.
    Returns: (memory_id, tags, detected_category, themes, actionable_items, enhanced_metadata)
    """
    from .database import db
    
    # Extract manual tags from content first
    cleaned_content, manual_tags = extract_tags(content)
    
    # Use comprehensive AI analysis unless the caller already did it.
    analysis = precomputed_analysis or analyze_capture_content(cleaned_content or content, model=model, client=client)
    
    # Extract themes, actionable items, and entities from analysis
    themes = analysis.get('themes', [])
    actionable_items = analysis.get('actionable_items', [])
    entities = analysis.get('entities', {})
    
    # Use focused themes if available in metadata (for web-fetched links)
    if metadata and 'focused_themes' in metadata:
        themes = metadata['focused_themes']
        # For focused themes, skip entity extraction to avoid tag explosion
        entity_tags = []
    else:
        # Combine all tags (manual + themes + entity terms) - normal behavior
        entity_tags = []
        for entity_list in entities.values():
            entity_tags.extend(entity_list)
    
    # Combine and clean tags
    all_tags = manual_tags + themes + entity_tags
    
    # Clean and filter tags
    cleaned_tags = []
    for tag in all_tags:
        if isinstance(tag, str):
            # Remove problematic characters and clean
            clean_tag = tag.strip().rstrip(',').strip()
            # Filter out very short, numeric-only, or problematic tags
            if (len(clean_tag) > 1 and 
                clean_tag not in ['#', ',', ':', ';'] and 
                not clean_tag.isdigit() and
                clean_tag.lower() not in cleaned_tags):
                cleaned_tags.append(clean_tag.lower())
    
    final_tags = cleaned_tags[:8]  # Limit to 8 most relevant tags
    
    # Enhance metadata with analysis results
    enhanced_metadata = metadata or {}
    enhanced_metadata.update({
        'ai_confidence': analysis.get('confidence', 0.5),
        'ai_summary': analysis.get('summary', ''),
        'themes': themes,
        'actionable_items': actionable_items,
        'entities': entities,
        'enhanced_content': analysis.get('enhanced_content', content)
    })
    
    # Save to database
    try:
        # Determine final command type: prioritize explicit commands (link, task, etc.) over AI detection
        # If command_type is explicitly 'link', always use 'link' regardless of AI analysis
        final_command_type = command_type if command_type == 'link' else analysis.get('type', command_type)

        # For links, always save the provided content (old format)
        save_content = content if final_command_type == 'link' else analysis.get('enhanced_content', content)
        memory_id = db.save_memory(
            content=save_content,
            user_id=user_id,
            command_type=final_command_type,
            tags=final_tags,
            metadata=enhanced_metadata
        )
        
        # Generate and save embedding using local model
        embedding = get_embedding_for_content(content)
        if embedding and memory_id:
            db.save_embedding(memory_id, embedding)
        
        # Save to markdown if enabled (optionally include extra export content)
        try:
            from .markdown_export import save_memory_to_markdown
            
            # Get the timestamp from the saved memory
            saved_memory = db.get_memory_by_id(memory_id, user_id)
            timestamp = saved_memory['timestamp'] if saved_memory else None

            export_content = save_content
            if markdown_extra:
                export_content = f"{save_content}\n\n---\nFull Content:\n{markdown_extra}"
            
            save_memory_to_markdown(
                export_content, 
                analysis.get('type', command_type), 
                final_tags, 
                enhanced_metadata, 
                timestamp,
                user_id
            )
        except Exception as e:
            # Don't fail the memory save if markdown export fails
            print(f"Note: Markdown export failed: {e}")
        
        return memory_id, final_tags, analysis.get('type', command_type), themes, actionable_items, enhanced_metadata
        
    except Exception as e:
        # Fallback: save without enhancement
        memory_id = db.save_memory(
            content=content,
            user_id=user_id,
            command_type=command_type,
            tags=manual_tags,
            metadata=metadata
        )
        return memory_id, manual_tags, command_type, [], [], metadata or {}

def extract_todos_from_content(content, model=None, client=None):
    """
    Extract structured todos from content using AI.
    Returns a list of todo dictionaries with enhanced information.
    """
    if not client:
        return []
    
    route = get_task_llm_route("TODO_EXTRACTION", client, model)
    if not route.client:
        return []
    model_to_use = route.model
    try:
        system_prompt = TODO_EXTRACTION_PROMPT

        result = complete_json(
            route.client,
            model_to_use,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ]
        )
        return result.get('todos', [])
        
    except Exception as e:
        return []

def synthesize_notes(content_list, topic, model=None, client=None):
    """Uses an LLM to synthesize a list of notes into a coherent document."""
    if not client:
        return "Could not synthesize notes: No LLM client."
    
    # Use provided model or fall back to default
    model_to_use = model or get_current_model()
    try:
        if isinstance(content_list[0], dict):
            notes_for_prompt = []
            for item in content_list[:SYNTHESIS_ITEM_LIMIT]:  # Limit to configurable items for synthesis
                content_type = item.get('command_type', 'unknown')
                content = item.get('content', '')
                tags = item.get('tags', [])
                notes_for_prompt.append(f"[{content_type.upper()}] {content}")
                if tags:
                    notes_for_prompt.append(f"Tags: {', '.join(tags)}")
                notes_for_prompt.append("---")
            combined_notes = "\n".join(notes_for_prompt)
        else:
            combined_notes = "\n\n".join(content_list[:SYNTHESIS_ITEM_LIMIT])
        
        system_prompt = SYNTHESIZE_NOTES_PROMPT
        
        return complete(
            client,
            model_to_use,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": f"Synthesize the following notes on the topic of '{topic}':\n\n{combined_notes}"}
            ]
        )
    except Exception as e:
        return f"Could not synthesize notes: {e}"

def extract_todos_from_multiple_contents(contents, model=None, client=None):
    """
    Extract todos from multiple pieces of content in a single API call.
    Returns a list of todo dictionaries with source content info.
    """
    if not client or not contents:
        return []
    
    route = get_task_llm_route("TODO_EXTRACTION", client, model)
    if not route.client:
        return []
    model_to_use = route.model
    try:
        # Prepare content for batch processing
        content_items = []
        for i, content in enumerate(contents):
            content_items.append(f"Content {i+1}:\n{content}\n---")
        combined_content = "\n".join(content_items)
        system_prompt = MULTI_TODO_EXTRACTION_PROMPT
        result = complete_json(
            route.client,
            model_to_use,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": combined_content}
            ]
        )
        todos = result.get('todos', [])
        # Add source content information
        for todo in todos:
            source_index = todo.get('source_index', 1) - 1  # Convert to 0-based index
            if 0 <= source_index < len(contents):
                todo['source_content'] = contents[source_index]
        return todos
    except Exception as e:
        return []

def extract_structured_entities(
    content: str, 
    model: Optional[str] = None, 
    client: Optional[Any] = None
) -> Dict[str, List[str]]:
    """
    Extract structured entities from content using LLM with caching.
    
    Uses AI to identify and categorize structured entities within text content,
    including people, organizations, technologies, projects, concepts, locations,
    and dates. Results are cached to improve performance for repeated content.
    
    Parameters:
        content (str): The text content to analyze for entities
        model (Optional[str]): Legacy model hint for older callers.
            Entity extraction now uses ENTITY_EXTRACTION_* routing config and
            defaults to the active chat model when no route override is set.
        client (Optional[Any]): OpenRouter client for LLM operations.
            Returns empty categories if None.
    
    Returns:
        Dict[str, List[str]]: Dictionary with entity categories as keys and
            lists of extracted entity names as values. Categories include:
            'people', 'organizations', 'technologies', 'projects', 'concepts',
            'locations', 'dates'. Returns empty lists for all categories
            if client is unavailable.
    """
    route = get_task_llm_route("ENTITY_EXTRACTION", client)
    if not route.client:
        return _default_entities()
    
    # Create cache key from content hash and route so provider/model changes do not reuse stale results
    cache_key = hashlib.md5(f"entities:{route.provider}:{route.model}:{content}".encode()).hexdigest()
    
    # Check cache first - reuse existing embedding cache for simplicity
    if cache_key in _embedding_cache:
        return _embedding_cache[cache_key]
    
    model_to_use = route.model
    try:
        system_prompt = ENTITY_EXTRACTION_PROMPT

        result = complete_json(
            route.client,
            model_to_use,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": content}
            ]
        )

        # Validate structure and provide defaults
        entities = _normalize_entities(result)
        
        # Cache the result (limit cache size)
        if len(_embedding_cache) < EMBEDDING_CACHE_SIZE:
            _embedding_cache[cache_key] = entities
        
        return entities
        
    except Exception as e:
        # Return empty structure on error
        return {
            "people": [],
            "organizations": [],
            "technologies": [],
            "projects": [],
            "concepts": [],
            "locations": [],
            "dates": []
        }

def extract_temporal_intent_ai(query, model=None, client=None):
    """
    AI fallback for complex temporal patterns.
    This is called by time.py when pattern matching fails.
    """
    if not client:
        return None

    route = get_task_llm_route("TEMPORAL_INTENT", client, model)
    if not route.client:
        return None
    model_to_use = route.model
    try:
        current_datetime = datetime.now()
        system_prompt = get_temporal_intent_prompt(current_datetime)

        result = complete_json(
            route.client,
            model_to_use,
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": query}
            ]
        )

        # Validate structure and provide defaults
        temporal_intent = {
            "has_temporal_intent": result.get("has_temporal_intent", False),
            "start_date": result.get("start_date"),
            "end_date": result.get("end_date"),
            "temporal_context": result.get("temporal_context"),
            "query_without_temporal": result.get("query_without_temporal", query),
            "confidence": result.get("confidence", 0.5)
        }
        
        return temporal_intent
        
    except Exception as e:
        # Return no temporal intent on error
        return {
            "has_temporal_intent": False,
            "start_date": None,
            "end_date": None, 
            "temporal_context": None,
            "query_without_temporal": query,
            "confidence": 0.0,
            "error": str(e)
        }

def migrate_embeddings_to_local(progress_callback=None):
    """
    Migrate all existing embeddings to use local sentence-transformer model.
    Clears existing embeddings and regenerates them with the new local model.
    
    Parameters:
        progress_callback (Optional[callable]): Function to call with progress updates
            
    Returns:
        Dict[str, Any]: Migration results with counts and any errors
    """
    from .database import db
    
    model = get_local_embedding_model()
    if not model:
        return {
            "success": False,
            "error": f"Local embedding model '{EMBEDDING_MODEL}' not available",
            "total_memories": 0,
            "migrated": 0,
            "failed": 0
        }
    
    try:
        # Get all memories that need embeddings
        all_memories = db.get_all_memories_for_migration()
        total_memories = len(all_memories)
        
        if progress_callback:
            progress_callback(f"Starting migration of {total_memories} memories to local embeddings...")
        
        # Clear existing embeddings
        db.clear_all_embeddings()
        
        if progress_callback:
            progress_callback("Cleared existing embeddings. Regenerating with local model...")
        
        migrated = 0
        failed = 0
        
        for i, memory in enumerate(all_memories):
            try:
                # Generate new embedding with local model
                embedding = get_embedding_for_content(memory['content'])
                
                if embedding:
                    db.save_embedding(memory['id'], embedding)
                    migrated += 1
                else:
                    failed += 1
                    
                # Progress update every 10 items
                if progress_callback and (i + 1) % 10 == 0:
                    progress_callback(f"Processed {i + 1}/{total_memories} memories...")
                    
            except Exception as e:
                failed += 1
                print(f"Failed to migrate memory {memory['id']}: {e}")
        
        result = {
            "success": True,
            "total_memories": total_memories,
            "migrated": migrated,
            "failed": failed,
            "model": EMBEDDING_MODEL,
            "dimensions": CURRENT_EMBEDDING_DIMENSIONS
        }
        
        if progress_callback:
            progress_callback(f"Migration complete! Migrated: {migrated}, Failed: {failed}")
        
        return result
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "total_memories": 0,
            "migrated": 0,
            "failed": 0
        }

def validate_local_embedding_setup():
    """
    Validate that local embedding model is properly loaded and functional.
    
    Returns:
        Dict[str, Any]: Validation results with model info and test results
    """
    validation_result = {
        "model_loaded": False,
        "model_name": EMBEDDING_MODEL,
        "expected_dimensions": CURRENT_EMBEDDING_DIMENSIONS,
        "actual_dimensions": None,
        "test_embedding": False,
        "error": None
    }
    
    try:
        model = get_local_embedding_model()
        if not model:
            validation_result["error"] = f"Local embedding model '{EMBEDDING_MODEL}' not loaded"
            return validation_result
        
        validation_result["model_loaded"] = True
        
        # Test embedding generation
        test_text = "This is a test sentence for embedding validation."
        test_embedding = get_embedding_for_content(test_text)
        
        if test_embedding:
            validation_result["actual_dimensions"] = len(test_embedding)
            validation_result["test_embedding"] = True
            
            # Check if dimensions match expected
            if validation_result["actual_dimensions"] != validation_result["expected_dimensions"]:
                validation_result["error"] = f"Dimension mismatch: expected {validation_result['expected_dimensions']}, got {validation_result['actual_dimensions']}"
        else:
            validation_result["error"] = "Failed to generate test embedding"
            
    except Exception as e:
        validation_result["error"] = str(e)
    
    return validation_result

# Add more AI-related functions as needed...
