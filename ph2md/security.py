from __future__ import annotations

import ipaddress
from urllib.parse import urlparse
from src.security.url_validator import SecurityError, validate_url


class URLValidationError(ValueError):
    pass


def validate_outbound_url(url: str, allowed_hosts: set[str] | None = None) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise URLValidationError(f"unsupported URL scheme: {parsed.scheme}")

    host = parsed.hostname
    if not host:
        raise URLValidationError("URL host is required")

    normalized_host = host.lower()
    if allowed_hosts is not None and normalized_host not in allowed_hosts:
        raise URLValidationError(f"host is not allowed: {normalized_host}")

    if normalized_host == "localhost" or normalized_host.endswith(".localhost"):
        raise URLValidationError("localhost targets are not allowed")

    try:
        address = ipaddress.ip_address(normalized_host)
    except ValueError:
        address = None

    if address is not None and (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    ):
        raise URLValidationError(f"unsafe IP target: {address}")

    try:
        return validate_url(url)
    except (SecurityError, ValueError) as exc:
        raise URLValidationError(str(exc)) from exc
