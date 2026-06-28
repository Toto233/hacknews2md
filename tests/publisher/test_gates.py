from pathlib import Path

from publisher.gates import check_local_image_limits, check_markdown_artifact


def test_check_markdown_artifact_accepts_existing_nonempty_file(tmp_path: Path) -> None:
    path = tmp_path / "article.md"
    path.write_text("---\ntitle: ok\n---\n\nbody\n", encoding="utf-8")

    result = check_markdown_artifact(path)

    assert result.ok is True
    assert result.warnings == []


def test_check_markdown_artifact_reports_missing_file(tmp_path: Path) -> None:
    result = check_markdown_artifact(tmp_path / "missing.md")

    assert result.ok is False
    assert result.warnings == [{"reason": "markdown_missing", "path": str(tmp_path / "missing.md")}]


def test_check_local_image_limits_reports_oversize(tmp_path: Path) -> None:
    image = tmp_path / "big.png"
    image.write_bytes(b"x" * 11)

    result = check_local_image_limits([image], limit_bytes=10)

    assert result.ok is False
    assert result.warnings == [
        {
            "reason": "image_oversize",
            "path": str(image),
            "size_bytes": 11,
            "limit_bytes": 10,
        }
    ]
