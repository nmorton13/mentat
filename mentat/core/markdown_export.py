"""
Automatic markdown export functionality for MENTAT memories.
Creates organized, date-based markdown files as memories are captured.
"""

import re
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .config import MARKDOWN_EXPORT_ENABLED, MARKDOWN_EXPORT_PATH
from .private_files import ensure_private_directory, open_private_text


def get_content_type_emoji(command_type: str) -> str:
    """Get emoji for content type"""
    emoji_map = {
        'idea': '💡',
        'dump': '🧠',
        'ask': '❓',
        'link': '🔗',
        'capture': '📝',
        'reflection': '🤔',
        'task': '✅',
        'ai_response': '🤖'
    }
    return emoji_map.get(command_type, '📝')


def get_content_type_title(command_type: str) -> str:
    """Get human-readable title for content type"""
    title_map = {
        'idea': 'Ideas',
        'dump': 'Thoughts',
        'ask': 'Questions',
        'link': 'Links',
        'capture': 'Captures',
        'reflection': 'Reflections',
        'task': 'Tasks',
        'ai_response': 'AI Responses'
    }
    return title_map.get(command_type, 'Captures')


def get_markdown_command_type(command_type: str, metadata: Optional[Dict[str, Any]] = None) -> str:
    """Prefer source-aware types for markdown display without changing database types."""
    source_info = (metadata or {}).get('source', {})
    if source_info.get('type') == 'ai_response':
        return 'ai_response'
    return command_type


def format_timestamp_for_display(timestamp: str) -> str:
    """Convert timestamp to readable time format"""
    try:
        # Parse ISO format timestamp
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        return dt.strftime('%H:%M')
    except (ValueError, AttributeError):
        return "??:??"


def format_timestamp_for_metadata(timestamp: str) -> str:
    """Convert ISO timestamps to a readable date/time string for metadata blocks."""
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d %H:%M')
    except (ValueError, AttributeError):
        return str(timestamp)


def format_tags_for_markdown(tags: List[str]) -> str:
    """Format tags for markdown display"""
    if not tags:
        return ""

    seen = set()
    normalized = []
    for tag in tags:
        clean_tag = normalize_tag(tag)
        if clean_tag and clean_tag not in seen:
            seen.add(clean_tag)
            normalized.append(f"#{clean_tag}")

    return " ".join(normalized[:5])  # Limit to 5 tags


def format_entities_for_markdown(metadata: Dict[str, Any]) -> str:
    """Extract and format key entities for markdown display"""
    if not metadata or 'entities' not in metadata:
        return ""
    
    entities = metadata.get('entities', {})
    entity_parts = []
    
    # Show most relevant entity types
    for entity_type in ['people', 'technologies', 'projects', 'organizations']:
        if entity_type in entities and entities[entity_type]:
            # Show first 2 entities of each type
            items = entities[entity_type][:2]
            for item in items:
                normalized = normalize_entity_link(item)
                if normalized:
                    entity_parts.append(f"[[{normalized}]]")
    
    return " ".join(entity_parts[:4])  # Limit total entities shown


def get_markdown_file_path(timestamp: str) -> Path:
    """Get the markdown file path for a given timestamp"""
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        year = dt.strftime('%Y')
        month = dt.strftime('%m-%B')
        filename = dt.strftime('%Y-%m-%d.md')
        
        file_path = Path(MARKDOWN_EXPORT_PATH) / year / month / filename
        return file_path
    except (ValueError, AttributeError):
        # Fallback to current date if timestamp parsing fails
        now = datetime.now()
        year = now.strftime('%Y')
        month = now.strftime('%m-%B')
        filename = now.strftime('%Y-%m-%d.md')
        
        file_path = Path(MARKDOWN_EXPORT_PATH) / year / month / filename
        return file_path


def create_daily_header(timestamp: str) -> str:
    """Create header for daily markdown file"""
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        date_str = dt.strftime('%B %d, %Y')
        return f"# {date_str}\n\n"
    except (ValueError, AttributeError):
        now = datetime.now()
        date_str = now.strftime('%B %d, %Y')
        return f"# {date_str}\n\n"


