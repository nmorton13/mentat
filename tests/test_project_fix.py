from mentat.core import database
from mentat.core.prompts import PROJECT_DASHBOARD_PROMPT


def test_database_analyze_project_progress_uses_llm_wrapper(monkeypatch, tmp_path):
    calls = []

    def fake_complete(client, model, messages, **kwargs):
        calls.append(
            {
                "client": client,
                "model": model,
                "messages": messages,
                "kwargs": kwargs,
            }
        )
        return "Project dashboard"

    monkeypatch.setattr(database, "complete", fake_complete)

    db = database.MemoryDatabase(db_path=str(tmp_path / "mentat.db"))
    client = object()
    project_data = {
        "all_content": [
            {
                "command_type": "idea",
                "content": "Build a smaller LLM wrapper cleanup slice.",
                "timestamp": "2026-06-18",
                "tags": ["mentat", "llm"],
            }
        ],
        "links": [],
        "ideas": [],
        "questions": [],
        "thoughts": [],
    }

    result = db.analyze_project_progress(
        project_data,
        "Mentat",
        openai_client=client,
        model="test-model",
    )

    assert result == "Project dashboard"
    assert calls[0]["client"] is client
    assert calls[0]["model"] == "test-model"
    assert calls[0]["kwargs"] == {}
    assert calls[0]["messages"][0] == {"role": "system", "content": PROJECT_DASHBOARD_PROMPT}
    assert "Project: Mentat" in calls[0]["messages"][1]["content"]
