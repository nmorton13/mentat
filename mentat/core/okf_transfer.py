"""Open Knowledge Format v0.2 export, validation, and import."""

from __future__ import annotations

from datetime import date, datetime
from importlib.metadata import PackageNotFoundError, version
import json
from pathlib import Path
import re
from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple
import unicodedata

import yaml

from .config import OKF_EXPORT_ACTOR, OKF_EXPORT_ENABLED, OKF_EXPORT_PATH
from .journal_transfer import TransferResult
from .private_files import ensure_private_directory, open_private_text


OKF_VERSION = "0.2"
RESERVED_FILENAMES = {"index.md", "log.md"}
TYPE_LABELS = {
    "ai_response": "AI Response",
    "ask": "Question",
    "capture": "Note",
    "dump": "Thought",
    "idea": "Idea",
    "journal_document": "Journal",
    "link": "Reference",
    "reflection": "Reflection",
    "status": "Status",
    "task": "Task",
    "voice_conversation": "Conversation",
}


def _package_actor() -> str:
    try:
        release_version = version("mentat")
    except PackageNotFoundError:
        release_version = "development"
    return f"mentat/{release_version}"


def _prepare_empty_directory(destination: Path) -> Path:
    destination = destination.expanduser().resolve()
    if destination.exists():
        if not destination.is_dir():
            raise ValueError(f"Export destination is not a directory: {destination}")
        if any(destination.iterdir()):
            raise ValueError(f"Export destination is not empty: {destination}")
    ensure_private_directory(destination)
    return destination


def _metadata_dict(metadata: Any) -> Dict[str, Any]:
    if isinstance(metadata, dict):
        return metadata
    if not metadata:
        return {}
    try:
        parsed = json.loads(metadata)
        return parsed if isinstance(parsed, dict) else {}
    except (TypeError, json.JSONDecodeError):
        return {}


def _one_line(value: Any, limit: int = 160) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit].rstrip()


def _title_for_memory(memory: Dict[str, Any], metadata: Dict[str, Any]) -> str:
    title = metadata.get("title")
    if not title:
        source = metadata.get("source")
        if isinstance(source, dict):
            title = source.get("title")
    if not title:
        first_line = next(
            (line.strip().lstrip("#").strip() for line in memory["content"].splitlines() if line.strip()),
            "",
        )
        title = first_line
    return _one_line(title or f"Memory {memory['id']}", limit=100)


def _slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    slug = re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")
    return slug[:60].rstrip("-") or "memory"


