"""
Shared service for CLI-parity enhanced chat responses over API.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from mentat.chat.enhanced_chat import EnhancedChatSystem


def _serialize_reference(ref_id: str, data: Dict[str, Any]) -> Dict[str, Any]:
    timestamp = data.get("timestamp")
    if isinstance(timestamp, datetime):
        timestamp = timestamp.isoformat()
    elif timestamp is not None:
        timestamp = str(timestamp)

    return {
        "id": ref_id,
        "topic": data.get("topic"),
        "context": data.get("context"),
        "personal_context": data.get("personal_context"),
        "timestamp": timestamp,
    }


def _collect_references(enhanced_chat: EnhancedChatSystem) -> List[Dict[str, Any]]:
    def _ref_sort_key(item: str) -> tuple[int, str]:
        return (0, f"{int(item):08d}") if item.isdigit() else (1, item)

    ordered_ids = sorted(enhanced_chat.session_references.keys(), key=_ref_sort_key)
    return [_serialize_reference(ref_id, enhanced_chat.session_references[ref_id]) for ref_id in ordered_ids]


def _run_enhanced_chat_sync(
    *,
    message: str,
    user_id: str,
    current_model: str,
    db: Any,
    openrouter_client: Any,
) -> Dict[str, Any]:
    enhanced_chat = EnhancedChatSystem(db, openrouter_client)
    result = enhanced_chat.enhanced_chat_response(
        query=message,
        user_id=user_id,
        current_model=current_model,
        update_global_state=None,
    )
    references = _collect_references(enhanced_chat)
    return {
        "response": result.get("response", ""),
        "sources": result.get("sources", []) or [],
        "patterns": result.get("patterns", []) or [],
        "connections": result.get("connections", []) or [],
        "suggestions": result.get("suggestions", []) or [],
        "references": references,
    }


async def run_enhanced_chat(
    *,
    message: str,
    user_id: str,
    current_model: str,
    db: Any,
    openrouter_client: Any,
) -> Dict[str, Any]:
    return await asyncio.to_thread(
        _run_enhanced_chat_sync,
        message=message,
        user_id=user_id,
        current_model=current_model,
        db=db,
        openrouter_client=openrouter_client,
    )
