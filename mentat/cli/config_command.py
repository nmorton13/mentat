"""Guided configuration and diagnostics for the Mentat CLI."""

from __future__ import annotations

import getpass
import importlib.util
import json
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping
from urllib.parse import urlparse, urlunparse

import requests
from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ENV_PATH = PROJECT_ROOT / ".env"
SECRET_KEYS = {"OPENROUTER_API_KEY", "OPENAI_API_KEY", "XAI_API_KEY", "CHAT_API_KEY"}
VALID_RUNTIME_PROVIDERS = {"openrouter", "local", "custom", "ollama"}


@dataclass(frozen=True)
class SetupResult:
    provider: str
    model: str
    changed: bool


class EnvDocument:
    """Update dotenv assignments while preserving comments and unknown lines."""

    def __init__(self, path: Path):
        self.path = path
        self.text = path.read_text(encoding="utf-8") if path.exists() else ""

    def values(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        return {
            key: value or ""
            for key, value in dotenv_values(self.path).items()
            if key is not None
        }

    def preview(self, updates: Mapping[str, str]) -> list[tuple[str, str, str]]:
        current = self.values()
        return [
            (key, current.get(key, ""), value)
            for key, value in updates.items()
            if current.get(key, "") != value
        ]

    def update(self, updates: Mapping[str, str]) -> bool:
        changes = self.preview(updates)
        if not changes:
            return False

        lines = self.text.splitlines()
        remaining = dict(updates)
        output: list[str] = []

        last_assignment: dict[str, int] = {}
        for index, line in enumerate(lines):
            match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=", line)
            if match and match.group(1) in updates:
                last_assignment[match.group(1)] = index

        for index, line in enumerate(lines):
            match = re.match(r"^(\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*).*$", line)
            if match and match.group(2) in remaining and last_assignment.get(match.group(2)) == index:
                key = match.group(2)
                value_text = line[len(match.group(1)):]
                comment_match = re.search(r"\s+#", value_text)
                comment = value_text[comment_match.start():] if comment_match else ""
                output.append(f"{match.group(1)}{_format_env_value(remaining.pop(key))}{comment}")
            else:
                output.append(line)

        if remaining:
            if output and output[-1].strip():
                output.append("")
            output.append("# Added by `mentat config init`")
            output.extend(f"{key}={_format_env_value(value)}" for key, value in remaining.items())

        new_text = "\n".join(output).rstrip() + "\n"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            "w", encoding="utf-8", dir=self.path.parent, delete=False
        ) as temp_file:
            temp_file.write(new_text)
            temp_path = Path(temp_file.name)
        os.replace(temp_path, self.path)
        self.text = new_text
        return True


def _format_env_value(value: str) -> str:
    if not value:
        return ""
    if re.fullmatch(r"[A-Za-z0-9_./:@+\-]+", value):
        return value
    return json.dumps(value)


def _masked(key: str, value: str) -> str:
    if not value:
        return "not set"
    if key not in SECRET_KEYS:
        return value
    return "set"


def _ask(
    prompt: str,
    default: str,
    input_fn: Callable[[str], str],
) -> str:
    suffix = f" [{default}]" if default else ""
    value = input_fn(f"{prompt}{suffix}: ").strip()
    return value or default


def _confirm(prompt: str, default: bool, input_fn: Callable[[str], str]) -> bool:
    suffix = "Y/n" if default else "y/N"
    value = input_fn(f"{prompt} [{suffix}]: ").strip().lower()
    if not value:
        return default
    return value in {"y", "yes"}


def _choose(
    prompt: str,
    options: list[tuple[str, str]],
    default: str,
    input_fn: Callable[[str], str],
    output: Callable[[str], None],
) -> str:
    output(prompt)
    for index, (value, label) in enumerate(options, start=1):
        marker = " (default)" if value == default else ""
        output(f"  {index}. {label}{marker}")
    while True:
        raw = input_fn("Choice: ").strip().lower()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        for value, _label in options:
            if raw == value:
                return value
        output("Enter a listed number or provider name.")


def _secret(
    prompt: str,
    current: str,
    secret_fn: Callable[[str], str],
) -> str:
    suffix = " [press Enter to keep current]" if current else ""
    value = secret_fn(f"{prompt}{suffix}: ").strip()
    return value or current


