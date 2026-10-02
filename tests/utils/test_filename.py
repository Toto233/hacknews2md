import pytest

from src.utils.filename import sanitize_filename_stem


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Your intellectual fly is open (2025)", "Your_intellectual_fly_is_open_2025"),
        ('Windows <bad>: "name" / file?', "Windows_bad_name_file"),
        ("中文标题【测试】", "中文标题_测试"),
        ("report. ", "report"),
        ("CON", "_CON"),
    ],
)
def test_sanitize_filename_stem_is_safe_for_windows_and_markdown(raw: str, expected: str) -> None:
    assert sanitize_filename_stem(raw) == expected


def test_sanitize_filename_stem_has_a_deterministic_fallback() -> None:
    assert sanitize_filename_stem("()[]<>:?*", fallback="image") == "image"


def test_sanitize_filename_stem_applies_max_length_after_cleanup() -> None:
    assert sanitize_filename_stem("a" * 80, max_length=50) == "a" * 50
