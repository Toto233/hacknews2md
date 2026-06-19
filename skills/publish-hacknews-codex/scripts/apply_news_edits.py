#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import json
import sqlite3
from pathlib import Path

from _bootstrap import DB_PATH


def main() -> int:
    parser = argparse.ArgumentParser(description="Apply Codex-generated HackNews titles and summaries to the database.")
    parser.add_argument("plan_file", help="JSON file with items[{id,title_chs,content_summary,discuss_summary}]")
    args = parser.parse_args()

    with open(args.plan_file, "r", encoding="utf-8") as f:
        plan = json.load(f)

    items = plan.get("items", [])
    conn = sqlite3.connect(str(DB_PATH))
    cur = conn.cursor()

    updated = 0
    for item in items:
        news_id = item["id"]
        cur.execute(
            """
            UPDATE news
            SET title_chs = ?, content_summary = ?, discuss_summary = ?
            WHERE id = ?
            """,
            (
                item.get("title_chs"),
                item.get("content_summary"),
                item.get("discuss_summary"),
                news_id,
            ),
        )
        updated += cur.rowcount

    conn.commit()
    conn.close()

    print(json.dumps({"ok": True, "updated": updated, "plan_file": str(Path(args.plan_file).resolve())}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
