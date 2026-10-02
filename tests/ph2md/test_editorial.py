import json
from pathlib import Path

import pytest
from click.testing import CliRunner

from ph2md.cli import main
from ph2md.config import AppPaths
from ph2md.db import ProductStore
from ph2md.editorial import render_editorial, run_editorial_publish, write_json
from ph2md.lock import monthly_lock
from publisher_shared.wechat import PublishError, PublishResult
from tests.ph2md.test_insights import _products, _valid_plan


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    from PIL import Image
    def logos(products, directory):
        directory.mkdir(parents=True, exist_ok=True)
        results = {}
        for product in products[:10]:
            path = directory / f"{product.rank}.png"
            Image.new("RGB", (128, 128), "white").save(path)
            results[product.rank] = path
        return results
    monkeypatch.setattr("ph2md.render.download_logos", logos)
    paths = AppPaths(tmp_path)
    store = ProductStore(paths.db_path)
    store.init_schema()
    store.replace_products_for_month(2026, 8, _products())
    write_json(paths.plan_path(2026, 8), _valid_plan())
    return paths


def test_status_reads_committed_snapshot_with_active_writer(workspace):
    from ph2md.lock import _file_lock
    store = ProductStore(workspace.db_path)
    store.upsert_monthly_run(2026, 8, "FETCHED")
    expected_count = store.count_products(2026, 8)
    with _file_lock(workspace.root / "data/producthunt/locks/source.lock"):
        with store.connect() as writer:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute("UPDATE monthly_runs SET status = ?", ("FETCHING",))
            result = CliRunner().invoke(main, ["--root", str(workspace.root), "status", "--year", "2026", "--month", "8"])
            assert result.exit_code == 0, result.output
            assert "Status: FETCHED" in result.output
            assert f"Products: {expected_count}" in result.output


def test_status_does_not_create_workspace(tmp_path):
    root = tmp_path / "new-workspace"
    result = CliRunner().invoke(main, ["--root", str(root), "status", "--year", "2026", "--month", "8"])
    assert result.exit_code == 0, result.output
    assert "Status: NOT_STARTED" in result.output
    assert not root.exists()


def test_receipt_atomic_replace_recovers_from_transient_windows_lock(tmp_path, monkeypatch):
    import os
    replace = os.replace
    attempts = []
    def temporarily_locked(source, destination):
        attempts.append(source)
        if len(attempts) < 3:
            raise PermissionError("file temporarily in use")
        replace(source, destination)
    monkeypatch.setattr("ph2md.editorial.os.replace", temporarily_locked)
    monkeypatch.setattr("ph2md.editorial.time.sleep", lambda seconds: None)
    path = tmp_path / "receipt.json"
    write_json(path, {"media_id": "retained-id"})
    assert json.loads(path.read_text(encoding="utf-8"))["media_id"] == "retained-id"
    assert len(attempts) == 3


def test_receipt_permanent_replace_failure_preserves_previous_file(tmp_path, monkeypatch):
    path = tmp_path / "receipt.json"
    write_json(path, {"status": "attempting"})
    def locked(*args):
        raise PermissionError("file remains in use")
    monkeypatch.setattr("ph2md.editorial.os.replace", locked)
    monkeypatch.setattr("ph2md.editorial.time.sleep", lambda seconds: None)
    with pytest.raises(PermissionError):
        write_json(path, {"media_id": "retained-id"})
    assert json.loads(path.read_text(encoding="utf-8"))["status"] == "attempting"
    assert json.loads(path.with_suffix(".json.tmp").read_text(encoding="utf-8"))["media_id"] == "retained-id"


def test_doctor_lock_conflict_is_a_clear_cli_error(workspace):
    from ph2md.lock import _file_lock
    with _file_lock(workspace.root / "data/producthunt/locks/source.lock"):
        result = CliRunner().invoke(main, ["--root", str(workspace.root), "doctor"])
    assert result.exit_code == 1
    assert "Error: Product Hunt already has an active writer" in result.output
    assert isinstance(result.exception, SystemExit)


