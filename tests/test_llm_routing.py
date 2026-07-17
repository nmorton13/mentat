from mentat.cli import commands
from mentat.core import ai, config, llm
from mentat.core.llm import LLMRoute, get_llm_route_display_rows, get_llm_route_summary, get_task_llm_route


def test_task_route_defaults_to_chat_active_model(monkeypatch):
    monkeypatch.setattr(config, "CONCEPT_EXPLORATION_PROVIDER", "chat")
    monkeypatch.setattr(config, "CONCEPT_EXPLORATION_MODEL", None)
    monkeypatch.setattr(config, "get_current_model", lambda: "active-chat-model")

    route = get_task_llm_route("CONCEPT_EXPLORATION", chat_client="chat-client")

    assert route.provider == "chat"
    assert route.client == "chat-client"
    assert route.model == "active-chat-model"
    assert route.model_source == "active chat model"


def test_task_route_openrouter_uses_openrouter_client_and_task_model(monkeypatch):
    created = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr(config, "CONCEPT_EXPLORATION_PROVIDER", "openrouter")
    monkeypatch.setattr(config, "CONCEPT_EXPLORATION_MODEL", "openrouter-task-model")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")
    monkeypatch.setattr(config, "OPENROUTER_BASE_URL", "https://openrouter.example/v1")
    monkeypatch.setattr("mentat.core.llm.OpenAI", FakeOpenAI)
    monkeypatch.setattr("mentat.core.llm._ROUTE_CLIENTS", {})

    route = get_task_llm_route("CONCEPT_EXPLORATION", chat_client="chat-client")

    assert route.provider == "openrouter"
    assert route.client is not None
    assert route.model == "openrouter-task-model"
    assert route.model_source == "task override"
    assert created["api_key"] == "test-key"
    assert created["base_url"] == "https://openrouter.example/v1"


def test_entity_extraction_uses_entity_route_not_legacy_model_hint(monkeypatch):
    route_calls = []

    def fake_route(prefix, chat_client, requested_model=None):
        route_calls.append((prefix, chat_client, requested_model))
        return LLMRoute("chat", "entity-client", "active-chat-model")

    def fake_complete_json(client, model, messages, **kwargs):
        return {"concepts": ["routing"]}

    monkeypatch.setattr(ai, "get_task_llm_route", fake_route)
    monkeypatch.setattr(ai, "complete_json", fake_complete_json)
    monkeypatch.setattr(config, "FAST_ENTITY_MODEL", "legacy-fast-model")

    result = ai.extract_structured_entities("provider routing", model="legacy-fast-model", client="chat-client")

    assert route_calls == [("ENTITY_EXTRACTION", "chat-client", None)]
    assert result["concepts"] == ["routing"]


