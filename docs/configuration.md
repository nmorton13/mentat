# Configuration

Mentat reads configuration from environment variables, usually through a project-local `.env` file.

For the common setup path, run:

```bash
mentat config init
```

The guided setup creates or updates `.env`, preserves comments and unrelated
settings, and activates the selected chat route. It can be run again later with
the current values offered as defaults. Use `mentat config show` for a masked
summary and `mentat config doctor` to check required credentials, local model
availability, export paths, and optional voice configuration.

The settings below remain available for advanced routing and direct editing.

## Required And Optional Keys

```env
# Required for most LLM chat/capture/summary features
OPENROUTER_API_KEY=your_openrouter_key

# Optional: OpenAI-only features such as OpenAI realtime voice or direct OpenAI routing
OPENAI_API_KEY=your_openai_key
```

Mentat uses OpenRouter for most hosted LLM chat/capture flows. Semantic embeddings are local sentence-transformers by default, so no API key is required for embeddings.

## User And Models

```env
MENTAT_USER_ID=mentat
OPENROUTER_MODEL=x-ai/grok-4.5
ONLINE_MODEL=openai/gpt-chat-latest
MODEL_CONFIG_PATH=config/models.json
```

`MODEL_CONFIG_PATH` points to the curated saved OpenRouter model list used by the CLI model selector.
`OPENROUTER_MODEL` is the OpenRouter fallback when no runtime route/model has been selected.
`ONLINE_MODEL` is optional and is only for explicit web-backed/online features that use OpenRouter's `openrouter:web_search` server tool. It does not control normal chat, ConceptExplorer, or entity extraction. Online/web calls always require `OPENROUTER_API_KEY` and route through OpenRouter; they never send OpenRouter web-search tools to a local `CHAT_BASE_URL`. If `ONLINE_MODEL` is unset, Mentat uses the active chat model when chat is already routed through OpenRouter, or `OPENROUTER_MODEL` when normal chat is local/custom.

To route normal chat/capture/summaries to a local or OpenAI-compatible server, set the optional `CHAT_*` values:

```env
CHAT_BASE_URL=http://localhost:1234/v1
CHAT_API_KEY=local
CHAT_MODEL=qwen-local
ONLINE_MODEL=openai/gpt-chat-latest
```

If `CHAT_*` values are unset, Mentat behaves as before and uses OpenRouter for normal LLM calls. If `CHAT_BASE_URL` is set without `CHAT_API_KEY`, Mentat uses `local` as a harmless placeholder API key for local servers that require the field but do not validate it.

`CHAT_*` values are defaults. Once you use `/model`, the runtime chat route in `data/runtime_settings.json` wins over `.env`: saved model selections route through OpenRouter, and `/model local` routes through the configured local endpoint.

To route normal chat through native Ollama, use `OLLAMA_*` and `/model ollama [model]`:

```env
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.2
OLLAMA_THINK=false
```

The Ollama route uses Ollama's native `/api/chat` endpoint. Use `CHAT_*` or `LOCAL_*` only for OpenAI-compatible local servers.

## Per-Feature LLM Routing

Some features can use their own provider/model instead of always following normal chat. This is useful when normal chat is local but a structured task needs a reliable OpenRouter model, or when a privacy-sensitive feature should stay local.

Provider routing chooses **where** the request goes. The model string only chooses the model at that provider.

Supported providers:

- `chat` — use the active normal chat client/model.
- `openrouter` — use `OPENROUTER_API_KEY` + `OPENROUTER_BASE_URL` and the feature model or `OPENROUTER_MODEL`.
- `local` — use `LOCAL_BASE_URL`/`LOCAL_API_KEY` and the feature model or `LOCAL_MODEL`.
- `ollama` — use native Ollama `/api/chat` with the feature model or `OLLAMA_MODEL`.
- `custom` — use feature-specific `<FEATURE>_BASE_URL`, `<FEATURE>_API_KEY`, and `<FEATURE>_MODEL`.

When a task provider is blank, Mentat falls back to `HELPERS_PROVIDER`/`HELPERS_MODEL` if set, then to `chat`.

Shared local provider settings:

```env
LOCAL_BASE_URL=http://localhost:1234/v1
LOCAL_API_KEY=local
LOCAL_MODEL=google/gemma-4-12b-qat
```

