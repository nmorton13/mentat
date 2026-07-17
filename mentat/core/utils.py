"""
Shared utility functions for MENTAT.

This module provides common utilities used across the codebase to avoid
code duplication and maintain a single source of truth for shared functionality.
"""

import json
from typing import Dict, Optional, Tuple, Any, List


def standardize_truncation(
    text: Optional[str],
    max_length: int,
    ellipsis: str = "..."
) -> Optional[str]:
    """
    Standardize text truncation with smart breaking and ellipsis handling.

    Performs intelligent text truncation that avoids breaking URLs or words
    awkwardly. Used throughout the codebase to ensure consistent text
    length limits while maintaining readability.

    Args:
        text: The text to truncate. If None or empty, returns as-is.
        max_length: Maximum allowed length for the truncated text
        ellipsis: String to append when text is truncated. Defaults to "...".

    Returns:
        The truncated text with ellipsis if needed, or the original
        text if it was within the length limit. Returns None if input was None.

    Examples:
        >>> standardize_truncation("Short text", 100)
        'Short text'
        >>> standardize_truncation("This is a very long text that needs truncation", 20)
        'This is a very long...'
    """
    if not text:
        return text

    if len(text) <= max_length:
        return text

    # Find a good breaking point (avoid breaking in the middle of words or URLs)
    truncated = text[:max_length]

    # Don't break in the middle of a URL
    if 'http' in truncated and truncated.count('http') != text[:max_length + 10].count('http'):
        # Find the last complete URL
        last_http = truncated.rfind('http')
        if last_http > max_length - 50:  # If URL is near the end, break before it
            truncated = text[:last_http].rstrip()
    else:
        # Break at word boundary if possible
        last_space = truncated.rfind(' ')
        if last_space > max_length - 20:  # Don't break too early
            truncated = text[:last_space]

    return truncated + ellipsis


def parse_item_metadata(item: Dict[str, Any]) -> Tuple[Dict[str, Any], Optional[str], Optional[Dict[str, Any]]]:
    """
    Parse metadata JSON from a memory item and extract common fields.

    Memory items store metadata as either a dict or a JSON string. This utility
    handles both cases and safely extracts commonly-used fields like source info
    and web context.

    Args:
        item: Memory item dictionary containing a 'metadata' key

    Returns:
        A tuple containing:
        - metadata_dict: Parsed metadata as a dictionary
        - source_info: The 'source' field from metadata, if present
        - web_context: The 'web_context' field from metadata, if present

    Examples:
        >>> item = {'metadata': '{"source": "web", "web_context": {"title": "Example"}}'}
        >>> metadata, source, web = parse_item_metadata(item)
        >>> print(source)
        'web'
        >>> print(web['title'])
        'Example'
    """
    metadata = item.get('metadata', {})

    # Handle metadata stored as JSON string
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata) if metadata else {}
        except (json.JSONDecodeError, ValueError):
            metadata = {}

    # Extract commonly-used fields
    source_info = metadata.get('source')
    web_context = metadata.get('web_context')

    return metadata, source_info, web_context


def parse_entities_from_metadata(metadata: Dict[str, Any]) -> Dict[str, List[str]]:
    """
    Extract structured entities from metadata dictionary.

    Args:
        metadata: Parsed metadata dictionary

    Returns:
        Dictionary of entity lists by category (people, technologies, projects, etc.)

    Examples:
        >>> metadata = {'entities': {'people': ['Alice', 'Bob'], 'projects': ['MENTAT']}}
        >>> entities = parse_entities_from_metadata(metadata)
        >>> print(entities['people'])
        ['Alice', 'Bob']
    """
    return metadata.get('entities', {})
