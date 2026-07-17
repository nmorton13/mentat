import hashlib
from datetime import datetime

from mentat.core import ai, prompts


PROMPT_HASHES = {
    "capture_analysis": "15f0d69e064ff3f0d45c526b78250715ef10d91332efd0e0037553d0094802c8",
    "todo_extraction": "e308e8c4ab05ad037c25075cc41c48f140550fd5a7922608799852ce1d0295df",
    "multi_todo_extraction": "d53e3687c6c52e74065c7567e64b0e6c26b3470c38e8484b6662a0cda80902fe",
    "entity_extraction": "c054c7a7659c16b7cbfc7c8f54c54975a49b7854687af195d52a82be1596396a",
    "synthesize_notes": "7d690fa8517e6390e364b87c9327930dea2462e055a1da145092db340e84b77d",
    "project_dashboard": "a28f7a7b0fa4f8465ec3a116ac5bc2a02931c3363f49d48a3c8fd03c42b44796",
    "weekly_summary": "b641cb275ca3cf9ea73a8c37eb4a6dd8f5b6692f7c5c12096690aa35e1ee03b4",
    "thought_analysis": "2635aa2c074ad321bf2a4742beec476977674429b9c69c728628f7ebd341a2e8",
}


def _prompt_hash(prompt: str) -> str:
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def test_core_prompt_exports_are_non_empty_strings():
    prompt_names = [
        "THOUGHT_ANALYSIS_PROMPT",
        "PROJECT_DASHBOARD_PROMPT",
        "WEEKLY_SUMMARY_PROMPT",
        "TODO_EXTRACTION_PROMPT",
        "MULTI_TODO_EXTRACTION_PROMPT",
        "SYNTHESIZE_NOTES_PROMPT",
        "ENTITY_EXTRACTION_PROMPT",
    ]

    for name in prompt_names:
        value = getattr(prompts, name)
        assert isinstance(value, str)
        assert value.strip()


def test_capture_analysis_prompt_includes_expected_schema_keys_and_hint():
    prompt = prompts.get_capture_analysis_prompt("task")

    assert prompt.startswith("The user has specified this is a 'task'.")
    for key in [
        '"type"',
        '"urls"',
        '"enhanced_content"',
        '"summary"',
        '"themes"',
        '"actionable_items"',
        '"entities"',
        '"confidence"',
    ]:
        assert key in prompt

    for entity_key in [
        '"people"',
        '"organizations"',
        '"technologies"',
        '"projects"',
        '"concepts"',
        '"locations"',
        '"dates"',
    ]:
        assert entity_key in prompt


def test_todo_and_entity_prompts_include_required_schema_keys():
    for key in [
        '"todos"',
        '"action"',
        '"context"',
        '"priority"',
        '"time_sensitive"',
        '"project"',
        '"due_date"',
        '"dependencies"',
    ]:
        assert key in prompts.TODO_EXTRACTION_PROMPT

    assert '"source_index"' in prompts.MULTI_TODO_EXTRACTION_PROMPT

    for key in [
        '"people"',
        '"organizations"',
        '"technologies"',
        '"projects"',
        '"concepts"',
        '"locations"',
        '"dates"',
    ]:
        assert key in prompts.ENTITY_EXTRACTION_PROMPT


def test_core_prompt_hashes_make_behavior_wording_changes_intentional():
    """Large prompt wording is product behavior; update hashes only intentionally."""
    prompt_values = {
        "capture_analysis": prompts.get_capture_analysis_prompt(),
        "todo_extraction": prompts.TODO_EXTRACTION_PROMPT,
        "multi_todo_extraction": prompts.MULTI_TODO_EXTRACTION_PROMPT,
        "entity_extraction": prompts.ENTITY_EXTRACTION_PROMPT,
        "synthesize_notes": prompts.SYNTHESIZE_NOTES_PROMPT,
        "project_dashboard": prompts.PROJECT_DASHBOARD_PROMPT,
        "weekly_summary": prompts.WEEKLY_SUMMARY_PROMPT,
        "thought_analysis": prompts.THOUGHT_ANALYSIS_PROMPT,
    }

    assert {name: _prompt_hash(prompt) for name, prompt in prompt_values.items()} == PROMPT_HASHES


def test_temporal_prompt_interpolates_reference_dates_and_schema_keys():
    prompt = prompts.get_temporal_intent_prompt(datetime(2025, 6, 25, 9, 30))

    assert "Current reference date is 2025-06-25" in prompt
    assert '"last week" -> 2025-06-16 to 2025-06-22' in prompt
    assert '"last month" -> 2025-05-01 to 2025-05-31' in prompt
    assert '"yesterday" -> 2025-06-24 to 2025-06-24' in prompt
    assert '"start_date": "2025-06-16"' in prompt
    assert '"end_date": "2025-05-31"' in prompt

    for key in [
        '"has_temporal_intent"',
        '"start_date"',
        '"end_date"',
        '"temporal_context"',
        '"query_without_temporal"',
        '"confidence"',
    ]:
        assert key in prompt

    assert "last_week_start" not in prompt
    assert "last_month_end" not in prompt
    assert "current_datetime" not in prompt


def test_extract_temporal_intent_ai_uses_defined_prompt_dates(monkeypatch):
    class FixedDateTime:
        @classmethod
        def now(cls):
            return datetime(2025, 6, 25, 9, 30)

    class Route:
        client = "temporal-client"
        model = "temporal-model"

    captured = {}

    def fake_complete_json(client, model, messages):
        captured["client"] = client
        captured["model"] = model
        captured["messages"] = messages
        return {
            "has_temporal_intent": True,
            "start_date": "2025-06-16",
            "end_date": "2025-06-22",
            "temporal_context": "last week",
            "query_without_temporal": "what did I do",
            "confidence": 0.95,
        }

    monkeypatch.setattr(ai, "datetime", FixedDateTime)
    monkeypatch.setattr(ai, "get_task_llm_route", lambda *args, **kwargs: Route())
    monkeypatch.setattr(ai, "complete_json", fake_complete_json)

    result = ai.extract_temporal_intent_ai("what did I do last week?", client="chat-client")

    assert result["has_temporal_intent"] is True
    assert captured["client"] == "temporal-client"
    assert captured["model"] == "temporal-model"
    system_prompt = captured["messages"][0]["content"]
    assert '"last week" -> 2025-06-16 to 2025-06-22' in system_prompt
    assert "last_week_start" not in system_prompt
