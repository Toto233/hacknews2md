"""Lazy command routing for the two publishing applications."""

from __future__ import annotations

import sys
from collections.abc import Sequence

import click


def producthunt_arguments(arguments: Sequence[str]) -> list[str] | None:
    """Translate the legacy ``publisher <command> producthunt`` entry point."""
    if len(arguments) < 2 or arguments[1].lower() != "producthunt":
        return None
    command, remaining = arguments[0], list(arguments[2:])
    if command in {"release", "cover", "plan", "apply", "collect", "capture-screenshots"}:
        raise click.ClickException(
            f"Product Hunt '{command}' is retired. Use ph2md export-plan, audit, render, "
            "preview and publish for the audited editorial workflow. "
            "Run ph2md --help for supported commands."
        )
    root_options: list[str] = []
    for index, value in enumerate(remaining):
        if value == "--root":
            if index + 1 >= len(remaining):
                raise click.UsageError("--root requires a path")
            root_options = remaining[index:index + 2]
            del remaining[index:index + 2]
            break
        if value.startswith("--root="):
            root_options = [value]
            del remaining[index]
            break
    if command == "publish" and "--dry-run" in remaining:
        command = "preview"
        remaining.remove("--dry-run")
    return [*root_options, command, *remaining]


def main() -> None:
    """Run PH without importing HN stages or load the existing HN CLI."""
    try:
        ph_arguments = producthunt_arguments(sys.argv[1:])
    except click.ClickException as exc:
        exc.show()
        raise SystemExit(exc.exit_code) from exc
    if ph_arguments is not None:
        from ph2md.cli import main as ph_main

        ph_main(args=ph_arguments, prog_name="publisher")
    else:
        from publisher.cli import main as hn_main

        hn_main()


if __name__ == "__main__":
    main()
