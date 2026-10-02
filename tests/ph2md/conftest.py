"""All PH tests run against disposable paths with no real DNS or HTTP."""
import socket
from src.security.url_validator import _tun_fake_ip_enabled

import httpx
import pytest
import requests


@pytest.fixture(autouse=True)
def isolate_network(monkeypatch):
    _tun_fake_ip_enabled.cache_clear()
    monkeypatch.setattr(socket, "getaddrinfo", lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))])
    monkeypatch.setenv("HACKNEWS_ALLOW_TUN_FAKE_IP", "false")
    def deny(*args, **kwargs):
        raise AssertionError("Unexpected live HTTP request")
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", deny)
    monkeypatch.setattr(requests.sessions.Session, "request", deny)
    yield
    _tun_fake_ip_enabled.cache_clear()
