from datetime import datetime

import pytest

from mentat.chat import temporal


class FixedDateTime:
    """Datetime shim for deterministic tests."""

    fixed_now = None

    @classmethod
    def now(cls):
        return cls.fixed_now


@pytest.mark.parametrize(
    "fixed_now,expected_start,expected_end",
    [
        (datetime(2025, 11, 15), "2025-06-01", "2025-08-31"),
        (datetime(2025, 2, 10), "2024-06-01", "2024-08-31"),
    ],
)
def test_last_summer_resolves_to_most_recent_season(monkeypatch, fixed_now, expected_start, expected_end):
    FixedDateTime.fixed_now = fixed_now
    monkeypatch.setattr(temporal, "datetime", FixedDateTime)

    result = temporal.extract_temporal_intent("What did I do last summer?", client=object())

    assert result["has_temporal_intent"] is True
    assert result["start_date"] == expected_start
    assert result["end_date"] == expected_end


def test_temporal_thinking_retrospective_is_treated_as_generic(monkeypatch):
    FixedDateTime.fixed_now = datetime(2026, 6, 30)
    monkeypatch.setattr(temporal, "datetime", FixedDateTime)

    result = temporal.extract_temporal_intent("What was I thinking about last month?", client=object())

    assert result["has_temporal_intent"] is True
    assert result["query_without_temporal"] == ""
