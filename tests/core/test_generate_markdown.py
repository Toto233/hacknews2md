"""Tests for src/core/generate_markdown.py."""

import os
import tempfile
from pathlib import Path

import pytest


class TestYamlQuote:
    """Tests for yaml_quote pure function."""

    def test_simple_string(self):
        from src.core.generate_markdown import yaml_quote
        result = yaml_quote("hello")
        assert result == '"hello"'

    def test_with_quotes(self):
        from src.core.generate_markdown import yaml_quote
        result = yaml_quote('say "hi"')
        assert "\\" in result

    def test_with_backslash(self):
        from src.core.generate_markdown import yaml_quote
        result = yaml_quote("a\\b")
        assert "\\" in result

    def test_with_newline(self):
        from src.core.generate_markdown import yaml_quote
        result = yaml_quote("a\nb")
        assert "\\n" in result

    def test_none(self):
        from src.core.generate_markdown import yaml_quote
        result = yaml_quote(None)
        assert isinstance(result, str)

    def test_integer(self):
        from src.core.generate_markdown import yaml_quote
        result = yaml_quote(42)
        assert "42" in result


class TestCopyImagesToAstro:
    """Tests for copy_images_to_astro with filesystem."""

    def test_copies_valid_path(self, tmp_path):
        from src.core.generate_markdown import copy_images_to_astro
        from datetime import datetime

        # Create source image under images/<date_dir>/ structure
        # (copy_images_to_astro expects this path layout)
        date_dir = datetime.now().strftime("%Y%m%d")
        src_img = tmp_path / "source" / "images" / date_dir / "img.png"
        src_img.parent.mkdir(parents=True)
        src_img.write_bytes(b"fake image data")

        dest_dir = tmp_path / "dest" / "images"
        result = copy_images_to_astro([str(src_img)], str(dest_dir))

        assert len(result) == 1
        assert str(src_img) in result

    def test_empty_list(self, tmp_path):
        from src.core.generate_markdown import copy_images_to_astro
        dest_dir = tmp_path / "dest"
        result = copy_images_to_astro([], str(dest_dir))
        assert result == {}

    def test_missing_file_skipped(self, tmp_path):
        from src.core.generate_markdown import copy_images_to_astro
        dest_dir = tmp_path / "dest"
        result = copy_images_to_astro(["/nonexistent/img.png"], str(dest_dir))
        assert len(result) == 0


class TestCleanupOldAstroImages:
    """Tests for cleanup_old_astro_images with filesystem."""

    def test_removes_old_dirs(self, tmp_path):
        from src.core.generate_markdown import cleanup_old_astro_images

        # Create old date directory
        old_dir = tmp_path / "20200101"
        old_dir.mkdir()
        (old_dir / "img.png").write_bytes(b"data")

        cleanup_old_astro_images(str(tmp_path), days=7)

        assert not old_dir.exists()

    def test_keeps_recent_dirs(self, tmp_path):
        from src.core.generate_markdown import cleanup_old_astro_images
        from datetime import datetime

        recent_dir = tmp_path / datetime.now().strftime("%Y%m%d")
        recent_dir.mkdir()
        (recent_dir / "img.png").write_bytes(b"data")

        cleanup_old_astro_images(str(tmp_path), days=7)

        assert recent_dir.exists()

    def test_skips_non_date_dirs(self, tmp_path):
        from src.core.generate_markdown import cleanup_old_astro_images

        non_date_dir = tmp_path / "not-a-date"
        non_date_dir.mkdir()

        cleanup_old_astro_images(str(tmp_path), days=7)

        assert non_date_dir.exists()

    def test_missing_dir_no_crash(self, tmp_path):
        from src.core.generate_markdown import cleanup_old_astro_images
        cleanup_old_astro_images(str(tmp_path / "nonexistent"), days=7)
