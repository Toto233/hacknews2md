# -*- coding: utf-8 -*-
"""Tests for URL validation and SSRF protection."""

import socket

import pytest
from src.security.url_validator import validate_url, validate_url_lenient, SecurityError


class TestValidateUrl:
    """Tests for the main validate_url function."""

    def test_valid_http_url(self):
        """Standard HTTP URLs should pass."""
        url = validate_url("http://example.com/article")
        assert url == "http://example.com/article"

    def test_valid_https_url(self):
        """Standard HTTPS URLs should pass."""
        url = validate_url("https://news.ycombinator.com/item?id=12345")
        assert url == "https://news.ycombinator.com/item?id=12345"

    def test_empty_url_raises(self):
        """Empty URLs should raise ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            validate_url("")

    def test_none_url_raises(self):
        """None URLs should raise ValueError."""
        with pytest.raises(ValueError):
            validate_url(None)

    def test_whitespace_only_raises(self):
        """Whitespace-only URLs should raise ValueError."""
        with pytest.raises(ValueError, match="must not be empty"):
            validate_url("   ")


class TestBlockedSchemes:
    """Tests for scheme blocking."""

    def test_file_scheme_blocked(self):
        """file:// scheme should be blocked."""
        with pytest.raises(SecurityError, match="Blocked URL scheme"):
            validate_url("file:///etc/passwd")

    def test_ftp_scheme_blocked(self):
        """ftp:// scheme should be blocked."""
        with pytest.raises(SecurityError, match="Blocked URL scheme"):
            validate_url("ftp://example.com/file.txt")

    def test_data_scheme_blocked(self):
        """data: scheme should be blocked."""
        with pytest.raises(SecurityError, match="Blocked URL scheme"):
            validate_url("data:text/html,<h1>test</h1>")

    def test_javascript_scheme_blocked(self):
        """javascript: scheme should be blocked."""
        with pytest.raises(SecurityError, match="Blocked URL scheme"):
            validate_url("javascript:alert('xss')")

    def test_blob_scheme_blocked(self):
        """blob: scheme should be blocked."""
        with pytest.raises(SecurityError, match="Blocked URL scheme"):
            validate_url("blob:https://example.com/uuid")

    def test_mailto_scheme_blocked(self):
        """mailto: scheme should be blocked."""
        with pytest.raises(SecurityError, match="Blocked URL scheme"):
            validate_url("mailto:user@example.com")


class TestBlockedHosts:
    """Tests for host blocking."""

    def test_aws_metadata_blocked(self):
        """AWS metadata endpoint should be blocked."""
        with pytest.raises(SecurityError, match="Blocked hostname"):
            validate_url("http://169.254.169.254/latest/meta-data/")

    def test_localhost_blocked(self):
        """localhost should be blocked."""
        with pytest.raises(SecurityError, match="Blocked hostname"):
            validate_url("http://localhost:8080/admin")

    def test_google_metadata_blocked(self):
        """Google metadata endpoint should be blocked."""
        with pytest.raises(SecurityError, match="Blocked hostname"):
            validate_url("http://metadata.google.internal/computeMetadata/v1/")


class TestPrivateIpBlocking:
    """Tests for private IP address blocking."""

    def test_10_x_blocked(self):
        """10.x.x.x private IPs should be blocked."""
        with pytest.raises(SecurityError, match="Private"):
            validate_url("http://10.0.0.1/admin")

    def test_192_168_blocked(self):
        """192.168.x.x private IPs should be blocked."""
        with pytest.raises(SecurityError, match="Private"):
            validate_url("http://192.168.1.1/config")

    def test_172_16_blocked(self):
        """172.16-31.x.x private IPs should be blocked."""
        with pytest.raises(SecurityError, match="Private"):
            validate_url("http://172.16.0.1/admin")

    def test_127_loopback_blocked(self):
        """127.x.x.x loopback should be blocked."""
        with pytest.raises(SecurityError, match="Private"):
            validate_url("http://127.0.0.1:8080/admin")

    def test_169_254_link_local_blocked(self):
        """169.254.x.x link-local should be blocked."""
        with pytest.raises(SecurityError, match="Blocked hostname"):
            validate_url("http://169.254.169.254/admin")

    def test_private_ip_allowed_with_flag(self):
        """Private IPs should be allowed when allow_private=True."""
        url = validate_url("http://192.168.1.1/admin", allow_private=True)
        assert url == "http://192.168.1.1/admin"


class TestTunFakeIpCompatibility:
    """TUN Fake-IP compatibility must not weaken other SSRF checks."""

    @staticmethod
    def _fake_ip_dns(*_args, **_kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("198.18.0.42", 0))]

    def test_fake_ip_dns_blocked_when_disabled(self, monkeypatch):
        monkeypatch.setattr("src.security.url_validator.socket.getaddrinfo", self._fake_ip_dns)

        with pytest.raises(SecurityError, match="private IP"):
            validate_url("https://example.com/article", allow_tun_fake_ip=False)

    def test_fake_ip_dns_allowed_when_enabled(self, monkeypatch):
        monkeypatch.setattr("src.security.url_validator.socket.getaddrinfo", self._fake_ip_dns)

        url = validate_url("https://example.com/article", allow_tun_fake_ip=True)

        assert url == "https://example.com/article"

    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/admin",
            "http://192.168.1.1/admin",
            "http://169.254.169.254/latest/meta-data/",
        ],
    )
    def test_tun_mode_still_blocks_internal_addresses(self, url):
        with pytest.raises(SecurityError):
            validate_url(url, allow_tun_fake_ip=True)


