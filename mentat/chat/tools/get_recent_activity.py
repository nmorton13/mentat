"""Tool: get_recent_activity - Summarize recent activity."""

import json
from datetime import datetime, timedelta
from typing import Any, Dict

from mentat.chat.tools.base import ToolSpec, get_logger, get_db

PARAMS = {
    "type": "object",
    "properties": {
        "days": {
            "type": "integer",
            "description": "How many days back to look (default: 7)",
            "default": 7,
        }
    },
    "required": [],
}


async def handler(arguments: Dict[str, Any], context: Dict[str, Any]) -> Dict[str, Any]:
    """Get summary of recent activity."""
    days = arguments.get("days", 7)
    user_id = context.get("user_id")
    log = get_logger(context)

    if not user_id:
        return {"success": False, "error": "No user_id provided"}

    log.info("get_recent_activity: last %s days", days)

    db = get_db()
    if not db:
        return {"success": False, "error": "Database unavailable"}

    try:
        cutoff = datetime.now() - timedelta(days=days)

        with db.db_pool.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT content, timestamp, command_type, tags
                FROM memories
                WHERE user_id = ? AND timestamp >= ?
                ORDER BY timestamp DESC
            """,
                [user_id, cutoff.isoformat()],
            )

            rows = cursor.fetchall()

        if not rows:
            return {
                "success": True,
                "period": f"last {days} days",
                "total_memories": 0,
                "message": f"No activity found in the last {days} days",
            }

        recent_items = []
        all_tags = []
        for content, timestamp, command_type, tags in rows[:5]:
            recent_items.append(
                {
                    "preview": content[:250] + "..." if len(content) > 250 else content,
                    "when": timestamp[:10] if timestamp else "unknown",
                    "type": command_type or "unknown",
                }
            )

            if tags:
                try:
                    tag_list = json.loads(tags) if isinstance(tags, str) else tags
                    all_tags.extend(tag_list if isinstance(tag_list, list) else [])
                except Exception:
                    pass

        tag_counts = {}
        for tag in all_tags:
            tag_counts[tag] = tag_counts.get(tag, 0) + 1
        top_themes = sorted(tag_counts.keys(), key=lambda t: tag_counts[t], reverse=True)[:5]

        return {
            "success": True,
            "period": f"last {days} days",
            "total_memories": len(rows),
            "recent_items": recent_items,
            "top_themes": top_themes,
            "summary": f"Found {len(rows)} memories from the last {days} days",
        }

    except Exception as exc:
        log.error("get_recent_activity error: %s", exc, exc_info=True)
        return {"success": False, "error": str(exc)}


spec = ToolSpec(
    name="get_recent_activity",
    description="Summarize recent activity when the user asks what they've been up to.",
    parameters=PARAMS,
    channels={"chat"},
    handler=handler,
)
