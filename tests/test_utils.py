import json

from mentat.core import utils


def test_standardize_truncation_respects_word_boundary():
    text = "This is a long sentence that should truncate cleanly"
    truncated = utils.standardize_truncation(text, 20)

    assert truncated.endswith("...")
    assert truncated.startswith("This is a long")


def test_standardize_truncation_avoids_breaking_urls():
    text = "Notes at https://example.com/some/very/long/path should stay intact"
    truncated = utils.standardize_truncation(text, 25)

    assert "https://example.com" not in truncated
    assert truncated.endswith("...")


def test_parse_item_metadata_handles_json_string():
    item = {"metadata": json.dumps({"source": {"type": "web"}, "web_context": {"title": "Example"}})}
    metadata, source_info, web_context = utils.parse_item_metadata(item)

    assert metadata["web_context"]["title"] == "Example"
    assert source_info == {"type": "web"}
    assert web_context == {"title": "Example"}


def test_parse_item_metadata_handles_invalid_json():
    item = {"metadata": "{not valid json"}
    metadata, source_info, web_context = utils.parse_item_metadata(item)

    assert metadata == {}
    assert source_info is None
    assert web_context is None


def test_parse_entities_from_metadata_returns_default():
    entities = utils.parse_entities_from_metadata({"entities": {"people": ["Ada"]}})

    assert entities == {"people": ["Ada"]}
