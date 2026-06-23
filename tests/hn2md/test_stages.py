# -*- coding: utf-8 -*-
"""Tests for BaseStage retry, transitions, and receipt recording."""

import json
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from hn2md.stages.base import BaseStage, redact_err
from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine, PublishJob, StageReceipt
from hn2md.constants import Stage


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_ctx(tmp_path: Path) -> RuntimeContext:
    """Build a minimal RuntimeContext pointing at tmp_path."""
    return RuntimeContext(
        project_root=tmp_path,
        db_path=tmp_path / "test.db",
        output_dir=tmp_path / "output",
        job_dir=tmp_path / "output" / "jobs",
        markdown_dir=tmp_path / "output" / "markdown",
        images_dir=tmp_path / "output" / "images",
        codex_dir=tmp_path / "output" / "codex",
        config_path=tmp_path / "config.json",
    )


def _make_machine(tmp_path: Path, stage: Stage = Stage.IDLE) -> JobStateMachine:
    """Build a JobStateMachine with a fresh job in IDLE state."""
    job_dir = tmp_path / "output" / "jobs"
    job_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat()
    job = PublishJob(date="2026-06-20", status=stage.value, created_at=now, updated_at=now)
    ledger_path = job_dir / "publish_job_2026-06-20.json"
    job.to_json(ledger_path)
    return JobStateMachine(job, ledger_path)


def _make_stage(sn: Stage, succeed_after: int = 0, max_retries: int = 2):
    """Create a concrete stage that fails *succeed_after* times then succeeds.

    If succeed_after is -1, the stage always fails.
    Returns (stage_instance, call_log_list).
    """
    call_log = []
    _succeed_after = succeed_after

    def _execute(self, ctx, machine):
        call_log.append(1)
        if _succeed_after == -1 or len(call_log) <= _succeed_after:
            raise ConnectionError(f"transient failure #{len(call_log)}")
        return {"items": 42}

    LoggingStage = type(
        "LoggingStage",
        (BaseStage,),
        {
            "stage_name": sn,
            "max_retries": max_retries,
            "execute": _execute,
        },
    )
    return LoggingStage(), call_log


# ---------------------------------------------------------------------------
# Tests: BaseStage.run succeeds
# ---------------------------------------------------------------------------

class TestBaseStageRunSucceeds:
    """Test BaseStage.run on successful execution."""

    def test_run_returns_receipt_on_success(self, tmp_path):
        """run() should return a StageReceipt with success=True."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)

        stage, _ = _make_stage(Stage.FETCHING, succeed_after=0)
        with patch("hn2md.stages.base.time.sleep"):
            receipt = stage.run(ctx, machine)

        assert isinstance(receipt, StageReceipt)
        assert receipt.success is True
        assert receipt.stage == "FETCHING"
        assert receipt.output_summary == {"items": 42}
        assert receipt.error is None

    def test_run_records_timestamps(self, tmp_path):
        """run() should set started_at and finished_at."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)

        stage, _ = _make_stage(Stage.COLLECTING, succeed_after=0)
        with patch("hn2md.stages.base.time.sleep"):
            receipt = stage.run(ctx, machine)

        assert receipt.started_at != ""
        assert receipt.finished_at != ""
        assert receipt.finished_at >= receipt.started_at

    def test_run_records_receipt_in_machine(self, tmp_path):
        """run() should persist the receipt into the machine's job stages."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)

        stage, _ = _make_stage(Stage.FETCHING, succeed_after=0)
        with patch("hn2md.stages.base.time.sleep"):
            stage.run(ctx, machine)

        assert "FETCHING" in machine.job.stages
        stored = machine.job.stages["FETCHING"]
        assert stored["success"] is True


# ---------------------------------------------------------------------------
# Tests: BaseStage.run retries on transient failure
# ---------------------------------------------------------------------------

class TestBaseStageRunRetries:
    """Test that BaseStage.run retries on transient failures."""

    def test_retries_and_succeeds(self, tmp_path):
        """run() should retry and succeed after transient failures."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)

        stage, call_log = _make_stage(Stage.FETCHING, succeed_after=2, max_retries=3)
        with patch("hn2md.stages.base.time.sleep"):
            receipt = stage.run(ctx, machine)

        assert receipt.success is True
        assert len(call_log) == 3  # 2 failures + 1 success

    def test_retry_preserves_last_error_on_all_fail(self, tmp_path):
        """If all retries fail, the receipt should contain the last error."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)

        stage, call_log = _make_stage(Stage.FETCHING, succeed_after=-1, max_retries=2)
        with patch("hn2md.stages.base.time.sleep"):
            with pytest.raises(ConnectionError):
                stage.run(ctx, machine)

        assert len(call_log) == 3  # 1 initial + 2 retries

    def test_retry_sleeps_between_attempts(self, tmp_path):
        """run() should call time.sleep between retry attempts."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)

        stage, _ = _make_stage(Stage.FETCHING, succeed_after=-1, max_retries=2)
        with patch("hn2md.stages.base.time.sleep") as mock_sleep:
            with pytest.raises(ConnectionError):
                stage.run(ctx, machine)

        # Should sleep twice (after attempt 1 and 2, not after final attempt 3)
        assert mock_sleep.call_count == 2


