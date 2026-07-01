import json

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.state import JobStateMachine
from publisher.producthunt.db import ProductStore
from publisher.producthunt.stages import ProductHuntFetchStage
from publisher.constants import GenericStage
from publisher.context import PublisherContext
from publisher.pipeline.runner import run_release
from publisher.sources import get_source


def _ctx(tmp_path):
    return RuntimeContext(
        project_root=tmp_path,
        db_path=tmp_path / "data" / "producthunt.db",
        output_dir=tmp_path / "output",
        job_dir=tmp_path / "output" / "jobs",
        markdown_dir=tmp_path / "output" / "markdown",
        images_dir=tmp_path / "output" / "images",
        codex_dir=tmp_path / "output" / "codex",
        config_path=tmp_path / "config" / "config.json",
    )


def test_producthunt_fetch_stage_parses_html_file_into_producthunt_database(tmp_path) -> None:
    html_file = tmp_path / "leaderboard.html"
    html_file.write_text(
        """
        <html><body>
        <script id="__NEXT_DATA__" type="application/json">
        {
          "props": {
            "pageProps": {
              "posts": [
                {
                  "rank": 1,
                  "name": "Kilo Code",
                  "slug": "kilo-code",
                  "tagline": "AI coding agents for VS Code",
                  "url": "/products/kilo-code",
                  "votesCount": 321,
                  "commentsCount": 12,
                  "topics": [{"name": "Developer Tools"}],
                  "thumbnail": {"url": "https://example.com/logo.png"}
                }
              ]
            }
          }
        }
        </script>
        </body></html>
        """,
        encoding="utf-8",
    )
    ctx = _ctx(tmp_path)
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, "202606")

    output = ProductHuntFetchStage().execute(ctx, machine, html_file=str(html_file), limit=10)

    assert output["total"] == 1
    assert output["db_path"] == str(tmp_path / "data" / "producthunt.db")
    assert machine.job.status == Stage.IDLE.value
    store = ProductStore(ctx.db_path)
    products = store.list_products(2026, 6)
    assert len(products) == 1
    assert products[0].name == "Kilo Code"
    assert products[0].rank == 1
    assert products[0].categories == ["Developer Tools"]


def test_producthunt_fetch_stage_uses_period_for_year_and_month(tmp_path) -> None:
    ctx = _ctx(tmp_path)
    machine, _ = JobStateMachine.load_or_create(ctx.job_dir, "202607")
    html_file = tmp_path / "leaderboard.html"
    html_file.write_text(
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps({"products": [{"name": "July Product", "slug": "july-product"}]})
        + "</script>",
        encoding="utf-8",
    )

    ProductHuntFetchStage().execute(ctx, machine, html_file=str(html_file), limit=10)

    products = ProductStore(ctx.db_path).list_products(2026, 7)
    assert [product.name for product in products] == ["July Product"]


def test_producthunt_release_runs_fetch_render_cover_publish_dry_run(tmp_path) -> None:
    html_file = tmp_path / "leaderboard.html"
    html_file.write_text(
        '<script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(
            {
                "products": [
                    {
                        "rank": 1,
                        "name": "Dry Run Product",
                        "slug": "dry-run-product",
                        "tagline": "A product for dry-run verification",
                        "votesCount": 42,
                        "commentsCount": 3,
                    }
                ]
            }
        )
        + "</script>",
        encoding="utf-8",
    )
    source = get_source("producthunt")
    ctx = PublisherContext.create(
        tmp_path,
        source="producthunt",
        period="202606",
        db_filename="producthunt.db",
    )

    result = run_release(
        ctx,
        source,
        stages=source.stage_order,
        dry_run=True,
        stage_kwargs={GenericStage.FETCHING: {"html_file": str(html_file), "limit": 10}},
    )

    assert result["completed_stages"] == ["FETCHING", "RENDERING", "COVERING", "PUBLISHING"]
    markdown = tmp_path / "output" / "markdown" / "producthunt_monthly_202606_wechat.md"
    cover = tmp_path / "output" / "images" / "202606" / "producthunt_cover_202606.png"
    assert markdown.exists()
    assert "Dry Run Product" in markdown.read_text(encoding="utf-8")
    assert cover.exists()
