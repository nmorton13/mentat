import json

from mentat.cli import config_command


def _answers(*values):
    iterator = iter(values)
    return lambda _prompt: next(iterator)


def test_env_document_updates_effective_values_and_preserves_other_content(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "# Personal note\n"
        "UNKNOWN_SETTING=keep-me\n"
        "MENTAT_USER_ID=old\n"
        "MENTAT_USER_ID=effective-old  # keep this comment\n",
        encoding="utf-8",
    )

    document = config_command.EnvDocument(env_path)
    assert document.update({"MENTAT_USER_ID": "nate", "HELPERS_PROVIDER": "chat"}) is True

    text = env_path.read_text(encoding="utf-8")
    assert "# Personal note" in text
    assert "UNKNOWN_SETTING=keep-me" in text
    assert "MENTAT_USER_ID=old" in text
    assert "MENTAT_USER_ID=nate  # keep this comment" in text
    assert "HELPERS_PROVIDER=chat" in text
    assert config_command.EnvDocument(env_path).values()["MENTAT_USER_ID"] == "nate"


def test_init_creates_minimal_ollama_config_and_activates_route(tmp_path):
    env_path = tmp_path / ".env"
    output = []
    activated = []

    result = config_command.run_init(
        env_path,
        input_fn=_answers(
            "nate",       # user
            "1",          # Ollama
            "",           # base URL
            "qwen3:8b",   # model
            "",           # helpers follow chat
            "",           # markdown enabled
            "notes",      # markdown path
            "",           # no voice
            "",           # write changes
        ),
        secret_fn=lambda _prompt: "",
        output=output.append,
        activate_route=lambda provider, model: activated.append((provider, model)) or True,
    )

    assert result == config_command.SetupResult("ollama", "qwen3:8b", True)
    assert activated == [("ollama", "qwen3:8b")]
    values = config_command.EnvDocument(env_path).values()
    assert values == {
        "MENTAT_USER_ID": "nate",
        "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
        "OLLAMA_MODEL": "qwen3:8b",
        "OLLAMA_THINK": "false",
        "HELPERS_PROVIDER": "chat",
        "HELPERS_MODEL": "",
        "MARKDOWN_EXPORT_ENABLED": "true",
        "MARKDOWN_EXPORT_PATH": "notes",
    }
    assert any("Mentat is ready" in line for line in output)


def test_init_decline_writes_nothing(tmp_path):
    env_path = tmp_path / ".env"

    result = config_command.run_init(
        env_path,
        input_fn=_answers("", "1", "", "", "", "", "", "", "n"),
        secret_fn=lambda _prompt: "",
        output=lambda _message: None,
    )

    assert result is None
    assert not env_path.exists()


def test_show_never_prints_secret_values(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENROUTER_API_KEY=super-secret-value\n"
        "OPENAI_API_KEY=another-secret-value\n"
        "XAI_API_KEY=xai-secret-value\n",
        encoding="utf-8",
    )
    output = []

    assert config_command.run_show(env_path, output=output.append) == 0

    rendered = "\n".join(output)
    assert "super-secret-value" not in rendered
    assert "another-secret-value" not in rendered
    assert "xai-secret-value" not in rendered
    assert rendered.count("set") == 3


def test_doctor_reports_missing_openrouter_key_as_blocking(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text("MENTAT_USER_ID=nate\nMARKDOWN_EXPORT_ENABLED=false\n", encoding="utf-8")
    output = []

    assert config_command.run_doctor(env_path, output=output.append) == 1
    assert any("OPENROUTER_API_KEY is not set" in line for line in output)
    assert output[-1] == "\nDoctor found 1 blocking issue."


def test_doctor_checks_ollama_endpoint_and_model(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text(
        json.dumps({"chat_provider": "ollama", "current_model": "qwen3:8b"}),
        encoding="utf-8",
    )
    env_path.write_text(
        "RUNTIME_SETTINGS_PATH=runtime.json\n"
        "OLLAMA_BASE_URL=http://127.0.0.1:11434\n"
        "OLLAMA_MODEL=qwen3:8b\n"
        "HELPERS_PROVIDER=chat\n"
        "MARKDOWN_EXPORT_ENABLED=false\n",
        encoding="utf-8",
    )

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "qwen3:8b"}]}

    monkeypatch.setattr(config_command.requests, "get", lambda *args, **kwargs: Response())
    output = []

    assert config_command.run_doctor(env_path, output=output.append) == 0
    assert any("model 'qwen3:8b' is available" in line for line in output)
    assert output[-1] == "\nDoctor found 0 blocking issues."


