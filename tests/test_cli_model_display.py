def test_display_models_table_marks_current(monkeypatch):
    from mentat.cli import display

    monkeypatch.setattr(
        display,
        "AVAILABLE_MODELS",
        {
            "grok": "x-ai/grok-4.1-fast",
            "gpt-5": "openai/gpt-5.2-chat",
        },
        raising=False,
    )

    with display.console.capture() as capture:
        display.display_models_table("openai/gpt-5.2-chat")

    output = capture.get()
    assert "gpt-5" in output
    assert "openai/gpt-5.2-chat" in output
    assert "Current" in output
