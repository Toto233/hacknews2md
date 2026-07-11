from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from scripts import generate_wechat_cover_ai


def test_run_image_generator_accepts_non_empty_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw_path = tmp_path / "raw.png"

    def fake_run(command: list[str], **kwargs: object) -> SimpleNamespace:
        Image.new("RGB", (1, 1)).save(raw_path, "PNG")
        return SimpleNamespace(returncode=0, stdout="generated")

    monkeypatch.setattr(generate_wechat_cover_ai.subprocess, "run", fake_run)

    generate_wechat_cover_ai.run_image_generator(
        ["node", "wrapper.mjs"], tmp_path, raw_path
    )


def test_run_image_generator_rejects_missing_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw_path = tmp_path / "raw.png"
    monkeypatch.setattr(
        generate_wechat_cover_ai.subprocess,
        "run",
        lambda command, **kwargs: SimpleNamespace(returncode=0, stdout="generated"),
    )

    with pytest.raises(RuntimeError, match="no image written"):
        generate_wechat_cover_ai.run_image_generator(
            ["node", "wrapper.mjs"], tmp_path, raw_path
        )


def test_run_image_generator_rejects_stale_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw_path = tmp_path / "raw.png"
    Image.new("RGB", (1, 1)).save(raw_path, "PNG")
    monkeypatch.setattr(
        generate_wechat_cover_ai.subprocess,
        "run",
        lambda command, **kwargs: SimpleNamespace(returncode=0, stdout="generated"),
    )

    with pytest.raises(RuntimeError, match="no image written"):
        generate_wechat_cover_ai.run_image_generator(
            ["node", "wrapper.mjs"], tmp_path, raw_path
        )


def test_extract_context_title_uses_first_news_heading(tmp_path: Path) -> None:
    markdown = tmp_path / "hacknews_summary_20260711_1200.md"
    markdown.write_text(
        """---
title: "日报标题 | Hacker News 摘要"
pubDatetime: 2026-07-11 12:00:00
---

## 1. 维修权重大胜利：约翰迪尔将开放农机自主维修权限 (John Deere owners get right to repair)

正文
""",
        encoding="utf-8",
    )

    assert (
        generate_wechat_cover_ai.extract_context_title(markdown, None)
        == "维修权重大胜利：约翰迪尔将开放农机自主维修权限 (John Deere owners get right to repair)"
    )


def test_generate_cover_ai_includes_hidden_context_and_absolute_output(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    markdown = tmp_path / "hacknews_summary_20260711_1200.md"
    markdown.write_text(
        """---
title: "日报标题 | Hacker News 摘要"
pubDatetime: 2026-07-11 12:00:00
---

## 1. 维修权重大胜利：约翰迪尔将开放农机自主维修权限 (John Deere owners get right to repair)

正文
""",
        encoding="utf-8",
    )
    wrapper = tmp_path / "skill" / "scripts" / "gpt_image_2_skill.cjs"
    wrapper.parent.mkdir(parents=True)
    wrapper.write_text("// noop", encoding="utf-8")
    output = tmp_path / "cover.png"
    captured: dict[str, object] = {}

    monkeypatch.setattr(generate_wechat_cover_ai, "resolve_image_wrapper", lambda settings: wrapper)

    def fake_run_image_generator(command: list[str], cwd: Path, raw_path: Path) -> None:
        captured["command"] = command
        captured["cwd"] = cwd
        captured["raw_path"] = raw_path
        Image.new("RGB", (1536, 1024)).save(raw_path, "PNG")

    monkeypatch.setattr(
        generate_wechat_cover_ai,
        "run_image_generator",
        fake_run_image_generator,
    )

    result = generate_wechat_cover_ai.generate_cover_ai(
        str(markdown),
        str(output),
        target_word="维修权胜利",
        context_title="维修权重大胜利：约翰迪尔将开放农机自主维修权限",
    )

    command = captured["command"]
    assert isinstance(command, list)
    assert "维修权胜利" in command[command.index("--instructions") + 1]
    assert "约翰迪尔将开放农机自主维修权限" in command[command.index("--instructions") + 1]
    assert "完整语境仅用于画面隐喻" in command[command.index("--prompt") + 1]
    assert Path(command[command.index("--out") + 1]).is_absolute()
    assert Path(result).is_absolute()
    assert output.exists()
