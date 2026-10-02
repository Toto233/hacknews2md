from pathlib import Path
import importlib
import sqlite3
import sys
import textwrap
from subprocess import CompletedProcess
from unittest.mock import call, patch

import pytest
from PIL import Image

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.stages.base import NonRetryableStageError
from hn2md.stages.publish import PublishStage
from src.utils.db_utils import init_database


def test_publish_calls_reusable_api_with_explicit_paths(tmp_path) -> None:
    md = tmp_path / "article.md"
    md.write_text("# safe", encoding="utf-8")
    cover = tmp_path / "cover.png"
    machine = type("M", (), {"job": type("J", (), {"stages": {}})()})()
    ctx = object()
    def _load(_ctx, _module, name):
        if name == "preflight_wechat_access_token":
            return lambda: "token-ok"
        return lambda *_, **__: "media-1"

    with (
        patch("src.utils.db_utils.get_illegal_keywords", return_value=[]),
        patch("hn2md.stages.publish.load_project_function", side_effect=_load) as load,
    ):
        result = PublishStage().execute(
            ctx, machine, markdown_file=str(md), cover_image=str(cover)
        )
    assert load.call_args_list == [
        call(ctx, "scripts.publish_wechat", "preflight_wechat_access_token"),
        call(ctx, "scripts.publish_wechat", "publish_to_wechat"),
    ]
    assert result["wechat_media_id"] == "media-1"
    assert result["cover_image"] == str(cover)
    assert result["skipped_images"] == []


def test_publish_preflight_whitelist_error_fails_before_upload(tmp_path) -> None:
    md = tmp_path / "article.md"
    md.write_text("# safe", encoding="utf-8")
    machine = type("M", (), {"job": type("J", (), {"stages": {}})()})()
    ctx = object()
    publish = lambda *_, **__: "media-should-not-upload"

    def _load(_ctx, _module, name):
        if name == "preflight_wechat_access_token":
            return lambda: (_ for _ in ()).throw(RuntimeError("WeChat API error 40164: invalid ip 188.253.120.170"))
        return publish

    with (
        patch("src.utils.db_utils.get_illegal_keywords", return_value=[]),
        patch("hn2md.stages.publish.load_project_function", side_effect=_load),
        pytest.raises(NonRetryableStageError, match="188.253.120.170"),
    ):
        PublishStage().execute(ctx, machine, markdown_file=str(md))


def test_publish_blocks_when_a_story_has_no_screenshot(tmp_path) -> None:
    db_path = tmp_path / "data" / "hacknews.db"
    init_database(str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO news (id, title, news_url, created_at) VALUES (1, 'Story', 'https://example.com/story', datetime('now', 'localtime'))"
        )
    md = tmp_path / "article.md"
    md.write_text("# safe", encoding="utf-8")
    ctx = RuntimeContext(
        project_root=tmp_path,
        db_path=db_path,
        output_dir=tmp_path / "output",
        job_dir=tmp_path / "output" / "jobs",
        markdown_dir=tmp_path / "output" / "markdown",
        images_dir=tmp_path / "output" / "images",
        codex_dir=tmp_path / "output" / "codex",
        config_path=tmp_path / "config" / "config.json",
    )
    machine = type("M", (), {"job": type("J", (), {"stages": {}})()})()

    with pytest.raises(NonRetryableStageError, match="Mandatory screenshot fallback.*https://example.com/story"):
        PublishStage().execute(ctx, machine, markdown_file=str(md), dry_run=True)


def test_publish_accepts_only_exact_user_approved_screenshot_waiver(tmp_path) -> None:
    db_path = tmp_path / "data" / "hacknews.db"
    init_database(str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO news (id, title, news_url, created_at) "
            "VALUES (1, 'Story', 'https://example.com/story', '2000-01-02 10:00:00')"
        )
    ctx = RuntimeContext(
        project_root=tmp_path,
        db_path=db_path,
        output_dir=tmp_path / "output",
        job_dir=tmp_path / "output" / "jobs",
        markdown_dir=tmp_path / "output" / "markdown",
        images_dir=tmp_path / "output" / "images",
        codex_dir=tmp_path / "output" / "codex",
        config_path=tmp_path / "config" / "config.json",
    )
    md = tmp_path / "article.md"
    md.write_text("# safe", encoding="utf-8")
    waiver = {
        "period": "20000102",
        "run_id": "run-1",
        "news_id": 1,
        "news_url": "https://example.com/story",
        "reason": "User waived unreachable source screenshot",
        "approved_by": "user",
    }
    job = type("J", (), {
        "date": "20000102",
        "run_id": "run-1",
        "stages": {},
        "screenshot_waivers": [waiver],
    })()
    machine = type("M", (), {"job": job})()

    with patch("src.utils.db_utils.get_illegal_keywords", return_value=[]):
        result = PublishStage().execute(ctx, machine, markdown_file=str(md), dry_run=True)
    assert result["screenshot_waivers_applied"] == [waiver]

    job.screenshot_waivers = [{**waiver, "news_url": "https://example.com/other"}]
    with pytest.raises(NonRetryableStageError, match="https://example.com/story"):
        PublishStage().execute(ctx, machine, markdown_file=str(md), dry_run=True)

    job.screenshot_waivers = [{**waiver, "run_id": "another-run"}]
    with pytest.raises(NonRetryableStageError, match="https://example.com/story"):
        PublishStage().execute(ctx, machine, markdown_file=str(md), dry_run=True)


