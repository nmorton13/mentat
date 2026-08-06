from __future__ import annotations

from pathlib import Path

import pytest

from mentat.core.database import MemoryDatabase
from mentat.core.journal_transfer import (
    export_journal,
    import_journal,
    parse_journal_file,
)


def _database(path: Path) -> MemoryDatabase:
    return MemoryDatabase(str(path))


def test_journal_snapshot_round_trip_and_duplicate_detection(tmp_path):
    source_db = _database(tmp_path / "source.db")
    source_db.save_memory(
        "First line\nSecond line",
        "nate",
        "reflection",
        ["project", "thinking"],
        {
            "ai_analyzed": True,
            "type": "reflection",
            "confidence": 0.9,
            "entities": {"projects": ["Mentat"]},
            "url": "https://example.com/source",
            "title": "Example source",
        },
        timestamp="2026-07-29T09:15:00",
    )
    source_db.save_memory(
        "Ship the archive work",
        "nate",
        "task",
        ["release"],
        {},
        timestamp="2026-07-29T10:30:00",
    )

    archive_path = tmp_path / "journal"
    export_result = export_journal(source_db, "nate", archive_path)

    assert export_result.exported == 2
    journal_file = archive_path / "2026" / "07-July" / "2026-07-29.md"
    assert journal_file.exists()
    assert "First line\n  Second line" in journal_file.read_text(encoding="utf-8")

    destination_db = _database(tmp_path / "destination.db")
    import_result = import_journal(
        destination_db,
        "nate",
        archive_path,
        embedding_generator=lambda _content: [1.0, 0.0],
    )

    assert import_result.imported == 2
    assert import_result.duplicates == 0
    restored = destination_db.get_memories_for_export("nate")
    assert [memory["content"] for memory in restored] == [
        "First line\nSecond line",
        "Ship the archive work",
    ]
    assert restored[0]["command_type"] == "reflection"
    assert restored[0]["timestamp"] == "2026-07-29T09:15:00"
    assert restored[0]["metadata"]["url"] == "https://example.com/source"

    duplicate_result = import_journal(destination_db, "nate", archive_path)
    assert duplicate_result.imported == 0
    assert duplicate_result.duplicates == 2


def test_journal_import_dry_run_does_not_write(tmp_path):
    journal_path = tmp_path / "2026-07-29.md"
    journal_path.write_text(
        "---\n"
        "date: 2026-07-29\n"
        "time: [ \"12:00\" ]\n"
        "type: [ \"idea\" ]\n"
        "tags: [ \"test\" ]\n"
        "people: []\n"
        "orgs: []\n"
        "projects: []\n"
        "source_url: []\n"
        "---\n\n"
        "# July 29, 2026\n\n"
        "**12:00** 💡 - #test  \n"
        "A portable thought\n\n",
        encoding="utf-8",
    )
    db = _database(tmp_path / "dry-run.db")

    result = import_journal(db, "nate", journal_path, dry_run=True)

    assert result.imported == 1
    assert result.dry_run is True
    assert db.get_memories_for_export("nate") == []


def test_journal_parser_falls_back_to_whole_document(tmp_path):
    journal_path = tmp_path / "2026-07-29.md"
    journal_path.write_text(
        "---\n"
        "date: 2026-07-29\n"
        "tags: [ \"hand-edited\" ]\n"
        "---\n\n"
        "# July 29, 2026\n\n"
        "This file was edited into ordinary prose.\n",
        encoding="utf-8",
    )

    entries = parse_journal_file(journal_path)

    assert len(entries) == 1
    assert entries[0].command_type == "journal_document"
    assert entries[0].content == "This file was edited into ordinary prose."
    assert entries[0].metadata["journal_import"]["fallback_document"] is True


def test_journal_export_refuses_nonempty_destination(tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    (destination / "keep.md").write_text("Do not overwrite", encoding="utf-8")
    db = _database(tmp_path / "source.db")

    with pytest.raises(ValueError, match="not empty"):
        export_journal(db, "nate", destination)
