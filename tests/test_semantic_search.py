from mentat.core.database import MemoryDatabase


def test_brute_sem_search_returns_best_match(tmp_path):
    db_path = tmp_path / "mentat_semantic.db"
    db = MemoryDatabase(db_path=str(db_path))

    first_id = db.save_memory("Alpha memory", "u1", "note")
    second_id = db.save_memory("Beta memory", "u1", "note")

    db.save_embedding(first_id, [1.0, 0.0])
    db.save_embedding(second_id, [0.0, 1.0])

    results = db.brute_sem_search([1.0, 0.0], k=1, min_similarity=0.0)

    assert results
    assert results[0][0] == first_id


def test_find_entity_connections_orders_by_shared_entities(tmp_path):
    db_path = tmp_path / "mentat_entities.db"
    db = MemoryDatabase(db_path=str(db_path))

    meta_one = {"entities": {"projects": ["Mentat"], "technologies": ["Python"]}}
    meta_two = {"entities": {"projects": ["Mentat"]}}

    first_id = db.save_memory("First", "u1", "note", metadata=meta_one)
    second_id = db.save_memory("Second", "u1", "note", metadata=meta_two)

    connections = db.find_entity_connections(
        {"projects": ["Mentat"], "technologies": ["Python"]},
        "u1",
        k=2
    )

    assert connections[0][0]["id"] == first_id
    assert connections[1][0]["id"] == second_id


def test_find_entity_connections_excludes_id(tmp_path):
    db_path = tmp_path / "mentat_entities.db"
    db = MemoryDatabase(db_path=str(db_path))

    meta = {"entities": {"projects": ["Mentat"]}}
    first_id = db.save_memory("First", "u1", "note", metadata=meta)
    second_id = db.save_memory("Second", "u1", "note", metadata=meta)

    connections = db.find_entity_connections(
        {"projects": ["Mentat"]},
        "u1",
        k=5,
        exclude_id=first_id
    )

    assert all(item[0]["id"] != first_id for item in connections)
    assert connections and connections[0][0]["id"] == second_id
