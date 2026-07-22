from pathlib import Path


def test_producthunt_skill_exists_and_uses_publisher_entry_points() -> None:
    skill = Path("skills/publish-producthunt-monthly/SKILL.md").read_text(encoding="utf-8")

    for command in (
        ".\\scripts\\publisher.ps1 fetch producthunt",
        ".\\scripts\\publisher.ps1 release producthunt",
        ".\\scripts\\publisher.ps1 render producthunt",
        ".\\scripts\\publisher.ps1 cover producthunt",
        ".\\scripts\\publisher.ps1 publish producthunt",
    ):
        assert command in skill
    assert "--year" in skill
    assert "--month" in skill


def test_producthunt_skill_keeps_producthunt_separate_from_hackernews() -> None:
    skill = Path("skills/publish-producthunt-monthly/SKILL.md").read_text(encoding="utf-8")

    assert "data/producthunt.db" in skill
    assert "data/hacknews.db" not in skill
    assert "publisher hackernews" not in skill
    assert "hn2md " not in skill
    assert "ph2md " not in skill


def test_producthunt_skill_defaults_to_wechat_only() -> None:
    skill = Path("skills/publish-producthunt-monthly/SKILL.md").read_text(encoding="utf-8")

    assert "默认只发布 WeChat" in skill
    assert "--target astro" not in skill
