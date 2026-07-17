from __future__ import annotations

from datetime import datetime

import pytest

from mentat.core import markdown_export


@pytest.fixture()
def markdown_export_path(tmp_path, monkeypatch):
    monkeypatch.setattr(markdown_export, "MARKDOWN_EXPORT_PATH", str(tmp_path))
    monkeypatch.setattr(markdown_export, "MARKDOWN_EXPORT_ENABLED", True)
    return tmp_path


def test_markdown_frontmatter_merge(markdown_export_path):
    timestamp_one = "2025-12-31T10:15:00"
    timestamp_two = "2025-12-31T11:00:00"

    metadata_one = {
        "entities": {
            "people": ["Jane Doe"],
            "organizations": ["OpenAI"]
        },
        "url": "https://example.com"
    }
    metadata_two = {
        "entities": {
            "projects": ["Mentat"]
        },
        "url": "https://example.org"
    }

    markdown_export.save_memory_to_markdown(
        content="First entry",
        command_type="reflection",
        tags=["#MyTag", "Second Tag"],
        metadata=metadata_one,
        timestamp=timestamp_one,
        user_id="nmorton"
    )
    markdown_export.save_memory_to_markdown(
        content="Second entry",
        command_type="idea",
        tags=["Second Tag", "Third"],
        metadata=metadata_two,
        timestamp=timestamp_two,
        user_id="nmorton"
    )

    file_path = markdown_export.get_markdown_file_path(timestamp_one)
    content = file_path.read_text(encoding="utf-8")

    assert "date: 2025-12-31" in content
    assert 'time: [ "10:15", "11:00" ]' in content
    assert 'type: [ "reflection", "idea" ]' in content
    assert 'tags: [ "mytag", "second-tag", "third" ]' in content
    assert 'people: [ "Jane Doe" ]' in content
    assert 'orgs: [ "OpenAI" ]' in content
    assert 'projects: [ "Mentat" ]' in content
    assert 'source_url: [ "https://example.com", "https://example.org" ]' in content


def test_markdown_wikilinks_and_action_items(markdown_export_path):
    timestamp = datetime(2025, 12, 31, 14, 30).isoformat()
    metadata = {
        "entities": {
            "people": ["Ada Lovelace"],
            "projects": ["Analytical Engine"]
        },
        "actionable_items": [
            {
                "action": "Review notes",
                "priority": "high",
                "context": "Follow up later"
            }
        ]
    }

    markdown_export.save_memory_to_markdown(
        content="Testing links and actions",
        command_type="task",
        tags=["#Test"],
        metadata=metadata,
        timestamp=timestamp,
        user_id="nmorton"
    )

    file_path = markdown_export.get_markdown_file_path(timestamp)
    content = file_path.read_text(encoding="utf-8")

    assert "[[Ada-Lovelace]]" in content
    assert "[[Analytical-Engine]]" in content
    assert "✅ **Action Items:**\n  - Review notes [high]\n  *Context:* Follow up later" in content


def test_markdown_ai_response_includes_source_details(markdown_export_path):
    timestamp = "2025-12-31T16:45:00"
    metadata = {
        "source": {
            "type": "ai_response",
            "model": "z-ai/glm-4.7",
            "command": "chat",
            "context": "chat_response",
            "timestamp": timestamp,
            "prompt": "Does Beautiful Mess clash with First Principle thinking?",
        }
    }

    markdown_export.save_memory_to_markdown(
        content="This was an AI reply worth saving.",
        command_type="reflection",
        tags=["#AI"],
        metadata=metadata,
        timestamp=timestamp,
        user_id="nmorton"
    )

    file_path = markdown_export.get_markdown_file_path(timestamp)
    content = file_path.read_text(encoding="utf-8")

    assert 'type: [ "ai_response" ]' in content
    assert "**16:45** 🤖" in content
    assert "🤖 **AI Response:**" in content
    assert "**Prompt:**\nDoes Beautiful Mess clash with First Principle thinking?\n\n**Response:**\nThis was an AI reply worth saving." in content
    assert "Model: `z-ai/glm-4.7`" in content
    assert "Command: `/chat`" in content
    assert "Context: `chat_response`" in content
    assert "Saved: 2025-12-31 16:45" in content
