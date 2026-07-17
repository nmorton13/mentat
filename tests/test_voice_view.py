import asyncio

from mentat.voice_ui.view import VoiceView


def test_update_transcript_merges_same_role():
    view = VoiceView()
    view.update_transcript("YOU", "Hello")
    view.update_transcript("YOU", "Hello again")

    assert len(view.messages) == 1
    assert view.messages[0]["text"] == "Hello again"


def test_update_transcript_appends_new_role():
    view = VoiceView()
    view.update_transcript("YOU", "Hello")
    view.update_transcript("ASSISTANT", "Hi")

    assert len(view.messages) == 2
    assert view.messages[1]["role"] == "ASSISTANT"


def test_update_status_bar_formats_timer():
    view = VoiceView()
    panel = view.update_status_bar()

    assert "Press Ctrl+C to End" in panel.renderable


def test_rebuild_transcript_shows_recent_only():
    view = VoiceView()
    for i in range(6):
        role = "YOU" if i % 2 == 0 else "ASSISTANT"
        view.update_transcript(role, f"Message {i}")

    assert len(view.messages) == 6
    assert "Showing last" in view.transcript_content.plain


def test_render_updates_status_and_transcript():
    async def _run():
        view = VoiceView()
        queue = asyncio.Queue()

        await queue.put({"type": "status", "value": "THINKING"})
        await queue.put({"type": "transcript", "role": "YOU", "text": "Test"})
        await queue.put({"type": "exit"})

        render_task = asyncio.create_task(view.render(queue))
        await asyncio.wait_for(render_task, timeout=2)

        assert view.status == "ENDING"
        assert view.messages[-1]["text"] == "Test"

    asyncio.run(_run())
