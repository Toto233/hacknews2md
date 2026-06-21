"""Tests for youtube_handler.py.

The youtube_handler module has no standalone pure functions -- its video ID
extraction logic is embedded inside the async ``get_youtube_content`` function,
which also performs network I/O.

This file documents the expected URL-parsing behaviour so that if the logic is
later extracted into a pure helper, these cases serve as a ready-made test
specification.
"""

import pytest


# ---------------------------------------------------------------------------
# Video-ID extraction patterns (documented, not yet testable as pure funcs)
# ---------------------------------------------------------------------------

# These tuples describe the expected behaviour of the inline video-ID parser
# inside get_youtube_content().  They can be turned into real tests once the
# extraction logic is refactored into a standalone pure function.

VIDEO_ID_CASES = [
    # (url, expected_video_id_or_None)
    ("https://www.youtube.com/watch?v=dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtube.com/watch?v=abc123", "abc123"),
    ("https://www.youtube.com/shorts/XYZ789", "XYZ789"),
    ("https://youtube.com/shorts/ABCDEF", "ABCDEF"),
    ("https://youtu.be/dQw4w9WgXcQ", "dQw4w9WgXcQ"),
    ("https://youtu.be/abc123?t=30", "abc123"),
    (
        "https://www.youtube.com/watch?v=ID123&list=PLrAXtmErZgOeiKm4sgNOknGvNjby9efdf",
        "ID123",
    ),
    ("https://example.com/watch?v=notyoutube", None),
]


@pytest.mark.parametrize("url,expected_id", VIDEO_ID_CASES)
def test_video_id_extraction_patterns(url, expected_id):
    """Verify expected video-ID patterns match the documented cases.

    This test validates the *test data* itself (e.g. no typos in URLs).
    Once get_youtube_content is refactored, replace this with a direct call.
    """
    # Simple sanity check: the expected_id should appear in the URL
    if expected_id is not None:
        assert expected_id in url
    else:
        # Non-YouTube URLs should not contain a youtube video ID we recognise
        assert "youtube.com" not in url and "youtu.be" not in url
