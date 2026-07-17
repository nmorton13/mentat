from mentat.chat.enhanced_chat import EnhancedChatSystem


class DummyDB:
    pass


def test_detect_intent_standard_for_personal():
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=None)

    assert chat._detect_intent("Show me my notes on caching") == "standard"


def test_detect_intent_standard_for_long_personal_reflection_query():
    chat = EnhancedChatSystem(DummyDB(), openrouter_client=None)

    query = (
        "What are the central ideas of my Beautiful Mess Theory and how does it "
        "relate to my thinking in general?"
    )
    assert chat._detect_intent(query) == "standard"
