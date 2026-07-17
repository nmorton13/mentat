from contextlib import contextmanager
from datetime import datetime
from io import StringIO
import json
import sys
import types

import pytest

from mentat.cli import commands
from mentat.cli import mentat
from mentat.core import llm


class ExplodingCompletions:
    def create(self, **kwargs):
        raise AssertionError("direct chat completion should not be used")


class ExplodingClient:
    def __init__(self):
        self.chat = types.SimpleNamespace(completions=ExplodingCompletions())


class DummyDB:
    def __init__(self):
        self.deleted = []
        self.latest_limit = None
        self.viewed = []
        self.todos = []
        self.updated_todos = []

    def delete_memory(self, memory_id, user_id):
        self.deleted.append((memory_id, user_id))
        return {"id": memory_id}

    def get_all_memories(self, user_id, limit):
        self.latest_limit = limit
        return [
            {
                "id": 10,
                "content": "first",
                "command_type": "note",
                "tags": ["alpha"],
                "timestamp": "2026-06-15",
                "metadata": '{"source": {"type": "test"}}',
            }
        ]

    def get_memory_by_id(self, memory_id, user_id):
        self.viewed.append((memory_id, user_id))
        if memory_id == 10:
            return {
                "id": 10,
                "content": "first",
                "command_type": "note",
                "tags": ["alpha"],
                "timestamp": "2026-06-15",
                "metadata": "{}",
            }
        return None

    def get_user_todos(self, user_id, status_filter=None):
        return list(self.todos)

    def update_todo_status_by_id(self, user_id, todo_id, new_status):
        self.updated_todos.append((user_id, todo_id, new_status))
        return {"todo_id": todo_id, "status": new_status}

    def search_memories(self, user_id, query, limit=None):
        return []

    def comprehensive_search(self, user_id, query):
        return []


@contextmanager
def _noop_spinner(*args, **kwargs):
    yield None


@contextmanager
def _noop_chat_spinner(*args, **kwargs):
    yield None, None


def test_format_search_result_includes_metadata():
    item = {
        "id": 1,
        "content": "Check https://example.com for details",
        "command_type": "note",
        "tags": ["alpha"],
        "timestamp": "2025-06-01T10:00:00",
    }

    result = commands._format_search_result(item, 1, preview_length=50)

    assert result.startswith("1.")
    assert "Tags:" in result
    assert "Date:" in result
    assert "Type:" in result


def test_handle_delete_confirms_and_removes_item(monkeypatch):
    dummy_db = DummyDB()
    items = [
        {"id": 10, "content": "first", "command_type": "note", "timestamp": "2025-06-01"},
        {"id": 20, "content": "second", "command_type": "note", "timestamp": "2025-06-02"},
    ]

    monkeypatch.setattr(commands, "show_thinking_spinner", _noop_spinner)
    monkeypatch.setattr("builtins.input", lambda _: "DELETE")

    commands.handle_delete("1", "u1", dummy_db, items)

    assert dummy_db.deleted == [(10, "u1")]
    assert len(items) == 1
    assert items[0]["id"] == 20


def test_handle_delete_cancelled_does_not_remove(monkeypatch):
    dummy_db = DummyDB()
    items = [{"id": 10, "content": "first", "command_type": "note", "timestamp": "2025-06-01"}]

    monkeypatch.setattr(commands, "show_thinking_spinner", _noop_spinner)
    monkeypatch.setattr("builtins.input", lambda _: "NOPE")

    commands.handle_delete("1", "u1", dummy_db, items)

    assert dummy_db.deleted == []
    assert len(items) == 1


def test_detect_ai_query_matches_model_name(monkeypatch):
    monkeypatch.setattr(
        "mentat.core.config.AVAILABLE_MODELS",
        {"TestModel": "openai/gpt-4o"},
        raising=False
    )

    assert commands.detect_ai_query("Show me TestModel responses", "openai/gpt-4o") is True
    assert commands.detect_ai_query("My own notes", "openai/gpt-4o") is False


