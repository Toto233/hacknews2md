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
        "Do not infer unreadable article content",
        "Keyword hits are warnings",
        "Full HackNews publish defaults to WeChat and Astro",
    ]

    for phrase in required_phrases:
        assert phrase in text