`LOCAL_*` does not replace `CHAT_*`. Use `CHAT_*` when normal Mentat chat should be local. Use `LOCAL_*` to define a reusable local provider for feature-specific routes.

Use `/model` to switch the **active chat route and model** and inspect resolved routes. Routes with `PROVIDER=chat` follow the active chat route selected by `/model`. Routes with explicit providers/models, such as `CONCEPT_EXPLORATION_PROVIDER=openrouter` plus `CONCEPT_EXPLORATION_MODEL=...`, are controlled by `.env` and do not change when you run `/model`.

Common `/model` forms:

```bash
/model 1                              # saved model number -> OpenRouter route
/model grok-4.5                       # saved label -> OpenRouter route
/model openrouter x-ai/grok-4.5       # pasted OpenRouter model id
/model local                          # configured local route/model
/model local qwen-local               # configured local endpoint with explicit model
/model ollama                         # configured native Ollama route/model
/model ollama llama3.2                # native Ollama route with explicit model
```

The active route is saved in `data/runtime_settings.json`:

```json
{
  "chat_provider": "openrouter",
  "current_model": "x-ai/grok-4.5"
}
```

or:

```json
{
  "chat_provider": "local",
  "current_model": "qwen-local"
}
```

The startup panel shows a compact route summary. `/model` shows the full route table for chat, ConceptExplorer, entity extraction, concept connection, capture analysis, todo extraction, temporal intent, and online/web-backed calls, including endpoint/base URL.

### ConceptExplorer

```env
CONCEPT_EXPLORATION_PROVIDER=
CONCEPT_EXPLORATION_MODEL=
CONCEPT_EXPLORATION_BATCH_SIZE=4
CONCEPT_EXPLORATION_DEFAULT_DEPTH=2
CONCEPT_EXPLORATION_MAX_CONCEPTS=4
```

If `CONCEPT_EXPLORATION_PROVIDER` is unset, it follows `HELPERS_PROVIDER`/`HELPERS_MODEL` when those shared helper defaults are set. Otherwise, it behaves as `chat` and follows the active model shown in the Mentat prompt. `/explore` prints the resolved provider, model, depth, max concepts, and batch size before building the tree.

Example: normal chat local, helper tasks through OpenRouter:

```env
CHAT_BASE_URL=http://localhost:1234/v1
CHAT_API_KEY=local
CHAT_MODEL=google/gemma-4-12b-qat

HELPERS_PROVIDER=openrouter
HELPERS_MODEL=google/gemini-3.1-flash-lite
```

### Entity Extraction

```env
ENTITY_EXTRACTION_PROVIDER=
ENTITY_EXTRACTION_MODEL=
```

If unset, entity extraction follows `HELPERS_*`, then normal chat. To force a fast OpenRouter model for structured entity JSON:

```env
ENTITY_EXTRACTION_PROVIDER=openrouter
ENTITY_EXTRACTION_MODEL=openai/gpt-4o-mini
```

### Concept Connection

`/connect` relationship analysis uses its own route:

```env
CONCEPT_CONNECTION_PROVIDER=
CONCEPT_CONNECTION_MODEL=
```

If unset, concept connection follows `HELPERS_*`, then normal chat. To force OpenRouter:

```env
CONCEPT_CONNECTION_PROVIDER=openrouter
CONCEPT_CONNECTION_MODEL=google/gemini-3.1-flash-lite
```

Additional structured tasks also support the same provider/model pattern. Their fallback order is: task-specific provider/model, then `HELPERS_PROVIDER`/`HELPERS_MODEL`, then normal chat.

```env
HELPERS_PROVIDER=openrouter
HELPERS_MODEL=google/gemini-3.1-flash-lite
CAPTURE_ANALYSIS_PROVIDER=
CAPTURE_ANALYSIS_MODEL=
TODO_EXTRACTION_PROVIDER=
TODO_EXTRACTION_MODEL=
TEMPORAL_INTENT_PROVIDER=
TEMPORAL_INTENT_MODEL=
```

