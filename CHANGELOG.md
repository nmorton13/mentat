# Changelog

All notable changes to Mentat are documented here.

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
