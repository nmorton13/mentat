from __future__ import annotations

from pathlib import Path

import yaml

from mentat.core.database import MemoryDatabase
from mentat.core.okf_transfer import (
    export_okf,
    import_okf,
    save_memory_to_okf,
    validate_okf_bundle,
)


def _database(path: Path) -> MemoryDatabase:
    return MemoryDatabase(str(path))


def _frontmatter(path: Path):
    text = path.read_text(encoding="utf-8")
    _, yaml_text, _body = text.split("---", 2)
    return yaml.safe_load(yaml_text)


def test_okf_export_is_conforming_and_round_trips_mentat_metadata(tmp_path):
    source_db = _database(tmp_path / "source.db")
    memory_id = source_db.save_memory(
        "The export should stay portable.",
        "nate",
        "reflection",
        ["mentat", "portability"],
        {
            "title": "Portable Mentat export",
            "summary": "A reflection about portable knowledge.",
            "url": "https://example.com/spec",
            "entities": {"projects": ["Mentat"]},
        },
        timestamp="2026-07-29T14:00:00",
    )
    bundle = tmp_path / "bundle"

    result = export_okf(
        source_db,
        "nate",
        bundle,
        actor="human:test-user",
    )

    assert result.exported == 1
    assert validate_okf_bundle(bundle) == []
    concept_path = next((bundle / "memories").rglob("*.md"))
    frontmatter = _frontmatter(concept_path)
    assert frontmatter["type"] == "Reflection"
    assert frontmatter["title"] == "Portable Mentat export"
    assert frontmatter["generated"]["by"] == "human:test-user"
    assert frontmatter["sources"][0]["resource"] == "https://example.com/spec"
    assert frontmatter["mentat"]["memory_id"] == memory_id
    assert frontmatter["mentat"]["command_type"] == "reflection"
    assert _frontmatter(bundle / "index.md")["okf_version"] == "0.2"

    destination_db = _database(tmp_path / "destination.db")
    imported = import_okf(destination_db, "nate", bundle)

    assert imported.imported == 1
    restored = destination_db.get_memories_for_export("nate")
    assert restored[0]["content"] == "The export should stay portable."
    assert restored[0]["command_type"] == "reflection"
    assert restored[0]["metadata"]["entities"] == {"projects": ["Mentat"]}
    assert restored[0]["metadata"]["okf"]["execution_allowed"] is False

    duplicate = import_okf(destination_db, "nate", bundle)
    assert duplicate.imported == 0
    assert duplicate.duplicates == 1


def test_okf_import_accepts_unknown_type_and_extension_fields(tmp_path):
    bundle = tmp_path / "third-party"
    bundle.mkdir()
    (bundle / "index.md").write_text(
        "---\nokf_version: \"0.2\"\n---\n\n# Bundle\n",
        encoding="utf-8",
    )
    (bundle / "unusual.md").write_text(
        "---\n"
        "type: Unexpected Future Concept\n"
        "title: Strange but valid\n"
        "tags: [future]\n"
        "producer_extension:\n"
        "  retained: true\n"
        "stale_after: 2026-09-23\n"
        "---\n\n"
        "Unknown fields must survive import.\n",
        encoding="utf-8",
    )
    db = _database(tmp_path / "import.db")

    assert validate_okf_bundle(bundle) == []
    result = import_okf(db, "nate", bundle, dry_run=False)

    assert result.imported == 1
    memory = db.get_memories_for_export("nate")[0]
    assert memory["command_type"] == "okf_concept"
    assert memory["content"].startswith("# Strange but valid")
    assert (
        memory["metadata"]["okf"]["frontmatter"]["producer_extension"]
        == {"retained": True}
    )
    assert memory["metadata"]["okf"]["frontmatter"]["stale_after"] == "2026-09-23"


def test_okf_validator_rejects_concept_without_type(tmp_path):
    bundle = tmp_path / "invalid"
    bundle.mkdir()
    (bundle / "concept.md").write_text(
        "---\ntitle: Missing type\n---\n\nBody\n",
        encoding="utf-8",
    )

    errors = validate_okf_bundle(bundle)

    assert errors == ["concept.md: missing non-empty type"]


def test_okf_validator_enforces_reserved_file_structure(tmp_path):
    bundle = tmp_path / "invalid-reserved"
    bundle.mkdir()
    (bundle / "index.md").write_text(
        "---\nokf_version: \"0.2\"\nproducer: mentat\n---\n\n# Bundle\n",
        encoding="utf-8",
    )
    (bundle / "log.md").write_text(
        "# Directory Update Log\n\n## July 29, 2026\n\n* Added a concept.\n",
        encoding="utf-8",
    )

    assert validate_okf_bundle(bundle) == [
        "index.md: root index.md frontmatter may only contain okf_version",
        "log.md: log date headings must use YYYY-MM-DD",
    ]


def test_okf_import_never_executes_attested_computation(tmp_path):
    bundle = tmp_path / "attested"
    bundle.mkdir()
    (bundle / "calculation.md").write_text(
        "---\n"
        "type: Attested Computation\n"
        "title: Never execute this during import\n"
        "runtime: python\n"
        "executor:\n"
        "  resource: references/run.py\n"
        "---\n\n"
        "# Computation\n\n"
        "```python\nraise RuntimeError('must not execute')\n```\n",
        encoding="utf-8",
    )
    db = _database(tmp_path / "attested.db")

    result = import_okf(db, "nate", bundle)

    assert result.imported == 1
    memory = db.get_memories_for_export("nate")[0]
    assert memory["metadata"]["okf"]["execution_allowed"] is False


def test_automatic_okf_export_updates_stable_concept_and_index(tmp_path):
    bundle = tmp_path / "automatic"
    memory = {
        "id": 42,
        "content": "Automatic portable memory",
        "command_type": "idea",
        "tags": ["portable"],
        "metadata": "{}",
        "timestamp": "2026-07-29T15:00:00",
    }

    assert save_memory_to_okf(
        memory,
        export_path=bundle,
        actor="human:test-user",
        force=True,
    )
    assert save_memory_to_okf(
        memory,
        export_path=bundle,
        actor="human:test-user",
        force=True,
    )

    concepts = list((bundle / "memories").rglob("*.md"))
    assert len(concepts) == 1
    index_text = (bundle / "index.md").read_text(encoding="utf-8")
    assert index_text.count("42-automatic-portable-memory.md") == 1
    assert validate_okf_bundle(bundle) == []
