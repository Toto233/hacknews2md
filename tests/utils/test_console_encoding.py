from __future__ import annotations

import os

from src.utils.console_encoding import configure_utf8_stdio


class _Stream:
    def __init__(self) -> None:
        self.calls: list[dict[str, str]] = []

    def reconfigure(self, **kwargs: str) -> None:
        self.calls.append(kwargs)


def test_configure_utf8_stdio_sets_environment_and_reconfigures(monkeypatch) -> None:
    stdout = _Stream()
    stderr = _Stream()
    monkeypatch.delenv("PYTHONUTF8", raising=False)
    monkeypatch.delenv("PYTHONIOENCODING", raising=False)

    configure_utf8_stdio(stdout=stdout, stderr=stderr)

    assert os.environ["PYTHONUTF8"] == "1"
    assert os.environ["PYTHONIOENCODING"] == "utf-8"
    assert stdout.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert stderr.calls == [{"encoding": "utf-8", "errors": "replace"}]
