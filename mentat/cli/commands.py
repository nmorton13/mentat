"""
MENTAT Command Handlers
Contains all business logic for individual commands
"""

import json
import re
from typing import Optional, Tuple, Dict, Any, List, Union, Callable
from collections import defaultdict, Counter

import sys
import os

from mentat.core.database import MemoryDatabase
from mentat.core.ai import (
    analyze_capture_content, analyze_thoughts,
    generate_weekly_summary,
    get_embedding_for_content,
    process_content_with_ai,
    synthesize_notes, extract_structured_entities
)
from mentat.core.llm import complete, complete_online
from mentat.chat.enhanced_chat import EnhancedChatSystem
from mentat.cli.display import (
    console, make_urls_clickable,
    format_content_with_markdown, render_markdown_to_panel,
    should_use_markdown_rendering, format_metadata_display,
    create_standard_panel, print_tool_reply, show_thinking_spinner,
    show_contextual_commands
)
from mentat.core.utils import standardize_truncation, parse_item_metadata
from mentat.core.config import (
    SEARCH_RESULTS_K, PROJECT_ANALYSIS_K, SYNTHESIS_K, SEMANTIC_SEARCH_MIN_SIMILARITY,
    CONNECTION_SURFACING_K, CONNECTION_DISPLAY_LIMIT, SEARCH_PREVIEW_LENGTH, PROJECT_PREVIEW_LENGTH,
    DEFAULT_SUMMARY_DAYS, DEFAULT_MEMORY_LIMIT, STRONG_SEMANTIC_SIMILARITY_THRESHOLD,
    WEB_SEARCH_ENTITY_FREQUENCY_THRESHOLD, WEB_CONTEXT_SUMMARY_LENGTH, ENTITY_FRESHNESS_DAYS,
    LINKS_DISPLAY_LIMIT, SEARCH_RESULTS_PER_SECTION, WEAK_SEMANTIC_FALLBACK_LIMIT,
    CONNECTION_PREVIEW_LENGTH, TIMELINE_CONTENT_LENGTH, ENTITY_SEARCH_LIMIT,
    TOP_ENTITIES_PER_CATEGORY, TIMELINE_RECENT_ITEMS_LIMIT,
    REFERENCE_RELATED_MEMORIES_LIMIT, PERSONAL_CONTEXT_MEMORIES_LIMIT,
    REFERENCE_EXPLANATION_MAX_TOKENS
)


def handle_view_ai_reference(
    reference: Dict[str, Any],
    item_num: int,
    user_id: str,
    current_model: str,
    db: Any,
    openrouter_client: Any,
    global_enhanced_chat: Any
) -> None:
    """
    Handle viewing an AI reference with concept tree exploration.

    This function generates a comprehensive explanation for an AI reference
    and displays a hierarchical concept tree for further exploration.
    Extracted to avoid code duplication in the /view command.

    Args:
        reference: The AI reference dictionary from enhanced chat
        item_num: The reference number being viewed
        user_id: Current user ID
        current_model: LLM model to use
        db: Database instance
        openrouter_client: OpenRouter API client
        global_enhanced_chat: Enhanced chat system instance
    """
    from mentat.cli.display import (
        console, show_thinking_spinner, should_use_markdown_rendering,
        render_markdown_to_panel, format_content_with_markdown,
        create_standard_panel
    )

    # Generate comprehensive explanation using existing web search
    with show_thinking_spinner("🔍 Researching and analyzing...") as (progress, task):
        explanation = global_enhanced_chat.generate_reference_explanation(reference, user_id, current_model)

    # Display the reference explanation with enhanced markdown rendering
    if should_use_markdown_rendering(explanation):
        panel = render_markdown_to_panel(
            explanation,
            f"🔗 Reference {item_num}: {reference['topic']}",
            None,
            "bright_blue"
        )
    else:
        formatted_explanation = format_content_with_markdown(explanation)
        panel = create_standard_panel(
            formatted_explanation,
            f"🔗 Reference {item_num}: {reference['topic']}",
            None,
            "bright_blue"
        )
    console.print(panel)

    # Add full hierarchical concept tree exploration
    try:
        from mentat.concepts.concept_integration import (
            ConceptIntegrationManager,
            build_full_hierarchical_concept_tree
        )
        integration_manager = ConceptIntegrationManager(db, openrouter_client)

        # Build full hierarchical concept tree using config values
        concept_tree = build_full_hierarchical_concept_tree(
            reference['topic'], user_id, db, openrouter_client
        )

        if concept_tree and concept_tree.get('concepts'):
            # Clear existing references when showing concept tree
            # This ensures concept numbers don't conflict with chat references
            if global_enhanced_chat:
                global_enhanced_chat.clear_references()

            # Display the hierarchical concept tree
            if concept_tree.get('hierarchical'):
                # Use new hierarchical formatting
                concept_display = integration_manager.format_hierarchical_concept_tree(concept_tree)
            else:
                # Fallback to regular formatting if hierarchy failed
                concept_display = integration_manager.format_concept_web_display(concept_tree, depth_level=2)

            console.print()  # Add spacing
            formatted_concept_display = format_content_with_markdown(concept_display)
            concept_panel = create_standard_panel(formatted_concept_display, "🌳 Related Concepts to Explore", None, "bright_cyan")
            console.print(concept_panel)

            # Add all concepts (main + sub) as explorable references to enhanced chat
            if global_enhanced_chat:
                concept_counter = 1
                for main_concept in concept_tree['concepts']:
                    # Add main concept
                    global_enhanced_chat.add_reference(
                        topic=main_concept['name'],
                        context=f"Main concept related to '{reference['topic']}'",
                        personal_context=main_concept.get('description', '')
                    )
                    concept_counter += 1

                    # Add sub-concepts
                    for sub_concept in main_concept.get('sub_concepts', []):
                        global_enhanced_chat.add_reference(
                            topic=sub_concept['name'],
                            context=f"Sub-concept under '{main_concept['name']}'",
                            personal_context=sub_concept.get('description', '')
                        )
                        concept_counter += 1
    except ImportError as import_error:
        console.print(f"[dim yellow]Note: Concept system not available: {import_error}[/dim yellow]")
    except Exception as concept_error:
        console.print(f"[dim yellow]Note: Concept web generation failed: {concept_error}[/dim yellow]")


