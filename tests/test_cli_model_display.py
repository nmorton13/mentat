def test_display_models_table_marks_current(monkeypatch):
    from mentat.cli import display

    monkeypatch.setattr(
        display,
        "AVAILABLE_MODELS",
        {
            "grok": "x-ai/grok-4.5",
            "gpt-5": "openai/gpt-5.6-terra",
        },
        raising=False,
    )

    with display.console.capture() as capture:
        display.display_models_table("openai/gpt-5.6-terra")

    output = capture.get()
    assert "gpt-5" in output
    assert "openai/gpt-5.6-terra" in output
    assert "Current" in output


def test_banner_uses_mentat_acronym():
    from mentat.cli import display

    with display.console.capture() as capture:
        display.print_banner()

    output = capture.get()
    assert "Mental Enhancement Node for Thought Analysis and Transformation" in output
    assert "Selective capture, search, reflection, and connection" in output
