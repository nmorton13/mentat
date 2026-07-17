import json

from mentat.core.database import MemoryDatabase


def test_save_memory_deduplicates(tmp_path):
    db_path = tmp_path / "mentat_sqlite.db"
    db = MemoryDatabase(db_path=str(db_path))

    memory_id = db.save_memory("Same content", "u1", "note", tags=["tag"])
    duplicate_id = db.save_memory("Same content", "u1", "note", tags=["tag"])

    assert memory_id == duplicate_id
    assert len(db.safe_memory_search("Same content", "u1")) == 1
    with db.db_pool.get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM memories_fts WHERE user_id = ? AND content = ?",
            ("u1", "Same content"),
        ).fetchone()[0]
    assert count == 1


def test_delete_memory_removes_embedding(tmp_path):
    db_path = tmp_path / "mentat_sqlite.db"
    db = MemoryDatabase(db_path=str(db_path))

    memory_id = db.save_memory("Embedding test", "u1", "note", tags=["tag"])
    db.save_embedding(memory_id, [1.0, 0.0])

    db.delete_memory(memory_id, "u1")

    with db.db_pool.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM mem_embeddings WHERE memory_id = ?", (memory_id,))
        remaining = cursor.fetchone()[0]

    assert remaining == 0
    assert db.get_memory_by_id(memory_id, "u1") is None


def test_safe_memory_search_matches_content(tmp_path):
    db_path = tmp_path / "mentat_sqlite.db"
    db = MemoryDatabase(db_path=str(db_path))

    db.save_memory("Garden planning notes", "u1", "note", tags=["garden"])

    results = db.safe_memory_search("garden", "u1")

    assert results
    assert any("Garden planning" in item["content"] for item in results)


def test_connection_pool_reuses_connection(tmp_path):
    db_path = tmp_path / "mentat_sqlite.db"
    db = MemoryDatabase(db_path=str(db_path))

    with db.db_pool.get_connection() as first_conn:
        first_id = id(first_conn)

    with db.db_pool.get_connection() as second_conn:
        second_id = id(second_conn)

    assert first_id == second_id


def test_delete_memory_removes_from_fts(tmp_path):
    db_path = tmp_path / "mentat_sqlite.db"
    db = MemoryDatabase(db_path=str(db_path))

    memory_id = db.save_memory("FTS removal test", "u1", "note", tags=["fts"])
    assert db.safe_memory_search("FTS removal", "u1")

    db.delete_memory(memory_id, "u1")

    assert db.safe_memory_search("FTS removal", "u1") == []
