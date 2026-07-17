# Mentat

An opinionated memory system for thoughts that keep tugging at you.

Mentat is a local-first CLI app for selectively saving thoughts, links, notes, and research, then surfacing them later through hybrid search, semantic connections, temporal queries, and AI-assisted chat.

## Why Mentat?

I built Mentat because most knowledge tools do not match how I actually think and work. Tabs pile up, links get
bookmarked randomly, podcast notes turn into reminders, and good ideas end up scattered across apps. Highly
structured tools can feel like extra work, while loose note dumps become hard to search later.

Mentat is not meant to capture your whole life. It is for the thoughts that keep coming back after the first moment
has passed: an idea from a walk, a quote that keeps working on you, a research thread you want to reconnect later, a
decision whose context matters, or a messy note that might become clearer after it sits for a few days. Mentat can add
tags, entities, summaries, todos, and connections later, so useful structure can emerge without requiring perfect
organization up front.

My goal was one terminal and agent-friendly memory system for people who think in multiple modes - sometimes
structured, sometimes messy, sometimes searching for a specific thing, and sometimes just exploring what they
already know.

## What Belongs In Mentat?

Use Mentat for ideas with some gravity: thoughts that survive the noise, keep showing up, or may connect to other
work later. Skip the disposable stuff. Mentat is intentionally more selective than a life logger and more opinionated
than a generic notes folder.

## Core Features

- AI-assisted `/capture` with entity, theme, tag, and action-item extraction
- Optional `/capture -w` web enrichment for selected entities that are novel or stale in your memory; useful for current, niche, ambiguous, or model-unknown terms
- Hybrid search across saved memories with keyword, semantic, and entity-aware matching
- Natural language temporal search such as "what was I thinking about last week?"
- Context-aware CLI chat over your memory corpus
- Voice sessions through the CLI `/voice` command
- Markdown export for human-readable, Obsidian-friendly archives

## Install

```bash
git clone https://github.com/nmorton13/mentat.git
cd mentat
uv sync
```

Run the guided setup:

```bash
uv run mentat config init
```

The setup command creates or safely updates `.env`, configures OpenRouter,
Ollama, or another OpenAI-compatible endpoint, and activates the selected
model route. Run it again later to change the basic setup. Advanced settings
can still be edited directly in `.env`.

The `0.8.x` release supports this clone-and-run source workflow. Portable wheel
installation and platform-specific user data directories are planned for a
later pre-1.0 release.

Voice is optional. Install its local audio dependencies with:

```bash
uv sync --extra voice
```

## Run

```bash
uv run mentat
```

## Core CLI Commands

The central loop is capture, return, and reconnect:

- `/capture <content>` - analyze and save content; extracts entities automatically
- `/capture -w <content>` - capture with web enrichment for selected novel/stale entities to improve tagging and classification
- `/search <query>` - search saved memories
- `/chat <query>` - ask a context-aware question over your memories
- `/latest [count]` - view recent captures
- `/project <name>` - analyze project-related content

Additional ways to work with selected memories:

- `/voice` - start a voice session
- `/links` - view saved links
- `/link <url> [comment]` - save a link and, ideally, why it matters to you; Mentat does not fetch the page
- `/todo` - show extracted actionable items
- `/tag <tags>` - search by tags
- `/delete <number>` - remove a numbered result after confirmation
- `/model` - inspect/switch chat routes and models (`/model 1`, `/model local`, `/model ollama`, `/model openrouter <id>`)
- `/summary [days]` - generate an activity summary
- `/synthesize <topic>` - combine related notes into a structured synthesis
- `/save` - capture a valuable AI response as a memory
- `/help` - show available commands

## Agent-Friendly Top-Level Commands

Top-level commands support shell automation without entering the interactive REPL:

```bash
uv run mentat latest 25 --json
uv run mentat search "machine learning" --json
uv run mentat links "research" --json
uv run mentat todo pending --json
uv run mentat chat "what changed recently?" --json
uv run mentat capture -
uv run mentat view 123
uv run mentat delete 123 --yes
uv run mentat mark todo_abc123
uv run mentat config show
uv run mentat config doctor
```

JSON mode prints a single JSON object on stdout with a schema version, command name, success flag, and data or error payload.

Mentat can also serve as durable memory behind a conversational or voice-capable
agent. After talking through an idea with Codex or another agent that has access
to the CLI, you can say, "Capture this in Mentat." The agent can preserve your
words directly or, when you explicitly ask, prepare a summary and capture that.
Long voice notes and agent-prepared text can be passed through `mentat capture -`.
The same agent can query your memories: "What does Mentat think about X?" or
"What connections does Mentat see between X and Y?" can be handed to
`mentat chat "..." --json` and returned in the conversation. These answers
synthesize the memories you selected; they are not a complete record or Mentat's
own beliefs.

## Local-First And Privacy

Memories, embeddings, runtime settings, and Markdown exports are stored locally.
When you choose OpenRouter, OpenAI, xAI, or another hosted endpoint, the content
needed for that request is sent to that provider. Chat requests may include
retrieved memories as context. Use Ollama or another local endpoint for routes
that should remain on your machine, and inspect effective routing with
`mentat config show` or `/model`.

## Data

Mentat stores memories in SQLite and can export captured content to Markdown files under `data/markdown/`. Local data directories are not required for a fresh install and should be treated as personal runtime data rather than project source.

## Documentation

- [Command Reference](docs/commands.md)
- [Configuration Guide](docs/configuration.md)
- [Tools & Capabilities](docs/tools.md)
- [Temporal Search](docs/temporal-search.md)
- [Workflows & Examples](docs/examples.md)
- [Contributing](docs/contributing.md)