def test_handle_capture_preserves_content_containing_url(monkeypatch):
    saved = {}

    def fake_analysis(*args, **kwargs):
        return {
            "type": "note",
            "confidence": 0.9,
            "enhanced_content": "enhanced",
            "summary": "summary",
            "themes": ["alpha"],
            "actionable_items": [],
            "urls": ["https://example.com"],
            "tags": ["alpha"],
        }

    def fake_process(content, *args, **kwargs):
        saved["content"] = content
        return 123, ["alpha"], "note", ["alpha"], [], {}

    monkeypatch.setattr(commands, "analyze_capture_content", fake_analysis)
    monkeypatch.setattr(commands, "process_content_with_ai", fake_process)

    commands.handle_capture(
        content="Check https://example.com",
        user_id="u1",
        enable_web_search=False,
        current_model="model",
        openrouter_client=None,
        openai_client=None,
        db=DummyDB(),
        last_displayed_items=[]
    )

    assert saved["content"] == "Check https://example.com"


def test_handle_capture_web_enrichment_preserves_original_content(monkeypatch):
    analysis = {
        "type": "task",
        "confidence": 0.9,
        "enhanced_content": "Review https://example.com tomorrow",
        "summary": "Review the page",
        "themes": ["review"],
        "actionable_items": [{"action": "Review the page"}],
        "urls": ["https://example.com"],
        "tags": ["review"],
    }
    saved = {}

    monkeypatch.setattr(
        commands,
        "enrich_content_with_web_search",
        lambda content, *args: (content, {"web_context_summary": "Current context"}),
    )
    monkeypatch.setattr(commands, "analyze_capture_content", lambda *args, **kwargs: analysis)

    def fake_process(content, *args, **kwargs):
        saved["content"] = content
        saved["analysis"] = kwargs["precomputed_analysis"]
        return 123, ["focused"], "task", ["focused"], [], {}

    monkeypatch.setattr(commands, "process_content_with_ai", fake_process)

    commands.handle_capture(
        content="Review https://example.com tomorrow",
        user_id="u1",
        enable_web_search=True,
        current_model="model",
        openrouter_client=object(),
        openai_client=None,
        db=DummyDB(),
        last_displayed_items=[],
    )

    assert saved["content"] == "Review https://example.com tomorrow"
    assert saved["analysis"]["tags"] == ["review"]


def test_parse_latest_limit_accepts_positive_count():
    assert mentat.parse_latest_limit("25") == 25


def test_parse_latest_limit_rejects_invalid_count():
    with pytest.raises(ValueError):
        mentat.parse_latest_limit("zero")


def test_parse_todo_args_splits_status_from_search():
    assert mentat.parse_todo_args("pending") == (None, "pending")
    assert mentat.parse_todo_args("done") == (None, "done")
    assert mentat.parse_todo_args("garden") == ("garden", None)


def test_parse_connect_concepts_supports_plain_and_pipe_input():
    assert mentat.parse_connect_concepts("machine learning | mental health") == [
        "machine learning",
        "mental health",
    ]
    assert mentat.parse_connect_concepts("machine learning mental health") == [
        "machine learning mental",
        "health",
    ]


def test_extract_agent_flags_accepts_json_before_content():
    argv, flags = mentat.extract_agent_flags(["search", "--json", "machine", "learning"])

    assert argv == ["search", "machine", "learning"]
    assert flags.json_output is True
    assert flags.yes is False


def test_extract_agent_flags_accepts_yes_after_content():
    argv, flags = mentat.extract_agent_flags(["delete", "123", "--yes"])

    assert argv == ["delete", "123"]
    assert flags.json_output is False
    assert flags.yes is True


def test_extract_agent_flags_leaves_existing_args_alone():
    argv, flags = mentat.extract_agent_flags(["latest", "25", "--user", "u1"])

    assert argv == ["latest", "25", "--user", "u1"]
    assert flags == mentat.AgentFlags()


def test_handle_latest_uses_requested_limit(monkeypatch):
    dummy_db = DummyDB()
    monkeypatch.setattr(commands, "print_tool_reply", lambda *args, **kwargs: None)

    commands.handle_latest("u1", dummy_db, [], limit=25)

    assert dummy_db.latest_limit == 25


