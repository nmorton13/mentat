from mentat.chat.enhanced_chat import EnhancedChatSystem
from mentat.core.llm import CompletionResult


class ExplodingCompletions:
    def create(self, **kwargs):
        raise AssertionError("direct chat completion should not be used")


class ExplodingClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": ExplodingCompletions()})()


class DummyDB:
    pass


def test_detect_intent_quick():
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=None)

    assert chat._detect_intent("What is Rust?") == "quick"


def test_detect_intent_research():
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=None)

    assert chat._detect_intent("Let's go deep on caching") == "research"


def test_detect_intent_decision():
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=None)

    assert chat._detect_intent("Should I pick SQLite or Postgres?") == "decision"


def test_build_source_attribution_counts_sources():
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=None)
    memories = [
        {"source_type": "timeframe"},
        {"source_type": "timeframe"},
        {"source_type": "semantic"},
        {"source_type": "entity"},
    ]

    attribution = chat._build_source_attribution(memories, temporal_context="last week")

    types = {entry["type"]: entry for entry in attribution}
    assert types["temporal"]["count"] == 2
    assert types["semantic"]["count"] == 1
    assert types["entity"]["count"] == 1


def test_generate_enhanced_response_uses_llm_wrapper(monkeypatch):
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=ExplodingClient())
    calls = []

    def fake_complete(client, model, messages):
        calls.append((client, model, messages))
        return "wrapped answer"

    monkeypatch.setattr("mentat.chat.enhanced_chat.complete", fake_complete)

    response = chat._generate_enhanced_response(
        "How should I proceed?",
        {"memories": []},
        [],
        "test-model",
    )

    assert response == "wrapped answer"
    assert calls[0][0] is chat.client
    assert calls[0][1] == "test-model"


def test_generate_enhanced_response_research_uses_online_wrapper(monkeypatch):
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=ExplodingClient())
    calls = []

    def fake_complete_online(client, model, messages):
        calls.append((client, model, messages))
        return CompletionResult(text="online answer", response=object(), model="test-model:online")

    monkeypatch.setattr("mentat.chat.enhanced_chat.complete_online", fake_complete_online)

    response = chat._generate_enhanced_response(
        "Research caching deeply",
        {"memories": []},
        [],
        "test-model",
        intent="research",
    )

    assert response == "online answer"
    assert calls[0][0] is chat.client
    assert calls[0][1] == "test-model"


def test_temporal_context_prompt_adds_strict_grounding_rules_only_for_temporal():
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=None)
    temporal_prompt = chat._build_context_prompt(
        {
            "temporal_context": "last week (2026-06-15 to 2026-06-21)",
            "memories": [
                {
                    "id": 42,
                    "content": "Worked on Mentat temporal retrieval.",
                    "command_type": "note",
                    "tags": [],
                    "timestamp": "2026-06-17",
                    "source_type": "timeframe",
                }
            ],
        },
        [],
    )

    normal_prompt = chat._build_context_prompt(
        {"memories": [], "temporal_context": None},
        [],
    )

    assert "**Temporal Grounding Rules:**" in temporal_prompt
    assert "Answer only from the listed memories" in temporal_prompt
    assert "Only 1 memory was found for this timeframe" in temporal_prompt
    assert "(Memory 1, 2026-06-25)" in temporal_prompt
    assert "Cite memory numbers and dates inline for factual claims" in temporal_prompt
    assert "instead of bare memory references" in temporal_prompt
    assert "Preserve uncertainty and hedging from source memories" in temporal_prompt
    assert "do not turn maybe/probably/might/seems into certainty" in temporal_prompt
    assert "Do not invent projects, events, dates" in temporal_prompt
    assert "1. [NOTE] 2026-06-17 (timeframe match):" in temporal_prompt
    assert "**Temporal Grounding Rules:**" not in normal_prompt
    assert "Cite memory numbers and dates inline for factual claims" not in normal_prompt
    assert "Preserve uncertainty and hedging from source memories" not in normal_prompt
    assert "Use general knowledge and encourage exploration" in normal_prompt


def test_temporal_context_prompt_handles_no_memories_without_general_knowledge():
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=None)

    prompt = chat._build_context_prompt(
        {
            "temporal_context": "yesterday (2026-06-29)",
            "memories": [],
        },
        [],
    )

    assert "Only 0 memories were found for this timeframe" in prompt
    assert "retrieved evidence is insufficient" in prompt
    assert "do not use general knowledge to infer what happened" in prompt


def test_generate_enhanced_response_logs_temporal_diagnostics(monkeypatch):
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=ExplodingClient())
    logged = {}

    def fake_complete(client, model, messages):
        return "grounded answer"

    def fake_log_llm_interaction(**kwargs):
        logged.update(kwargs)

    monkeypatch.setattr("mentat.chat.enhanced_chat.complete", fake_complete)
    monkeypatch.setattr("mentat.chat.enhanced_chat.log_llm_interaction", fake_log_llm_interaction)

    response = chat._generate_enhanced_response(
        "what did I work on last week?",
        {
            "temporal_context": "last week (2026-06-15 to 2026-06-21)",
            "temporal_start_date": "2026-06-15",
            "temporal_end_date": "2026-06-21",
            "query_without_temporal": "",
            "memories": [
                {
                    "id": 42,
                    "content": "Worked on Mentat temporal retrieval.",
                    "command_type": "note",
                    "tags": [],
                    "timestamp": "2026-06-17",
                    "source_type": "timeframe",
                }
            ],
        },
        [],
        "test-model",
        user_id="u1",
    )

    assert response == "grounded answer"
    metadata = logged["metadata"]
    assert metadata["temporal_context"] == "last week (2026-06-15 to 2026-06-21)"
    assert metadata["start_date"] == "2026-06-15"
    assert metadata["end_date"] == "2026-06-21"
    assert metadata["query_without_temporal"] == ""
    assert metadata["user_id"] == "u1"
    assert metadata["num_memories"] == 1
    assert metadata["num_prompt_memories"] == 1
    assert metadata["prompt_memories"] == [
        {
            "prompt_index": 1,
            "id": 42,
            "source_type": "timeframe",
            "timestamp": "2026-06-17",
        }
    ]
