# Architecture

Mentat core is a local-first Python app with two main surfaces:

- CLI commands in `mentat/cli/`
- Voice and chat helpers in `mentat/chat/`

## Core Modules

- `mentat/cli/mentat.py` - interactive CLI entrypoint
- `mentat/cli/commands.py` - command handlers for capture, search, links, summaries, reflection, and related workflows
- `mentat/cli/display.py` - Rich terminal rendering
- `mentat/core/config.py` - environment and runtime model settings
- `mentat/core/llm.py` - chat-completion wrapper and provider routing
- `mentat/core/prompts.py` - product prompts, including the dedicated MENTAT reflection identity and evidence boundaries
- `mentat/core/ai.py` - LLM, embedding, extraction, and capture-analysis helpers
- `mentat/core/database.py` - SQLite storage and search helpers
- `mentat/core/markdown_export.py` - Markdown export pipeline
- `mentat/core/journal_transfer.py` - Journal Markdown v1 snapshot export/import
- `mentat/core/okf_transfer.py` - OKF v0.2 export, validation, and import
- `mentat/chat/enhanced_chat.py` - context-aware chat over stored memories
- `mentat/chat/mentat_voice_session.py` - voice session orchestration
- `mentat/chat/tools/` - retained memory tool definitions
- `mentat/concepts/` - concept exploration and display helpers
- `mentat/api/enhanced_chat_service.py` - shared service adapter for chat parity, not a standalone public server surface

## Data Flow

1. The user captures content through the CLI.
2. Mentat analyzes the content with the configured LLM.
3. The database stores the original content, tags, metadata, and embeddings.
4. Optional Journal Markdown and OKF exporters write local archives.
5. Search, chat, project analysis, reflection, and concept exploration retrieve context from the same core store.

Reflection uses a read-only archive view of the selected user's memories,
excludes saved AI responses, and deterministically samples across time and
content types under an automatic corpus-size and prompt-character budget. It
then makes one plain-text completion through the active chat route without
writing the answer back to SQLite or a file.

Hosted LLM routes receive the prompt content required for their task. Normal
chat can include locally retrieved memories in that prompt. Reflection can
include a broader cross-timeline selection, up to 100 memories for large
corpora. Local-first refers to storage and user control over routing, not a
claim that hosted routes keep all content on-device.

## Boundary

The core app intentionally excludes the old Telegram runtime, scheduler, digest/nudge systems, local command/file tools, and optional MCP experiments. Those remain recoverable from archive history rather than being part of the release surface.
