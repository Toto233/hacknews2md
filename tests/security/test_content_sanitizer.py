# -*- coding: utf-8 -*-
"""Tests for content sanitization utilities."""

import pytest
from src.security.content_sanitizer import (
    sanitize_for_yaml,
    sanitize_for_html,
    redact_secrets,
    contains_hallucination_markers,
    validate_summary_length,
)


class TestSanitizeForYaml:
    """Tests for YAML sanitization."""

    def test_normal_text_unchanged(self):
        """Normal text should pass through."""
        assert sanitize_for_yaml("Hello World") == "Hello World"

    def test_none_returns_empty(self):
        """None should return empty string."""
        assert sanitize_for_yaml(None) == ""

    def test_yaml_boundary_neutralized(self):
        """YAML frontmatter boundaries (---) should be neutralized."""
        result = sanitize_for_yaml("---\nmalicious: true\n---")
        assert "---" not in result or "— —" in result

    def test_control_characters_removed(self):
        """Control characters should be removed."""
        result = sanitize_for_yaml("Hello\x00World\x01\x02")
        assert "\x00" not in result
        assert "\x01" not in result
        assert "Hello" in result
        assert "World" in result

    def test_yaml_directive_neutralized(self):
        """YAML directives should be neutralized."""
        result = sanitize_for_yaml("%YAML 1.2\n%TAG ! tag:example.com,2000:")
        assert not result.startswith("%YAML")
        assert not result.startswith("%TAG")

    def test_integer_input(self):
        """Integer inputs should be converted to string."""
        assert sanitize_for_yaml(42) == "42"

    def test_em_dash_preserved(self):
        """Regular em dashes should be preserved."""
        result = sanitize_for_yaml("Hello — World")
        assert "— World" in result


class TestSanitizeForHtml:
    """Tests for HTML sanitization."""

    def test_normal_text_unchanged(self):
        """Normal text should pass through."""
        assert sanitize_for_html("Hello World") == "Hello World"

    def test_none_returns_empty(self):
        """None should return empty string."""
        assert sanitize_for_html(None) == ""

    def test_html_tags_escaped(self):
        """HTML tags should be escaped."""
        result = sanitize_for_html("<script>alert('xss')</script>")
        assert "<script>" not in result
        assert "&lt;script&gt;" in result

    def test_ampersand_escaped(self):
        """Ampersands should be escaped."""
        result = sanitize_for_html("A & B")
        assert "&amp;" in result

    def test_quotes_escaped(self):
        """Quotes should be escaped."""
        result = sanitize_for_html('He said "hello"')
        assert "&quot;" in result

    def test_single_quotes_escaped(self):
        """Single quotes should be escaped."""
        result = sanitize_for_html("It's a test")
        assert "&#x27;" in result

    def test_integer_input(self):
        """Integer inputs should be converted to string."""
        assert sanitize_for_html(42) == "42"


class TestRedactSecrets:
    """Tests for secret redaction."""

    def test_normal_text_unchanged(self):
        """Normal text should pass through."""
        assert redact_secrets("Hello World") == "Hello World"

    def test_none_returns_empty(self):
        """None should return empty string."""
        assert redact_secrets(None) == ""

    def test_openai_key_redacted(self):
        """OpenAI-style keys should be redacted."""
        result = redact_secrets("Using key sk-abc123def456ghi789jkl012mno345")
        assert "REDACTED" in result
        # The key should be partially visible (first few chars) then redacted
        assert "sk-" in result

    def test_google_api_key_redacted(self):
        """Google API keys should be redacted."""
        # Use a standalone key without "Key:" prefix to avoid key-value pattern matching first
        result = redact_secrets("Using AIzaSyA1234567890abcdefghijklmnopqrstuv as key")
        assert "REDACTED" in result
        assert "AIza" in result

    def test_bearer_token_redacted(self):
        """Bearer tokens should be redacted."""
        result = redact_secrets("Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")
        assert "REDACTED" in result

    def test_password_in_text_redacted(self):
        """Password key-value pairs should be redacted."""
        result = redact_secrets('password: "supersecretpassword123"')
        assert "REDACTED" in result

    def test_multiple_secrets_redacted(self):
        """Multiple secrets should all be redacted."""
        text = "sk-abc123def456ghi789jkl012mno345 and ghp_abcdefghijklmnopqrstuvwxyz1234567890"
        result = redact_secrets(text)
        assert result.count("REDACTED") >= 2

    def test_github_token_redacted(self):
        """GitHub personal tokens should be redacted."""
        # Use standalone token without "token:" prefix to avoid key-value pattern matching first
        result = redact_secrets("Found ghp_abcdefghijklmnopqrstuvwxyz1234567890 in config")
        assert "REDACTED" in result
        assert "ghp_" in result


class TestContainsHallucinationMarkers:
    """Tests for hallucination marker detection."""

    def test_normal_text_no_markers(self):
        """Normal summary text should not be flagged."""
        assert not contains_hallucination_markers("This is a summary of the article.")

    def test_empty_text_no_markers(self):
        """Empty text should not be flagged."""
        assert not contains_hallucination_markers("")
        assert not contains_hallucination_markers(None)

    def test_as_an_ai_detected(self):
        """'As an AI' should be detected."""
        assert contains_hallucination_markers("As an AI language model, I cannot...")

    def test_i_apologize_detected(self):
        """'I apologize' should be detected."""
        assert contains_hallucination_markers("I apologize, but I cannot summarize this.")

    def test_disclaimer_detected(self):
        """'Disclaimer:' should be detected."""
        assert contains_hallucination_markers("Disclaimer: This is not financial advice.")

    def test_case_insensitive(self):
        """Detection should be case-insensitive."""
        assert contains_hallucination_markers("as an ai, i cannot help")

    def test_partial_match_no_false_positive(self):
        """Partial matches should not cause false positives."""
        assert not contains_hallucination_markers("The AI model was trained on data.")


class TestValidateSummaryLength:
    """Tests for summary length validation."""

    def test_valid_summary(self):
        """Normal-length summary should pass."""
        errors = validate_summary_length("This is a valid summary with enough content.")
        assert errors == []

    def test_empty_summary(self):
        """Empty summary should fail."""
        errors = validate_summary_length("")
        assert any("empty" in e.lower() for e in errors)

    def test_none_summary(self):
        """None summary should fail."""
        errors = validate_summary_length(None)
        assert any("empty" in e.lower() for e in errors)

    def test_too_short_summary(self):
        """Very short summary should fail."""
        errors = validate_summary_length("Hi", min_length=10)
        assert any("too short" in e.lower() for e in errors)

    def test_too_long_summary(self):
        """Very long summary should fail."""
        errors = validate_summary_length("A" * 6000, max_length=5000)
        assert any("too long" in e.lower() for e in errors)

    def test_custom_field_name(self):
        """Custom field name should appear in errors."""
        errors = validate_summary_length("", field_name="标题")
        assert any("标题" in e for e in errors)

    def test_custom_min_max(self):
        """Custom min/max should be respected."""
        errors = validate_summary_length("Short", min_length=3, max_length=100)
        assert errors == []