def test_task_route_local_uses_local_provider_defaults(monkeypatch):
    created = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            created.update(kwargs)

    monkeypatch.setattr(config, "ENTITY_EXTRACTION_PROVIDER", "local")
    monkeypatch.setattr(config, "ENTITY_EXTRACTION_MODEL", None)
    monkeypatch.setattr(config, "LOCAL_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setattr(config, "LOCAL_API_KEY", "local-key")
    monkeypatch.setattr(config, "LOCAL_MODEL", "local-model")
    monkeypatch.setattr("mentat.core.llm.OpenAI", FakeOpenAI)
    monkeypatch.setattr("mentat.core.llm._ROUTE_CLIENTS", {})

    route = get_task_llm_route("ENTITY_EXTRACTION", chat_client="chat-client")

    assert route.provider == "local"
    assert route.client is not None
    assert route.model == "local-model"
    assert route.model_source == "local default"
    assert created["api_key"] == "local-key"
    assert created["base_url"] == "http://localhost:1234/v1"


def test_task_route_ollama_uses_native_client(monkeypatch):
    monkeypatch.setattr(config, "ENTITY_EXTRACTION_PROVIDER", "ollama")
    monkeypatch.setattr(config, "ENTITY_EXTRACTION_MODEL", None)
    monkeypatch.setattr(config, "OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setattr(config, "OLLAMA_MODEL", "gemma4:12b-mlx")
    monkeypatch.setattr("mentat.core.llm._ROUTE_CLIENTS", {})

    route = get_task_llm_route("ENTITY_EXTRACTION", chat_client="chat-client")

    assert route.provider == "ollama"
    assert isinstance(route.client, llm.OllamaChatClient)
    assert route.model == "gemma4:12b-mlx"
    assert route.model_source == "ollama default"
    assert route.base_url == "http://127.0.0.1:11434"


def test_route_display_rows_include_primary_routes(monkeypatch):
    monkeypatch.setattr(config, "CONCEPT_EXPLORATION_PROVIDER", "chat")
    monkeypatch.setattr(config, "CONCEPT_EXPLORATION_MODEL", None)
    monkeypatch.setattr(config, "ENTITY_EXTRACTION_PROVIDER", "chat")
    monkeypatch.setattr(config, "ENTITY_EXTRACTION_MODEL", None)
    monkeypatch.setattr(config, "CONCEPT_CONNECTION_PROVIDER", "openrouter")
    monkeypatch.setattr(config, "CONCEPT_CONNECTION_MODEL", "connection-model")
    monkeypatch.setattr(config, "CAPTURE_ANALYSIS_PROVIDER", "chat")
    monkeypatch.setattr(config, "CAPTURE_ANALYSIS_MODEL", None)
    monkeypatch.setattr(config, "TODO_EXTRACTION_PROVIDER", "chat")
    monkeypatch.setattr(config, "TODO_EXTRACTION_MODEL", None)
    monkeypatch.setattr(config, "TEMPORAL_INTENT_PROVIDER", "chat")
    monkeypatch.setattr(config, "TEMPORAL_INTENT_MODEL", None)
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", None)
    monkeypatch.setattr(config, "ONLINE_MODEL", "online-model")

    rows = get_llm_route_display_rows(chat_client="chat-client", current_model="chat-model")
    rows_by_feature = {row["feature"]: row for row in rows}

    assert set(rows_by_feature) == {
        "Chat",
        "ConceptExplorer",
        "Entity Extraction",
        "Concept Connection",
        "Capture Analysis",
        "Todo Extraction",
        "Temporal Intent",
        "Online/Web",
    }
    assert rows_by_feature["Chat"]["model"] == "chat-model"
    assert rows_by_feature["ConceptExplorer"]["provider"] == "chat"
    assert rows_by_feature["Entity Extraction"]["provider"] == "chat"
    assert rows_by_feature["Concept Connection"]["provider"] == "openrouter"
    assert rows_by_feature["Concept Connection"]["status"] == "missing api key"
    assert rows_by_feature["Capture Analysis"]["provider"] == "chat"
    assert rows_by_feature["Todo Extraction"]["provider"] == "chat"
    assert rows_by_feature["Temporal Intent"]["provider"] == "chat"
    assert rows_by_feature["Online/Web"]["model"] == "online-model"


def test_llm_route_summary_reflects_local_chat_and_feature_routes(monkeypatch):
    monkeypatch.setattr(config, "_runtime_chat_provider", lambda: None)
    monkeypatch.setattr(config, "CHAT_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setattr(config, "CONCEPT_EXPLORATION_PROVIDER", "openrouter")
    monkeypatch.setattr(config, "CONCEPT_EXPLORATION_MODEL", "concept-model")
    monkeypatch.setattr(config, "ENTITY_EXTRACTION_PROVIDER", "chat")
    monkeypatch.setattr(config, "ENTITY_EXTRACTION_MODEL", None)
    monkeypatch.setattr(config, "CONCEPT_CONNECTION_PROVIDER", "local")
    monkeypatch.setattr(config, "CONCEPT_CONNECTION_MODEL", "connection-local-model")
    monkeypatch.setattr(config, "LOCAL_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setattr(config, "ONLINE_MODEL", "online-model")
    monkeypatch.setattr(config, "OPENROUTER_API_KEY", "test-key")

    summary = get_llm_route_summary(chat_client="chat-client", current_model="local-chat-model")

    assert "Chat local → local-chat-model" in summary
    assert "concept=openrouter" in summary
    assert "entity=chat/local" in summary
    assert "connect=local" in summary
    assert "online=openrouter" in summary
    assert "via OpenRouter" not in summary


def test_concept_connection_uses_route_not_fast_entity_model(monkeypatch):
    class DummyDB:
        def comprehensive_search(self, user_id, concept):
            return [{"content": f"memory about {concept}"}]

    route_calls = []
    complete_calls = []

    def fake_route(prefix, chat_client, requested_model=None):
        route_calls.append((prefix, chat_client, requested_model))
        return LLMRoute("chat", "connection-client", "connection-model")

    def fake_complete(client, model, messages, **kwargs):
        complete_calls.append({"client": client, "model": model, "kwargs": kwargs})
        return "connection analysis"

    monkeypatch.setattr(llm, "get_task_llm_route", fake_route)
    monkeypatch.setattr(commands, "complete", fake_complete)
    monkeypatch.setattr(config, "FAST_ENTITY_MODEL", "legacy-fast-model")

    result = commands._generate_concept_connection_analysis(
        "workflow",
        "productivity",
        "user1",
        "chat-client",
        DummyDB(),
        current_model="legacy-current-model",
    )

    assert result == "connection analysis"
    assert route_calls == [("CONCEPT_CONNECTION", "chat-client", None)]
    assert complete_calls[0]["client"] == "connection-client"
    assert complete_calls[0]["model"] == "connection-model"
