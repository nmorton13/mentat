import importlib
import json
from pathlib import Path

import pytest


def _load_config(monkeypatch, tmp_path, clear_online_model=True, clear_chat_provider=True, clear_helper_settings=True):
    model_config = tmp_path / "models.json"
    runtime_settings = tmp_path / "runtime_settings.json"
    model_config.write_text(
        json.dumps(
            {
                "default_model": "x-ai/grok-4.5",
                "models": [
                    {"id": "x-ai/grok-4.5", "label": "grok", "reasoning": True},
                    {"id": "openai/gpt-5.6-terra", "label": "gpt-5", "reasoning": True},
                    {"id": "openai/gpt-chat-latest", "label": "gpt-chat", "reasoning": False},
                ],
            }
        )
    )
    monkeypatch.setenv("MODEL_CONFIG_PATH", str(model_config))
    monkeypatch.setenv("RUNTIME_SETTINGS_PATH", str(runtime_settings))
    monkeypatch.setenv("OPENROUTER_API_KEY", "")
    monkeypatch.setenv("OPENROUTER_MODEL", "x-ai/grok-4.5")
    if clear_chat_provider:
        monkeypatch.setenv("CHAT_BASE_URL", "")
        monkeypatch.setenv("CHAT_API_KEY", "")
        monkeypatch.setenv("CHAT_MODEL", "")
    if clear_online_model:
        monkeypatch.setenv("ONLINE_MODEL", "")
    if clear_helper_settings:
        helper_envs = [
            "HELPERS_PROVIDER",
            "HELPERS_MODEL",
            "CONCEPT_EXPLORATION_PROVIDER",
            "CONCEPT_EXPLORATION_MODEL",
            "ENTITY_EXTRACTION_PROVIDER",
            "ENTITY_EXTRACTION_MODEL",
            "CONCEPT_CONNECTION_PROVIDER",
            "CONCEPT_CONNECTION_MODEL",
            "CAPTURE_ANALYSIS_PROVIDER",
            "CAPTURE_ANALYSIS_MODEL",
            "TODO_EXTRACTION_PROVIDER",
            "TODO_EXTRACTION_MODEL",
            "TEMPORAL_INTENT_PROVIDER",
            "TEMPORAL_INTENT_MODEL",
        ]
        for env_name in helper_envs:
            monkeypatch.setenv(env_name, "")

    import mentat.core.config as config

    return importlib.reload(config), runtime_settings


def test_runtime_model_roundtrip(monkeypatch, tmp_path):
    config, runtime_settings = _load_config(monkeypatch, tmp_path)

    assert config.get_current_model() == "x-ai/grok-4.5"
    assert config.set_current_model("openai/gpt-5.6-terra") is True
    assert config.get_current_model() == "openai/gpt-5.6-terra"

    data = json.loads(runtime_settings.read_text())
    assert data["current_model"] == "openai/gpt-5.6-terra"


def test_online_model_loads_independently_from_current_model(monkeypatch, tmp_path):
    config, _runtime_settings = _load_config(monkeypatch, tmp_path)
    assert config.ONLINE_MODEL is None

    monkeypatch.setenv("ONLINE_MODEL", "openai/gpt-chat-latest")
    config, _runtime_settings = _load_config(monkeypatch, tmp_path, clear_online_model=False)

    assert config.ONLINE_MODEL == "openai/gpt-chat-latest"
    assert config.get_current_model() == "x-ai/grok-4.5"


def test_chat_provider_settings_are_optional_and_override_normal_model(monkeypatch, tmp_path):
    config, _runtime_settings = _load_config(monkeypatch, tmp_path)
    assert config.get_chat_base_url() == config.OPENROUTER_BASE_URL
    assert config.get_chat_api_key() is None
    assert config.get_current_model() == "x-ai/grok-4.5"

    monkeypatch.setenv("CHAT_BASE_URL", "http://localhost:1234/v1")
    monkeypatch.setenv("CHAT_MODEL", "qwen-local")
    config, _runtime_settings = _load_config(monkeypatch, tmp_path, clear_chat_provider=False)

    assert config.get_chat_base_url() == "http://localhost:1234/v1"
    assert config.get_chat_api_key() == "local"
    assert config.get_current_model() == "qwen-local"
    assert config.set_current_model("another-local-model") is True
    assert config.get_current_model() == "another-local-model"


