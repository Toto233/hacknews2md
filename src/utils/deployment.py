"""Portable deployment path resolution for the HackNews publishing workflow."""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ASTRO_BLOG_SUBDIR = Path("src/data/blog")


@dataclass(frozen=True)
class DeploymentSettings:
    project_root: Path
    db_path: Path
    astro_enabled: bool
    astro_repo: Path | None
    astro_blog_dir: Path | None
    image_wrapper: Path | None
    config_path: Path


def _as_bool(value: object, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _resolve_path(value: object, base: Path) -> Path | None:
    if value is None or not str(value).strip():
        return None
    path = Path(os.path.expandvars(os.path.expanduser(str(value).strip())))
    if not path.is_absolute():
        path = base / path
    return path.resolve()


def load_deployment_settings(
    project_root: Path | str | None = None,
    environ: Mapping[str, str] | None = None,
) -> DeploymentSettings:
    env = os.environ if environ is None else environ
    root_value = env.get("HACKNEWS_ROOT") or project_root or DEFAULT_PROJECT_ROOT
    root = Path(root_value).expanduser().resolve()
    config_path = _resolve_path(
        env.get("HACKNEWS_DEPLOYMENT_CONFIG") or root / "config" / "deployment.local.json",
        root,
    )
    assert config_path is not None

    config = {}
    if config_path.exists():
        config = json.loads(config_path.read_text(encoding="utf-8"))

    astro = config.get("astro", {})
    image_generator = config.get("image_generator", {})
    astro_repo = _resolve_path(env.get("HACKNEWS_ASTRO_REPO") or astro.get("repo_path"), root)
    astro_enabled = _as_bool(
        env.get("HACKNEWS_ASTRO_ENABLED"),
        default=_as_bool(astro.get("enabled"), default=False),
    )
    blog_subdir = Path(astro.get("blog_subdir") or DEFAULT_ASTRO_BLOG_SUBDIR)
    astro_blog_dir = (astro_repo / blog_subdir).resolve() if astro_enabled and astro_repo else None

    db_path = _resolve_path(env.get("HACKNEWS_DB_PATH"), root) or root / "data" / "hacknews.db"
    image_wrapper = _resolve_path(
        env.get("HACKNEWS_IMAGE_WRAPPER") or image_generator.get("wrapper_path"),
        root,
    )

    return DeploymentSettings(
        project_root=root,
        db_path=db_path.resolve(),
        astro_enabled=astro_enabled,
        astro_repo=astro_repo,
        astro_blog_dir=astro_blog_dir,
        image_wrapper=image_wrapper,
        config_path=config_path,
    )


def resolve_image_wrapper(settings: DeploymentSettings | None = None) -> Path:
    current = settings or load_deployment_settings()
    candidates = [
        current.image_wrapper,
        Path.home() / ".claude/skills/gpt-image-2-skill/scripts/gpt_image_2_skill.cjs",
        Path.home() / ".codex/skills/gpt-image-2-skill/scripts/gpt_image_2_skill.cjs",
    ]
    for candidate in candidates:
        if candidate and candidate.exists():
            return candidate
    checked = ", ".join(str(path) for path in candidates if path)
    raise FileNotFoundError(f"gpt-image-2-skill wrapper not found. Checked: {checked}")
