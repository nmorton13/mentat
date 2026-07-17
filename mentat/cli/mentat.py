#!/usr/bin/env python3
"""
MENTAT Command Line Interface - Enhanced Version with Rich UI
Uses /capture for intelligent content analysis and categorization
"""

import argparse
from importlib.metadata import PackageNotFoundError, version
import json
import sys
import os
from dataclasses import dataclass
from dotenv import load_dotenv
from datetime import datetime
import sys
import os

from mentat.core.database import MemoryDatabase
from mentat.core.ai import (
    analyze_capture_content, analyze_thoughts,
    generate_weekly_summary,
    get_embedding_for_content,
    process_content_with_ai,
    synthesize_notes, extract_structured_entities
)
from mentat.chat.enhanced_chat import EnhancedChatSystem
from openai import OpenAI
import json

env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
load_dotenv(dotenv_path=env_path)

# Import centralized configuration
from mentat.core.config import (
    AVAILABLE_MODELS, get_model_by_number, get_current_model,
    set_current_model, set_chat_route, DEFAULT_USER_ID,
    CHAT_MEMORY_K, SEARCH_RESULTS_K, PROJECT_ANALYSIS_K, SYNTHESIS_K, SEMANTIC_SEARCH_MIN_SIMILARITY,
    CHAT_SEARCH_MIN_SIMILARITY, PROJECT_SEARCH_MIN_SIMILARITY, CONNECTION_SURFACING_K,
    OPENAI_BASE_URL, OPENROUTER_BASE_URL, EMBEDDING_MODEL,
    get_chat_api_key, get_chat_base_url, get_chat_provider,
    GRUVBOX_COLORS, RICH_THEME,
    DATABASE_PATH,
    CHAT_PREVIEW_LENGTH, SEARCH_PREVIEW_LENGTH, PROJECT_PREVIEW_LENGTH,
    CHAT_SEARCH_K, DEFAULT_SUMMARY_DAYS, DEFAULT_MEMORY_LIMIT, STRONG_SEMANTIC_SIMILARITY_THRESHOLD,
    LLM_REQUEST_TIMEOUT
)

# Reload API keys after load_dotenv
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# Import display layer
from mentat.cli.display import (
    console, make_urls_clickable,
    format_content_with_markdown, render_markdown_content,
    render_markdown_to_panel, should_use_markdown_rendering,
    format_metadata_display, format_numbered_list_item,
    create_standard_panel, print_banner, print_colored,
    print_ai_reply, print_tool_reply, print_enhanced_chat_reply,
    display_llm_routes_table, display_models_table, display_search_results,
    show_loading_spinner, show_thinking_spinner
)
# Import shared utilities
from mentat.core.llm import OllamaChatClient
from mentat.core.utils import standardize_truncation, parse_item_metadata
from mentat.cli.commands import (
    handle_capture, handle_search, handle_links, handle_latest,
    handle_summary, handle_project, handle_tag, handle_todo, handle_mark,
    handle_synthesize, generate_reference_explanation, handle_save_response,
    handle_delete, handle_view_ai_reference, parse_link_memory,
    detect_ai_query, search_ai_responses
)
from mentat.cli.config_command import run_config_command
from rich import box
from rich.panel import Panel
from rich.prompt import Prompt
import time
import re

# Initialize database and clients
db = MemoryDatabase()  # Uses centralized DATABASE_PATH from config
openai_api_key = OPENAI_API_KEY
openrouter_api_key = get_chat_api_key()

# Initialize OpenAI client for embeddings
openai_client = OpenAI(api_key=openai_api_key, timeout=LLM_REQUEST_TIMEOUT) if openai_api_key else None

def build_chat_client():
    """Build the normal chat client from the effective route."""
    chat_base_url = get_chat_base_url()
    if get_chat_provider() == "ollama":
        return OllamaChatClient(chat_base_url)

    chat_api_key = get_chat_api_key()
    if not chat_api_key:
        return None

    default_headers = None
    if chat_base_url == OPENROUTER_BASE_URL:
        app_url = os.getenv("OPENROUTER_APP_URL_CLI") or os.getenv("OPENROUTER_APP_URL") or "https://mentat.local/cli"
        app_title = os.getenv("OPENROUTER_APP_TITLE_CLI") or os.getenv("OPENROUTER_APP_TITLE") or "Mentat CLI"
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


# Initialize normal chat LLM client. Variable name is historical.
openrouter_client = build_chat_client()

# Get current model from centralized config
current_model = get_current_model()

# Global storage for /view command
last_displayed_items = []
# Global reference to enhanced chat system for reference lookups
global_enhanced_chat = None
# Global storage for /save command - track last AI response
last_ai_response = None
last_ai_response_command = None
last_ai_prompt = None
# Global storage for last executed command to improve /view command context
last_executed_command = None

NUMBERED_CONTEXT_COMMANDS = {"view", "delete", "mark", "explore", "explain"}

CHAT_SPINNER_TEXT = "🧠 Starting chat..."
JSON_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class AgentFlags:
    """Top-level flags used by noninteractive agent workflows."""

    json_output: bool = False
    yes: bool = False

def update_ai_response_state(response, command, prompt=None):
    """Update global AI response state for saving"""
    global last_ai_response, last_ai_response_command, last_ai_prompt
    last_ai_response = response
    last_ai_response_command = command
    last_ai_prompt = prompt


def parse_content_arg(content_parts):
    """Return a shell-friendly content string from argparse remainder parts."""
    if content_parts is None:
        return ""
    if isinstance(content_parts, str):
        return content_parts
    return " ".join(content_parts).strip()


def extract_agent_flags(argv):
    """Extract agent-mode flags before argparse treats them as content."""
    cleaned = []
    json_output = False
    yes = False

    for arg in argv:
        if arg == "--json":
            json_output = True
        elif arg == "--yes":
            yes = True
        else:
            cleaned.append(arg)

    return cleaned, AgentFlags(json_output=json_output, yes=yes)


def _metadata_payload(metadata):
    if not metadata:
        return {}
    if isinstance(metadata, dict):
        return metadata
    try:
        return json.loads(metadata)
    except (TypeError, json.JSONDecodeError):
        return {}


def json_envelope(command, data=None, success=True, error=None):
    payload = {
        "schema_version": JSON_SCHEMA_VERSION,
        "command": command,
        "success": success,
    }
    if success:
        payload["data"] = data if data is not None else {}
    else:
        payload["error"] = error or {"message": "Unknown error"}
    return payload


def print_json_response(command, data=None, success=True, error=None):
    print(json.dumps(json_envelope(command, data, success, error), ensure_ascii=False))