def test_ollama_runtime_route_is_distinct_from_local(monkeypatch, tmp_path):
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "gemma4:12b-mlx")
    config, runtime_settings = _load_config(monkeypatch, tmp_path)

    assert config.set_chat_route("ollama", "gemma4:12b-mlx") is True
    assert config.get_chat_provider() == "ollama"
    assert config.get_chat_base_url() == "http://127.0.0.1:11434"
    assert config.get_chat_api_key() is None
    assert config.get_current_model() == "gemma4:12b-mlx"

    data = json.loads(runtime_settings.read_text())
    assert data["chat_provider"] == "ollama"
    assert data["current_model"] == "gemma4:12b-mlx"


def test_helpers_defaults_apply_to_task_routes_and_specific_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("HELPERS_PROVIDER", "openrouter")
    monkeypatch.setenv("HELPERS_MODEL", "google/gemini-3.1-flash-lite")
    monkeypatch.setenv("TEMPORAL_INTENT_MODEL", "google/gemini-3.1-pro")
    monkeypatch.setenv("ENTITY_EXTRACTION_PROVIDER", "ollama")
    monkeypatch.setenv("ENTITY_EXTRACTION_MODEL", "gemma4:12b-mlx")

    config, _runtime_settings = _load_config(monkeypatch, tmp_path, clear_helper_settings=False)

    assert config.CONCEPT_EXPLORATION_PROVIDER == "openrouter"
    assert config.CONCEPT_EXPLORATION_MODEL == "google/gemini-3.1-flash-lite"
    assert config.CONCEPT_CONNECTION_PROVIDER == "openrouter"
    assert config.CONCEPT_CONNECTION_MODEL == "google/gemini-3.1-flash-lite"
    assert config.CAPTURE_ANALYSIS_PROVIDER == "openrouter"
    assert config.CAPTURE_ANALYSIS_MODEL == "google/gemini-3.1-flash-lite"
    assert config.TODO_EXTRACTION_PROVIDER == "openrouter"
    assert config.TODO_EXTRACTION_MODEL == "google/gemini-3.1-flash-lite"
    assert config.TEMPORAL_INTENT_PROVIDER == "openrouter"
    assert config.TEMPORAL_INTENT_MODEL == "google/gemini-3.1-pro"
    assert config.ENTITY_EXTRACTION_PROVIDER == "ollama"
    assert config.ENTITY_EXTRACTION_MODEL == "gemma4:12b-mlx"


def test_reasoning_settings(monkeypatch, tmp_path):
    config, _runtime_settings = _load_config(monkeypatch, tmp_path)

    assert config.model_supports_reasoning("x-ai/grok-4.5") is True
    assert config.model_supports_reasoning("openai/gpt-chat-latest") is False

    assert config.get_reasoning_effort() == "minimal"
    assert config.get_reasoning_extra_body("x-ai/grok-4.5") == {
        "reasoning": {"effort": "minimal"}
    }

    assert config.set_reasoning_effort("low") is True
    assert config.get_reasoning_extra_body("openai/gpt-5.6-terra") == {
        "reasoning": {"effort": "low"}
    }

    assert config.set_reasoning_effort("off") is True
    assert config.get_reasoning_extra_body("openai/gpt-5.6-terra") is None


def test_curated_model_config_is_self_consistent():
    model_config = Path(__file__).resolve().parents[1] / "config" / "models.json"
    data = json.loads(model_config.read_text(encoding="utf-8"))
    models = data["models"]
    model_ids = [model["id"] for model in models]
    labels = [model["label"] for model in models]

    assert data["default_model"] in model_ids
    assert len(model_ids) == len(set(model_ids))
    assert len(labels) == len(set(labels))
    assert all(isinstance(model["reasoning"], bool) for model in models)


def test_runtime_paths_resolve_from_project_root(monkeypatch, tmp_path):
    monkeypatch.delenv("DATABASE_PATH", raising=False)
    monkeypatch.delenv("MARKDOWN_EXPORT_PATH", raising=False)

    import mentat.core.config as config

    config = importlib.reload(config)
    project_root = Path(config.__file__).resolve().parents[2]

    assert Path(config.DATABASE_PATH) == project_root / "data" / "mentat.db"
    assert Path(config.MARKDOWN_EXPORT_PATH) == project_root / "data" / "markdown"

    db_override = tmp_path / "custom.db"
    markdown_override = tmp_path / "markdown"
    monkeypatch.setenv("DATABASE_PATH", str(db_override))
    monkeypatch.setenv("MARKDOWN_EXPORT_PATH", str(markdown_override))

    config = importlib.reload(config)

    assert Path(config.DATABASE_PATH) == db_override
    assert Path(config.MARKDOWN_EXPORT_PATH) == markdown_override
