"""Disposable, offline restart tests; no publishing or configured services are called."""

from __future__ import annotations

import json
import socket
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest
import requests

from hn2md.context import RuntimeContext
from hn2md.stages.base import NonRetryableStageError
from hn2md.state import JobStateMachine, PublishJob
from publisher.hn_restart import restart_fetch


@pytest.fixture
def restart_state(tmp_path, monkeypatch):
    monkeypatch.setattr("requests.get", Mock(side_effect=AssertionError("live HTTP forbidden")))
    monkeypatch.setattr(
        socket, "getaddrinfo",
        lambda *_args, **_kwargs: [(socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443))],
    )
    ctx = RuntimeContext.create(tmp_path)
    ctx.db_path.parent.mkdir(parents=True)
    with sqlite3.connect(ctx.db_path) as conn:
        conn.execute("CREATE TABLE news (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT, news_url TEXT, discuss_url TEXT, created_at TEXT)")
        conn.execute("CREATE TABLE news_history (id INTEGER PRIMARY KEY, news_url TEXT)")
        conn.execute("CREATE TABLE filtered_domains (id INTEGER PRIMARY KEY, domain TEXT)")
        conn.execute("INSERT INTO news VALUES (1, 'Previous today', 'https://old.example/today', '', '2026-10-07 01:00:00')")
        conn.execute("INSERT INTO news VALUES (2, 'Previous day', 'https://old.example/yesterday', '', '2026-10-06 01:00:00')")
        conn.execute("INSERT INTO news_history VALUES (1, 'https://new.example/1')")
        conn.execute("INSERT INTO filtered_domains VALUES (1, 'filtered.example')")
    published = {"success": True, "output_summary": {"wechat_media_id": "existing-media-id"}}
    job = PublishJob(
        date="20261007", status="FETCHING", run_id="existing-run",
        stories=[{"id": 1, "title": "Previous today", "news_url": "https://old.example/today"}],
        stages={stage: {"success": True} for stage in ("COLLECTING", "CAPTURING", "PLANNING", "APPLYING", "RENDERING", "COVERING")},
        receipts={"PUBLISHING": [published], "RENDERING": [{"success": True}]},
        skipped_stories=[{"id": 11}], screenshot_waivers=[{"id": 1}], keyword_decisions=[{"keyword": "old"}],
        audit_report={"blocking_count": 1}, audit_exemption={"approved_at": "old"}, manual_astro={"sha": "old"},
    )
    job.stages["PUBLISHING"] = published
    machine = JobStateMachine(job, ctx.job_dir / "publish_job_20261007.json")
    machine._save()
    return ctx, machine


def fresh_items() -> list[dict[str, str]]:
    return [
        {"title": f"Story {i}", "news_url": f"https://new.example/{i}", "discuss_url": f"https://news.ycombinator.com/item?id={i}"}
        for i in range(1, 11)
    ]


@pytest.mark.parametrize("items", [[], fresh_items()[:9]])
def test_unsuccessful_fetch_retains_database_and_ledger(restart_state, monkeypatch, items) -> None:
    ctx, machine = restart_state
    before = machine.ledger_path.read_bytes()
    monkeypatch.setattr("publisher.hn_restart.fetch_news", lambda **_kwargs: items)
    with pytest.raises(RuntimeError, match="Existing daily rows were retained"):
        restart_fetch(ctx, machine)
    with sqlite3.connect(ctx.db_path) as conn:
        assert conn.execute("SELECT id FROM news ORDER BY id").fetchall() == [(1,), (2,)]
    assert machine.ledger_path.read_bytes() == before
    assert not (ctx.project_root / "data" / "backups").exists()


