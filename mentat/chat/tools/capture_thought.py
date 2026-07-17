"""Tool: capture_thought - Save a thought to memory."""

import asyncio
from datetime import datetime
from typing import Any, Dict

from mentat.chat.tools.base import (
    ToolSpec, get_logger, get_db, get_openrouter_client, get_channel,
    MENTAT_AVAILABLE, analyze_capture_content, get_current_model
)

PARAMS = {
    "type": "object",
    "properties": {
        "content": {
            "type": "string",
            "description": (
                "The thought/idea to capture. You MUST use the user's EXACT words "
                "verbatim. Do not summarize or rephrase unless explicitly asked."
            ),
        },
        "context": {
            "type": "string",
            "description": (
                "Optional: brief context about why this is being captured or "
                "what it relates to"
            ),
        },
    },
    "required": ["content"],
}


async def handler(arguments: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Capture a thought to the user's memory database."""
    content = arguments.get("content", "").strip()
    capture_context = arguments.get("context", "").strip()
    user_id = context.get("user_id")
    channel = get_channel(context)
    log = get_logger(context)

    if not content:
        return {"success": False, "error": "No content to capture"}
    if not user_id:
        return {"success": False, "error": "No user_id provided"}

    log.info("capture_thought: '%s...'", content[:50])

    db = get_db()
    if not db:
        return {"success": False, "error": "Database unavailable"}

    try:
        full_content = content
        if capture_context:
            full_content = f"{content}\n\nContext: {capture_context}"

        if channel == "clawdbot" and MENTAT_AVAILABLE:
            try:
                from mentat.core.ai import process_content_with_ai
            except Exception as exc:
                log.warning("Tool capture imports failed: %s", exc, exc_info=True)
                return {"success": False, "error": "Capture pipeline unavailable"}

            openrouter_client = get_openrouter_client()
            ai_analyzed = openrouter_client is not None
            current_model = get_current_model()
            loop = asyncio.get_event_loop()

            analysis = await loop.run_in_executor(
                None,
                lambda: analyze_capture_content(
                    full_content,
                    model=current_model,
                    client=openrouter_client,
                ),
            )

            metadata = {
                "capture_method": "tool_capture",
                "timestamp": datetime.now().isoformat(),
                "source": {
                    "type": "tool_capture",
                    "method": channel,
                    "timestamp": datetime.now().isoformat(),
                },
                "ai_analyzed": ai_analyzed,
                "confidence": analysis.get("confidence", 0.5),
                "actionable_items": analysis.get("actionable_items", []),
                "tool_context": capture_context if capture_context else None,
            }

            memory_id, tags, detected_category, themes, actionable_items, enhanced_metadata = await loop.run_in_executor(
                None,
                lambda: process_content_with_ai(
                    full_content,
                    user_id,
                    analysis.get("type", "dump"),
                    metadata=metadata,
                    model=current_model,
                    client=openrouter_client,
                ),
            )

            return {
                "success": True,
                "memory_id": memory_id,
                "message": "Captured successfully",
                "tags": tags,
                "summary": enhanced_metadata.get("ai_summary", "")[:100],
                "content_type": detected_category,
                "themes": themes,
                "actionable_items": len(actionable_items) if actionable_items else 0,
            }

        openrouter_client = get_openrouter_client()
        ai_analyzed = openrouter_client is not None and MENTAT_AVAILABLE
        if openrouter_client and MENTAT_AVAILABLE:
            current_model = get_current_model()
            analysis = analyze_capture_content(
                full_content,
                model=current_model,
                client=openrouter_client,
            )
        else:
            analysis = {
                "themes": [],
                "entities": {},
                "actionable_items": [],
                "summary": content[:100],
                "confidence": 0.5,
            }

        if channel == "voice":
            command_type = "voice_capture"
            metadata = {
                "entities": analysis.get("entities", {}),
                "actionable_items": analysis.get("actionable_items", []),
                "ai_summary": analysis.get("summary", ""),
                "ai_confidence": analysis.get("confidence", 0.5),
                "ai_analyzed": ai_analyzed,
                "captured_during_voice": True,
                "voice_context": capture_context if capture_context else None,
            }
        else:
            command_type = "chat_capture"
            metadata = {
                "entities": analysis.get("entities", {}),
                "actionable_items": analysis.get("actionable_items", []),
                "ai_summary": analysis.get("summary", ""),
                "ai_confidence": analysis.get("confidence", 0.5),
                "ai_analyzed": ai_analyzed,
                "captured_during_chat": True,
                "chat_context": capture_context if capture_context else None,
            }

        memory_id = db.save_memory(
            content=full_content,
            user_id=user_id,
            command_type=command_type,
            tags=analysis.get("themes", []),
            metadata=metadata,
        )

        if memory_id:
            try:
                from mentat.core.markdown_export import save_memory_to_markdown

                saved_memory = db.get_memory_by_id(memory_id, user_id)
                timestamp = saved_memory["timestamp"] if saved_memory else None
                save_memory_to_markdown(
                    content=full_content,
                    command_type=command_type,
                    tags=analysis.get("themes", []),
                    metadata=metadata,
                    timestamp=timestamp,
                    user_id=user_id,
                )
            except Exception as exc:
                log.warning(
                    "Markdown export failed for %s capture: %s",
                    channel,
                    exc,
                    exc_info=True,
                )

        return {
            "success": True,
            "memory_id": memory_id,
            "message": "Captured successfully",
            "tags": analysis.get("themes", [])[:3],
            "summary": (
                analysis.get("summary", "")[:100]
                if analysis.get("summary")
                else content[:100]
            ),
        }

    except Exception as exc:
        log.error("Error in capture_thought: %s", exc, exc_info=True)
        return {"success": False, "error": str(exc)}


spec = ToolSpec(
    name="capture_thought",
    description="Capture a specific thought to memory when the user explicitly asks.",
    parameters=PARAMS,
    channels={"chat", "voice"},
    handler=handler,
)
