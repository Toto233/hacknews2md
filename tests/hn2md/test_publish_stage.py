from pathlib import Path
import sys
import textwrap
from unittest.mock import patch

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