def _iso_timestamp(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return datetime.now().astimezone().isoformat()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return text


def _source_entries(metadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    candidates: List[Tuple[str, Optional[str]]] = []
    if metadata.get("url"):
        candidates.append((str(metadata["url"]), metadata.get("title")))
    for url in metadata.get("urls", []) if isinstance(metadata.get("urls"), list) else []:
        if url:
            candidates.append((str(url), None))
    if metadata.get("fetched_url"):
        candidates.append((str(metadata["fetched_url"]), metadata.get("title")))
    source = metadata.get("source")
    if isinstance(source, dict) and source.get("url"):
        candidates.append((str(source["url"]), source.get("title")))

    entries = []
    seen = set()
    for resource, title in candidates:
        if resource in seen:
            continue
        seen.add(resource)
        entry: Dict[str, Any] = {
            "id": f"source-{len(entries) + 1}",
            "resource": resource,
        }
        if title:
            entry["title"] = _one_line(title)
        entries.append(entry)
    return entries


def memory_to_okf(
    memory: Dict[str, Any],
    *,
    actor: Optional[str] = None,
) -> Tuple[Dict[str, Any], str, str]:
    """Map one Mentat memory to OKF frontmatter, body, and stable relative path."""
    metadata = _metadata_dict(memory.get("metadata"))
    title = _title_for_memory(memory, metadata)
    command_type = str(memory.get("command_type") or "capture")
    frontmatter: Dict[str, Any] = {
        "type": TYPE_LABELS.get(command_type, command_type.replace("_", " ").title()),
        "title": title,
    }
    summary = metadata.get("ai_summary") or metadata.get("summary")
    if summary and _one_line(summary) != _one_line(memory["content"]):
        frontmatter["description"] = _one_line(summary)
    tags = [str(tag) for tag in memory.get("tags") or [] if str(tag).strip()]
    if tags:
        frontmatter["tags"] = tags
    frontmatter["generated"] = {
        "by": actor or _package_actor(),
        "at": _iso_timestamp(memory.get("timestamp")),
    }
    sources = _source_entries(metadata)
    if sources:
        frontmatter["sources"] = sources
    frontmatter["mentat"] = {
        "schema_version": 1,
        "memory_id": memory["id"],
        "command_type": command_type,
        "metadata": metadata,
    }

    try:
        captured = datetime.fromisoformat(
            str(memory.get("timestamp") or "").replace("Z", "+00:00")
        )
        date_path = f"{captured:%Y}/{captured:%m}"
    except ValueError:
        date_path = "undated"
    relative_path = (
        Path("memories")
        / date_path
        / f"{memory['id']}-{_slug(title)}.md"
    )
    return frontmatter, str(memory["content"]).strip(), relative_path.as_posix()


def _document_text(frontmatter: Dict[str, Any], body: str) -> str:
    yaml_text = yaml.safe_dump(
        frontmatter,
        allow_unicode=True,
        default_flow_style=False,
        sort_keys=False,
    ).rstrip()
    return f"---\n{yaml_text}\n---\n\n{body.rstrip()}\n"


def _write_private(path: Path, text: str) -> None:
    ensure_private_directory(path.parent)
    with open_private_text(path) as file:
        file.write(text)


def export_okf(
    db: Any,
    user_id: str,
    destination: Path,
    *,
    actor: Optional[str] = None,
) -> TransferResult:
    """Export all memories for one user as a conforming OKF v0.2 bundle."""
    destination = _prepare_empty_directory(Path(destination))
    memories = db.get_memories_for_export(user_id)
    result = TransferResult(format="okf-v0.2", destination=str(destination))
    index_entries = []

    for memory in memories:
        frontmatter, body, relative_path = memory_to_okf(
            memory,
            actor=actor or OKF_EXPORT_ACTOR,
        )
        _write_private(destination / relative_path, _document_text(frontmatter, body))
        index_entries.append(
            f"* [{frontmatter['title']}]({relative_path})"
            + (
                f" - {frontmatter['description']}"
                if frontmatter.get("description")
                else ""
            )
        )
        result.exported += 1

    index_frontmatter = {"okf_version": OKF_VERSION}
    index_body = "# Mentat Knowledge Bundle\n\n## Memories\n\n"
    index_body += "\n".join(index_entries) if index_entries else "_No memories exported._"
    _write_private(
        destination / "index.md",
        _document_text(index_frontmatter, index_body),
    )

    errors = validate_okf_bundle(destination)
    if errors:
        raise RuntimeError("Invalid OKF export: " + "; ".join(errors))
    return result


def _update_bundle_index(
    bundle: Path,
    relative_path: str,
    frontmatter: Dict[str, Any],
) -> None:
    index_path = bundle / "index.md"
    entry = (
        f"* [{frontmatter['title']}]({relative_path})"
        + (
            f" - {frontmatter['description']}"
            if frontmatter.get("description")
            else ""
        )
    )
    entries = {}
    if index_path.exists():
        _existing_frontmatter, existing_body = _split_document(
            index_path.read_text(encoding="utf-8")
        )
        for line in existing_body.splitlines():
            match = re.match(r"^\* \[.*\]\(([^)]+)\)(?: - .*)?$", line)
            if match:
                entries[match.group(1)] = line
    entries[relative_path] = entry
    body = "# Mentat Knowledge Bundle\n\n## Memories\n\n"
    body += "\n".join(entries[path] for path in sorted(entries))
    _write_private(
        index_path,
        _document_text({"okf_version": OKF_VERSION}, body),
    )


def save_memory_to_okf(
    memory: Dict[str, Any],
    *,
    export_path: Optional[Path] = None,
    actor: Optional[str] = None,
    force: bool = False,
) -> bool:
    """Write or update one captured memory in the automatic OKF bundle."""
    if not OKF_EXPORT_ENABLED and not force:
        return True
    try:
        bundle = Path(export_path or OKF_EXPORT_PATH)
        ensure_private_directory(bundle)
        frontmatter, body, relative_path = memory_to_okf(
            memory,
            actor=actor or OKF_EXPORT_ACTOR,
        )
        _write_private(bundle / relative_path, _document_text(frontmatter, body))
        _update_bundle_index(bundle, relative_path, frontmatter)
        return True
    except Exception:
        return False


def save_database_memory_to_okf(
    db: Any,
    memory_id: int,
    user_id: str,
) -> bool:
    """Load the persisted record and write its canonical automatic OKF concept."""
    if not OKF_EXPORT_ENABLED:
        return True
    memory = db.get_memory_by_id(memory_id, user_id)
    if not memory:
        return False
    return save_memory_to_okf(memory)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _split_document(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    if not text.startswith("---\n"):
        return None, text
    closing = text.find("\n---\n", 4)
    if closing == -1:
        return None, text
    try:
        loaded = yaml.safe_load(text[4:closing])
    except yaml.YAMLError:
        return None, text
    normalized = _json_safe(loaded) if isinstance(loaded, dict) else None
    return normalized, text[closing + 5:].lstrip("\n")


def _bundle_markdown_files(bundle: Path) -> Iterable[Path]:
    return sorted(
        path for path in bundle.rglob("*.md")
        if path.is_file() and not path.is_symlink()
    )


def validate_okf_bundle(bundle: Path) -> List[str]:
    """Return conformance errors for an OKF v0.2 bundle."""
    bundle = Path(bundle)
    if not bundle.is_dir():
        return [f"Bundle directory does not exist: {bundle}"]
    errors = []
    for path in _bundle_markdown_files(bundle):
        relative = path.relative_to(bundle).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"{relative}: unreadable ({exc})")
            continue
        frontmatter, body = _split_document(text)
        if path.name == "index.md":
            if path.parent != bundle and frontmatter is not None:
                errors.append(f"{relative}: nested index.md must not have frontmatter")
            elif path.parent == bundle and frontmatter is not None:
                extra_keys = set(frontmatter) - {"okf_version"}
                if extra_keys:
                    errors.append(
                        f"{relative}: root index.md frontmatter may only contain "
                        "okf_version"
                    )
            if not body.lstrip().startswith("#"):
                errors.append(f"{relative}: index.md must contain a Markdown heading")
            continue
        if path.name == "log.md":
            if frontmatter is not None:
                errors.append(f"{relative}: log.md must not have frontmatter")
            if not body.lstrip().startswith("#"):
                errors.append(f"{relative}: log.md must contain a Markdown heading")
            invalid_dates = [
                heading
                for heading in re.findall(r"(?m)^##\s+(.+?)\s*$", body)
                if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", heading)
            ]
            if invalid_dates:
                errors.append(
                    f"{relative}: log date headings must use YYYY-MM-DD"
                )
            continue
        if frontmatter is None:
            errors.append(f"{relative}: missing or invalid YAML frontmatter")
            continue
        concept_type = frontmatter.get("type")
        if not isinstance(concept_type, str) or not concept_type.strip():
            errors.append(f"{relative}: missing non-empty type")
    return errors


def _concept_files(bundle: Path) -> Iterable[Path]:
    return (
        path for path in _bundle_markdown_files(bundle)
        if path.name not in RESERVED_FILENAMES
    )


def _third_party_content(frontmatter: Dict[str, Any], body: str) -> str:
    title = _one_line(frontmatter.get("title"))
    body = body.strip()
    if title and not body.lstrip().startswith("#"):
        return f"# {title}\n\n{body}".rstrip()
    return body


def import_okf(
    db: Any,
    user_id: str,
    bundle: Path,
    *,
    dry_run: bool = False,
    embedding_generator: Optional[Callable[[str], Optional[List[float]]]] = None,
) -> TransferResult:
    """Import OKF concepts as searchable memories without executing bundle code."""
    bundle = Path(bundle).expanduser().resolve()
    validation_errors = validate_okf_bundle(bundle)
    if validation_errors:
        raise ValueError("Invalid OKF bundle: " + "; ".join(validation_errors))

    result = TransferResult(
        format="okf-v0.2",
        source=str(bundle),
        dry_run=dry_run,
    )
    for path in _concept_files(bundle):
        frontmatter, body = _split_document(path.read_text(encoding="utf-8"))
        if frontmatter is None:
            result.errors += 1
            continue
        mentat_extension = frontmatter.get("mentat")
        if isinstance(mentat_extension, dict):
            command_type = str(
                mentat_extension.get("command_type") or "okf_concept"
            )
            content = body.strip()
            original_metadata = mentat_extension.get("metadata")
            metadata = (
                dict(original_metadata)
                if isinstance(original_metadata, dict)
                else {}
            )
        else:
            command_type = "okf_concept"
            content = _third_party_content(frontmatter, body)
            metadata = {}
        if not content:
            result.skipped += 1
            continue

        metadata["okf"] = {
            "version": OKF_VERSION,
            "source_path": path.relative_to(bundle).as_posix(),
            "frontmatter": frontmatter,
            "execution_allowed": False,
        }
        tags_value = frontmatter.get("tags")
        tags = (
            [str(tag) for tag in tags_value]
            if isinstance(tags_value, list)
            else []
        )
        generated = frontmatter.get("generated")
        timestamp = (
            generated.get("at")
            if isinstance(generated, dict) and generated.get("at")
            else datetime.fromtimestamp(path.stat().st_mtime).isoformat()
        )

        if db.find_memory_id(content, user_id, command_type):
            result.duplicates += 1
            continue
        if dry_run:
            result.imported += 1
            continue
        memory_id = db.save_memory(
            content,
            user_id,
            command_type,
            tags,
            metadata,
            timestamp=str(timestamp),
        )
        if not memory_id:
            result.errors += 1
            continue
        result.imported += 1
        if embedding_generator:
            try:
                embedding = embedding_generator(content)
                if embedding:
                    db.save_embedding(memory_id, embedding)
            except Exception:
                result.errors += 1
    return result