def test_publish_screenshot_gate_uses_run_date_after_midnight(tmp_path) -> None:
    db_path = tmp_path / "data" / "hacknews.db"
    init_database(str(db_path))
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "INSERT INTO news (id, title, news_url, created_at) VALUES (1, 'Old', 'https://example.com/old', '2000-01-02 10:00:00')"
        )
        conn.execute(
            "INSERT INTO news (id, title, news_url, screenshot, created_at) "
            "VALUES (2, 'Current', 'https://example.com/current', 'current.png', datetime('now', 'localtime'))"
        )
    ctx = RuntimeContext(
        project_root=tmp_path,
        db_path=db_path,
        output_dir=tmp_path / "output",
        job_dir=tmp_path / "output" / "jobs",
        markdown_dir=tmp_path / "output" / "markdown",
        images_dir=tmp_path / "output" / "images",
        codex_dir=tmp_path / "output" / "codex",
        config_path=tmp_path / "config" / "config.json",
    )
    md = tmp_path / "article.md"
    md.write_text("# safe", encoding="utf-8")
    machine = type("M", (), {"job": type("J", (), {"date": "20000102", "stages": {}})()})()

    with pytest.raises(NonRetryableStageError, match="https://example.com/old"):
        PublishStage().execute(ctx, machine, markdown_file=str(md), dry_run=True)

    with sqlite3.connect(db_path) as conn:
        conn.execute("UPDATE news SET screenshot='old.png' WHERE id=1")
        conn.execute("UPDATE news SET screenshot=NULL WHERE id=2")
    with patch("src.utils.db_utils.get_illegal_keywords", return_value=[]):
        result = PublishStage().execute(ctx, machine, markdown_file=str(md), dry_run=True)
    assert result["dry_run"] is True


def test_publish_fails_when_wechat_returns_no_media_id(tmp_path) -> None:
    md = tmp_path / "article.md"
    md.write_text("# safe", encoding="utf-8")
    machine = type("M", (), {"job": type("J", (), {"stages": {}})()})()

    with (
        patch("src.utils.db_utils.get_illegal_keywords", return_value=[]),
        patch("hn2md.stages.publish.load_project_function", return_value=lambda *_, **__: None),
        pytest.raises(RuntimeError, match="no media_id returned"),
    ):
        PublishStage().execute(object(), machine, markdown_file=str(md))


def test_publish_reports_oversize_local_images(tmp_path) -> None:
    image = tmp_path / "oversize.png"
    image.write_bytes(b"x" * (1024 * 1024 + 1))
    md = tmp_path / "article.md"
    md.write_text(f"# safe\n\n![large]({image})\n", encoding="utf-8")
    machine = type("M", (), {"job": type("J", (), {"stages": {}})()})()
    ctx = object()

    with (
        patch("src.utils.db_utils.get_illegal_keywords", return_value=[]),
        patch("hn2md.stages.publish.load_project_function", return_value=lambda *_, **__: "media-1"),
    ):
        result = PublishStage().execute(ctx, machine, markdown_file=str(md))

    assert result["wechat_media_id"] == "media-1"
    assert result["skipped_images"] == [
        {
            "path": str(image),
            "reason": "oversize",
            "limit_bytes": 1024 * 1024,
            "size_bytes": 1024 * 1024 + 1,
        }
    ]


def test_publish_compresses_valid_oversize_images_before_wechat_upload(tmp_path) -> None:
    image = tmp_path / "oversize.png"
    Image.effect_noise((1600, 1600), 100).convert("RGB").save(image)
    assert image.stat().st_size > 1024 * 1024
    md = tmp_path / "article.md"
    md.write_text(f"# safe\n\n![large]({image})\n", encoding="utf-8")
    machine = type("M", (), {"job": type("J", (), {"stages": {}})()})()

    with (
        patch("src.utils.db_utils.get_illegal_keywords", return_value=[]),
        patch("hn2md.stages.publish.load_project_function", return_value=lambda *_, **__: "media-1"),
    ):
        result = PublishStage().execute(object(), machine, markdown_file=str(md))

    assert result["wechat_media_id"] == "media-1"
    assert result["skipped_images"] == []
    assert result["compressed_images"]
    compressed_path = Path(result["compressed_images"][0]["compressed_path"])
    assert compressed_path.exists()
    assert compressed_path.stat().st_size <= 1024 * 1024
    assert str(compressed_path) in md.read_text(encoding="utf-8")