def format_memory_for_markdown(
    content: str, 
    command_type: str, 
    tags: List[str], 
    metadata: Dict[str, Any], 
    timestamp: str
) -> str:
    """Format a single memory entry for markdown with comprehensive metadata"""
    time_str = format_timestamp_for_display(timestamp)
    effective_command_type = get_markdown_command_type(command_type, metadata)
    emoji = get_content_type_emoji(effective_command_type)
    tags_str = format_tags_for_markdown(tags)
    entities_str = format_entities_for_markdown(metadata)
    
    # Build the metadata line (tags and key entities for readability)
    meta_parts = [part for part in [tags_str, entities_str] if part]
    meta_line = f" - {' '.join(meta_parts)}" if meta_parts else ""
    
    # Format content (handle multi-line content)
    formatted_content = content.strip()
    if '\n' in formatted_content:
        # Multi-line content - indent it
        lines = formatted_content.split('\n')
        formatted_content = lines[0] + '\n' + '\n'.join(f'  {line}' for line in lines[1:])
    
    # Start building the entry
    entry_parts = [f"**{time_str}** {emoji}{meta_line}  \n{formatted_content}"]
    
    # Add comprehensive metadata section
    metadata_sections = []

    source_info = metadata.get('source') if metadata else None
    prompt_text = ""
    if source_info and source_info.get('type') == 'ai_response':
        response_info = []
        if source_info.get('prompt'):
            prompt_lines = str(source_info['prompt']).strip().split('\n')
            formatted_prompt = prompt_lines[0]
            if len(prompt_lines) > 1:
                formatted_prompt += '\n' + '\n'.join(f'  {line}' for line in prompt_lines[1:])
            prompt_text = f"**Prompt:**\n{formatted_prompt}\n\n**Response:**\n"
        if source_info.get('model'):
            response_info.append(f"Model: `{source_info['model']}`")
        if source_info.get('command'):
            response_info.append(f"Command: `/{source_info['command']}`")
        if source_info.get('context'):
            response_info.append(f"Context: `{source_info['context']}`")
        if source_info.get('timestamp'):
            response_info.append(f"Saved: {format_timestamp_for_metadata(source_info['timestamp'])}")
        if response_info:
            metadata_sections.append(f"🤖 **AI Response:** {', '.join(response_info)}")

    if prompt_text:
        entry_parts = [f"**{time_str}** {emoji}{meta_line}  \n{prompt_text}{formatted_content}"]
    
    # AI Analysis Data
    if metadata.get('ai_analyzed'):
        ai_info = []
        if metadata.get('confidence'):
            ai_info.append(f"Confidence: {metadata['confidence']:.1%}")
        if metadata.get('type') or command_type:
            ai_info.append(f"Type: {metadata.get('type', command_type)}")
        if ai_info:
            metadata_sections.append(f"📊 **AI Analysis:** {', '.join(ai_info)}")
    
    # Full Entity Breakdown
    if metadata.get('entities'):
        entities = metadata['entities']
        entity_details = []
        for category, items in entities.items():
            if items:
                formatted_items = [f"`{item}`" for item in items]
                entity_details.append(f"*{category.title()}:* {', '.join(formatted_items)}")
        if entity_details:
            metadata_sections.append(f"🏷️ **Entities:** {' | '.join(entity_details)}")
    
    # URLs
    if metadata.get('url'):
        metadata_sections.append(f"🌐 **URL:** {metadata['url']}")
        if metadata.get('title'):
            metadata_sections.append(f"📄 **Title:** {metadata['title']}")
    
    # Actionable Items
    actionable_items = metadata.get('actionable_items', [])
    if actionable_items:
        action_list = []
        for item in actionable_items:
            if isinstance(item, dict):
                action = item.get('action', str(item))
                priority = item.get('priority', 'medium')
                project = f" ({item['project']})" if item.get('project') else ''
                time_icon = '⏰' if item.get('time_sensitive') else ''
                action_list.append(f"- {action}{project} [{priority}]{time_icon}")
                if item.get('context'):
                    action_list.append(f"*Context:* {item['context']}")
                if item.get('due_date'):
                    action_list.append(f"*Due:* {item['due_date']}")
            else:
                action_list.append(f"- {item}")
        if action_list:
            formatted_actions = "\n".join(f"  {line}" for line in action_list)
            metadata_sections.append(f"✅ **Action Items:**\n{formatted_actions}")
    
    # AI-Generated Summary
    ai_summary = metadata.get('ai_summary') or metadata.get('summary')
    if ai_summary and ai_summary.strip() and ai_summary.strip() != content.strip():
        metadata_sections.append(f"📝 **AI Summary:** {ai_summary.strip()}")
    
    # Enhanced Content (if different from original)
    if metadata.get('enhanced_content') and metadata['enhanced_content'] != content.strip():
        metadata_sections.append(f"✨ **Enhanced:** {metadata['enhanced_content']}")
    
    # Web Context Data
    if metadata.get('web_context'):
        web_ctx = metadata['web_context']
        if web_ctx.get('web_context_summary'):
            metadata_sections.append(f"🌐 **Web Context:** {web_ctx['web_context_summary']}")
    
    # Theme Analysis
    if metadata.get('themes'):
        themes = [f"`{theme}`" for theme in metadata['themes']]
        metadata_sections.append(f"🎯 **Themes:** {', '.join(themes)}")
    
    # User ID (for multi-user systems)
    if metadata.get('user_id'):
        metadata_sections.append(f"👤 **User:** {metadata['user_id']}")
    
    # Add metadata sections if any exist
    if metadata_sections:
        entry_parts.append("\n" + "\n".join(metadata_sections))
    
    return "\n".join(entry_parts) + "\n\n"