def enrich_content_with_web_search(
    content: str,
    user_id: str,
    current_model: str,
    openrouter_client: Optional[Any],
    db: Any
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Enrich content using OpenRouter's web search server tool to add context for unknown entities.

    Extracts entities from the content, filters for novel entities based on frequency in the database,
    and performs a web search to retrieve definitions or additional context using OpenRouter's web-backed completion wrapper.

    Parameters:
        content (str): The original text content to enrich.
        user_id (str): Identifier for the user, used to check entity frequency.
        current_model (str): The name of the current AI model used for entity extraction and search.
        openrouter_client (Optional[Any]): Client instance to interact with OpenRouter API. 
            If None, web search is skipped.
        db (Any): Database interface to check entity frequency.

    Returns:
        Tuple[str, Optional[Dict[str, Any]]]:
            - The original content (str).
            - A dictionary with web enrichment metadata (e.g., source counts, top domain, summary) or None if enrichment did not happen.
    """
    try:
        # First, extract entities from the content to understand what we might need to search for
        entities = extract_structured_entities(content, model=current_model, client=openrouter_client)
        
        # Check if we have any entities worth searching for
        searchable_entities = []
        for category, entity_list in entities.items():
            if category in ['concepts', 'people', 'organizations', 'technologies', 'projects']:
                searchable_entities.extend(entity_list)
        
        if not searchable_entities:
            console.print("[dim]📝 No entities found that need web context[/dim]")
            return content, None
        
        # Smart freshness check: search for novel entities OR stale entities based on category
        entity_frequencies, novel_entities = db.check_entity_frequency_with_freshness(
            user_id, searchable_entities, entities, threshold=WEB_SEARCH_ENTITY_FREQUENCY_THRESHOLD
        )
        
        if not novel_entities:
            console.print(f"[dim]📝 All entities are fresh and known: {', '.join(searchable_entities)}[/dim]")
            return content, None
        elif len(novel_entities) < len(searchable_entities):
            skipped = [entity for entity in searchable_entities if entity not in novel_entities]
            console.print(f"[dim]⚡ Skipping fresh entities: {', '.join(skipped)}[/dim]")
        
        # Show what we're searching and why
        novel_count = sum(1 for entity in novel_entities if entity_frequencies.get(entity, 0) < WEB_SEARCH_ENTITY_FREQUENCY_THRESHOLD)
        stale_count = len(novel_entities) - novel_count
        
        search_reason = []
        if novel_count > 0:
            search_reason.append(f"{novel_count} novel")
        if stale_count > 0:
            search_reason.append(f"{stale_count} stale")
        
        reason_str = " + ".join(search_reason) if search_reason else "novel"
        console.print(f"🔍 [cyan]Enriching with web context ({reason_str}): {', '.join(novel_entities[:3])}{'...' if len(novel_entities) > 3 else ''}[/cyan]")
        
        # Use OpenRouter's web search server tool to get context
        if not openrouter_client:
            console.print("[yellow]⚠️ OpenRouter client not available for web search[/yellow]")
            return content, None
        
        # Create a concise search prompt
        search_prompt = f"""Provide brief definitions for: {', '.join(novel_entities)}

Keep each definition to 1-2 sentences for content tagging purposes."""
        
        online_result = complete_online(
            openrouter_client,
            current_model,
            [{"role": "user", "content": search_prompt}]
        )
        response = online_result.response
        web_enhanced_response = online_result.text
        
        # Extract minimal web context metadata for audit purposes
        source_count = 0
        top_domain = None
        
        if hasattr(response.choices[0].message, 'annotations') and response.choices[0].message.annotations:
            domains = []
            for annotation in response.choices[0].message.annotations:
                if annotation.type == 'url_citation':
                    citation = annotation.url_citation
                    # Extract clean domain name
                    domain = citation.url.split('/')[2] if '/' in citation.url else citation.url
                    domains.append(domain)
                    source_count += 1
            
            # Get the most common domain as "top_domain" 
            if domains:
                top_domain = max(set(domains), key=domains.count)
            
            console.print(f"✅ [green]Found context from {source_count} sources[/green]")
            # Return original content but with web context for enhanced tagging
            return content, {
                'web_enriched': True,
                'source_count': source_count,
                'top_domain': top_domain,
                'web_context_summary': web_enhanced_response[:WEB_CONTEXT_SUMMARY_LENGTH]  # Brief summary for tagging
            }
        else:
            # Even without structured citations, the response might contain useful context
            console.print("✅ [green]Enhanced with web intelligence[/green]")
            return content, {
                'web_enriched': True,
                'source_count': 1,
                'top_domain': 'web_search',
                'web_context_summary': web_enhanced_response[:WEB_CONTEXT_SUMMARY_LENGTH]
            }
            
    except Exception as e:
        console.print(f"[yellow]⚠️ Web enrichment failed: {e}[/yellow]")
        return content, None

def semantic_search(
    user_id: str, 
    query: str, 
    k: int, 
    db: Any, 
    openai_client: Optional[Any]
) -> List[Dict[str, Any]]:
    """
    Semantic search helper for CLI commands.
    
    Performs semantic similarity search using embeddings to find memories
    that are conceptually related to the query, even if they don't share keywords.
    
    Parameters:
        user_id (str): Identifier for the user whose memories to search
        query (str): The search query text to find similar content
        k (int): Maximum number of results to return
        db (Any): Database interface for accessing stored memories
        openai_client (Optional[Any]): OpenAI client for generating embeddings.
            If None, semantic search will be skipped.
    
    Returns:
        List[Dict[str, Any]]: List of memory dictionaries containing content,
            metadata, and similarity scores. Empty list if no matches found.
    """
    return db.semantic_search(
        user_id, query, k, min_similarity=SEMANTIC_SEARCH_MIN_SIMILARITY,
        get_embedding_func=lambda q: get_embedding_for_content(q, client=openai_client)
    )

def save_memory(
    content: str, 
    user_id: str, 
    command_type: str, 
    tags: List[str], 
    metadata: Dict[str, Any], 
    db: Any, 
    openai_client: Optional[Any]
) -> Optional[int]:
    """
    Save memory to database with embedding generation.
    
    Stores a memory in the database and generates an embedding for semantic search.
    This is the core persistence function used by all capture operations.
    
    Parameters:
        content (str): The text content to store
        user_id (str): Identifier for the user saving the memory
        command_type (str): Type classification (e.g., 'idea', 'task', 'link')
        tags (List[str]): List of tags/themes associated with the content
        metadata (Dict[str, Any]): Additional structured data (entities, etc.)
        db (Any): Database interface for storage operations
        openai_client (Optional[Any]): OpenAI client for embedding generation.
            If None, content is saved without semantic search capability.
    
    Returns:
        Optional[int]: Database ID of the saved memory, or None if save failed
    """
    try:
        # Save the core memory record to database
        memory_id = db.save_memory(content, user_id, command_type, tags, metadata)
        
        # Generate and save embedding for semantic search capability
        if openai_client:
            try:
                embedding = get_embedding_for_content(content, client=openai_client)
                if embedding:
                    db.save_embedding(memory_id, embedding)
            except Exception as e:
                console.print(f"[yellow]Warning: Could not generate embedding: {e}[/yellow]")
        
        # Automatically save to markdown if enabled
        try:
            from mentat.core.markdown_export import save_memory_to_markdown
            
            # Get the timestamp from the saved memory
            saved_memory = db.get_memory_by_id(memory_id, user_id)
            timestamp = saved_memory['timestamp'] if saved_memory else None
            
            save_memory_to_markdown(content, command_type, tags, metadata, timestamp, user_id)
        except Exception as e:
            # Don't fail the memory save if markdown export fails
            console.print(f"[dim yellow]Note: Markdown export failed: {e}[/dim yellow]")
        
        return memory_id
    except Exception as e:
        console.print(f"[red]Error saving memory: {e}[/red]")
        return None

def generate_connection_explanation(new_content_tags: List[str], new_content_entities: Dict[str, List[str]],
                                   connected_memories: List[Dict[str, Any]], shared_entities: Optional[List[str]] = None) -> str:
    """
    Generate a natural language explanation for why memories are connected.
    Uses rule-based analysis of tags, entities, and content types without LLM calls.

    Parameters:
        new_content_tags (List[str]): Tags from the newly captured content
        new_content_entities (Dict[str, List[str]]): Entities extracted from new content
        connected_memories (List[Dict[str, Any]]): List of connected memory dictionaries
        shared_entities (Optional[List[str]]): Specific entities that connect them (for entity-based connections)

    Returns:
        str: Natural language explanation of the connection
    """
    # Collect all tags from connected memories
    all_connected_tags = []
    all_connected_entities = {}

    for mem in connected_memories:
        # Parse tags
        if mem.get('tags'):
            tags_data = mem['tags']
            if isinstance(tags_data, str):
                tags = [t.strip() for t in tags_data.split(',') if t.strip()]
                all_connected_tags.extend(tags)
            elif isinstance(tags_data, list):
                all_connected_tags.extend(tags_data)

        # Parse entities from metadata
        if mem.get('metadata'):
            try:
                if isinstance(mem['metadata'], str):
                    metadata = json.loads(mem['metadata'])
                else:
                    metadata = mem['metadata']

                if 'entities' in metadata:
                    for category, entities in metadata['entities'].items():
                        if category not in all_connected_entities:
                            all_connected_entities[category] = []
                        all_connected_entities[category].extend(entities)
            except:
                pass

    # Find overlapping themes
    overlapping_tags = set(new_content_tags) & set(all_connected_tags)

    # Find overlapping entities across all categories
    overlapping_entities_by_category = {}
    if new_content_entities:
        for category, entities in new_content_entities.items():
            if category in all_connected_entities:
                overlap = set(entities) & set(all_connected_entities[category])
                if overlap:
                    overlapping_entities_by_category[category] = list(overlap)

    # Build explanation based on what we found
    explanation_parts = []

    # If specific shared entities were provided (entity-based connection), use those
    if shared_entities:
        explanation_parts.append(', '.join(shared_entities[:3]))
    else:
        # Otherwise, build from overlapping data
        if overlapping_entities_by_category:
            # Flatten all overlapping entities with category context
            entity_mentions = []
            for category, entities in overlapping_entities_by_category.items():
                entity_mentions.extend(entities[:2])  # Take top 2 per category
            if entity_mentions:
                explanation_parts.extend(entity_mentions[:4])  # Max 4 entities

        if overlapping_tags:
            # Add top tags
            tag_list = list(overlapping_tags)[:3]  # Max 3 tags
            explanation_parts.extend(tag_list)

    # Generate natural language
    if explanation_parts:
        if len(explanation_parts) == 1:
            return f"they share the theme: {explanation_parts[0]}"
        elif len(explanation_parts) == 2:
            return f"they share themes around {explanation_parts[0]} and {explanation_parts[1]}"
        else:
            themes = ', '.join(explanation_parts[:-1])
            return f"they share themes around {themes}, and {explanation_parts[-1]}"
    else:
        # Fallback if no obvious overlap
        return "they have similar semantic meaning"

def handle_capture(
    content: str, 
    user_id: str, 
    enable_web_search: bool, 
    current_model: str, 
    openrouter_client: Optional[Any], 
    openai_client: Optional[Any], 
    db: Any, 
    last_displayed_items: List[Dict[str, Any]],
    source_info: Optional[Dict[str, Any]] = None
) -> None:
    """
    Handle /capture command with advanced analysis and saving.
    
    The primary content capture workflow that intelligently analyzes, categorizes,
    and enriches any input using AI. Includes optional web search for context
    enhancement and automatic connection discovery with existing memories.
    
    Parameters:
        content (str): The text content to capture and analyze
        user_id (str): Identifier for the user capturing the content
        enable_web_search (bool): Whether to use web search for context enrichment
        current_model (str): Name of the AI model to use for analysis
        openrouter_client (Optional[Any]): Client for LLM operations and web search.
            If None, analysis capabilities are limited.
        openai_client (Optional[Any]): Client for embedding generation.
            If None, semantic connections cannot be found.
        db (Any): Database interface for storage and retrieval operations
        last_displayed_items (List[Dict[str, Any]]): Mutable list to store results
            for the /view command functionality
    
    Returns:
        None: Outputs results directly to console and updates last_displayed_items
    """
    
    # Web enrichment phase (if enabled)
    web_context_metadata = None
    if enable_web_search:
        content, web_context_metadata = enrich_content_with_web_search(content, user_id, current_model, openrouter_client, db)
    
    console.print("🧠 [cyan]Analyzing your content...[/cyan]")

    # Use the comprehensive analysis function with OpenRouter client if available
    # If we have web context, provide it as a hint for better tagging
    web_hint = None
    if web_context_metadata and web_context_metadata.get('web_context_summary'):
        web_hint = f"Context for better tagging: {web_context_metadata['web_context_summary']}"
    
    analysis = analyze_capture_content(content, user_hint=web_hint, model=current_model, client=openrouter_client)

    # Build results text for display
    results_text = f"""
[bold green]✅ Captured as {analysis['type'].upper()}[/bold green] (confidence: {analysis['confidence']:.1%})

[bold]Content Type:[/bold] {analysis['type'].title()}
[bold]Confidence:[/bold] {analysis['confidence']:.1%}
"""
    if analysis['enhanced_content'] != content:
        formatted_enhanced = format_content_with_markdown(analysis['enhanced_content'])
        results_text += f"\n[bold]Enhanced Content:[/bold]\n{formatted_enhanced}\n"
    if analysis['summary']:
        formatted_summary = format_content_with_markdown(analysis['summary'])
        results_text += f"\n[bold]Summary:[/bold] {formatted_summary}\n"
    if analysis['themes']:
        results_text += f"\n[bold]Themes:[/bold] {', '.join(analysis['themes'])}\n"
    if analysis['actionable_items']:
        results_text += f"\n[bold]Actionable Items:[/bold]\n"
        for item in analysis['actionable_items']:
            if isinstance(item, dict):
                action = item.get('action', str(item))
                priority = item.get('priority', 'medium')
                time_sensitive = '⏰' if item.get('time_sensitive') else ''
                project = f" (Project: {item['project']})" if item.get('project') else ''
                results_text += f"• {action}{project} [{priority}]{time_sensitive}\n"
                if item.get('context'):
                    results_text += f"   💭 Context: {item['context']}\n"
                if item.get('due_date'):
                    results_text += f"   📅 Due: {item['due_date']}\n"
            else:
                results_text += f"• {item}\n"
    if analysis['urls']:
        results_text += f"\n[bold]URLs Found:[/bold] {len(analysis['urls'])}\n"
        for url in analysis['urls']:
            results_text += f"• {url}\n"

    # Display results in a panel
    from rich import box
    from rich.panel import Panel
    panel = Panel(
        results_text,
        title="📝 Content Analysis Results",
        border_style="bright_green",
        box=box.ROUNDED
    )
    console.print(panel)

    content_to_save = content

    # Combine tags from themes and tags (if present)
    all_tags = list(set(analysis.get('themes', []) + analysis.get('tags', []))) if 'tags' in analysis else list(set(analysis.get('themes', [])))

    # Prepare metadata
    metadata = {
        'ai_analyzed': True,
        'confidence': analysis['confidence'],
        'actionable_items': analysis.get('actionable_items', [])
    }
    
    # Add source information if provided
    if source_info:
        metadata['source'] = source_info
    
    # Add web context if available
    if web_context_metadata:
        metadata['web_context'] = web_context_metadata

    # Use process_content_with_ai for all content types
    memory_id, tags, detected_category, themes, actionable_items, enhanced_metadata = process_content_with_ai(
        content_to_save,
        user_id,
        analysis['type'],
        metadata=metadata,
        model=current_model,
        client=openrouter_client,
        embedding_client=openai_client,
        precomputed_analysis=analysis,
    )

    if memory_id:
        console.print("[bold green]✅ Content saved successfully![/bold green]")
        if tags:
            console.print(f"[bright_green]🏷 Tags:[/bright_green] {', '.join(tags)}")
        # Show connections if available
        if openai_client:
            try:
                console.print("[cyan]🔍 Looking for connections...[/cyan]")
                
                # Try semantic connections first
                q_emb = get_embedding_for_content(content, client=openai_client)
                semantic_found = False
                
                if q_emb:
                    similar_results = db.brute_sem_search(q_emb, k=CONNECTION_SURFACING_K)
                    # Extract just the memory IDs from (memory_id, similarity) tuples
                    similar_ids = [result[0] for result in similar_results]
                    if memory_id in similar_ids:
                        similar_ids.remove(memory_id)
                    if similar_ids:
                        similar_memories = db.get_memories_by_ids(similar_ids[:CONNECTION_DISPLAY_LIMIT], user_id)
                        if similar_memories:
                            # Store results for /view command
                            last_displayed_items.clear()
                            last_displayed_items.extend(similar_memories)

                            # Generate explanation for connections
                            explanation = generate_connection_explanation(
                                tags,
                                enhanced_metadata.get('entities', {}) if enhanced_metadata else {},
                                similar_memories
                            )

                            console.print(f"[cyan]🔗 This reminds me of the following because {explanation}:[/cyan]")
                            for i, mem in enumerate(similar_memories, 1):
                                raw_content = standardize_truncation(mem['content'], CONNECTION_PREVIEW_LENGTH)
                                formatted_content = format_content_with_markdown(raw_content)
                                console.print(f"   [{i}] [dim]({mem['command_type']})[/dim] {formatted_content}")
                            console.print("[dim]💡 Use /view <number> to see full content[/dim]")
                            semantic_found = True
                
                # Try entity-based connections if we have entities and didn't find many semantic matches
                if enhanced_metadata and 'entities' in enhanced_metadata:
                    entity_connections = db.find_entity_connections(
                        enhanced_metadata['entities'],
                        user_id,
                        k=CONNECTION_DISPLAY_LIMIT,
                        exclude_id=memory_id
                    )
                    if entity_connections and not semantic_found:
                        # Store entity connection results for /view command
                        entity_memories = [mem for mem, shared_entities in entity_connections]
                        last_displayed_items.clear()
                        last_displayed_items.extend(entity_memories)

                        # Collect all shared entities for explanation
                        all_shared = []
                        for _, shared_entities in entity_connections:
                            all_shared.extend(shared_entities)
                        unique_shared = list(dict.fromkeys(all_shared))  # Preserve order, remove duplicates

                        # Generate explanation
                        explanation = generate_connection_explanation(
                            tags,
                            enhanced_metadata.get('entities', {}),
                            entity_memories,
                            shared_entities=unique_shared
                        )

                        console.print(f"[cyan]🔗 This reminds me of the following because {explanation}:[/cyan]")
                        for i, (mem, shared_entities) in enumerate(entity_connections, 1):
                            raw_content = standardize_truncation(mem['content'], CONNECTION_PREVIEW_LENGTH)
                            formatted_content = format_content_with_markdown(raw_content)
                            console.print(f"   [{i}] [dim]({mem['command_type']})[/dim] {formatted_content}")
                        console.print("[dim]💡 Use /view <number> to see full content[/dim]")
                            
            except Exception as e:
                console.print(f"[yellow]Warning: Could not find connections: {e}[/yellow]")
    else:
        console.print("[bold red]❌ Failed to save content[/bold red]")


def _format_search_result(
    item: Dict[str, Any],
    item_num: int,
    preview_length: int = SEARCH_PREVIEW_LENGTH
) -> str:
    """
    Format a single search result for display.

    This helper consolidates the duplicate formatting logic used across
    exact, semantic, and entity search results to ensure consistent
    presentation and make updates easier.

    Args:
        item: Memory item dictionary containing content, metadata, tags, etc.
        item_num: Display number for this result (for /view command)
        preview_length: Maximum character length for content preview

    Returns:
        Formatted string with numbered item, content preview, and metadata
    """
    # Format content with markdown and clickable URLs
    raw_content = standardize_truncation(item['content'], preview_length)
    formatted_content = format_content_with_markdown(raw_content)

    # Extract source information from metadata if present
    item_metadata, source_info, _ = parse_item_metadata(item)

    # Use standardized metadata formatting
    metadata = format_metadata_display(
        item.get('tags', []),
        item.get('timestamp', ''),
        item['command_type'],
        item.get('why_matched', ''),
        None,  # web_context
        source_info
    )

    # Build result string
    result_text = f"{item_num}. {formatted_content}\n"
    if metadata:
        result_text += f"   {metadata}\n"
    result_text += "\n"

    return result_text


def handle_search(
    query: str, 
    user_id: str, 
    current_model: str, 
    openrouter_client: Optional[Any], 
    openai_client: Optional[Any], 
    db: Any, 
    last_displayed_items: List[Dict[str, Any]]
) -> None:
    """
    Handle /search command with exact/tag matches first, then strong semantic matches, with 'why matched' explanations.
    
    Implements a hybrid search strategy that combines multiple approaches for the best results:
    1. Keyword/tag search for exact matches
    2. Strong semantic search using embeddings  
    3. Entity-based search for shared structured entities
    4. Weak semantic fallback if no other matches found
    
    Parameters:
        query (str): The search query text entered by the user
        user_id (str): Identifier for the user performing the search
        current_model (str): Name of the AI model for entity extraction
        openrouter_client (Optional[Any]): Client for LLM operations and entity extraction.
            If None, entity-based search is skipped.
        openai_client (Optional[Any]): Client for embedding generation and semantic search.
            If None, semantic search capabilities are disabled.
        db (Any): Database interface for search operations
        last_displayed_items (List[Dict[str, Any]]): Mutable list to store search results
            for the /view command functionality
    
    Returns:
        None: Outputs formatted search results to console and updates last_displayed_items
    """
    console.print(f"🔍 [cyan]Searching for: {query}[/cyan]")
    
    # NEW: Smart routing - detect if user wants AI responses vs personal knowledge
    is_ai_query = detect_ai_query(query, current_model)
    
    if is_ai_query:
        # Search AI responses only
        console.print("[dim blue]🤖 Searching AI responses...[/dim blue]")
        ai_results = search_ai_responses(query, user_id, db, openai_client)
        display_ai_search_results(ai_results, query, last_displayed_items)
        return
    else:
        # Search personal knowledge only (existing logic)
        console.print("[dim green]📝 Searching personal knowledge...[/dim green]")
    
    try:
        # 1. Run keyword/tag search for exact/tag matches
        exact_results = db.safe_memory_search(query, user_id)
        # Remove duplicates by content (in case semantic search finds the same)
        seen_contents = set(item['content'] for item in exact_results)
        # 2. Run semantic search for related matches (above threshold)
        semantic_results = []
        weak_semantic_results = []
        if openai_client:
            embedding = get_embedding_for_content(query, client=openai_client)
            if embedding:
                all_semantic = db.semantic_search(user_id, query, k=SEARCH_RESULTS_K, min_similarity=0.1, get_embedding_func=lambda q: get_embedding_for_content(q, client=openai_client))
                for item in all_semantic:
                    # Parse similarity from 'why_matched' string
                    sim = None
                    why = item.get('why_matched', '')
                    if 'score:' in why:
                        try:
                            sim = float(why.split('score:')[1].split(')')[0].strip())
                        except Exception:
                            sim = None
                    # Only add if not already in exact/tag results
                    if item['content'] not in seen_contents:
                        if sim is not None and sim >= STRONG_SEMANTIC_SIMILARITY_THRESHOLD:
                            semantic_results.append(item)
                        elif sim is not None:
                            weak_semantic_results.append(item)
        
        # Update seen_contents to include semantic results
        seen_contents.update(item['content'] for item in semantic_results)
        
        # 3. Run entity-based search 
        entity_results = []
        if openrouter_client:
            try:
                # Extract entities from the search query
                query_entities = extract_structured_entities(query, model=current_model, client=openrouter_client)
                if any(entity_list for entity_list in query_entities.values() if entity_list):
                    entity_connections = db.find_entity_connections(query_entities, user_id, k=ENTITY_SEARCH_LIMIT)
                    for memory, shared_entities in entity_connections:
                        # Skip if already shown in other results
                        if memory['content'] not in seen_contents:
                            # Add why_matched explanation for entity matches
                            shared_str = ", ".join(shared_entities[:3])
                            memory['why_matched'] = f"Shared entities: {shared_str}"
                            entity_results.append(memory)
            except Exception as e:
                # If entity search fails, continue without it
                console.print(f"[yellow]Warning: Entity search failed: {e}[/yellow]")
                entity_results = []
        
        # 4. Prepare unified results for /view and display
        all_search_results = []
        all_search_results.extend(exact_results[:SEARCH_RESULTS_PER_SECTION])
        all_search_results.extend(semantic_results[:SEARCH_RESULTS_PER_SECTION]) 
        all_search_results.extend(entity_results[:SEARCH_RESULTS_PER_SECTION])
        if not all_search_results:
            all_search_results.extend(weak_semantic_results[:WEAK_SEMANTIC_FALLBACK_LIMIT])
        
        # Store for /view command
        last_displayed_items.clear()
        last_displayed_items.extend(all_search_results)
        
        content_text = ""
        item_num = 1
        
        if exact_results:
            content_text += f"[bold green]Found {len(exact_results)} exact/tag matches:[/bold green]\n\n"
            for item in exact_results[:SEARCH_RESULTS_PER_SECTION]:
                content_text += _format_search_result(item, item_num, SEARCH_PREVIEW_LENGTH)
                item_num += 1
        if semantic_results:
            content_text += f"[bold blue]Related (strong semantic matches): {len(semantic_results)}[/bold blue]\n\n"
            for item in semantic_results[:SEARCH_RESULTS_PER_SECTION]:
                content_text += _format_search_result(item, item_num, SEARCH_PREVIEW_LENGTH)
                item_num += 1
        
        if entity_results:
            content_text += f"[bold magenta]Entity matches: {len(entity_results)}[/bold magenta]\n\n"
            for item in entity_results[:SEARCH_RESULTS_PER_SECTION]:
                content_text += _format_search_result(item, item_num, SEARCH_PREVIEW_LENGTH)
                item_num += 1
        
        if not exact_results and not semantic_results and not entity_results:
            content_text += "[yellow]No exact, semantic, or entity matches found.[/yellow]\n"
            if weak_semantic_results:
                content_text += "[dim]Here are some loosely related notes:[/dim]\n\n"
                for item in weak_semantic_results[:WEAK_SEMANTIC_FALLBACK_LIMIT]:
                    # Format content with markdown and clickable URLs
                    raw_content = standardize_truncation(item['content'], SEARCH_PREVIEW_LENGTH)
                    formatted_content = format_content_with_markdown(raw_content)
                    
                    # Use standardized metadata formatting
                    metadata = format_metadata_display(
                        item.get('tags', []), 
                        item.get('timestamp', ''), 
                        item['command_type'],
                        item.get('why_matched', '')
                    )
                    
                    content_text += f"{item_num}. {formatted_content}\n"
                    if metadata:
                        content_text += f"   {metadata}\n"
                    content_text += "\n"
                    item_num += 1
        if all_search_results:
            content_text += f"\n[dim]💡 Use /view <number> to see full content (1-{len(all_search_results)})[/dim]"
        print_tool_reply(content_text, f"🔍 Search Results: {query}", "MENTAT Search Tool", "bright_blue")
    except Exception as e:
        print_tool_reply(f"[bold red]❌ Search failed: {e}[/bold red]", f"🔍 Search Results: {query}", "MENTAT Search Tool", "bright_red")

def parse_link_memory(memory_text, metadata_json=None):
    """
    Parse link memory text to extract components.
    Falls back to metadata JSON if content doesn't have structured format.

    Args:
        memory_text: The content field from the database
        metadata_json: Optional JSON string containing metadata

    Returns:
        Dictionary with parsed link components
    """
    lines = memory_text.split('\n')
    parsed = {
        'title': 'No title',
        'url': '',
        'summary': '',
        'comment': '',
        'tags': []
    }

    # First try to parse from structured content
    for line in lines:
        line = line.strip()
        if line.startswith('Title:'):
            parsed['title'] = line.replace('Title:', '').strip()
        elif line.startswith('URL:'):
            parsed['url'] = line.replace('URL:', '').strip()
        elif line.startswith('Summary:'):
            parsed['summary'] = line.replace('Summary:', '').strip()
        elif line.startswith('Comment:'):
            parsed['comment'] = line.replace('Comment:', '').strip()
        elif line.startswith('Tags:'):
            tags_str = line.replace('Tags:', '').strip()
            parsed['tags'] = [tag.strip() for tag in tags_str.split(',') if tag.strip()]

    # Fallback to metadata if content parsing didn't find title/url
    if metadata_json and (parsed['title'] == 'No title' or not parsed['url']):
        try:
            import json
            metadata = json.loads(metadata_json)

            # Use metadata fields if content parsing failed
            if parsed['title'] == 'No title' and 'title' in metadata and metadata['title']:
                parsed['title'] = metadata['title']

            if not parsed['url'] and 'url' in metadata and metadata['url']:
                parsed['url'] = metadata['url']

            if not parsed['summary'] and 'ai_summary' in metadata and metadata['ai_summary']:
                parsed['summary'] = metadata['ai_summary']

            # If still no summary, use the content itself as summary (truncated)
            if not parsed['summary'] and parsed['title'] != 'No title':
                # Use first 200 chars of content as summary
                content_preview = memory_text[:200].strip()
                if content_preview:
                    parsed['summary'] = content_preview + ('...' if len(memory_text) > 200 else '')

        except (json.JSONDecodeError, Exception):
            pass  # If metadata parsing fails, keep what we parsed from content

    return parsed

def handle_links(user_id, search_term, db):
    """Handle /links command"""
    console.print("🔗 [cyan]Retrieving saved links...[/cyan]")

    try:
        links = db.search_for_links(user_id, search_term)
        if links:
            console.print(f"[bold green]Found {len(links)} links:[/bold green]\n")

            for i, link_data in enumerate(links[:LINKS_DISPLAY_LIMIT], 1):
                # Unpack content and metadata (returned as tuple from db)
                content, metadata_json = link_data[:2]

                # Parse the link memory to extract components
                parsed = parse_link_memory(content, metadata_json)

                # New link captures store URL + comment. Older link memories may
                # still have fetched titles and summaries, so display either form.
                title = parsed['title'] or 'No title'
                url = parsed['url'] or 'No URL'
                note = parsed['comment'] or parsed['summary'] or 'No comment'
                
                # Create individual link content with clickable URLs and markdown formatting
                formatted_title = format_content_with_markdown(title)
                formatted_note = format_content_with_markdown(note)
                clickable_url = make_urls_clickable(url) if url != 'No URL' else url
                
                link_content = ""
                if title != 'No title':
                    link_content += f"[bold]{formatted_title}[/bold]\n"
                link_content += f"🔗 {clickable_url}\n"
                link_content += f"📝 {formatted_note}"
                
                # Create individual panel for each link
                link_panel = create_standard_panel(
                    link_content,
                    f"Link #{i}",
                    None,
                    "bright_blue"
                )
                console.print(link_panel)
                console.print()  # Add spacing between links
            
            title = f" Saved Links{f' - {search_term}' if search_term else ''}"
        else:
            title = f" Saved Links{f' - {search_term}' if search_term else ''}"
            print_tool_reply("[red]❌ No links found[/red]", title, "MENTAT Link Tool", "bright_red")
    except Exception as e:
        title = f" Saved Links{f' - {search_term}' if search_term else ''}"
        print_tool_reply(f"[bold red]❌ Failed to retrieve links: {e}[/bold red]", title, "MENTAT Link Tool", "bright_red")

def handle_link(url_with_comment: str, user_id: str, current_model: str, openrouter_client: Any, openai_client: Any, db: MemoryDatabase, last_displayed_items: List):
    """
    Handle /link command by saving a URL and optional user comment.
    Usage: /link <url> [comment]
    """
    if not url_with_comment.strip():
        print_tool_reply("[red]❌ Please provide a URL after /link command[/red]", " Link Tool", "MENTAT Link Tool", "bright_red")
        console.print("\n[dim]Example: /link https://example.com This is interesting[/dim]")
        return

    # Parse URL and comment
    parts = url_with_comment.strip().split(' ', 1)
    url = parts[0]
    comment = parts[1] if len(parts) > 1 else ""

    # Validate URL
    if not url.startswith(('http://', 'https://')):
        print_tool_reply("[red]❌ Please provide a valid URL starting with http:// or https://[/red]", " Link Tool", "MENTAT Link Tool", "bright_red")
        return

    try:
        structured_content = f"URL: {url}"
        if comment:
            structured_content += f"\nComment: {comment}"

        metadata = {
            'url': url,
            'ai_analyzed': True,
            'source': {
                'type': 'link',
                'url': url,
            }
        }
        if comment:
            metadata['user_note'] = comment

        focused_analysis = analyze_capture_content(
            structured_content,
            model=current_model,
            client=openrouter_client,
        )
        
        metadata['focused_themes'] = focused_analysis.get('themes', [])[:5]
        
        memory_id, tags, detected_category, themes, actionable_items, enhanced_metadata = process_content_with_ai(
            structured_content,
            user_id,
            'link',
            metadata=metadata,
            client=openrouter_client,
            embedding_client=openai_client,
            precomputed_analysis=focused_analysis,
        )
        
        # Display what was saved
        panel_content = []
        panel_content.append(f"[bold green]🔗 Link saved successfully![/bold green]\n")
        panel_content.append(f"[bold]URL:[/bold] {make_urls_clickable(url)}")
        
        if comment:
            panel_content.append(f"[bold]Comment:[/bold] {comment}")
        
        if tags:
            panel_content.append(f"[bold]Tags:[/bold] {', '.join(tags)}")
        
        panel_text = "\n".join(panel_content)
        print_tool_reply(panel_text, " Link Saved", "MENTAT Link Tool", "bright_green")
        
        # Proactive connection surfacing
        with show_thinking_spinner("Looking for connections..."):
            q_emb = get_embedding_for_content(structured_content, client=openai_client)
            if q_emb:
                similar_results = db.brute_sem_search(q_emb, k=CONNECTION_SURFACING_K)
                # Extract just the memory IDs from (memory_id, similarity) tuples
                similar_ids = [result[0] for result in similar_results if result[0] != memory_id]
                
                if similar_ids:
                    similar_memories = db.get_memories_by_ids(similar_ids[:CONNECTION_DISPLAY_LIMIT], user_id)
                    if similar_memories:
                        connections = []
                        for mem in similar_memories:
                            content_preview = standardize_truncation(mem['content'], CONNECTION_PREVIEW_LENGTH)
                            connections.append(f"• [dim]{mem['command_type'].upper()}:[/dim] {content_preview}")
                        
                        connections_text = "\n".join(connections)
                        print_tool_reply(f"🧠 [bold]Related content found:[/bold]\n\n{connections_text}", " Connections", "MENTAT Connection Tool", "bright_blue")
        
        # Update last displayed items for potential /view usage
        last_displayed_items.clear()
        last_displayed_items.append({
            'id': memory_id,
            'content': structured_content,
            'type': 'link',
            'url': url
        })
        
    except Exception as e:
        console.print(f"[red]❌ Error processing link: {e}[/red]")
        print_tool_reply(f"[red]❌ Failed to process link: {e}[/red]", " Link Tool", "MENTAT Link Tool", "bright_red")

def handle_latest(user_id, db, last_displayed_items, limit=DEFAULT_MEMORY_LIMIT):
    """Handle /latest command"""
    console.print("📅 [cyan]Retrieving latest content...[/cyan]")
    
    try:
        memories = db.get_all_memories(user_id, limit=limit)
        if memories:
            # Store results for /view command
            last_displayed_items.clear()
            last_displayed_items.extend(memories)
            
            content_text = f"[bold green]📝 Found {len(memories)} recent items:[/bold green]\n"
            for i, item in enumerate(memories, 1):
                content_text += f"\n{i}. [{item['command_type'].upper()}]\n"
                raw_content = standardize_truncation(item['content'], PROJECT_PREVIEW_LENGTH)
                formatted_content = format_content_with_markdown(raw_content)
                content_text += f"   {formatted_content}\n"
                
                # Use standardized metadata formatting
                metadata_raw = item.get('metadata', '{}')
                if isinstance(metadata_raw, str):
                    item_metadata = json.loads(metadata_raw) if metadata_raw else {}
                else:
                    item_metadata = metadata_raw or {}
                web_context = item_metadata.get('web_context')
                
                
                metadata = format_metadata_display(
                    item['tags'] if 'tags' in item else [], 
                    item['timestamp'] if 'timestamp' in item else '', 
                    None,  # Don't repeat command_type since it's already shown
                    None,
                    web_context,
                    item_metadata.get('source')  # Add source information
                )
                if metadata:
                    content_text += f"   {metadata}\n"
            
            print_tool_reply(content_text, " Latest Content", "MENTAT Latest Tool", "bright_green")
            show_contextual_commands(last_displayed_items)
        else:
            print_tool_reply("[red]❌ No recent content found[/red]", " Latest Content", "MENTAT Latest Tool", "bright_red")
    except Exception as e:
        print_tool_reply(f"[bold red]❌ Failed to retrieve latest content: {e}[/bold red]", " Latest Content", "MENTAT Latest Tool", "bright_red")

def handle_summary(user_id, days, current_model, openrouter_client, db):
    """Handle /summary command"""
    console.print(f" [cyan]Generating {days}-day summary...[/cyan]")
    
    try:
        weekly_data = db.get_weekly_content(user_id, days)
        if weekly_data['all_content']:
            summary = generate_weekly_summary(weekly_data, days, model=current_model, client=openrouter_client)
            
            # Use enhanced markdown rendering for AI-generated summary content
            if should_use_markdown_rendering(summary):
                summary_panel = render_markdown_to_panel(
                    summary, 
                    f"📈 {days}-Day Summary", 
                    subtitle="MENTAT Activity Analysis",
                    border_style="bright_yellow"
                )
                console.print(summary_panel)
            else:
                # Fallback to standard formatting for simple content
                formatted_summary = format_content_with_markdown(summary)
                content_text = "[bold green]📈 Your Summary:[/bold green]\n"
                content_text += formatted_summary
                print_tool_reply(content_text, f" {days}-Day Summary", "MENTAT Summary Tool", "bright_yellow")
        else:
            print_tool_reply(f"[red]❌ No activity found in the last {days} days[/red]", f" {days}-Day Summary", "MENTAT Summary Tool", "bright_red")
    except Exception as e:
        print_tool_reply(f"[bold red]❌ Failed to generate summary: {e}[/bold red]", f" {days}-Day Summary", "MENTAT Summary Tool", "bright_red")

def analyze_project_entities(project_memories):
    """Analyze and aggregate entity frequencies from project memories"""
    
    # Initialize category counters
    entity_frequencies = {
        'people': Counter(),
        'organizations': Counter(),
        'technologies': Counter(),
        'projects': Counter(),
        'concepts': Counter(),
        'locations': Counter(),
        'dates': Counter()
    }
    
    for memory in project_memories:
        if 'metadata' not in memory or not memory['metadata']:
            continue
            
        try:
            # Parse metadata JSON
            metadata = json.loads(memory['metadata']) if isinstance(memory['metadata'], str) else memory['metadata']
            entities = metadata.get('entities', {})
            
            # Count entities by category
            for category, entity_list in entities.items():
                if isinstance(entity_list, list) and entity_list:
                    for entity in entity_list:
                        if entity and isinstance(entity, str):
                            entity_frequencies[category][entity.strip()] += 1
                            
        except (json.JSONDecodeError, TypeError, AttributeError):
            # Skip memories with malformed metadata
            continue
    
    # Convert to regular dicts and filter out empty categories, keeping only top 5 per category
    result = {}
    for category, counter in entity_frequencies.items():
        if counter:
            # Get top most frequent entities for this category
            top_entities = dict(counter.most_common(TOP_ENTITIES_PER_CATEGORY))
            if top_entities:
                result[category] = top_entities
    
    return result

def format_project_analysis(analysis_text):
    """Format project analysis text for better Rich display"""
    if not analysis_text:
        return "[dim]No analysis available[/dim]"
    
    try:
        # Split into lines and process each line
        lines = analysis_text.split('\n')
        formatted_lines = []
        
        for line in lines:
            line = line.strip()
            if not line:
                formatted_lines.append("")
                continue
                
            # Handle different markdown elements
            if line.startswith('# '):
                # Main title - make it bold and cyan
                title = line[2:].strip()
                formatted_lines.append(f"[bold cyan]{title}[/bold cyan]")
            elif line.startswith('## '):
                # Section headers - make them bold and yellow
                header = line[3:].strip()
                formatted_lines.append(f"\n[bold yellow]{header}[/bold yellow]")
            elif line.startswith('### '):
                # Subsection headers - make them bold and blue
                subheader = line[4:].strip()
                formatted_lines.append(f"\n[bold blue]{subheader}[/bold blue]")
            elif line.startswith('- **') and line.endswith('**'):
                # Bold list items - keep bold but add color
                item = line[2:-2]  # Remove "- **" and "**"
                formatted_lines.append(f"• [bold]{item}[/bold]")
            elif line.startswith('- '):
                # Regular list items
                item = line[2:].strip()
                formatted_lines.append(f"• {item}")
            elif line.startswith('1. **') and line.endswith('**'):
                # Numbered bold items
                item = line[3:-2]  # Remove "1. **" and "**"
                formatted_lines.append(f"1. [bold]{item}[/bold]")
            else:
                # Try numbered list formatting (1-9)
                from .display import format_numbered_list_item
                numbered_result = format_numbered_list_item(line)
                if numbered_result:
                    formatted_lines.append(numbered_result)
                elif '**' in line:
                    # Handle inline bold text safely
                    # Replace **text** with [bold]text[/bold] using regex for proper matching
                    formatted_line = re.sub(r'\*\*([^*]+)\*\*', r'[bold]\1[/bold]', line)
                    formatted_lines.append(formatted_line)
                elif line.startswith('  - '):
                    # Indented list items
                    item = line[4:].strip()
                    formatted_lines.append(f"    • {item}")
                else:
                    # Regular text
                    formatted_lines.append(line)
        
        return '\n'.join(formatted_lines)
    
    except Exception as e:
        # Fallback to plain text if Rich formatting fails
        console.print(f"[yellow]Warning: Rich formatting failed, using plain text[/yellow]")
        return analysis_text

def handle_project(
    project_name: str, 
    user_id: str, 
    current_model: str, 
    openrouter_client: Optional[Any], 
    db: Any
) -> None:
    """
    Handle /project command with comprehensive project analysis and entity frequency counting.
    
    Semantically finds all content related to a project and generates an AI-powered 
    analysis dashboard. Key feature is entity frequency analysis that counts occurrences
    of structured entities within the project's content.
    
    Parameters:
        project_name (str): Name of the project to analyze
        user_id (str): Identifier for the user requesting the analysis
        current_model (str): Name of the AI model for analysis generation
        openrouter_client (Optional[Any]): Client for LLM operations and project analysis.
            If None, AI analysis is skipped but basic content stats are shown.
        db (Any): Database interface for content retrieval and analysis operations
    
    Returns:
        None: Outputs formatted project analysis to console including content stats,
            entity frequencies, AI analysis, and timeline
    """
    console.print(f" [cyan]Analyzing project: {project_name}[/cyan]")
    
    try:
        with show_thinking_spinner("🤔 Thinking...") as (progress, task):
            
            def get_embedding_wrapper(content):
                return get_embedding_for_content(content)
            
            project_data = db.semantic_project_content(
                user_id, project_name, k=PROJECT_ANALYSIS_K,
                get_embedding_for_query=get_embedding_wrapper,
                brute_sem_search=db.brute_sem_search,
                fallback_project_search=db._fallback_project_search
            )
            
            if project_data['all_content']:
                # Build content for the panel
                content_text = f"[bold green]📋 Project Content Found:[/bold green]\n"
                content_text += f"   • {len(project_data['links'])} links\n"
                content_text += f"   • {len(project_data['ideas'])} ideas\n" 
                content_text += f"   • {len(project_data['questions'])} questions\n"
                content_text += f"   • {len(project_data['thoughts'])} thoughts\n"
                
                # Add entity frequency analysis
                entity_frequencies = analyze_project_entities(project_data['all_content'])
                if entity_frequencies:
                    content_text += f"\n[bold magenta]🏷️ Entities in this project:[/bold magenta]\n"
                    for category, entities in entity_frequencies.items():
                        if entities:
                            content_text += f"   • {category.title()}: {', '.join([f'{name} ({count})' for name, count in entities.items()])}\n"
                
                if openrouter_client:
                    analysis = db.analyze_project_progress(project_data, project_name, openrouter_client, model=current_model)
                    
                    # Check if analysis contains significant markdown and render accordingly
                    if should_use_markdown_rendering(analysis):
                        # Create a separate markdown panel for rich AI analysis
                        analysis_panel = render_markdown_to_panel(
                            analysis, 
                            "🤖 AI Project Analysis", 
                            subtitle="MENTAT Analysis Engine",
                            border_style="bright_green"
                        )
                        console.print(analysis_panel)
                        console.print()  # Add spacing
                    else:
                        # Use the existing formatted approach for simpler content
                        formatted_analysis = format_project_analysis(analysis)
                        content_text += f"\n[bold green]🤖 AI Project Analysis:[/bold green]\n{formatted_analysis}"
                    
                    # Add timeline analysis after AI analysis (which includes "Why Included")
                    if project_data['all_content']:
                        content_text += f"\n\n[bold yellow]📅 Timeline:[/bold yellow]\n"
                        recent_items = sorted(project_data['all_content'], key=lambda x: x['timestamp'] if x['timestamp'] else '', reverse=True)[:TIMELINE_RECENT_ITEMS_LIMIT]
                        for item in recent_items:
                            timestamp = item['timestamp'] if item['timestamp'] else 'Unknown date'
                            content_type = item['command_type'].upper()
                            raw_content = standardize_truncation(item['content'], TIMELINE_CONTENT_LENGTH)
                            formatted_content = format_content_with_markdown(raw_content)
                            content_text += f"• {timestamp}: {content_type} - {formatted_content}\n"
                
                print_tool_reply(content_text, f"📊 Project Analysis: {project_name}", "MENTAT Project Tool", "bright_green")
            else:
                print_tool_reply(f"[red]❌ No content found for project '{project_name}'[/red]", f"📊 Project Analysis: {project_name}", "MENTAT Project Tool", "bright_red")
    except Exception as e:
        print_tool_reply(f"[bold red]❌ Project analysis failed: {str(e)}[/bold red]", f"📊 Project Analysis: {project_name}", "MENTAT Project Tool", "bright_red")

def handle_tag(tags, user_id, db, last_displayed_items):
    """Handle /tag command"""
    console.print(f" [cyan]Searching by tags: {', '.join(tags)}[/cyan]")
    
    try:
        results = db.search_by_tags(user_id, tags)
        if results:
            # Store results for /view command
            last_displayed_items.clear()
            last_displayed_items.extend(results)
            
            content_text = f"[bold green]Found {len(results)} tagged items:[/bold green]\n"
            for i, item in enumerate(results[:SEARCH_RESULTS_PER_SECTION], 1):
                raw_content = standardize_truncation(item['content'], PROJECT_PREVIEW_LENGTH)
                formatted_content = format_content_with_markdown(raw_content)
                
                # Use standardized metadata formatting
                metadata = format_metadata_display(
                    item.get('tags', []), 
                    item.get('timestamp', ''), 
                    item.get('command_type', ''),
                    None
                )
                
                content_text += f"\n{i}. {formatted_content}\n"
                if metadata:
                    content_text += f"   {metadata}\n"
            
            content_text += f"\n[dim]💡 Use /view <number> to see full content (1-{len(results)})[/dim]"
            print_tool_reply(content_text, f"🏷 Tag Search: {', '.join(tags)}", "MENTAT Tag Tool", "bright_yellow")
        else:
            print_tool_reply(f"[red]❌ No items found with those tags[/red]", f" Tag Search: {', '.join(tags)}", "MENTAT Tag Tool", "bright_red")
    except Exception as e:
        print_tool_reply(f"[bold red]❌ Tag search failed: {e}[/bold red]", f" Tag Search: {', '.join(tags)}", "MENTAT Tag Tool", "bright_red")

def handle_todo(user_id, search_term, db, status_filter=None, last_displayed_items=None):
    """Handle /todo command with enhanced status display and filtering"""
    # Import display functions here to avoid circular imports
    from .display import format_todo_with_status, format_todo_metadata
    from mentat.core.config import DEFAULT_TODO_FILTER

    # Use default filter if no specific filter was requested
    # status_filter will be explicitly set to "pending" when /hide is called
    # so we only apply DEFAULT_TODO_FILTER when status_filter is None
    if status_filter is None:
        status_filter = DEFAULT_TODO_FILTER

    todos = db.get_user_todos(user_id, status_filter=status_filter)
    
    # Apply search term filtering if provided
    if search_term:
        todos = [t for t in todos if search_term.lower() in t['action'].lower()]
    
    if todos:
        # Store todos for /view command (convert to memory-like format)
        if last_displayed_items is not None:
            last_displayed_items.clear()
            for todo in todos:
                # Convert todo to memory-like format for /view compatibility
                memory_like = {
                    'id': todo.get('memory_id'),
                    'content': f"Todo: {todo['action']}\n\nFrom: {todo['source_content'][:200]}..." if len(todo['source_content']) > 200 else f"Todo: {todo['action']}\n\nFrom: {todo['source_content']}",
                    'command_type': todo.get('command_type', 'task'),
                    'tags': todo.get('tags', []),
                    'timestamp': todo.get('timestamp', ''),
                    'status': todo.get('status', 'pending'),
                    'priority': todo.get('priority', 'medium'),
                    'project': todo.get('project', ''),
                    'original_todo': todo  # Keep reference to original todo data
                }
                last_displayed_items.append(memory_like)
        # Build title with status filter info
        title_parts = [" Todos"]
        if status_filter:
            title_parts.append(f" - {status_filter}")
        if search_term:
            title_parts.append(f" - '{search_term}'")
        title = "".join(title_parts)
        
        # Count by status for summary
        status_counts = {}
        for todo in todos:
            status = todo.get('status', 'pending')
            status_counts[status] = status_counts.get(status, 0) + 1
        
        # Create summary line
        if status_filter:
            content_text = f"[bold green]Found {len(todos)} {status_filter} todos:[/bold green]\n\n"
        else:
            summary_parts = []
            for status, count in status_counts.items():
                if count > 0:
                    summary_parts.append(f"{count} {status}")
            content_text = f"[bold green]Current Todos ({', '.join(summary_parts)}):[/bold green]\n\n"
        
        # Format each todo with status indicators
        for todo in todos:
            display_number = todo.get('display_number', 0)
            formatted_todo = format_todo_with_status(todo, display_number)
            content_text += formatted_todo + "\n"
            
            # Add metadata if present
            metadata_line = format_todo_metadata(todo)
            if metadata_line:
                content_text += metadata_line + "\n"
            
            content_text += "\n"  # Extra space between todos
        
        # Add usage instructions with note about number stability
        if status_filter:
            content_text += f"[dim]💡 Use [cyan]/view <number>[/cyan] for details • [cyan]/mark <number(s)>[/cyan] to toggle • [cyan]/todo[/cyan] to show all (numbers stay the same)[/dim]"
        else:
            content_text += f"[dim]💡 Use [cyan]/view <number>[/cyan] for details • [cyan]/mark <number(s)>[/cyan] to toggle done/pending • [cyan]/todo done[/cyan] to show completed[/dim]"
        
        print_tool_reply(content_text, title, "MENTAT Todo Tool", "bright_cyan")
    else:
        filter_desc = f" {status_filter}" if status_filter else ""
        search_desc = f" matching '{search_term}'" if search_term else ""
        title = f" Todos{filter_desc}{search_desc}"
        print_tool_reply(f"[red]No{filter_desc} todos found{search_desc}.[/red]", title, "MENTAT Todo Tool", "bright_red")

def handle_mark(user_id, todo_numbers, db):
    """Handle /mark command to toggle todo(s) between pending and done

    Args:
        user_id: User identifier
        todo_numbers: Single todo number (int) or list of todo numbers
        db: Database instance
    """
    # Import display functions here to avoid circular imports
    from .display import get_status_indicator

    # Normalize input to always be a list
    if isinstance(todo_numbers, int):
        todo_numbers = [todo_numbers]

    # Get all todos to find the right ones by display number
    # Use a large limit to ensure we can find high-numbered todos
    todos = db.get_user_todos(user_id, status_filter=None, limit=200)

    # Track results for summary
    marked_todos = []
    not_found = []

    # Process each todo number
    for todo_number in todo_numbers:
        # Find todo by display number
        target_todo = None
        for todo in todos:
            if todo.get('display_number') == todo_number:
                target_todo = todo
                break

        if not target_todo:
            not_found.append(todo_number)
            continue

        # Toggle between pending and done
        current_status = target_todo.get('status', 'pending')
        new_status = 'pending' if current_status == 'done' else 'done'

        # Update the todo status in database
        memory_id = target_todo['memory_id']
        item_index = target_todo['item_index']

        success = db.update_todo_status(memory_id, item_index, new_status)

        if success:
            indicator = get_status_indicator(new_status)
            action_preview = target_todo['action'][:50] + "..." if len(target_todo['action']) > 50 else target_todo['action']

            if new_status == 'done':
                action_display = f"[strike]{action_preview}[/strike]"
            else:
                action_display = action_preview

            marked_todos.append({
                'number': todo_number,
                'status': new_status,
                'indicator': indicator,
                'action': action_display
            })

    # Display results
    if marked_todos:
        if len(marked_todos) == 1:
            # Single item - original detailed message
            todo = marked_todos[0]
            status_display = "completed" if todo['status'] == 'done' else "unmarked (back to pending)"
            print_tool_reply(
                f"[bright_green]✅ Todo #{todo['number']} {status_display}[/bright_green]\n\n"
                f"{todo['indicator']} {todo['action']}",
                " Mark Todo", "MENTAT Mark Tool", "bright_green"
            )
        else:
            # Multiple items - show summary
            completed = [t for t in marked_todos if t['status'] == 'done']
            pending = [t for t in marked_todos if t['status'] == 'pending']

            summary_lines = [f"[bright_green]✅ Marked {len(marked_todos)} todo(s)[/bright_green]\n"]

            if completed:
                summary_lines.append(f"[bright_green]Completed ({len(completed)}):[/bright_green]")
                for todo in completed:
                    summary_lines.append(f"  {todo['indicator']} #{todo['number']}: {todo['action']}")

            if pending:
                if completed:
                    summary_lines.append("")  # Blank line separator
                summary_lines.append(f"[yellow]Unmarked to pending ({len(pending)}):[/yellow]")
                for todo in pending:
                    summary_lines.append(f"  {todo['indicator']} #{todo['number']}: {todo['action']}")

            print_tool_reply(
                "\n".join(summary_lines),
                " Mark Todos", "MENTAT Mark Tool", "bright_green"
            )

    # Report any not found
    if not_found:
        not_found_str = ", ".join(f"#{n}" for n in not_found)
        print_tool_reply(
            f"[red]❌ Todo(s) not found: {not_found_str}[/red]\n"
            f"[dim]Use [cyan]/todo[/cyan] to see current todos.[/dim]",
            " Mark Todo", "MENTAT Mark Tool", "bright_red"
        )

    # If nothing was processed at all
    if not marked_todos and not not_found:
        print_tool_reply(
            "[red]❌ No todos were marked[/red]",
            " Mark Todo", "MENTAT Mark Tool", "bright_red"
        )

def handle_synthesize(user_id, topic, current_model, openrouter_client, openai_client, db):
    """Handle /synthesize command."""
    relevant = semantic_search(user_id, topic, k=SYNTHESIS_K, db=db, openai_client=openai_client)  # Use local semantic_search function
    if relevant:
        try:
            if not openrouter_client:
                print_tool_reply("[red]❌ Synthesis unavailable: OpenRouter client not initialized.[/red]", f"🔗 Synthesis: {topic}", "MENTAT Synthesis Tool", "bright_red")
                return
            synth_msg = f"🤔 Thinking... Synthesizing {len(relevant)} relevant items for \"{topic}\"..."
            with show_thinking_spinner(synth_msg) as (progress, task):
                synthesized = synthesize_notes(relevant, topic, model=current_model, client=openrouter_client)
            
            # Use enhanced markdown rendering for AI-generated synthesis content
            if should_use_markdown_rendering(synthesized):
                synthesis_panel = render_markdown_to_panel(
                    synthesized, 
                    f"🔗 Synthesis: {topic}", 
                    subtitle="MENTAT Knowledge Synthesis",
                    border_style="bright_magenta"
                )
                console.print(synthesis_panel)
            else:
                # Fallback to standard formatting for simple content
                formatted_synthesized = format_content_with_markdown(synthesized)
                content_text = f"[bold green]Synthesizing {len(relevant)} relevant items...[/bold green]\n"
                content_text += f"\n[bold]Synthesized Document:[/bold]\n"
                content_text += formatted_synthesized
                print_tool_reply(content_text, f"🔗 Synthesis: {topic}", "MENTAT Synthesis Tool", "bright_magenta")
        except Exception as e:
            print_tool_reply(f"[red]❌ Synthesis failed: {e}[/red]", f"🔗 Synthesis: {topic}", "MENTAT Synthesis Tool", "bright_red")
    else:
        print_tool_reply("[red]No content to synthesize.[/red]", f"🔗 Synthesis: {topic}", "MENTAT Synthesis Tool", "bright_red")

def generate_reference_explanation(reference, user_id, current_model, openrouter_client, db):
    """Generate detailed explanation for a numbered reference"""
    topic = reference['topic']
    context = reference['context']
    
    # Search for personal context about this topic
    related_memories = db.search_memories(user_id, topic, limit=REFERENCE_RELATED_MEMORIES_LIMIT)
    
    # Build explanation using web search for comprehensive info
    if openrouter_client:
        try:
            prompt = f"""Provide a comprehensive explanation of "{topic}" with the following structure:

**What it is:** Brief definition and overview
**Why it matters:** Significance and applications  
**Key details:** Important technical aspects or features
**Connection to user:** How this relates to their interests/work

User context: {context}
Related user memories: {len(related_memories)} items found

Keep the explanation informative but concise (2-3 paragraphs max)."""

            result = complete_online(
                openrouter_client,
                current_model,
                [{"role": "user", "content": prompt}],
                max_tokens=REFERENCE_EXPLANATION_MAX_TOKENS
            )
            
            explanation = result.text
            
            # Add personal context if available
            if related_memories:
                explanation += "\n\n**From your memories:**\n"
                for mem in related_memories[:PERSONAL_CONTEXT_MEMORIES_LIMIT]:
                    preview = mem['content'][:100].replace('\n', ' ')
                    explanation += f"• {preview}...\n"
            
            return format_content_with_markdown(explanation)
            
        except Exception as e:
            return f"**{topic}**\n\nTechnical concept mentioned in AI response.\n\n*Unable to generate detailed explanation: {str(e)}*"
    
    return f"**{topic}**\n\nTechnical concept mentioned in AI response.\n\n*Web search unavailable - no API client*"


def handle_save_response(user_id, current_model, openrouter_client, openai_client, db, last_displayed_items,
                        last_ai_response=None, last_ai_response_command=None, last_ai_prompt=None, clear_response_callback=None):
    """Save the last AI response as a searchable archive item."""
    
    if not last_ai_response:
        console.print("[yellow]No recent AI response to save[/yellow]")
        return
    
    console.print("[cyan]Saving AI response as captured memory...[/cyan]")
    
    try:
        # Create source metadata for AI response
        from datetime import datetime
        source_info = {
            'type': 'ai_response',
            'model': current_model,
            'timestamp': datetime.now().isoformat(),
            'context': 'chat_response'
        }
        if last_ai_response_command:
            source_info['command'] = last_ai_response_command
        if last_ai_prompt:
            source_info['prompt'] = last_ai_prompt
        
        metadata = {'source': source_info}
        memory_id = save_memory(
            last_ai_response,
            user_id,
            'ai_response',
            ['ai_response'],
            metadata,
            db,
            openai_client,
        )

        if not memory_id:
            console.print("[red]Failed to save AI response[/red]")
            return

        console.print("[bold green]✅ AI response saved for search[/bold green]")
        
        # Clear after saving to prevent accidental re-saves
        if clear_response_callback:
            clear_response_callback()
        
        console.print("[green]✓ AI response saved successfully[/green]")
        
    except Exception as e:
        console.print(f"[red]Error saving AI response: {e}[/red]")


def handle_delete(item_num_str: str, user_id: str, db: MemoryDatabase, last_displayed_items: List[Dict[str, Any]]):
    """
    Delete a memory by number from the last displayed results.
    
    Args:
        item_num_str: String number of the item to delete
        user_id: User identifier
        db: Database instance
        last_displayed_items: List of items from last command (latest, search, etc.)
    """
    try:
        # Parse the item number
        try:
            item_num = int(item_num_str)
        except ValueError:
            console.print(f"[red]Error: '{item_num_str}' is not a valid number[/red]")
            return
        
        # Check if we have any displayed items
        if not last_displayed_items:
            console.print("[yellow]No numbered items available. Run /latest, /search, or another command that shows numbered results first.[/yellow]")
            return
        
        # Validate the item number
        if item_num < 1 or item_num > len(last_displayed_items):
            console.print(f"[red]Error: Item number must be between 1 and {len(last_displayed_items)}[/red]")
            return
        
        # Get the memory to delete
        memory_to_delete = last_displayed_items[item_num - 1]
        memory_id = memory_to_delete.get('id')
        
        if not memory_id:
            console.print("[red]Error: Selected item doesn't have a valid ID for deletion[/red]")
            return
        
        # Show preview of what will be deleted
        content_preview = standardize_truncation(memory_to_delete.get('content', ''), 100)
        memory_type = memory_to_delete.get('command_type', 'unknown')
        timestamp = memory_to_delete.get('timestamp', 'unknown')
        
        console.print(f"[yellow]About to delete item {item_num}:[/yellow]")
        console.print(create_standard_panel(
            f"**Type**: {memory_type}\n**Date**: {timestamp}\n**Content**: {content_preview}",
            title="🗑️ Delete Preview",
            border_style="yellow"
        ))
        
        # Ask for confirmation
        console.print("[bold red]This action cannot be undone![/bold red]")
        confirmation = input("Type 'DELETE' to confirm: ").strip()
        
        if confirmation != 'DELETE':
            console.print("[yellow]Deletion cancelled.[/yellow]")
            return
        
        # Perform the deletion
        with show_thinking_spinner("Deleting memory..."):
            deleted_memory = db.delete_memory(memory_id, user_id)
        
        # Remove from last_displayed_items to keep numbering consistent
        last_displayed_items.pop(item_num - 1)
        
        # Confirm deletion
        console.print(f"[green]✓ Memory {memory_id} deleted successfully[/green]")
        
        # Show updated numbering if there are remaining items
        if last_displayed_items:
            console.print(f"[dim]Remaining items: 1-{len(last_displayed_items)}. Numbers have been updated.[/dim]")
        else:
            console.print("[dim]No items remaining in current view.[/dim]")
        
    except Exception as e:
        console.print(f"[red]Error deleting memory: {e}[/red]")


# AI Response Search Functions

def detect_ai_query(query: str, current_model: str) -> bool:
    """
    Detect if query is looking for AI responses
    Returns True if should search AI responses, False for personal knowledge
    """
    from mentat.core.config import AVAILABLE_MODELS
    
    query_lower = query.lower()
    
    # Explicit AI terms
    ai_terms = ['ai response', 'ai explained', 'assistant', 'told me', 'suggested', 'ai told', 'ai said', 'gpt']
    if any(term in query_lower for term in ai_terms):
        return True
    
    # Model name detection (dynamic from config)
    for friendly_name, model_path in AVAILABLE_MODELS.items():
        if friendly_name.lower() in query_lower:
            return True
        # Check model path parts: "deepseek", "claude", "gpt"
        for part in model_path.lower().split('/'):
            if len(part) >= 3:
                # Check if the query contains this model part as a substring
                if part in query_lower:
                    return True
                # Also check for partial matches like longer words in model names
                # Skip very short words to avoid false matches like "ai" in "openai"
                for query_word in query_lower.split():
                    if len(query_word) >= 4 and query_word in part:
                        return True
    
    return False

def search_ai_responses(query: str, user_id: str, db: Any, openai_client: Any) -> List[Dict]:
    """Search AI responses by content and metadata"""
    
    results = []
    try:
        with db.db_pool.get_connection() as conn:
            cursor = conn.cursor()
            
            # Check if this is a general "ai response" query (return all AI responses)
            if query.lower().strip() in ['ai response', 'ai responses']:
                cursor.execute('''
                    SELECT m.id, m.content, m.command_type, m.tags, m.timestamp, m.metadata
                    FROM memories m
                    WHERE m.user_id = ? 
                    AND json_extract(m.metadata, '$.source.type') = 'ai_response'
                    ORDER BY m.timestamp DESC
                    LIMIT 10
                ''', (user_id,))
            else:
                # Search content AND metadata for AI responses only
                cursor.execute('''
                    SELECT m.id, m.content, m.command_type, m.tags, m.timestamp, m.metadata
                    FROM memories m
                    WHERE m.user_id = ? 
                    AND json_extract(m.metadata, '$.source.type') = 'ai_response'
                    AND (
                        m.content LIKE ? 
                        OR json_extract(m.metadata, '$.source.model') LIKE ?
                    )
                    ORDER BY m.timestamp DESC
                    LIMIT 10
                ''', (user_id, f'%{query}%', f'%{query}%'))
            
            for row in cursor.fetchall():
                results.append({
                    'id': row[0],
                    'content': row[1],
                    'command_type': row[2],
                    'tags': json.loads(row[3]) if row[3] else [],
                    'timestamp': row[4],
                    'metadata': row[5],
                    'why_matched': f"AI response match: {query}"
                })
    except Exception as e:
        console.print(f"[yellow]AI search error: {e}[/yellow]")
    
    # Add semantic search for AI responses if available
    if openai_client and openai_client:
        try:
            all_semantic = db.semantic_search(
                user_id, query, k=5, min_similarity=0.1,
                get_embedding_func=lambda q: get_embedding_for_content(q, client=openai_client)
            )
            # Filter to only AI responses
            ai_semantic = []
            for item in all_semantic:
                try:
                    metadata = json.loads(item.get('metadata', '{}')) if item.get('metadata') else {}
                    if metadata.get('source', {}).get('type') == 'ai_response':
                        ai_semantic.append(item)
                except:
                    pass
            
            # Merge with content results (deduplicate)
            seen_content = {r['content'] for r in results}
            for sem_result in ai_semantic:
                if sem_result['content'] not in seen_content:
                    results.append(sem_result)
                    
        except Exception:
            pass  # Semantic search is optional
    
    return results

def display_ai_search_results(results: List[Dict], query: str, last_displayed_items: List):
    """Display AI response search results with clear attribution"""
    
    if not results:
        console.print("[yellow]No AI responses found matching your query.[/yellow]")
        console.print("[dim]Try: 'ai response', model names (deepseek, claude), or 'assistant explained'[/dim]")
        return
    
    # Store for /view command
    last_displayed_items.clear()
    last_displayed_items.extend(results)
    
    content_text = f"[bold blue]🤖 Found {len(results)} AI responses:[/bold blue]\n\n"
    
    for i, item in enumerate(results, 1):
        # Format content 
        raw_content = standardize_truncation(item['content'], SEARCH_PREVIEW_LENGTH)
        formatted_content = format_content_with_markdown(raw_content)
        
        # Extract source info for display
        metadata = item.get('metadata', {})
        if isinstance(metadata, str):
            metadata = json.loads(metadata) if metadata else {}
        
        source_info = metadata.get('source', {})
        prompt = source_info.get('prompt')
        formatted_prompt = None
        if prompt:
            raw_prompt = standardize_truncation(str(prompt), SEARCH_PREVIEW_LENGTH)
            formatted_prompt = format_content_with_markdown(raw_prompt)
        
        # Enhanced metadata with source prominence
        metadata_display = format_metadata_display(
            item.get('tags', []),
            item.get('timestamp', ''),
            item.get('command_type', ''),
            item.get('why_matched', f"AI response match: {query}"),
            None,  # web_context
            source_info
        )
        
        if formatted_prompt:
            content_text += f"{i}. [bold]Prompt:[/bold] {formatted_prompt}\n"
            content_text += f"   [bold]Response:[/bold] {formatted_content}\n"
        else:
            content_text += f"{i}. {formatted_content}\n"
        content_text += f"   {metadata_display}\n\n"
    
    # Display in panel
    print_tool_reply(content_text, "🤖 AI Response Search", "MENTAT AI Search", "bright_blue")
    
    # Show contextual commands
    console.print("[dim]💡 Use /view <number> to see full AI response content[/dim]")

# Concept Exploration Command Handlers

def handle_explore_web_command(concept_or_number: str, user_id: str, db: MemoryDatabase, 
                              openrouter_client: Any, last_displayed_items: List[Dict], 
                              global_enhanced_chat: Any = None,
                              interactive: bool = True) -> None:
    """
    Handle /explore command for full concept exploration sessions
    
    Args:
        concept_or_number: Either a concept name or reference number
        user_id: User identifier
        db: Database instance
        openrouter_client: OpenRouter client for LLM interactions
        last_displayed_items: List for numbered item tracking
        global_enhanced_chat: Enhanced chat system instance
        interactive: Whether numbered interactive references persist after display
    """
    try:
        from mentat.concepts.concept_integration import ConceptIntegrationManager
        from mentat.concepts.concept_display import render_interactive_concept_tree
        
        integration_manager = ConceptIntegrationManager(db, openrouter_client)
        
        # Determine if input is a number (reference) or concept name
        concept_name = None
        
        if concept_or_number.isdigit():
            # Handle reference number
            ref_num = int(concept_or_number)
            
            # Check AI references first
            if global_enhanced_chat and global_enhanced_chat.get_reference(str(ref_num)):
                reference = global_enhanced_chat.get_reference(str(ref_num))
                concept_name = reference['topic']
            # Check last displayed items
            elif 1 <= ref_num <= len(last_displayed_items):
                # Try to extract concept from displayed item
                item = last_displayed_items[ref_num - 1]
                concept_name = _extract_concept_from_item(item)
            else:
                console.print(f"[red]Invalid reference number: {ref_num}[/red]")
                return
        else:
            # Direct concept name
            concept_name = concept_or_number.strip()
        
        if not concept_name:
            console.print("[red]Unable to determine concept for exploration[/red]")
            return
        
        console.print(f"🌳 [cyan]Launching concept exploration for: {concept_name}[/cyan]")
        from mentat.core.config import (
            CONCEPT_EXPLORATION_BATCH_SIZE,
            CONCEPT_EXPLORATION_DEFAULT_DEPTH,
            CONCEPT_EXPLORATION_MAX_CONCEPTS,
        )
        from mentat.core.llm import get_task_llm_route
        concept_route = get_task_llm_route("CONCEPT_EXPLORATION", openrouter_client)
        console.print(
            f"[dim]ConceptExplorer provider: {concept_route.provider} • "
            f"model: {concept_route.model} ({concept_route.model_source}) • "
            f"depth={CONCEPT_EXPLORATION_DEFAULT_DEPTH}, "
            f"max_concepts={CONCEPT_EXPLORATION_MAX_CONCEPTS}, "
            f"batch={CONCEPT_EXPLORATION_BATCH_SIZE}[/dim]"
        )
        
        # Get user's knowledge context
        with show_thinking_spinner("Analyzing your knowledge context..."):
            user_memories = db.comprehensive_search(user_id, concept_name)[:5]
            knowledge_analysis = integration_manager.analyze_user_knowledge_gaps(
                concept_name, user_memories, user_id
            )
        
        # Build deep hierarchical concept tree
        with show_thinking_spinner("Building deep concept exploration tree..."):
            from mentat.concepts.concept_integration import build_deep_hierarchical_concept_tree
            
            concept_tree = build_deep_hierarchical_concept_tree(
                concept_name, user_id, db, openrouter_client
            )
        
        if not concept_tree or not concept_tree.get('concepts'):
            console.print(f"[yellow]No related concepts found for '{concept_name}'[/yellow]")
            return
        
        # Display the deep hierarchical concept tree
        if concept_tree.get('deep_hierarchy'):
            # Use new 3-level hierarchical formatting
            concept_display = integration_manager.format_deep_hierarchical_concept_tree(
                concept_tree,
                interactive=interactive,
            )
        else:
            # Fallback to regular 2-level formatting if deep hierarchy failed
            concept_display = integration_manager.format_hierarchical_concept_tree(
                concept_tree,
                interactive=interactive,
            )
        
        console.print()  # Add spacing
        formatted_concept_display = format_content_with_markdown(concept_display)
        from mentat.cli.display import create_standard_panel
        concept_panel = create_standard_panel(formatted_concept_display, "🌳 Deep Concept Exploration", None, "bright_green")
        console.print(concept_panel)
        
        # Show knowledge analysis if available
        if knowledge_analysis.get('knowledge_gaps'):
            console.print()
            gaps_text = "\n".join([f"• {gap}" for gap in knowledge_analysis['knowledge_gaps']])
            console.print(create_standard_panel(
                gaps_text,
                "🎯 Knowledge Gaps Identified",
                border_style="bright_yellow"
            ))
        
        # Clear existing references when entering deep concept exploration mode
        # This ensures concept exploration numbers don't conflict with chat references
        if global_enhanced_chat:
            global_enhanced_chat.clear_references()
            
            # Add all concepts (main + sub + deep) as explorable references to enhanced chat
            concept_counter = 1
            for main_concept in concept_tree['concepts']:
                # Add main concept
                global_enhanced_chat.add_reference(
                    topic=main_concept['name'],
                    context=f"Main concept in deep exploration of '{concept_name}'",
                    personal_context=main_concept.get('description', '')
                )
                concept_counter += 1
                
                # Add sub-concepts
                for sub_concept in main_concept.get('sub_concepts', []):
                    global_enhanced_chat.add_reference(
                        topic=sub_concept['name'],
                        context=f"Sub-concept under '{main_concept['name']}'",
                        personal_context=sub_concept.get('description', '')
                    )
                    concept_counter += 1
                    
                    # Add deep concepts
                    for deep_concept in sub_concept.get('deep_concepts', []):
                        global_enhanced_chat.add_reference(
                            topic=deep_concept['name'],
                            context=f"Deep concept under '{sub_concept['name']}'",
                            personal_context=deep_concept.get('description', '')
                        )
                        concept_counter += 1
        
        # Update last_displayed_items for /view command
        explorable_concepts = []
        concept_counter = 1
        for main_concept in concept_tree['concepts']:
            # Add main concept
            explorable_concepts.append({
                'id': f"concept_{concept_counter}",
                'content': f"Concept: {main_concept['name']}\n\nDescription: {main_concept.get('description', 'No description available')}",
                'command_type': 'deep_concept_exploration',
                'timestamp': concept_tree.get('generation_time', ''),
                'concept_data': main_concept
            })
            concept_counter += 1
            
            # Add sub-concepts
            for sub_concept in main_concept.get('sub_concepts', []):
                explorable_concepts.append({
                    'id': f"concept_{concept_counter}",
                    'content': f"Concept: {sub_concept['name']}\n\nDescription: {sub_concept.get('description', 'No description available')}",
                    'command_type': 'deep_concept_exploration',
                    'timestamp': concept_tree.get('generation_time', ''),
                    'concept_data': sub_concept
                })
                concept_counter += 1
                
                # Add deep concepts
                for deep_concept in sub_concept.get('deep_concepts', []):
                    explorable_concepts.append({
                        'id': f"concept_{concept_counter}",
                        'content': f"Concept: {deep_concept['name']}\n\nDescription: {deep_concept.get('description', 'No description available')}",
                        'command_type': 'deep_concept_exploration',
                        'timestamp': concept_tree.get('generation_time', ''),
                        'concept_data': deep_concept
                    })
                    concept_counter += 1
        
        last_displayed_items.clear()
        last_displayed_items.extend(explorable_concepts)
        
        console.print()
        if interactive:
            console.print("[dim]💡 Use /explore <number> to discover related concepts • /explain <number> for detailed explanations[/dim]")
        else:
            console.print('[dim]💡 Use mentat explore "<concept>" to discover related concepts • mentat explain "<concept>" for detailed explanations[/dim]')
        
    except ImportError as e:
        console.print(f"[red]Concept exploration not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error during concept exploration: {e}[/red]")


def handle_explain_command(concept_or_number: str, user_id: str, db: MemoryDatabase,
                          openrouter_client: Any, global_enhanced_chat: Any = None,
                          last_displayed_items: Optional[List[Dict]] = None) -> None:
    """
    Handle /explain command for detailed concept explanations without generating more concepts
    
    Args:
        concept_or_number: Either a concept name or reference number
        user_id: User identifier
        db: Database instance
        openrouter_client: OpenRouter client for LLM interactions
        global_enhanced_chat: Enhanced chat system instance
        last_displayed_items: List for resolving numbered concept exploration items
    """
    try:
        from mentat.concepts.concept_integration import ConceptIntegrationManager
        
        integration_manager = ConceptIntegrationManager(db, openrouter_client)
        
        # Determine if input is a number (reference) or concept name
        concept_name = None
        
        if concept_or_number.isdigit():
            # Handle reference number
            ref_num = int(concept_or_number)
            
            # Check AI references first
            if global_enhanced_chat and global_enhanced_chat.get_reference(str(ref_num)):
                reference = global_enhanced_chat.get_reference(str(ref_num))
                concept_name = reference['topic']
            elif last_displayed_items and 1 <= ref_num <= len(last_displayed_items):
                item = last_displayed_items[ref_num - 1]
                concept_name = _extract_concept_from_item(item)
            else:
                console.print(f"[red]Invalid reference number: {ref_num}[/red]")
                return
        else:
            # Direct concept name
            concept_name = concept_or_number.strip()
        
        if not concept_name:
            console.print("[red]Unable to determine concept for explanation[/red]")
            return
        
        console.print(f"📚 [cyan]Generating detailed explanation for: {concept_name}[/cyan]")
        
        # Generate comprehensive concept explanation
        with show_thinking_spinner("📖 Researching and analyzing concept..."):
            explanation = integration_manager.generate_concept_explanation(
                concept_name, user_id, "gpt-4o-mini"  # Use current model from context
            )
        
        # Display the explanation with enhanced markdown rendering
        if should_use_markdown_rendering(explanation):
            panel = render_markdown_to_panel(
                explanation,
                f"📚 Concept Explanation: {concept_name}",
                None,
                "bright_magenta"
            )
        else:
            formatted_explanation = format_content_with_markdown(explanation)
            panel = create_standard_panel(
                formatted_explanation,
                f"📚 Concept Explanation: {concept_name}",
                None, 
                "bright_magenta"
            )
        console.print(panel)
        
        # Extract learning pathways and create explorable references
        learning_concepts = _extract_learning_pathways(explanation)
        if learning_concepts and global_enhanced_chat:
            global_enhanced_chat.clear_references()
            for i, concept_name in enumerate(learning_concepts, 1):
                global_enhanced_chat.add_reference(
                    topic=concept_name,
                    context=f"Learning pathway from '{concept_name}' explanation",
                    personal_context=f"Suggested area to explore further"
                )
        
        # Show additional options
        console.print()
        if learning_concepts:
            console.print("[dim]💡 Next steps:[/dim]")
            console.print("[dim]   • Use [cyan]/explore <number>[/cyan] to explore learning pathways above[/dim]")
            console.print("[dim]   • Use [cyan]/explore <concept>[/cyan] to discover other related concepts[/dim]")
            console.print("[dim]   • Use [cyan]/save[/cyan] to capture this explanation as a memory[/dim]")
        else:
            console.print("[dim]💡 Next steps:[/dim]")
            console.print("[dim]   • Use [cyan]/explore <concept>[/cyan] to discover related concepts[/dim]")
            console.print("[dim]   • Use [cyan]/save[/cyan] to capture this explanation as a memory[/dim]")
        
    except ImportError as e:
        console.print(f"[red]Concept explanation not available: {e}[/red]")
    except Exception as e:
        console.print(f"[red]Error generating concept explanation: {e}[/red]")


def handle_connect_command(concept1: str, concept2: str, user_id: str,
                          openrouter_client: Any, db: MemoryDatabase,
                          current_model: str = None) -> None:
    """
    Handle /connect command for concept relationship analysis

    Args:
        concept1: First concept or reference number
        concept2: Second concept or reference number
        user_id: User identifier
        openrouter_client: OpenRouter client
        db: Database instance
        current_model: Legacy model hint; concept connection uses CONCEPT_CONNECTION_* routing.
    """
    try:
        from mentat.concepts.concept_integration import ConceptIntegrationManager
        
        integration_manager = ConceptIntegrationManager(db, openrouter_client)
        
        # Resolve concept names (handle numbers if needed)
        name1 = _resolve_concept_name(concept1)
        name2 = _resolve_concept_name(concept2)
        
        console.print(f"🔗 [cyan]Analyzing connections between: {name1} ↔ {name2}[/cyan]")
        
        # Generate connection analysis
        with show_thinking_spinner("Analyzing conceptual relationships..."):
            connection_analysis = _generate_concept_connection_analysis(
                name1, name2, user_id, openrouter_client, db, current_model
            )
        
        # Display the analysis with enhanced markdown rendering
        if connection_analysis:
            if should_use_markdown_rendering(connection_analysis):
                panel = render_markdown_to_panel(
                    connection_analysis,
                    f"🔗 Connection Analysis: {name1} ↔ {name2}",
                    None,
                    "bright_magenta"
                )
            else:
                formatted_analysis = format_content_with_markdown(connection_analysis)
                panel = create_standard_panel(
                    formatted_analysis,
                    f"🔗 Connection Analysis: {name1} ↔ {name2}",
                    None,
                    "bright_magenta"
                )
            console.print(panel)
        else:
            console.print(f"[yellow]Unable to find meaningful connections between '{name1}' and '{name2}'[/yellow]")
            
    except Exception as e:
        console.print(f"[red]Error analyzing concept connections: {e}[/red]")


# Helper functions for concept exploration

def _extract_concept_from_item(item: Dict) -> Optional[str]:
    """Extract a concept name from a displayed item"""
    content = item.get('content', '')
    
    # Try to extract from concept exploration items
    if item.get('command_type') in ('concept_exploration', 'deep_concept_exploration'):
        concept_data = item.get('concept_data', {})
        return concept_data.get('name')
    
    # Try to extract from regular content (first meaningful word/phrase)
    # This is a simple heuristic - could be improved
    words = content.split()
    if words:
        # Return first few words as concept
        return ' '.join(words[:3])
    
    return None


def _extract_learning_pathways(explanation: str) -> List[str]:
    """Extract numbered learning pathway concepts from LLM explanation"""
    import re
    
    concepts = []
    
    # Look for numbered items in learning pathways section
    # Pattern: number followed by concept name (before colon)
    learning_section_match = re.search(r'\*\*Learning pathways:\*\*(.*?)(?:\*\*|$)', explanation, re.DOTALL | re.IGNORECASE)
    
    if learning_section_match:
        learning_text = learning_section_match.group(1)
        
        # Find numbered items: "1 Machine Learning and AI Fundamentals:"
        numbered_items = re.findall(r'(\d+)\s+([^:]+?):', learning_text)
        
        for number, concept_name in numbered_items:
            # Clean up the concept name
            clean_concept = concept_name.strip()
            if clean_concept and len(clean_concept) > 3:  # Avoid very short matches
                concepts.append(clean_concept)
    
    return concepts[:5]  # Limit to prevent too many references


def _resolve_concept_name(concept_input: str) -> str:
    """Resolve concept input to a name (handle numbers vs. names)"""
    if concept_input.isdigit():
        # For now, just return as-is since we don't have reference context here
        # In a full implementation, this would resolve reference numbers
        return f"Concept#{concept_input}"
    return concept_input.strip()


def _generate_concept_connection_analysis(concept1: str, concept2: str, user_id: str,
                                        openrouter_client: Any, db: MemoryDatabase,
                                        current_model: str = None) -> str:
    """Generate analysis of connections between two concepts"""
    try:
        # Get user's memories related to both concepts
        memories1 = db.comprehensive_search(user_id, concept1)[:3]
        memories2 = db.comprehensive_search(user_id, concept2)[:3]
        
        # Build context for analysis
        context = f"User's related memories for {concept1}:\n"
        for i, mem in enumerate(memories1, 1):
            context += f"{i}. {mem.get('content', '')[:150]}...\n"
        
        context += f"\nUser's related memories for {concept2}:\n"
        for i, mem in enumerate(memories2, 1):
            context += f"{i}. {mem.get('content', '')[:150]}...\n"
        
        # Generate connection analysis
        prompt = f"""Analyze the conceptual connections between "{concept1}" and "{concept2}".

Provide a comprehensive analysis covering:

**Direct Connections:**
- How these concepts relate directly to each other
- Shared principles, methods, or applications

**Bridging Concepts:**
- Intermediate concepts that connect these two
- Common frameworks or domains they both belong to

**Practical Intersections:**
- Real-world scenarios where both concepts apply
- How understanding one helps with the other

**Learning Pathways:**
- How studying one concept could lead to the other
- Prerequisites and natural progressions

**From User's Context:**
{context}

**Personal Connections:**
- How these concepts relate in the user's specific context
- Opportunities for synthesis or cross-application

Keep the analysis practical and focused on learning value."""

        from mentat.core.config import CONCEPT_CONNECTION_MAX_TOKENS
        from mentat.core.llm import get_task_llm_route

        route = get_task_llm_route("CONCEPT_CONNECTION", openrouter_client)
        if not route.client:
            return f"Concept connection route unavailable: {route.model_source}"

        return complete(
            route.client,
            route.model,
            [{"role": "user", "content": prompt}],
            max_tokens=CONCEPT_CONNECTION_MAX_TOKENS,
            temperature=0.3
        )
        
    except Exception as e:
        return f"Error generating connection analysis: {e}"
