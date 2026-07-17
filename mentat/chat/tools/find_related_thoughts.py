"""Tool: find_related_thoughts - Search past notes related to a concept."""

import json
from typing import Any, Dict

from mentat.chat.tools.base import (
    ToolSpec, get_logger, get_db, get_openai_client, get_embedding_for_content
)

PARAMS = {
    "type": "object",
    "properties": {
        "concept": {
            "type": "string",
            "description": "The concept or topic to check for past notes about",
        },
        "reason": {
            "type": "string",
            "description": (
                "Why this connection would be valuable to surface now "
                "(helps ensure thoughtful use)"
            ),
        },
    },
    "required": ["concept", "reason"],
}


async def handler(arguments: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Find thoughts related to a concept using semantic search."""
    concept = arguments.get("concept", "").strip()
    reason = arguments.get("reason", "").strip()
    user_id = context.get("user_id")
    log = get_logger(context)

    if not concept:
        return {"success": False, "error": "No concept provided"}
    if not user_id:
        return {"success": False, "error": "No user_id provided"}

    log.info("find_related_thoughts: '%s' (reason: %s)", concept, reason)

    db = get_db()
    openai_client = get_openai_client()
    if not db or not openai_client:
        return {"success": False, "error": "Database or OpenAI client unavailable"}

    try:
        query_embedding = get_embedding_for_content(concept, client=openai_client)
        if not query_embedding:
            return {
                "success": True,
                "found": False,
                "message": "Could not generate embedding for concept",
                "reason_logged": reason,
            }

        mem_ids = db.brute_sem_search(query_embedding, k=10, min_similarity=0.15)
        if not mem_ids:
            return {
                "success": True,
                "found": False,
                "message": "No connections found",
                "reason_logged": reason,
            }

        with db.db_pool.get_connection() as conn:
            cursor = conn.cursor()
            memory_ids_only = [mem_id for mem_id, _ in mem_ids]
            placeholders = ",".join(["?"] * len(memory_ids_only))

            cursor.execute(
                f"""
                SELECT id, content, timestamp, tags
                FROM memories
                WHERE user_id = ? AND id IN ({placeholders})
                ORDER BY timestamp DESC
            """,
                [user_id] + memory_ids_only,
            )

            connections = []
            for row in cursor.fetchall()[:5]:
                mem_id, content, timestamp, tags = row
                similarity = next((sim for mid, sim in mem_ids if mid == mem_id), 0.0)

                tag_list = []
                if tags:
                    try:
                        tag_list = json.loads(tags) if isinstance(tags, str) else tags
                    except Exception:
                        tag_list = []

                connections.append(
                    {
                        "snippet": content[:250] + "..." if len(content) > 250 else content,
                        "when": timestamp[:10] if timestamp else "unknown",
                        "tags": tag_list[:3] if isinstance(tag_list, list) else [],
                        "similarity": round(similarity, 2),
                    }
                )

        return {
            "success": True,
            "found": True,
            "count": len(connections),
            "connections": connections,
            "suggestion": f"Found {len(connections)} related thoughts about {concept}",
        }

    except Exception as exc:
        log.error("Error in find_related_thoughts: %s", exc, exc_info=True)
        return {"success": False, "error": str(exc)}


spec = ToolSpec(
    name="find_related_thoughts",
    description=(
        "Check if user has thoughts/notes related to current topic. "
        "Use when it would be valuable to connect to their previous thinking. "
        "Do not use for every message."
    ),
    parameters=PARAMS,
    channels={"chat", "voice"},
    handler=handler,
)
