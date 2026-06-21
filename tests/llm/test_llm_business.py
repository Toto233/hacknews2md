"""Tests for src/llm/llm_business.py."""

from unittest.mock import patch, MagicMock

import pytest


class TestGenerateSummary:
    """Tests for generate_summary function."""

    @patch("src.llm.llm_business.call_llm")
    def test_empty_text(self, mock_llm):
        from src.llm.llm_business import generate_summary
        result = generate_summary("")
        assert result == ""
        mock_llm.assert_not_called()

    @patch("src.llm.llm_business.call_llm")
    def test_article_type(self, mock_llm):
        from src.llm.llm_business import generate_summary
        mock_llm.return_value = "This is a summary."
        result = generate_summary("a" * 500, prompt_type="article")
        assert result == "This is a summary."
        mock_llm.assert_called_once()

    @patch("src.llm.llm_business.call_llm")
    def test_discussion_type(self, mock_llm):
        from src.llm.llm_business import generate_summary
        mock_llm.return_value = "Discussion summary."
        result = generate_summary("a" * 500, prompt_type="discussion")
        assert result == "Discussion summary."

    @patch("src.llm.llm_business.call_llm")
    def test_null_returns_empty(self, mock_llm):
        from src.llm.llm_business import generate_summary
        mock_llm.return_value = "null"
        result = generate_summary("a" * 500)
        assert result == ""


class TestTranslateTitle:
    """Tests for translate_title function."""

    @patch("src.llm.llm_business.call_llm")
    def test_empty_title(self, mock_llm):
        from src.llm.llm_business import translate_title
        result = translate_title("", "summary")
        assert result == ""
        mock_llm.assert_not_called()

    @patch("src.llm.llm_business.call_llm")
    def test_success(self, mock_llm):
        from src.llm.llm_business import translate_title
        mock_llm.return_value = "翻译后的标题"
        result = translate_title("Original Title", "content summary")
        assert result == "翻译后的标题"

    @patch("src.llm.llm_business.call_llm")
    def test_null_response(self, mock_llm):
        from src.llm.llm_business import translate_title
        mock_llm.return_value = "null"
        result = translate_title("Title", "summary")
        assert result == ""


class TestGenerateSummaryFromImage:
    """Tests for generate_summary_from_image function."""

    @patch("src.llm.llm_business.call_llm")
    def test_empty_data(self, mock_llm):
        from src.llm.llm_business import generate_summary_from_image
        result = generate_summary_from_image("", "describe this", "grok")
        assert result == ""
        mock_llm.assert_not_called()
