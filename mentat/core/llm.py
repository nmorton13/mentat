"""Small chat-completion wrapper helpers for Mentat LLM calls."""

import json
import re
import types
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
from openai import BadRequestError, OpenAI

from mentat.core import config


@dataclass(frozen=True)
class CompletionResult:
    text: str
    response: Any
    model: str


@dataclass(frozen=True)
class LLMRoute:
    """Resolved provider/client/model route for a feature-specific LLM task."""
    provider: str
    client: Any
    model: str
    base_url: Optional[str] = None
    model_source: str = "default"


def message_text(message: Any) -> str:
    """Extract response text from provider-specific OpenAI-compatible messages."""
    content = getattr(message, "content", None)
    if content:
        return content

    reasoning = getattr(message, "reasoning", None)
    if isinstance(reasoning, str):
        return reasoning

    return ""


def _completion_result(client: Any, model: str, messages: List[Dict[str, str]], **kwargs: Any) -> CompletionResult:
    response = client.chat.completions.create(model=model, messages=messages, **kwargs)
    text = message_text(response.choices[0].message)
    return CompletionResult(text=text, response=response, model=model)


def _optional_float(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _optional_int(value: Any) -> Optional[int]:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class OllamaChatCompletions:
    """Small OpenAI-shaped adapter for Ollama's native /api/chat endpoint."""

    def __init__(self, base_url: str):
        normalized = (base_url or config.OLLAMA_BASE_URL).rstrip("/")
        if normalized.endswith("/api"):
            normalized = normalized[:-len("/api")]
        self.base_url = normalized

    def create(self, model: str, messages: List[Dict[str, str]], **kwargs: Any) -> Any:
        request_kwargs = dict(kwargs)
        response_format = request_kwargs.pop("response_format", None)
        max_tokens = request_kwargs.pop("max_tokens", None)
        temperature = request_kwargs.pop("temperature", None)
        top_p = request_kwargs.pop("top_p", None)
        top_k = request_kwargs.pop("top_k", None)

        payload: Dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "think": config.OLLAMA_THINK,
        }
        if response_format == {"type": "json_object"}:
            payload["format"] = "json"

        options: Dict[str, Any] = {}
        option_values = {
            "temperature": _optional_float(temperature if temperature is not None else config.OLLAMA_TEMPERATURE),
            "top_p": _optional_float(top_p if top_p is not None else config.OLLAMA_TOP_P),
            "top_k": _optional_int(top_k if top_k is not None else config.OLLAMA_TOP_K),
            "num_predict": _optional_int(max_tokens if max_tokens is not None else config.OLLAMA_NUM_PREDICT),
        }
        for key, value in option_values.items():
            if value is not None:
                options[key] = value
        if options:
            payload["options"] = options

        url = f"{self.base_url}/api/chat"
        response = requests.post(url, json=payload, timeout=config.LLM_REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        content = data.get("message", {}).get("content", "")
        return types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content=content))],
            raw=data,
        )


class OllamaChatClient:
    """Client exposing client.chat.completions.create for existing LLM helpers."""

    def __init__(self, base_url: Optional[str] = None):
        completions = OllamaChatCompletions(base_url or config.OLLAMA_BASE_URL)
        self.chat = types.SimpleNamespace(completions=completions)


def complete(client: Any, model: str, messages: List[Dict[str, str]], **kwargs: Any) -> str:
    """Return plain text from an OpenAI-compatible chat completion."""
    return _completion_result(client, model, messages, **kwargs).text


def _parse_json_text(text: str) -> Any:
    stripped = (text or "").strip()
    original_error: Optional[json.JSONDecodeError] = None
    try:
        return json.loads(stripped)
    except json.JSONDecodeError as exc:
        original_error = exc

    for match in re.finditer(r"```(?:json)?\s*(.*?)```", stripped, re.IGNORECASE | re.DOTALL):
        candidate = match.group(1).strip()
        try:
            return json.loads(candidate)
        except json.JSONDecodeError:
            continue

    decoder = json.JSONDecoder()
    for index, char in enumerate(stripped):
        if char not in "[{":
            continue
        try:
            value, _end = decoder.raw_decode(stripped[index:])
            return value
        except json.JSONDecodeError:
            continue
    if original_error is not None:
        raise original_error
    raise json.JSONDecodeError("No JSON found", stripped, 0)