def _is_local_url(url: str) -> bool:
    hostname = (urlparse(url).hostname or "").lower()
    return hostname in {"localhost", "127.0.0.1", "::1"}


def _url_error(url: str) -> str | None:
    try:
        parsed = urlparse(url)
        _port = parsed.port
    except ValueError as exc:
        return str(exc)
    if parsed.scheme not in {"http", "https"}:
        return "URL must use http or https"
    if not parsed.hostname:
        return "URL must include a hostname"
    return None


def _display_url(url: str) -> str:
    """Remove embedded credentials, query parameters, and fragments from a URL."""
    error = _url_error(url)
    if error:
        return f"invalid URL ({error})"
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    netloc = hostname
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))


def _ask_url(
    prompt: str,
    default: str,
    input_fn: Callable[[str], str],
    output: Callable[[str], None],
) -> str:
    while True:
        value = _ask(prompt, default, input_fn).rstrip("/")
        error = _url_error(value)
        if not error:
            return value
        output(f"Invalid URL: {error}")


def _runtime_settings_path(values: Mapping[str, str], env_path: Path) -> Path:
    path = Path(values.get("RUNTIME_SETTINGS_PATH") or "data/runtime_settings.json")
    return path if path.is_absolute() else env_path.parent / path


def _runtime_route(values: Mapping[str, str], env_path: Path) -> tuple[str | None, str | None]:
    path = _runtime_settings_path(values, env_path)
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None, None
    provider = data.get("chat_provider")
    model = data.get("current_model")
    if provider not in VALID_RUNTIME_PROVIDERS:
        provider = None
    if not isinstance(model, str) or not model.strip():
        model = None
    return provider, model


def _effective_route(values: Mapping[str, str], env_path: Path) -> tuple[str, str, str]:
    runtime_provider, runtime_model = _runtime_route(values, env_path)
    provider = runtime_provider
    if not provider:
        chat_url = values.get("CHAT_BASE_URL", "").strip()
        provider = "local" if chat_url and _is_local_url(chat_url) else "custom" if chat_url else "openrouter"

    if provider == "ollama":
        return (
            provider,
            runtime_model or values.get("OLLAMA_MODEL") or "gemma4:12b-mlx",
            values.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434",
        )
    if provider in {"local", "custom"}:
        return (
            provider,
            runtime_model or values.get("CHAT_MODEL") or values.get("LOCAL_MODEL") or "not set",
            values.get("CHAT_BASE_URL") or values.get("LOCAL_BASE_URL") or "http://localhost:1234/v1",
        )
    return (
        "openrouter",
        runtime_model or values.get("OPENROUTER_MODEL") or "x-ai/grok-4.5",
        "https://openrouter.ai/api/v1",
    )


