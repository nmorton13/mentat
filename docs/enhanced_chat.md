# Enhanced Chat System

This document explains how the Enhanced Chat system builds context, retrieves memories, and generates responses. For implementation details, see `mentat/chat/enhanced_chat.py`.

## Purpose

`EnhancedChatSystem` builds chat answers by combining:
- Semantic + keyword search over your memories
- Entity-based connections
- Temporal intent understanding
- User pattern analysis
- AI synthesis with transparent source attribution

## 🧭 High-Level Flow

1. **Structured Query Check**
   - If the query looks like a structured request (e.g., todo lists), use specialized logic instead of LLM synthesis.

2. **Context Gathering** (`_gather_comprehensive_context`)
   - Extract entities from the query.
   - Detect temporal intent and filter by time range if needed.
   - Run **hybrid search** (semantic + keyword) if no temporal filter is used.
   - Find entity connections (shared entities in metadata).
   - Build source attribution metadata.

3. **Corpus Pattern Signals** (`_identify_user_patterns`)
   - Analyze command types, tags, and repeated entities.
   - Identify lightweight recurring vocabulary and technology signals.

4. **Intent Detection** (`_detect_intent`)
   - Classifies intent into modes like `standard`, `research`, `decision`, `explore`, or `quick`.
   - Intent controls prompt style and web-backed model routing for research.

5. **Response Generation** (`_generate_enhanced_response`)
   - Builds a rich context prompt that includes:
     - memory previews
     - tags
     - timestamps
     - source types (semantic/entity)
     - temporal context (if relevant)
   - Sends it to the current model with a matching system prompt.

6. **Exploration References** (`_prepare_exploration_references`)
   - Builds explorable concepts from the already-gathered context.
   - Keeps the AI response text unchanged.
   - Shows numbered concepts in the follow-up card for `/view`, `/explore`, and `/synthesize`.

7. **Follow-up Suggestions** (`_generate_follow_up_suggestions`)
   - Generates small, actionable next steps for the user.

## 🔎 Hybrid Search (Chat)

Enhanced chat uses a hybrid strategy (`_hybrid_search`) that merges:
- **Semantic search** via embeddings (`brute_sem_search`)
- **Keyword search** via FTS5 (`safe_memory_search`)

**Ranking formula (conceptual):**

```
score = {
  semantic_similarity,                 # 1 - cosine_distance
  KEYWORD_MATCH_BASELINE_SCORE         # constant baseline for keyword hits
}

final_score = max(semantic_score, keyword_score)
```

Additional details:
- By default, primary results grow to 25, internal candidates grow to 75, and the
  prompt ceiling grows to 50 as memories are added.
- Semantic candidates are fetched with an internal multiplier: `internal_k = k * internal_multiplier`.
- Explicit `CHAT_HYBRID_SEARCH_K`, `HYBRID_SEARCH_INTERNAL_MULTIPLIER`, and
  `CHAT_CONTEXT_LIMIT` values override their corresponding automatic values.
- Results below `CHAT_MIN_SIMILARITY` are excluded from semantic candidates.
- Keyword matches get a fixed baseline score (`KEYWORD_MATCH_BASELINE_SCORE`).
- If a memory appears in both sets, the higher score wins and `why_matched` is updated.
- Results are sorted by `final_score` (descending) and truncated to `k`.

## Memory Selection And Formatting

Memories marked as AI-derived responses are removed from ordinary semantic and
entity context before prompt construction. They can be searched explicitly as
AI references, but they are not treated as evidence of the user's own thinking.

When building the context prompt, the system uses length-aware truncation:

- If content is short → include in full
- If `ai_summary` exists and content is long → use the summary
- Otherwise → truncate with `standardize_truncation`

This logic lives in `_format_memory_content` and keeps prompts token-efficient.

## Concept & Reference System

After the model responds, the system:

- Reuses query entities and retrieved-memory tags as concept candidates
- Stores references in session state for `/view` and `/explore`
- Shows numbered concepts in the follow-up card instead of mutating the response text

### 🧭 Exploration Candidate Priority

Exploration references are prioritized from context signals:

- Query entities first, because they reflect what the user explicitly asked about.
- Repeated tags from retrieved memories next, because they reflect the context Mentat actually used.
- Shared entities from connected memories after that, as useful secondary associations.

## 📌 Configuration Knobs (Config)

Key settings in `mentat/core/config.py` that affect enhanced chat:

- `CHAT_HYBRID_SEARCH_K`, `CHAT_MIN_SIMILARITY`
- `HYBRID_SEARCH_INTERNAL_MULTIPLIER`
- `KEYWORD_MATCH_BASELINE_SCORE`
- `CHAT_CONTEXT_LIMIT`, `CHAT_PREVIEW_LENGTH`, `CHAT_CONTENT_TRUNCATION_LENGTH`
- `ENTITY_SEARCH_LIMIT`, `ENTITY_CONNECTION_PREVIEW_LENGTH`
- `ENTITY_EXTRACTION_PROVIDER`, `ENTITY_EXTRACTION_MODEL`
- `MAX_TOTAL_REFERENCES`

Entity extraction uses per-feature LLM routing. If `ENTITY_EXTRACTION_PROVIDER` is unset, it follows `HELPERS_PROVIDER`/`HELPERS_MODEL` when those shared defaults are set, then falls back to the active normal chat client/model. Set `ENTITY_EXTRACTION_PROVIDER=openrouter` plus `ENTITY_EXTRACTION_MODEL=...` to force a reliable OpenRouter model for structured entity JSON, `ENTITY_EXTRACTION_PROVIDER=local` to use the shared `LOCAL_*` provider, or `ENTITY_EXTRACTION_PROVIDER=ollama` to use native Ollama.

> **Legacy setting:** `FAST_ENTITY_MODEL` is superseded.
>
> It no longer controls active entity extraction. It is documented only for migration from older `.env` files. For the old “fast separate model” behavior, configure `ENTITY_EXTRACTION_PROVIDER` and `ENTITY_EXTRACTION_MODEL`; otherwise entity extraction follows `HELPERS_*` when configured, then normal chat.

## 🔗 Related Files

- `mentat/chat/enhanced_chat.py` — main logic
- `mentat/core/database.py` — search + entity connections
- `mentat/core/ai.py` — entity extraction + embeddings
- `mentat/chat/prompts.py` — system prompt variants
- `mentat/chat/temporal.py` — temporal intent detection

---

If you update search behavior, context logic, or exploration-reference formatting, make sure to reflect the changes here.
