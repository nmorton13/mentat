# Temporal Search Guide

Use temporal search when you remember roughly when you captured a thought but
not the words you used.

## What Temporal Answers Mean

Mentat searches the memories you chose to preserve in a time window. It does
not reconstruct everything that happened, everything you did, or objective
productivity. A sparse answer may simply mean that few thoughts from that
period were worth capturing.

Ask:

```bash
/chat what was I thinking about last week?
/chat what did I preserve about the migration last month?
/chat which questions kept appearing in my spring notes?
```

Be cautious with questions such as "what happened last month?" The answer can
only describe the selected record, not the missing parts of the month.

## Supported Time Patterns

Mentat combines deterministic date parsing with an LLM fallback for less common
phrasing.

### Relative Periods

```bash
/chat what thoughts did I capture yesterday?
/chat what was I wrestling with last week?
/chat what did I preserve recently?
/chat what questions appeared last month?
/chat what was in my notes this time last year?
```

`last week` means the previous complete Monday-through-Sunday week. `last
month` means the previous complete calendar month.

### Months And Years

```bash
/chat what did I preserve about local models last January?
/chat which research questions appeared in March?
/chat my selected database notes from September 2025
```

### Seasons

```bash
/chat what garden lessons did I save last spring?
/chat which system-design questions appeared during winter?
/chat what plans have I captured for this summer?
```

Mentat treats spring as March-May, summer as June-August, fall as
September-November, and winter as December-February.

### Holidays And Rough Event Periods

```bash
/chat what thoughts did I save around Christmas?
/chat my reflections around Easter time
/chat what did I preserve near the end-of-year review?
```

Holiday ranges and ambiguous expressions may use the configured temporal-intent
LLM route.

## Broad And Focused Queries

A broad temporal query analyzes every eligible memory in the requested period:

```bash
/chat what themes appear in the notes I saved last week?
```

A focused query applies both the date window and a topic filter:

```bash
/chat what did I preserve about React debugging last week?
/chat database tradeoffs from last month
/chat trust and system simplicity in my winter notes
```

Broad does not mean comprehensive. It means broad across the memories present
in Mentat for that period.

## Useful Workflows

### Return To A Project Question

```bash
/chat what did I preserve about the authentication redesign last month?
/search rollback ownership
/chat which assumptions changed across those notes?
```

### Trace Learning

```bash
/chat which vector-search ideas appeared in my January notes?
/chat how did my explanation of embeddings change through spring?
/synthesize embedding intuitions
```

### Review Recurrence

```bash
/summary 30
/chat which questions recur in the memories I saved this month?
/chat which of those questions also appeared last quarter?
```

These queries can reveal recurrence inside the corpus. They should not be used
as measurements of output, mood, or productivity unless the captured record was
explicitly designed for that purpose.

## Query Tips

- Name the topic when you remember it; focused temporal queries are usually stronger.
- Start broad when you remember only the period, then narrow from the returned themes.
- Say "captured," "saved," "preserved," or "in my notes" when the distinction matters.
- Treat a low-memory period as limited evidence, not proof that nothing happened.
- Use `/view` after temporal chat when you want to inspect the underlying memory.

## Technical Behavior

Common expressions such as `yesterday`, `last week`, `last month`, month names,
seasons, and Christmas ranges are parsed deterministically in
`mentat/chat/temporal.py`. More ambiguous expressions can fall back to the
configured `TEMPORAL_INTENT_PROVIDER` and `TEMPORAL_INTENT_MODEL`, which inherit
from `HELPERS_*` and then active chat when unset.

Temporal retrieval filters by each memory's saved timestamp. It does not infer
the date of an event mentioned inside the note unless that date also affected
how the memory was stored.

---

Temporal search is for finding the thoughts you deliberately left yourself,
even when the season is easier to remember than the sentence.
