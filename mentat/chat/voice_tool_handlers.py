"""
Voice conversation tool handler adapter.

This module forwards voice tool calls to the shared tool handlers.
"""

from typing import Any, Dict, Optional

from mentat.chat.tools import execute_tool as execute_shared_tool


async def execute_tool(
    function_name: str,
    arguments: Dict[str, Any],
    user_id: str,
    logger: Optional[Any] = None,
) -> Dict[str, Any]:
    """
    Execute a voice conversation tool via the shared handler layer.

    Args:
        function_name: Name of the tool to execute
        arguments: Tool arguments
        user_id: User ID for database queries
        logger: Optional logger for debugging

    Returns:
        dict: Tool execution result
    """
    context: Dict[str, Any] = {
        "user_id": user_id,
        "channel": "voice",
    }
    if logger is not None:
        context["logger"] = logger
    return await execute_shared_tool(function_name, arguments, context)
