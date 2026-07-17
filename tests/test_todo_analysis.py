import json

from mentat.core import ai
from mentat.core.database import MemoryDatabase


def test_extract_todos_from_content_without_client():
    todos = ai.extract_todos_from_content("Remember to call Sam")

    assert todos == []


def test_update_todo_status_marks_complete(tmp_path):
    db_path = tmp_path / "mentat_todo.db"
    db = MemoryDatabase(db_path=str(db_path))

    metadata = {
        "actionable_items": [
            {"action": "finish draft", "status": "pending"}
        ]
    }

    memory_id = db.save_memory(
        "Finish the draft",
        "u1",
        "task",
        tags=["todo"],
        metadata=metadata
    )

    db.update_todo_status(memory_id, 0, "done")

    updated = db.get_memory_by_id(memory_id, "u1")
    updated_metadata = json.loads(updated["metadata"])

    assert updated_metadata["actionable_items"][0]["status"] == "done"


def test_get_user_todos_backfills_persisted_todo_ids(tmp_path):
    db_path = tmp_path / "mentat_todo.db"
    db = MemoryDatabase(db_path=str(db_path))

    memory_id = db.save_memory(
        "Finish the draft",
        "u1",
        "task",
        tags=["todo"],
        metadata={"actionable_items": [{"action": "finish draft", "status": "pending"}]}
    )

    todos = db.get_user_todos("u1", status_filter=None)
    updated = db.get_memory_by_id(memory_id, "u1")
    updated_metadata = json.loads(updated["metadata"])

    assert todos[0]["todo_id"].startswith("todo_")
    assert updated_metadata["actionable_items"][0]["todo_id"] == todos[0]["todo_id"]


def test_update_todo_status_by_id_survives_reorder(tmp_path):
    db_path = tmp_path / "mentat_todo.db"
    db = MemoryDatabase(db_path=str(db_path))

    memory_id = db.save_memory(
        "Finish the draft and send the note",
        "u1",
        "task",
        tags=["todo"],
        metadata={
            "actionable_items": [
                {"todo_id": "todo_first", "action": "finish draft", "status": "pending"},
                {"todo_id": "todo_second", "action": "send note", "status": "pending"},
            ]
        }
    )
    memory = db.get_memory_by_id(memory_id, "u1")
    metadata = json.loads(memory["metadata"])
    metadata["actionable_items"].reverse()
    with db.db_pool.get_connection() as conn:
        conn.execute(
            "UPDATE memories SET metadata = ? WHERE id = ?",
            (json.dumps(metadata), memory_id),
        )

    result = db.update_todo_status_by_id("u1", "todo_first", "done")
    updated = db.get_memory_by_id(memory_id, "u1")
    updated_metadata = json.loads(updated["metadata"])
    statuses = {
        item["todo_id"]: item["status"]
        for item in updated_metadata["actionable_items"]
    }

    assert result["todo_id"] == "todo_first"
    assert statuses["todo_first"] == "done"
    assert statuses["todo_second"] == "pending"
