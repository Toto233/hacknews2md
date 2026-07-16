# -*- coding: utf-8 -*-
"""Tests for job state machine and atomic writes."""

import json
import os
import pytest
from pathlib import Path
from datetime import datetime

from hn2md.state import PublishJob, JobStateMachine, StageReceipt, Stage


@pytest.fixture
def job_dir(tmp_path):
    """Create a temporary job directory."""
    return tmp_path / "jobs"


@pytest.fixture
def sample_job():
    """Create a sample PublishJob."""
    now = datetime.now().isoformat()
    return PublishJob(
        date="20260620",
        status=Stage.IDLE.value,
        created_at=now,
        updated_at=now,
    )


class TestPublishJob:
    """Tests for PublishJob dataclass."""

    def test_to_json_creates_file(self, sample_job, job_dir):
        """to_json should create the file."""
        job_dir.mkdir(parents=True)
        path = job_dir / "test_job.json"
        sample_job.to_json(path)
        assert path.exists()

    def test_to_json_content(self, sample_job, job_dir):
        """to_json should write valid JSON."""
        job_dir.mkdir(parents=True)
        path = job_dir / "test_job.json"
        sample_job.to_json(path)

        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["date"] == "20260620"
        assert data["status"] == Stage.IDLE.value

    def test_from_json_roundtrip(self, sample_job, job_dir):
        """to_json -> from_json should preserve all fields."""
        job_dir.mkdir(parents=True)
        path = job_dir / "test_job.json"
        sample_job.to_json(path)

        loaded = PublishJob.from_json(path)
        assert loaded.date == sample_job.date
        assert loaded.status == sample_job.status
        assert loaded.created_at == sample_job.created_at

    def test_from_json_accepts_utf8_bom(self, sample_job, job_dir):
        """PowerShell-written UTF-8 BOM JSON should still load."""
        job_dir.mkdir(parents=True)
        path = job_dir / "test_job.json"
        path.write_text(json.dumps(sample_job.__dict__), encoding="utf-8-sig")

        loaded = PublishJob.from_json(path)

        assert loaded.date == sample_job.date
        assert loaded.status == sample_job.status

    def test_to_json_creates_directory(self, sample_job, job_dir):
        """to_json should create parent directories."""
        path = job_dir / "subdir" / "test_job.json"
        sample_job.to_json(path)
        assert path.exists()

    def test_atomic_write_creates_backup(self, sample_job, job_dir):
        """to_json should create .bak file on second write."""
        job_dir.mkdir(parents=True)
        path = job_dir / "test_job.json"
        bak_path = path.with_suffix(".bak")

        # First write
        sample_job.to_json(path)
        assert not bak_path.exists()

        # Second write should create backup
        sample_job.to_json(path)
        assert bak_path.exists()

    def test_atomic_write_retries_transient_windows_lock(self, sample_job, job_dir, monkeypatch):
        """A transient Windows file lock should not fail the state write."""
        job_dir.mkdir(parents=True)
        path = job_dir / "test_job.json"
        real_replace = os.replace
        attempts = 0

        def flaky_replace(src, dst):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise PermissionError(5, "Access is denied")
            return real_replace(src, dst)

        monkeypatch.setattr("hn2md.state.os.replace", flaky_replace)

        sample_job.to_json(path)

        assert attempts == 2
        assert path.exists()

    def test_from_json_corrupted_primary_recovers_from_backup(self, sample_job, job_dir):
        """from_json should recover from .bak if primary is corrupted."""
        job_dir.mkdir(parents=True)
        path = job_dir / "test_job.json"
        bak_path = path.with_suffix(".bak")

        # Write valid data
        sample_job.to_json(path)

        # Create backup (second write)
        sample_job.to_json(path)

        # Corrupt primary file
        path.write_text("not valid json", encoding="utf-8")

        # Should recover from backup
        loaded = PublishJob.from_json(path)
        assert loaded.date == sample_job.date

    def test_from_json_both_corrupted_raises(self, sample_job, job_dir):
        """from_json should raise if both primary and backup are corrupted."""
        job_dir.mkdir(parents=True)
        path = job_dir / "test_job.json"
        bak_path = path.with_suffix(".bak")

        # Write valid data then create backup
        sample_job.to_json(path)
        sample_job.to_json(path)

        # Corrupt both files
        path.write_text("corrupt1", encoding="utf-8")
        bak_path.write_text("corrupt2", encoding="utf-8")

        with pytest.raises((json.JSONDecodeError, KeyError)):
            PublishJob.from_json(path)


