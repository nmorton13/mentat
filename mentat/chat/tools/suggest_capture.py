"""Tool: suggest_capture - Suggest capturing a significant insight."""

from typing import Any, Dict

from mentat.chat.tools.base import ToolSpec, get_logger

PARAMS = {
    "type": "object",
    "properties": {
        "content": {
            "type": "string",
            "description": "The insight/idea to suggest capturing.",
        },
        "reason": {
            "type": "string",
            "description": "Why this is worth capturing.",
        },
        "suggested_tags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "1-3 relevant tags for organizing the capture.",
        },
    },
    "required": ["content", "reason"],
}


async def handler(arguments: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Suggest capturing an insight (does not actually save - just suggests)."""
    content = arguments.get("content", "").strip()
    reason = arguments.get("reason", "").strip()
    suggested_tags = arguments.get("suggested_tags", [])
    log = get_logger(context)

    if not content:
        return {"success": False, "error": "No content provided"}
    if not reason:
        return {"success": False, "error": "No reason provided"}

    log.info("suggest_capture: %s", reason)

    return {
        "success": True,
        "suggestion_made": True,
        "content": content,
        "reason": reason,
        "suggested_tags": suggested_tags or [],
        "analysis": "This information may warrant archival",
    }


spec = ToolSpec(
    name="suggest_capture",
    description=(
        "Suggest capturing a significant insight. Use sparingly and only for "
        "meaningful moments."
    ),
    parameters=PARAMS,
    channels={"chat", "voice"},
    handler=handler,
)
