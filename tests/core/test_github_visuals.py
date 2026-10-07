from src.core.github_visuals import (
    github_preview_filename,
    has_saved_github_preview,
    is_github_page_url,
    is_github_social_preview_url,
)


def test_github_visual_urls_use_exact_hosts() -> None:
    assert is_github_page_url("https://github.com/owner/repo")
    assert is_github_page_url("https://www.github.com/owner/repo")
    assert not is_github_page_url("https://github.com.evil.example/owner/repo")
    assert not is_github_page_url("https://raw.githubusercontent.com/owner/repo/file")
    assert is_github_social_preview_url("https://opengraph.githubassets.com/hash/owner/repo")
    assert not is_github_social_preview_url("https://opengraph.githubassets.com.evil.example/hash")


def test_saved_preview_must_be_a_matching_existing_file(tmp_path) -> None:
    preview = tmp_path / f"{github_preview_filename(42)}.png"
    preview.write_bytes(b"preview")
    avatar = tmp_path / "avatar.png"
    avatar.write_bytes(b"avatar")

    assert has_saved_github_preview(str(preview), 42)
    assert not has_saved_github_preview(str(preview), 43)
    assert not has_saved_github_preview(str(avatar), 42)
    assert not has_saved_github_preview(str(tmp_path / "GitHubPreview_42_missing.png"), 42)