def memory_json_item(item):
    metadata = _metadata_payload(item.get("metadata"))
    return {
        "id": item.get("id"),
        "type": item.get("command_type"),
        "content": item.get("content", ""),
        "tags": item.get("tags", []),
        "timestamp": item.get("timestamp"),
        "metadata": metadata,
        "why_matched": item.get("why_matched"),
    }


def link_json_item(link_data):
    content, metadata_json = link_data[:2]
    memory_id = link_data[2] if len(link_data) > 2 else None
    parsed = parse_link_memory(content, metadata_json)
    return {
        "id": memory_id,
        "title": parsed["title"],
        "url": parsed["url"],
        "summary": parsed["summary"],
        "comment": parsed["comment"],
        "tags": parsed["tags"],
        "content": content,
        "metadata": _metadata_payload(metadata_json),
    }


def todo_json_item(todo):
    return {
        "id": todo.get("todo_id"),
        "memory_id": todo.get("memory_id"),
        "item_index": todo.get("item_index"),
        "display_number": todo.get("display_number"),
        "action": todo.get("action"),
        "context": todo.get("context", ""),
        "priority": todo.get("priority", "medium"),
        "status": todo.get("status", "pending"),
        "marked_date": todo.get("marked_date", ""),
        "time_sensitive": todo.get("time_sensitive", False),
        "project": todo.get("project", ""),
        "due_date": todo.get("due_date", ""),
        "dependencies": todo.get("dependencies", []),
        "source_content": todo.get("source_content", ""),
        "timestamp": todo.get("timestamp"),
        "tags": todo.get("tags", []),
        "type": todo.get("command_type"),
    }


def chat_reference_json_items(enhanced_chat):
    references = getattr(enhanced_chat, "session_references", {}) or {}
    items = []
    for ref_id in sorted(references, key=lambda value: int(value) if str(value).isdigit() else str(value)):
        reference = references[ref_id]
        timestamp = reference.get("timestamp")
        if hasattr(timestamp, "isoformat"):
            timestamp = timestamp.isoformat()
        items.append({
            "id": ref_id,
            "topic": reference.get("topic", ""),
            "context": reference.get("context", ""),
            "personal_context": reference.get("personal_context", ""),
            "timestamp": timestamp,
        })
    return items


def chat_json_payload(result, enhanced_chat, query, model):
    return {
        "query": query,
        "model": model,
        "response": result.get("response", ""),
        "sources": result.get("sources", []),
        "patterns": result.get("patterns", []),
        "connections": result.get("connections", []),
        "suggestions": result.get("suggestions", []),
        "references": chat_reference_json_items(enhanced_chat),
        "viewable_items": result.get("viewable_items", []),
    }


def json_error(command, message, code="error"):
    print_json_response(command, success=False, error={"code": code, "message": message})


def parse_latest_limit(arg):
    """Parse an optional latest count, falling back to the configured default."""
    if not arg:
        return DEFAULT_MEMORY_LIMIT
    if arg.isdigit() and int(arg) > 0:
        return int(arg)
    raise ValueError("latest count must be a positive integer")


def parse_todo_args(arg):
    """Parse todo arguments into search term and status filter."""
    if not arg:
        return None, None
    if arg in ["pending", "done"]:
        return None, arg
    return arg, None


def parse_connect_concepts(arg):
    """Parse two concept names from quoted, pipe-delimited, or plain input."""
    if not arg:
        return []
    if "|" in arg:
        return [concept.strip() for concept in arg.split("|") if concept.strip()]

    import re
    quoted_pattern = r'"([^"]+)"|\'([^\']+)\'|(\S+)'
    matches = re.findall(quoted_pattern, arg)
    concepts = [match[0] or match[1] or match[2] for match in matches if any(match)]
    if len(concepts) == 2:
        return concepts
    if len(concepts) > 2:
        return [" ".join(concepts[:-1]), concepts[-1]]
    return concepts


def _default_label_for_model(model_id: str) -> str:
    return model_id.rstrip("/").split("/")[-1] or model_id


def _save_openrouter_model_if_missing(model_id: str) -> None:
    """Offer to save a pasted OpenRouter model into config/models.json."""
    global AVAILABLE_MODELS
    if model_id in AVAILABLE_MODELS.values():
        return

    if not sys.stdin.isatty():
        return
    try:
        answer = Prompt.ask(
            "[yellow]Save this OpenRouter model to config/models.json for future /model selection?[/yellow]",
            choices=["y", "n"],
            default="y",
        )
    except Exception:
        return
    if answer.lower() != "y":
        return

    from mentat.core import config as core_config

    label = Prompt.ask("Label", default=_default_label_for_model(model_id)).strip() or _default_label_for_model(model_id)
    config_path = core_config.Path(core_config.MODEL_CONFIG_PATH)
    data = core_config._load_model_config() or {"default_model": model_id, "models": []}
    models = data.setdefault("models", [])
    if not any(isinstance(entry, dict) and entry.get("id") == model_id for entry in models):
        models.append({"id": model_id, "label": label, "reasoning": False})
        config_path.parent.mkdir(parents=True, exist_ok=True)
        with config_path.open("w", encoding="utf-8") as file:
            json.dump(data, file, indent=2)
            file.write("\n")
        core_config.refresh_available_models()
        AVAILABLE_MODELS = core_config.AVAILABLE_MODELS
        console.print(f"[green]💾 Saved {model_id} as {label}[/green]")


def _refresh_chat_client_after_route_change() -> None:
    global openrouter_client
    openrouter_client = build_chat_client()


def _switch_chat_route(provider: str, model_id: str, message: str) -> bool:
    global current_model
    if not set_chat_route(provider, model_id):
        console.print(f"[red]❌ Could not switch chat route to {provider}: {model_id}[/red]")
        return False
    # Keep the legacy model setter side effects/tests intact for curated models.
    set_current_model(model_id)
    current_model = model_id
    _refresh_chat_client_after_route_change()
    console.print(message)
    return True


