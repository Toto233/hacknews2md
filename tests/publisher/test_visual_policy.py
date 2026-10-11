"""Offline coverage of blocked-page omissions and their exact publication scope."""

from pathlib import Path
from unittest.mock import Mock

import pytest
from click.testing import CliRunner

from hn2md.context import RuntimeContext
from hn2md.stages.publish import _require_screenshots_for_publish
from hn2md.stages.base import NonRetryableStageError
from hn2md.stages.screenshot import CaptureScreenshotsStage
from hn2md.state import JobStateMachine
from publisher.cli import main
from publisher.visual_policy import blocked_capture_waiver, screenshot_waiver_authorized
from src.db.connection import get_db
from src.utils.db_utils import init_database


@pytest.fixture(autouse=True)
def forbid_live_http(monkeypatch):
    monkeypatch.setattr("requests.sessions.Session.request", Mock(side_effect=AssertionError("Live HTTP forbidden")))
    monkeypatch.setattr("publisher.cli.validate_url", lambda url: url)


def setup_run(tmp_path: Path) -> tuple[RuntimeContext, JobStateMachine]:
    ctx = RuntimeContext.create(tmp_path)
    init_database(str(ctx.db_path))
    with get_db(str(ctx.db_path)) as conn:
        conn.execute("INSERT INTO news (id,title,news_url,created_at) VALUES (1,'Story',?,?)",
                     ("https://example.com/story", "2026-06-27 10:00:00"))
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, "20260627")
    return ctx, machine


def test_blocked_page_stage_records_omission_but_timeout_remains_pending(tmp_path, monkeypatch):
    ctx, machine = setup_run(tmp_path)
    summary = {"requested": 2, "captured": 0, "items": [
        {"id": 1, "news_url": "https://example.com/story", "captured": False,
         "reason": "access_denied", "evidence_path": "blocked.png"},
        {"id": 2, "news_url": "https://example.com/timeout", "captured": False,
         "reason": "screenshot_timeout"},
    ], "warnings": [{"id": 1, "reason": "access_denied"}, {"id": 2, "reason": "screenshot_timeout"}]}
    monkeypatch.setattr("hn2md.stages.screenshot.capture_missing_screenshots", lambda *a, **k: summary)
    result = CaptureScreenshotsStage().execute(ctx, machine)
    assert result["warnings"] == [{"id": 2, "reason": "screenshot_timeout"}]
    assert len(result["screenshot_omissions"]) == 1
    loaded, _ = JobStateMachine.load_or_create(ctx.job_dir, "20260627")
    omission = loaded.job.screenshot_waivers[0]
    assert omission["evidence_path"] == "blocked.png"
    assert _require_screenshots_for_publish(ctx, "20260627", waivers=[omission], run_id=loaded.job.run_id) == [omission]
    for changes in ({"run_id": "old"}, {"news_url": "https://example.com/other"},
                    {"period": "20260626"}, {"news_id": 2}, {"failure_kind": "screenshot_timeout"},
                    {"policy": "other"}):
        with pytest.raises(NonRetryableStageError):
            _require_screenshots_for_publish(ctx, "20260627", waivers=[{**omission, **changes}], run_id=loaded.job.run_id)


def test_missing_capture_without_specific_failure_is_not_implicitly_waived(tmp_path, monkeypatch):
    ctx, machine = setup_run(tmp_path)
    monkeypatch.setattr("hn2md.stages.screenshot.capture_missing_screenshots", lambda *a, **k: {
        "items": [{"id": 1, "captured": False, "reason": "screenshot_unavailable"}],
        "warnings": [{"id": 1, "reason": "screenshot_unavailable"}],
    })
    result = CaptureScreenshotsStage().execute(ctx, machine)
    assert result["screenshot_omissions"] == []
    assert machine.job.screenshot_waivers == []
    with pytest.raises(NonRetryableStageError):
        _require_screenshots_for_publish(ctx, "20260627", run_id=machine.job.run_id)


