"""
Persistent chat session storage with SQLite backend.

Provides:
- Persistent conversation history across CLI sessions
- Automatic context summarization for long conversations
- TTL-based session expiry
- Background cleanup scheduling
"""

import asyncio
import hashlib
import json
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from mentat.core.config import DATABASE_PATH
from mentat.core.llm import complete
from mentat.core.private_files import create_private_file, ensure_private_directory

logger = logging.getLogger("mentat.session_store")

# Default settings
DEFAULT_HISTORY_LENGTH = 16  # Max messages to keep in active context
DEFAULT_SESSION_TTL_DAYS = 7  # Sessions expire after this many days of inactivity
SUMMARY_THRESHOLD = 24  # Summarize when total messages exceeds this
MESSAGES_TO_SUMMARIZE = 16  # How many old messages to roll into summary


# Summarization prompt template
SUMMARIZATION_PROMPT = """Summarize this conversation concisely. Focus on:
- Key topics discussed
- Important facts mentioned (names, preferences, decisions)
- Any pending questions or tasks

Keep it under 150 words. Write in third person ("The user discussed...", "They mentioned...").

{existing_summary}

Recent conversation to incorporate:
{conversation}"""


def _format_messages_for_summary(messages: List[Dict[str, str]]) -> str:
    """Format messages into a readable string for summarization."""
    lines = []
    for msg in messages:
        role = msg.get("role", "unknown").capitalize()
        content = msg.get("content", "")[:500]  # Truncate long messages
        lines.append(f"{role}: {content}")
    return "\n".join(lines)