def normalize_tag(tag: str) -> str:
    """Normalize tags for Obsidian-friendly output."""
    if tag is None:
        return ""
    clean = str(tag).strip().lstrip('#')
    clean = clean.replace(' ', '-')
    return clean.lower()


def normalize_entity_link(entity: str) -> str:
    """Normalize entity names for Obsidian wiki links."""
    if entity is None:
        return ""
    clean = str(entity).strip()
    return clean.replace(' ', '-')


def parse_frontmatter_value(value: str) -> Any:
    """Parse a YAML frontmatter value into a Python type."""
    value = value.strip()
    if value.startswith('[') and value.endswith(']'):
        inner = value[1:-1].strip()
        if not inner:
            return []
        quoted = re.findall(r'"([^"]*)"', inner)
        if quoted:
            return quoted
        return [item.strip().strip('"') for item in inner.split(',') if item.strip()]
    return value


def split_frontmatter(content: str) -> Tuple[Dict[str, Any], str]:
    """Split YAML frontmatter from the rest of the content."""
    if not content.startswith('---\n'):
        return {}, content

    lines = content.splitlines(keepends=True)
    for idx in range(1, len(lines)):
        if lines[idx].strip() == '---':
            frontmatter_lines = [line.strip() for line in lines[1:idx]]
            frontmatter: Dict[str, Any] = {}
            for line in frontmatter_lines:
                if not line or ':' not in line:
                    continue
                key, value = line.split(':', 1)
                frontmatter[key.strip()] = parse_frontmatter_value(value)
            return frontmatter, ''.join(lines[idx + 1:])

    return {}, content


def format_frontmatter_list(values: List[str]) -> str:
    if not values:
        return "[]"

    def quote(item: str) -> str:
        return f"\"{str(item).replace('\"', '\\\\\"')}\""

    return "[ " + ", ".join(quote(value) for value in values) + " ]"


def build_frontmatter(frontmatter: Dict[str, Any]) -> str:
    ordered_fields = [
        'date',
        'time',
        'type',
        'tags',
        'people',
        'orgs',
        'projects',
        'source_url'
    ]
    lines = ["---\n"]
    for field in ordered_fields:
        value = frontmatter.get(field)
        if field == 'date':
            lines.append(f"date: {value or ''}\n")
        else:
            values = value if isinstance(value, list) else ([] if value in (None, '') else [value])
            lines.append(f"{field}: {format_frontmatter_list(values)}\n")
    lines.append("---\n\n")
    return "".join(lines)


def format_date_for_frontmatter(timestamp: str) -> str:
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        return dt.strftime('%Y-%m-%d')
    except (ValueError, AttributeError):
        return datetime.now().strftime('%Y-%m-%d')


def extract_frontmatter_updates(
    command_type: str,
    tags: List[str],
    metadata: Dict[str, Any],
    timestamp: str
) -> Dict[str, Any]:
    time_str = format_timestamp_for_display(timestamp)
    date_str = format_date_for_frontmatter(timestamp)
    effective_command_type = get_markdown_command_type(command_type, metadata)

    normalized_tags = []
    seen_tags = set()
    for tag in tags:
        clean = normalize_tag(tag)
        if clean and clean not in seen_tags:
            seen_tags.add(clean)
            normalized_tags.append(clean)

    entities = metadata.get('entities', {}) if metadata else {}
    people = list(entities.get('people', []))
    orgs = list(entities.get('organizations', []))
    projects = list(entities.get('projects', []))

    urls = []
    if metadata:
        if metadata.get('url'):
            urls.append(metadata['url'])
        if metadata.get('urls'):
            urls.extend([url for url in metadata['urls'] if url])
        if metadata.get('fetched_url'):
            urls.append(metadata['fetched_url'])

    return {
        'date': date_str,
        'time': [time_str] if time_str else [],
        'type': [effective_command_type] if effective_command_type else [],
        'tags': normalized_tags,
        'people': people,
        'orgs': orgs,
        'projects': projects,
        'source_url': urls
    }


