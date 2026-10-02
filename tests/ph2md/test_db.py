from pathlib import Path
import sqlite3

import pytest

import ph2md.db as db_module
from ph2md.db import ProductStore
from ph2md.models import Product


def test_init_creates_schema(tmp_path: Path):
    store = ProductStore(tmp_path / "ph.db")

    store.init_schema()

    tables = store.table_names()
    assert "products" in tables
    assert "monthly_runs" in tables


def test_upsert_products_is_idempotent(tmp_path: Path):
    store = ProductStore(tmp_path / "ph.db")
    store.init_schema()
    product = Product(
        year=2026,
        month=6,
        rank=1,
        name="Fundraisly",
        slug="fundraisly",
        tagline="AI fundraising agent",
        producthunt_url="https://www.producthunt.com/products/fundraisly",
        votes=1462,
        comments=411,
        categories=["Venture Capital", "Artificial Intelligence"],
        thumbnail_url="https://ph-files.imgix.net/fundraisly.png",
    )

    store.upsert_products([product])
    store.upsert_products([product])

    assert store.count_products(2026, 6) == 1
    saved = store.list_products(2026, 6)
    assert saved[0].name == "Fundraisly"
    assert saved[0].categories == ["Venture Capital", "Artificial Intelligence"]


def test_run_status_can_be_updated_and_read(tmp_path: Path):
    store = ProductStore(tmp_path / "ph.db")
    store.init_schema()

    store.upsert_monthly_run(2026, 6, "FETCHING")
    store.upsert_monthly_run(2026, 6, "FETCHED", receipt_file="output/receipts/fetch_202606.json")

    run = store.get_monthly_run(2026, 6)
    assert run is not None
    assert run["status"] == "FETCHED"
    assert run["receipt_file"] == "output/receipts/fetch_202606.json"


def test_record_wechat_draft_preserves_existing_monthly_run_fields(tmp_path: Path):
    store = ProductStore(tmp_path / "ph.db")
    store.init_schema()
    store.upsert_monthly_run(2026, 9, "FETCHED")
    with store.connect() as conn:
        conn.execute(
            "UPDATE monthly_runs SET headline = ?, html_file = ? WHERE year = ? AND month = ?",
            ("September headline", "old.html", 2026, 9),
        )

    store.record_wechat_draft(
        2026, 9, "media-123", "article.md", "cover.png", "publish_receipt.json"
    )

    run = store.get_monthly_run(2026, 9)
    assert run["status"] == "PUBLISHED"
    assert run["wechat_media_id"] == "media-123"
    assert run["markdown_file"] == "article.md"
    assert run["cover_image"] == "cover.png"
    assert run["receipt_file"] == "publish_receipt.json"
    assert run["headline"] == "September headline"
    assert run["html_file"] == "old.html"


def test_fetch_status_updates_preserve_published_draft_receipt(tmp_path: Path):
    store = ProductStore(tmp_path / "ph.db")
    store.init_schema()
    store.record_wechat_draft(
        2026, 9, "media-123", "article.md", "cover.png", "publish_receipt.json"
    )

    for status in ("FETCHING", "FETCHED", "FAILED"):
        store.upsert_monthly_run(2026, 9, status, receipt_file="fetch_receipt.json")
        run = store.get_monthly_run(2026, 9)
        assert run["status"] == "PUBLISHED"
        assert run["receipt_file"] == "publish_receipt.json"
        assert run["wechat_media_id"] == "media-123"

    store.replace_products_for_month(2026, 9, [
        Product(2026, 9, 1, "Refreshed", "https://www.producthunt.com/products/refreshed")
    ])
    assert store.count_products(2026, 9) == 1


def test_replace_products_for_month_allows_rank_reordering(tmp_path: Path):
    store = ProductStore(tmp_path / "ph.db")
    store.init_schema()
    store.upsert_products(
        [
            Product(
                year=2026,
                month=6,
                rank=1,
                name="Old First",
                producthunt_url="https://www.producthunt.com/products/old-first",
            ),
            Product(
                year=2026,
                month=6,
                rank=2,
                name="Old Second",
                producthunt_url="https://www.producthunt.com/products/old-second",
            ),
        ]
    )

    store.replace_products_for_month(
        2026,
        6,
        [
            Product(
                year=2026,
                month=6,
                rank=1,
                name="Old Second",
                producthunt_url="https://www.producthunt.com/products/old-second",
            ),
            Product(
                year=2026,
                month=6,
                rank=2,
                name="Old First",
                producthunt_url="https://www.producthunt.com/products/old-first",
            ),
        ],
    )

    products = store.list_products(2026, 6)
    assert [(product.rank, product.name) for product in products] == [
        (1, "Old Second"),
        (2, "Old First"),
    ]


def test_delete_products_for_month_keeps_other_months(tmp_path: Path):
    store = ProductStore(tmp_path / "ph.db")
    store.init_schema()
    store.upsert_products(
        [
            Product(
                year=2026,
                month=6,
                rank=1,
                name="June Product",
                producthunt_url="https://www.producthunt.com/products/june",
            ),
            Product(
                year=2026,
                month=5,
                rank=1,
                name="May Product",
                producthunt_url="https://www.producthunt.com/products/may",
            ),
        ]
    )

    store.delete_products_for_month(2026, 6)

    assert store.count_products(2026, 6) == 0
    assert store.count_products(2026, 5) == 1


