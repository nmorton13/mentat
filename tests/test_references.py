from mentat.chat.enhanced_chat import EnhancedChatSystem


class DummyDB:
    def comprehensive_search(self, user_id, query):
        return []


class ExplodingCompletions:
    def create(self, **kwargs):
        raise AssertionError("post-answer reference preparation should not call the LLM")


class ExplodingClient:
    def __init__(self):
        self.chat = type("Chat", (), {"completions": ExplodingCompletions()})()


def test_reference_lifecycle():
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=None)

    ref_id = chat.add_reference("Topic", "Context")
    reference = chat.get_reference(ref_id)

    assert reference["topic"] == "Topic"

    chat.clear_references()

    assert chat.get_reference(ref_id) is None


def test_prepare_exploration_references_uses_context_without_mutating_response():
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=ExplodingClient())
    context_data = {
        "query_entities": {
            "concepts": ["Beautiful Mess"],
            "technologies": ["LM Studio"],
        },
        "memories": [
            {
                "tags": ["first-principles", "beautiful_mess", "note"],
                "command_type": "reflection",
                "timestamp": "2026-05-20",
            },
            {
                "tags": ["order and chaos", "first-principles"],
                "command_type": "idea",
                "timestamp": "2026-02-10",
            },
        ],
        "entity_connections": [
            ({"command_type": "reflection", "timestamp": "2025-10-24"}, ["emergent order"])
        ],
    }

    response = "First Principles can support a Beautiful Mess."
    result = chat._prepare_exploration_references(response, context_data)

    assert result == response
    topics = [reference["topic"] for reference in chat.session_references.values()]
    assert topics[:2] == ["Beautiful Mess", "LM Studio"]
    assert "first principles" in topics
    assert "note" not in topics


def test_prepare_exploration_references_skips_quick_mode():
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=ExplodingClient())

    result = chat._prepare_exploration_references(
        "Short answer.",
        {"query_entities": {"concepts": ["Beautiful Mess"]}, "memories": []},
        intent="quick",
    )

    assert result == "Short answer."
    assert chat.session_references == {}


def test_generate_reference_explanation_uses_online_wrapper(monkeypatch):
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=ExplodingClient())
    calls = []

    def fake_complete_online(client, model, messages, **kwargs):
        calls.append((client, model, messages, kwargs))
        from mentat.core.llm import CompletionResult
        return CompletionResult(text="Detailed explanation", response=object(), model=f"{model}:online")

    monkeypatch.setattr("mentat.chat.enhanced_chat.complete_online", fake_complete_online)

    result = chat.generate_reference_explanation(
        {"topic": "SQLite vectors", "context": "chat reference", "personal_context": "notes"},
        "user-1",
        "test-model",
    )

    assert result == "Detailed explanation"
    assert calls[0][0] is chat.client
    assert calls[0][1] == "test-model"
    assert calls[0][3]["max_tokens"] == 1500


def test_generate_reference_explanation_fallback_uses_plain_wrapper(monkeypatch):
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=ExplodingClient())
    calls = []

    def fake_complete_online(*args, **kwargs):
        raise RuntimeError("online unavailable")

    def fake_complete(client, model, messages, **kwargs):
        calls.append((client, model, messages, kwargs))
        return "Fallback explanation"

    monkeypatch.setattr("mentat.chat.enhanced_chat.complete_online", fake_complete_online)
    monkeypatch.setattr("mentat.chat.enhanced_chat.complete", fake_complete)

    result = chat.generate_reference_explanation(
        {"topic": "SQLite vectors", "context": "chat reference"},
        "user-1",
        "test-model:online",
    )

    assert result == "Fallback explanation\n\n*Note: Limited explanation due to research unavailability.*"
    assert calls[0][0] is chat.client
    assert calls[0][1] == "test-model"
    assert calls[0][3]["max_tokens"] == 800
