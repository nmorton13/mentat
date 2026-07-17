# Security Policy

## Supported Release

Security fixes are applied to the latest `0.8.x` release while Mentat remains
in its pre-1.0 release cycle.

## Reporting A Vulnerability

Report security issues privately to `nathan.morton+mentat@gmail.com`. Do not
open a public issue for a suspected credential leak, arbitrary file access,
unsafe command execution, or exposure of personal memory data.

Include the affected version, a concise reproduction, and the impact. Never
attach a real Mentat database, `.env` file, API key, private memory, or provider
response containing personal context. Use synthetic examples.

## Data And Provider Boundary

Mentat stores its SQLite database, embeddings, runtime settings, and Markdown
exports locally. Requests routed to hosted LLM providers send the prompt data
needed for that feature; chat prompts can contain retrieved memories. Users who
need an on-device route should configure Ollama or another local endpoint and
verify effective routes with `mentat config show` or `/model`.
