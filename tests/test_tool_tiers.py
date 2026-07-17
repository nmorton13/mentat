from mentat.chat.tools import get_tools


def _names(tools):
    return [t["function"]["name"] for t in tools]


def test_default_chat_uses_tier1_only():
    names = _names(get_tools(channel="chat", schema="openai"))
    assert "capture_thought" in names
    assert "find_related_thoughts" in names


def test_tier2_keeps_memory_tools_only():
    names = _names(get_tools(channel="chat", schema="openai", metadata={"tool_tier": "tier2"}))
    assert "capture_thought" in names
    assert "find_related_thoughts" in names
    assert "get_recent_activity" in names


def test_voice_keeps_voice_capable_tools():
    names = _names(get_tools(channel="voice", schema="openai"))
    assert "capture_thought" in names
    assert "get_recent_activity" not in names
