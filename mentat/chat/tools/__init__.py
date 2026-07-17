"""
Tool registry for chat and voice sessions.

Provides:
- get_tools(channel, schema, metadata) - Get tool definitions for a channel
- execute_tool(name, arguments, context) - Execute a tool by name
- get_conversation_tools() - Get tools for voice conversations (realtime format)
"""

import logging
from typing import Any, Dict, List, Literal, Optional

from mentat.chat.tools.base import ToolSpec, to_openai_tool, to_realtime_tool
from mentat.chat.tools.policy import get_tool_tier, tier_includes

from mentat.chat.tools.find_related_thoughts import spec as find_related_thoughts_spec
from mentat.chat.tools.check_forgotten_ideas import spec as check_forgotten_ideas_spec
from mentat.chat.tools.capture_thought import spec as capture_thought_spec
from mentat.chat.tools.suggest_capture import spec as suggest_capture_spec
from mentat.chat.tools.get_recent_activity import spec as get_recent_activity_spec

Schema = Literal["openai", "realtime"]

logger = logging.getLogger("mentat.tools")

# Registry of all tools
TOOL_SPECS: List[ToolSpec] = [
    # Memory tools
    find_related_thoughts_spec,
    check_forgotten_ideas_spec,
    capture_thought_spec,
    suggest_capture_spec,
    get_recent_activity_spec,
]


def _normalize_channel(channel: str) -> str:
    """Normalize channel name."""
    normalized = (channel or "").strip().lower()
    return normalized or "chat"


def get_tools(
    channel: str,
    schema: Schema = "openai",
    metadata: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Get tool definitions for a specific channel and schema format.

    Args:
        channel: "chat" or "voice"
        schema: "openai" (function calling) or "realtime" (Realtime API)
        metadata: Optional metadata for tier filtering

    Returns:
        List of tool definitions in the requested format
    """
    normalized = _normalize_channel(channel)
    specs = [spec for spec in TOOL_SPECS if spec.enabled and normalized in spec.channels]

    # Tier filtering. Voice keeps current behavior unless explicitly provided.
    selected_tier = None
    if metadata and metadata.get("tool_tier"):
        selected_tier = str(metadata.get("tool_tier")).strip().lower()
    elif normalized == "chat":
        selected_tier = "tier1"

    if selected_tier:
        specs = [
            spec for spec in specs
            if tier_includes(selected_tier, get_tool_tier(spec.name))
        ]

    if schema == "realtime":
        return [to_realtime_tool(spec) for spec in specs]
    if schema == "openai":
        return [to_openai_tool(spec) for spec in specs]
    raise ValueError(f"Unsupported schema: {schema}")


async def execute_tool(
    name: str,
    arguments: Dict[str, Any],
    context: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Execute a tool by name.

    Args:
        name: Tool name
        arguments: Tool arguments
        context: Execution context (user_id, channel, logger, etc.)

    Returns:
        Tool execution result
    """
    spec = next((spec for spec in TOOL_SPECS if spec.name == name), None)
    if not spec:
        logger.error("Unknown tool requested: %s", name)
        return {"success": False, "error": f"Unknown tool: {name}"}
    if not spec.enabled:
        logger.warning("Tool disabled: %s", name)
        return {"success": False, "error": f"Tool disabled: {name}"}
    try:
        return await spec.handler(arguments, context)
    except Exception as exc:
        logger.error("Tool execution failed: %s - %s", name, exc, exc_info=True)
        return {"success": False, "error": str(exc)}


def get_conversation_tools() -> List[Dict[str, Any]]:
    """Get tool definitions for voice conversations (realtime format)."""
    return get_tools(channel="voice", schema="realtime")


# For backward compatibility with old imports
__all__ = [
    "TOOL_SPECS",
    "get_tools",
    "execute_tool",
    "get_conversation_tools",
]