def test_restart_replaces_only_today_and_retains_history_and_publish_evidence(restart_state, monkeypatch) -> None:
    ctx, machine = restart_state
    fetch = Mock(return_value=fresh_items())
    monkeypatch.setattr("publisher.hn_restart.fetch_news", fetch)
    before = machine.ledger_path.read_bytes()
    result = restart_fetch(ctx, machine)
    fetch.assert_called_once_with(ignore_history=True)
    assert result["saved"] == 10 and result["replaced"] == 1 and result["ignore_history"] is True
    with sqlite3.connect(ctx.db_path) as conn:
        assert conn.execute("SELECT title FROM news WHERE id = 2").fetchone() == ("Previous day",)
        assert conn.execute("SELECT count(*) FROM news WHERE strftime('%Y%m%d', created_at) = '20261007'").fetchone() == (10,)
        assert conn.execute("SELECT news_url FROM news_history").fetchall() == [("https://new.example/1",)]
        assert conn.execute("SELECT domain FROM filtered_domains").fetchall() == [("filtered.example",)]
    with sqlite3.connect(result["database_backup"]) as conn:
        assert conn.execute("SELECT id FROM news ORDER BY id").fetchall() == [(1,), (2,)]
    assert Path(result["ledger_backup"]).read_bytes() == before
    assert machine.job.run_id == "existing-run"
    assert list(machine.job.stages) == ["PUBLISHING"]
    assert machine.job.stages["PUBLISHING"]["output_summary"]["wechat_media_id"] == "existing-media-id"
    assert machine.job.receipts["PUBLISHING"][0]["output_summary"]["wechat_media_id"] == "existing-media-id"
    assert machine.job.receipts["RENDERING"] == [{"success": True}]
    assert machine.job.audit_report is None and machine.job.audit_exemption is None
    assert machine.job.manual_astro is None
    assert machine.job.skipped_stories == machine.job.keyword_decisions == machine.job.screenshot_waivers == []
    assert len(machine.job.stories) == 10
    persisted = json.loads(machine.ledger_path.read_text(encoding="utf-8"))
    assert persisted["run_id"] == "existing-run" and len(persisted["stories"]) == 10


@pytest.mark.parametrize("invalid", ["ask", "filtered", "unsafe", "unsafe_discussion"])
def test_normal_filters_are_not_bypassed(restart_state, monkeypatch, invalid) -> None:
    ctx, machine = restart_state
    items = fresh_items()
    if invalid == "ask":
        items[0]["title"] = "Ask HN: question"
    elif invalid == "filtered":
        items[0]["news_url"] = "https://filtered.example/one"
    elif invalid == "unsafe":
        items[0]["news_url"] = "http://127.0.0.1/one"
    else:
        items[0]["discuss_url"] = "http://127.0.0.1/one"
    monkeypatch.setattr("publisher.hn_restart.fetch_news", lambda **_kwargs: items)
    with pytest.raises(RuntimeError, match="selected 9"):
        restart_fetch(ctx, machine)
    with sqlite3.connect(ctx.db_path) as conn:
        assert conn.execute("SELECT count(*) FROM news").fetchone() == (2,)


def test_browser_recovery_also_ignores_history(restart_state, monkeypatch) -> None:
    ctx, machine = restart_state
    fetch = Mock(return_value=fresh_items())
    monkeypatch.setattr("publisher.hn_front_recovery.fetch_browser_front_ids", fetch)
    result = restart_fetch(ctx, machine, front_ids="1,2,3,4,5,6,7,8,9,10")
    fetch.assert_called_once_with("1,2,3,4,5,6,7,8,9,10", ignore_history=True)
    assert result["source"] == "browser_front_ids_hn_api"


def test_http_419_is_not_retried(restart_state, monkeypatch) -> None:
    ctx, machine = restart_state
    response = requests.Response()
    response.status_code = 419
    fetch = Mock(side_effect=requests.HTTPError(response=response))
    monkeypatch.setattr("publisher.hn_restart.fetch_news", fetch)
    with pytest.raises(NonRetryableStageError, match="419"):
        restart_fetch(ctx, machine)
    fetch.assert_called_once()


def test_sql_failure_rolls_back_scoped_replacement(restart_state, monkeypatch) -> None:
    ctx, machine = restart_state
    monkeypatch.setattr("publisher.hn_restart.fetch_news", lambda **_kwargs: fresh_items())
    before = machine.ledger_path.read_bytes()
    with sqlite3.connect(ctx.db_path) as conn:
        conn.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON news WHEN NEW.title = 'Story 2' BEGIN SELECT RAISE(ABORT, 'fixture insert failure'); END")
    with pytest.raises(sqlite3.IntegrityError, match="fixture insert failure"):
        restart_fetch(ctx, machine)
    with sqlite3.connect(ctx.db_path) as conn:
        assert conn.execute("SELECT id FROM news ORDER BY id").fetchall() == [(1,), (2,)]
    assert machine.ledger_path.read_bytes() == before
