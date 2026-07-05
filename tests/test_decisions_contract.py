import re
from pathlib import Path


def test_decisions_log_exists_with_required_contract() -> None:
    text = Path("docs/DECISIONS.md").read_text(encoding="utf-8")

    required_phrases = [
        "# Decisions",
        "## How to use",
        "## Decision template",
        "Status:",
        "Issue:",
        "Supersedes:",
        "Failure mode of alternative:",
        "Do not infer unreadable article content",
        "Keyword hits are warnings",
        "Full HackNews publish defaults to WeChat and Astro",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_every_decision_has_failure_mode_field() -> None:
    """Each decision entry must have a 'Failure mode of alternative' field."""
    text = Path("docs/DECISIONS.md").read_text(encoding="utf-8")

    # Find all decision headings (### YYYY-MM-DD — ...)
    decision_headings = re.findall(r"^### \d{4}-\d{2}-\d{2} — .+", text, re.MULTILINE)
    assert len(decision_headings) >= 1, "Expected at least one decision entry"

    # Find all failure mode lines
    failure_mode_lines = re.findall(r"^- Failure mode of alternative:.+", text, re.MULTILINE)
    assert len(failure_mode_lines) >= len(decision_headings), (
        f"Expected {len(decision_headings)} failure mode fields, found {len(failure_mode_lines)}. "
        "Every decision must have a 'Failure mode of alternative' line."
    )
