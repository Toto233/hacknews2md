"""Helpers for loading repository-local publishing scripts."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

from hn2md.context import RuntimeContext


def load_project_function(ctx: RuntimeContext, module_name: str, function_name: str) -> Any:
    """Load a function from a repository-local script module.

    Console entry points can run with the environment's Scripts directory as
    ``sys.path[0]`` instead of the project root. The hn2md stages still need to
    resolve ``scripts/*.py`` from the active RuntimeContext project root.
    """
    project_root = Path(getattr(ctx, "project_root", Path.cwd())).resolve()
    project_root_str = str(project_root)
    if project_root_str not in sys.path:
        sys.path.insert(0, project_root_str)

    module = importlib.import_module(module_name)
    return getattr(module, function_name)
