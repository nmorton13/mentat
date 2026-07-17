from mentat.concepts import concept_explorer, concept_integration
from mentat.concepts.concept_explorer import ConceptNode, MentatConceptExplorer
from mentat.concepts.concept_integration import ConceptIntegrationManager
from mentat.core.llm import LLMRoute


class DummyDB:
    def get_all_memories(self, user_id):
        return []

    def comprehensive_search(self, user_id, concept):
        return [
            {
                "content": "Mentat uses wrapper cleanup to simplify LLM calls.",
                "timestamp": "2026-06-18",
            }
        ]


class ExplodingCompletions:
    def create(self, **kwargs):
        raise AssertionError("concept calls should use the LLM wrapper")


class ExplodingClient:
    chat = type("Chat", (), {"completions": ExplodingCompletions()})()


def test_format_concept_web_display_handles_empty():
    manager = ConceptIntegrationManager(DummyDB(), openrouter_client=None)

    assert manager.format_concept_web_display({}, depth_level=1) == ""


def test_deep_concept_tree_hint_matches_execution_context():
    manager = ConceptIntegrationManager(DummyDB(), openrouter_client=None)
    concept_tree = {
        "root": "machine learning",
        "concepts": [
            {
                "name": "Generative Soundscapes",
                "number": 25,
                "domain": "creative",
                "novelty": 0.8,
                "sub_concepts": [],
            }
        ],
    }

    interactive = manager.format_deep_hierarchical_concept_tree(concept_tree, interactive=True)
    one_shot = manager.format_deep_hierarchical_concept_tree(concept_tree, interactive=False)

    assert "/explain <number>" in interactive
    assert 'mentat explain "<concept>"' in one_shot
    assert "/explain <number>" not in one_shot


def test_get_diverse_concepts_uses_llm_wrapper(monkeypatch):
    calls = []

    def fake_complete(client, model, messages, **kwargs):
        calls.append(
            {
                "client": client,
                "model": model,
                "messages": messages,
                "kwargs": kwargs,
            }
        )
        return '[{"name": "Wrapper Cleanup", "domain": "tech"}]'

    monkeypatch.setattr(concept_explorer, "complete", fake_complete)
    monkeypatch.setattr(
        concept_explorer,
        "get_task_llm_route",
        lambda prefix, client: LLMRoute("chat", client, "test-concept-model"),
    )

    explorer = MentatConceptExplorer(ExplodingClient())
    result = explorer.get_diverse_concepts("Mentat", count=1)

    assert result == [
        {
            "name": "Wrapper Cleanup",
            "description": "Related to Mentat",
            "domain": "tech",
            "confidence": 0.8,
            "novelty_score": 0.5,
        }
    ]
    assert calls[0]["client"] is explorer.client
    assert calls[0]["model"] == "test-concept-model"
    assert calls[0]["kwargs"] == {"max_tokens": 800, "temperature": 0.7}
    assert "Generate 1 concepts related to" in calls[0]["messages"][0]["content"]


def test_generate_concepts_batch_uses_llm_wrapper(monkeypatch):
    calls = []

    def fake_complete(client, model, messages, **kwargs):
        calls.append(
            {
                "client": client,
                "model": model,
                "messages": messages,
                "kwargs": kwargs,
            }
        )
        return '{"Parent": [{"name": "Child Concept", "domain": "science"}]}'

    monkeypatch.setattr(concept_explorer, "complete", fake_complete)
    monkeypatch.setattr(
        concept_explorer,
        "get_task_llm_route",
        lambda prefix, client: LLMRoute("chat", client, "test-concept-model"),
    )

    explorer = MentatConceptExplorer(ExplodingClient())
    result = explorer._batch_generate_child_concepts(
        [ConceptNode("Parent")],
        depth=1,
        max_concepts=1,
        user_knowledge_context=[],
        existing_concepts=[],
    )

    assert result["Parent"] == [
        {
            "name": "Child Concept",
            "description": "Related to Parent",
            "domain": "science",
            "confidence": 0.8,
            "novelty_score": 0.5,
        }
    ]
    assert calls[0]["model"] == "test-concept-model"
    assert calls[0]["kwargs"] == {"max_tokens": 800, "temperature": 0.4}
    assert "Parents: Parent" in calls[0]["messages"][0]["content"]


def test_explain_concept_uses_llm_wrapper(monkeypatch):
    calls = []

    def fake_complete(client, model, messages, **kwargs):
        calls.append(
            {
                "client": client,
                "model": model,
                "messages": messages,
                "kwargs": kwargs,
            }
        )
        return "**What it is:** A wrapper cleanup."

    monkeypatch.setattr(concept_integration, "complete", fake_complete)

    manager = ConceptIntegrationManager(DummyDB(), openrouter_client=ExplodingClient())
    result = manager.generate_concept_explanation("LLM wrapper", "user1", current_model="test-model")

    assert result.startswith("**What it is:** A wrapper cleanup.")
    assert "**From your memories:**" in result
    assert calls[0]["client"] is manager.client
    assert calls[0]["model"] == "test-model"
    assert calls[0]["kwargs"] == {"max_tokens": 600, "temperature": 0.3}
    assert "LLM wrapper" in calls[0]["messages"][0]["content"]
