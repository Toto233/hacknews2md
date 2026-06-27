"""
URL validation and SSRF protection.

Blocks:
- Non-HTTP/HTTPS schemes (file://, ftp://, data://, javascript:, etc.)
- Private/internal IP addresses (10.x, 172.16-31.x, 192.168.x, 127.x, 169.254.x)
- Metadata endpoints (169.254.169.254, metadata.google.internal)
- localhost / loopback
- Excessively long URLs (> 2048 chars)
"""

import ipaddress
import logging
import os
import socket
import urllib.parse
from functools import lru_cache

logger = logging.getLogger(__name__)


class SecurityError(Exception):
    """Raised when a URL fails security validation."""

    pass


# Schemes that are NEVER allowed
BLOCKED_SCHEMES = frozenset({"file", "ftp", "ftps", "data", "javascript", "vbscript", "blob", "mailto"})

# Only these schemes are allowed
ALLOWED_SCHEMES = frozenset({"http", "https"})

# Hosts that are explicitly blocked
BLOCKED_HOSTS = frozenset(
    {
        "169.254.169.254",  # AWS/GCP/Azure metadata
        "metadata.google.internal",
        "metadata.google.com",
        "instance-data",  # AWS instance metadata hostname
        "localhost",
        "localhost.localdomain",
    }
)

# Max URL length to prevent buffer-based attacks
MAX_URL_LENGTH = 2048

# Clash/Mihomo and similar TUN proxies commonly use this benchmarking range
# as synthetic DNS answers. It is allowed only through explicit configuration.
TUN_FAKE_IP_NETWORK = ipaddress.ip_network("198.18.0.0/15")


@lru_cache(maxsize=1)
def _tun_fake_ip_enabled() -> bool:
    """Resolve TUN Fake-IP compatibility from env, then project config."""
    env_value = os.getenv("HACKNEWS_ALLOW_TUN_FAKE_IP")
    if env_value is not None:
        return env_value.strip().lower() in {"1", "true", "yes", "on"}

    try:
        from src.utils.config import Config

        return bool(Config().get("security.allow_tun_fake_ip", True))
    except Exception as exc:
        logger.debug("Unable to load TUN Fake-IP setting: %s", exc)
        return True


def _is_tun_fake_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return whether an address belongs to the IPv4 TUN Fake-IP range."""
    return isinstance(ip, ipaddress.IPv4Address) and ip in TUN_FAKE_IP_NETWORK


def _is_private_ip(hostname: str, allow_tun_fake_ip: bool = False) -> bool:
    """Check if a hostname resolves to a private/internal IP address."""
    try:
        ip = ipaddress.ip_address(hostname)
        if allow_tun_fake_ip and _is_tun_fake_ip(ip):
            return False
        # Only block IPv4 private ranges; IPv6 global addresses are fine
        if isinstance(ip, ipaddress.IPv6Address):
            return ip.is_loopback or ip.is_link_local or ip.is_reserved
        return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved
    except ValueError:
        # Not a raw IP — check via DNS resolution
        return False


def _resolve_and_check(hostname: str, allow_tun_fake_ip: bool = False) -> None:
    """Resolve hostname and verify it doesn't point to a private network."""
    if _is_private_ip(hostname, allow_tun_fake_ip=allow_tun_fake_ip):
        raise SecurityError(f"Private/internal IP address blocked: {hostname}")

    # For non-IP hostnames, resolve and check
    try:
        addrinfos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        for family, _, _, _, sockaddr in addrinfos:
            ip_str = sockaddr[0]
            ip = ipaddress.ip_address(ip_str)
            if allow_tun_fake_ip and _is_tun_fake_ip(ip):
                continue
            # Only block IPv4 private ranges; IPv6 global addresses are fine
            if isinstance(ip, ipaddress.IPv6Address):
                if ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    raise SecurityError(f"Hostname '{hostname}' resolves to private IPv6: {ip_str}")
            else:
                if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
                    raise SecurityError(f"Hostname '{hostname}' resolves to private IP: {ip_str}")
    except socket.gaierror:
        # DNS resolution failed — let the caller handle network errors
        logger.debug(f"DNS resolution failed for '{hostname}' — allowing URL")


def validate_url(
    url: str,
    allow_private: bool = False,
    allow_tun_fake_ip: bool | None = None,
) -> str:
    """Validate a URL for safety against SSRF attacks.

    Args:
        url: The URL to validate.
        allow_private: If True, skip private IP checks (for local dev/testing).
        allow_tun_fake_ip: Allow only the TUN Fake-IP range `198.18.0.0/15`.
            If omitted, resolve from environment or project configuration.

    Returns:
        The validated URL (unchanged).

    Raises:
        SecurityError: If the URL fails any security check.
        ValueError: If the URL is empty or malformed.
    """
    if not url or not url.strip():
        raise ValueError("URL must not be empty")

    url = url.strip()

    if len(url) > MAX_URL_LENGTH:
        raise SecurityError(f"URL exceeds maximum length ({MAX_URL_LENGTH} chars)")

    parsed = urllib.parse.urlparse(url)

    # Scheme check
    if parsed.scheme not in ALLOWED_SCHEMES:
        raise SecurityError(f"Blocked URL scheme: '{parsed.scheme}' (allowed: {', '.join(sorted(ALLOWED_SCHEMES))})")

    # Hostname check
    hostname = parsed.hostname
    if not hostname:
        raise SecurityError(f"URL has no hostname: {url}")

    hostname = hostname.lower().rstrip(".")

    # Explicit blocklist
    if hostname in BLOCKED_HOSTS:
        raise SecurityError(f"Blocked hostname: {hostname}")

    # Block URLs with credentials embedded
    if parsed.username or parsed.password:
        raise SecurityError("URL must not contain embedded credentials")

    # Private IP check (unless explicitly allowed)
    if not allow_private:
        if allow_tun_fake_ip is None:
            allow_tun_fake_ip = _tun_fake_ip_enabled()
        _resolve_and_check(hostname, allow_tun_fake_ip=allow_tun_fake_ip)

    logger.debug(f"URL validated: {url[:80]}...")
    return url


def validate_url_lenient(url: str) -> str | None:
    """Validate URL, returning None instead of raising on failure.

    Useful for non-critical paths where we want to skip bad URLs
    rather than abort the entire operation.
    """
    try:
        return validate_url(url)
    except (SecurityError, ValueError) as e:
        logger.warning(f"URL validation failed: {e} | url={url[:80]}")
        return None