def handle_model_command(arg):
    """Show or switch the current chat route/model for interactive and top-level CLI."""
    global current_model

    if arg:
        stripped_arg = arg.strip()
        parts = stripped_arg.split()
        switch_successful = False

        if parts and parts[0].lower() == "local":
            from mentat.core import config as core_config

            local_model = " ".join(parts[1:]).strip() or core_config.CHAT_MODEL or core_config.LOCAL_MODEL
            if not local_model:
                console.print("[red]❌ No local model configured. Set CHAT_MODEL or LOCAL_MODEL, or run /model local <model>.[/red]")
                return
            if not (core_config.CHAT_BASE_URL or core_config.LOCAL_BASE_URL):
                console.print("[red]❌ No local base URL configured. Set CHAT_BASE_URL or LOCAL_BASE_URL.[/red]")
                return
            switch_successful = _switch_chat_route(
                "local",
                local_model,
                f"[green]✅ Chat route switched to local: {local_model}[/green]",
            )

        elif parts and parts[0].lower() == "ollama":
            from mentat.core import config as core_config

            ollama_model = " ".join(parts[1:]).strip() or core_config.OLLAMA_MODEL
            if not ollama_model:
                console.print("[red]❌ No Ollama model configured. Set OLLAMA_MODEL, or run /model ollama <model>.[/red]")
                return
            switch_successful = _switch_chat_route(
                "ollama",
                ollama_model,
                f"[green]✅ Chat route switched to native Ollama: {ollama_model}[/green]",
            )

        elif parts and parts[0].lower() == "openrouter":
            model_id = " ".join(parts[1:]).strip()
            if not model_id:
                console.print("[red]❌ Usage: /model openrouter <provider/model-id>[/red]")
                return
            switch_successful = _switch_chat_route(
                "openrouter",
                model_id,
                f"[green]✅ Chat route switched to OpenRouter: {model_id}[/green]",
            )
            if switch_successful:
                _save_openrouter_model_if_missing(model_id)

        elif stripped_arg.isdigit():
            model_to_switch = get_model_by_number(stripped_arg)
            if model_to_switch:
                switch_successful = _switch_chat_route(
                    "openrouter",
                    model_to_switch,
                    f"[green]✅ OpenRouter model switched to #{stripped_arg}: {model_to_switch}[/green]",
                )
            else:
                console.print(f"[red]❌ Invalid model number: {stripped_arg}. Use 1-{len(AVAILABLE_MODELS)}[/red]")
        else:
            model_key = stripped_arg.lower()
            if model_key in AVAILABLE_MODELS:
                model_to_switch = AVAILABLE_MODELS[model_key]
                switch_successful = _switch_chat_route(
                    "openrouter",
                    model_to_switch,
                    f"[green]✅ OpenRouter model switched to: {model_to_switch}[/green]",
                )
            elif stripped_arg in AVAILABLE_MODELS.values():
                switch_successful = _switch_chat_route(
                    "openrouter",
                    stripped_arg,
                    f"[green]✅ OpenRouter model switched to: {stripped_arg}[/green]",
                )
            elif set_current_model(stripped_arg):
                current_model = stripped_arg
                _refresh_chat_client_after_route_change()
                console.print(f"[green]✅ Model switched to: {current_model}[/green]")
                switch_successful = True
            else:
                console.print(f"[red]❌ Unknown model: {stripped_arg}[/red]")
                console.print(f"[yellow]💡 Try /model <number>, /model local, /model ollama <model>, or /model openrouter <provider/model-id>[/yellow]")

        if switch_successful:
            console.print()
            console.print(f"[bright_cyan]🤖 Current model: [bold]{current_model}[/bold][/bright_cyan]")
            console.print()
            display_llm_routes_table(current_model, openrouter_client)
            console.print()
            display_models_table(current_model)
        return

    console.print(f"[bright_cyan]🤖 Current model: [bold]{current_model}[/bold][/bright_cyan]")
    console.print()
    display_llm_routes_table(current_model, openrouter_client)
    console.print()
    display_models_table(current_model)


def make_spinner_status_callback(progress, task):
    """Create a small callback for live chat spinner status updates."""
    def update_status(message):
        progress.update(task, description=message)

    return update_status


def should_prioritize_ai_references(
    last_command: str,
    has_ai_references: bool,
    has_search_results: bool
) -> bool:
    """Determine whether /view should check AI references before search results."""
    if has_ai_references and not has_search_results:
        return True
    if has_search_results and not has_ai_references:
        return False

    search_result_commands = ["search", "todo", "latest", "project", "synthesize", "tags"]
    if last_command in search_result_commands:
        return False
    return has_ai_references


def select_view_item(item_num: int, items: list):
    """Select viewable item by display_number (todos) or by index fallback."""
    for potential_item in items:
        if "original_todo" in potential_item:
            original_todo = potential_item["original_todo"]
            if original_todo.get("display_number") == item_num:
                return potential_item

    if 1 <= item_num <= len(items):
        return items[item_num - 1]

    return None


def format_view_metadata_markdown(tags, date, command_type, web_context=None, source_info=None):
    """Build plain markdown metadata for /view panels."""
    metadata_parts = []

    if tags:
        tags_str = ", ".join(tags) if isinstance(tags, list) else str(tags)
        metadata_parts.append(f"**Tags:** {tags_str}")

    if source_info and source_info.get("type") == "ai_response":
        model = source_info.get("model", "AI")
        model_display = next(
            (friendly_name for friendly_name, model_path in AVAILABLE_MODELS.items() if model_path == model),
            model,
        )
        metadata_parts.append(f"**Source:** {model_display} response")
        command_type = "ai_response"

    if web_context and web_context.get("web_enriched"):
        source_count = web_context.get("source_count", 0)
        if source_count > 1:
            metadata_parts.append(f"**Web-enriched:** {source_count} sources")
        else:
            metadata_parts.append("**Web-enriched:** yes")

    if date:
        formatted_date = date[:10] if len(date) > 10 else date
        metadata_parts.append(f"**Date:** {formatted_date}")

    if command_type:
        metadata_parts.append(f"**Type:** {command_type.upper()}")

    return "\n".join(metadata_parts)


