"""Locate the owning HackNews repository for repository-installed skill scripts."""

from __future__ import annotations

import os
import sys
from pathlib import Path


PROJECT_MARKER = Path("src/core/fetch_news.py")


def find_repo_root() -> Path:
    configured = os.environ.get("HACKNEWS_ROOT")
    candidates = []
    if configured:
        candidates.append(Path(configured).expanduser())
    candidates.extend([Path.cwd(), *Path.cwd().parents])
    script_path = Path(__file__).resolve()
    candidates.extend([script_path.parent, *script_path.parents])

    seen = set()
    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if (resolved / PROJECT_MARKER).is_file():
            return resolved
    raise RuntimeError(
        "HackNews repository not found. Run from the repository or set HACKNEWS_ROOT."
    )


REPO_ROOT = find_repo_root()
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.utils.deployment import load_deployment_settings  # noqa: E402


SETTINGS = load_deployment_settings(project_root=REPO_ROOT)
DB_PATH = SETTINGS.db_path
