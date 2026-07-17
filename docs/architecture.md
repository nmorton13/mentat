# Architecture

Mentat core is a local-first Python app with two main surfaces:

- CLI commands in `mentat/cli/`
- Voice and chat helpers in `mentat/chat/`

## Core Modules

- `mentat/cli/mentat.py` - interactive CLI entrypoint
- `mentat/cli/commands.py` - command handlers for capture, search, links, summaries, and related workflows
- `mentat/cli/display.py` - Rich terminal rendering
- `mentat/core/config.py` - environment and runtime model settings
- `mentat/core/llm.py` - chat-completion wrapper and provider routing
- `mentat/core/ai.py` - LLM, embedding, extraction, and capture-analysis helpers
- `mentat/core/database.py` - SQLite storage and search helpers
- `mentat/core/markdown_export.py` - Markdown export pipeline
- `mentat/chat/enhanced_chat.py` - context-aware chat over stored memories
- `mentat/chat/mentat_voice_session.py` - voice session orchestration
- `mentat/chat/tools/` - retained memory tool definitions
- `mentat/concepts/` - concept exploration and display helpers
- `mentat/api/enhanced_chat_service.py` - shared service adapter for chat parity, not a standalone public server surface

## Data Flow

1. The user captures content through the CLI.
2. Mentat analyzes the content with the configured LLM.
3. The database stores the original content, tags, metadata, and embeddings.
4. Optional Markdown export writes a readable archive.
5. Search, chat, project analysis, and concept exploration retrieve context from the same core store.

Hosted LLM routes receive the prompt content required for their task. Normal
chat can include locally retrieved memories in that prompt. Local-first refers
to storage and user control over routing, not a claim that hosted routes keep
all content on-device.

## Boundary

The core app intentionally excludes the old Telegram runtime, scheduler, digest/nudge systems, local command/file tools, and optional MCP experiments. Those remain recoverable from archive history rather than being part of the release surface.