class ChatSessionStore:
    """
    Persistent chat session storage backed by SQLite.
    
    Features:
    - Stores full conversation history
    - Returns trimmed history for context window
    - Auto-summarizes old context when threshold exceeded
    - TTL-based cleanup
    
    How summarization works:
    ┌─────────────────────────────────────────────────────────────┐
    │                    Session History                          │
    ├─────────────────────────────────────────────────────────────┤
    │  [Summary of older messages]                                │
    │  ───────────────────────────                                │
    │  Message 17: user: "..."     ← Kept in active context       │
    │  Message 18: assistant: "..."                               │
    │  Message 19: user: "..."                                    │
    │  ...                                                        │
    │  Message 24: assistant: "..." ← Most recent                 │
    └─────────────────────────────────────────────────────────────┘
    
    When message count > SUMMARY_THRESHOLD:
    1. Take oldest MESSAGES_TO_SUMMARIZE messages
    2. Summarize them (merge with existing summary if any)
    3. Delete those messages from DB
    4. Store new summary
    """

    def __init__(
        self,
        db_path: Optional[str] = None,
        history_length: int = DEFAULT_HISTORY_LENGTH,
        session_ttl_days: int = DEFAULT_SESSION_TTL_DAYS,
        summary_threshold: int = SUMMARY_THRESHOLD,
    ):
        self.db_path = db_path or DATABASE_PATH
        self.history_length = history_length
        self.session_ttl_days = session_ttl_days
        self.summary_threshold = summary_threshold
        db_parent = os.path.dirname(os.path.abspath(self.db_path))
        if not os.path.exists(db_parent):
            ensure_private_directory(db_parent)
        create_private_file(self.db_path)
        self._init_tables()

    def _get_conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=10)
        os.chmod(self.db_path, 0o600)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_tables(self) -> None:
        """Create chat session tables if they don't exist."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # Sessions table - one row per unique session
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_key TEXT PRIMARY KEY,
                    user_id TEXT NOT NULL,
                    channel TEXT NOT NULL,
                    thread_id TEXT NOT NULL,
                    summary TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Messages table - full history
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS chat_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_key TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata TEXT,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_key) REFERENCES chat_sessions(session_key)
                )
            ''')
            
            cursor.execute(
                'CREATE INDEX IF NOT EXISTS idx_chat_messages_session '
                'ON chat_messages(session_key, created_at)'
            )
            conn.commit()

    @staticmethod
    def make_session_key(user_id: str, channel: str, thread_id: str) -> str:
        """Generate a deterministic key from an unambiguous encoding."""
        encoded = json.dumps(
            [user_id, channel, thread_id], ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return f"v2:{hashlib.sha256(encoded).hexdigest()}"

    def get_or_create_session(
        self, user_id: str, channel: str, thread_id: str
    ) -> str:
        """Get existing session or create a new one. Returns session_key."""
        session_key = self.make_session_key(user_id, channel, thread_id)
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT session_key FROM chat_sessions WHERE session_key = ?',
                (session_key,)
            )
            row = cursor.fetchone()
            
            if row:
                # Update last activity
                cursor.execute(
                    'UPDATE chat_sessions SET updated_at = ? WHERE session_key = ?',
                    (datetime.now().isoformat(), session_key)
                )
            else:
                # Create new session
                cursor.execute(
                    '''INSERT INTO chat_sessions 
                       (session_key, user_id, channel, thread_id, created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?)''',
                    (session_key, user_id, channel, thread_id,
                     datetime.now().isoformat(), datetime.now().isoformat())
                )
            conn.commit()
        
        return session_key

    def append_message(
        self,
        session_key: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        """Append a message to the session. Returns message ID."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''INSERT INTO chat_messages (session_key, role, content, metadata, created_at)
                   VALUES (?, ?, ?, ?, ?)''',
                (session_key, role, content,
                 json.dumps(metadata) if metadata else None,
                 datetime.now().isoformat())
            )
            msg_id = cursor.lastrowid
            
            # Update session activity
            cursor.execute(
                'UPDATE chat_sessions SET updated_at = ? WHERE session_key = ?',
                (datetime.now().isoformat(), session_key)
            )
            conn.commit()
            return msg_id

    def get_history(
        self,
        session_key: str,
        limit: Optional[int] = None,
    ) -> List[Dict[str, str]]:
        """
        Get conversation history for context.
        
        Returns the most recent `limit` messages (default: self.history_length).
        If there's a session summary, it's prepended as context.
        """
        limit = limit or self.history_length
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # Get session summary if exists
            cursor.execute(
                'SELECT summary FROM chat_sessions WHERE session_key = ?',
                (session_key,)
            )
            row = cursor.fetchone()
            summary = row["summary"] if row and row["summary"] else None
            
            # Get recent messages
            cursor.execute(
                '''SELECT role, content FROM chat_messages 
                   WHERE session_key = ?
                   ORDER BY created_at DESC
                   LIMIT ?''',
                (session_key, limit)
            )
            rows = cursor.fetchall()
        
        # Reverse to chronological order
        messages = [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]
        
        # Prepend summary as context if exists
        if summary and messages:
            messages.insert(0, {
                "role": "system",
                "content": f"[Previous conversation context: {summary}]"
            })
        
        return messages

    def get_full_history(self, session_key: str) -> List[Dict[str, Any]]:
        """Get complete conversation history (for export/debug)."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT role, content, metadata, created_at 
                   FROM chat_messages 
                   WHERE session_key = ?
                   ORDER BY created_at ASC''',
                (session_key,)
            )
            rows = cursor.fetchall()
        
        return [
            {
                "role": r["role"],
                "content": r["content"],
                "metadata": json.loads(r["metadata"]) if r["metadata"] else None,
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def get_oldest_messages(
        self, session_key: str, count: int
    ) -> List[Dict[str, Any]]:
        """Get the oldest N messages (for summarization)."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT id, role, content FROM chat_messages 
                   WHERE session_key = ?
                   ORDER BY created_at ASC
                   LIMIT ?''',
                (session_key, count)
            )
            rows = cursor.fetchall()
        
        return [
            {"id": r["id"], "role": r["role"], "content": r["content"]}
            for r in rows
        ]

    def delete_messages_by_ids(self, message_ids: List[int]) -> int:
        """Delete messages by their IDs. Returns count deleted."""
        if not message_ids:
            return 0
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            placeholders = ",".join("?" * len(message_ids))
            cursor.execute(
                f'DELETE FROM chat_messages WHERE id IN ({placeholders})',
                message_ids
            )
            deleted = cursor.rowcount
            conn.commit()
        
        return deleted

    def get_summary(self, session_key: str) -> Optional[str]:
        """Get current session summary."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT summary FROM chat_sessions WHERE session_key = ?',
                (session_key,)
            )
            row = cursor.fetchone()
            return row["summary"] if row else None

    def set_summary(self, session_key: str, summary: str) -> None:
        """Set a summary for the session (for context compression)."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'UPDATE chat_sessions SET summary = ?, updated_at = ? WHERE session_key = ?',
                (summary, datetime.now().isoformat(), session_key)
            )
            conn.commit()

    def get_message_count(self, session_key: str) -> int:
        """Get total number of messages in a session."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'SELECT COUNT(*) as cnt FROM chat_messages WHERE session_key = ?',
                (session_key,)
            )
            row = cursor.fetchone()
            return row["cnt"] if row else 0

    def needs_summarization(self, session_key: str) -> bool:
        """Check if session has exceeded the summary threshold."""
        count = self.get_message_count(session_key)
        return count > self.summary_threshold

    def clear_session(self, session_key: str) -> None:
        """Clear all messages from a session (keeps the session itself)."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                'DELETE FROM chat_messages WHERE session_key = ?',
                (session_key,)
            )
            cursor.execute(
                'UPDATE chat_sessions SET summary = NULL, updated_at = ? WHERE session_key = ?',
                (datetime.now().isoformat(), session_key)
            )
            conn.commit()

    def cleanup_expired_sessions(self) -> int:
        """Remove sessions older than TTL. Returns count of deleted sessions."""
        cutoff = datetime.now() - timedelta(days=self.session_ttl_days)
        
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # Find expired sessions
            cursor.execute(
                'SELECT session_key FROM chat_sessions WHERE updated_at < ?',
                (cutoff.isoformat(),)
            )
            expired = [r["session_key"] for r in cursor.fetchall()]
            
            if expired:
                # Delete messages first (foreign key)
                placeholders = ",".join("?" * len(expired))
                cursor.execute(
                    f'DELETE FROM chat_messages WHERE session_key IN ({placeholders})',
                    expired
                )
                cursor.execute(
                    f'DELETE FROM chat_sessions WHERE session_key IN ({placeholders})',
                    expired
                )
                conn.commit()
        
        if expired:
            logger.info("Cleaned up %d expired chat sessions", len(expired))
        return len(expired)

    def get_sessions_needing_summarization(self) -> List[str]:
        """Find all sessions that have exceeded the message threshold."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(
                '''SELECT session_key, COUNT(*) as cnt 
                   FROM chat_messages 
                   GROUP BY session_key 
                   HAVING cnt > ?''',
                (self.summary_threshold,)
            )
            return [r["session_key"] for r in cursor.fetchall()]


