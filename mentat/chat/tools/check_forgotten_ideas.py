"""Tool: check_forgotten_ideas - Surface past ideas during brainstorming."""

import json
from typing import Any, Dict

from mentat.chat.tools.base import (
    ToolSpec, get_logger, get_db, get_openai_client, get_embedding_for_content
)

PARAMS = {
    "type": "object",
    "properties": {
        "brainstorm_topic": {
            "type": "string",
            "description": "What they're currently brainstorming about",
        },
    },
    "required": ["brainstorm_topic"],
}


async def handler(arguments: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Find past ideas related to a brainstorming topic."""
    topic = arguments.get("brainstorm_topic", "").strip()
    user_id = context.get("user_id")
    log = get_logger(context)

    if not topic:
        return {"success": False, "error": "No brainstorm topic provided"}
    if not user_id:
        return {"success": False, "error": "No user_id provided"}

    log.info("check_forgotten_ideas: '%s'", topic)

    db = get_db()
    openai_client = get_openai_client()
    if not db or not openai_client:
        return {"success": False, "error": "Database or OpenAI client unavailable"}

    try:
        query_embedding = get_embedding_for_content(topic, client=openai_client)
        if not query_embedding:
            return {
                "success": True,
                "found": False,
                "message": "Could not generate embedding for topic",
            }

        mem_ids = db.brute_sem_search(query_embedding, k=8, min_similarity=0.15)
        if not mem_ids:
            return {
                "success": True,
                "found": False,
                "message": "No past ideas found on this topic",
            }

        with db.db_pool.get_connection() as conn:
            cursor = conn.cursor()
            memory_ids_only = [mem_id for mem_id, _ in mem_ids]
            placeholders = ",".join(["?"] * len(memory_ids_only))

            cursor.execute(
                f"""
                SELECT id, content, timestamp, tags, command_type
                FROM memories
                WHERE user_id = ? AND id IN ({placeholders})
                ORDER BY timestamp DESC
            """,
                [user_id] + memory_ids_only,
            )

            ideas = []
            for row in cursor.fetchall()[:4]:
                mem_id, content, timestamp, tags, command_type = row

                tag_list = []
                if tags:
                    try:
                        tag_list = json.loads(tags) if isinstance(tags, str) else tags
                    except Exception:
                        tag_list = []

                ideas.append(
                    {
                        "preview": content[:250] + "..." if len(content) > 250 else content,
                        "when": timestamp[:10] if timestamp else "unknown",
                        "tags": tag_list[:3] if isinstance(tag_list, list) else [],
                        "type": command_type if command_type else "unknown",
                    }
                )

        return {
            "success": True,
            "found": True,
            "count": len(ideas),
            "ideas": ideas,
            "suggestion": f"You have {len(ideas)} related ideas from the past",
        }

    except Exception as exc:
        log.error("Error in check_forgotten_ideas: %s", exc, exc_info=True)
        return {"success": False, "error": str(exc)}


spec = ToolSpec(
    name="check_forgotten_ideas",
    description=(
        "When brainstorming, surface past ideas they might have forgotten. "
        "Use sparingly and only when it would spark new thinking."
    ),
    parameters=PARAMS,
    channels={"chat", "voice"},
    handler=handler,
)
