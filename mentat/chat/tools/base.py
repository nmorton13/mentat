"""
Base infrastructure for tool definitions.

Provides:
- ToolSpec dataclass for defining tools
- Schema adapters for OpenAI and Realtime API formats
- Shared utilities for tool handlers
"""

import json
import logging
import os
import re
import shlex
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Literal, Optional, Set, Union

logger = logging.getLogger("mentat.tools")

Schema = Literal["openai", "realtime"]

# Try to import mentat modules
try:
    from mentat.core.ai import analyze_capture_content, get_embedding_for_content
    from mentat.core.config import (
        LLM_REQUEST_TIMEOUT,
        OPENROUTER_BASE_URL,
        get_chat_api_key,
        get_chat_base_url,
        get_chat_provider,
        get_current_model,
    )
    from mentat.core.llm import OllamaChatClient
    from mentat.core.database import MemoryDatabase
    from openai import OpenAI
    MENTAT_AVAILABLE = True
except ImportError:
    MENTAT_AVAILABLE = False


@dataclass(frozen=True)
class ToolSpec:
    """Specification for a tool that can be called by the AI."""
    name: str
    description: Union[str, Callable[[], str]]  # Static string or dynamic function
    parameters: Dict[str, Any]
    channels: Set[str]
    handler: Callable[[Dict[str, Any], Dict[str, Any]], Any]
    enabled: bool = True

    def get_description(self) -> str:
        """Resolve description, calling it if it's a function."""
        if callable(self.description):
            return self.description()
        return self.description


def to_openai_tool(spec: ToolSpec) -> Dict[str, Any]:
    """Convert a ToolSpec to OpenAI function calling format."""
    return {
        "type": "function",
        "function": {
            "name": spec.name,
            "description": spec.get_description(),
            "parameters": spec.parameters,
        },
    }


def to_realtime_tool(spec: ToolSpec) -> Dict[str, Any]:
    """Convert a ToolSpec to OpenAI Realtime API format."""
    return {
        "type": "function",
        "name": spec.name,
        "description": spec.get_description(),
        "parameters": spec.parameters,
    }


# --- Shared handler utilities ---

def get_logger(context: Dict[str, Any]) -> logging.Logger:
    """Get logger from context or return default."""
    context_logger = context.get("logger")
    return context_logger if context_logger else logger


def get_channel(context: Dict[str, Any]) -> str:
    """Get normalized channel from context."""
    return (context.get("channel") or "chat").strip().lower()


def get_db() -> Optional["MemoryDatabase"]:
    """Get database instance if available."""
    if not MENTAT_AVAILABLE:
        return None
    return MemoryDatabase()


def get_openai_client() -> Optional["OpenAI"]:
    """Get OpenAI client for embeddings if available."""
    if not MENTAT_AVAILABLE:
        return None
    openai_api_key = os.getenv("OPENAI_API_KEY")
    if not openai_api_key:
        return None
    return OpenAI(api_key=openai_api_key)


def get_openrouter_client() -> Optional[Any]:
    """Get the normal chat LLM client if available.

    Uses CHAT_* provider settings when configured, otherwise preserves the
    existing OpenRouter client behavior.
    """

    if not MENTAT_AVAILABLE:
        return None

    chat_base_url = get_chat_base_url()
    if get_chat_provider() == "ollama":
        return OllamaChatClient(chat_base_url)

    chat_api_key = get_chat_api_key()
    if not chat_api_key:
        return None

    default_headers = None
    if chat_base_url == OPENROUTER_BASE_URL:
        # Optional OpenRouter metadata headers
        app_url = (
            os.getenv("OPENROUTER_APP_URL_CHATBOT")
            or os.getenv("OPENROUTER_APP_URL")
            or "https://mentat.local/chatbot"
        )
        app_title = (
            os.getenv("OPENROUTER_APP_TITLE_CHATBOT")
            or os.getenv("OPENROUTER_APP_TITLE")
            or "Mentat"
        )

        headers = {}
        if app_url:
            headers["HTTP-Referer"] = app_url
        if app_title:
            headers["X-Title"] = app_title
        default_headers = headers or None

    return OpenAI(
        api_key=chat_api_key,
        base_url=chat_base_url,
        timeout=LLM_REQUEST_TIMEOUT,
        default_headers=default_headers,
    )


def parse_allowed_commands(value: str) -> Set[str]:
    """Parse comma-separated command allowlist."""
    return {item.strip() for item in value.split(",") if item.strip()}


def truncate_output(text: str, limit: int) -> Dict[str, Any]:
    """Truncate text output to limit, returning truncation status."""
    if limit <= 0:
        return {"output": "", "truncated": bool(text)}
    if len(text) <= limit:
        return {"output": text, "truncated": False}
    return {"output": text[:limit], "truncated": True}


def parse_default_args(value: str) -> List[str]:
    """Parse shell-style default arguments string."""
    if not value:
        return []
    try:
        return shlex.split(value)
    except ValueError:
        return []


def parse_tags(tags: Any) -> List[str]:
    """Parse tags from various formats (string, list, JSON)."""
    if not tags:
        return []
    if isinstance(tags, list):
        return tags
    if isinstance(tags, str):
        try:
            parsed = json.loads(tags)
            return parsed if isinstance(parsed, list) else []
        except Exception:
            return []
    return []
