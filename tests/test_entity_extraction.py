import json
import types

from mentat.core import ai


class DummyResponse:
    def __init__(self, content):
        self.choices = [types.SimpleNamespace(message=types.SimpleNamespace(content=content))]


class DummyCompletions:
    def __init__(self, content):
        self.content = content

    def create(self, **kwargs):
        return DummyResponse(self.content)


class DummyClient:
    def __init__(self, content):
        self.chat = types.SimpleNamespace(completions=DummyCompletions(content))


def test_extract_structured_entities_with_client():
    payload = {
        "people": ["Ada"],
        "organizations": ["OpenAI"],
        "technologies": ["Python"],
        "projects": ["MENTAT"],
        "concepts": ["knowledge management"],
        "locations": ["Paris"],
        "dates": ["2025-06-01"],
    }
    client = DummyClient(json.dumps(payload))

    entities = ai.extract_structured_entities("Ada built MENTAT", client=client)

    assert entities["people"] == ["Ada"]
    assert entities["projects"] == ["MENTAT"]


def test_extract_structured_entities_without_client():
    entities = ai.extract_structured_entities("No client provided")

    assert entities["people"] == []
