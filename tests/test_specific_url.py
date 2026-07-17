from mentat.cli import display


def test_make_urls_clickable_handles_query_params():
    url = "https://example.com/search?q=test&lang=en"
    text = f"Check {url} for results"

    result = display.make_urls_clickable(text)

    assert f"[link={url}]" in result
