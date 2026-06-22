"""
Content sanitization for YAML frontmatter and HTML output.

Prevents:
- YAML injection via titles containing `---` or special characters
- HTML injection via unescaped user content
- Script injection in markdown/HTML output
- Secret leakage in log output
"""

import re

# Patterns that look like API keys or secrets
_SECRET_PATTERNS = [
    re.compile(r"(sk-[a-zA-Z0-9]{20,})"),  # OpenAI-style keys
    re.compile(r"(AIza[a-zA-Z0-9_-]{20,})"),  # Google API keys
    re.compile(r"(ya29\.[a-zA-Z0-9_-]+)"),  # Google OAuth tokens
    re.compile(r"(ghp_[a-zA-Z0-9]{20,})"),  # GitHub personal tokens
    re.compile(r"(gho_[a-zA-Z0-9]{20,})"),  # GitHub OAuth tokens
    re.compile(r"(Bearer\s+[a-zA-Z0-9._-]{20,})"),  # Bearer tokens
    re.compile(r"(xoxb-[a-zA-Z0-9-]+)"),  # Slack bot tokens
    re.compile(r"(xoxp-[a-zA-Z0-9-]+)"),  # Slack user tokens
    re.compile(r'(?i)(password|secret|token|key)["\s]*[:=]["\s]*([^\s,;}{]{8,})'),  # Key-value pairs
]


def redact_secrets(text: str | None) -> str:
    """Redact potential secrets from text for safe logging.

    Replaces detected secret patterns with [REDACTED] markers.
    Safe for log output — prevents accidental secret leakage.
    """
    if not text:
        return ""

    text = str(text)
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(lambda m: m.group(0)[:4] + "***[REDACTED]", text)

    return text


# Characters that are dangerous in YAML values
_YAML_UNSAFE_PATTERN = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_YAML_FRONTMATTER_BOUNDARY = re.compile(r"^-{3,}\s*$", re.MULTILINE)


def sanitize_for_yaml(value: str | None) -> str:
    """Sanitize a string for safe inclusion in YAML frontmatter.

    Handles:
    - Null/empty values
    - YAML frontmatter boundary markers (---)
    - Control characters
    - Values that look like YAML directives

    Returns a safe string suitable for YAML quoting.
    """
    if value is None:
        return ""

    value = str(value)

    # Remove control characters (except tab, newline, carriage return)
    value = _YAML_UNSAFE_PATTERN.sub("", value)

    # Neutralize YAML frontmatter boundaries
    # A title like "---\nmalicious: true\n---" must not break frontmatter
    value = value.replace("---", "— —")  # Replace with em-dash approximation

    # Neutralize YAML directive markers
    value = re.sub(r"^%YAML\s", "YAML ", value, flags=re.MULTILINE)
    value = re.sub(r"^%TAG\s", "TAG ", value, flags=re.MULTILINE)

    return value


def quote_yaml_scalar(value: object) -> str:
    """Return a sanitized double-quoted YAML scalar."""
    sanitized = sanitize_for_yaml(None if value is None else str(value))
    escaped = sanitized.replace("\\", "\\\\").replace('"', '\\"')
    escaped = (
        escaped.replace("\r\n", "\\n")
        .replace("\r", "\\n")
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'


def sanitize_for_html(value: str | None) -> str:
    """Sanitize a string for safe inclusion in HTML output.

    Escapes HTML special characters to prevent injection.
    """
    if value is None:
        return ""

    value = str(value)
    value = value.replace("&", "&amp;")
    value = value.replace("<", "&lt;")
    value = value.replace(">", "&gt;")
    value = value.replace('"', "&quot;")
    value = value.replace("'", "&#x27;")

    return value


def contains_hallucination_markers(text: str | None) -> bool:
    """Check if text contains common LLM hallucination/rejection markers.

    Returns True if the text looks like it's from the LLM itself
    rather than a genuine summary of the content.
    """
    if not text:
        return False

    markers = [
        "As an AI",
        "As a language model",
        "I cannot",
        "I'm sorry",
        "I apologize",
        "I don't have access",
        "I'm unable to",
        "As an assistant",
        "I'm not able to",
        "I was unable to",
        "Note:",
        "Disclaimer:",
        "Please note that",
    ]

    text_lower = text.lower()
    return any(marker.lower() in text_lower for marker in markers)


def validate_summary_length(
    text: str | None,
    min_length: int = 20,
    max_length: int = 5000,
    field_name: str = "summary",
) -> list[str]:
    """Validate that a summary meets length requirements.

    Returns a list of error messages (empty if valid).
    """
    errors = []

    if not text:
        errors.append(f"{field_name} is empty")
        return errors

    text = text.strip()

    if len(text) < min_length:
        errors.append(f"{field_name} too short ({len(text)} < {min_length} chars)")

    if len(text) > max_length:
        errors.append(f"{field_name} too long ({len(text)} > {max_length} chars)")

    return errors