def build_view_panel(item: dict, item_num: int):
    """Build the /view panel for a selected item."""
    content = item.get("content", "No content available")
    timestamp = item.get("timestamp", "Unknown date")
    command_type = item.get("command_type", "Unknown type")

    # Extract source information from metadata if present
    _, source_info, web_context = parse_item_metadata(item)

    # Use markdown metadata when the body will be rendered as markdown.
    markdown_metadata = format_view_metadata_markdown(
        item.get("tags", []),
        timestamp,
        command_type,
        web_context,
        source_info
    )

    # Use Rich metadata only for the plain panel path.
    metadata = format_metadata_display(
        item.get("tags", []),
        timestamp,
        command_type,
        None,
        web_context,
        source_info
    )

    # Special handling for link content - convert to markdown
    if command_type.upper() == "LINK" and "Title:" in content and "URL:" in content:
        # Parse the link content and format as markdown
        lines = content.split("\n")
        title = url = summary = ""

        for line in lines:
            line = line.strip()
            if line.startswith("Title:"):
                title = line.replace("Title:", "").strip()
            elif line.startswith("URL:"):
                url = line.replace("URL:", "").strip()
            elif line.startswith("Summary:"):
                summary = line.replace("Summary:", "").strip()

        # Create markdown metadata (no Rich markup)
        tags_str = ", ".join(item.get("tags", []))
        markdown_metadata = f"**Tags:** {tags_str}\n" if tags_str else ""
        markdown_metadata += f"**Date:** {timestamp}\n"
        markdown_metadata += f"**Type:** {command_type.upper()}\n"

        # Create proper markdown content
        markdown_content = f"# {title}\n\n" if title else ""
        markdown_content += f"**URL:** [{url}]({url})\n\n" if url else ""
        markdown_content += f"**Summary:** {summary}" if summary else ""

        view_content = f"{markdown_metadata}\n{markdown_content}"
        return render_markdown_to_panel(
            view_content,
            f"📄 Item {item_num} - Full Content",
            None,
            "cyan"
        )

    # Check if content should use enhanced markdown rendering
    if should_use_markdown_rendering(content):
        view_content = f"{markdown_metadata}\n\n{content}"
        return render_markdown_to_panel(
            view_content,
            f"📄 Item {item_num} - Full Content",
            None,
            "cyan"
        )

    # Use basic formatting for simple content
    formatted_content = format_content_with_markdown(content)
    view_content = f"{metadata}\n\n{formatted_content}"
    return create_standard_panel(
        view_content,
        f"📄 Item {item_num} - Full Content",
        None,
        "cyan"
    )



# All command handlers and utility functions moved to commands.py and display.py



