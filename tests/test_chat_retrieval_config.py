from mentat.core.config import (
    resolve_chat_retrieval_limits,
    resolve_reflection_corpus_limits,
)


def test_chat_retrieval_limits_scale_to_current_defaults(monkeypatch):
    for name in (
        "CHAT_HYBRID_SEARCH_K",
        "HYBRID_SEARCH_INTERNAL_MULTIPLIER",
        "CHAT_CONTEXT_LIMIT",
    ):
        monkeypatch.delenv(name, raising=False)

    expected = {
        0: (0, 1.0, 0),
        10: (10, 1.0, 10),
        20: (20, 1.0, 20),
        25: (25, 1.0, 25),
        40: (25, 1.6, 40),
        50: (25, 2.0, 50),
        100: (25, 3.0, 50),
        243: (25, 3.0, 50),
        1000: (25, 3.0, 50),
    }

    for memory_count, values in expected.items():
        limits = resolve_chat_retrieval_limits(memory_count)
        assert (
            limits["search_k"],
            limits["internal_multiplier"],
            limits["context_limit"],
        ) == values


def test_explicit_chat_retrieval_limits_override_automatic_values(monkeypatch):
    monkeypatch.setenv("CHAT_HYBRID_SEARCH_K", "12")
    monkeypatch.setenv("HYBRID_SEARCH_INTERNAL_MULTIPLIER", "4.5")
    monkeypatch.setenv("CHAT_CONTEXT_LIMIT", "18")

    assert resolve_chat_retrieval_limits(243) == {
        "search_k": 12,
        "internal_multiplier": 4.5,
        "context_limit": 18,
    }


def test_chat_retrieval_limits_allow_partial_overrides(monkeypatch):
    monkeypatch.delenv("CHAT_HYBRID_SEARCH_K", raising=False)
    monkeypatch.delenv("HYBRID_SEARCH_INTERNAL_MULTIPLIER", raising=False)
    monkeypatch.setenv("CHAT_CONTEXT_LIMIT", "30")

    assert resolve_chat_retrieval_limits(40) == {
        "search_k": 25,
        "internal_multiplier": 1.6,
        "context_limit": 30,
    }


def test_reflection_corpus_limits_scale_without_manual_tuning():
    expected = {
        0: 0,
        10: 10,
        50: 50,
        51: 51,
        100: 60,
        101: 70,
        250: 70,
        251: 80,
        500: 80,
        501: 100,
        1000: 100,
    }

    for memory_count, memory_limit in expected.items():
        assert resolve_reflection_corpus_limits(memory_count) == {
            "memory_limit": memory_limit,
            "max_corpus_chars": 60_000,
        }
