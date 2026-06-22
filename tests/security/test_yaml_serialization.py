"""Canonical YAML scalar serialization tests."""

import pytest

from src.security.content_sanitizer import quote_yaml_scalar


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, '""'),
        ("plain", '"plain"'),
        ('say "hi"', '"say \\"hi\\""'),
        ("a\\b", '"a\\\\b"'),
        ("a\nb", '"a\\nb"'),
        ("a\r\nb", '"a\\nb"'),
        ("a\tb", '"a\\tb"'),
        ("---\nmalicious: true", '"— —\\nmalicious: true"'),
    ],
)
def test_quote_yaml_scalar(value, expected) -> None:
    assert quote_yaml_scalar(value) == expected