def run_init(
    env_path: Path = DEFAULT_ENV_PATH,
    *,
    input_fn: Callable[[str], str] = input,
    secret_fn: Callable[[str], str] = getpass.getpass,
    output: Callable[[str], None] = print,
    activate_route: Callable[[str, str], bool] | None = None,
) -> SetupResult | None:
    document = EnvDocument(env_path)
    values = document.values()
    current_provider, current_model, _endpoint = _effective_route(values, env_path)

    output("Let's set up the minimum needed for capture, search, and reflection.")
    output("Advanced model routes can be tuned later.\n")

    user_id = _ask("Mentat user ID", values.get("MENTAT_USER_ID") or "mentat", input_fn)
    default_provider = "custom" if current_provider in {"local", "custom"} else current_provider
    if default_provider not in {"ollama", "openrouter", "custom"}:
        default_provider = "ollama"
    provider = _choose(
        "How should Mentat run its language model?",
        [
            ("ollama", "Ollama (local)"),
            ("openrouter", "OpenRouter (hosted)"),
            ("custom", "Custom OpenAI-compatible endpoint"),
        ],
        default_provider,
        input_fn,
        output,
    )

    updates: dict[str, str] = {"MENTAT_USER_ID": user_id}
    route_provider = provider

    if provider == "ollama":
        base_url = _ask_url(
            "Ollama base URL",
            values.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434",
            input_fn,
            output,
        )
        model = _ask(
            "Ollama model",
            values.get("OLLAMA_MODEL") or (current_model if current_provider == "ollama" else "llama3.2"),
            input_fn,
        )
        updates.update({"OLLAMA_BASE_URL": base_url, "OLLAMA_MODEL": model, "OLLAMA_THINK": values.get("OLLAMA_THINK") or "false"})
    elif provider == "openrouter":
        api_key = _secret("OpenRouter API key", values.get("OPENROUTER_API_KEY", ""), secret_fn)
        model = _ask(
            "OpenRouter model",
            values.get("OPENROUTER_MODEL") or (current_model if current_provider == "openrouter" else "x-ai/grok-4.5"),
            input_fn,
        )
        updates.update({"OPENROUTER_API_KEY": api_key, "OPENROUTER_MODEL": model})
    else:
        base_url = _ask_url(
            "OpenAI-compatible base URL",
            values.get("CHAT_BASE_URL") or "http://localhost:1234/v1",
            input_fn,
            output,
        )
        api_key = _secret("API key (optional for local servers)", values.get("CHAT_API_KEY", ""), secret_fn)
        model = _ask("Model name", values.get("CHAT_MODEL") or "local-model", input_fn)
        route_provider = "local" if _is_local_url(base_url) else "custom"
        updates.update({"CHAT_BASE_URL": base_url, "CHAT_API_KEY": api_key or "local", "CHAT_MODEL": model})

    helpers_follow_chat = values.get("HELPERS_PROVIDER", "") in {"", "chat"}
    if _confirm("Should helper tasks follow the same chat model?", helpers_follow_chat, input_fn):
        updates.update({"HELPERS_PROVIDER": "chat", "HELPERS_MODEL": ""})
    else:
        helper_provider = _choose(
            "Choose the helper provider:",
            [("ollama", "Ollama"), ("openrouter", "OpenRouter")],
            values.get("HELPERS_PROVIDER") if values.get("HELPERS_PROVIDER") in {"ollama", "openrouter"} else provider if provider in {"ollama", "openrouter"} else "ollama",
            input_fn,
            output,
        )
        helper_default = (
            values.get("HELPERS_MODEL")
            or (updates.get("OLLAMA_MODEL") if helper_provider == "ollama" else updates.get("OPENROUTER_MODEL"))
            or (values.get("OLLAMA_MODEL") if helper_provider == "ollama" else values.get("OPENROUTER_MODEL"))
            or model
        )
        helper_model = _ask("Helper model", helper_default, input_fn)
        updates.update({"HELPERS_PROVIDER": helper_provider, "HELPERS_MODEL": helper_model})

    markdown_enabled = _confirm(
        "Export captured memories as Markdown?",
        values.get("MARKDOWN_EXPORT_ENABLED", "true").lower() not in {"false", "0", "no"},
        input_fn,
    )
    updates["MARKDOWN_EXPORT_ENABLED"] = "true" if markdown_enabled else "false"
    if markdown_enabled:
        updates["MARKDOWN_EXPORT_PATH"] = _ask(
            "Markdown export path",
            values.get("MARKDOWN_EXPORT_PATH") or "data/markdown",
            input_fn,
        )

    voice_is_configured = values.get("VOICE_PROVIDER", "") in {"openai", "xai"}
    if _confirm("Configure voice now?", voice_is_configured, input_fn):
        voice_provider = _choose(
            "Choose the voice provider:",
            [("openai", "OpenAI"), ("xai", "xAI")],
            values.get("VOICE_PROVIDER") if values.get("VOICE_PROVIDER") in {"openai", "xai"} else "openai",
            input_fn,
            output,
        )
        key_name = "OPENAI_API_KEY" if voice_provider == "openai" else "XAI_API_KEY"
        updates["VOICE_PROVIDER"] = voice_provider
        updates[key_name] = _secret(f"{voice_provider} API key", values.get(key_name, ""), secret_fn)
        default_voice_model = "gpt-realtime-mini" if voice_provider == "openai" else values.get("VOICE_MODEL", "")
        updates["VOICE_MODEL"] = _ask("Voice model", values.get("VOICE_MODEL") or default_voice_model, input_fn)

    changes = document.preview(updates)
    if changes:
        output("\nChanges to .env:")
        for key, old, new in changes:
            output(f"  {key}: {_masked(key, old)} -> {_masked(key, new)}")
        if not _confirm("Write these changes?", True, input_fn):
            output("No changes written.")
            return None
        changed = document.update(updates)
    else:
        output("\nYour .env already matches these answers.")
        changed = False

    if activate_route and not activate_route(route_provider, model):
        raise RuntimeError("Could not activate the selected model route")

    output("\nMentat is ready.")
    output(f"  User:    {user_id}")
    output(f"  Chat:    {route_provider} / {model}")
    helpers = "chat model" if updates.get("HELPERS_PROVIDER") == "chat" else f"{updates.get('HELPERS_PROVIDER')} / {updates.get('HELPERS_MODEL')}"
    output(f"  Helpers: {helpers}")
    output(f"  Export:  {updates.get('MARKDOWN_EXPORT_PATH', 'disabled') if markdown_enabled else 'disabled'}")
    output("\nTry: mentat capture \"A thought I want to return to...\"")
    return SetupResult(route_provider, model, changed)


