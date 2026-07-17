"""Tests for the persistent chat session store."""

import asyncio
import os
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from mentat.chat.session_store import (
    ChatSessionStore,
    AsyncChatSessionStore,
    SessionSummarizer,
    _format_messages_for_summary,
    MESSAGES_TO_SUMMARIZE,
)


@pytest.fixture
def temp_db():
    """Create a temporary database file."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.unlink(path)


@pytest.fixture
def store(temp_db):
    """Create a test session store."""
    return ChatSessionStore(
        db_path=temp_db,
        history_length=4,
        summary_threshold=8,
        session_ttl_days=1,
    )


@pytest.fixture
def async_store(temp_db):
    """Create a test async session store."""
    return AsyncChatSessionStore(
        db_path=temp_db,
        history_length=4,
        summary_threshold=8,
        session_ttl_days=1,
    )


class TestChatSessionStore:
    """Tests for the sync ChatSessionStore."""

    def test_create_session(self, store):
        key = store.get_or_create_session("user1", "api", "thread1")
        assert key.startswith("v2:")
        assert len(key) == 67

    def test_session_keys_do_not_collide_on_colons(self, store):
        first = store.get_or_create_session("a:b", "c", "d")
        second = store.get_or_create_session("a", "b:c", "d")

        assert first != second
        store.append_message(first, "user", "first")
        store.append_message(second, "user", "second")
        assert store.get_history(first)[0]["content"] == "first"
        assert store.get_history(second)[0]["content"] == "second"

    def test_create_session_idempotent(self, store):
        key1 = store.get_or_create_session("user1", "api", "thread1")
        key2 = store.get_or_create_session("user1", "api", "thread1")
        assert key1 == key2

    def test_append_and_get_messages(self, store):
        key = store.get_or_create_session("user1", "chat", "default")
        store.append_message(key, "user", "Hello")
        store.append_message(key, "assistant", "Hi there!")

        history = store.get_history(key)
        assert len(history) == 2
        assert history[0]["role"] == "user"
        assert history[0]["content"] == "Hello"
        assert history[1]["role"] == "assistant"

    def test_history_limit_works(self, store):
        key = store.get_or_create_session("user1", "chat", "default")
        
        # Add more messages than the limit (4)
        for i in range(10):
            role = "user" if i % 2 == 0 else "assistant"
            store.append_message(key, role, f"Message {i}")

        # Should only get the most recent 4
        history = store.get_history(key)
        assert len(history) == 4
        assert history[0]["content"] == "Message 6"
        assert history[-1]["content"] == "Message 9"

    def test_message_count(self, store):
        key = store.get_or_create_session("user1", "chat", "default")
        
        assert store.get_message_count(key) == 0
        
        store.append_message(key, "user", "Hello")
        assert store.get_message_count(key) == 1
        
        store.append_message(key, "assistant", "Hi")
        assert store.get_message_count(key) == 2

    def test_needs_summarization(self, store):
        key = store.get_or_create_session("user1", "chat", "default")
        
        # Under threshold (8)
        for i in range(6):
            store.append_message(key, "user", f"Msg {i}")
        
        assert not store.needs_summarization(key)
        
        # Over threshold
        store.append_message(key, "user", "Over")
        store.append_message(key, "user", "Threshold")
        store.append_message(key, "user", "Now")
        
        assert store.needs_summarization(key)

    def test_get_oldest_messages(self, store):
        key = store.get_or_create_session("user1", "chat", "default")
        
        for i in range(6):
            store.append_message(key, "user", f"Message {i}")
        
        oldest = store.get_oldest_messages(key, 3)
        assert len(oldest) == 3
        assert oldest[0]["content"] == "Message 0"
        assert oldest[2]["content"] == "Message 2"

    def test_delete_messages_by_ids(self, store):
        key = store.get_or_create_session("user1", "chat", "default")
        
        for i in range(4):
            store.append_message(key, "user", f"Message {i}")
        
        oldest = store.get_oldest_messages(key, 2)
        ids_to_delete = [m["id"] for m in oldest]
        
        deleted = store.delete_messages_by_ids(ids_to_delete)
        assert deleted == 2
        assert store.get_message_count(key) == 2

    def test_set_and_get_summary(self, store):
        key = store.get_or_create_session("user1", "chat", "default")
        
        assert store.get_summary(key) is None
        
        store.set_summary(key, "User discussed AI topics.")
        assert store.get_summary(key) == "User discussed AI topics."

    def test_summary_prepended_to_history(self, store):
        key = store.get_or_create_session("user1", "chat", "default")
        store.set_summary(key, "Previous context here.")
        store.append_message(key, "user", "New message")
        
        history = store.get_history(key)
        assert len(history) == 2
        assert history[0]["role"] == "system"
        assert "Previous context" in history[0]["content"]
        assert history[1]["content"] == "New message"

    def test_clear_session(self, store):
        key = store.get_or_create_session("user1", "chat", "default")
        store.append_message(key, "user", "Hello")
        store.set_summary(key, "Some summary")
        
        store.clear_session(key)
        
        assert store.get_message_count(key) == 0
        assert store.get_summary(key) is None

    def test_full_history(self, store):
        key = store.get_or_create_session("user1", "chat", "default")
        store.append_message(key, "user", "Msg 1", {"test": True})
        store.append_message(key, "assistant", "Msg 2")
        
        full = store.get_full_history(key)
        assert len(full) == 2
        assert full[0]["metadata"] == {"test": True}
        assert full[1]["metadata"] is None
        assert "created_at" in full[0]


class TestFormatMessagesForSummary:
    """Tests for the message formatting helper."""

    def test_formats_messages(self):
        messages = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there"},
        ]
        result = _format_messages_for_summary(messages)
        assert "User: Hello" in result
        assert "Assistant: Hi there" in result

    def test_truncates_long_messages(self):
        messages = [{"role": "user", "content": "x" * 1000}]
        result = _format_messages_for_summary(messages)
        # Should be truncated to 500 chars
        assert len(result) < 600


class TestSessionSummarizer:
    """Tests for the session summarizer."""

    def test_summarizer_without_client_returns_none(self, store):
        summarizer = SessionSummarizer(store, llm_client=None)
        key = store.get_or_create_session("user1", "chat", "default")
        
        # Add enough messages to trigger summarization
        for i in range(10):
            store.append_message(key, "user", f"Msg {i}")
        
        result = summarizer.summarize_session(key)
        assert result is None

    def test_summarizer_skips_if_not_needed(self, store):
        mock_client = MagicMock()
        summarizer = SessionSummarizer(store, llm_client=mock_client, model="test")
        
        key = store.get_or_create_session("user1", "chat", "default")
        store.append_message(key, "user", "Hello")  # Only 1 message
        
        result = summarizer.summarize_session(key)
        assert result is None
        mock_client.chat.completions.create.assert_not_called()

    def test_summarizer_calls_llm_wrapper_and_updates_store(self, store, monkeypatch):
        calls = []

        def fake_complete(client, model, messages, **kwargs):
            calls.append(
                {
                    "client": client,
                    "model": model,
                    "messages": messages,
                    "kwargs": kwargs,
                }
            )
            return "User discussed various topics."

        monkeypatch.setattr("mentat.chat.session_store.complete", fake_complete)

        mock_client = MagicMock()
        
        summarizer = SessionSummarizer(store, llm_client=mock_client, model="test-model")
        
        key = store.get_or_create_session("user1", "chat", "default")
        
        # Add enough messages to trigger summarization
        for i in range(12):
            store.append_message(key, "user", f"Message {i}")
        
        initial_count = store.get_message_count(key)
        result = summarizer.summarize_session(key)
        
        # Should have summarized
        assert result == "User discussed various topics."
        assert store.get_summary(key) == "User discussed various topics."
        
        # Should have deleted some messages
        assert store.get_message_count(key) < initial_count
        
        # LLM wrapper should have been called with the original request options.
        assert calls[0]["client"] is mock_client
        assert calls[0]["model"] == "test-model"
        assert calls[0]["kwargs"] == {"max_tokens": 300, "temperature": 0.3}
        assert calls[0]["messages"][0]["role"] == "system"
        assert "Message 0" in calls[0]["messages"][1]["content"]
        mock_client.chat.completions.create.assert_not_called()


class TestAsyncChatSessionStore:
    """Tests for the async wrapper."""

    def test_async_operations(self, async_store):
        """Test async operations using asyncio.run."""
        async def _test():
            key = await async_store.get_or_create_session("user1", "api", "thread1")
            assert key.startswith("v2:")
            
            await async_store.append_message(key, "user", "Hello async")
            history = await async_store.get_history(key)
            
            assert len(history) == 1
            assert history[0]["content"] == "Hello async"
        
        asyncio.run(_test())

    def test_async_needs_summarization(self, async_store):
        """Test async needs_summarization check."""
        async def _test():
            key = await async_store.get_or_create_session("user1", "api", "thread1")
            
            # Under threshold
            for i in range(5):
                await async_store.append_message(key, "user", f"Msg {i}")
            
            assert not await async_store.needs_summarization(key)
        
        asyncio.run(_test())

    def test_configure_summarizer(self, async_store):
        mock_client = MagicMock()
        async_store.configure_summarizer(mock_client, "test-model")
        
        assert async_store._summarizer is not None
        assert async_store._summarizer.llm_client == mock_client
