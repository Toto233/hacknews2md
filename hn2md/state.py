"""Job state machine and run ledger."""

from __future__ import annotations

import json
import hashlib
import logging
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from hn2md.constants import RETRY_BUDGETS, Stage

logger = logging.getLogger(__name__)

NON_EXEMPTIBLE_AUDIT_CODES = {
    "summary_too_short",
    "discussion_summary_too_short",
}


def _audit_issue_fingerprint(report: dict[str, Any]) -> str:
    """Return a stable fingerprint for the actionable issues in an audit report."""
    issues = report.get("issues", [])
    if not isinstance(issues, list):
        issues = []
    material = [
        {
            "news_id": issue.get("news_id"),
            "code": issue.get("code"),
            "message": issue.get("message"),
            "news_url": issue.get("news_url"),
            "action_required": issue.get("action_required"),
            "failure_count": issue.get("failure_count"),
        }
        for issue in issues
        if isinstance(issue, dict) and issue.get("severity", "blocking") == "blocking"
    ]
    encoded = json.dumps(material, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _audit_exemption_matches(exemption: dict[str, Any] | None, report: dict[str, Any]) -> bool:
    """Return whether an approval covers exactly the current blocking issue set."""
    return bool(
        exemption
        and exemption.get("issue_fingerprint")
        and exemption["issue_fingerprint"] == _audit_issue_fingerprint(report)
    )


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
    (Stage.COLLECTING, Stage.CAPTURING),
    (Stage.COLLECTING, Stage.FAILED),
    # A manual content repair can require collection to rerun after the visual
    # fallback has started or been interrupted.
    (Stage.CAPTURING, Stage.COLLECTING),
    (Stage.CAPTURING, Stage.PLANNING),
    (Stage.CAPTURING, Stage.FAILED),
    (Stage.PLANNING, Stage.APPLYING),
    (Stage.PLANNING, Stage.FAILED),
    (Stage.APPLYING, Stage.RENDERING),
    (Stage.APPLYING, Stage.FAILED),
    (Stage.RENDERING, Stage.COVERING),
    # Standard ImageGen covers are generated outside the legacy COVERING stage
    # and are supplied directly to the publish command.
    (Stage.RENDERING, Stage.PUBLISHING),
    (Stage.RENDERING, Stage.FAILED),
    (Stage.COVERING, Stage.PUBLISHING),
    (Stage.COVERING, Stage.FAILED),
    # A publish failure may reveal invalid rendered metadata (for example a
    # provider field-length limit), so allow the artifact to be regenerated.
    (Stage.PUBLISHING, Stage.RENDERING),
    (Stage.PUBLISHING, Stage.DONE),
    (Stage.PUBLISHING, Stage.FAILED),
    # Re-publish an existing completed run to a new WeChat draft without re-rendering.
    (Stage.DONE, Stage.PUBLISHING),
    (Stage.DONE, Stage.RENDERING),
    # A completed draft can receive a replacement cover before an intentional re-publish.
    (Stage.DONE, Stage.COVERING),
    (Stage.FAILED, Stage.IDLE),
    # --from-stage resume
    (Stage.IDLE, Stage.COLLECTING),
    (Stage.IDLE, Stage.CAPTURING),
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
    run_id: str | None = None


@dataclass
class PublishJob:
    """Top-level job descriptor persisted as JSON run ledger."""

    date: str
    status: str = Stage.IDLE.value
    created_at: str = ""
    updated_at: str = ""
    stories: list[dict[str, Any]] = field(default_factory=list)
    skipped_stories: list[dict[str, Any]] = field(default_factory=list)
    stages: dict[str, Any] = field(default_factory=dict)
    receipts: dict[str, Any] = field(default_factory=dict)
    lock_pid: int | None = None
    error: str | None = None
    audit_report: dict[str, Any] | None = None
    audit_exemption: dict[str, Any] | None = None
    publish_intent: dict[str, Any] | None = None
    manual_astro: dict[str, Any] | None = None
    continuation_notes: list[dict[str, Any]] | dict[str, Any] | None = None
    review_assessment: dict[str, Any] | None = None
    keyword_decisions: list[dict[str, Any]] = field(default_factory=list)
    screenshot_waivers: list[dict[str, Any]] = field(default_factory=list)
    remote_readback: dict[str, Any] | None = None
    run_id: str = ""

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
        """Persist the latest audit result and retain approval for identical issues."""
        previous_exemption = self.job.audit_exemption
        self.job.audit_report = report
        if not _audit_exemption_matches(previous_exemption, report):
            self.job.audit_exemption = None
        self.job.updated_at = datetime.now().isoformat()
        self._save()

    def invalidate_audit(self) -> None:
        """Clear audit state after publishable content changes."""
        self.job.audit_report = None
        self.job.audit_exemption = None
        self.job.updated_at = datetime.now().isoformat()
        self._save()

    def refresh_collection_context(self, context_file: str, story_id: int) -> None:
        """Record a manual repair without rerunning network collection."""
        receipt = self.job.stages.get(Stage.COLLECTING.value)
        if isinstance(receipt, dict):
            summary = receipt.setdefault("output_summary", {})
            if isinstance(summary, dict):
                summary["context_file"] = context_file
                warnings = summary.get("content_warnings")
                if isinstance(warnings, list):
                    summary["content_warnings"] = [
                        warning
                        for warning in warnings
                        if not isinstance(warning, dict) or warning.get("id") != story_id
                    ]
                repairs = summary.setdefault("manual_repairs", [])
                if isinstance(repairs, list):
                    repairs.append({"id": story_id, "refreshed_at": datetime.now().isoformat()})
        self.job.updated_at = datetime.now().isoformat()
        self._save()

    def record_skipped_story(self, story: dict[str, Any]) -> None:
        """Persist an intentional manual exclusion and remove it from active stories."""
        story_id = story["id"]
        self.job.stories = [item for item in self.job.stories if item.get("id") != story_id]
        self.job.skipped_stories = [
            item for item in self.job.skipped_stories if item.get("id") != story_id
        ]
        self.job.skipped_stories.append(story)
        self.job.updated_at = datetime.now().isoformat()
        self._save()

    def record_manual_astro(self, evidence: dict[str, Any]) -> None:
        """Persist verified Astro push evidence without reopening publication."""
        self.job.manual_astro = dict(evidence)
        intent = self.job.publish_intent
        if isinstance(intent, dict):
            requested = intent.setdefault("requested_targets", [])
            completed = intent.setdefault("completed_targets", [])
            if isinstance(requested, list) and "astro" not in requested:
                requested.append("astro")
            if isinstance(completed, list) and "astro" not in completed:
                completed.append("astro")
        self.job.updated_at = datetime.now().isoformat()
        self._save()

    def record_keyword_decision(self, decision: dict[str, Any]) -> None:
        """Persist one contextual keyword review, replacing the same sentence review."""
        keyword = str(decision.get("keyword") or "").strip()
        sentence = str(decision.get("sentence") or "").strip()
        if not keyword or not sentence:
            raise ValueError("keyword and sentence are required")
        self.job.keyword_decisions = [
            item
            for item in self.job.keyword_decisions
            if not (
                str(item.get("keyword") or "").strip() == keyword
                and str(item.get("sentence") or "").strip() == sentence
            )
        ]
        self.job.keyword_decisions.append(dict(decision))
        self.job.updated_at = datetime.now().isoformat()
        self._save()

    def approve_audit(self) -> None:
        """Approve the current blocking audit snapshot for this daily job."""
        report = self.job.audit_report
        if not report or not report.get("blocking_count"):
            raise ValueError("no blocking audit report to approve")
        non_exemptible = sorted(
            {
                str(issue.get("code"))
                for issue in report.get("issues", [])
                if isinstance(issue, dict) and issue.get("code") in NON_EXEMPTIBLE_AUDIT_CODES
            }
        )
        if non_exemptible:
            raise ValueError(
                "audit issues must be repaired and cannot be approved: " + ", ".join(non_exemptible)
            )
        self.job.audit_exemption = {
            "approved_at": datetime.now().isoformat(),
            "issue_snapshot": report.get("issues", []),
            "issue_fingerprint": _audit_issue_fingerprint(report),
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
            if not job.run_id:
                job.run_id = uuid.uuid4().hex
                job.updated_at = datetime.now().isoformat()
                job.to_json(ledger_path)
        else:
            now = datetime.now().isoformat()
            job = PublishJob(date=date_str, created_at=now, updated_at=now, run_id=uuid.uuid4().hex)
            job.to_json(ledger_path)
        return cls(job, ledger_path), ledger_path
