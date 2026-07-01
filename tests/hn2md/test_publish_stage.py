from pathlib import Path
import sys
import textwrap
from unittest.mock import patch

import pytest
from PIL import Image

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.stages.publish import PublishStage


def test_publish_calls_reusable_api_with_explicit_paths(tmp_path) -> None:
    md = tmp_path / "article.md"
    md.write_text("# safe", encoding="utf-8")
    cover = tmp_path / "cover.png"
    machine = type("M", (), {"job": type("J", (), {"stages": {}})()})()
    ctx = object()
    with (
        patch("src.utils.db_utils.get_illegal_keywords", return_value=[]),
        patch("hn2md.stages.publish.load_project_function", return_value=lambda *_, **__: "media-1") as load,
    ):
        result = PublishStage().execute(
            ctx, machine, markdown_file=str(md), cover_image=str(cover)
        )
    load.assert_called_once_with(ctx, "scripts.publish_wechat", "publish_to_wechat")
    assert result["wechat_media_id"] == "media-1"
    assert result["skipped_images"] == []


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


def test_publish_loads_project_script_when_project_root_not_on_sys_path(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    script_dir = project / "scripts"
    script_dir.mkdir(parents=True)
    (script_dir / "publish_wechat.py").write_text(
        textwrap.dedent(
            """
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
    monkeypatch.setattr(
        sys,
        "path",
        [p for p in sys.path if Path(p or ".").resolve() not in {repo_root, project}],
    )
    sys.modules.pop("scripts", None)
    sys.modules.pop("scripts.publish_wechat", None)

    with patch("src.utils.db_utils.get_illegal_keywords", return_value=[]):
        result = PublishStage().execute(ctx, machine, markdown_file=str(md))

    assert result["wechat_media_id"] == "media-from-project-script"
