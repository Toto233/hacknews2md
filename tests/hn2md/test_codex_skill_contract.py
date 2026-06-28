from pathlib import Path


def test_codex_skill_uses_publisher_project_entry_points() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    for command in (
        "publisher fetch hackernews",
        "publisher collect hackernews",
        "publisher plan hackernews",
        "publisher apply hackernews",
        "publisher render hackernews",
        "publisher cover hackernews",
        "publisher publish hackernews",
    ):
        assert command in skill
    assert "hn2md " not in skill
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