def run_main_with_args(monkeypatch, args):
    monkeypatch.setattr(mentat.sys, "argv", ["mentat", *args])
    monkeypatch.setattr(mentat, "print_banner", lambda: None)
    monkeypatch.setattr(mentat.console, "print", lambda *a, **k: None)

    mentat.main()


def test_main_version_reports_package_version(monkeypatch, capsys):
    monkeypatch.setattr(mentat.sys, "argv", ["mentat", "--version"])
    monkeypatch.setattr(mentat, "version", lambda _name: "0.8.0")

    with pytest.raises(SystemExit) as exc:
        mentat.main()

    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "Mentat 0.8.0"


def test_main_latest_json_emits_parseable_envelope(monkeypatch, capsys):
    dummy_db = DummyDB()
    monkeypatch.setattr(mentat.sys, "argv", ["mentat", "latest", "25", "--json", "--user", "u1"])
    monkeypatch.setattr(mentat, "db", dummy_db)
    monkeypatch.setattr(mentat, "print_banner", lambda: pytest.fail("banner should not print in JSON mode"))

    mentat.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == mentat.JSON_SCHEMA_VERSION
    assert payload["command"] == "latest"
    assert payload["success"] is True
    assert payload["data"]["limit"] == 25
    assert payload["data"]["items"][0]["id"] == 10


def test_main_todo_json_includes_persisted_todo_id(monkeypatch, capsys):
    dummy_db = DummyDB()
    dummy_db.todos = [
        {
            "todo_id": "todo_abc",
            "memory_id": 10,
            "item_index": 0,
            "display_number": 3,
            "action": "Write tests",
            "status": "pending",
            "priority": "high",
            "project": "Mentat",
            "source_content": "source",
        }
    ]
    monkeypatch.setattr(mentat.sys, "argv", ["mentat", "todo", "pending", "--json", "--user", "u1"])
    monkeypatch.setattr(mentat, "db", dummy_db)
    monkeypatch.setattr(mentat, "print_banner", lambda: pytest.fail("banner should not print in JSON mode"))

    mentat.main()

    payload = json.loads(capsys.readouterr().out)
    todo = payload["data"]["todos"][0]
    assert todo["id"] == "todo_abc"
    assert todo["memory_id"] == 10
    assert todo["item_index"] == 0
    assert todo["display_number"] == 3


def test_main_rejects_unsupported_json_command(monkeypatch, capsys):
    monkeypatch.setattr(mentat.sys, "argv", ["mentat", "model", "--json"])

    with pytest.raises(SystemExit) as exc:
        mentat.main()

    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert payload["error"]["code"] == "unsupported_json_command"


def test_main_rejects_unsupported_yes_flag_as_json(monkeypatch, capsys):
    monkeypatch.setattr(mentat.sys, "argv", ["mentat", "latest", "--json", "--yes"])

    with pytest.raises(SystemExit) as exc:
        mentat.main()

    assert exc.value.code == 1
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert payload["error"]["code"] == "unsupported_yes_flag"


def test_main_chat_json_emits_existing_chat_result(monkeypatch, capsys):
    class FakeEnhancedChat:
        def __init__(self, db, openrouter_client):
            self.session_references = {
                "1": {
                    "topic": "Agent CLI",
                    "context": "Tag from retrieved memories",
                    "personal_context": "Mentioned in recent roadmap work",
                    "timestamp": datetime(2026, 6, 15, 10, 30),
                }
            }

        def enhanced_chat_response(self, query, user_id, current_model, update_callback, status_callback=None):
            assert status_callback is None
            update_callback("same answer", "chat", query)
            return {
                "response": "same answer",
                "sources": [{"type": "semantic", "description": "Semantic similarity matches", "count": 2}],
                "patterns": ["Prefers notes"],
                "connections": [],
                "suggestions": ["Try a timeframe"],
            }

    monkeypatch.setattr(mentat.sys, "argv", ["mentat", "chat", "what changed?", "--json", "--user", "u1"])
    monkeypatch.setattr(mentat, "openrouter_client", object())
    monkeypatch.setattr(mentat, "current_model", "test-model")
    monkeypatch.setattr(mentat, "EnhancedChatSystem", FakeEnhancedChat)
    monkeypatch.setattr(mentat, "print_banner", lambda: pytest.fail("banner should not print in JSON mode"))
    monkeypatch.setattr(mentat, "print_enhanced_chat_reply", lambda *args, **kwargs: pytest.fail("JSON chat should not use Rich display"))
    monkeypatch.setattr(mentat, "show_thinking_spinner", lambda *args, **kwargs: pytest.fail("JSON chat should not start spinner"))

    mentat.main()

    payload = json.loads(capsys.readouterr().out)
    assert payload["schema_version"] == mentat.JSON_SCHEMA_VERSION
    assert payload["command"] == "chat"
    assert payload["success"] is True
    assert payload["data"]["query"] == "what changed?"
    assert payload["data"]["model"] == "test-model"
    assert payload["data"]["response"] == "same answer"
    assert payload["data"]["sources"][0]["type"] == "semantic"
    assert payload["data"]["references"][0]["id"] == "1"
    assert payload["data"]["references"][0]["timestamp"] == "2026-06-15T10:30:00"