def _is_response_format_rejection(exc: BadRequestError) -> bool:
    details = f"{exc} {getattr(exc, 'body', '')}".lower()
    return "response_format" in details or "json_object" in details


def complete_json(
    client: Any,
    model: str,
    messages: List[Dict[str, str]],
    use_response_format: bool = True,
    **kwargs: Any
) -> Any:
    """Return parsed JSON from a chat completion, with text fallback support."""
    request_kwargs = dict(kwargs)
    if use_response_format:
        request_kwargs.setdefault("response_format", {"type": "json_object"})

    try:
        result = _completion_result(client, model, messages, **request_kwargs)
    except TypeError:
        if not use_response_format or "response_format" not in request_kwargs:
            raise
        request_kwargs.pop("response_format", None)
        result = _completion_result(client, model, messages, **request_kwargs)
    except BadRequestError as exc:
        if (
            not use_response_format
            or "response_format" not in request_kwargs
            or not _is_response_format_rejection(exc)
        ):
            raise
        request_kwargs.pop("response_format", None)
        result = _completion_result(client, model, messages, **request_kwargs)

    return _parse_json_text(result.text)


_ROUTE_CLIENTS: Dict[Tuple[str, str, str], Any] = {}


def _openrouter_headers() -> Optional[Dict[str, str]]:
    """Build optional OpenRouter attribution headers."""
    import os

    app_url = os.getenv("OPENROUTER_APP_URL_CLI") or os.getenv("OPENROUTER_APP_URL") or "https://mentat.local/cli"
    app_title = os.getenv("OPENROUTER_APP_TITLE_CLI") or os.getenv("OPENROUTER_APP_TITLE") or "Mentat CLI"
    headers = {}
    if app_url:
        headers["HTTP-Referer"] = app_url
    if app_title:
        headers["X-Title"] = app_title
    return headers or None


def _cached_openai_client(provider: str, base_url: str, api_key: str, headers: Optional[Dict[str, str]] = None) -> Any:
    """Return a cached OpenAI-compatible client for a provider/base URL/API key tuple."""
    key = (provider, base_url, api_key)
    if key not in _ROUTE_CLIENTS:
        kwargs: Dict[str, Any] = {
            "api_key": api_key,
            "base_url": base_url,
            "timeout": config.LLM_REQUEST_TIMEOUT,
        }
        if headers:
            kwargs["default_headers"] = headers
        _ROUTE_CLIENTS[key] = OpenAI(**kwargs)
    return _ROUTE_CLIENTS[key]


def _cached_ollama_client(base_url: str) -> Any:
    """Return a cached native Ollama client for a base URL."""
    key = ("ollama", base_url, "")
    if key not in _ROUTE_CLIENTS:
        _ROUTE_CLIENTS[key] = OllamaChatClient(base_url)
    return _ROUTE_CLIENTS[key]


