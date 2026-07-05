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

    def _ensure_astro_staging_clean(self, astro_blog_dir: Path | None) -> None:
        """Block Astro rendering when the target repo already has staged changes."""
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
        # ANTI-FLIP-FLOP: astro_enabled defaults to True.
        # See docs/DECISIONS.md "Full HackNews publish defaults to WeChat and Astro".
        # Do NOT change the default to False — silently dropping Astro means
        # days of missing blog content before anyone notices. Only callers that
        # explicitly pass astro_enabled=False should skip Astro output.
        from src.core.generate_markdown import generate_markdown
        from src.utils.deployment import load_deployment_settings

        apply_receipt = machine.job.stages.get(Stage.APPLYING.value)
        plan_file = apply_receipt.get("output_summary", {}).get("plan_file") if apply_receipt else None
        if not plan_file:
            raise RuntimeError("No plan file from APPLYING stage")

        settings = load_deployment_settings(project_root=ctx.project_root)
        astro_blog_dir = settings.astro_blog_dir if astro_enabled else None
        self._ensure_astro_staging_clean(astro_blog_dir)
        return generate_markdown(
            db_path=ctx.db_path,
            output_dir=ctx.markdown_dir,
            plan_file=Path(plan_file),
            astro_blog_dir=astro_blog_dir,
        )
