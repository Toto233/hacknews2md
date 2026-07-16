"""Job state machine and run ledger."""

from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from hn2md.constants import RETRY_BUDGETS, Stage

logger = logging.getLogger(__name__)


def _replace_with_retry(src: Path, dst: Path, attempts: int = 3, delay: float = 0.05) -> None:
    """Atomically replace a file, tolerating brief Windows file locks."""
    for attempt in range(attempts):
        try:
            os.replace(str(src), str(dst))
            return
        except PermissionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay)


VALID_TRANSITIONS: set[tuple[Stage, Stage]] = {
    (Stage.IDLE, Stage.FETCHING),
    (Stage.FETCHING, Stage.COLLECTING),
    (Stage.FETCHING, Stage.RENDERING),
    (Stage.FETCHING, Stage.FAILED),
    (Stage.COLLECTING, Stage.PLANNING),
    (Stage.COLLECTING, Stage.FAILED),
    (Stage.PLANNING, Stage.APPLYING),
    (Stage.PLANNING, Stage.FAILED),
    (Stage.APPLYING, Stage.RENDERING),
    (Stage.APPLYING, Stage.FAILED),
    (Stage.RENDERING, Stage.COVERING),
    (Stage.RENDERING, Stage.FAILED),
    (Stage.COVERING, Stage.PUBLISHING),
    (Stage.COVERING, Stage.FAILED),
    (Stage.PUBLISHING, Stage.DONE),
    (Stage.PUBLISHING, Stage.FAILED),
    # Re-publish an existing completed run to a new WeChat draft without re-rendering.
    (Stage.DONE, Stage.PUBLISHING),
    (Stage.FAILED, Stage.IDLE),
    # --from-stage resume
    (Stage.IDLE, Stage.COLLECTING),
    (Stage.IDLE, Stage.PLANNING),
    (Stage.IDLE, Stage.APPLYING),
    (Stage.IDLE, Stage.RENDERING),
    (Stage.IDLE, Stage.COVERING),
    (Stage.IDLE, Stage.PUBLISHING),
}


@dataclass
class StageReceipt:
    """Receipt for a single stage execution."""

    stage: str
    started_at: str
    finished_at: str
    success: bool
    input_summary: dict[str, Any] = field(default_factory=dict)
    output_summary: dict[str, Any] = field(default_factory=dict)
    error: str | None = None
    retry_count: int = 0
    artifacts: list[str] = field(default_factory=list)