def get_task_llm_route(
    task_prefix: str,
    chat_client: Any = None,
    requested_model: Optional[str] = None,
) -> LLMRoute:
    """Resolve provider/client/model for a feature-specific LLM task.

    Env/config convention:
    - <TASK>_PROVIDER: chat (default), openrouter, local, ollama, or custom
    - <TASK>_MODEL: optional task-specific model override
    - <TASK>_BASE_URL and <TASK>_API_KEY: used for custom provider

    Provider routing chooses where the request is sent; the model string only
    chooses the model at that provider.
    """
    prefix = task_prefix.upper()
    provider = (getattr(config, f"{prefix}_PROVIDER", None) or "chat").strip().lower()
    task_model = getattr(config, f"{prefix}_MODEL", None)

    if provider == "chat":
        model = task_model or requested_model or config.get_current_model()
        source = "task override" if task_model else ("requested" if requested_model else "active chat model")
        return LLMRoute(provider="chat", client=chat_client, model=model, base_url=config.get_chat_base_url(), model_source=source)

    if provider == "openrouter":
        if not config.OPENROUTER_API_KEY:
            return LLMRoute(provider="openrouter", client=None, model=task_model or config.OPENROUTER_MODEL, base_url=config.OPENROUTER_BASE_URL, model_source="missing api key")
        model = task_model or config.OPENROUTER_MODEL
        source = "task override" if task_model else "openrouter default"
        client = _cached_openai_client("openrouter", config.OPENROUTER_BASE_URL, config.OPENROUTER_API_KEY, _openrouter_headers())
        return LLMRoute(provider="openrouter", client=client, model=model, base_url=config.OPENROUTER_BASE_URL, model_source=source)

    if provider == "local":
        base_url = config.LOCAL_BASE_URL or config.CHAT_BASE_URL
        model = task_model or config.LOCAL_MODEL or requested_model or config.CHAT_MODEL or config.get_current_model()
        source = "task override" if task_model else ("local default" if config.LOCAL_MODEL else "fallback")
        if not base_url:
            return LLMRoute(provider="local", client=None, model=model, base_url=None, model_source="missing local base url")
        client = _cached_openai_client("local", base_url, config.LOCAL_API_KEY)
        return LLMRoute(provider="local", client=client, model=model, base_url=base_url, model_source=source)

    if provider == "ollama":
        base_url = config.OLLAMA_BASE_URL
        model = task_model or config.OLLAMA_MODEL or requested_model or config.get_current_model()
        source = "task override" if task_model else ("ollama default" if config.OLLAMA_MODEL else "fallback")
        client = _cached_ollama_client(base_url)
        return LLMRoute(provider="ollama", client=client, model=model, base_url=base_url, model_source=source)

    if provider == "custom":
        import os

        base_url = os.getenv(f"{prefix}_BASE_URL", "").strip() or None
        api_key = os.getenv(f"{prefix}_API_KEY", "").strip() or None
        model = task_model or requested_model or config.get_current_model()
        if not base_url or not api_key:
            return LLMRoute(provider="custom", client=None, model=model, base_url=base_url, model_source="missing custom config")
        client = _cached_openai_client(f"custom:{prefix}", base_url, api_key)
        source = "task override" if task_model else "fallback"
        return LLMRoute(provider="custom", client=client, model=model, base_url=base_url, model_source=source)

    # Unknown provider: degrade safely to chat behavior.
    model = task_model or requested_model or config.get_current_model()
    return LLMRoute(provider=f"{provider} (unknown; using chat)", client=chat_client, model=model, base_url=config.get_chat_base_url(), model_source="fallback")


def get_chat_route(chat_client: Any = None, current_model: Optional[str] = None) -> LLMRoute:
    """Describe the normal chat route without changing any runtime settings."""
    provider = config.get_chat_provider()
    base_url = config.get_chat_base_url()
    return LLMRoute(
        provider=provider,
        client=chat_client,
        model=current_model or config.get_current_model(),
        base_url=base_url,
        model_source="runtime route" if getattr(config, "_runtime_chat_provider")() else "env/default",
    )


def _select_online_model(current_model: Optional[str] = None) -> Tuple[str, str]:
    """Select the OpenRouter model for explicit online/web-backed calls."""
    if config.ONLINE_MODEL:
        return _without_online_suffix(config.ONLINE_MODEL), "online override"
    if config.get_chat_base_url() == config.OPENROUTER_BASE_URL:
        return _without_online_suffix(current_model or config.get_current_model()), "active chat model"
    return _without_online_suffix(config.OPENROUTER_MODEL), "openrouter default"


def get_online_route(current_model: Optional[str] = None) -> LLMRoute:
    """Describe explicit online/web-backed route selection.

    Online/web calls use OpenRouter's `openrouter:web_search` server tool, so
    they require an OpenRouter API key and never route through a local chat
    endpoint.
    """
    model, source = _select_online_model(current_model)
    client_available = bool(config.OPENROUTER_API_KEY)
    return LLMRoute(
        provider="openrouter",
        client=True if client_available else None,
        model=model,
        base_url=config.OPENROUTER_BASE_URL,
        model_source=source if client_available else "missing api key",
    )


