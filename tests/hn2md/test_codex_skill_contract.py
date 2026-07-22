from pathlib import Path


def test_codex_skill_uses_publisher_project_entry_points() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    for command in (
        ".\\scripts\\publisher.ps1 fetch hackernews",
        ".\\scripts\\publisher.ps1 collect hackernews",
        ".\\scripts\\publisher.ps1 audit hackernews",
        ".\\scripts\\publisher.ps1 plan hackernews",
        ".\\scripts\\publisher.ps1 apply hackernews",
        ".\\scripts\\publisher.ps1 render hackernews",
        ".\\scripts\\publisher.ps1 cover hackernews",
        ".\\scripts\\publisher.ps1 publish hackernews",
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
    assert skill.index(".\\scripts\\publisher.ps1 audit hackernews") < skill.index(".\\scripts\\publisher.ps1 plan hackernews")
    assert "--approve" in skill
    assert "blocking" in skill


def test_codex_skill_prefers_compact_draft_plan_material() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    assert ".\\scripts\\publisher.ps1 draft-plan hackernews" in skill
    assert "context_file" in skill
    assert skill.index(".\\scripts\\publisher.ps1 audit hackernews") < skill.index(".\\scripts\\publisher.ps1 draft-plan hackernews")


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
    assert ".\\scripts\\publisher.ps1 collect hackernews --rerun" in skill
    assert skill.index(".\\scripts\\publisher.ps1 collect hackernews --rerun") < skill.index(".\\scripts\\publisher.ps1 audit hackernews --json")


def test_codex_skill_keyword_gate_requires_sentence_review_for_neutral_or_negative_context() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    assert "关键词命中仅提醒，不硬阻止发布" in skill
    assert "褒义" in skill
    assert "中性或贬义" in skill
    assert "整句话" in skill
    assert "确认后再发布" in skill


def test_codex_skill_requires_discussion_summary_source_when_discussion_is_empty() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    assert "discuss_summary_source_type" in skill
    assert "external_hn_snippet" in skill
    assert "discussion_content 为空" in skill


def test_codex_skill_uses_github_issues_and_decisions_for_recurring_changes() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    assert "GitHub Issue" in skill
    assert "docs/DECISIONS.md" in skill
    assert "Supersedes" in skill
    assert "不要直接改回旧行为" in skill
    assert "Failure mode of alternative" in skill
    assert "另一条路为什么走不通" in skill


def test_codex_skill_handles_existing_astro_staged_changes_without_deleting_files() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    assert "Astro 仓库已有 staged changes" in skill
    assert "不要删除文件，不要 reset" in skill
    assert "restore --staged" in skill
    assert "无关未跟踪文件" in skill


def test_codex_skill_post_run_review_uses_dedicated_publisher_command() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")
    assert ".\\scripts\\publisher.ps1 review-run hackernews" in skill
    assert ".\\scripts\\publisher.ps1 review-run hackernews --json" in skill
    assert "output/reviews/run_review_" in skill
    assert "publisher audit hackernews --post-publish" not in skill


def test_codex_skill_uses_publisher_for_future_domain_filters() -> None:
    skill = Path("skills/publish-hacknews-codex/SKILL.md").read_text(encoding="utf-8")

    assert ".\\scripts\\publisher.ps1 filter-domain hackernews" in skill
