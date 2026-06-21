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
