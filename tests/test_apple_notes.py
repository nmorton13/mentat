import types

import pytest

from mentat.chat import enhanced_chat


def test_gather_context_includes_apple_notes(monkeypatch):
    # Pretend we are on macOS
    monkeypatch.setattr(enhanced_chat.sys, "platform", "darwin")

    # Stub embedding client presence
    dummy_chat = enhanced_chat.EnhancedChatSystem(
        db=types.SimpleNamespace(
            get_database_stats=lambda user_id: {
                "total_memories": 243,
                "type_counts": [],
            }
        ),
        openrouter_client=None,
    )
    dummy_chat.openai_client = object()

    # Avoid real entity/temporal calls
    monkeypatch.setattr(enhanced_chat, "extract_structured_entities", lambda *a, **k: [])
    from mentat.chat import temporal
    monkeypatch.setattr(temporal, "extract_temporal_intent", lambda *a, **k: {"has_temporal_intent": False})

    # Stub search pipelines
    monkeypatch.setattr(
        dummy_chat,
        "_hybrid_search",
        lambda user_id, query, k=0, internal_multiplier=1.0: [
            {
                "id": "mem1",
                "user_id": user_id,
                "content": "local memory about writing",
                "command_type": "note",
                "tags": [],
                "metadata": {},
                "timestamp": "2024-01-01",
            }
        ],
    )

    context = dummy_chat._gather_comprehensive_context("improve dialogue", user_id="u1")

    # Memories come from Mentat store only (Apple Notes now require sync).
    assert [m["id"] for m in context["memories"]] == ["mem1"]