def test_main_chat_without_json_still_uses_display(monkeypatch):
    captured = {}

    class FakeEnhancedChat:
        session_references = {}

        def __init__(self, db, openrouter_client):
            pass

        def enhanced_chat_response(self, query, user_id, current_model, update_callback, status_callback=None):
            captured["status_callback_present"] = status_callback is not None
            return {
                "response": "same answer",
                "sources": [],
                "patterns": [],
                "connections": [],
                "suggestions": [],
            }

    monkeypatch.setattr(mentat, "openrouter_client", object())
    monkeypatch.setattr(mentat, "EnhancedChatSystem", FakeEnhancedChat)
    monkeypatch.setattr(mentat, "show_thinking_spinner", _noop_chat_spinner)
    monkeypatch.setattr(mentat, "make_spinner_status_callback", lambda progress, task: object())
    monkeypatch.setattr(mentat, "print_enhanced_chat_reply", lambda result, *args: captured.update(result=result))

    run_main_with_args(monkeypatch, ["chat", "what changed?", "--user", "u1"])

    assert captured["status_callback_present"] is True
    assert captured["result"]["response"] == "same answer"


def test_main_dispatches_latest_count(monkeypatch):
    captured = {}

    def fake_latest(user_id, db, last_displayed_items, limit):
        captured["user_id"] = user_id
        captured["limit"] = limit

    monkeypatch.setattr(mentat, "handle_latest", fake_latest)

    run_main_with_args(monkeypatch, ["latest", "25", "--user", "u1"])

    assert captured == {"user_id": "u1", "limit": 25}


def test_main_capture_dash_reads_stdin(monkeypatch):
    captured = {}

    def fake_capture(content, user_id, enable_web_search, current_model, openrouter_client, openai_client, db, last_displayed_items):
        captured["content"] = content

    monkeypatch.setattr(mentat, "handle_capture", fake_capture)
    monkeypatch.setattr(mentat.sys, "stdin", StringIO("line one\nline two\n"))

    run_main_with_args(monkeypatch, ["capture", "-", "--user", "u1"])

    assert captured == {"content": "line one\nline two"}


def test_main_delete_requires_yes(monkeypatch):
    dummy_db = DummyDB()
    monkeypatch.setattr(mentat, "db", dummy_db)

    with pytest.raises(SystemExit) as exc:
        run_main_with_args(monkeypatch, ["delete", "10", "--user", "u1"])

    assert exc.value.code == 1
    assert dummy_db.deleted == []


def test_main_delete_with_yes_removes_memory(monkeypatch):
    dummy_db = DummyDB()
    monkeypatch.setattr(mentat, "db", dummy_db)

    run_main_with_args(monkeypatch, ["delete", "10", "--yes", "--user", "u1"])

    assert dummy_db.deleted == [(10, "u1")]