def test_publish_reports_unsupported_local_image_formats(tmp_path) -> None:
    image = tmp_path / "animation.gif"
    image.write_bytes(b"gif")
    md = tmp_path / "article.md"
    md.write_text(f"# safe\n\n![gif]({image})\n", encoding="utf-8")
    machine = type("M", (), {"job": type("J", (), {"stages": {}})()})()

    with (
        patch("src.utils.db_utils.get_illegal_keywords", return_value=[]),
        patch("hn2md.stages.publish.load_project_function", return_value=lambda *_, **__: "media-1"),
    ):
        result = PublishStage().execute(object(), machine, markdown_file=str(md))

    assert result["skipped_images"] == [
        {
            "path": str(image),
            "reason": "unsupported_format",
            "supported_formats": ["jpg", "jpeg", "png", "webp"],
            "suffix": ".gif",
        }
    ]


def test_publish_converts_valid_gif_images_before_wechat_upload(tmp_path) -> None:
    image = tmp_path / "animation.gif"
    Image.new("RGB", (32, 32), "red").save(image, format="GIF")
    md = tmp_path / "article.md"
    md.write_text(f"# safe\n\n![gif]({image})\n", encoding="utf-8")
    machine = type("M", (), {"job": type("J", (), {"stages": {}})()})()

    with (
        patch("src.utils.db_utils.get_illegal_keywords", return_value=[]),
        patch("hn2md.stages.publish.load_project_function", return_value=lambda *_, **__: "media-1"),
    ):
        result = PublishStage().execute(object(), machine, markdown_file=str(md))

    assert result["wechat_media_id"] == "media-1"
    assert result["skipped_images"] == []
    assert result["converted_images"] == [
        {
            "original_path": str(image),
            "converted_path": str(image.with_name("animation_wechat.png")),
            "original_suffix": ".gif",
            "converted_suffix": ".png",
        }
    ]
    assert image.with_name("animation_wechat.png").exists()
    assert str(image.with_name("animation_wechat.png")) in md.read_text(encoding="utf-8")


def test_publish_syncs_astro_and_records_pushed_commit(tmp_path) -> None:
    astro_repo = tmp_path / "astro"
    astro_file = astro_repo / "src" / "data" / "blog" / "article.md"
    astro_file.parent.mkdir(parents=True)
    astro_file.write_text("# Astro", encoding="utf-8")
    md = tmp_path / "article.md"
    md.write_text("# safe", encoding="utf-8")
    ctx = RuntimeContext(
        project_root=tmp_path,
        db_path=tmp_path / "data" / "hacknews.db",
        output_dir=tmp_path / "output",
        job_dir=tmp_path / "output" / "jobs",
        markdown_dir=tmp_path / "output" / "markdown",
        images_dir=tmp_path / "output" / "images",
        codex_dir=tmp_path / "output" / "codex",
        config_path=tmp_path / "config" / "config.json",
    )
    machine = type(
        "M",
        (),
        {"job": type("J", (), {"date": "20260627", "stages": {Stage.RENDERING.value: {"output_summary": {"astro_file": str(astro_file)}}}})()},
    )()
    settings = type("Settings", (), {"astro_enabled": True, "astro_repo": astro_repo})()
    commands: list[list[str]] = []

    def _git(command: list[str], **_kwargs) -> CompletedProcess[str]:
        commands.append(command)
        if command[-3:] == ["diff", "--cached", "--quiet"]:
            return CompletedProcess(command, 1, "", "")
        if command[-2:] == ["rev-parse", "HEAD"]:
            return CompletedProcess(command, 0, "abc123\n", "")
        return CompletedProcess(command, 0, "", "")

    with (
        patch("src.utils.db_utils.get_illegal_keywords", return_value=[]),
        patch("hn2md.stages.publish.load_deployment_settings", return_value=settings),
        patch("hn2md.stages.publish.subprocess.run", side_effect=_git),
    ):
        result = PublishStage().execute(ctx, machine, markdown_file=str(md), targets=("astro",))

    assert result["wechat_media_id"] is None
    assert result["requested_targets"] == ["astro"]
    assert result["completed_targets"] == ["astro"]
    assert result["astro"] == {
        "status": "pushed",
        "repo": str(astro_repo),
        "file": str(astro_file),
        "commit": "abc123",
    }
    assert commands[-2][-1] == "HEAD"
    assert commands[-1][-1] == "push"


