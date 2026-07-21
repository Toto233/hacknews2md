from pathlib import Path
import json
import sys
import textwrap
from unittest.mock import patch

from PIL import Image

from hn2md.constants import Stage
from hn2md.context import RuntimeContext
from hn2md.stages.cover import CoverStage


def _machine(md: Path):
    return type("M", (), {"job": type("J", (), {"stages": {Stage.RENDERING.value: {"output_summary": {"markdown_file": str(md)}}}})()})()


def test_cover_ai_calls_reusable_api(tmp_path) -> None:
    md = tmp_path / "a.md"
    ctx = object()
    with patch("hn2md.stages.cover.load_project_function", return_value=lambda *_, **__: "ai.png") as load:
        result = CoverStage().execute(ctx, _machine(md), mode="ai", target_word="短标题")
    load.assert_called_once_with(ctx, "scripts.generate_wechat_cover_ai", "generate_cover_ai")
    assert result["cover_image"] == "ai.png"


def test_cover_pillow_calls_reusable_api(tmp_path) -> None:
    md = tmp_path / "a.md"
    ctx = object()
    with patch("hn2md.stages.cover.load_project_function", return_value=lambda *_: "pillow.png") as load:
        result = CoverStage().execute(ctx, _machine(md), markdown_file=str(md), mode="pillow")
    load.assert_called_once_with(ctx, "scripts.generate_wechat_cover", "generate_cover")
    assert result["cover_image"] == "pillow.png"


def test_cover_external_registers_existing_image(tmp_path) -> None:
    md = tmp_path / "a.md"
    cover = tmp_path / "cover.png"
    Image.new("RGB", (2100, 900), "white").save(cover)

    result = CoverStage().execute(
        object(),
        _machine(md),
        markdown_file=str(md),
        mode="external",
        cover_image=str(cover),
        target_word="幽灵锁漏洞",
    )

    assert result["cover_image"] == str(cover)
    assert result["mode"] == "external"
    assert result["target_word"] == "幽灵锁漏洞"
    assert result["display_title"] == "幽灵锁漏洞"
    assert result["share_preview_crop"] == "center_1x1"
    assert result["cover_dimensions"] == {"width": 2100, "height": 900}
    preview = Path(result["share_preview_image"])
    assert preview.exists()
    assert Image.open(preview).size == (900, 900)


def test_cover_external_requires_existing_image(tmp_path) -> None:
    md = tmp_path / "a.md"

    try:
        CoverStage().execute(
            object(),
            _machine(md),
            markdown_file=str(md),
            mode="external",
            cover_image=str(tmp_path / "missing.png"),
        )
    except RuntimeError as exc:
        assert "External cover image not found" in str(exc)
    else:
        raise AssertionError("expected RuntimeError")


def test_cover_uses_first_ordered_story_when_target_is_omitted(tmp_path) -> None:
    md = tmp_path / "a.md"
    cover = tmp_path / "cover.png"
    plan = tmp_path / "plan.json"
    cover.write_bytes(b"png")
    plan.write_text(
        json.dumps(
            {
                "ordered_ids": [2, 1],
                "items": [
                    {"id": 1, "title_chs": "Second story"},
                    {"id": 2, "title_chs": "Lead story"},
                ],
            }
        ),
        encoding="utf-8",
    )
    machine = type(
        "M",
        (),
        {
            "job": type(
                "J",
                (),
                {
                    "stages": {
                        Stage.RENDERING.value: {
                            "output_summary": {"markdown_file": str(md), "plan_file": str(plan)}
                        }
                    }
                },
            )()
        },
    )()

    result = CoverStage().execute(object(), machine, mode="external", cover_image=str(cover))

    assert result["target_word"] == "Lead story"
    assert result["display_title"] == "Lead story"
    assert result["lead_story_id"] == 2
    assert result["lead_story_title"] == "Lead story"


def test_cover_loads_project_script_when_project_root_not_on_sys_path(tmp_path, monkeypatch) -> None:
    project = tmp_path / "project"
    script_dir = project / "scripts"
    script_dir.mkdir(parents=True)
    (script_dir / "generate_wechat_cover.py").write_text(
        textwrap.dedent(
            """
            def generate_cover(markdown_file):
                return "loaded-from-project-script.png"
            """
        ),
        encoding="utf-8",
    )
    md = tmp_path / "a.md"
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

    repo_root = Path(__file__).resolve().parents[2]
    monkeypatch.setattr(
        sys,
        "path",
        [p for p in sys.path if Path(p or ".").resolve() not in {repo_root, project}],
    )
    sys.modules.pop("scripts", None)
    sys.modules.pop("scripts.generate_wechat_cover", None)

    result = CoverStage().execute(ctx, _machine(md), markdown_file=str(md), mode="pillow")

    assert result["cover_image"] == "loaded-from-project-script.png"
