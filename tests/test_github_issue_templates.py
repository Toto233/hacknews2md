from pathlib import Path


def test_publish_issue_templates_exist() -> None:
    template_dir = Path(".github/ISSUE_TEMPLATE")

    expected_templates = [
        "publish-bug.yml",
        "quality-gate.yml",
        "workflow-improvement.yml",
        "decision.yml",
    ]

    for filename in expected_templates:
        text = (template_dir / filename).read_text(encoding="utf-8")
        assert "labels:" in text
        assert "body:" in text