def test_same_product_url_can_hold_two_monthly_launches(tmp_path: Path):
    store = ProductStore(tmp_path / "ph.db")
    store.init_schema()
    products = [
        Product(2026, 9, 1, "Kilo Code for JetBrains", "https://www.producthunt.com/products/kilocode"),
        Product(2026, 9, 2, "Kilo Code for iOS and Android", "https://www.producthunt.com/products/kilocode"),
    ]

    store.replace_products_for_month(2026, 9, products)

    assert [(item.rank, item.name) for item in store.list_products(2026, 9)] == [
        (1, "Kilo Code for JetBrains"),
        (2, "Kilo Code for iOS and Android"),
    ]


@pytest.mark.parametrize(
    "replacement",
    [
        [Product(2026, 9, 1, "First", "https://www.producthunt.com/products/first"),
         Product(2026, 9, 3, "Third", "https://www.producthunt.com/products/third")],
        [Product(2026, 9, 1, "First", "https://www.producthunt.com/products/first"),
         Product(2026, 9, 2, "First", "https://www.producthunt.com/products/first")],
        [Product(2026, 8, 1, "Wrong month", "https://www.producthunt.com/products/wrong")],
    ],
)
def test_invalid_source_cannot_replace_existing_month(tmp_path: Path, replacement: list[Product]):
    store = ProductStore(tmp_path / "ph.db")
    store.init_schema()
    original = Product(2026, 9, 1, "Original", "https://www.producthunt.com/products/original")
    store.replace_products_for_month(2026, 9, [original])

    with pytest.raises(ValueError):
        store.replace_products_for_month(2026, 9, replacement)

    assert store.list_products(2026, 9) == [original]


def test_failed_insert_rolls_back_month_replacement(tmp_path: Path, monkeypatch):
    store = ProductStore(tmp_path / "ph.db")
    store.init_schema()
    original = Product(2026, 9, 1, "Original", "https://www.producthunt.com/products/original")
    store.replace_products_for_month(2026, 9, [original])

    def fail_insert(conn: sqlite3.Connection, products: list[Product]) -> None:
        raise sqlite3.IntegrityError("simulated insert failure")

    monkeypatch.setattr("ph2md.db._upsert_products", fail_insert)
    with pytest.raises(sqlite3.IntegrityError):
        store.replace_products_for_month(2026, 9, [
            Product(2026, 9, 1, "Replacement", "https://www.producthunt.com/products/replacement")
        ])

    assert store.list_products(2026, 9) == [original]


def test_source_to_store_count_mismatch_rolls_back_month_replacement(tmp_path: Path, monkeypatch):
    store = ProductStore(tmp_path / "ph.db")
    store.init_schema()
    original = Product(2026, 9, 1, "Original", "https://www.producthunt.com/products/original")
    store.replace_products_for_month(2026, 9, [original])
    real_upsert = db_module._upsert_products

    def drop_one(conn: sqlite3.Connection, products: list[Product]) -> None:
        real_upsert(conn, products[:1])

    monkeypatch.setattr("ph2md.db._upsert_products", drop_one)
    with pytest.raises(ValueError, match="Stored leaderboard does not match source"):
        store.replace_products_for_month(2026, 9, [
            Product(2026, 9, 1, "First", "https://www.producthunt.com/products/first"),
            Product(2026, 9, 2, "Second", "https://www.producthunt.com/products/second"),
        ])

    assert store.list_products(2026, 9) == [original]


def test_schema_migration_preserves_legacy_rows_and_run(tmp_path: Path):
    db_path = tmp_path / "legacy.db"
    with sqlite3.connect(db_path) as conn:
        conn.executescript("""
            CREATE TABLE products (
                id INTEGER PRIMARY KEY AUTOINCREMENT, year INTEGER NOT NULL, month INTEGER NOT NULL,
                rank INTEGER NOT NULL, name TEXT NOT NULL, slug TEXT, tagline TEXT,
                producthunt_url TEXT NOT NULL, official_url TEXT, thumbnail_url TEXT,
                local_image TEXT, votes INTEGER, comments INTEGER, categories_json TEXT,
                source TEXT NOT NULL DEFAULT 'leaderboard', fetched_at TEXT NOT NULL,
                UNIQUE(year, month,rank), UNIQUE(year,month,producthunt_url)
            );
            INSERT INTO products (year,month,rank,name,producthunt_url,local_image,fetched_at)
            VALUES (2026,9,1,'Original','https://www.producthunt.com/products/kilocode','saved.png','2026-09-30');
            CREATE TABLE monthly_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, year INTEGER NOT NULL, month INTEGER NOT NULL,
                status TEXT NOT NULL, headline TEXT, tags_json TEXT, markdown_file TEXT,
                html_file TEXT, astro_file TEXT, cover_image TEXT, wechat_media_id TEXT,
                receipt_file TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(year,month)
            );
            INSERT INTO monthly_runs (year,month,status,created_at,updated_at)
            VALUES (2026,9,'FETCHED','2026-09-30','2026-09-30');
        """)
    store = ProductStore(db_path)

    store.init_schema()
    store.init_schema()
    store.upsert_products([
        Product(2026, 9, 2, "Second Kilo Launch", "https://www.producthunt.com/products/kilocode")
    ])

    assert store.count_products(2026, 9) == 2
    assert store.get_monthly_run(2026, 9)["status"] == "FETCHED"
    with store.connect() as conn:
        row = conn.execute("SELECT id,local_image FROM products WHERE rank = 1").fetchone()
    assert (row["id"], row["local_image"]) == (1, "saved.png")
