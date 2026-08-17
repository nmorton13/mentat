# Changelog

All notable changes to Mentat are documented here.

## 0.9.2 - 2026-08-17

### Changed

- Made actionable-item capture selective: new memories create at most one
  broader learning, inquiry, practice, experiment, or decision item, backed by
  an exact quote from the user's words.
- Stopped generating and displaying priority for newly captured actionable
  items while retaining compatibility with existing item metadata, `/todo`,
  `/mark`, filters, display numbers, statuses, and durable IDs.
- Simplified hybrid-search result merging around durable memory IDs, reducing
  redundant work while preserving keyword and semantic search behavior.

### Fixed

- Prevented tentative ideas, assistant suggestions, and routine project work
  such as releases, screenshots, integrations, and implementation tasks from
  being promoted into actionable items.

## 0.9.1 - 2026-08-06

### Added

- Added one-shot `/reflection` and `mentat reflection` output that uses the
  active model to identify one difficult but constructive pattern across a
  deterministic, automatically scaled cross-section of personal memories.

### Safety

- Reflection excludes saved AI responses, treats captured prompt-like text as
  evidence rather than instructions, requires counterevidence, and never saves
  its generated answer.

## 0.9.0 - 2026-08-06

### Added

- Added explicit Journal Markdown v1 snapshot export and duplicate-safe import,
  including dry-run and JSON result modes.
- Added Open Knowledge Format v0.2 export, validation, import, and opt-in
  automatic writing with one concept file per memory.
- Added independent Journal, OKF, both, or off choices to guided setup, plus
  masked configuration display and writable-path diagnostics.
- Added Venice AI as a named OpenAI-compatible chat and helper provider with
  guided setup, `/model venice`, and provider diagnostics.

### Changed

- Declared PyYAML directly for safe OKF frontmatter parsing.
- Documented Journal v1 as the stable human-readable archive and OKF as the
  portable round-trip format.
- Retained and reverified the first-use local embedding-model download,
  Hugging Face cache, and offline-after-download documentation.

### Fixed

- Rendered `/explore` concept-tree Markdown without exposing formatting markers
  or collapsing the tree layout.
- Normalized matching outer quotes in `/explore` and `/explain`, honored the
  configured exploration depth, and clarified that the concept limit applies
  to each parent.
- Routed `/explain` through the active chat model instead of sending a
  hardcoded hosted model name to local Ollama.

### Safety

- Manual exports refuse nonempty destinations.
- OKF imports preserve unknown metadata but never execute attested
  computations, executors, attesters, SQL, scripts, or referenced code.
- Personal OKF actor identities remain in the ignored local `.env`; no personal
  actor is shipped in public defaults.

## 0.8.2 - 2026-07-17

### Changed

- Documented how Mentat becomes more useful as its selected memory grows and
  added a review-first workflow for existing Markdown, Obsidian, and text notes.

### Fixed

- Prevented the `/mark` notation in interactive help from enabling
  strikethrough formatting on the commands that followed it.

## 0.8.1 - 2026-07-17

### Changed

- Restored the MENTAT acronym in the interactive CLI banner.
- Refreshed the curated OpenRouter model list and default against the live
  catalog.

## 0.8.0 - 2026-07-12

### Added

- Agent-friendly JSON commands, durable memory and todo identifiers, stdin
  capture, and explicit noninteractive deletion confirmation.
- Route-aware OpenRouter, OpenAI-compatible, local, and native Ollama model
  support with shared and task-specific helper routing.
- Guided `mentat config init`, masked `config show`, and configuration
  diagnostics through `config doctor`.
- Human-readable Markdown export, voice sessions, temporal retrieval, and
  concept exploration in the retained core application.

### Changed

- Defined Mentat as an opinionated system for selective thought capture and
  reflection rather than comprehensive life logging.
- Kept saved AI responses out of ordinary memory context while retaining
  explicit AI-reference search.
- Removed legacy Telegram, scheduler, digest, email-tool, broad server, and
  experimental runtime surfaces from the public core.
- Simplified `/link` to store only the supplied URL and comment without fetching
  or ingesting the linked page.

### Fixed

- Preserved actionable URL captures during web enrichment.
- Prevented duplicate full-text index rows for duplicate memories.
- Improved structured JSON fallback for OpenAI-compatible endpoints.
- Made shared memory tools respect native Ollama routing and truthful analysis
  metadata.
- Prevented `config doctor` request failures from exposing endpoint URLs,
  embedded credentials, or query tokens.
- Restricted sensitive logs, transcripts, Markdown exports, runtime settings,
  and session databases to owner-only file and directory permissions.
- Replaced ambiguous colon-joined chat session keys with collision-safe,
  unambiguously encoded keys.

### Distribution

The `0.8.0` release supports the documented clone-and-run source workflow.
Portable wheel installation and platform-specific user data directories remain
planned work for a later pre-1.0 release.