def run_show(env_path: Path = DEFAULT_ENV_PATH, *, output: Callable[[str], None] = print) -> int:
    values = EnvDocument(env_path).values()
    provider, model, endpoint = _effective_route(values, env_path)
    helper_provider = values.get("HELPERS_PROVIDER") or "chat"
    helper_model = values.get("HELPERS_MODEL") or ("active chat model" if helper_provider == "chat" else "provider default")

    output(f"Config file: {env_path} ({'found' if env_path.exists() else 'missing'})")
    output(f"User:        {values.get('MENTAT_USER_ID') or 'mentat'}")
    output(f"Chat:        {provider} / {model}")
    output(f"Endpoint:    {_display_url(endpoint)}")
    output(f"Helpers:     {helper_provider} / {helper_model}")
    output(f"Online:      {values.get('ONLINE_MODEL') or 'not configured'}")
    output(f"Markdown:    {values.get('MARKDOWN_EXPORT_PATH') or 'data/markdown'} ({values.get('MARKDOWN_EXPORT_ENABLED') or 'true'})")
    output(f"Voice:       {values.get('VOICE_PROVIDER') or 'not configured'}")
    output(f"OpenRouter:  {_masked('OPENROUTER_API_KEY', values.get('OPENROUTER_API_KEY', ''))}")
    output(f"OpenAI:      {_masked('OPENAI_API_KEY', values.get('OPENAI_API_KEY', ''))}")
    output(f"xAI:         {_masked('XAI_API_KEY', values.get('XAI_API_KEY', ''))}")
    return 0


def _check_endpoint(provider: str, model: str, endpoint: str, values: Mapping[str, str]) -> tuple[bool, str]:
    error = _url_error(endpoint)
    if error:
        return False, f"invalid endpoint: {error}"
    headers: dict[str, str] = {}
    if provider == "ollama":
        url = f"{endpoint.rstrip('/')}/api/tags"
    else:
        url = f"{endpoint.rstrip('/')}/models"
        api_key = values.get("CHAT_API_KEY", "")
        if api_key and api_key != "local":
            headers["Authorization"] = f"Bearer {api_key}"

    try:
        response = requests.get(url, headers=headers, timeout=3)
        response.raise_for_status()
        data = response.json()
    except (requests.RequestException, ValueError):
        # Request exceptions often echo the URL, including embedded credentials
        # and query tokens. Keep doctor output useful without exposing endpoint data.
        return False, f"cannot reach configured {provider} endpoint"

    if provider == "ollama":
        names = {
            item.get("name") or item.get("model")
            for item in data.get("models", [])
            if isinstance(item, dict)
        }
    else:
        names = {
            item.get("id")
            for item in data.get("data", [])
            if isinstance(item, dict)
        }
    if not names:
        return False, "endpoint responded, but no models were listed"
    if model not in names:
        return False, f"endpoint responded, but model '{model}' was not listed"
    return True, f"endpoint responded and model '{model}' is available"


