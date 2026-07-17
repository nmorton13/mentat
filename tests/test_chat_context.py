from mentat.chat import enhanced_chat
from mentat.chat import temporal as temporal_module


class DummyDB:
    def __init__(self, memory_count=243):
        self.timeframe_calls = []
        self.memory_count = memory_count

    def get_database_stats(self, user_id):
        return {"total_memories": self.memory_count, "type_counts": []}

    def search_by_timeframe(self, user_id, query=None, start_date=None, end_date=None, k=None):
        self.timeframe_calls.append((user_id, query, start_date, end_date, k))
        return [
            {
                "id": 1,
                "content": "Worked on summer planning",
                "command_type": "note",
                "tags": ["summer"],
                "timestamp": "2025-06-20",
            }
        ]

    def find_entity_connections(self, *args, **kwargs):
        return []


def test_gather_context_prefers_temporal_timeframe(monkeypatch):
    dummy_db = DummyDB()
    chat = enhanced_chat.EnhancedChatSystem(dummy_db, openrouter_client=None)

    def fake_temporal_intent(*args, **kwargs):
        return {
            "has_temporal_intent": True,
            "start_date": "2025-06-01",
            "end_date": "2025-08-31",
            "temporal_context": "last summer",
            "query_without_temporal": "",
        }

    monkeypatch.setattr(temporal_module, "extract_temporal_intent", fake_temporal_intent)
    monkeypatch.setattr(enhanced_chat, "extract_structured_entities", lambda *args, **kwargs: {})
    monkeypatch.setattr(chat, "_hybrid_search", lambda *args, **kwargs: [])

    context = chat._gather_comprehensive_context("what did I do last summer", "u1")

    assert dummy_db.timeframe_calls
    assert context["temporal_context"] == "last summer"
    assert context["temporal_start_date"] == "2025-06-01"
    assert context["temporal_end_date"] == "2025-08-31"
    assert context["query_without_temporal"] == ""
    assert context["memories"][0]["source_type"] == "timeframe"


def test_gather_context_falls_back_to_hybrid_search(monkeypatch):
    dummy_db = DummyDB()
    chat = enhanced_chat.EnhancedChatSystem(dummy_db, openrouter_client=None)

    monkeypatch.setattr(temporal_module, "extract_temporal_intent", lambda *args, **kwargs: {"has_temporal_intent": False})
    monkeypatch.setattr(enhanced_chat, "extract_structured_entities", lambda *args, **kwargs: {})
    monkeypatch.setattr(chat, "_hybrid_search", lambda *args, **kwargs: [{"id": 2, "content": "Fallback"}])

    context = chat._gather_comprehensive_context("what did I do", "u1")

    assert context["memories"][0]["content"] == "Fallback"


def test_gather_context_uses_corpus_sized_retrieval_limits(monkeypatch):
    for name in (
        "CHAT_HYBRID_SEARCH_K",
        "HYBRID_SEARCH_INTERNAL_MULTIPLIER",
        "CHAT_CONTEXT_LIMIT",
    ):
        monkeypatch.delenv(name, raising=False)

    dummy_db = DummyDB(memory_count=40)
    chat = enhanced_chat.EnhancedChatSystem(dummy_db, openrouter_client=None)
    calls = []

    monkeypatch.setattr(
        temporal_module,
        "extract_temporal_intent",
        lambda *args, **kwargs: {"has_temporal_intent": False},
    )
    monkeypatch.setattr(
        enhanced_chat,
        "extract_structured_entities",
        lambda *args, **kwargs: {},
    )

    def fake_hybrid_search(user_id, query, k, internal_multiplier):
        calls.append((user_id, query, k, internal_multiplier))
        return []

    monkeypatch.setattr(chat, "_hybrid_search", fake_hybrid_search)

    context = chat._gather_comprehensive_context("what did I do", "u1")

    assert calls == [("u1", "what did I do", 25, 1.6)]
    assert context["chat_context_limit"] == 40


def test_gather_context_skips_entity_extraction_when_search_is_strong(monkeypatch):
    dummy_db = DummyDB()
    chat = enhanced_chat.EnhancedChatSystem(dummy_db, openrouter_client=object())
    memories = [{"id": i, "content": f"Memory {i}"} for i in range(8)]

    monkeypatch.setattr(temporal_module, "extract_temporal_intent", lambda *args, **kwargs: {"has_temporal_intent": False})
    monkeypatch.setattr(chat, "_hybrid_search", lambda *args, **kwargs: memories)

    def fail_entity_extraction(*args, **kwargs):
        raise AssertionError("entity extraction should be skipped")

    monkeypatch.setattr(enhanced_chat, "extract_structured_entities", fail_entity_extraction)

    context = chat._gather_comprehensive_context("what should i focus on next", "u1")

    assert len(context["memories"]) == 8
    assert context["query_entities"] == []
    assert context["entity_connections"] == []