def test_publish_keyword_gate_warns_with_full_sentence_without_blocking(tmp_path) -> None:
    md = tmp_path / "article.md"
    md.write_text("# title\n\nfirst line\nThis sentence has a blocked keyword here. Next sentence.\nlast line\n", encoding="utf-8")
    machine = type("M", (), {"job": type("J", (), {"stages": {}})()})()

    with patch("src.utils.db_utils.get_illegal_keywords", return_value=["blocked"]):
        result = PublishStage().execute(object(), machine, markdown_file=str(md), dry_run=True)

    assert result["keyword_warnings"] == [
        {
            "keyword": "blocked",
            "path": str(md),
            "line": 4,
            "sentence": "This sentence has a blocked keyword here.",
            "context": "This sentence has a blocked keyword here. Next sentence.",
        }
    ]


def test_keyword_review_groups_duplicate_image_alt_text_without_paths(tmp_path) -> None:
    from hn2md.stages.publish import _keyword_locations

    title = "“间谍水印”概念：隐藏的追踪信号"
    content = "\n".join(
        [
            f"## 8. {title} (Spymarks, not Watermarks)",
            *(f"![{title}](C:/images/Spymarks_{index}.png)" for index in range(4)),
            "作者把这种隐藏信号称为间谍水印。",
            "HN 读者争论间谍水印与隐写术的区别。",
        ]
    )

    warnings = _keyword_locations(content, ["间谍"], str(tmp_path / "article.md"))

    assert len(warnings) == 4
    image_warning = warnings[1]
    assert image_warning["sentence"] == title
    assert [location["line"] for location in image_warning["locations"]] == [2, 3, 4, 5]
    assert len(image_warning["legacy_sentences"]) == 4
    assert all(".png" not in warning["sentence"] for warning in warnings)


def test_keyword_review_keeps_identical_text_in_separate_stories(tmp_path) -> None:
    from hn2md.stages.publish import _keyword_locations

    content = "\n".join(
        [
            "## 1. 第一条",
            "![间谍水印](C:/images/first.png)",
            "![间谍水印](C:/images/first-2.png)",
            "## 2. 第二条",
            "![间谍水印](C:/images/second.png)",
        ]
    )

    warnings = _keyword_locations(content, ["间谍"], str(tmp_path / "article.md"))

    assert len(warnings) == 2
    assert [warning["line"] for warning in warnings] == [2, 5]
    assert [location["line"] for location in warnings[0]["locations"]] == [2, 3]


def test_publish_loads_project_script_when_project_root_not_on_sys_path(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    script_dir = project / "scripts"
    script_dir.mkdir(parents=True)
    (script_dir / "publish_wechat.py").write_text(
        textwrap.dedent(
            """
            def preflight_wechat_access_token():
                return "token-from-project-script"

            def publish_to_wechat(markdown_file, cover_image=None):
                return "media-from-project-script"
            """
        ),
        encoding="utf-8",
    )
    md = tmp_path / "article.md"
    md.write_text("# safe", encoding="utf-8")
    ctx = RuntimeContext(
        project_root=project,
        db_path=project / "data" / "hacknews.db",
        output_dir=project / "output",
        job_dir=project / "output" / "jobs",
        markdown_dir=project / "output" / "markdown",
        images_dir=project / "output" / "images",
        codex_dir=project / "output" / "codex",
        config_path=project / "config" / "config.json",
    )
    machine = type("M", (), {"job": type("J", (), {"stages": {}})()})()

    repo_root = Path(__file__).resolve().parents[2]
    original_path = list(sys.path)
    monkeypatch.setattr(
        sys,
        "path",
        [p for p in sys.path if Path(p or ".").resolve() not in {repo_root, project}],
    )
    original_scripts = sys.modules.get("scripts")
    original_publish_wechat = sys.modules.get("scripts.publish_wechat")
    sys.modules.pop("scripts", None)
    sys.modules.pop("scripts.publish_wechat", None)

    try:
        with patch("src.utils.db_utils.get_illegal_keywords", return_value=[]):
            result = PublishStage().execute(ctx, machine, markdown_file=str(md))
    finally:
        sys.path = original_path
        sys.modules.pop("scripts", None)
        sys.modules.pop("scripts.publish_wechat", None)
        if original_scripts is not None and original_publish_wechat is not None:
            sys.modules["scripts"] = original_scripts
        if original_publish_wechat is not None:
            sys.modules["scripts.publish_wechat"] = original_publish_wechat
        else:
            if str(repo_root) not in sys.path:
                sys.path.insert(0, str(repo_root))
            importlib.import_module("scripts.publish_wechat")

    assert result["wechat_media_id"] == "media-from-project-script"
