# Export, Import, and Interchange

Mentat supports two Markdown-based archive formats with different jobs:

| Format | Best for | Layout | Round trip |
| --- | --- | --- | --- |
| Journal Markdown v1 | Reading a dated personal archive in Markdown or Obsidian | One file per day with multiple entries | Recovers fields represented by the journal |
| Open Knowledge Format v0.2 | Portable, Git-friendly interchange with other tools and agents | One concept file per memory | Preserves original Mentat content and structured metadata |

The formats are independent and can be enabled together.

## Automatic Export

Run `mentat config init` and choose Journal Markdown, OKF, both, or off.
The equivalent environment settings are:

```env
MARKDOWN_EXPORT_ENABLED=true
MARKDOWN_EXPORT_PATH=data/markdown

OKF_EXPORT_ENABLED=false
OKF_EXPORT_PATH=data/okf
OKF_EXPORT_ACTOR=human:your-name
```

Journal export remains enabled by default for compatibility. OKF is opt-in.
Personal actor identities belong only in the ignored local `.env`. If no actor
is configured, Mentat identifies the producer with its application version.

An export failure warns without rolling back a successful SQLite capture.
Export directories contain personal memory and should not be committed unless
that is an explicit choice.

## Snapshot Export

Manual export includes every memory for the selected user, even when automatic
export was previously disabled:

```bash
mentat export markdown /path/to/new-journal
mentat export okf /path/to/new-okf-bundle
```

Mentat refuses to write into a nonempty destination. This prevents a snapshot
from duplicating entries or overwriting an existing archive.

Both commands support `--json` for a machine-readable count and destination.

## Journal Markdown v1

Journal v1 is the existing dated, human-readable Mentat archive. It aggregates
tags, types, people, projects, and source URLs in daily frontmatter and keeps
individual entries in the body.

It is a stable reading format rather than a lossless database serialization.
The journal does not contain every internal SQLite field or a durable ID for
every historical entry. Import therefore restores the content and structured
fields represented by the file and reports anything it cannot parse.

Import only files produced in Mentat's known Journal v1 layout:

```bash
mentat import markdown /path/to/journal --dry-run
mentat import markdown /path/to/journal
```

Files manually changed beyond reliable entry splitting are imported as one
document instead of being silently discarded.

## Open Knowledge Format v0.2

OKF export targets the
[Open Knowledge Format v0.2 specification](https://github.com/GoogleCloudPlatform/knowledge-catalog/blob/main/okf/SPEC.md).
It writes:

```text
bundle/
  index.md
  memories/
    2026/
      07/
        123-short-title.md
```

Every memory concept has a nonempty `type`, its original content as Markdown,
and YAML frontmatter for title, description, tags, generation, and sources.
A namespaced `mentat` extension preserves the durable memory ID, command type,
and existing structured metadata. Unknown OKF types and extension fields remain
valid and are retained on import.

```bash
mentat import okf /path/to/bundle --dry-run
mentat import okf /path/to/bundle
```

Import validates required OKF structure, stores concepts for normal search and
chat, and generates embeddings locally. It does not use an LLM to rewrite or
reclassify imported content.

Attested Computation concepts are readable and searchable, but Mentat never
executes their computation, executor, attester, SQL, scripts, or referenced
code during import.

## Import Safety

Both importers:

- support `--dry-run`;
- avoid exact duplicate memories;
- preserve source-path information;
- generate embeddings locally during a real import;
- report imported, duplicate, skipped, and error counts.

Importing can trigger the same first-use embedding-model download described in
the [installation guide](installation.md).
