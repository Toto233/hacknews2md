from __future__ import annotations

from typing import Any

from ph2md.db import ProductStore


def set_run_status(
    store: ProductStore,
    year: int,
    month: int,
    status: str,
    receipt_file: str | None = None,
) -> None:
    store.upsert_monthly_run(year, month, status, receipt_file=receipt_file)


def get_run_status(store: ProductStore, year: int, month: int) -> dict[str, Any] | None:
    return store.get_monthly_run(year, month)
