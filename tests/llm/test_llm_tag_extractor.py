"""Tests for src/llm/llm_tag_extractor.py."""

from unittest.mock import patch

import pytest


class TestParseTagsFromText:
    """Tests for parse_tags_from_text pure function."""

    def test_dash_format(self):
        from src.llm.llm_tag_extractor import parse_tags_from_text
        text = "- Tag1\n- Tag2\n- Tag3"
        tags = parse_tags_from_text(text)
        assert tags == ["Tag1", "Tag2", "Tag3"]

    def test_numbered_format(self):
        from src.llm.llm_tag_extractor import parse_tags_from_text
        text = "1. Tag1\n2. Tag2\n3. Tag3"
        tags = parse_tags_from_text(text)
        assert tags == ["Tag1", "Tag2", "Tag3"]

    def test_comma_separated(self):
        from src.llm.llm_tag_extractor import parse_tags_from_text
        text = "Tag1, Tag2, Tag3"
        tags = parse_tags_from_text(text)
        assert tags == ["Tag1", "Tag2", "Tag3"]

    def test_chinese_comma(self):
        from src.llm.llm_tag_extractor import parse_tags_from_text
        text = "Tag1，Tag2，Tag3"
        tags = parse_tags_from_text(text)
        assert tags == ["Tag1", "Tag2", "Tag3"]

    def test_dedup(self):
        from src.llm.llm_tag_extractor import parse_tags_from_text
        text = "- Tag1\n- Tag2\n- Tag1"
        tags = parse_tags_from_text(text)
        assert tags == ["Tag1", "Tag2"]

    def test_max_four(self):
        from src.llm.llm_tag_extractor import parse_tags_from_text
        text = "- T1\n- T2\n- T3\n- T4\n- T5"
        tags = parse_tags_from_text(text)
        assert len(tags) == 4

    def test_empty(self):
        from src.llm.llm_tag_extractor import parse_tags_from_text
        assert parse_tags_from_text("") == []

    def test_mixed_format(self):
        from src.llm.llm_tag_extractor import parse_tags_from_text
        text = "- Tag1\n2. Tag2"
        tags = parse_tags_from_text(text)
        assert len(tags) == 2


class TestExtractTagsWithLlm:
    """Tests for extract_tags_with_llm function."""

    @patch("src.llm.llm_tag_extractor.call_llm")
    def test_success(self, mock_llm):
        from src.llm.llm_tag_extractor import extract_tags_with_llm
        mock_llm.return_value = "- AI\n- Security\n- Open_Source"
        with patch("src.llm.llm_tag_extractor.load_llm_config") as mock_config:
            mock_config.return_value = {"default": "gemini", "gemini": {}, "grok": {}}
            tags = extract_tags_with_llm([("中文标题", "English Title")])
            assert len(tags) == 3

    @patch("src.llm.llm_tag_extractor.call_llm")
    def test_fallback(self, mock_llm):
        from src.llm.llm_tag_extractor import extract_tags_with_llm
        # First call fails, second succeeds
        mock_llm.side_effect = [Exception("fail"), "- Tag1\n- Tag2"]
        with patch("src.llm.llm_tag_extractor.load_llm_config") as mock_config:
            mock_config.return_value = {"default": "gemini", "gemini": {}, "grok": {}}
            tags = extract_tags_with_llm([("Title", "Title")])
            assert len(tags) == 2

    @patch("src.llm.llm_tag_extractor.call_llm")
    def test_all_fail(self, mock_llm):
        from src.llm.llm_tag_extractor import extract_tags_with_llm
        mock_llm.side_effect = Exception("fail")
        with patch("src.llm.llm_tag_extractor.load_llm_config") as mock_config:
            mock_config.return_value = {"default": "gemini", "gemini": {}, "grok": {}}
            tags = extract_tags_with_llm([("Title", "Title")])
            assert tags == []
