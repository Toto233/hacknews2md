"""Length and formatting rules for the Hacker News recap headline."""

from datetime import date

from src.security.content_sanitizer import contains_hallucination_markers, sanitize_for_yaml


_RECAP_LABEL = "Hacker News 摘要"
_TITLE_SUFFIX = " | " + _RECAP_LABEL + " ({date})"
RECAP_HEADLINE_LIMIT = 64 - len(_TITLE_SUFFIX.format(date="0000-00-00"))


def validate_recap_headline(value: object) -> str:
    """Return a usable one-line headline prefix or reject it without truncation."""
    headline = sanitize_for_yaml(value).strip() if isinstance(value, str) else ""
    if (
        not headline
        or len(headline.splitlines()) != 1
        or headline.lower() == "null"
        or headline.startswith("```")
        or contains_hallucination_markers(headline)
    ):
        raise ValueError("recap_headline must be a non-empty, single-line headline")
    if len(headline) > RECAP_HEADLINE_LIMIT:
        raise ValueError(f"recap_headline must be at most {RECAP_HEADLINE_LIMIT} characters")
    return headline


def format_recap_title(lead_title: str, recap_headline: object, published_on: date) -> str:
    """Use the lead, an edited headline, or the dated recap label for older plans."""
    prefix = sanitize_for_yaml(lead_title).strip()
    if len(prefix) > RECAP_HEADLINE_LIMIT:
        prefix = validate_recap_headline(recap_headline) if recap_headline is not None else ""
    if not prefix:
        return f"{_RECAP_LABEL} ({published_on.isoformat()})"
    return prefix + _TITLE_SUFFIX.format(date=published_on.isoformat())
