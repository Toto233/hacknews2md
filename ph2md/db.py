from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from contextlib import contextmanager
from collections.abc import Iterator

from src.db.connection import get_db
from typing import Any

from ph2md.models import Product


class ProductStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path

    @contextmanager
    def connect(self, *, read_only: bool = False) -> Iterator[sqlite3.Connection]:
        with get_db(str(self.db_path), read_only=read_only) as conn:
            conn.row_factory = sqlite3.Row
            yield conn

    def read_monthly_status(self, year: int, month: int) -> tuple[dict[str, Any] | None, int]:
        """Read one consistent snapshot without schema setup or writer locks."""
        if not self.db_path.is_file():
            return None, 0
        with self.connect(read_only=True) as conn:
            conn.execute("BEGIN")
            run = conn.execute(
                "SELECT * FROM monthly_runs WHERE year = ? AND month = ?", (year, month)
            ).fetchone()
            count = conn.execute(
                "SELECT COUNT(*) FROM products WHERE year = ? AND month = ?", (year, month)
            ).fetchone()[0]
        return dict(run) if run else None, int(count)

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(_products_table_sql("products", if_not_exists=True))
            conn.execute(
                """
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
                )
                """
            )
            if _has_legacy_url_unique_constraint(conn):
                _migrate_products_to_rank_identity(conn)

    def table_names(self) -> set[str]:
        with self.connect() as conn:
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall()
        return {row["name"] for row in rows}

    def upsert_products(self, products: list[Product]) -> None:
        with self.connect() as conn:
            _upsert_products(conn, products)

    def replace_products_for_month(self, year: int, month: int, products: list[Product]) -> None:
        validate_month_products(year, month, products)
        with self.connect() as conn:
            conn.execute("DELETE FROM products WHERE year = ? AND month = ?", (year, month))
            _upsert_products(conn, products)
            stored = conn.execute(
                "SELECT COUNT(*) AS total, COUNT(DISTINCT rank) AS unique_ranks, "
                "MIN(rank) AS first_rank, MAX(rank) AS last_rank "
                "FROM products WHERE year = ? AND month = ?",
                (year, month),
            ).fetchone()
            expected = len(products)
            if (
                stored["total"] != expected
                or stored["unique_ranks"] != expected
                or stored["first_rank"] != 1
                or stored["last_rank"] != expected
            ):
                raise ValueError(
                    f"Stored leaderboard does not match source for {year}-{month:02d}: "
                    f"source={expected}, stored={stored['total']}"
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
                    status = CASE
                        WHEN NULLIF(TRIM(monthly_runs.wechat_media_id), '') IS NOT NULL
                        THEN monthly_runs.status ELSE excluded.status END,
                    receipt_file = CASE
                        WHEN NULLIF(TRIM(monthly_runs.wechat_media_id), '') IS NOT NULL
                        THEN monthly_runs.receipt_file
                        ELSE COALESCE(excluded.receipt_file, monthly_runs.receipt_file) END,
                    updated_at = excluded.updated_at
                """,
                (year, month, status, receipt_file, now, now),
            )

    def record_wechat_draft(
        self,
        year: int,
        month: int,
        media_id: str,
        markdown_file: str,
        cover_image: str,
        receipt_file: str,
        *,
        verified: bool = True,
    ) -> None:
        if not media_id.strip():
            raise ValueError("WeChat media ID is required")
        now = _now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO monthly_runs (
                    year, month, status, markdown_file, cover_image,
                    wechat_media_id, receipt_file, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(year, month) DO UPDATE SET
                    status = excluded.status,
                    markdown_file = excluded.markdown_file,
                    cover_image = excluded.cover_image,
                    wechat_media_id = excluded.wechat_media_id,
                    receipt_file = excluded.receipt_file,
                    updated_at = excluded.updated_at
                """,
                (year, month, 'PUBLISHED' if verified else 'PUBLISH_UNVERIFIED', markdown_file, cover_image, media_id, receipt_file, now, now),
            )

    def get_monthly_run(self, year: int, month: int) -> dict[str, Any] | None:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM monthly_runs WHERE year = ? AND month = ?",
                (year, month),
            ).fetchone()
        return dict(row) if row else None


def validate_month_products(year: int, month: int, products: list[Product]) -> None:
    if not products:
        raise ValueError(f"No ranked products for {year}-{month:02d}")
    ranks = [product.rank for product in products]
    expected = list(range(1, len(products) + 1))
    if ranks != expected:
        raise ValueError(f"Leaderboard ranks must be consecutive from 1: got {ranks}")
    seen_launches: set[tuple[str, str]] = set()
    for product in products:
        if (product.year, product.month) != (year, month):
            raise ValueError(f"Rank {product.rank} belongs to a different month")
        launch = (product.name.strip().casefold(), product.producthunt_url.strip())
        if not all(launch):
            raise ValueError(f"Rank {product.rank} has no name or Product Hunt URL")
        if launch in seen_launches:
            raise ValueError(f"Duplicate launch at rank {product.rank}: {product.name}")
        seen_launches.add(launch)


def _products_table_sql(name: str, *, if_not_exists: bool = False) -> str:
    clause = "IF NOT EXISTS " if if_not_exists else ""
    return f"""
        CREATE TABLE {clause}{name} (
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
            UNIQUE(year, month, rank)
        )
    """


def _has_legacy_url_unique_constraint(conn: sqlite3.Connection) -> bool:
    for index in conn.execute("PRAGMA index_list(products)"):
        if not index["unique"]:
            continue
        escaped_name = index["name"].replace("'", "''")
        columns = [row["name"] for row in conn.execute(f"PRAGMA index_info('{escaped_name}')")]
        if columns == ["year", "month", "producthunt_url"]:
            return True
    return False


def _migrate_products_to_rank_identity(conn: sqlite3.Connection) -> None:
    columns = (
        "id, year, month, rank, name, slug, tagline, producthunt_url, "
        "official_url, thumbnail_url, local_image, votes, comments, "
        "categories_json, source, fetched_at"
    )
    conn.execute(_products_table_sql("products_rank_identity_new"))
    conn.execute(
        f"INSERT INTO products_rank_identity_new ({columns}) "
        f"SELECT {columns} FROM products"
    )
    conn.execute("DROP TABLE products")
    conn.execute("ALTER TABLE products_rank_identity_new RENAME TO products")


def _upsert_products(conn: sqlite3.Connection, products: list[Product]) -> None:
    now = _now()
    conn.executemany(
        """
        INSERT INTO products (
            year, month, rank, name, slug, tagline, producthunt_url,
            official_url, thumbnail_url, votes, comments,
            categories_json, source, fetched_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(year, month, rank) DO UPDATE SET
            local_image = CASE
                WHEN products.name = excluded.name
                 AND products.producthunt_url = excluded.producthunt_url
                THEN products.local_image ELSE NULL END,
            name = excluded.name,
            slug = excluded.slug,
            tagline = excluded.tagline,
            producthunt_url = excluded.producthunt_url,
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
