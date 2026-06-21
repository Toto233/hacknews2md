"""Tests for src/integrations/markdown_to_html_converter.py."""

import pytest


class TestExtractYamlHeader:
    """Tests for _extract_yaml_header pure function."""

    def test_with_title(self):
        from src.integrations.markdown_to_html_converter import WeChatArticleConverter
        converter = WeChatArticleConverter()
        md = "---\ntitle: \"Test Title\"\ndate: 2026-06-20\n---\n\nContent here"
        result = converter._extract_yaml_header(md)
        assert result.get("title") == "Test Title"

    def test_no_yaml(self):
        from src.integrations.markdown_to_html_converter import WeChatArticleConverter
        converter = WeChatArticleConverter()
        md = "No YAML header here"
        result = converter._extract_yaml_header(md)
        assert isinstance(result, dict)


class TestProcessHeading:
    """Tests for _process_heading pure function."""

    def test_numbered_heading(self):
        from src.integrations.markdown_to_html_converter import WeChatArticleConverter
        converter = WeChatArticleConverter()
        result = converter._process_heading("## 1. Test Title")
        assert "Test Title" in result

    def test_plain_heading(self):
        from src.integrations.markdown_to_html_converter import WeChatArticleConverter
        converter = WeChatArticleConverter()
        result = converter._process_heading("## Simple Title")
        assert "Simple Title" in result


class TestProcessImage:
    """Tests for _process_image pure function."""

    def test_valid_image(self):
        from src.integrations.markdown_to_html_converter import WeChatArticleConverter
        converter = WeChatArticleConverter()
        result = converter._process_image("![alt text](https://example.com/img.png)")
        assert "img" in result.lower() or "image" in result.lower()


class TestSanitizeFilename:
    """Tests for _sanitize_filename module-level function."""

    def test_illegal_chars(self):
        from src.integrations.markdown_to_html_converter import _sanitize_filename
        result = _sanitize_filename('file<>name')
        assert "<" not in result
        assert ">" not in result

    def test_long_filename(self):
        from src.integrations.markdown_to_html_converter import _sanitize_filename
        result = _sanitize_filename("a" * 300)
        assert len(result) <= 200

    def test_empty_after_sanitize(self):
        from src.integrations.markdown_to_html_converter import _sanitize_filename
        result = _sanitize_filename("///???")
        assert len(result) > 0  # Should return default name


class TestConvertMarkdownToHtml:
    """Tests for convert_markdown_to_html convenience wrapper."""

    def test_returns_html(self):
        from src.integrations.markdown_to_html_converter import convert_markdown_to_html
        md = "---\ntitle: Test\n---\n\n## Hello\n\nParagraph text"
        result = convert_markdown_to_html(md)
        assert "<!DOCTYPE" in result or "<html" in result.lower()

    def test_chinese_content(self):
        from src.integrations.markdown_to_html_converter import convert_markdown_to_html
        md = "---\ntitle: 测试\n---\n\n## 你好\n\n这是一段中文文本"
        result = convert_markdown_to_html(md)
        assert "你好" in result
        assert "中文" in result


class TestConvert:
    """Tests for WeChatArticleConverter.convert full pipeline."""

    def test_full_article(self):
        from src.integrations.markdown_to_html_converter import WeChatArticleConverter
        converter = WeChatArticleConverter()
        md = """---
title: "Test Article"
date: 2026-06-20
---

## 1. First Section

This is a paragraph with **bold** and *italic* text.

## 2. Second Section

Another paragraph with `inline code`.

---

Final section.
"""
        result = converter.convert(md)
        assert len(result) > 0
        assert "Test Article" in result or "First Section" in result