class TestEmbeddedCredentials:
    """Tests for embedded credential blocking."""

    def test_username_in_url_blocked(self):
        """URLs with embedded username should be blocked."""
        with pytest.raises(SecurityError, match="embedded credentials"):
            validate_url("http://user:pass@example.com/admin")

    def test_username_only_blocked(self):
        """URLs with username but no password should be blocked."""
        with pytest.raises(SecurityError, match="embedded credentials"):
            validate_url("http://user@example.com/admin")


class TestUrlLength:
    """Tests for URL length limits."""

    def test_long_url_blocked(self):
        """URLs exceeding max length should be blocked."""
        long_url = "http://example.com/" + "a" * 2100
        with pytest.raises(SecurityError, match="maximum length"):
            validate_url(long_url)

    def test_max_length_url_allowed(self):
        """URLs at exactly max length should be allowed."""
        # 2048 chars total
        url = "http://example.com/" + "a" * (2048 - len("http://example.com/"))
        result = validate_url(url)
        assert result == url


class TestValidateUrlLenient:
    """Tests for the lenient validation wrapper."""

    def test_valid_url_returns_url(self):
        """Valid URLs should be returned."""
        url = validate_url_lenient("https://example.com")
        assert url == "https://example.com"

    def test_invalid_url_returns_none(self):
        """Invalid URLs should return None."""
        result = validate_url_lenient("file:///etc/passwd")
        assert result is None

    def test_private_ip_returns_none(self):
        """Private IPs should return None."""
        result = validate_url_lenient("http://192.168.1.1/admin")
        assert result is None

    def test_empty_url_returns_none(self):
        """Empty URLs should return None."""
        result = validate_url_lenient("")
        assert result is None


class TestIPv6Addresses:
    """Tests for IPv6 address handling."""

    def test_ipv6_loopback_blocked(self):
        """IPv6 loopback ::1 should be blocked."""
        with pytest.raises(SecurityError, match="Private"):
            validate_url("http://[::1]:8080/path")

    def test_ipv6_link_local_blocked(self):
        """IPv6 link-local fe80:: addresses should be blocked."""
        with pytest.raises(SecurityError, match="Private"):
            validate_url("http://[fe80::1]/path")

    def test_ipv6_allowed_with_private_flag(self):
        """IPv6 addresses should pass when allow_private=True."""
        url = validate_url("http://[::1]:8080/path", allow_private=True)
        assert url == "http://[::1]:8080/path"


class TestUrlWithFragments:
    """Tests for URLs containing fragment identifiers."""

    def test_url_with_fragment(self):
        """URLs with fragments should pass validation."""
        url = validate_url("https://example.com/page#section1")
        assert url == "https://example.com/page#section1"

    def test_url_with_complex_fragment(self):
        """URLs with complex fragments should pass."""
        url = validate_url("https://example.com/page#top?redirect=true")
        assert url == "https://example.com/page#top?redirect=true"

    def test_url_with_empty_fragment(self):
        """URLs with empty fragment (#) should pass."""
        url = validate_url("https://example.com/page#")
        assert url == "https://example.com/page#"


class TestUrlWithQueryParameters:
    """Tests for URLs containing query parameters."""

    def test_url_with_single_query_param(self):
        """URLs with one query parameter should pass."""
        url = validate_url("https://example.com/search?q=test")
        assert url == "https://example.com/search?q=test"

    def test_url_with_multiple_query_params(self):
        """URLs with multiple query parameters should pass."""
        url = validate_url("https://example.com/search?q=test&page=1&lang=en")
        assert url == "https://example.com/search?q=test&page=1&lang=en"

    def test_url_with_encoded_query_params(self):
        """URLs with percent-encoded query parameters should pass."""
        url = validate_url("https://example.com/search?q=hello%20world&lang=en")
        assert url == "https://example.com/search?q=hello%20world&lang=en"

    def test_url_with_query_and_fragment(self):
        """URLs with both query params and fragments should pass."""
        url = validate_url("https://example.com/page?id=123#top")
        assert url == "https://example.com/page?id=123#top"


class TestVeryLongUrls:
    """Tests for extremely long URLs approaching the length limit."""

    def test_url_just_under_limit(self):
        """A URL just under 2048 chars should pass."""
        # Build a URL that is exactly 2047 chars
        base = "http://example.com/"
        padding = "a" * (2047 - len(base))
        url = base + padding
        assert len(url) == 2047
        result = validate_url(url)
        assert result == url

    def test_url_exactly_at_limit(self):
        """A URL at exactly 2048 chars should pass."""
        base = "http://example.com/"
        padding = "a" * (2048 - len(base))
        url = base + padding
        assert len(url) == 2048
        result = validate_url(url)
        assert result == url

    def test_url_one_over_limit(self):
        """A URL at 2049 chars should be blocked."""
        base = "http://example.com/"
        padding = "a" * (2049 - len(base))
        url = base + padding
        assert len(url) == 2049
        with pytest.raises(SecurityError, match="maximum length"):
            validate_url(url)

    def test_very_long_path_segments(self):
        """A URL with many long path segments under the limit should pass."""
        segments = "/".join(["segment" * 10] * 20)
        url = f"http://example.com/{segments}"
        if len(url) <= 2048:
            result = validate_url(url)
            assert result == url

    def test_very_long_url_lenient_returns_none(self):
        """validate_url_lenient should return None for very long URLs."""
        base = "http://example.com/"
        padding = "a" * (2100 - len(base))
        url = base + padding
        assert validate_url_lenient(url) is None