def test_offline_render_preview_and_single_publish(workspace, monkeypatch):
    render_editorial(workspace, 2026, 8)
    calls = []
    monkeypatch.setattr("publisher_shared.wechat.preview_article", lambda *args, **kwargs: True)
    monkeypatch.setattr("publisher_shared.wechat.publish_article", lambda *args, **kwargs: calls.append(args) or PublishResult("known-id", True))
    assert run_editorial_publish(workspace, 2026, 8, preview=True) is None
    assert not (workspace.receipts_dir / "publish_202608.json").exists()
    assert run_editorial_publish(workspace, 2026, 8) == "known-id"
    assert run_editorial_publish(workspace, 2026, 8) == "known-id"
    assert len(calls) == 1
    assert ProductStore(workspace.db_path).get_monthly_run(2026, 8)["status"] == "PUBLISHED"


def test_render_gate_preserves_existing_article(workspace):
    markdown = render_editorial(workspace, 2026, 8, download_images=False)
    original = markdown.read_bytes()
    plan = _valid_plan()
    plan["items"][0]["observation"] = ""
    write_json(workspace.plan_path(2026, 8), plan)
    with pytest.raises(ValueError, match="failed audit"):
        render_editorial(workspace, 2026, 8, download_images=False)
    assert markdown.read_bytes() == original


def test_publish_refuses_stale_render(workspace, monkeypatch):
    markdown = render_editorial(workspace, 2026, 8, download_images=False)
    markdown.write_text(markdown.read_text(encoding="utf-8") + "changed", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after render"):
        run_editorial_publish(workspace, 2026, 8)
    assert not (workspace.receipts_dir / "publish_202608.json").exists()


@pytest.mark.parametrize("known_id", [None, "remote-id"])
def test_uncertain_upload_preserves_id_and_blocks_retry(workspace, monkeypatch, known_id):
    render_editorial(workspace, 2026, 8)
    calls = []
    def fail(*args, **kwargs):
        calls.append(1)
        raise PublishError("verification or network failed", media_id=known_id)
    monkeypatch.setattr("publisher_shared.wechat.publish_article", fail)
    with pytest.raises(PublishError):
        run_editorial_publish(workspace, 2026, 8)
    receipt = json.loads((workspace.receipts_dir / "publish_202608.json").read_text(encoding="utf-8"))
    assert receipt["status"] == "uncertain"
    assert receipt.get("media_id") == known_id
    with pytest.raises(RuntimeError, match="uncertain|unresolved"):
        run_editorial_publish(workspace, 2026, 8)
    assert len(calls) == 1
    if known_id:
        run = ProductStore(workspace.db_path).get_monthly_run(2026, 8)
        assert run["wechat_media_id"] == known_id
        assert run["status"] == "PUBLISH_UNVERIFIED"


def test_offline_render_does_not_satisfy_publish_image_gate(workspace):
    render_editorial(workspace, 2026, 8, download_images=False)
    with pytest.raises(ValueError, match="all Top 10 product images"):
        run_editorial_publish(workspace, 2026, 8, preview=True)


def test_month_writer_lock_rejects_second_owner(tmp_path):
    with monthly_lock(tmp_path, 2026, 8):
        with pytest.raises(RuntimeError, match="active writer"):
            with monthly_lock(tmp_path, 2026, 8):
                pytest.fail("lock allowed two owners")
    with monthly_lock(tmp_path, 2026, 8):
        pass


def test_cli_root_and_local_fetch_are_isolated(tmp_path):
    fixture = Path(__file__).parent / "fixtures" / "producthunt_monthly.html"
    runner = CliRunner()
    result = runner.invoke(main, ["--root", str(tmp_path), "fetch", "--year", "2026", "--month", "8", "--html-file", str(fixture)])
    assert result.exit_code == 0, result.output
    assert AppPaths(tmp_path).db_path.exists()
    result = runner.invoke(main, ["--root", str(tmp_path), "export-plan", "--year", "2026", "--month", "8"])
    assert result.exit_code != 0  # fixture contains only three products, so cannot author Top 10
    result = runner.invoke(main, ["--root", str(tmp_path), "status", "--year", "2026", "--month", "8"])
    assert result.exit_code == 0 and "Products: 3" in result.output
