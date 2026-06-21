"""Tests for pdf_handler.py.

The pdf_handler module has no standalone pure functions.  Its only public
function ``get_pdf_content`` is async and performs network I/O (HTTP download +
PyPDF2 extraction).

This file is a placeholder documenting that fact.  If pure helpers are
extracted in the future (e.g. a content-type validator, text cleaner), add
their tests here.
"""

import pytest

from src.core.handlers import pdf_handler


def test_placeholder_pdf_handler_has_no_pure_functions():
    """Confirm this is a placeholder -- pdf_handler has no pure functions yet."""
    # get_pdf_content exists but is async and requires network
    assert hasattr(pdf_handler, "get_pdf_content")