@dataclass
class PublishJob:
    """Top-level job descriptor persisted as JSON run ledger."""

    date: str
    status: str = Stage.IDLE.value
    created_at: str = ""
    updated_at: str = ""
    stories: list[dict[str, Any]] = field(default_factory=list)
    stages: dict[str, Any] = field(default_factory=dict)
    receipts: dict[str, Any] = field(default_factory=dict)
    lock_pid: int | None = None
    error: str | None = None
    audit_report: dict[str, Any] | None = None
    audit_exemption: dict[str, Any] | None = None

    def to_json(self, path: Path) -> None:
        """Atomically write job state to JSON.

        Uses write-to-temp + os.replace() to prevent corruption
        if the process is killed mid-write. Also maintains a .bak
        copy for recovery.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(asdict(self), ensure_ascii=False, indent=2)

        tmp_path = path.with_suffix(".tmp")
        bak_path = path.with_suffix(".bak")

        try:
            # Write to temporary file first
            tmp_path.write_text(content, encoding="utf-8")

            # Backup existing file
            if path.exists():
                try:
                    path.rename(bak_path)
                except OSError:
                    # Backup failed — not critical, continue with replace
                    logger.debug(f"Failed to create backup: {bak_path}")

            # Atomic replace
            _replace_with_retry(tmp_path, path)
        except OSError as e:
            logger.error(f"State write failed: {e} | path={path}")
            # Attempt recovery from backup
            if bak_path.exists() and not path.exists():
                try:
                    bak_path.rename(path)
                    logger.info(f"Recovered state from backup: {bak_path}")
                except OSError:
                    pass
            raise

    @classmethod
    def from_json(cls, path: Path) -> PublishJob:
        """Load job state from JSON with backup fallback.

        If the primary file is corrupted, attempts to load from .bak.
        If both fail, raises the original error.
        """
        bak_path = path.with_suffix(".bak")

        # Try primary file
        try:
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            return cls(**data)
        except (json.JSONDecodeError, KeyError, TypeError) as primary_error:
            logger.warning(f"Primary state file corrupted: {primary_error} | path={path}")

            # Try backup file
            if bak_path.exists():
                try:
                    data = json.loads(bak_path.read_text(encoding="utf-8-sig"))
                    logger.info(f"Recovered state from backup: {bak_path}")
                    return cls(**data)
                except (json.JSONDecodeError, KeyError, TypeError) as backup_error:
                    logger.error(f"Backup also corrupted: {backup_error} | path={bak_path}")

            # Both failed
            raise primary_error


class JobStateMachine:
    """Manages PublishJob lifecycle with transitions, receipts, and retry budgets."""

    def __init__(self, job: PublishJob, ledger_path: Path):
        self.job = job
        self.ledger_path = ledger_path

    def can_transition(self, target: Stage) -> bool:
        current = Stage(self.job.status)
        return (current, target) in VALID_TRANSITIONS

    def transition(self, target: Stage) -> None:
        if not self.can_transition(target):
            raise ValueError(f"Invalid transition: {self.job.status} -> {target.value}")
        self.job.status = target.value
        self.job.updated_at = datetime.now().isoformat()
        self._save()

    def record_receipt(self, receipt: StageReceipt) -> None:
        serialized = asdict(receipt)
        history = self.job.receipts.get(receipt.stage)
        if isinstance(history, list):
            stage_history = history
        elif isinstance(history, dict):
            stage_history = [history]
        else:
            stage_history = []
            previous = self.job.stages.get(receipt.stage)
            if isinstance(previous, dict):
                stage_history.append(previous)
        stage_history.append(serialized)
        self.job.receipts[receipt.stage] = stage_history
        self.job.stages[receipt.stage] = serialized
        self.job.updated_at = datetime.now().isoformat()
        self._save()

    def can_retry(self, stage: Stage) -> bool:
        receipt = self.job.stages.get(stage.value)
        if not receipt:
            return True
        budget = RETRY_BUDGETS.get(stage, 1)
        return receipt.get("retry_count", 0) < budget

    def stage_completed_successfully(self, stage: Stage) -> bool:
        receipt = self.job.stages.get(stage.value)
        return receipt is not None and receipt.get("success", False)

    def record_audit_report(self, report: dict[str, Any]) -> None:
        """Persist the latest audit result and invalidate stale approval."""
        self.job.audit_report = report
        self.job.audit_exemption = None
        self.job.updated_at = datetime.now().isoformat()
        self._save()

    def approve_audit(self) -> None:
        """Approve the current blocking audit snapshot for this daily job."""
        report = self.job.audit_report
        if not report or not report.get("blocking_count"):
            raise ValueError("no blocking audit report to approve")
        self.job.audit_exemption = {
            "approved_at": datetime.now().isoformat(),
            "issue_snapshot": report.get("issues", []),
        }
        self.job.updated_at = datetime.now().isoformat()
        self._save()

    def _save(self) -> None:
        self.job.to_json(self.ledger_path)

    @classmethod
    def load_or_create(cls, job_dir: Path, date_str: str) -> tuple[JobStateMachine, Path]:
        ledger_path = job_dir / f"publish_job_{date_str}.json"
        if ledger_path.exists():
            job = PublishJob.from_json(ledger_path)
        else:
            now = datetime.now().isoformat()
            job = PublishJob(date=date_str, created_at=now, updated_at=now)
            job.to_json(ledger_path)
        return cls(job, ledger_path), ledger_path
