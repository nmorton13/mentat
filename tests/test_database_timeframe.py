from mentat.core.database import MemoryDatabase


def _set_timestamp(db, memory_id, timestamp):
    with db.db_pool.get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE memories SET timestamp = ? WHERE id = ?",
            (timestamp, memory_id)
        )


def test_search_by_timeframe_filters_by_date_and_excludes_ai(tmp_path):
    db_path = tmp_path / "mentat_test.db"
    db = MemoryDatabase(db_path=str(db_path))

    note_id = db.save_memory("Garden work", "u1", "note", tags=["garden"])
    ai_id = db.save_memory("AI response content", "u1", "ai_response", tags=["ai"])

    _set_timestamp(db, note_id, "2025-06-15 10:00:00")
    _set_timestamp(db, ai_id, "2025-06-16 12:00:00")

    results = db.search_by_timeframe("u1", start_date="2025-06-01", end_date="2025-06-30")

    assert len(results) == 1
    assert results[0]["id"] == note_id
    assert results[0]["content"] == "Garden work"


def test_search_by_timeframe_applies_query_filter(tmp_path):
    db_path = tmp_path / "mentat_test.db"
    db = MemoryDatabase(db_path=str(db_path))

    first_id = db.save_memory("Database migration work", "u1", "note", tags=["db"])
    second_id = db.save_memory("Team sync meeting", "u1", "note", tags=["meeting"])

    _set_timestamp(db, first_id, "2025-06-20 10:00:00")
    _set_timestamp(db, second_id, "2025-06-21 10:00:00")

    results = db.search_by_timeframe(
        "u1",
        query="database",
        start_date="2025-06-01",
        end_date="2025-06-30"
    )

    assert len(results) == 1
    assert results[0]["content"] == "Database migration work"
