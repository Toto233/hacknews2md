from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from publisher.producthunt.models import Product


class ProductStore:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def connect(self) -> sqlite3.Connection:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA busy_timeout = 5000")
        return conn

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    rank INTEGER NOT NULL,
                    name TEXT NOT NULL,
                    slug TEXT,
                    tagline TEXT,
                    producthunt_url TEXT NOT NULL,
                    official_url TEXT,
                    thumbnail_url TEXT,
                    local_image TEXT,
                    votes INTEGER,
                    comments INTEGER,
                    categories_json TEXT,
                    source TEXT NOT NULL DEFAULT 'leaderboard',
                    fetched_at TEXT NOT NULL,
                    UNIQUE(year, month, rank),
                    UNIQUE(year, month, producthunt_url)
                );

                CREATE TABLE IF NOT EXISTS monthly_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    year INTEGER NOT NULL,
                    month INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    headline TEXT,
                    tags_json TEXT,
                    markdown_file TEXT,
                    html_file TEXT,
                    astro_file TEXT,
                    cover_image TEXT,
                    wechat_media_id TEXT,
                    receipt_file TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(year, month)
                );
                """
            )

    def replace_products_for_month(self, year: int, month: int, products: list[Product]) -> None:
        self.delete_products_for_month(year, month)
        self.upsert_products(products)

    def upsert_products(self, products: list[Product]) -> None:
        now = _now()
        with self.connect() as conn:
            conn.executemany(
                """
                INSERT INTO products (
                    year, month, rank, name, slug, tagline, producthunt_url,
                    official_url, thumbnail_url, votes, comments,
                    categories_json, source, fetched_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(year, month, producthunt_url) DO UPDATE SET
                    rank = excluded.rank,
                    name = excluded.name,
                    slug = excluded.slug,
                    tagline = excluded.tagline,
                    official_url = excluded.official_url,
                    thumbnail_url = excluded.thumbnail_url,
                    votes = excluded.votes,
                    comments = excluded.comments,
                    categories_json = excluded.categories_json,
                    source = excluded.source,
                    fetched_at = excluded.fetched_at
                """,
                [
                    (
                        product.year,
                        product.month,
                        product.rank,
                        product.name,
                        product.slug,
                        product.tagline,
                        product.producthunt_url,
                        product.official_url,
                        product.thumbnail_url,
                        product.votes,
                        product.comments,
                        json.dumps(product.categories, ensure_ascii=False),
                        product.source,
                        now,
                    )
                    for product in products
                ],
            )

    def delete_products_for_month(self, year: int, month: int) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM products WHERE year = ? AND month = ?", (year, month))

    def count_products(self, year: int, month: int) -> int:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) AS count FROM products WHERE year = ? AND month = ?",
                (year, month),
            ).fetchone()
        return int(row["count"])

    def list_products(self, year: int, month: int) -> list[Product]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM products
                WHERE year = ? AND month = ?
                ORDER BY rank ASC
                """,
                (year, month),
            ).fetchall()
        return [_row_to_product(row) for row in rows]

    def upsert_monthly_run(
        self,
        year: int,
        month: int,
        status: str,
        receipt_file: str | None = None,
    ) -> None:
        now = _now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO monthly_runs (year, month, status, receipt_file, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(year, month) DO UPDATE SET
                    status = excluded.status,
                    receipt_file = COALESCE(excluded.receipt_file, monthly_runs.receipt_file),
                    updated_at = excluded.updated_at
                """,
                (year, month, status, receipt_file, now, now),
            )

    def update_monthly_run_artifacts(self, year: int, month: int, **artifacts: Any) -> None:
        self.upsert_monthly_run(year, month, artifacts.get("status") or "UPDATED")
        with self.connect() as conn:
            conn.execute(
                """
                UPDATE monthly_runs
                SET status = COALESCE(?, status),
                    headline = COALESCE(?, headline),
                    tags_json = COALESCE(?, tags_json),
                    markdown_file = COALESCE(?, markdown_file),
                    html_file = COALESCE(?, html_file),
                    astro_file = COALESCE(?, astro_file),
                    cover_image = COALESCE(?, cover_image),
                    wechat_media_id = COALESCE(?, wechat_media_id),
                    receipt_file = COALESCE(?, receipt_file),
                    updated_at = ?
                WHERE year = ? AND month = ?
                """,
                (
                    artifacts.get("status"),
                    artifacts.get("headline"),
                    artifacts.get("tags_json"),
                    artifacts.get("markdown_file"),
                    artifacts.get("html_file"),
                    artifacts.get("astro_file"),
                    artifacts.get("cover_image"),
                    artifacts.get("wechat_media_id"),
                    artifacts.get("receipt_file"),
                    _now(),
                    year,
                    month,
                ),
            )

    def get_monthly_run(self, year: int, month: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM monthly_runs WHERE year = ? AND month = ?",
                (year, month),
            ).fetchone()
        return dict(row) if row else None


def _row_to_product(row: sqlite3.Row) -> Product:
    categories = json.loads(row["categories_json"] or "[]")
    return Product(
        year=row["year"],
        month=row["month"],
        rank=row["rank"],
        name=row["name"],
        slug=row["slug"],
        tagline=row["tagline"],
        producthunt_url=row["producthunt_url"],
        official_url=row["official_url"],
        thumbnail_url=row["thumbnail_url"],
        votes=row["votes"],
        comments=row["comments"],
        categories=categories,
        source=row["source"],
    )


def _now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