class TestJobStateMachine:
    """Tests for JobStateMachine transitions."""

    def test_valid_transition(self, job_dir):
        """Should allow valid transitions."""
        job_dir.mkdir(parents=True)
        machine, _ = JobStateMachine.load_or_create(job_dir, "20260620")
        assert machine.can_transition(Stage.FETCHING)

    def test_invalid_transition(self, job_dir):
        """Should reject invalid transitions."""
        job_dir.mkdir(parents=True)
        machine, _ = JobStateMachine.load_or_create(job_dir, "20260620")
        # Can't go from IDLE directly to DONE
        assert not machine.can_transition(Stage.DONE)

    def test_transition_updates_status(self, job_dir):
        """transition should update job status."""
        job_dir.mkdir(parents=True)
        machine, _ = JobStateMachine.load_or_create(job_dir, "20260620")
        machine.transition(Stage.FETCHING)
        assert machine.job.status == Stage.FETCHING.value

    def test_transition_persists(self, job_dir):
        """transition should persist to disk."""
        job_dir.mkdir(parents=True)
        machine, ledger_path = JobStateMachine.load_or_create(job_dir, "20260620")
        machine.transition(Stage.FETCHING)

        # Reload from disk
        loaded_job = PublishJob.from_json(ledger_path)
        assert loaded_job.status == Stage.FETCHING.value

    def test_resume_transitions(self, job_dir):
        """IDLE should be able to jump to any stage (for --from-stage)."""
        job_dir.mkdir(parents=True)
        machine, _ = JobStateMachine.load_or_create(job_dir, "20260620")
        for stage in [Stage.COLLECTING, Stage.PLANNING, Stage.APPLYING,
                      Stage.RENDERING, Stage.COVERING, Stage.PUBLISHING]:
            # Fresh machine for each test
            machine2, _ = JobStateMachine.load_or_create(job_dir, "20260620")
            assert machine2.can_transition(stage)

    def test_load_or_create_new(self, job_dir):
        """load_or_create should create new job if none exists."""
        job_dir.mkdir(parents=True)
        machine, ledger_path = JobStateMachine.load_or_create(job_dir, "20260620")
        assert machine.job.date == "20260620"
        assert machine.job.status == Stage.IDLE.value
        assert ledger_path.exists()

    def test_load_or_create_existing(self, job_dir):
        """load_or_create should load existing job."""
        job_dir.mkdir(parents=True)
        machine1, _ = JobStateMachine.load_or_create(job_dir, "20260620")
        machine1.transition(Stage.FETCHING)

        machine2, _ = JobStateMachine.load_or_create(job_dir, "20260620")
        assert machine2.job.status == Stage.FETCHING.value

    def test_record_receipt(self, job_dir):
        """record_receipt should store receipt in job."""
        job_dir.mkdir(parents=True)
        machine, _ = JobStateMachine.load_or_create(job_dir, "20260620")
        receipt = StageReceipt(
            stage=Stage.FETCHING.value,
            started_at=datetime.now().isoformat(),
            finished_at=datetime.now().isoformat(),
            success=True,
            output_summary={"count": 10},
        )
        machine.record_receipt(receipt)
        assert Stage.FETCHING.value in machine.job.stages

    def test_record_receipt_preserves_stage_history(self, job_dir):
        """record_receipt should retain every execution while exposing the latest receipt."""
        job_dir.mkdir(parents=True)
        machine, ledger_path = JobStateMachine.load_or_create(job_dir, "20260620")
        first = StageReceipt(
            stage=Stage.COLLECTING.value,
            started_at=datetime.now().isoformat(),
            finished_at=datetime.now().isoformat(),
            success=True,
            output_summary={"content_warnings": [{"id": 42, "reason": "missing"}]},
        )
        second = StageReceipt(
            stage=Stage.COLLECTING.value,
            started_at=datetime.now().isoformat(),
            finished_at=datetime.now().isoformat(),
            success=True,
            output_summary={"content_warnings": []},
        )

        machine.record_receipt(first)
        machine.record_receipt(second)

        assert machine.job.stages[Stage.COLLECTING.value] == second.__dict__
        assert machine.job.receipts[Stage.COLLECTING.value] == [first.__dict__, second.__dict__]
        reloaded = PublishJob.from_json(ledger_path)
        assert reloaded.receipts[Stage.COLLECTING.value] == [first.__dict__, second.__dict__]

    def test_record_receipt_migrates_latest_receipt_from_legacy_ledger(self, job_dir):
        """The first rerun after upgrade should preserve the pre-history stage receipt."""
        job_dir.mkdir(parents=True)
        machine, _ = JobStateMachine.load_or_create(job_dir, "20260620")
        legacy_receipt = StageReceipt(
            stage=Stage.COLLECTING.value,
            started_at=datetime.now().isoformat(),
            finished_at=datetime.now().isoformat(),
            success=True,
            output_summary={"content_warnings": [{"id": 42, "reason": "missing"}]},
        )
        rerun_receipt = StageReceipt(
            stage=Stage.COLLECTING.value,
            started_at=datetime.now().isoformat(),
            finished_at=datetime.now().isoformat(),
            success=True,
            output_summary={"content_warnings": []},
        )
        machine.job.stages[Stage.COLLECTING.value] = legacy_receipt.__dict__
        machine.job.receipts = {}

        machine.record_receipt(rerun_receipt)

        assert machine.job.receipts[Stage.COLLECTING.value] == [
            legacy_receipt.__dict__,
            rerun_receipt.__dict__,
        ]

    def test_stage_completed_successfully(self, job_dir):
        """stage_completed_successfully should check receipt success."""
        job_dir.mkdir(parents=True)
        machine, _ = JobStateMachine.load_or_create(job_dir, "20260620")
        assert not machine.stage_completed_successfully(Stage.FETCHING)

        receipt = StageReceipt(
            stage=Stage.FETCHING.value,
            started_at=datetime.now().isoformat(),
            finished_at=datetime.now().isoformat(),
            success=True,
        )
        machine.record_receipt(receipt)
        assert machine.stage_completed_successfully(Stage.FETCHING)

    def test_can_retry(self, job_dir):
        """can_retry should check retry budget."""
        job_dir.mkdir(parents=True)
        machine, _ = JobStateMachine.load_or_create(job_dir, "20260620")
        assert machine.can_retry(Stage.FETCHING)