def test_doctor_checks_separate_ollama_helper_route(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENROUTER_API_KEY=test-key\n"
        "OPENROUTER_MODEL=openrouter-model\n"
        "HELPERS_PROVIDER=ollama\n"
        "HELPERS_MODEL=helper-model\n"
        "OLLAMA_BASE_URL=http://127.0.0.1:11434\n"
        "MARKDOWN_EXPORT_ENABLED=false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        config_command.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(config_command.requests.ConnectionError("offline")),
    )
    output = []

    assert config_command.run_doctor(env_path, output=output.append) == 1
    assert any("helper cannot reach" in line for line in output)


def test_doctor_does_not_expose_endpoint_secrets(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "CHAT_PROVIDER=local\n"
        "CHAT_MODEL=test-model\n"
        "CHAT_BASE_URL=http://user:password@private-host/v1?token=secret\n"
        "HELPERS_PROVIDER=chat\n"
        "MARKDOWN_EXPORT_ENABLED=false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(
        config_command.requests,
        "get",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            config_command.requests.ConnectionError(
                "failed for http://user:password@private-host/v1?token=secret"
            )
        ),
    )
    output = []

    assert config_command.run_doctor(env_path, output=output.append) == 1
    rendered = "\n".join(output)
    assert "cannot reach configured custom endpoint" in rendered
    for sensitive in (
        "user:password",
        "password",
        "private-host",
        "/v1?token=secret",
        "token=secret",
    ):
        assert sensitive not in rendered


def test_doctor_rejects_empty_ollama_model_list(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    runtime_path = tmp_path / "runtime.json"
    runtime_path.write_text(
        json.dumps({"chat_provider": "ollama", "current_model": "missing-model"}),
        encoding="utf-8",
    )
    env_path.write_text(
        "RUNTIME_SETTINGS_PATH=runtime.json\n"
        "OLLAMA_BASE_URL=http://127.0.0.1:11434\n"
        "OLLAMA_MODEL=missing-model\n"
        "MARKDOWN_EXPORT_ENABLED=false\n",
        encoding="utf-8",
    )

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": []}

    monkeypatch.setattr(config_command.requests, "get", lambda *args, **kwargs: Response())
    output = []

    assert config_command.run_doctor(env_path, output=output.append) == 1
    assert any("no models were listed" in line for line in output)


def test_show_handles_malformed_endpoint_without_exposing_it(tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "CHAT_BASE_URL=http://user:secret@localhost:bad/v1?token=hidden\n"
        "CHAT_MODEL=local-model\n",
        encoding="utf-8",
    )
    output = []

    assert config_command.run_show(env_path, output=output.append) == 0
    rendered = "\n".join(output)
    assert "invalid URL" in rendered
    assert "secret" not in rendered
    assert "hidden" not in rendered


def test_doctor_reports_missing_optional_voice_dependencies(monkeypatch, tmp_path):
    env_path = tmp_path / ".env"
    env_path.write_text(
        "OPENROUTER_API_KEY=test-key\n"
        "VOICE_PROVIDER=xai\n"
        "XAI_API_KEY=voice-key\n"
        "MARKDOWN_EXPORT_ENABLED=false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config_command.importlib.util, "find_spec", lambda _package: None)
    output = []

    assert config_command.run_doctor(env_path, output=output.append) == 1
    assert any("uv sync --extra voice" in line for line in output)


def test_config_command_rejects_unknown_actions(capsys):
    assert config_command.run_config_command(["mystery"]) == 2
    assert "Usage: mentat config [init|show|doctor]" in capsys.readouterr().out