> **Legacy setting:** `FAST_ENTITY_MODEL` is superseded.
>
> It no longer controls active entity extraction or concept connection behavior. It is mentioned only so older `.env` files are easy to migrate. If you previously relied on its default fast OpenRouter model, set `ENTITY_EXTRACTION_PROVIDER`/`ENTITY_EXTRACTION_MODEL` explicitly. Otherwise, entity extraction follows `HELPERS_*` when configured, then the active normal chat model/client.

## Web Features And Model Routing

Mentat has two web-access paths plus local link capture:

| Feature | What it does | Model/config path |
| --- | --- | --- |
| `/capture -w <content>` | Captures your note, extracts selected novel/stale entities, performs web enrichment for those entities, and uses that context to improve tags/classification. | Uses OpenRouter-backed web enrichment during capture; it does not replace the saved note with webpage content. |
| `/link <url> [comment]` | Saves the URL and your optional comment as a searchable memory without fetching the page. | No request is made to the linked site; an agent can provide a summary as the comment when wanted. |
| Online/research chat calls | Uses OpenRouter's web-search capable online path for explicit web-backed answers. | Controlled by `ONLINE_MODEL`; always requires `OPENROUTER_API_KEY` and routes through OpenRouter. |

Use `/capture -w` for context around terms in your own note, `/link` to preserve a URL and your reason for keeping it, and `ONLINE_MODEL` only to choose the model for explicit online/web-backed LLM calls.

## Search And Retrieval

```env
CHAT_MEMORY_K=10
SEARCH_RESULTS_K=8
PROJECT_ANALYSIS_K=25
SYNTHESIS_K=15
CHAT_MIN_SIMILARITY=0.2
SEMANTIC_SEARCH_MIN_SIMILARITY=0.1
```

Enhanced chat automatically grows into its standard retrieval limits as memories
are added:

| Saved memories | Primary results | Internal candidates | Prompt ceiling |
| ---: | ---: | ---: | ---: |
| 10 | 10 | 10 | 10 |
| 25 | 25 | 25 | 25 |
| 50 | 25 | 50 | 50 |
| 75 or more | 25 | 75 | 50 |

The automatic values are deterministic. They depend only on the number of saved
memories and do not add another model call or query router. To override any part
of the automatic tuning, set its numeric value explicitly:

```env
CHAT_HYBRID_SEARCH_K=25
HYBRID_SEARCH_INTERNAL_MULTIPLIER=3.0
CHAT_CONTEXT_LIMIT=50
```

Unset values remain automatic, so one setting can be overridden without requiring
the others. `CHAT_MIN_SIMILARITY` continues to control semantic match strictness.

## Database

```env
DATABASE_PATH=data/mentat.db
DATABASE_MAX_CONNECTIONS=5
DATABASE_TIMEOUT=30
DATABASE_CHECK_SAME_THREAD=false
```

Relative `DATABASE_PATH` values are resolved from the project root.

## Markdown Export

```env
MARKDOWN_EXPORT_ENABLED=true
MARKDOWN_EXPORT_PATH=data/markdown
```

Markdown exports are human-readable backups of captured memories and can be read by tools like Obsidian.
Relative `MARKDOWN_EXPORT_PATH` values are resolved from the project root.

## Voice

```env
# Provider and credentials
VOICE_PROVIDER=openai
OPENAI_API_KEY=your_openai_key
XAI_API_KEY=your_xai_key

# Realtime model settings
VOICE_REALTIME_URL=
VOICE_MODEL=gpt-realtime-mini
VOICE_TRANSCRIBE_MODEL=
VOICE_NAME=alloy

# Capture behavior
VOICE_AUTO_CAPTURE=false
VOICE_CAPTURE_TYPE=voice_conversation
VOICE_CAPTURE_PROMPT_TIMEOUT=30
VOICE_SUGGEST_CAPTURES=true
```

These settings control CLI voice-session provider selection, realtime model behavior, and memory capture behavior. Set `VOICE_PROVIDER=xai` with `XAI_API_KEY` to use xAI realtime voice.

Example xAI voice configuration:

```env
VOICE_PROVIDER=xai
XAI_API_KEY=your_xai_key
VOICE_MODEL=replace_with_xai_realtime_model
VOICE_NAME=Ara
VOICE_AUTO_CAPTURE=false
```

Use the current xAI realtime model name available to your account for `VOICE_MODEL`.
