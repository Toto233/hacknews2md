"""Portable filename helpers for generated publishing assets."""

import re


_UNSAFE_FILENAME_CHARS = re.compile(r'[\x00-\x1f<>:"/\\|?*()\[\]{}【】]+')
_SEPARATOR_RUN = re.compile(r"[\s_]+")
_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


def sanitize_filename_stem(
    value: str,
    *,
    max_length: int = 50,
    fallback: str = "image",
) -> str:
    """Return a Windows-safe stem that is also safe in Markdown image paths.

    Windows permits parentheses, but an unescaped closing parenthesis terminates
    the image destination used by this project's Markdown renderer. Generated
    asset names therefore use a deliberately narrower portable character set.
    """
    if max_length < 1:
        raise ValueError("max_length must be positive")

    safe_name = _UNSAFE_FILENAME_CHARS.sub("_", value)
    safe_name = _SEPARATOR_RUN.sub("_", safe_name).strip(" ._-")
    safe_name = safe_name[:max_length].rstrip(" ._-")

    if not safe_name:
        safe_name = _UNSAFE_FILENAME_CHARS.sub("_", fallback)
        safe_name = _SEPARATOR_RUN.sub("_", safe_name).strip(" ._-")
        safe_name = safe_name[:max_length].rstrip(" ._-") or "image"

    if safe_name.split(".", 1)[0].upper() in _WINDOWS_RESERVED_NAMES:
        safe_name = f"_{safe_name}"
        safe_name = safe_name[:max_length].rstrip(" ._-") or "image"

    return safe_name
