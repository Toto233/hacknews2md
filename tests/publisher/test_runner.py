from unittest.mock import MagicMock

from hn2md.constants import Stage as HnStage
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