class SessionSummarizer:
    """
    Handles summarization of old messages using an LLM.
    
    This is separate from the store to keep DB logic clean
    and allow different summarization strategies.
    """

    def __init__(
        self,
        store: ChatSessionStore,
        llm_client: Any = None,
        model: Optional[str] = None,
    ):
        self.store = store
        self.llm_client = llm_client
        self.model = model

    def set_llm_client(self, client: Any, model: str) -> None:
        """Set the LLM client (called lazily when needed)."""
        self.llm_client = client
        self.model = model

    def summarize_session(self, session_key: str) -> Optional[str]:
        """
        Summarize oldest messages and update the session.
        
        Process:
        1. Get oldest MESSAGES_TO_SUMMARIZE messages
        2. Call LLM to summarize (incorporating existing summary)
        3. Delete those old messages
        4. Store new summary
        
        Returns the new summary, or None if summarization failed/skipped.
        """
        if not self.llm_client:
            logger.warning("No LLM client configured for summarization")
            return None

        # Check if summarization is needed
        if not self.store.needs_summarization(session_key):
            return None

        # Get oldest messages to summarize
        old_messages = self.store.get_oldest_messages(session_key, MESSAGES_TO_SUMMARIZE)
        if len(old_messages) < MESSAGES_TO_SUMMARIZE // 2:
            # Not enough old messages to be worth summarizing
            return None

        # Get existing summary to incorporate
        existing_summary = self.store.get_summary(session_key)
        existing_section = ""
        if existing_summary:
            existing_section = f"Existing context summary:\n{existing_summary}\n\n"

        # Format messages for summarization
        conversation_text = _format_messages_for_summary(old_messages)

        # Build the prompt
        prompt = SUMMARIZATION_PROMPT.format(
            existing_summary=existing_section,
            conversation=conversation_text
        )

        try:
            # Call LLM for summarization
            new_summary = complete(
                self.llm_client,
                self.model,
                [
                    {"role": "system", "content": "You are a helpful assistant that summarizes conversations concisely."},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=300,
                temperature=0.3,  # Low temperature for consistent summaries
            ).strip()
            
            if new_summary:
                # Delete the old messages we just summarized
                message_ids = [m["id"] for m in old_messages]
                deleted_count = self.store.delete_messages_by_ids(message_ids)
                
                # Store the new summary
                self.store.set_summary(session_key, new_summary)
                
                logger.info(
                    "Summarized session %s: deleted %d messages, new summary: %d chars",
                    session_key, deleted_count, len(new_summary)
                )
                return new_summary

        except Exception as e:
            logger.error("Summarization failed for %s: %s", session_key, e)

        return None

    def summarize_all_pending(self) -> int:
        """Summarize all sessions that need it. Returns count processed."""
        sessions = self.store.get_sessions_needing_summarization()
        processed = 0
        
        for session_key in sessions:
            if self.summarize_session(session_key):
                processed += 1
        
        if processed:
            logger.info("Summarized %d sessions", processed)
        return processed


# Async wrapper for chat integrations.
class AsyncChatSessionStore:
    """Async wrapper around ChatSessionStore."""

    def __init__(self, store: Optional[ChatSessionStore] = None, **kwargs):
        self._store = store or ChatSessionStore(**kwargs)
        self._summarizer: Optional[SessionSummarizer] = None
        self._cleanup_task: Optional[asyncio.Task] = None

    @property
    def store(self) -> ChatSessionStore:
        """Access underlying sync store."""
        return self._store

    def session_key(self, user_id: str, channel: str, thread_id: str) -> str:
        return self._store.make_session_key(user_id, channel, thread_id)

    async def get_or_create_session(
        self, user_id: str, channel: str, thread_id: str
    ) -> str:
        return self._store.get_or_create_session(user_id, channel, thread_id)

    async def get_history(
        self, session_key: str, limit: Optional[int] = None
    ) -> List[Dict[str, str]]:
        return self._store.get_history(session_key, limit)

    async def append_message(
        self,
        session_key: str,
        role: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        return self._store.append_message(session_key, role, content, metadata)

    async def get_summary(self, session_key: str) -> Optional[str]:
        return self._store.get_summary(session_key)

    async def set_summary(self, session_key: str, summary: str) -> None:
        self._store.set_summary(session_key, summary)

    async def get_message_count(self, session_key: str) -> int:
        return self._store.get_message_count(session_key)

    async def clear_session(self, session_key: str) -> None:
        self._store.clear_session(session_key)

    async def cleanup_expired(self) -> int:
        return self._store.cleanup_expired_sessions()

    async def needs_summarization(self, session_key: str) -> bool:
        return self._store.needs_summarization(session_key)

    # --- Summarization integration ---

    def configure_summarizer(self, llm_client: Any, model: str) -> None:
        """Configure the summarizer with an LLM client."""
        self._summarizer = SessionSummarizer(self._store, llm_client, model)

    async def maybe_summarize(self, session_key: str) -> Optional[str]:
        """Summarize session if needed. Call after appending messages."""
        if not self._summarizer:
            return None
        
        # Run in executor to not block
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._summarizer.summarize_session, session_key
        )

    async def summarize_all_pending(self) -> int:
        """Summarize all sessions that need it."""
        if not self._summarizer:
            return 0
        
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None, self._summarizer.summarize_all_pending
        )

    # --- Background cleanup scheduling ---

    async def start_cleanup_scheduler(
        self,
        interval_hours: float = 6.0,
        run_immediately: bool = True,
    ) -> None:
        """
        Start a background task that periodically cleans up expired sessions.
        
        Args:
            interval_hours: How often to run cleanup (default: every 6 hours)
            run_immediately: Whether to run cleanup immediately on start
        """
        if self._cleanup_task and not self._cleanup_task.done():
            logger.warning("Cleanup scheduler already running")
            return

        async def cleanup_loop():
            if run_immediately:
                try:
                    expired = await self.cleanup_expired()
                    summarized = await self.summarize_all_pending()
                    logger.info(
                        "Initial cleanup: %d expired sessions, %d summarized",
                        expired, summarized
                    )
                except Exception as e:
                    logger.error("Initial cleanup failed: %s", e)

            while True:
                await asyncio.sleep(interval_hours * 3600)
                try:
                    expired = await self.cleanup_expired()
                    summarized = await self.summarize_all_pending()
                    if expired or summarized:
                        logger.info(
                            "Scheduled cleanup: %d expired, %d summarized",
                            expired, summarized
                        )
                except Exception as e:
                    logger.error("Scheduled cleanup failed: %s", e)

        self._cleanup_task = asyncio.create_task(cleanup_loop())
        logger.info("Started session cleanup scheduler (every %.1f hours)", interval_hours)

    async def stop_cleanup_scheduler(self) -> None:
        """Stop the background cleanup task."""
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
            self._cleanup_task = None
            logger.info("Stopped session cleanup scheduler")
