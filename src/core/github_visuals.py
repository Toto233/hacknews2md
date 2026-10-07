"""Identify GitHub's repository sharing card in a saved article image set."""

from pathlib import Path
from urllib.parse import urlparse


def is_github_page_url(url: str) -> bool:
    """Match GitHub pages, not lookalike hosts or raw-content CDNs."""
    return urlparse(url).hostname in {"github.com", "www.github.com"}


def is_github_social_preview_url(url: str) -> bool:
    """Match the GitHub-generated Open Graph image service."""
    return urlparse(url).hostname == "opengraph.githubassets.com"


def github_preview_filename(story_id: int) -> str:
    """Give a saved preview an auditable story-specific filename."""
    return f"GitHubPreview_{story_id}"


def has_saved_github_preview(path: str | None, story_id: int) -> bool:
    """Require the actual saved sharing card, not an arbitrary article image."""
    if not path:
        return False
    candidate = Path(path)
    stem = github_preview_filename(story_id)
    return candidate.is_file() and (candidate.stem == stem or candidate.stem.startswith(f"{stem}_"))
