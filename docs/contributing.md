# Contributing to Mentat

Mentat is an opinionated memory system for selective capture, return,
reflection, and connection. Contributions should strengthen that loop without
turning the default product into comprehensive activity logging or a broad
automation platform.

## Before You Start

- Open an issue before beginning a substantial feature or architectural change.
- Keep changes focused and preserve existing behavior unless the change is
  intentional and documented.
- Use synthetic content in tests and examples. Never commit personal memories,
  `.env` files, databases, logs, provider responses, or credentials.

## Development Setup

Mentat requires Git and `uv`. The project targets Python 3.12; `uv` can install
and manage that Python version.

```bash
git clone https://github.com/YOUR_USERNAME/mentat.git
cd mentat
uv python install 3.12
uv sync --python 3.12 --group dev
```

Most tests do not require a configured LLM account. To exercise the application
against a real provider or local model, run:

```bash
uv run mentat config init
uv run mentat config doctor
```

Voice support is optional and requires the native dependencies described in the
[installation guide](installation.md#optional-voice-support). To match the full
CI environment after installing those dependencies:

```bash
uv sync --python 3.12 --group dev --extra voice
```

## Project Layout

- `mentat/cli/` contains the interactive and top-level command surfaces.
- `mentat/core/` contains configuration, storage, LLM routing, analysis, and
  Markdown export.
- `mentat/chat/` contains memory-aware chat, temporal handling, tools, and
  voice-session orchestration.
- `mentat/concepts/` contains concept exploration and display helpers.
- `tests/` mirrors the supported behavior and public command contracts.
- `docs/` contains current user and contributor documentation.

See [Architecture](architecture.md) for the runtime data flow and product
boundary.

## Making A Change

1. Create a focused branch from `main`.
2. Read the implementation, its callers, and the relevant tests before editing.
3. Add or update tests that express the behavior the change is meant to
   preserve.
4. Update CLI help, configuration examples, and documentation when a public
   surface changes.
5. Keep machine-readable output stable: JSON commands must emit one valid JSON
   object on stdout and retain durable identifiers.
6. Keep saved AI responses out of ordinary personal-memory context unless a
   future change explicitly revisits that product boundary.

## Verification

Run focused tests while developing, then run the release-relevant checks before
opening a pull request:

```bash
uv lock --check
uv run --group dev pytest
uv build --sdist
```

The dev group includes pytest and the focused Pylint check exercised by the
test suite. CI also installs the `voice` extra and checks the tracked tree and
source distribution for common runtime, credential, and cache artifacts.

If a check cannot be run locally, explain why in the pull request.

## Pull Requests

Keep each pull request narrow and describe:

- the user-visible behavior and why it belongs in Mentat;
- the tests and manual checks performed;
- any configuration, migration, privacy, or provider-routing impact;
- any relevant check that was skipped.

The repository's pull request template contains the final scope, verification,
and privacy checklist. Use [GitHub Issues](https://github.com/nmorton13/mentat/issues)
for bug reports, feature proposals, and development questions.
