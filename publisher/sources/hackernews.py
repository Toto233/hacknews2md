from __future__ import annotations

import requests

from hn2md.stages.apply import ApplyStage
from hn2md.stages.collect import CollectStage
from hn2md.stages.cover import CoverStage
from hn2md.stages.fetch import FetchStage
from hn2md.stages.base import NonRetryableStageError
from hn2md.stages.plan import PlanStage
from hn2md.stages.publish import PublishStage
from hn2md.stages.render import RenderStage
from hn2md.stages.screenshot import CaptureScreenshotsStage
from publisher.constants import GenericStage
from publisher.sources.base import SourceDefinition


class BrowserFrontFetchStage(FetchStage):
    """Allow explicit browser-/front recovery without changing the normal scraper."""

    def execute(self, ctx, machine, *, front_ids: str | None = None) -> dict[str, object]:
        if front_ids is None:
            try:
                return super().execute(ctx, machine)
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code == 419:
                    raise NonRetryableStageError(
                        "HN /front returned HTTP 419. Inspect the dated /front page in a browser, "
                        "then use 'publisher fetch hackernews --front-ids <ordered IDs>' "
                        "for the verified browser ranking; do not substitute current topstories."
                    ) from exc
                raise

        from hn2md.stages.fetch import _story_metadata
        from publisher.hn_front_recovery import fetch_browser_front_ids
        from src.core.archive_news import archive_old_news
        from src.core.fetch_news import save_to_database
        from src.utils.db_utils import init_database

        init_database()
        archive_old_news()
        items = fetch_browser_front_ids(front_ids)
        if len(items) != 10:
            raise ValueError(f"browser /front recovery selected {len(items)} stories; expected 10")
        saved = save_to_database(items)
        if saved != len(items):
            raise ValueError(f"browser /front recovery saved {saved}/{len(items)} stories")
        machine.job.stories = [_story_metadata(item) for item in items]
        return {"fetched": len(items), "saved": saved, "source": "browser_front_ids_hn_api"}


HACKERNEWS_SOURCE = SourceDefinition(
    name="hackernews",
    period_kind="date",
    stages={
        GenericStage.FETCHING: BrowserFrontFetchStage,
        GenericStage.COLLECTING: CollectStage,
        GenericStage.CAPTURING: CaptureScreenshotsStage,
        GenericStage.PLANNING: PlanStage,
        GenericStage.APPLYING: ApplyStage,
        GenericStage.RENDERING: RenderStage,
        GenericStage.COVERING: CoverStage,
        GenericStage.PUBLISHING: PublishStage,
    },
    stage_order=(
        GenericStage.FETCHING,
        GenericStage.COLLECTING,
        GenericStage.CAPTURING,
        GenericStage.PLANNING,
        GenericStage.APPLYING,
        GenericStage.RENDERING,
        GenericStage.COVERING,
        GenericStage.PUBLISHING,
    ),
    required_artifacts={
        GenericStage.RENDERING: ("markdown_file", "html_file"),
        GenericStage.COVERING: ("cover_image",),
    },
    supports_domain_filter=True,
)
