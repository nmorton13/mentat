from mentat.cli import commands


def test_generate_connection_explanation_uses_shared_entities():
    explanation = commands.generate_connection_explanation(
        new_content_tags=["alpha"],
        new_content_entities={"projects": ["MENTAT"]},
        connected_memories=[],
        shared_entities=["MENTAT", "Python"]
    )

    assert "MENTAT" in explanation


def test_generate_connection_explanation_uses_overlapping_tags():
    connected = [{"tags": ["alpha", "beta"]}]

    explanation = commands.generate_connection_explanation(
        new_content_tags=["alpha"],
        new_content_entities={},
        connected_memories=connected
    )

    assert "alpha" in explanation
