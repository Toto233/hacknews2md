from __future__ import annotations

from pathlib import Path
from typing import Any

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine
from hn2md.stages.base import BaseStage
from hn2md.stages.publish import PublishStage
from publisher.producthunt.db import ProductStore
from publisher.producthunt.fetch import FetchError, fetch_leaderboard, fetch_leaderboard_from_html_file
from publisher.producthunt.render import render_month


def period_to_year_month(period: str) -> tuple[int, int]:
    if len(period) != 6 or not period.isdigit():
        raise ValueError(f"Product Hunt period must be YYYYMM, got {period}")
    year = int(period[:4])
    month = int(period[4:])
    if month < 1 or month > 12:
        raise ValueError(f"Product Hunt month must be 1-12, got {month}")
    return year, month


class ProductHuntFetchStage(BaseStage):
    stage_name = Stage.FETCHING

    def execute(
        self,
        ctx: RuntimeContext,
        machine: JobStateMachine,
        limit: int = 25,
        html_file: str | None = None,
    ) -> dict[str, Any]:
        year, month = period_to_year_month(machine.job.date)
        store = ProductStore(ctx.db_path)
        store.init_schema()
        store.upsert_monthly_run(year, month, "FETCHING")

        try:
            if html_file:
                result = fetch_leaderboard_from_html_file(Path(html_file), year, month, limit)
            else:
                result = fetch_leaderboard(
                    year,
                    month,
                    limit,
                    debug_dir=ctx.output_dir / "debug" / f"{year}{month:02d}",
                )
        except FetchError:
            store.upsert_monthly_run(year, month, "FAILED")
            raise

        if not result.products:
            store.upsert_monthly_run(year, month, "FAILED")
            raise RuntimeError("No products parsed from Product Hunt leaderboard")

        store.replace_products_for_month(year, month, result.products)
        store.upsert_monthly_run(year, month, "FETCHED")
        return {
            "year": year,
            "month": month,
            "url": result.url,
            "total": len(result.products),
            "warnings": result.warnings,
            "db_path": str(ctx.db_path),
        }


class ProductHuntRenderStage(BaseStage):
    stage_name = Stage.RENDERING

    def execute(self, ctx: RuntimeContext, machine: JobStateMachine, astro_enabled: bool = False) -> dict[str, Any]:
        year, month = period_to_year_month(machine.job.date)
        result = render_month(ctx, year, month, astro_enabled=astro_enabled)
        ProductStore(ctx.db_path).update_monthly_run_artifacts(
            year,
            month,
            status="RENDERED",
            markdown_file=result["markdown_file"],
            html_file=result["html_file"],
            astro_file=result.get("astro_file"),
        )
        return result


class ProductHuntCoverStage(BaseStage):
    stage_name = Stage.COVERING

    def execute(
        self,
        ctx: RuntimeContext,
        machine: JobStateMachine,
        markdown_file: str | None = None,
        mode: str = "pillow",
        target_word: str | None = None,
    ) -> dict[str, Any]:
        year, month = period_to_year_month(machine.job.date)
        from publisher.producthunt.render import render_cover

        products = ProductStore(ctx.db_path).list_products(year, month)
        if not products:
            raise RuntimeError(f"No Product Hunt products found for {year}-{month:02d}")
        image_dir = ctx.images_dir / f"{year}{month:02d}"
        cover = image_dir / f"producthunt_cover_{year}{month:02d}.png"
        render_cover(cover, year, month, products)
        ProductStore(ctx.db_path).update_monthly_run_artifacts(year, month, status="COVERED", cover_image=str(cover))
        return {"cover_image": str(cover)}


class ProductHuntPublishStage(PublishStage):
    stage_name = Stage.PUBLISHING

    def execute(
        self,
        ctx: RuntimeContext,
        machine: JobStateMachine,
        dry_run: bool = False,
        markdown_file: str | None = None,
        cover_image: str | None = None,
    ) -> dict[str, Any]:
        result = super().execute(ctx, machine, dry_run=dry_run, markdown_file=markdown_file, cover_image=cover_image)
        year, month = period_to_year_month(machine.job.date)
        ProductStore(ctx.db_path).update_monthly_run_artifacts(
            year,
            month,
            status="PUBLISHED" if not dry_run else "PUBLISH_DRY_RUN",
            wechat_media_id=result.get("wechat_media_id"),
        )
        return result