def get_llm_route_display_rows(chat_client: Any = None, current_model: Optional[str] = None) -> List[Dict[str, str]]:
    """Return display-ready rows for the primary LLM routes Mentat uses."""
    routes = [
        ("Chat", get_chat_route(chat_client, current_model)),
        ("ConceptExplorer", get_task_llm_route("CONCEPT_EXPLORATION", chat_client)),
        ("Entity Extraction", get_task_llm_route("ENTITY_EXTRACTION", chat_client)),
        ("Concept Connection", get_task_llm_route("CONCEPT_CONNECTION", chat_client)),
        ("Capture Analysis", get_task_llm_route("CAPTURE_ANALYSIS", chat_client)),
        ("Todo Extraction", get_task_llm_route("TODO_EXTRACTION", chat_client)),
        ("Temporal Intent", get_task_llm_route("TEMPORAL_INTENT", chat_client)),
        ("Online/Web", get_online_route(current_model)),
    ]
    rows = []
    for name, route in routes:
        status = "available" if route.client is not None or name in {"Chat", "Online/Web"} else "unavailable"
        if route.client is None and route.model_source.startswith("missing"):
            status = route.model_source
        rows.append({
            "feature": name,
            "provider": route.provider,
            "model": route.model,
            "source": route.model_source,
            "base_url": route.base_url or "",
            "status": status,
        })
    return rows


def get_llm_route_summary(chat_client: Any = None, current_model: Optional[str] = None) -> str:
    """Return a compact one-line route summary for startup display."""
    rows = get_llm_route_display_rows(chat_client=chat_client, current_model=current_model)
    rows_by_feature = {row["feature"]: row for row in rows}
    chat = rows_by_feature["Chat"]
    summary_parts = [f"Chat {chat['provider']} → {chat['model']}"]

    feature_labels = [
        ("ConceptExplorer", "concept"),
        ("Entity Extraction", "entity"),
        ("Concept Connection", "connect"),
        ("Online/Web", "online"),
    ]
    feature_parts = []
    for feature, label in feature_labels:
        row = rows_by_feature.get(feature)
        if not row:
            continue
        if row["provider"] == "chat":
            provider = f"chat/{chat['provider']}"
        else:
            provider = row["provider"]
        if row["status"] != "available":
            provider = f"{provider} ({row['status']})"
        feature_parts.append(f"{label}={provider}")

    if feature_parts:
        summary_parts.append("Features " + ", ".join(feature_parts))
    return "; ".join(summary_parts)


_ONLINE_CLIENT: Optional[Any] = None


def _get_online_client(default_client: Any = None) -> Any:
    """Use OpenRouter for web-backed calls that require OpenRouter server tools."""
    global _ONLINE_CLIENT
    if not config.OPENROUTER_API_KEY:
        raise RuntimeError("OPENROUTER_API_KEY is required for online/web-backed calls")
    if _ONLINE_CLIENT is None:
        _ONLINE_CLIENT = OpenAI(
            api_key=config.OPENROUTER_API_KEY,
            base_url=config.OPENROUTER_BASE_URL,
            timeout=config.LLM_REQUEST_TIMEOUT,
        )
    return _ONLINE_CLIENT


def _without_online_suffix(model: str) -> str:
    """Normalize legacy OpenRouter :online model slugs to base model IDs."""
    return model[:-len(":online")] if model.endswith(":online") else model


def _with_web_search_tool(tools: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """Ensure OpenRouter's web search server tool is exposed to the model."""
    if tools is None:
        return [{"type": "openrouter:web_search"}]
    if any(tool.get("type") == "openrouter:web_search" for tool in tools):
        return tools
    return [*tools, {"type": "openrouter:web_search"}]


def complete_online(client: Any, model: str, messages: List[Dict[str, str]], **kwargs: Any) -> CompletionResult:
    """Call OpenRouter's web search server tool and preserve the raw response."""
    selected_model, _source = _select_online_model(model)
    request_kwargs = dict(kwargs)
    request_kwargs["tools"] = _with_web_search_tool(request_kwargs.get("tools"))
    return _completion_result(_get_online_client(), selected_model, messages, **request_kwargs)
