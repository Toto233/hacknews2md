"""Offline tests for browser-observed HN /front recovery."""

from __future__ import annotations

import sqlite3
import socket
from contextlib import contextmanager
from unittest.mock import Mock

import pytest

from publisher.hn_front_recovery import fetch_browser_front_ids


def test_browser_front_ids_preserve_order_and_existing_filters(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))],
    )
    db_path = tmp_path / "news.db"
    with sqlite3.connect(db_path) as conn:
        conn.execute("CREATE TABLE news_history (id INTEGER PRIMARY KEY, news_url TEXT)")
        conn.execute("CREATE TABLE filtered_domains (id INTEGER PRIMARY KEY, domain TEXT)")
        conn.execute("INSERT INTO filtered_domains (domain) VALUES ('filtered.example')")
        conn.execute("INSERT INTO news_history (news_url) VALUES ('https://old.example/3')")

    @contextmanager
    def test_db():
        conn = sqlite3.connect(db_path)
        try:
            yield conn
        finally:
            conn.close()

    def fake_get(url: str, timeout: int) -> Mock:
        item_id = int(url.rsplit("/", 1)[-1].removesuffix(".json"))
        domain = "filtered.example" if item_id == 2 else "old.example" if item_id == 3 else "new.example"
        response = Mock()
        response.json.return_value = {
            "id": item_id,
            "type": "story",
            "title": f"Story {item_id}",
            "url": f"https://{domain}/{item_id}",
        }
        return response

    monkeypatch.setattr("publisher.hn_front_recovery.get_db", test_db)
    monkeypatch.setattr("publisher.hn_front_recovery.requests.get", fake_get)
    items = fetch_browser_front_ids(",".join(str(i) for i in range(1, 13)))

    assert len(items) == 10
    assert [item["title"] for item in items] == ["Story 1", *[f"Story {i}" for i in range(4, 13)]]
    assert items[0]["discuss_url"] == "https://news.ycombinator.com/item?id=1"


@pytest.mark.parametrize("ids", ["1,2", ",".join(["1"] * 10), "abc," + ",".join(str(i) for i in range(2, 11))])
def test_browser_front_ids_reject_bad_input(ids: str) -> None:
    with pytest.raises(ValueError):
        fetch_browser_front_ids(ids)
