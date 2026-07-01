from pathlib import Path


def test_codex_skill_uses_publisher_project_entry_points() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    for command in (
        "publisher fetch hackernews",
        "publisher collect hackernews",
        "publisher audit hackernews",
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


def test_codex_skill_runs_audit_before_manual_plan() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    assert skill.index("publisher audit hackernews") < skill.index("publisher plan hackernews")
    assert "--approve" in skill
    assert "blocking" in skill


def test_codex_skill_defaults_to_wechat_and_astro_publish() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    assert "默认完整发布必须同时完成 WeChat 和 Astro" in skill
    assert "只发微信" in skill
    assert "明确要求" in skill


def test_codex_skill_forbids_guessing_missing_article_content() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    assert "不得用公开知识猜正文" in skill
    assert "human_input_or_handler" in skill
    assert "scraper_failures" in skill


def test_codex_skill_refreshes_collect_receipt_after_human_backfill() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    assert "用户说“补齐了”" in skill
    assert "publisher collect hackernews --rerun" in skill
    assert skill.index("publisher collect hackernews --rerun") < skill.index("publisher audit hackernews --json")


def test_codex_skill_keyword_gate_requires_sentence_review_for_neutral_or_negative_context() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    assert "关键词命中仅提醒，不硬阻止发布" in skill
    assert "褒义" in skill
    assert "中性或贬义" in skill
    assert "整句话" in skill
    assert "确认后再发布" in skill