def interactive_mode(user_id):
    """Interactive REPL mode with Rich UI"""
    global current_model, global_enhanced_chat
    if not openrouter_client:
        console.print("[yellow]⚠️ Chat features limited without OpenRouter API key.[/yellow]")

    # Initialize chat history for the interactive session
    chat_history = []
    N = 6  # Number of messages to keep (3 user/assistant exchanges)
    
    # Show welcome message with embedding/LLM info and stats
    # Get embedding model info
    embedding_model = EMBEDDING_MODEL
    embedding_status = (
        f"[dim]Embeddings: {embedding_model}[/dim]"
        if openai_client else
        "[yellow]Embeddings: OpenAI API key not set (embedding features limited)[/yellow]"
    )
    # Compact route summary for normal chat and key feature-specific LLM routes
    from mentat.core.llm import get_llm_route_summary
    llm_info = f"[dim]LLM routes: {get_llm_route_summary(openrouter_client, current_model)}[/dim]"
    # Get user stats (memories, links, todos)
    try:
        stats = db.get_database_stats(user_id)
        total_memories = stats.get('total_memories', 0)
        type_counts = dict(stats.get('type_counts', []))
        num_links = type_counts.get('link', 0)
        num_todos = type_counts.get('task', 0)
        stats_line = f"[dim]Stats: {total_memories} memories, {num_links} links, {num_todos} todos[/dim]"
    except Exception:
        stats_line = "[dim]Stats: unavailable[/dim]"

    welcome_panel = Panel(
        
        "[dim]Use /help for commands. Type /exit to quit.[/dim]\n"
        f"[dim]Current user: {user_id}[/dim]\n"
        f"[dim]Current model: {current_model}[/dim]\n"
        f"{embedding_status}\n"
        f"{llm_info}\n"
        f"{stats_line}",
        title=" MENTAT Interactive",
        border_style="bright_cyan",
        box=box.ROUNDED
    )
    console.print(welcome_panel)
    console.print()

    from prompt_toolkit import prompt
    from prompt_toolkit.formatted_text import HTML
    from prompt_toolkit.history import FileHistory
    from prompt_toolkit.cursor_shapes import CursorShape

    while True:
        try:
            # Enhanced prompt with current model
            model_short = current_model.split('/')[-1] if '/' in current_model else current_model
            # Enhanced prompt with Rich-style formatting and command history
            prompt_text = HTML(f'<ansicyan><b>mentat</b></ansicyan> <ansibrightblack>({user_id})</ansibrightblack> <ansibrightblack>[</ansibrightblack><ansiyellow>{model_short}</ansiyellow><ansibrightblack>]</ansibrightblack> ')
            user_input = prompt(
                prompt_text, 
                history=FileHistory('.mentat_history'),
                cursor=CursorShape.BLINKING_BLOCK
            )
            
            if not user_input:
                continue
            if user_input.lower() in ["/exit", "/quit"]:
                break
            elif user_input.startswith("/"):
                parts = user_input[1:].split(maxsplit=1)
                cmd = parts[0].lower()
                arg = parts[1] if len(parts) > 1 else None
                
                # Track last executed command for better context in /view
                # Don't update for view, delete, mark commands as they need previous context
                global last_executed_command
                if cmd not in ["view", "delete", "mark"]:
                    last_executed_command = cmd
                
                # Clear previous results for /view command (except for commands that need numbered items)
                if cmd not in NUMBERED_CONTEXT_COMMANDS:
                    global last_displayed_items
                    last_displayed_items = []

                if cmd == "help":
                    help_text = """
[bold]Available Commands:[/bold]
• [cyan]/capture <text>[/cyan] - Capture and analyze content (use /capture alone for multi-line mode)
• [cyan]/capture --web-search <text>[/cyan] - Capture with web context enrichment (use -w for short)
• [cyan]/search <query>[/cyan] - Search your memories
• [cyan]/search ai response[/cyan] - Show saved AI responses
• [cyan]/links [term][/cyan] - Show saved links | [cyan]/link <url> [comment][/cyan] - Save a link
• [cyan]/latest[/cyan] - Show recent content
• [cyan]/summary [days][/cyan] - Generate summary
• [cyan]/project <name>[/cyan] - Analyze project
• [cyan]/tag <tags>[/cyan] - Search by tags
• [cyan]/todo [search|done][/cyan] - Show todos (completed hidden by default)
• [cyan]/mark <number>[s][/cyan] - Toggle todo(s) done/pending (e.g., /mark 3 or /mark 10, 13, 24)
• [cyan]/synthesize <topic>[/cyan] - Synthesize notes
• [cyan]/chat <query>[/cyan] - Chat with AI
• [cyan]/voice[/cyan] - Start a voice chat session
• [cyan]/explore <concept|number>[/cyan] - Deep concept exploration with knowledge gaps analysis
• [cyan]/connect "concept1" "concept2"[/cyan] - Analyze concept relationships (use quotes for multi-word)
• [cyan]/model [model][/cyan] - Change AI model
• [cyan]/view <number>[/cyan] - View full content from last results
• [cyan]/help[/cyan] - Show this help
• [cyan]/exit[/cyan] - Quit
                    """
                    help_panel = create_standard_panel(help_text, "📚 Help", None, "bright_blue")
                    console.print(help_panel)
                    
                elif cmd == "voice":
                    import asyncio
                    try:
                        from mentat.cli.voice_command import voice_command
                    except ImportError as exc:
                        console.print("[yellow]Voice dependencies are not installed.[/yellow]")
                        console.print("[cyan]Run: uv sync --extra voice[/cyan]")
                        console.print(f"[dim]{exc}[/dim]")
                        continue
                    try:
                        asyncio.run(voice_command(user_id))
                    except KeyboardInterrupt:
                        # Voice session ended gracefully, continue CLI
                        pass
                elif cmd == "view" and arg:
                    try:
                        item_num = int(arg)
                        
                        # Smart priority: Consider the last executed command for better context
                        has_ai_references = global_enhanced_chat and len(global_enhanced_chat.session_references) > 0
                        has_search_results = len(last_displayed_items) > 0
                        
                        # Debug info (can be removed later)
                        # console.print(f"[dim]Debug: last_executed_command='{last_executed_command}', has_ai_references={has_ai_references}, has_search_results={has_search_results}[/dim]")
                        
                        # Determine which to check first based on context
                        check_ai_first = should_prioritize_ai_references(
                            last_executed_command,
                            has_ai_references,
                            has_search_results
                        )
                        
                        # Try AI references first if determined
                        found_item = False
                        
                        if check_ai_first and global_enhanced_chat:
                            try:
                                reference = global_enhanced_chat.get_reference(str(item_num))
                                if reference:
                                    handle_view_ai_reference(
                                        reference, item_num, user_id, current_model,
                                        db, openrouter_client, global_enhanced_chat
                                    )
                                    found_item = True
                            except Exception as ref_error:
                                pass  # Fall back to search results
                        
                        # Check for regular search results if not found in AI references
                        # Need to search by display_number, not array index, to handle filtered todos
                        if not found_item and len(last_displayed_items) > 0:
                            # Find item by display_number (todos) or array index fallback.
                            item = select_view_item(item_num, last_displayed_items)

                            if item is not None:
                                panel = build_view_panel(item, item_num)
                                console.print(panel)
                            found_item = True  # Mark as found to prevent error message
                            
                        # If not found, try the other system as fallback
                        if not found_item and not check_ai_first and global_enhanced_chat:
                            try:
                                reference = global_enhanced_chat.get_reference(str(item_num))
                                if reference:
                                    handle_view_ai_reference(
                                        reference, item_num, user_id, current_model,
                                        db, openrouter_client, global_enhanced_chat
                                    )
                                    found_item = True
                            except Exception as ref_error:
                                pass
                        
                        # Show error if nothing found
                        if not found_item:
                            ref_count = len(global_enhanced_chat.session_references) if global_enhanced_chat else 0
                            search_count = len(last_displayed_items)
                            max_range = max(search_count, ref_count)
                            
                            if max_range > 0:
                                if search_count > 0 and ref_count > 0:
                                    console.print(f"[red]❌ Invalid number. Available: 1-{search_count} (search results) or 1-{ref_count} (AI references)[/red]")
                                elif search_count > 0:
                                    console.print(f"[red]❌ Invalid number. Choose 1-{search_count} (search results)[/red]")
                                else:
                                    console.print(f"[red]❌ Invalid number. Choose 1-{ref_count} (AI references)[/red]")
                            else:
                                console.print("[red]❌ No items available to view[/red]")
                                
                    except ValueError:
                        console.print("[red]❌ Please provide a valid number[/red]")
                elif cmd == "view":
                    ref_count = len(global_enhanced_chat.session_references) if global_enhanced_chat else 0
                    max_items = max(len(last_displayed_items), ref_count)
                    
                    if max_items > 0:
                        if len(last_displayed_items) > 0 and ref_count > 0:
                            console.print(f"[yellow]Available items: 1-{len(last_displayed_items)} (search results) | 1-{ref_count} (AI references). Use /view <number>[/yellow]")
                        elif len(last_displayed_items) > 0:
                            console.print(f"[yellow]Available items: 1-{len(last_displayed_items)} (search results). Use /view <number>[/yellow]") 
                        else:
                            console.print(f"[yellow]Available references: 1-{ref_count} (AI references). Use /view <number>[/yellow]")
                    else:
                        console.print("[yellow]No recent results to view. Run a search or start a chat first.[/yellow]")
                
                elif cmd == "delete" and arg:
                    handle_delete(arg, user_id, db, last_displayed_items)
                    
                elif cmd == "save":
                    def clear_ai_response():
                        global last_ai_response, last_ai_response_command, last_ai_prompt
                        last_ai_response = None
                        last_ai_response_command = None
                        last_ai_prompt = None
                    
                    handle_save_response(user_id, current_model, openrouter_client, openai_client, db, 
                                       last_displayed_items, last_ai_response, last_ai_response_command, last_ai_prompt, clear_ai_response)
                    
                elif cmd == "model":
                    handle_model_command(arg)
                    continue
                    
                elif cmd == "capture":
                    # Clear chat history for commands (stateless)
                    chat_history = []
                    if arg:
                        # Check for web search flag
                        enable_web_search = False
                        content = arg
                        if arg.startswith(('--web-search ', '-w ')):
                            enable_web_search = True
                            content = arg.split(' ', 1)[1] if ' ' in arg else ""
                        elif arg in ('--web-search', '-w'):
                            enable_web_search = True
                            content = ""
                        
                        if content:
                            # Single line capture
                            handle_capture(content, user_id, enable_web_search, current_model, openrouter_client, openai_client, db, last_displayed_items)
                        elif enable_web_search:
                            # Multi-line capture mode with web search enabled
                            console.print("[cyan]📝 Multi-line capture mode with web search enabled. Enter your content (press Ctrl+D or type 'END' on a new line to finish):[/cyan]")
                            lines = []
                            try:
                                while True:
                                    line = Prompt.ask("[dim]>[/dim]", default="")
                                    if line.strip().upper() == "END":
                                        break
                                    lines.append(line)
                            except EOFError:
                                # Ctrl+D pressed
                                pass
                            if lines:
                                full_content = "\n".join(lines)
                                handle_capture(full_content, user_id, True, current_model, openrouter_client, openai_client, db, last_displayed_items)
                        else:
                            console.print("[red]❌ No content provided for capture[/red]")
                    else:
                        # Multi-line capture mode
                        console.print("[cyan]📝 Multi-line capture mode. Enter your content (press Ctrl+D or type 'END' on a new line to finish):[/cyan]")
                        lines = []
                        try:
                            while True:
                                line = Prompt.ask("[dim]>[/dim]", default="")
                                if line.strip().upper() == "END":
                                    break
                                lines.append(line)
                        except EOFError:
                            # Ctrl+D pressed
                            pass
                        if lines:
                            content = "\n".join(lines)
                            handle_capture(content, user_id, False, current_model, openrouter_client, openai_client, db, last_displayed_items)
                        else:
                            console.print("[yellow]No content entered.[/yellow]")
                elif cmd == "search" and arg:
                    chat_history = []
                    handle_search(arg, user_id, current_model, openrouter_client, openai_client, db, last_displayed_items)
                elif cmd == "links":
                    chat_history = []
                    handle_links(user_id, arg, db)
                elif cmd == "link" and arg:
                    chat_history = []
                    from .commands import handle_link
                    handle_link(arg, user_id, current_model, openrouter_client, openai_client, db, last_displayed_items)
                elif cmd == "latest":
                    chat_history = []
                    try:
                        limit = parse_latest_limit(arg)
                    except ValueError as e:
                        console.print(f"[red]❌ {e}[/red]")
                        continue
                    handle_latest(user_id, db, last_displayed_items, limit=limit)
                elif cmd == "summary":
                    chat_history = []
                    days = int(arg) if arg and arg.isdigit() else DEFAULT_SUMMARY_DAYS
                    handle_summary(user_id, days, current_model, openrouter_client, db)
                elif cmd == "project" and arg:
                    chat_history = []
                    handle_project(arg, user_id, current_model, openrouter_client, db)
                elif cmd == "tag" and arg:
                    chat_history = []
                    handle_tag(arg.split(), user_id, db, last_displayed_items)
                elif cmd == "todo":
                    chat_history = []
                    # Parse argument as either status filter or search term
                    status_filter = None
                    search_term = None
                    
                    if arg:
                        # Check if arg is a status filter
                        if arg in ['pending', 'done']:
                            status_filter = arg
                        else:
                            search_term = arg
                    
                    handle_todo(user_id, search_term, db, status_filter, last_displayed_items)
                elif cmd == "mark":
                    chat_history = []
                    if not arg:
                        console.print("[red]❌ Usage: /mark <number>[s][/red]")
                        console.print("[dim]Examples:[/dim]")
                        console.print("[dim]  /mark 3           - Mark a single todo[/dim]")
                        console.print("[dim]  /mark 10, 13, 24 - Mark multiple todos[/dim]")
                        continue

                    try:
                        # Parse comma-separated numbers
                        if ',' in arg:
                            # Multiple numbers
                            todo_numbers = []
                            for num_str in arg.split(','):
                                num_str = num_str.strip()
                                if num_str:
                                    todo_numbers.append(int(num_str))

                            if not todo_numbers:
                                console.print("[red]❌ No valid todo numbers provided[/red]")
                                continue

                            handle_mark(user_id, todo_numbers, db)
                        else:
                            # Single number
                            todo_number = int(arg.strip())
                            handle_mark(user_id, todo_number, db)
                    except ValueError:
                        console.print("[red]❌ Todo numbers must be valid integers[/red]")
                        console.print("[dim]Examples: /mark 3 or /mark 10, 13, 24[/dim]")
                        continue
                elif cmd == "hide":
                    chat_history = []
                    # Show only pending todos (hide completed ones)
                    handle_todo(user_id, "", db, "pending", last_displayed_items)
                elif cmd == "synthesize" and arg:
                    chat_history = []
                    handle_synthesize(user_id, arg, current_model, openrouter_client, openai_client, db)
                elif cmd == "explore" and arg:
                    chat_history = []
                    from .commands import handle_explore_web_command
                    handle_explore_web_command(
                        arg,
                        user_id,
                        db,
                        openrouter_client,
                        last_displayed_items,
                        global_enhanced_chat,
                        interactive=True,
                    )
                elif cmd == "explain" and arg:
                    chat_history = []
                    from .commands import handle_explain_command
                    handle_explain_command(arg, user_id, db, openrouter_client, global_enhanced_chat, last_displayed_items)
                elif cmd == "connect" and arg:
                    chat_history = []
                    from .commands import handle_connect_command

                    # Parse concepts with support for multi-word phrases
                    # Supports three formats:
                    # 1. Quoted: /connect "machine learning" "mental health"
                    # 2. Pipe-delimited: /connect machine learning | mental health
                    # 3. Simple space: /connect gaming health (for single words)

                    concepts = parse_connect_concepts(arg)

                    if len(concepts) >= 2:
                        handle_connect_command(concepts[0], concepts[1], user_id, openrouter_client, db, current_model)
                    else:
                        console.print("[red]❌ /connect requires two concepts[/red]")
                        console.print('[dim]Usage examples:[/dim]')
                        console.print('[dim]  /connect "machine learning" "mental health"[/dim]')
                        console.print('[dim]  /connect machine learning | mental health[/dim]')
                        console.print('[dim]  /connect gaming health[/dim]')
                elif cmd in ["exit", "quit"]:
                    break
                elif cmd == "chat" and arg:
                    if not openrouter_client:
                        console.print("[red]❌ Chat unavailable without API key.[/red]")
                        continue
                    
                    # Clear chat history for /chat command (stateless)
                    chat_history = []
                    
                    # Clear search results so AI references get priority
                    last_displayed_items = []
                    
                    # Initialize enhanced chat system
                    enhanced_chat = EnhancedChatSystem(db, openrouter_client)
                    global_enhanced_chat = enhanced_chat  # Make available for /view references
                    
                    # Show progress through the actual enhanced-chat stages.
                    with show_thinking_spinner(CHAT_SPINNER_TEXT) as (progress, task):
                        # Get enhanced response
                        result = enhanced_chat.enhanced_chat_response(
                            arg,
                            user_id,
                            current_model,
                            update_ai_response_state,
                            status_callback=make_spinner_status_callback(progress, task),
                        )
                    
                    # Display enhanced chat response in unified beautiful format
                    print_enhanced_chat_reply(result, current_model, global_enhanced_chat, last_displayed_items)
                    
                    continue
                    
                else:
                    console.print("[red]❌ Unknown command. Use /help for list.[/red]")
            else:
                # Handle regular chat input using enhanced chat system
                if openrouter_client:
                    # Clear search results so AI references get priority
                    last_displayed_items = []
                    
                    # Initialize enhanced chat system
                    enhanced_chat = EnhancedChatSystem(db, openrouter_client)
                    global_enhanced_chat = enhanced_chat  # Make available for /view references
                    
                    # Show progress through the actual enhanced-chat stages.
                    with show_thinking_spinner(CHAT_SPINNER_TEXT) as (progress, task):
                        # Get enhanced response
                        result = enhanced_chat.enhanced_chat_response(
                            user_input,
                            user_id,
                            current_model,
                            update_ai_response_state,
                            status_callback=make_spinner_status_callback(progress, task),
                        )
                    
                    # Display enhanced chat response in unified beautiful format
                    print_enhanced_chat_reply(result, current_model, global_enhanced_chat, last_displayed_items)
                    
                    # Update chat history for continuity (simplified - just track the conversation)
                    chat_history.append({"role": "user", "content": user_input})
                    chat_history.append({"role": "assistant", "content": result['response']})
                    chat_history = chat_history[-N:]  # Keep last N turns
                    
                else:
                    console.print("[red]❌ Chat unavailable without API key.[/red]")
                    
        except EOFError:
            # Handle EOF (Ctrl+D or piped input ending)
            console.print("\\n[green]👋 Goodbye![/green]")
            break
        except KeyboardInterrupt:
            # Handle Ctrl+C
            console.print("\\n[green]👋 Goodbye![/green]")
            break
        except Exception as e:
            console.print(f"[bold red]❌ Error: {str(e)}[/bold red]")

