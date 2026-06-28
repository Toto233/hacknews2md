"""Tests for PDF URL normalization and extraction helpers."""

from src.core.handlers import pdf_handler


def test_github_blob_pdf_url_converts_to_raw_url() -> None:
    url = "https://github.com/deepseek-ai/DeepSpec/blob/main/DSpark_paper.pdf"

    assert pdf_handler.normalize_pdf_url(url) == (
        "https://raw.githubusercontent.com/deepseek-ai/DeepSpec/main/DSpark_paper.pdf"
    )


def test_plain_pdf_url_is_unchanged() -> None:
    url = "https://example.com/paper.pdf"

    assert pdf_handler.normalize_pdf_url(url) == url


def test_detects_github_blob_pdf_as_pdf_url() -> None:
    assert pdf_handler.is_pdf_url("https://github.com/org/repo/blob/main/paper.pdf")