def test_gather_context_extracts_entities_when_search_is_weak(monkeypatch):
    class EntityDB(DummyDB):
        def __init__(self):
            super().__init__()
            self.entity_calls = []

        def find_entity_connections(self, entities, user_id, k=None):
            self.entity_calls.append((entities, user_id, k))
            return [
                (
                    {
                        "id": 99,
                        "content": "Connected memory",
                        "command_type": "note",
                        "tags": [],
                        "timestamp": "2026-06-01",
                    },
                    ["focus"],
                )
            ]

    dummy_db = EntityDB()
    chat = enhanced_chat.EnhancedChatSystem(dummy_db, openrouter_client=object())

    monkeypatch.setattr(temporal_module, "extract_temporal_intent", lambda *args, **kwargs: {"has_temporal_intent": False})
    monkeypatch.setattr(chat, "_hybrid_search", lambda *args, **kwargs: [{"id": 1, "content": "One result"}])
    monkeypatch.setattr(enhanced_chat, "extract_structured_entities", lambda *args, **kwargs: {"concepts": ["focus"]})

    context = chat._gather_comprehensive_context("what should i focus on next", "u1")

    assert dummy_db.entity_calls
    assert context["query_entities"] == {"concepts": ["focus"]}
    assert context["memories"][1]["source_type"] == "entity"


def test_gather_context_extracts_entities_for_named_concept_queries(monkeypatch):
    dummy_db = DummyDB()
    chat = enhanced_chat.EnhancedChatSystem(dummy_db, openrouter_client=object())
    calls = []
    memories = [{"id": i, "content": f"Memory {i}"} for i in range(10)]

    monkeypatch.setattr(temporal_module, "extract_temporal_intent", lambda *args, **kwargs: {"has_temporal_intent": False})
    monkeypatch.setattr(chat, "_hybrid_search", lambda *args, **kwargs: memories)

    def fake_entity_extraction(*args, **kwargs):
        calls.append(args)
        return {"concepts": ["Beautiful Mess", "First Principles"]}

    monkeypatch.setattr(enhanced_chat, "extract_structured_entities", fake_entity_extraction)

    context = chat._gather_comprehensive_context("Does Beautiful Mess clash with First Principles?", "u1")

    assert calls
    assert context["query_entities"] == {"concepts": ["Beautiful Mess", "First Principles"]}


def test_chat_context_filters_ai_derived_semantic_memories(monkeypatch):
    dummy_db = DummyDB()
    chat = enhanced_chat.EnhancedChatSystem(dummy_db, openrouter_client=None)
    memories = [
        {
            "id": 1,
            "content": "Human memory",
            "command_type": "reflection",
            "metadata": {},
        },
        {
            "id": 2,
            "content": "Old saved AI response",
            "command_type": "reflection",
            "metadata": '{"source": {"type": "ai_response", "model": "test"}}',
        },
        {
            "id": 3,
            "content": "Explicit AI response",
            "command_type": "ai_response",
            "metadata": {},
        },
    ]

    monkeypatch.setattr(temporal_module, "extract_temporal_intent", lambda *args, **kwargs: {"has_temporal_intent": False})
    monkeypatch.setattr(chat, "_hybrid_search", lambda *args, **kwargs: memories)

    context = chat._gather_comprehensive_context("tell me what I think", "u1")

    assert [mem["id"] for mem in context["memories"]] == [1]


def test_chat_context_filters_ai_derived_entity_connections(monkeypatch):
    class EntityDB(DummyDB):
        def find_entity_connections(self, entities, user_id, k=None):
            return [
                (
                    {
                        "id": 2,
                        "content": "Old saved AI response",
                        "command_type": "reflection",
                        "metadata": {"source": {"type": "ai_response", "model": "test"}},
                    },
                    ["Beautiful Mess"],
                ),
                (
                    {
                        "id": 4,
                        "content": "Human entity memory",
                        "command_type": "reflection",
                        "metadata": {},
                    },
                    ["Beautiful Mess"],
                ),
            ]

    dummy_db = EntityDB()
    chat = enhanced_chat.EnhancedChatSystem(dummy_db, openrouter_client=object())

    monkeypatch.setattr(temporal_module, "extract_temporal_intent", lambda *args, **kwargs: {"has_temporal_intent": False})
    monkeypatch.setattr(chat, "_hybrid_search", lambda *args, **kwargs: [])
    monkeypatch.setattr(enhanced_chat, "extract_structured_entities", lambda *args, **kwargs: {"concepts": ["Beautiful Mess"]})

    context = chat._gather_comprehensive_context("Does Beautiful Mess connect to this?", "u1")

    assert [mem["id"] for mem in context["memories"]] == [4]
    assert [item[0]["id"] for item in context["entity_connections"]] == [4]
