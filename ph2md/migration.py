"""Conservative copy migration from the former Product Hunt editorial project."""
from __future__ import annotations

import json
import shutil
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ph2md.config import AppPaths
from ph2md.db import ProductStore
from ph2md.editorial import write_json
from ph2md.lock import source_lock


def migrate_legacy_workspace(source_root: Path, paths: AppPaths) -> dict[str, Any]:
    source_root = source_root.resolve()
    source_db = source_root / "data" / "producthunt.db"
    if not source_db.is_file():
        raise ValueError(f"No legacy editorial database: {source_db}")
    if source_root == paths.root.resolve():
        raise ValueError("Use a separate source workspace for legacy editorial migration")
    # Read-only is essential here: migration must not modify the original project's WAL or schema.
    with sqlite3.connect(source_db.as_uri() + "?mode=ro", uri=True) as source:
        columns = {row[1] for row in source.execute("PRAGMA table_info(products)")}
        run_columns = {row[1] for row in source.execute("PRAGMA table_info(monthly_runs)")}
        if not {"rank", "name", "producthunt_url", "year", "month", "categories_json"} <= columns or not {"year", "month", "wechat_media_id"} <= run_columns:
            raise ValueError("Source database is not the editorial ph2md schema; refusing migration")
        source_outputs = source_root / "output"
        copies = [(file, paths.output_dir / file.relative_to(source_outputs)) for directory in ("codex", "markdown", "images", "receipts", "backups", "debug") for file in (source_outputs / directory).rglob("*") if file.is_file()]
        conflicts = [str(destination) for _, destination in copies if destination.exists()]
        if paths.db_path.exists():
            conflicts.append(str(paths.db_path))
        if conflicts:
            raise ValueError("Migration would overwrite existing files: " + "; ".join(conflicts[:10]))
        with source_lock(paths.root):
            conflicts = [str(destination) for _, destination in copies if destination.exists()]
            if paths.db_path.exists():
                conflicts.append(str(paths.db_path))
            if conflicts:
                raise ValueError("Migration would overwrite existing files: " + "; ".join(conflicts[:10]))
            paths.ensure()
            # Keep a consistent unmodified source snapshot separate from the working database.
            timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
            backup = paths.output_dir / "backups" / f"legacy_database_{timestamp}.db"
            backup.parent.mkdir(parents=True, exist_ok=True)
            with sqlite3.connect(backup) as destination:
                source.backup(destination)
            shutil.copy2(backup, paths.db_path)
            for original, destination in copies:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(original, destination)
            store = ProductStore(paths.db_path)
            store.init_schema()
            # Rebase only stored local artifact paths; the source backup and originals stay intact.
            with store.connect() as connection:
                rows = connection.execute("SELECT id, markdown_file, html_file, astro_file, cover_image, receipt_file FROM monthly_runs").fetchall()
                for row in rows:
                    values = [_rebase(value, source_root, paths) for value in row[1:]]
                    connection.execute("UPDATE monthly_runs SET markdown_file=?, html_file=?, astro_file=?, cover_image=?, receipt_file=? WHERE id=?", (*values, row["id"]))
            for _, destination in copies:
                if destination.suffix in {".md", ".html", ".json"} and "backups" not in destination.relative_to(paths.output_dir).parts:
                    text = destination.read_text(encoding="utf-8")
                    for old, new in ((str(source_outputs), str(paths.output_dir)), (source_outputs.as_posix(), paths.output_dir.as_posix()), (str(source_outputs).replace("\\", "\\\\"), str(paths.output_dir).replace("\\", "\\\\"))):
                        text = text.replace(old, new)
                    if destination.suffix == ".json":
                        payload = json.loads(text)
                        text = json.dumps(_rebase_json_paths(payload, source_root, paths), ensure_ascii=False, indent=2) + "\n"
                    elif destination.suffix == ".md":
                        import re
                        text = re.sub(r"(?<=\()output/([^\s)]+)(?=\))", lambda match: (paths.output_dir / match.group(1)).as_posix(), text)
                    elif destination.suffix == ".html":
                        import re
                        text = re.sub(r'(?<=src=")output/([^"\s]+)', lambda match: (paths.output_dir / match.group(1)).as_posix(), text)
                    destination.write_text(text, encoding="utf-8")
            report = {"source_root": str(source_root), "database": str(paths.db_path), "database_backup": str(backup), "copied_files": len(copies), "originals_preserved": True}
            write_json(paths.receipts_dir / f"migration_{timestamp}.json", report)
            return report


def _rebase(value: str | None, source_root: Path, paths: AppPaths) -> str | None:
    if not value:
        return value
    normalized = value.replace("\\", "/")
    source_output = (source_root / "output").as_posix()
    if normalized.startswith(source_output + "/"):
        return paths.output_dir.as_posix() + normalized[len(source_output):]
    if normalized.startswith("output/"):
        return str(paths.output_dir / normalized[len("output/"):])
    return value


def _rebase_json_paths(value: Any, source_root: Path, paths: AppPaths) -> Any:
    if isinstance(value, dict):
        return {key: _rebase_json_paths(item, source_root, paths) for key, item in value.items()}
    if isinstance(value, list):
        return [_rebase_json_paths(item, source_root, paths) for item in value]
    if isinstance(value, str) and (value.replace("\\", "/").startswith("output/") or value.replace("\\", "/").startswith((source_root / "output").as_posix() + "/")):
        return _rebase(value, source_root, paths)
    return value
