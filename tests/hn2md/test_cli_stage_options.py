"""CLI options must reach their stage implementations."""

from contextlib import nullcontext
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from hn2md.cli import main
from hn2md.constants import Stage
from hn2md.context import RuntimeContext


def _runtime(tmp_path) -> RuntimeContext:
    return RuntimeContext(
        project_root=tmp_path,
        db_path=tmp_path / "data" / "hacknews.db",
        output_dir=tmp_path / "output",
        job_dir=tmp_path / "output" / "jobs",
        markdown_dir=tmp_path / "output" / "markdown",
        images_dir=tmp_path / "output" / "images",
        codex_dir=tmp_path / "output" / "codex",
        config_path=tmp_path / "config" / "config.json",
    )


def _invoke(tmp_path, args: list[str]) -> tuple[object, MagicMock, MagicMock]:
    runtime = _runtime(tmp_path)
    machine = MagicMock()
    stage = MagicMock()
    stage.run.return_value.output_summary = {}

    with (
        patch("hn2md.cli.RuntimeContext.create", return_value=runtime),
        patch("hn2md.cli.JobStateMachine.load_or_create", return_value=(machine, runtime.job_dir / "job.json")),
        patch("hn2md.cli.daily_lock", side_effect=lambda *_args, **_kwargs: nullcontext()),
        patch("hn2md.cli._load_stage", return_value=stage),
    ):
        result = CliRunner().invoke(main, args)

    return result, stage, machine


def test_collect_forwards_concurrency(tmp_path) -> None:
    result, stage, machine = _invoke(tmp_path, ["collect", "--concurrency", "5"])

    assert result.exit_code == 0, result.output
    stage.run.assert_called_once_with(_runtime(tmp_path), machine, concurrency=5)


def test_plan_forwards_manual_plan(tmp_path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text("{}", encoding="utf-8")

    result, stage, machine = _invoke(tmp_path, ["plan", "--manual-plan", str(plan)])

    assert result.exit_code == 0, result.output
    stage.run.assert_called_once_with(
        _runtime(tmp_path),
        machine,
        llm=None,
        manual_plan_file=str(plan),
    )


def test_apply_forwards_plan_file(tmp_path) -> None:
    plan = tmp_path / "plan.json"

    result, stage, machine = _invoke(tmp_path, ["apply", str(plan)])

    assert result.exit_code == 0, result.output
    stage.run.assert_called_once_with(_runtime(tmp_path), machine, plan_file=str(plan))


def test_cover_forwards_all_options(tmp_path) -> None:
    markdown = tmp_path / "article.md"

    result, stage, machine = _invoke(
        tmp_path,
        ["cover", str(markdown), "--mode", "ai", "--target-word", "主体事件"],
    )

    assert result.exit_code == 0, result.output
    stage.run.assert_called_once_with(
        _runtime(tmp_path),
        machine,
        markdown_file=str(markdown),
        mode="ai",
        target_word="主体事件",
    )


def test_publish_forwards_paths(tmp_path) -> None:
    markdown = tmp_path / "article.md"
    cover = tmp_path / "cover.png"

    result, stage, machine = _invoke(
        tmp_path,
        ["publish", str(markdown), "--cover-image", str(cover)],
    )

    assert result.exit_code == 0, result.output
    stage.run.assert_called_once_with(
        _runtime(tmp_path),
        machine,
        markdown_file=str(markdown),
        cover_image=str(cover),
    )


def test_publish_marks_job_done_after_success(tmp_path) -> None:
    markdown = tmp_path / "article.md"

    result, _stage, machine = _invoke(tmp_path, ["publish", str(markdown)])

    assert result.exit_code == 0, result.output
    machine.transition.assert_called_once_with(Stage.DONE)