def main():
    global global_enhanced_chat
    argv, agent_flags = extract_agent_flags(sys.argv[1:])

    parser = argparse.ArgumentParser(
        description="Mentat - an opinionated memory system for selective thought capture and reflection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  mentat                      # Interactive mode
  mentat capture "This idea from my walk still feels worth thinking through"
  mentat chat "what patterns do you see in my recent notes?"
  mentat latest 25
  mentat search "artificial intelligence"
  mentat links
  mentat todo pending
  mentat config init
  mentat config doctor

The /capture command intelligently analyzes and categorizes your content!
        """
    )
    try:
        release_version = version("mentat")
    except PackageNotFoundError:
        release_version = "0.8.0"
    parser.add_argument('--version', action='version', version=f'Mentat {release_version}')

    parser.add_argument('command', nargs='?', default=None, choices=[
        'capture', 'chat', 'search', 'links', 'link', 'latest', 'summary',
        'project', 'tag', 'todo', 'model', 'synthesize', 'explore', 'explain',
        'connect', 'view', 'delete', 'mark', 'config'
    ], help='Command to execute')

    parser.add_argument('content', nargs='*', help='Content for the command')
    parser.add_argument('--user', '-u', default=DEFAULT_USER_ID, help='User ID (default: MENTAT_USER_ID or mentat)')
    parser.add_argument('--days', '-d', type=int, default=DEFAULT_SUMMARY_DAYS, help=f'Number of days for summary (default: {DEFAULT_SUMMARY_DAYS})')
    parser.add_argument('--tags', '-t', nargs='+', help='Tags for tag search')
    parser.add_argument('--web-search', '-w', action='store_true', help='Enable web search for context enrichment during capture')

    args = parser.parse_args(argv)

    json_supported_commands = {"chat", "search", "latest", "links", "todo"}

    if agent_flags.json_output and args.command not in json_supported_commands:
        json_error(
            args.command or "interactive",
            "--json is only supported for chat, search, latest, links, and todo",
            "unsupported_json_command",
        )
        sys.exit(1)

    if agent_flags.yes and args.command != "delete":
        if agent_flags.json_output:
            json_error(
                args.command or "interactive",
                "--yes is only supported for delete",
                "unsupported_yes_flag",
            )
        else:
            console.print("[red]❌ --yes is only supported for delete[/red]")
        sys.exit(1)

    if args.command == "config":
        sys.exit(run_config_command(args.content, activate_route=set_chat_route))

    # Show banner
    if not agent_flags.json_output:
        print_banner()

    if args.command is None:
        interactive_mode(args.user)
        sys.exit(0)

    content_arg = parse_content_arg(args.content)

    # Execute command
    try:
        if args.command == 'capture':
            if content_arg == "-":
                content_arg = sys.stdin.read().strip()
            if not content_arg:
                console.print("[red]❌ Error: Content required for capture command[/red]")
                console.print("[cyan]Examples:[/cyan]")
                console.print("  mentat capture 'I think AI will revolutionize education'")
                console.print("  mentat capture 'https://openai.com This new model looks promising'")
                console.print("  mentat capture 'How do I implement authentication in React?'")
                sys.exit(1)
            handle_capture(content_arg, args.user, args.web_search, current_model, openrouter_client, openai_client, db, last_displayed_items)

        elif args.command == 'view':
            if not content_arg:
                console.print("[red]❌ Error: Memory ID required for view command[/red]")
                sys.exit(1)
            try:
                memory_id = int(content_arg)
            except ValueError:
                console.print(f"[red]❌ Error: '{content_arg}' is not a valid memory ID[/red]")
                sys.exit(1)
            item = db.get_memory_by_id(memory_id, args.user)
            if not item:
                console.print(f"[red]❌ Memory {memory_id} not found[/red]")
                sys.exit(1)
            console.print(build_view_panel(item, memory_id))

        elif args.command == 'delete':
            if not content_arg:
                console.print("[red]❌ Error: Memory ID required for delete command[/red]")
                sys.exit(1)
            if not agent_flags.yes:
                console.print("[red]❌ Refusing noninteractive delete without --yes[/red]")
                sys.exit(1)
            try:
                memory_id = int(content_arg)
            except ValueError:
                console.print(f"[red]❌ Error: '{content_arg}' is not a valid memory ID[/red]")
                sys.exit(1)
            deleted_memory = db.delete_memory(memory_id, args.user)
            console.print(f"[green]✓ Memory {deleted_memory['id']} deleted successfully[/green]")

        elif args.command == 'mark':
            if not content_arg:
                console.print("[red]❌ Error: Todo ID required for mark command[/red]")
                sys.exit(1)
            todos = db.get_user_todos(args.user, status_filter=None)
            target = next((todo for todo in todos if todo.get("todo_id") == content_arg), None)
            if not target:
                console.print(f"[red]❌ Todo {content_arg} not found[/red]")
                sys.exit(1)
            new_status = "pending" if target.get("status") == "done" else "done"
            updated = db.update_todo_status_by_id(args.user, content_arg, new_status)
            if not updated:
                console.print(f"[red]❌ Todo {content_arg} not found[/red]")
                sys.exit(1)
            console.print(f"[green]✓ Todo {content_arg} marked {new_status}[/green]")

        elif args.command == 'chat':
            if not content_arg:
                console.print("[red]❌ Error: Chat query required[/red]")
                sys.exit(1)
            if not openrouter_client:
                console.print("[red]❌ Chat unavailable without API key.[/red]")
                sys.exit(1)

            last_displayed_items.clear()
            enhanced_chat = EnhancedChatSystem(db, openrouter_client)
            global_enhanced_chat = enhanced_chat
            if agent_flags.json_output:
                result = enhanced_chat.enhanced_chat_response(
                    content_arg,
                    args.user,
                    current_model,
                    update_ai_response_state,
                )
                print_json_response(
                    "chat",
                    chat_json_payload(result, global_enhanced_chat, content_arg, current_model),
                )
                return

            with show_thinking_spinner(CHAT_SPINNER_TEXT) as (progress, task):
                result = enhanced_chat.enhanced_chat_response(
                    content_arg,
                    args.user,
                    current_model,
                    update_ai_response_state,
                    status_callback=make_spinner_status_callback(progress, task),
                )
            print_enhanced_chat_reply(result, current_model, global_enhanced_chat, last_displayed_items)
            
        elif args.command == 'search':
            if not content_arg:
                if agent_flags.json_output:
                    json_error("search", "Search query required", "missing_query")
                    sys.exit(1)
                console.print("[red]❌ Error: Search query required[/red]")
                sys.exit(1)
            if agent_flags.json_output:
                if detect_ai_query(content_arg, current_model):
                    results = search_ai_responses(content_arg, args.user, db, openai_client)
                    mode = "ai_responses"
                else:
                    results = db.safe_memory_search(content_arg, args.user)
                    mode = "personal_knowledge"
                print_json_response(
                    "search",
                    {
                        "query": content_arg,
                        "mode": mode,
                        "results": [memory_json_item(item) for item in results],
                    },
                )
                return
            handle_search(content_arg, args.user, current_model, openrouter_client, openai_client, db, last_displayed_items)
            
        elif args.command == 'links':
            if agent_flags.json_output:
                links = db.search_for_links(args.user, content_arg)
                print_json_response(
                    "links",
                    {
                        "search_term": content_arg or None,
                        "links": [link_json_item(link_data) for link_data in links],
                    },
                )
                return
            handle_links(args.user, content_arg, db)
            
        elif args.command == 'link':
            if not content_arg:
                console.print("[red]❌ Error: URL required for /link command[/red]")
                console.print("[dim]Example: mentat.py link 'https://example.com This is interesting'[/dim]")
                sys.exit(1)
            from .commands import handle_link
            handle_link(content_arg, args.user, current_model, openrouter_client, openai_client, db, last_displayed_items)
            
        elif args.command == 'latest':
            try:
                limit = parse_latest_limit(content_arg)
            except ValueError as e:
                if agent_flags.json_output:
                    json_error("latest", str(e), "invalid_limit")
                    sys.exit(1)
                console.print(f"[red]❌ {e}[/red]")
                sys.exit(1)
            if agent_flags.json_output:
                memories = db.get_all_memories(args.user, limit=limit)
                print_json_response(
                    "latest",
                    {
                        "limit": limit,
                        "items": [memory_json_item(item) for item in memories],
                    },
                )
                return
            handle_latest(args.user, db, last_displayed_items, limit=limit)
            
        elif args.command == 'summary':
            days = int(content_arg) if content_arg and content_arg.isdigit() else args.days
            handle_summary(args.user, days, current_model, openrouter_client, db)
            
        elif args.command == 'project':
            if not content_arg:
                console.print("[red]❌ Error: Project name required[/red]")
                sys.exit(1)
            handle_project(content_arg, args.user, current_model, openrouter_client, db)
            
        elif args.command == 'tag':
            tags = args.tags or content_arg.split()
            if not tags:
                console.print("[red]❌ Error: Tags required for tag command[/red]")
                sys.exit(1)
            handle_tag(tags, args.user, db, last_displayed_items)

        elif args.command == 'todo':
            search_term, status_filter = parse_todo_args(content_arg)
            if agent_flags.json_output:
                from mentat.core.config import DEFAULT_TODO_FILTER
                effective_status = status_filter if status_filter is not None else DEFAULT_TODO_FILTER
                todos = db.get_user_todos(args.user, status_filter=effective_status)
                if search_term:
                    todos = [t for t in todos if search_term.lower() in t["action"].lower()]
                print_json_response(
                    "todo",
                    {
                        "search_term": search_term,
                        "status_filter": effective_status,
                        "todos": [todo_json_item(todo) for todo in todos],
                    },
                )
                return
            handle_todo(args.user, search_term, db, status_filter, last_displayed_items)

        elif args.command == 'model':
            handle_model_command(content_arg)

        elif args.command == 'synthesize':
            if not content_arg:
                console.print("[red]❌ Error: Topic required for synthesize command[/red]")
                sys.exit(1)
            handle_synthesize(args.user, content_arg, current_model, openrouter_client, openai_client, db)

        elif args.command == 'explore':
            if not content_arg:
                console.print("[red]❌ Error: Concept or number required for explore command[/red]")
                sys.exit(1)
            from .commands import handle_explore_web_command
            handle_explore_web_command(
                content_arg,
                args.user,
                db,
                openrouter_client,
                last_displayed_items,
                global_enhanced_chat,
                interactive=False,
            )

        elif args.command == 'explain':
            if not content_arg:
                console.print("[red]❌ Error: Concept or number required for explain command[/red]")
                sys.exit(1)
            from .commands import handle_explain_command
            handle_explain_command(content_arg, args.user, db, openrouter_client, global_enhanced_chat, last_displayed_items)

        elif args.command == 'connect':
            concepts = parse_connect_concepts(content_arg)
            if len(concepts) < 2:
                console.print("[red]❌ connect requires two concepts[/red]")
                console.print('[dim]Examples: mentat connect "machine learning" "mental health" or mentat connect machine learning | mental health[/dim]')
                sys.exit(1)
            from .commands import handle_connect_command
            handle_connect_command(concepts[0], concepts[1], args.user, openrouter_client, db, current_model)
            
    except KeyboardInterrupt:
        if agent_flags.json_output:
            json_error(args.command or "unknown", "Interrupted", "interrupted")
        else:
            console.print("\n[green]👋 Goodbye![/green]")
        sys.exit(0)
    except Exception as e:
        if agent_flags.json_output:
            json_error(args.command or "unknown", str(e), "unexpected_error")
        else:
            console.print(f"[bold red]❌ Unexpected error: {e}[/bold red]")
        sys.exit(1)

if __name__ == "__main__":
    main()
