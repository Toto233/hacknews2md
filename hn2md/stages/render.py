"""Render stage: generate Markdown/HTML from database."""

from pathlib import Path
import subprocess
from typing import Any

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine
from hn2md.stages.base import BaseStage


class RenderStage(BaseStage):
    stage_name = Stage.RENDERING

    def _astro_skip_reason(self, settings: Any, astro_blog_dir: Path | None) -> str | None:
        if astro_blog_dir is None:
            return None
        astro_repo = getattr(settings, "astro_repo", None)
        if astro_repo and not Path(astro_repo).exists():
            return f"Astro repository not found: {astro_repo}"
        try:
            self._ensure_astro_staging_clean(astro_blog_dir)
        except RuntimeError as exc:
            return str(exc)
        return None

    def _ensure_astro_staging_clean(self, astro_blog_dir: Path | None) -> None:
        """Raise when Astro has staged changes that should be skipped."""
        if astro_blog_dir is None:
            return
        blog_dir = Path(astro_blog_dir).resolve()
        repo = None
        for candidate in (blog_dir, *blog_dir.parents):
            if (candidate / ".git").exists():
                repo = candidate
                break
        if repo is None:
            return
        result = subprocess.run(
            ["git", "-C", str(repo), "diff", "--cached", "--name-only"],
            text=True,
            capture_output=True,
            check=False,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Failed to inspect Astro repository staged changes: {result.stderr.strip()}")
        staged = [line.strip() for line in result.stdout.splitlines() if line.strip()]
        if staged:
            joined = ", ".join(staged)
            raise RuntimeError(f"Astro repository has staged changes before render: {joined}")

    def execute(self, ctx: RuntimeContext, machine: JobStateMachine, astro_enabled: bool = True) -> dict[str, Any]:
        # Astro is attempted by default, but repo/preflight failures are
        # recoverable follow-ups so they do not block the WeChat draft.
        # Do NOT change the default to False — silently dropping Astro means
        from src.core.generate_markdown import generate_markdown
        from src.utils.deployment import load_deployment_settings

        apply_receipt = machine.job.stages.get(Stage.APPLYING.value)
        plan_file = apply_receipt.get("output_summary", {}).get("plan_file") if apply_receipt else None
        if not plan_file:
            raise RuntimeError("No plan file from APPLYING stage")

        settings = load_deployment_settings(project_root=ctx.project_root)
        astro_blog_dir = settings.astro_blog_dir if astro_enabled else None
        astro_skip_reason = self._astro_skip_reason(settings, astro_blog_dir) if astro_enabled else None
        if astro_skip_reason:
            astro_blog_dir = None
        result = generate_markdown(
            db_path=ctx.db_path,
            output_dir=ctx.markdown_dir,
            plan_file=Path(plan_file),
            astro_blog_dir=astro_blog_dir,
        )
        if astro_skip_reason:
            result["astro_skipped"] = True
            result["astro_skip_reason"] = astro_skip_reason
        return result
