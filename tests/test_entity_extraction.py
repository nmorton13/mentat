import json
import types

from mentat.core import ai
from mentat.core import config


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


def test_extract_structured_entities_with_client(monkeypatch):
    monkeypatch.setattr(config, "ENTITY_EXTRACTION_PROVIDER", "chat")
    monkeypatch.setattr(config, "ENTITY_EXTRACTION_MODEL", None)
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


def test_extract_structured_entities_without_client(monkeypatch):
    monkeypatch.setattr(config, "ENTITY_EXTRACTION_PROVIDER", "chat")
    monkeypatch.setattr(config, "ENTITY_EXTRACTION_MODEL", None)
    entities = ai.extract_structured_entities("No client provided")

    assert entities["people"] == []
