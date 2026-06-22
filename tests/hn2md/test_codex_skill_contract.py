from pathlib import Path


def test_codex_skill_uses_only_hn2md_project_entry_points() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    for command in (
        "hn2md fetch",
        "hn2md collect",
        "hn2md plan --manual-plan",
        "hn2md apply",
        "hn2md render",
        "hn2md cover",
        "hn2md publish",
    ):
        assert command in skill
    for legacy in (
        "src\\core\\fetch_news.py",
        "collect_news_context.py",
        "apply_news_edits.py",
        "render_manual_markdown.py",
        "generate_wechat_cover_ai.py",
        "publish_wechat.py",
    ):
        assert legacy not in skill


def test_codex_skill_explicitly_forbids_external_llm_in_manual_mode() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    assert "Gemini/Grok/Moonshot" in skill
    assert "不得调用" in skill
