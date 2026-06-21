"""Tests for src/llm/llm_evaluator.py."""

from unittest.mock import patch

import pytest


class TestEvaluateNewsAttraction:
    """Tests for evaluate_news_attraction function."""

    @patch("src.llm.llm_evaluator.call_llm")
    def test_empty_items(self, mock_llm):
        from src.llm.llm_evaluator import evaluate_news_attraction
        ratings, reason = evaluate_news_attraction([])
        assert ratings == []
        assert reason == ""
        mock_llm.assert_not_called()

    @patch("src.llm.llm_evaluator.call_llm")
    def test_success(self, mock_llm):
        from src.llm.llm_evaluator import evaluate_news_attraction
        mock_llm.return_value = '{"ratings": [{"id": 1, "score": 9}, {"id": 2, "score": 7}], "headline_reason": "test"}'
        items = [
            (1, "Title 1", "https://a.com", "", "Summary 1", "", None, None, None, None),
            (2, "Title 2", "https://b.com", "", "Summary 2", "", None, None, None, None),
        ]
        ratings, reason = evaluate_news_attraction(items)
        assert len(ratings) == 2

    @patch("src.llm.llm_evaluator.call_llm")
    def test_invalid_json(self, mock_llm):
        from src.llm.llm_evaluator import evaluate_news_attraction
        mock_llm.return_value = "not valid json"
        items = [(1, "Title", "https://a.com", "", "Summary", "", None, None, None, None)]
        ratings, reason = evaluate_news_attraction(items)
        assert ratings == []

    @patch("src.llm.llm_evaluator.call_llm")
    def test_strips_markdown_block(self, mock_llm):
        from src.llm.llm_evaluator import evaluate_news_attraction
        mock_llm.return_value = '```json\n{"ratings": [{"id": 1, "score": 8}], "headline_reason": "test"}\n```'
        items = [(1, "Title", "https://a.com", "", "Summary", "", None, None, None, None)]
        ratings, reason = evaluate_news_attraction(items)
        assert len(ratings) == 1

    @patch("src.llm.llm_evaluator.call_llm")
    def test_llm_failure(self, mock_llm):
        from src.llm.llm_evaluator import evaluate_news_attraction
        mock_llm.return_value = ""
        items = [(1, "Title", "https://a.com", "", "Summary", "", None, None, None, None)]
        ratings, reason = evaluate_news_attraction(items)
        assert ratings == []
