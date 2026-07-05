from src.core.handlers.fediverse_handler import (
    extract_activitypub_note,
    extract_alternate_activitypub_url,
    extract_html_metadata_summary,
    is_fediverse_url,
)


def test_is_fediverse_url_detects_actor_status_urls() -> None:
    assert is_fediverse_url("https://mathstodon.xyz/@iblech/1161234567890") is True
    assert is_fediverse_url("https://mastodon.social/users/alice/statuses/1") is True
    assert is_fediverse_url("https://example.com/article") is False


def test_extract_activitypub_note_returns_plain_text() -> None:
    note = {
        "type": "Note",
        "attributedTo": "https://mathstodon.xyz/users/iblech",
        "published": "2026-07-03T01:02:03Z",
        "url": "https://mathstodon.xyz/@iblech/1161234567890",
        "content": "<p>Readable toot body with <a href='https://example.com'>a link</a>.</p>",
    }

    assert extract_activitypub_note(note, "https://mathstodon.xyz/@iblech/1161234567890") == (
        "Author: https://mathstodon.xyz/users/iblech\n"
        "Published: 2026-07-03T01:02:03Z\n"
        "URL: https://mathstodon.xyz/@iblech/1161234567890\n\n"
        "Readable toot body with a link."
    )


def test_extract_alternate_activitypub_url_from_javascript_shell() -> None:
    html = """
    <html><head>
      <link href="/users/alice/statuses/1" rel="alternate" type="application/activity+json">
    </head><body>Enable JavaScript to view this page.</body></html>
    """

    assert extract_alternate_activitypub_url(html, "https://mastodon.social/@alice/1") == (
        "https://mastodon.social/users/alice/statuses/1"
    )


def test_extract_html_metadata_summary_ignores_javascript_shell_body() -> None:
    html = """
    <html><head>
      <meta property="og:description" content="Public metadata description from the toot page.">
    </head><body>Enable JavaScript to view this page.</body></html>
    """

    assert extract_html_metadata_summary(html) == "Public metadata description from the toot page."
