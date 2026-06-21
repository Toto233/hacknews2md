# -*- coding: utf-8 -*-
"""Tests for PublishStage dry-run mode."""

import sys
import types
import pytest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock

from hn2md.stages.publish import PublishStage
from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine, PublishJob
from hn2md.constants import Stage


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


def _make_machine(tmp_path: Path) -> JobStateMachine:
    """Build a JobStateMachine with a fresh job in PUBLISHING state."""
    job_dir = tmp_path / "output" / "jobs"
    job_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.now().isoformat()
    job = PublishJob(date="2026-06-20", status=Stage.PUBLISHING.value, created_at=now, updated_at=now)
    ledger_path = job_dir / "publish_job_2026-06-20.json"
    job.to_json(ledger_path)
    return JobStateMachine(job, ledger_path)


def _setup_md_file(tmp_path, machine, content="# Test\n\nSome content."):
    """Create a markdown file and register it in the machine's rendering receipt."""
    md_dir = tmp_path / "output" / "markdown"
    md_dir.mkdir(parents=True, exist_ok=True)
    md_file = md_dir / "test.md"
    md_file.write_text(content, encoding="utf-8")

    machine.job.stages[Stage.RENDERING.value] = {
        "stage": Stage.RENDERING.value,
        "success": True,
        "output_summary": {"markdown_file": str(md_file)},
    }
    return md_file


class TestPublishDryRun:
    """Test PublishStage in dry-run mode."""

    @patch("src.utils.db_utils.get_illegal_keywords", return_value=[])
    def test_dry_run_returns_dry_run_flag(self, mock_keywords, tmp_path):
        """PublishStage with dry_run=True should return dry_run=True."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)
        md_file = _setup_md_file(tmp_path, machine)

        stage = PublishStage()
        result = stage.execute(ctx, machine, dry_run=True)

        assert result["dry_run"] is True
        assert result["markdown_file"] == str(md_file)
        assert result["wechat_media_id"] is None
        assert result["safety_check"] == "passed"

    def test_dry_run_does_not_call_wechat(self, tmp_path):
        """PublishStage with dry_run=True should NOT import or call publish_wechat."""
        ctx = _make_ctx(tmp_path)
        machine = _make_machine(tmp_path)
        _setup_md_file(tmp_path, machine)

        stage = PublishStage()

        # Mock the DB functions to avoid database dependency
        with patch("src.utils.db_utils.get_illegal_keywords", return_value=[]):
            # Mock the publish_wechat module so we can verify it's never imported
            mock_module = types.ModuleType("scripts.publish_wechat")
            mock_module.main = MagicMock(return_value="fake_media_id")
            sys.modules["scripts.publish_wechat"] = mock_module
            try:
                result = stage.execute(ctx, machine, dry_run=True)
                # In dry-run mode, the import line is never reached,
                # so main() should not have been called
                mock_module.main.assert_not_called()
            finally:
                del sys.modules["scripts.publish_wechat"]

        assert result["dry_run"] is True
