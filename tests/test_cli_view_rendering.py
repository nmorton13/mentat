from mentat.cli import mentat
from rich.text import Text


def test_help_text_does_not_enable_strikethrough():
    rendered = Text.from_markup(mentat.HELP_TEXT)

    assert all(str(span.style) not in {"s", "strike"} for span in rendered.spans)
    assert "/mark <number(s)>" in rendered.plain


def test_build_view_panel_link_uses_markdown_renderer(monkeypatch):
    captured = {}

    def fake_render_markdown(content, title, subtitle, border_style):
        captured["content"] = content
        captured["title"] = title
        return "markdown_panel"

    monkeypatch.setattr(mentat, "render_markdown_to_panel", fake_render_markdown)

    item = {
        "content": "Title: Example\nURL: https://example.com\nSummary: Summary text",
        "command_type": "link",
        "tags": ["alpha"],
        "timestamp": "2025-06-01",
    }

    panel = mentat.build_view_panel(item, 2)

    assert panel == "markdown_panel"
    assert "https://example.com" in captured["content"]
    assert captured["title"].startswith("📄 Item 2")


def test_build_view_panel_markdown_branch(monkeypatch):
    monkeypatch.setattr(mentat, "should_use_markdown_rendering", lambda _: True)

    def fake_render_markdown(content, title, subtitle, border_style):
        return {"content": content, "title": title}

    monkeypatch.setattr(mentat, "render_markdown_to_panel", fake_render_markdown)

    item = {
        "content": "# Header",
        "command_type": "note",
        "tags": [],
        "timestamp": "2025-06-01",
    }

    panel = mentat.build_view_panel(item, 1)

    assert panel["title"].startswith("📄 Item 1")
    assert "# Header" in panel["content"]


def test_build_view_panel_plain_text_branch(monkeypatch):
    monkeypatch.setattr(mentat, "should_use_markdown_rendering", lambda _: False)
    monkeypatch.setattr(mentat, "format_content_with_markdown", lambda content: f"FORMATTED:{content}")

    def fake_create_panel(content, title, subtitle, border_style):
        return {"content": content, "title": title}

    monkeypatch.setattr(mentat, "create_standard_panel", fake_create_panel)

    item = {
        "content": "Just text",
        "command_type": "note",
        "tags": ["alpha"],
        "timestamp": "2025-06-01",
    }

    panel = mentat.build_view_panel(item, 3)

    assert panel["title"].startswith("📄 Item 3")
    assert "FORMATTED:Just text" in panel["content"]
