from mentat.cli import mentat


def test_should_prioritize_ai_references_prefers_ai_when_only_ai():
    assert mentat.should_prioritize_ai_references(
        last_command="chat",
        has_ai_references=True,
        has_search_results=False
    ) is True


def test_should_prioritize_ai_references_prefers_search_for_search_commands():
    assert mentat.should_prioritize_ai_references(
        last_command="search",
        has_ai_references=True,
        has_search_results=True
    ) is False


def test_should_prioritize_ai_references_defaults_to_ai_when_available():
    assert mentat.should_prioritize_ai_references(
        last_command="chat",
        has_ai_references=True,
        has_search_results=True
    ) is True


def test_select_view_item_prefers_display_number():
    items = [
        {"original_todo": {"display_number": 7}, "content": "todo"},
        {"content": "other"},
    ]

    selected = mentat.select_view_item(7, items)

    assert selected["content"] == "todo"


def test_select_view_item_falls_back_to_index():
    items = [
        {"content": "first"},
        {"content": "second"},
    ]

    selected = mentat.select_view_item(2, items)

    assert selected["content"] == "second"


def test_build_view_panel_uses_markdown_metadata_for_ai_response(monkeypatch):
    captured = {}

    def fake_render_markdown_to_panel(text, title, subtitle=None, border_style="bright_blue"):
        captured["text"] = text
        captured["title"] = title
        return object()

    monkeypatch.setattr(mentat, "render_markdown_to_panel", fake_render_markdown_to_panel)

    item = {
        "content": "# Saved AI reply\n\nThis is the full response.",
        "command_type": "reflection",
        "tags": ["ai", "philosophy"],
        "timestamp": "2025-08-28 16:07:56",
        "metadata": {
            "source": {
                "type": "ai_response",
                "model": "x-ai/grok-4",
            }
        },
    }

    mentat.build_view_panel(item, 3)

    assert "[bright_green]" not in captured["text"]
    assert "**Source:** x-ai/grok-4 response" in captured["text"]
    assert "**Type:** AI_RESPONSE" in captured["text"]
