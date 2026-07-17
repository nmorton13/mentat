import asyncio

from mentat.cli import voice_command as voice_module


class DummySession:
    def __init__(self, update_queue, user_id, auto_capture=True):
        self.update_queue = update_queue
        self.user_id = user_id
        self.auto_capture = auto_capture
        self.cleanup_called = False

    async def start_session(self):
        await self.update_queue.put({"type": "exit"})

    async def end_session(self):
        return {"transcript": [], "duration": "0:00"}

    async def capture_conversation_from_data(self, data):
        return None

    def cleanup_audio(self):
        self.cleanup_called = True


class DummyView:
    def __init__(self):
        self.render_calls = 0

    async def render(self, update_queue):
        self.render_calls += 1
        await asyncio.sleep(0)


def test_voice_command_runs_and_cleans_up(monkeypatch):
    created = {}

    def make_session(update_queue, user_id, auto_capture=True):
        created["session"] = DummySession(update_queue, user_id, auto_capture)
        return created["session"]

    monkeypatch.setattr(voice_module, "MentatVoiceSession", make_session)
    monkeypatch.setattr(voice_module, "VoiceView", DummyView)

    asyncio.run(voice_module.voice_command(user_id="u1", auto_capture=True))

    assert created["session"].cleanup_called is True
