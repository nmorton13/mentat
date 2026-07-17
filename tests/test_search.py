import json

from mentat.cli import commands
from mentat.core.database import MemoryDatabase


def test_search_ai_responses_finds_ai_metadata(tmp_path):
    db_path = tmp_path / "mentat_ai.db"
    db = MemoryDatabase(db_path=str(db_path))

    metadata = {"source": {"type": "ai_response", "model": "test-model"}}
    db.save_memory(
        "AI response content",
        "u1",
        "ai_response",
        tags=["ai"],
        metadata=metadata
    )

    results = commands.search_ai_responses("ai response", "u1", db, openai_client=None)

    assert len(results) == 1
    assert results[0]["content"] == "AI response content"


def test_get_all_memories_excludes_ai_responses(tmp_path):
    db_path = tmp_path / "mentat_latest.db"
    db = MemoryDatabase(db_path=str(db_path))

    db.save_memory("Direct thought", "u1", "note", tags=["thought"])
    db.save_memory(
        "Saved AI reply",
        "u1",
        "ai_response",
        tags=["ai_response"],
        metadata={"source": {"type": "ai_response", "model": "test-model"}},
    )

    memories = db.get_all_memories("u1", limit=10)

    assert [memory["content"] for memory in memories] == ["Direct thought"]


def test_saved_ai_response_is_searchable_but_not_latest(monkeypatch, tmp_path):
    db_path = tmp_path / "mentat_saved_ai.db"
    db = MemoryDatabase(db_path=str(db_path))

    monkeypatch.setattr(commands.console, "print", lambda *args, **kwargs: None)

    commands.handle_save_response(
        user_id="u1",
        current_model="z-ai/glm-5.2",
        openrouter_client=None,
        openai_client=None,
        db=db,
        last_displayed_items=[],
        last_ai_response="A useful AI reply about attention residue",
        last_ai_response_command="chat",
        last_ai_prompt="What am I missing here?",
        clear_response_callback=None,
    )

    latest_memories = db.get_all_memories("u1", limit=10)
    ai_results = commands.search_ai_responses("attention residue", "u1", db, openai_client=None)

    assert latest_memories == []
    assert len(ai_results) == 1
    assert ai_results[0]["content"] == "A useful AI reply about attention residue"


def test_display_ai_search_results_updates_last_displayed(monkeypatch):
    last_displayed_items = []
    captured = {}

    def fake_print_tool_reply(content, title, subtitle, border_style):
        captured["content"] = content
        captured["title"] = title

    monkeypatch.setattr(commands, "print_tool_reply", fake_print_tool_reply)
    monkeypatch.setattr(commands.console, "print", lambda *args, **kwargs: None)

    results = [
        {
            "content": "Response text",
            "command_type": "ai_response",
            "tags": ["ai"],
            "timestamp": "2025-06-01",
            "metadata": json.dumps({"source": {"type": "ai_response", "model": "test"}}),
            "why_matched": "AI response match",
        }
    ]

    commands.display_ai_search_results(results, "ai response", last_displayed_items)

    assert last_displayed_items == results
    assert "Found 1 AI responses" in captured["content"]


def test_display_ai_search_results_includes_prompt_preview(monkeypatch):
    captured = {}

    def fake_print_tool_reply(content, title, subtitle, border_style):
        captured["content"] = content

    monkeypatch.setattr(commands, "print_tool_reply", fake_print_tool_reply)
    monkeypatch.setattr(commands.console, "print", lambda *args, **kwargs: None)

    results = [
        {
            "content": "Response text",
            "command_type": "ai_response",
            "tags": ["ai"],
            "timestamp": "2025-06-01",
            "metadata": json.dumps(
                {
                    "source": {
                        "type": "ai_response",
                        "model": "test",
                        "prompt": "What did I ask the AI about?",
                    }
                }
            ),
            "why_matched": "AI response match",
        }
    ]

    commands.display_ai_search_results(results, "ai response", [])

    assert "Prompt:" in captured["content"]
    assert "What did I ask the AI about?" in captured["content"]
    assert "Response:" in captured["content"]


def test_hybrid_search_returns_keyword_result(tmp_path):
    from mentat.chat.enhanced_chat import EnhancedChatSystem

    db_path = tmp_path / "mentat_hybrid.db"
    db = MemoryDatabase(db_path=str(db_path))
    db.save_memory("Hybrid keyword match", "u1", "note", tags=["hybrid"])

    chat = EnhancedChatSystem(db, openrouter_client=None)
    chat.openai_client = None

    results = chat._hybrid_search("u1", "keyword", k=5)

    assert results
    assert results[0]["content"] == "Hybrid keyword match"


def test_hybrid_search_marks_keyword_duplicate(monkeypatch, tmp_path):
    from mentat.chat import enhanced_chat

    db_path = tmp_path / "mentat_hybrid.db"
    db = MemoryDatabase(db_path=str(db_path))
    memory_id = db.save_memory("Semantic keyword overlap", "u1", "note", tags=["hybrid"])
    db.save_embedding(memory_id, [1.0, 0.0])

    chat = enhanced_chat.EnhancedChatSystem(db, openrouter_client=None)
    chat.openai_client = object()

    monkeypatch.setattr(enhanced_chat, "get_embedding_for_content", lambda *args, **kwargs: [1.0, 0.0])

    results = chat._hybrid_search("u1", "Semantic keyword", k=5)

    assert results
    assert "Keyword match" in results[0]["why_matched"]
