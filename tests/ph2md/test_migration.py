import json
from pathlib import Path

import pytest

from ph2md.config import AppPaths
from ph2md.db import ProductStore
from ph2md.editorial import write_json
from ph2md.migration import migrate_legacy_workspace
from tests.ph2md.test_insights import _products, _valid_plan


def test_migration_preserves_source_and_known_id(tmp_path):
    source = tmp_path / "legacy"
    store = ProductStore(source / "data" / "producthunt.db")
    store.init_schema()
    store.replace_products_for_month(2026, 8, _products())
    old_markdown = source / "output" / "markdown" / "producthunt_monthly_202608_wechat.md"
    old_cover = source / "output" / "images" / "202608" / "cover.png"
    old_receipt = source / "output" / "receipts" / "publish_202608.json"
    old_markdown.parent.mkdir(parents=True)
    old_cover.parent.mkdir(parents=True)
    old_cover.write_bytes(b"test-image")
    old_markdown.write_text(f"![cover]({old_cover.as_posix()})\n![relative](output/images/202608/cover.png)", encoding="utf-8")
    original = old_markdown.read_bytes()
    write_json(old_receipt, {"media_id": "legacy-id", "status": "published", "markdown_file": str(old_markdown), "cover_image": str(old_cover)})
    write_json(source / "output" / "codex" / "producthunt_plan_202608.json", _valid_plan())
    store.record_wechat_draft(2026, 8, "legacy-id", str(old_markdown), str(old_cover), str(old_receipt))
    paths = AppPaths(tmp_path / "new")
    report = migrate_legacy_workspace(source, paths)
    assert Path(report["database_backup"]).exists()
    assert old_markdown.read_bytes() == original
    assert ProductStore(source / "data" / "producthunt.db").get_monthly_run(2026, 8)["wechat_media_id"] == "legacy-id"
    run = ProductStore(paths.db_path).get_monthly_run(2026, 8)
    assert run["wechat_media_id"] == "legacy-id"
    assert Path(run["markdown_file"]) == paths.markdown_path(2026, 8)
    assert paths.output_dir.as_posix() in paths.markdown_path(2026, 8).read_text(encoding="utf-8")
    assert "(output/images/" not in paths.markdown_path(2026, 8).read_text(encoding="utf-8")
    assert json.loads((paths.receipts_dir / "publish_202608.json").read_text(encoding="utf-8"))["media_id"] == "legacy-id"
    with pytest.raises(ValueError, match="overwrite"):
        migrate_legacy_workspace(source, paths)


def test_migration_rejects_incompatible_integrated_database(tmp_path):
    import sqlite3
    source = tmp_path / "legacy"
    (source / "data").mkdir(parents=True)
    with sqlite3.connect(source / "data" / "producthunt.db") as connection:
        connection.execute("CREATE TABLE products(id INTEGER, period TEXT)")
    paths = AppPaths(tmp_path / "new")
    with pytest.raises(ValueError, match="not the editorial"):
        migrate_legacy_workspace(source, paths)
    assert not paths.db_path.exists()