def merge_frontmatter(
    frontmatter: Dict[str, Any],
    updates: Dict[str, Any]
) -> Dict[str, Any]:
    merged = frontmatter.copy()
    merged['date'] = merged.get('date') or updates.get('date', '')

    for field in ['time', 'type', 'tags', 'people', 'orgs', 'projects', 'source_url']:
        existing = merged.get(field, [])
        if isinstance(existing, str):
            existing = [existing] if existing else []
        update_values = updates.get(field, [])
        if isinstance(update_values, str):
            update_values = [update_values]

        seen = set()
        combined = []
        for value in existing + update_values:
            if value and value not in seen:
                seen.add(value)
                combined.append(value)
        merged[field] = combined

    return merged


def save_memory_to_markdown(
    content: str,
    command_type: str,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    timestamp: Optional[str] = None,
    user_id: Optional[str] = None
) -> bool:
    """
    Save a memory to the appropriate daily markdown file.
    
    Args:
        content: The memory content
        command_type: Type of memory (idea, dump, ask, etc.)
        tags: List of tags associated with the memory
        metadata: Structured metadata dictionary
        timestamp: ISO format timestamp (uses current time if None)
    
    Returns:
        bool: True if successful, False otherwise
    """
    if not MARKDOWN_EXPORT_ENABLED:
        return True  # Silently skip if disabled
    
    try:
        # Use current timestamp if none provided
        if not timestamp:
            timestamp = datetime.now().isoformat()
        
        # Ensure we have lists/dicts
        tags = tags or []
        metadata = metadata or {}
        
        # Get the file path
        file_path = get_markdown_file_path(timestamp)
        
        # Ensure directory exists
        ensure_private_directory(file_path.parent)
        
        # Check if file exists to determine if we need a header
        file_exists = file_path.exists()
        
        # Add user_id to metadata if provided
        if user_id and metadata is None:
            metadata = {}
        if user_id:
            metadata = metadata.copy() if metadata else {}
            metadata['user_id'] = user_id
        
        # Format the memory entry
        memory_entry = format_memory_for_markdown(
            content, command_type, tags, metadata, timestamp
        )

        # Load existing content if needed for frontmatter merge
        existing_content = ""
        if file_exists:
            existing_content = file_path.read_text(encoding='utf-8')

        frontmatter, body = split_frontmatter(existing_content)
        frontmatter_updates = extract_frontmatter_updates(
            command_type,
            tags,
            metadata,
            timestamp
        )
        merged_frontmatter = merge_frontmatter(frontmatter, frontmatter_updates)

        if not body.strip():
            body = create_daily_header(timestamp)
        else:
            stripped_body = body.lstrip('\n')
            if not stripped_body.startswith('# '):
                body = create_daily_header(timestamp) + stripped_body
            else:
                body = stripped_body

        updated_content = build_frontmatter(merged_frontmatter) + body + memory_entry

        with open_private_text(file_path) as f:
            f.write(updated_content)
        
        return True
        
    except Exception as e:
        # Log error but don't fail the memory save operation
        print(f"Warning: Failed to save memory to markdown: {e}")
        return False


def create_markdown_directories() -> bool:
    """Create the base markdown export directory structure"""
    try:
        ensure_private_directory(MARKDOWN_EXPORT_PATH)
        return True
    except Exception as e:
        print(f"Warning: Could not create markdown directories: {e}")
        return False


def get_markdown_export_status() -> Dict[str, Any]:
    """Get status information about markdown export"""
    return {
        'enabled': MARKDOWN_EXPORT_ENABLED,
        'export_path': MARKDOWN_EXPORT_PATH,
        'directory_exists': Path(MARKDOWN_EXPORT_PATH).exists(),
        'writable': os.access(Path(MARKDOWN_EXPORT_PATH).parent, os.W_OK) if Path(MARKDOWN_EXPORT_PATH).parent.exists() else False
    }