def test_main_mark_uses_persisted_todo_id(monkeypatch):
    dummy_db = DummyDB()
    dummy_db.todos = [{"todo_id": "todo_abc", "status": "pending"}]
    monkeypatch.setattr(mentat, "db", dummy_db)

    run_main_with_args(monkeypatch, ["mark", "todo_abc", "--user", "u1"])

    assert dummy_db.updated_todos == [("u1", "todo_abc", "done")]


def test_main_dispatches_todo_status(monkeypatch):
    captured = {}

    def fake_todo(user_id, search_term, db, status_filter, last_displayed_items):
        captured["user_id"] = user_id
        captured["search_term"] = search_term
        captured["status_filter"] = status_filter

    monkeypatch.setattr(mentat, "handle_todo", fake_todo)

    run_main_with_args(monkeypatch, ["todo", "pending", "--user", "u1"])

    assert captured == {"user_id": "u1", "search_term": None, "status_filter": "pending"}


def test_main_dispatches_model(monkeypatch):
    captured = {}

    def fake_model(arg):
        captured["arg"] = arg

    monkeypatch.setattr(mentat, "openrouter_client", object())
    monkeypatch.setattr(mentat, "handle_model_command", fake_model)

    run_main_with_args(monkeypatch, ["model", "grok-4.5"])

    assert captured == {"arg": "grok-4.5"}


def test_model_command_switches_current_model_without_online_model(monkeypatch):
    saved = []
    routes = []
    monkeypatch.setattr(mentat, "AVAILABLE_MODELS", {"gpt-5": "openai/gpt-5.6-terra"})
    monkeypatch.setattr(mentat, "current_model", "qwen-local")
    monkeypatch.setattr(mentat, "set_chat_route", lambda provider, model: routes.append((provider, model)) or True)
    monkeypatch.setattr(mentat, "set_current_model", lambda model: saved.append(model) or True)
    monkeypatch.setattr(mentat, "build_chat_client", lambda: "new-chat-client")
    monkeypatch.setattr(mentat, "display_models_table", lambda current_model: None)
    monkeypatch.setattr(mentat.console, "print", lambda *args, **kwargs: None)

    mentat.handle_model_command("gpt-5")

    assert mentat.current_model == "openai/gpt-5.6-terra"
    assert routes == [("openrouter", "openai/gpt-5.6-terra")]
    assert saved == ["openai/gpt-5.6-terra"]


def test_model_command_accepts_custom_model_when_config_allows(monkeypatch):
    saved = []
    monkeypatch.setattr(mentat, "AVAILABLE_MODELS", {"gpt-5": "openai/gpt-5.6-terra"})
    monkeypatch.setattr(mentat, "current_model", "openai/gpt-5.6-terra")
    monkeypatch.setattr(mentat, "set_current_model", lambda model: saved.append(model) or True)
    monkeypatch.setattr(mentat, "display_models_table", lambda current_model: None)
    monkeypatch.setattr(mentat.console, "print", lambda *args, **kwargs: None)

    mentat.handle_model_command("qwen-local")

    assert mentat.current_model == "qwen-local"
    assert saved == ["qwen-local"]


def test_model_command_saved_model_selects_openrouter_route(monkeypatch):
    routes = []
    monkeypatch.setattr(mentat, "AVAILABLE_MODELS", {"grok": "x-ai/grok-4.5"})
    monkeypatch.setattr(mentat, "set_chat_route", lambda provider, model: routes.append((provider, model)) or True)
    monkeypatch.setattr(mentat, "set_current_model", lambda model: True)
    monkeypatch.setattr(mentat, "build_chat_client", lambda: "new-chat-client")
    monkeypatch.setattr(mentat, "display_llm_routes_table", lambda current_model, chat_client=None: None)
    monkeypatch.setattr(mentat, "display_models_table", lambda current_model: None)
    monkeypatch.setattr(mentat.console, "print", lambda *args, **kwargs: None)

    mentat.handle_model_command("grok")

    assert routes == [("openrouter", "x-ai/grok-4.5")]
    assert mentat.current_model == "x-ai/grok-4.5"
    assert mentat.openrouter_client == "new-chat-client"