# ---------------------------------------------------------------------------
# Tests: BaseStage.run gives up after max_retries
# ---------------------------------------------------------------------------

class TestBaseStageRunGivesUp:
    """Test that BaseStage.run raises after exhausting retries."""

    def test_raises_after_max_retries(self, tmp_path):
        """run() should re-raise the exception after max_retries."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)

        stage, call_log = _make_stage(Stage.FETCHING, succeed_after=-1, max_retries=1)
        with patch("hn2md.stages.base.time.sleep"):
            with pytest.raises(ConnectionError, match="transient failure"):
                stage.run(ctx, machine)

        assert len(call_log) == 2  # 1 initial + 1 retry

    def test_zero_retries_raises_immediately(self, tmp_path):
        """With max_retries=0, run() should call execute() once and raise."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)

        stage, call_log = _make_stage(Stage.COLLECTING, succeed_after=-1, max_retries=0)
        with patch("hn2md.stages.base.time.sleep"):
            with pytest.raises(ConnectionError):
                stage.run(ctx, machine)

        assert len(call_log) == 1

    def test_records_failure_in_receipt(self, tmp_path):
        """A failed run should record error in the receipt."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)

        stage, _ = _make_stage(Stage.FETCHING, succeed_after=-1, max_retries=1)
        with patch("hn2md.stages.base.time.sleep"):
            with pytest.raises(ConnectionError):
                stage.run(ctx, machine)

        stored = machine.job.stages.get("FETCHING")
        assert stored is not None
        assert stored["success"] is False
        assert "transient failure" in stored["error"]

    def test_failed_stage_can_be_rerun_within_retry_budget(self, tmp_path):
        """A failed stage should be runnable again instead of getting stuck in its own status."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)

        failing_stage, _ = _make_stage(Stage.FETCHING, succeed_after=-1, max_retries=0)
        with patch("hn2md.stages.base.time.sleep"):
            with pytest.raises(ConnectionError):
                failing_stage.run(ctx, machine)

        retry_stage, _ = _make_stage(Stage.FETCHING, succeed_after=0, max_retries=0)
        receipt = retry_stage.run(ctx, machine)

        assert receipt.success is True
        assert machine.job.status == Stage.FETCHING.value
        assert machine.job.stages["FETCHING"]["success"] is True

    def test_retry_budget_exhausted_raises(self, tmp_path):
        """run() should raise RuntimeError when retry budget is exhausted."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)

        # Pre-fill the receipt with a retry_count exceeding the budget
        machine.job.stages["FETCHING"] = {
            "stage": "FETCHING",
            "retry_count": 10,
            "success": False,
        }
        machine._save()

        stage, _ = _make_stage(Stage.FETCHING, succeed_after=0, max_retries=2)
        with pytest.raises(RuntimeError, match="Retry budget exhausted"):
            stage.run(ctx, machine)


# ---------------------------------------------------------------------------
# Tests: Receipt recording
# ---------------------------------------------------------------------------

class TestReceiptRecording:
    """Test that receipts are correctly built and persisted."""

    def test_receipt_has_stage_name(self, tmp_path):
        """Receipt stage field should match the stage's stage_name."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)

        stage, _ = _make_stage(Stage.COLLECTING, succeed_after=0)
        with patch("hn2md.stages.base.time.sleep"):
            receipt = stage.run(ctx, machine)

        assert receipt.stage == "COLLECTING"

    def test_receipt_output_summary_on_success(self, tmp_path):
        """Receipt should contain the execute() return value as output_summary."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)

        stage, _ = _make_stage(Stage.FETCHING, succeed_after=0)
        with patch("hn2md.stages.base.time.sleep"):
            receipt = stage.run(ctx, machine)

        assert receipt.output_summary == {"items": 42}

    def test_receipt_persisted_to_json(self, tmp_path):
        """The receipt should be saved to the ledger JSON file."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)

        stage, _ = _make_stage(Stage.FETCHING, succeed_after=0)
        with patch("hn2md.stages.base.time.sleep"):
            stage.run(ctx, machine)

        # Re-read the ledger file
        data = json.loads(machine.ledger_path.read_text(encoding="utf-8"))
        assert "FETCHING" in data["stages"]
        assert data["stages"]["FETCHING"]["success"] is True


class TestRedactErr:
    """Test the redact_err helper."""

    def test_short_message_unchanged(self):
        """Short messages should be returned as-is."""
        assert redact_err("short") == "short"

    def test_long_message_truncated(self):
        """Messages over 200 chars should be truncated with '...'."""
        msg = "x" * 250
        result = redact_err(msg)
        assert len(result) == 203  # 200 + len("...")
        assert result.endswith("...")

    def test_exact_200_chars_unchanged(self):
        """A 200-char message should not be truncated."""
        msg = "a" * 200
        assert redact_err(msg) == msg

    def test_empty_message(self):
        """Empty message should return empty string."""
        assert redact_err("") == ""