def run_doctor(env_path: Path = DEFAULT_ENV_PATH, *, output: Callable[[str], None] = print) -> int:
    values = EnvDocument(env_path).values()
    provider, model, endpoint = _effective_route(values, env_path)
    failures = 0

    def report(status: str, message: str) -> None:
        output(f"[{status}] {message}")

    if env_path.exists():
        report("ok", f"configuration found at {env_path}")
    else:
        report("fail", "no .env file; run `mentat config init`")
        failures += 1

    user_id = values.get("MENTAT_USER_ID") or "mentat"
    report("ok", f"user ID is {user_id}")

    if provider == "openrouter":
        if values.get("OPENROUTER_API_KEY"):
            report("ok", f"OpenRouter is configured with model {model}")
        else:
            report("fail", "OpenRouter is active but OPENROUTER_API_KEY is not set")
            failures += 1
    else:
        ok, message = _check_endpoint(provider, model, endpoint, values)
        report("ok" if ok else "fail", message)
        failures += 0 if ok else 1

    helper_provider = (values.get("HELPERS_PROVIDER") or "chat").lower()
    helper_model = values.get("HELPERS_MODEL") or model
    if helper_provider == "chat":
        report("ok", f"helper tasks follow {provider} / {model}")
    elif helper_provider == "openrouter":
        if values.get("OPENROUTER_API_KEY"):
            report("ok", f"helper tasks use openrouter / {helper_model}")
        else:
            report("fail", "helpers use OpenRouter but OPENROUTER_API_KEY is not set")
            failures += 1
    elif helper_provider == "ollama":
        helper_endpoint = values.get("OLLAMA_BASE_URL") or "http://127.0.0.1:11434"
        helper_model = values.get("HELPERS_MODEL") or values.get("OLLAMA_MODEL") or ""
        if not helper_model:
            report("fail", "helpers use Ollama but no helper or Ollama model is configured")
            failures += 1
        elif provider == "ollama" and helper_endpoint == endpoint and helper_model == model:
            report("ok", f"helper tasks share ollama / {helper_model}")
        else:
            ok, message = _check_endpoint("ollama", helper_model, helper_endpoint, values)
            report("ok" if ok else "fail", f"helper {message}")
            failures += 0 if ok else 1
    elif helper_provider == "local":
        helper_endpoint = values.get("LOCAL_BASE_URL") or ""
        helper_model = values.get("HELPERS_MODEL") or values.get("LOCAL_MODEL") or ""
        if not helper_endpoint or not helper_model:
            report("fail", "helpers use local routing but LOCAL_BASE_URL or helper model is missing")
            failures += 1
        else:
            ok, message = _check_endpoint("local", helper_model, helper_endpoint, values)
            report("ok" if ok else "fail", f"helper {message}")
            failures += 0 if ok else 1
    else:
        report("fail", f"unsupported shared helper provider: {helper_provider}")
        failures += 1

    export_enabled = values.get("MARKDOWN_EXPORT_ENABLED", "true").lower() not in {"false", "0", "no"}
    if export_enabled:
        export_path = Path(values.get("MARKDOWN_EXPORT_PATH") or "data/markdown")
        if not export_path.is_absolute():
            export_path = env_path.parent / export_path
        parent = export_path if export_path.exists() else export_path.parent
        while not parent.exists() and parent != parent.parent:
            parent = parent.parent
        if parent.exists() and os.access(parent, os.W_OK):
            report("ok", f"Markdown export path is writable: {export_path}")
        else:
            report("fail", f"Markdown export path is not writable: {export_path}")
            failures += 1
    else:
        report("skip", "Markdown export is disabled")

    voice_provider = values.get("VOICE_PROVIDER", "").lower()
    if voice_provider:
        voice_key = "OPENAI_API_KEY" if voice_provider == "openai" else "XAI_API_KEY"
        if values.get(voice_key):
            report("ok", f"optional voice provider {voice_provider} is configured")
        else:
            report("warn", f"voice uses {voice_provider}, but {voice_key} is not set")
        missing_voice_packages = [
            package
            for package in ("pyaudio", "websockets")
            if importlib.util.find_spec(package) is None
        ]
        if missing_voice_packages:
            report("fail", "voice dependencies are missing; run `uv sync --extra voice`")
            failures += 1
    else:
        report("skip", "voice is not configured")

    output(f"\nDoctor found {failures} blocking issue{'s' if failures != 1 else ''}.")
    return 1 if failures else 0


def run_config_command(
    args: list[str],
    *,
    env_path: Path = DEFAULT_ENV_PATH,
    activate_route: Callable[[str, str], bool] | None = None,
) -> int:
    action = args[0].lower() if args else "init"
    if len(args) > 1 or action not in {"init", "show", "doctor"}:
        print("Usage: mentat config [init|show|doctor]")
        return 2
    if action == "init":
        return 0 if run_init(env_path, activate_route=activate_route) is not None else 1
    if action == "show":
        return run_show(env_path)
    return run_doctor(env_path)