def test_capture_to_publish_policy_survives_rerun_without_retry(tmp_path, monkeypatch):
    ctx, machine = setup_run(tmp_path)
    capture = Mock(return_value={"id": 1, "screenshot": None,
                                "reason": "verification_required", "attempts": 1})
    monkeypatch.setattr("hn2md.screenshot_capture._capture_one_in_process", capture)
    first = CaptureScreenshotsStage().execute(ctx, machine)
    assert first["captured"] == 0
    assert first["warnings"] == []
    assert first["screenshot_omissions"][0]["news_url"] == "https://example.com/story"
    loaded, _ = JobStateMachine.load_or_create(ctx.job_dir, "20260627")
    second = CaptureScreenshotsStage().execute(ctx, loaded)
    assert second["waived_skipped"] == 1
    capture.assert_called_once()
    assert _require_screenshots_for_publish(
        ctx, "20260627", waivers=loaded.job.screenshot_waivers, run_id=loaded.job.run_id,
    ) == loaded.job.screenshot_waivers


@pytest.mark.parametrize("kind", ["screenshot_timeout", "network_error", "", "unknown"])
def test_policy_cannot_authorize_unspecified_failures(kind):
    with pytest.raises(ValueError):
        blocked_capture_waiver("20260627", "run", 1, "https://example.com", kind, "failed")


def test_repair_same_source_and_blocked_omission_need_no_new_confirmation(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx, machine = setup_run(tmp_path)
    directory = tmp_path / "output/images/20260627"
    directory.mkdir(parents=True)
    blocked, valid = directory / "blocked.png", directory / "valid.png"
    for path in (blocked, valid):
        path.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    with get_db(str(ctx.db_path)) as conn:
        conn.execute("UPDATE news SET screenshot=? WHERE id=1", (str(blocked),))
    base = ["repair-screenshot", "hackernews", "1", "--date", "20260627", "--url",
            "https://example.com/story", "--reason", "Verified 403 error page"]
    result = CliRunner().invoke(main, [*base, "--replacement-file", str(valid),
                                      "--replacement-url", "https://example.com/story"])
    assert result.exit_code == 0, result.output
    loaded, _ = JobStateMachine.load_or_create(ctx.job_dir, "20260627")
    assert loaded.job.continuation_notes[-1]["approved_by"] == "source_recovery"
    result = CliRunner().invoke(main, [*base, "--omit", "--failure-kind", "access_denied"])
    assert result.exit_code == 0, result.output
    assert blocked.exists() and valid.exists()
    loaded, _ = JobStateMachine.load_or_create(ctx.job_dir, "20260627")
    assert screenshot_waiver_authorized(loaded.job.screenshot_waivers[0], loaded.job.run_id)
    with get_db(str(ctx.db_path)) as conn:
        assert conn.execute("SELECT screenshot FROM news WHERE id=1").fetchone()[0] is None
    result = CliRunner().invoke(main, [*base, "--replacement-file", str(valid),
                                      "--replacement-url", "https://example.com/story"])
    assert result.exit_code == 0, result.output
    loaded, _ = JobStateMachine.load_or_create(ctx.job_dir, "20260627")
    assert loaded.job.screenshot_waivers == []
    with get_db(str(ctx.db_path)) as conn:
        assert conn.execute("SELECT screenshot FROM news WHERE id=1").fetchone()[0] == str(valid.resolve())


def test_alternate_source_and_unclassified_omission_still_require_user(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ctx, machine = setup_run(tmp_path)
    directory = tmp_path / "output/images/20260627"
    directory.mkdir(parents=True)
    image = directory / "image.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\nimage")
    with get_db(str(ctx.db_path)) as conn:
        conn.execute("UPDATE news SET screenshot=? WHERE id=1", (str(image),))
    base = ["repair-screenshot", "hackernews", "1", "--date", "20260627", "--url",
            "https://example.com/story", "--reason", "source repair"]
    for extra in (["--omit"], ["--replacement-file", str(image), "--replacement-url", "https://other.example.com/story"]):
        result = CliRunner().invoke(main, [*base, *extra])
        assert result.exit_code != 0
        assert "--user-confirmed" in result.output
