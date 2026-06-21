"""Tests for pure functions in twitter_handler.py."""

import pytest

from src.core.handlers.twitter_handler import _extract_tweet_id, _is_x_url


# ---------------------------------------------------------------------------
# _is_x_url
# ---------------------------------------------------------------------------


class TestIsXUrl:
    """Tests for _is_x_url(url)."""

    def test_x_com(self):
        assert _is_x_url("https://x.com/elonmusk/status/123") is True

    def test_twitter_com(self):
        assert _is_x_url("https://twitter.com/user/status/456") is True

    def test_mobile_twitter_com(self):
        assert _is_x_url("https://mobile.twitter.com/user/status/789") is True

    def test_m_twitter_com(self):
        assert _is_x_url("https://m.twitter.com/user/status/101") is True

    def test_www_x_com(self):
        assert _is_x_url("https://www.x.com/user/status/202") is True

    def test_www_twitter_com(self):
        assert _is_x_url("https://www.twitter.com/user/status/303") is True

    def test_http_scheme(self):
        assert _is_x_url("http://twitter.com/user/status/404") is True

    def test_unrelated_domain(self):
        assert _is_x_url("https://example.com/some/page") is False

    def test_facebook(self):
        assert _is_x_url("https://facebook.com/post/123") is False

    def test_substring_match_behavior(self):
        # "x.com" is a substring of "x.com.evil.com" netloc -- matches by design
        assert _is_x_url("https://x.com.evil.com/phish") is True

    def test_empty_string(self):
        assert _is_x_url("") is False

    def test_malformed_url(self):
        # urlparse still works on non-URL strings; netloc will be empty
        assert _is_x_url("not a url") is False

    def test_path_only(self):
        assert _is_x_url("/some/path") is False

    def test_case_insensitive_domain(self):
        assert _is_x_url("https://X.COM/user/status/1") is True
        assert _is_x_url("https://TWITTER.COM/user/status/1") is True


# ---------------------------------------------------------------------------
# _extract_tweet_id
# ---------------------------------------------------------------------------


class TestExtractTweetId:
    """Tests for _extract_tweet_id(url)."""

    def test_standard_x_url(self):
        url = "https://x.com/elonmusk/status/1234567890"
        assert _extract_tweet_id(url) == "1234567890"

    def test_standard_twitter_url(self):
        url = "https://twitter.com/user/status/9876543210"
        assert _extract_tweet_id(url) == "9876543210"

    def test_url_with_query_params(self):
        url = "https://x.com/user/status/111222333?s=20&t=abc"
        assert _extract_tweet_id(url) == "111222333"

    def test_url_with_fragment(self):
        url = "https://twitter.com/user/status/444555666#fragment"
        assert _extract_tweet_id(url) == "444555666"

    def test_mobile_twitter_url(self):
        url = "https://mobile.twitter.com/user/status/777888999"
        assert _extract_tweet_id(url) == "777888999"

    def test_long_tweet_id(self):
        url = "https://x.com/user/status/1785123456789012345"
        assert _extract_tweet_id(url) == "1785123456789012345"

    def test_no_status_in_path(self):
        url = "https://x.com/elonmusk"
        assert _extract_tweet_id(url) == ""

    def test_status_with_no_id(self):
        url = "https://x.com/user/status/"
        assert _extract_tweet_id(url) == ""

    def test_non_numeric_after_status(self):
        url = "https://x.com/user/status/abc123"
        assert _extract_tweet_id(url) == ""

    def test_empty_string(self):
        assert _extract_tweet_id("") == ""

    def test_completely_invalid_url(self):
        assert _extract_tweet_id("not a url at all") == ""

    def test_non_twitter_url_with_status(self):
        # "status" appears in other sites too; function still extracts it
        url = "https://example.com/user/status/42"
        assert _extract_tweet_id(url) == "42"