def test_model_command_local_selects_configured_local_route(monkeypatch):
    routes = []
    from mentat.core import config as core_config

    monkeypatch.setattr(core_config, "CHAT_MODEL", "google/gemma-4-12b-qat")
    monkeypatch.setattr(core_config, "LOCAL_MODEL", "")
    monkeypatch.setattr(core_config, "CHAT_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setattr(core_config, "LOCAL_BASE_URL", None)
    monkeypatch.setattr(mentat, "set_chat_route", lambda provider, model: routes.append((provider, model)) or True)
    monkeypatch.setattr(mentat, "set_current_model", lambda model: True)
    monkeypatch.setattr(mentat, "build_chat_client", lambda: "local-client")
    monkeypatch.setattr(mentat, "display_llm_routes_table", lambda current_model, chat_client=None: None)
    monkeypatch.setattr(mentat, "display_models_table", lambda current_model: None)
    monkeypatch.setattr(mentat.console, "print", lambda *args, **kwargs: None)

    mentat.handle_model_command("local")

    assert routes == [("local", "google/gemma-4-12b-qat")]
    assert mentat.current_model == "google/gemma-4-12b-qat"
    assert mentat.openrouter_client == "local-client"


def test_model_command_ollama_selects_native_route(monkeypatch):
    routes = []
    from mentat.core import config as core_config

    monkeypatch.setattr(core_config, "OLLAMA_MODEL", "gemma4:12b-mlx")
    monkeypatch.setattr(mentat, "set_chat_route", lambda provider, model: routes.append((provider, model)) or True)
    monkeypatch.setattr(mentat, "set_current_model", lambda model: True)
    monkeypatch.setattr(mentat, "build_chat_client", lambda: "ollama-client")
    monkeypatch.setattr(mentat, "display_llm_routes_table", lambda current_model, chat_client=None: None)
    monkeypatch.setattr(mentat, "display_models_table", lambda current_model: None)
    monkeypatch.setattr(mentat.console, "print", lambda *args, **kwargs: None)

    mentat.handle_model_command("ollama gemma4:12b-mlx")

    assert routes == [("ollama", "gemma4:12b-mlx")]
    assert mentat.current_model == "gemma4:12b-mlx"
    assert mentat.openrouter_client == "ollama-client"


def test_build_chat_client_returns_ollama_adapter_without_api_key(monkeypatch):
    monkeypatch.setattr(mentat, "get_chat_provider", lambda: "ollama")
    monkeypatch.setattr(mentat, "get_chat_base_url", lambda: "http://127.0.0.1:11434")
    monkeypatch.setattr(mentat, "get_chat_api_key", lambda: None)

    client = mentat.build_chat_client()

    assert isinstance(client, mentat.OllamaChatClient)


def test_main_dispatches_synthesize(monkeypatch):
    captured = {}

    def fake_synthesize(user_id, topic, current_model, openrouter_client, openai_client, db):
        captured["user_id"] = user_id
        captured["topic"] = topic

    monkeypatch.setattr(mentat, "handle_synthesize", fake_synthesize)

    run_main_with_args(monkeypatch, ["synthesize", "React learning", "--user", "u1"])

    assert captured == {"user_id": "u1", "topic": "React learning"}


def test_main_dispatches_explore(monkeypatch):
    captured = {}

    def fake_explore(concept_or_number, user_id, db, openrouter_client, last_displayed_items, global_enhanced_chat, interactive):
        captured["concept"] = concept_or_number
        captured["user_id"] = user_id
        captured["interactive"] = interactive

    monkeypatch.setattr(commands, "handle_explore_web_command", fake_explore)

    run_main_with_args(monkeypatch, ["explore", "machine learning", "--user", "u1"])

    assert captured == {"concept": "machine learning", "user_id": "u1", "interactive": False}


def test_main_dispatches_explain(monkeypatch):
    captured = {}

    def fake_explain(concept_or_number, user_id, db, openrouter_client, global_enhanced_chat, last_displayed_items):
        captured["concept"] = concept_or_number
        captured["user_id"] = user_id
        captured["last_displayed_items"] = last_displayed_items

    monkeypatch.setattr(commands, "handle_explain_command", fake_explain)

    run_main_with_args(monkeypatch, ["explain", "deep learning", "--user", "u1"])

    assert captured == {"concept": "deep learning", "user_id": "u1", "last_displayed_items": []}


def test_interactive_numbered_context_preserves_explore_and_explain():
    assert {"view", "delete", "mark", "explore", "explain"}.issubset(
        mentat.NUMBERED_CONTEXT_COMMANDS
    )


def test_main_dispatches_connect(monkeypatch):
    captured = {}

    def fake_connect(concept1, concept2, user_id, openrouter_client, db, current_model):
        captured["concept1"] = concept1
        captured["concept2"] = concept2
        captured["user_id"] = user_id

    monkeypatch.setattr(commands, "handle_connect_command", fake_connect)

    run_main_with_args(monkeypatch, ["connect", "machine learning", "|", "mental health", "--user", "u1"])

    assert captured == {
        "concept1": "machine learning",
        "concept2": "mental health",
        "user_id": "u1",
    }


def test_main_dispatches_chat(monkeypatch):
    captured = {}

    class FakeEnhancedChat:
        def __init__(self, db, openrouter_client):
            captured["init_client"] = openrouter_client

        def enhanced_chat_response(self, query, user_id, current_model, update_callback, status_callback=None):
            captured["query"] = query
            captured["user_id"] = user_id
            return {"response": "ok"}

    monkeypatch.setattr(mentat, "openrouter_client", object())
    monkeypatch.setattr(mentat, "EnhancedChatSystem", FakeEnhancedChat)
    monkeypatch.setattr(mentat, "show_thinking_spinner", _noop_chat_spinner)
    monkeypatch.setattr(mentat, "make_spinner_status_callback", lambda progress, task: None)
    monkeypatch.setattr(mentat, "print_enhanced_chat_reply", lambda *a, **k: None)

    run_main_with_args(monkeypatch, ["chat", "what changed recently?", "--user", "u1"])

    assert captured["query"] == "what changed recently?"
    assert captured["user_id"] == "u1"


def test_handle_save_response_stores_ai_response_command_type(monkeypatch):
    captured = {}

    def fake_save_memory(content, user_id, command_type, tags, metadata, db, openai_client):
        captured["content"] = content
        captured["user_id"] = user_id
        captured["command_type"] = command_type
        captured["tags"] = tags
        captured["metadata"] = metadata
        return 123

    monkeypatch.setattr(commands, "save_memory", fake_save_memory)
    monkeypatch.setattr(commands.console, "print", lambda *args, **kwargs: None)

    commands.handle_save_response(
        user_id="u1",
        current_model="z-ai/glm-5.2",
        openrouter_client=None,
        openai_client=None,
        db=DummyDB(),
        last_displayed_items=[],
        last_ai_response="Saved response",
        last_ai_response_command="chat",
        last_ai_prompt="What should I think about this?",
        clear_response_callback=None,
    )

    assert captured["content"] == "Saved response"
    assert captured["user_id"] == "u1"
    assert captured["command_type"] == "ai_response"
    assert captured["tags"] == ["ai_response"]
    source_info = captured["metadata"]["source"]
    assert source_info["type"] == "ai_response"
    assert source_info["model"] == "z-ai/glm-5.2"
    assert source_info["command"] == "chat"
    assert source_info["prompt"] == "What should I think about this?"


def test_extract_concept_from_deep_concept_exploration_item():
    item = {
        "command_type": "deep_concept_exploration",
        "content": "Concept: Data Bias",
        "concept_data": {"name": "Data Bias"},
    }

    assert commands._extract_concept_from_item(item) == "Data Bias"


def test_handle_explain_resolves_last_displayed_deep_concept(monkeypatch):
    captured = {}

    class FakeIntegrationManager:
        def __init__(self, db, openrouter_client):
            captured["init"] = (db, openrouter_client)

        def generate_concept_explanation(self, concept, user_id, current_model):
            captured["concept"] = concept
            captured["user_id"] = user_id
            captured["model"] = current_model
            return "Explanation for Data Bias"

    monkeypatch.setattr(
        "mentat.concepts.concept_integration.ConceptIntegrationManager",
        FakeIntegrationManager,
    )
    monkeypatch.setattr(commands, "show_thinking_spinner", _noop_spinner)
    monkeypatch.setattr(commands.console, "print", lambda *args, **kwargs: None)

    last_displayed_items = [
        {
            "command_type": "deep_concept_exploration",
            "content": "Concept: Data Bias",
            "concept_data": {"name": "Data Bias"},
        }
    ]

    commands.handle_explain_command(
        "1",
        "u1",
        DummyDB(),
        openrouter_client=object(),
        global_enhanced_chat=None,
        last_displayed_items=last_displayed_items,
    )

    assert captured["concept"] == "Data Bias"
    assert captured["user_id"] == "u1"
    assert captured["model"] == "gpt-4o-mini"


def test_cli_reference_explanation_uses_online_wrapper(monkeypatch):
    calls = []

    def fake_complete_online(client, model, messages, **kwargs):
        calls.append((client, model, messages, kwargs))
        from mentat.core.llm import CompletionResult
        return CompletionResult(text="Wrapped reference explanation", response=object(), model=f"{model}:online")

    monkeypatch.setattr(commands, "complete_online", fake_complete_online)

    result = commands.generate_reference_explanation(
        {"topic": "SQLite vectors", "context": "chat reference"},
        "u1",
        "test-model",
        ExplodingClient(),
        DummyDB(),
    )

    assert "Wrapped reference explanation" in result
    assert calls[0][0].__class__ is ExplodingClient
    assert calls[0][1] == "test-model"
    assert calls[0][3]["max_tokens"] == commands.REFERENCE_EXPLANATION_MAX_TOKENS


def test_concept_connection_analysis_uses_plain_wrapper(monkeypatch):
    calls = []

    def fake_complete(client, model, messages, **kwargs):
        calls.append((client, model, messages, kwargs))
        return "Wrapped connection analysis"

    monkeypatch.setattr(commands, "complete", fake_complete)
    monkeypatch.setattr(
        "mentat.core.llm.get_task_llm_route",
        lambda prefix, client: llm.LLMRoute("chat", client, "connection-test-model"),
    )

    result = commands._generate_concept_connection_analysis(
        "SQLite",
        "Embeddings",
        "u1",
        ExplodingClient(),
        DummyDB(),
        current_model="test-model",
    )

    assert result == "Wrapped connection analysis"
    assert calls[0][0].__class__ is ExplodingClient
    assert calls[0][1] == "connection-test-model"
    assert calls[0][3]["temperature"] == 0.3


def test_handle_link_saves_only_url_and_comment(monkeypatch):
    saved = {}

    analysis = {
        "type": "link",
        "confidence": 0.9,
        "enhanced_content": "ignored enhancement",
        "summary": "User-provided link note",
        "themes": ["research"],
        "actionable_items": [],
        "urls": ["https://example.com/post"],
        "tags": ["research"],
    }

    monkeypatch.setattr(commands, "analyze_capture_content", lambda *args, **kwargs: analysis)
    monkeypatch.setattr(commands, "get_embedding_for_content", lambda *args, **kwargs: None)
    monkeypatch.setattr(commands, "show_thinking_spinner", _noop_spinner)

    def fake_process(content, *args, **kwargs):
        saved["content"] = content
        saved["metadata"] = kwargs["metadata"]
        saved["markdown_extra"] = kwargs.get("markdown_extra")
        return 42, ["research"], "link", ["research"], [], {}

    monkeypatch.setattr(commands, "process_content_with_ai", fake_process)
    displayed = []

    commands.handle_link(
        "https://example.com/post This changed how I think about memory",
        "u1",
        "model",
        object(),
        None,
        DummyDB(),
        displayed,
    )

    assert saved["content"] == (
        "URL: https://example.com/post\n"
        "Comment: This changed how I think about memory"
    )
    assert saved["metadata"]["source"] == {
        "type": "link",
        "url": "https://example.com/post",
    }
    assert saved["metadata"]["user_note"] == "This changed how I think about memory"
    assert saved["markdown_extra"] is None
    assert displayed == [{
        "id": 42,
        "content": saved["content"],
        "type": "link",
        "url": "https://example.com/post",
    }]
