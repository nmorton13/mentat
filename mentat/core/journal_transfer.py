"""Snapshot export and import for Mentat Journal Markdown v1."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
import re
from typing import Any, Callable, Dict, Iterable, List, Optional

from .markdown_export import save_memory_to_markdown, split_frontmatter
from .private_files import ensure_private_directory


ENTRY_START = re.compile(
    r"(?m)^\*\*(?P<time>\d{2}:\d{2}|\?\?:\?\?)\*\* "
    r"(?P<header>[^\n]*?)  \n"
)
METADATA_START = re.compile(
    r"(?m)^(?:📊|🏷️|🌐|📄|✅|📝|✨|🎯|👤|🤖) \*\*"
)
TYPE_FROM_EMOJI = {
    "💡": "idea",
    "🧠": "dump",
    "❓": "ask",
    "🔗": "link",
    "📝": "capture",
    "🤔": "reflection",
    "✅": "task",
    "🤖": "ai_response",
}


@dataclass
class TransferResult:
    """Stable result summary for human and JSON CLI output."""

    format: str
    source: Optional[str] = None
    destination: Optional[str] = None
    exported: int = 0
    imported: int = 0
    duplicates: int = 0
    skipped: int = 0
    errors: int = 0
    dry_run: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class JournalEntry:
    content: str
    command_type: str
    tags: List[str]
    metadata: Dict[str, Any]
    timestamp: str


def _prepare_empty_directory(destination: Path) -> Path:
    destination = destination.expanduser().resolve()
    if destination.exists():
        if not destination.is_dir():
            raise ValueError(f"Export destination is not a directory: {destination}")
        if any(destination.iterdir()):
            raise ValueError(f"Export destination is not empty: {destination}")
    ensure_private_directory(destination)
    return destination


def export_journal(db: Any, user_id: str, destination: Path) -> TransferResult:
    """Export all memories for one user to a fresh Journal Markdown v1 archive."""
    destination = _prepare_empty_directory(Path(destination))
    memories = db.get_memories_for_export(user_id)
    result = TransferResult(
        format="journal-v1",
        destination=str(destination),
    )

    for memory in memories:
        written = save_memory_to_markdown(
            memory["content"],
            memory["command_type"],
            memory.get("tags") or [],
            memory.get("metadata") or {},
            memory.get("timestamp"),
            user_id,
            export_path=destination,
            force=True,
        )
        if written:
            result.exported += 1
        else:
            result.errors += 1

    if result.errors:
        raise RuntimeError(
            f"Journal export failed for {result.errors} of {len(memories)} memories"
        )
    return result


def _deindent_content(content: str) -> str:
    lines = content.rstrip().splitlines()
    if not lines:
        return ""
    restored = [lines[0]]
    restored.extend(line[2:] if line.startswith("  ") else line for line in lines[1:])
    return "\n".join(restored).strip()


def _entry_timestamp(date_value: Any, time_value: str, path: Path) -> str:
    date_text = str(date_value or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_text):
        date_text = path.stem if re.fullmatch(r"\d{4}-\d{2}-\d{2}", path.stem) else ""
    if not date_text:
        date_text = datetime.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m-%d")
    time_text = time_value if re.fullmatch(r"\d{2}:\d{2}", time_value) else "00:00"
    return f"{date_text}T{time_text}:00"


def _command_type(header: str, rendered_metadata: str) -> str:
    analysis_match = re.search(
        r"(?m)^📊 \*\*AI Analysis:\*\*.*?\bType:\s*([^,\n]+)",
        rendered_metadata,
    )
    if analysis_match:
        return analysis_match.group(1).strip()
    for emoji, command_type in TYPE_FROM_EMOJI.items():
        if emoji in header:
            return command_type
    return "capture"


def _parse_entry(
    path: Path,
    date_value: Any,
    index: int,
    match: re.Match[str],
    rendered: str,
) -> Optional[JournalEntry]:
    metadata_match = METADATA_START.search(rendered)
    content_block = rendered[:metadata_match.start()] if metadata_match else rendered
    rendered_metadata = rendered[metadata_match.start():].strip() if metadata_match else ""
    header = match.group("header")
    command_type = _command_type(header, rendered_metadata)
    metadata: Dict[str, Any] = {
        "journal_import": {
            "format": "journal-v1",
            "source_path": str(path),
            "entry_index": index,
        }
    }

    if content_block.startswith("**Prompt:**\n") and "\n\n**Response:**\n" in content_block:
        prompt, content_block = content_block[len("**Prompt:**\n"):].split(
            "\n\n**Response:**\n",
            1,
        )
        metadata["source"] = {
            "type": "ai_response",
            "prompt": _deindent_content(prompt),
        }
        command_type = "ai_response"

    content = _deindent_content(content_block)
    if not content:
        return None

    tags = list(dict.fromkeys(re.findall(r"(?<!\w)#([A-Za-z0-9_-]+)", header)))
    mentions = list(dict.fromkeys(re.findall(r"\[\[([^\]]+)\]\]", header)))
    if mentions:
        metadata["entities"] = {"mentions": mentions}

    url_match = re.search(r"(?m)^🌐 \*\*URL:\*\*\s*(.+)$", rendered_metadata)
    if url_match:
        metadata["url"] = url_match.group(1).strip()
    title_match = re.search(r"(?m)^📄 \*\*Title:\*\*\s*(.+)$", rendered_metadata)
    if title_match:
        metadata["title"] = title_match.group(1).strip()
    if rendered_metadata:
        metadata["journal_import"]["rendered_metadata"] = rendered_metadata

    return JournalEntry(
        content=content,
        command_type=command_type,
        tags=tags,
        metadata=metadata,
        timestamp=_entry_timestamp(date_value, match.group("time"), path),
    )


def parse_journal_file(path: Path) -> List[JournalEntry]:
    """Parse one Mentat daily journal file into recoverable memory entries."""
    text = path.read_text(encoding="utf-8")
    frontmatter, body = split_frontmatter(text)
    matches = list(ENTRY_START.finditer(body))
    entries: List[JournalEntry] = []

    for position, match in enumerate(matches):
        end = matches[position + 1].start() if position + 1 < len(matches) else len(body)
        entry = _parse_entry(
            path,
            frontmatter.get("date"),
            position + 1,
            match,
            body[match.end():end].rstrip(),
        )
        if entry:
            entries.append(entry)

    if entries or not body.strip():
        return entries

    fallback_content = body.strip()
    heading_lines = fallback_content.splitlines()
    if heading_lines and heading_lines[0].startswith("# "):
        fallback_content = "\n".join(heading_lines[1:]).strip()
    if not fallback_content:
        return []
    tags_value = frontmatter.get("tags", [])
    tags = tags_value if isinstance(tags_value, list) else [str(tags_value)]
    return [JournalEntry(
        content=fallback_content,
        command_type="journal_document",
        tags=[str(tag) for tag in tags if tag],
        metadata={
            "journal_import": {
                "format": "journal-v1",
                "source_path": str(path),
                "fallback_document": True,
            }
        },
        timestamp=_entry_timestamp(frontmatter.get("date"), "00:00", path),
    )]


def _journal_files(source: Path) -> Iterable[Path]:
    if source.is_file():
        if source.suffix.lower() != ".md":
            raise ValueError(f"Journal source is not a Markdown file: {source}")
        return [source]
    if not source.is_dir():
        raise ValueError(f"Journal source does not exist: {source}")
    return sorted(
        path for path in source.rglob("*.md")
        if path.is_file() and not path.is_symlink()
    )


def import_journal(
    db: Any,
    user_id: str,
    source: Path,
    *,
    dry_run: bool = False,
    embedding_generator: Optional[Callable[[str], Optional[List[float]]]] = None,
) -> TransferResult:
    """Import a Journal Markdown v1 archive without LLM reanalysis."""
    source = Path(source).expanduser().resolve()
    result = TransferResult(
        format="journal-v1",
        source=str(source),
        dry_run=dry_run,
    )

    for path in _journal_files(source):
        try:
            entries = parse_journal_file(path)
        except (OSError, UnicodeError, ValueError):
            result.errors += 1
            continue
        if not entries:
            result.skipped += 1
            continue

        for entry in entries:
            if db.find_memory_id(entry.content, user_id, entry.command_type):
                result.duplicates += 1
                continue
            if dry_run:
                result.imported += 1
                continue
            memory_id = db.save_memory(
                entry.content,
                user_id,
                entry.command_type,
                entry.tags,
                entry.metadata,
                timestamp=entry.timestamp,
            )
            if not memory_id:
                result.errors += 1
                continue
            result.imported += 1
            if embedding_generator:
                try:
                    embedding = embedding_generator(entry.content)
                    if embedding:
                        db.save_embedding(memory_id, embedding)
                except Exception:
                    result.errors += 1

    return result
