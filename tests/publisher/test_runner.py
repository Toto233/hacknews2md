from unittest.mock import MagicMock

from hn2md.constants import Stage as HnStage
from hn2md.state import JobStateMachine
from publisher.constants import GenericStage
from publisher.context import PublisherContext
from publisher.pipeline.runner import run_release
from publisher.sources.base import SourceDefinition


class FakeStage:
    stage_name = HnStage.FETCHING

    def __init__(self) -> None:
        self.run = MagicMock()
        self.run.return_value.finished_at = "done"
        self.run.return_value.output_summary = {"ok": True}


class FakePublishStage(FakeStage):
    stage_name = HnStage.PUBLISHING


class FakeRenderStage(FakeStage):
    stage_name = HnStage.RENDERING


def test_run_release_invokes_source_stages_in_order(tmp_path) -> None:
    fake_stage = FakeStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.FETCHING: lambda: fake_stage},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")

    result = run_release(ctx, source, stages=[GenericStage.FETCHING], dry_run=True)

    assert result["source"] == "hackernews"
    assert result["period"] == "20260627"
    assert result["dry_run"] is True
    assert result["completed_stages"] == ["FETCHING"]
    fake_stage.run.assert_called_once()


def test_run_release_rejects_stage_missing_required_artifact(tmp_path) -> None:
    fake_stage = FakeStage()
    fake_stage.run.return_value.output_summary = {}
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.FETCHING: lambda: fake_stage},
        required_artifacts={GenericStage.FETCHING: ("markdown_file",)},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")

    try:
        run_release(ctx, source, stages=[GenericStage.FETCHING], dry_run=True)
    except RuntimeError as exc:
        assert "FETCHING missing required artifacts: markdown_file" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_run_release_can_rerun_publishing_from_done_without_prior_stages(tmp_path) -> None:
    fake_stage = FakePublishStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.PUBLISHING: lambda: fake_stage},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    machine.job.status = HnStage.DONE.value
    machine._save()

    result = run_release(
        ctx,
        source,
        stages=[GenericStage.PUBLISHING],
        dry_run=False,
        targets=("wechat",),
        rerun=True,
    )

    assert result["completed_stages"] == ["PUBLISHING"]
    reloaded, _ = JobStateMachine.load_or_create(ctx.job_dir, ctx.period)
    assert reloaded.job.status == HnStage.DONE.value
    fake_stage.run.assert_called_once()


def test_run_release_disables_astro_render_for_wechat_only_target(tmp_path) -> None:
    fake_stage = FakeRenderStage()
    fake_stage.run.return_value.output_summary = {"markdown_file": "a.md", "html_file": "a.html"}
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.RENDERING: lambda: fake_stage},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")

    run_release(ctx, source, stages=[GenericStage.RENDERING], targets=("wechat",))

    fake_stage.run.assert_called_once()
    assert fake_stage.run.call_args.kwargs["astro_enabled"] is False


def test_run_release_passes_stage_specific_kwargs(tmp_path) -> None:
    fake_stage = FakeStage()
    source = SourceDefinition(
        name="hackernews",
        period_kind="date",
        stages={GenericStage.COLLECTING: lambda: fake_stage},
    )
    ctx = PublisherContext.create(tmp_path, source="hackernews", period="20260627")

    run_release(
        ctx,
        source,
        stages=[GenericStage.COLLECTING],
        stage_kwargs={GenericStage.COLLECTING: {"concurrency": 5}},
    )

    fake_stage.run.assert_called_once()
    assert fake_stage.run.call_args.kwargs["concurrency"] == 5
