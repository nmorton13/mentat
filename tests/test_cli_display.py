from mentat.cli import display


def test_make_urls_clickable_preserves_markdown_links():
    text = "See [docs](https://example.com) and https://another.example.com"
    result = display.make_urls_clickable(text)

    assert "[docs](https://example.com)" in result
    assert "[link=https://another.example.com]" in result


def test_make_urls_clickable_skips_existing_rich_links():
    text = "[link=https://example.com]https://example.com[/link]"
    result = display.make_urls_clickable(text)

    assert result == text


def test_should_use_markdown_rendering_detects_markdown():
    assert display.should_use_markdown_rendering("# Header") is True
    assert display.should_use_markdown_rendering("1. Item") is True
    assert display.should_use_markdown_rendering("Plain text only") is False


def test_format_metadata_display_includes_core_fields():
    rendered = display.format_metadata_display(
        tags=["alpha", "beta"],
        date="2025-06-01T10:00:00",
        command_type="note",
        why_matched="keyword match"
    )

    assert "Tags:" in rendered
    assert "Date:" in rendered
    assert "Type:" in rendered
    assert "Why matched:" in rendered


def test_format_numbered_list_item_handles_single_digit():
    assert display.format_numbered_list_item("3. test item") == "3. test item"
    assert display.format_numbered_list_item("10. test item") is None
