"""Audited rendering and publication for Product Hunt monthly articles."""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ph2md.config import AppPaths
from ph2md.db import ProductStore, validate_month_products
from ph2md.insights import load_insight_plan
from ph2md.lock import monthly_lock, source_lock


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(temporary, path)
            return
        except PermissionError:
            if attempt == 4:
                raise
            time.sleep(0.05 * (attempt + 1))


def audited_products(paths: AppPaths, year: int, month: int, plan: Path | None = None) -> tuple[list, dict]:
    with source_lock(paths.root):
        store = ProductStore(paths.db_path)
        store.init_schema()
        products = store.list_products(year, month)
    validate_month_products(year, month, products)
    if len(products) < 10:
        raise ValueError("Editorial monthly articles require at least 10 source products")
    return products, load_insight_plan(plan or paths.plan_path(year, month), products, year, month)


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _source_sha(products: list) -> str:
    return hashlib.sha256(json.dumps([asdict(product) for product in products], sort_keys=True).encode()).hexdigest()


def render_editorial(paths: AppPaths, year: int, month: int, insights_file: Path | None = None, *, download_images: bool = True) -> Path:
    from ph2md.render import TAIPEI, backup_month_outputs, build_article, build_wechat_html, download_logos, render_cover

    with monthly_lock(paths.root, year, month):
        plan = insights_file or paths.plan_path(year, month)
        products, insights = audited_products(paths, year, month, plan)
        now = datetime.now(TAIPEI)
        backup_month_outputs(paths.root, year, month, backed_up_at=now)
        canonical = paths.plan_path(year, month)
        if plan.resolve() != canonical.resolve():
            if canonical.exists():
                backup = paths.output_dir / "backups" / f"plan_{year}{month:02d}_{now.strftime('%Y%m%d_%H%M%S_%f')}.json"
                backup.parent.mkdir(parents=True, exist_ok=True)
                backup.write_bytes(canonical.read_bytes())
            write_json(canonical, json.loads(plan.read_text(encoding="utf-8")))
        logos = download_logos(products, paths.cover_path(year, month).parent / "logos") if download_images else {}
        render_cover(paths.cover_path(year, month), year, month, products)
        markdown = paths.markdown_path(year, month)
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_text(build_article(products, logos, year, month, insights, published_at=now), encoding="utf-8")
        markdown.with_suffix(".html").write_text(build_wechat_html(products, logos, year, month, insights), encoding="utf-8")
        write_json(paths.receipts_dir / f"render_{year}{month:02d}.json", {"plan_sha256": _sha(canonical), "source_sha256": _source_sha(products), "markdown_sha256": _sha(markdown), "logos": {str(rank): {"path": str(path.resolve()), "sha256": _sha(path)} for rank, path in logos.items()}, "generated_at": now.isoformat()})
        ProductStore(paths.db_path).upsert_monthly_run(year, month, "RENDERED")
        return markdown


def run_editorial_publish(paths: AppPaths, year: int, month: int, *, cover_image: Path | None = None, preview: bool = False, config_path: Path | None = None) -> str | None:
    from publisher_shared.wechat import preview_article, publish_article

    with monthly_lock(paths.root, year, month):
        store = ProductStore(paths.db_path)
        store.init_schema()
        receipt_path = paths.receipts_dir / f"publish_{year}{month:02d}.json"
        if not preview:
            run = store.get_monthly_run(year, month) or {}
            if run.get("wechat_media_id"):
                if run.get("status") == "PUBLISH_UNVERIFIED":
                    raise RuntimeError(f"Known draft Media ID: {run['wechat_media_id']}; remote verification remains unresolved; no upload performed")
                return str(run["wechat_media_id"])
            if receipt_path.exists():
                previous = json.loads(receipt_path.read_text(encoding="utf-8"))
                if previous.get("media_id"):
                    media_id = str(previous["media_id"])
                    verified = previous.get("status") in {"confirmed", "published"} and previous.get("verified", True)
                    store.record_wechat_draft(year, month, media_id, str(previous.get("markdown_file", paths.markdown_path(year, month))), str(previous.get("cover_image", cover_image or paths.cover_path(year, month))), str(receipt_path), verified=verified)
                    if not verified:
                        raise RuntimeError(f"Known draft Media ID: {media_id}; remote verification remains unresolved; no upload performed")
                    return media_id
                raise RuntimeError(f"Prior upload outcome is uncertain; inspect WeChat drafts before retrying: {receipt_path}")
        products, _ = audited_products(paths, year, month)
        markdown = paths.markdown_path(year, month).resolve()
        cover = (cover_image or paths.cover_path(year, month)).resolve()
        for path in (markdown, cover):
            if not path.is_file():
                raise FileNotFoundError(path)
        manifest = paths.receipts_dir / f"render_{year}{month:02d}.json"
        if not manifest.exists():
            raise ValueError("Article has no rendering receipt; run render before preview/publish")
        fingerprint = json.loads(manifest.read_text(encoding="utf-8"))
        if fingerprint.get("plan_sha256") != _sha(paths.plan_path(year, month)) or fingerprint.get("source_sha256") != _source_sha(products) or fingerprint.get("markdown_sha256") != _sha(markdown):
            raise ValueError("Plan, source, or article changed after render; run render before preview/publish")
        logos = fingerprint.get("logos", {})
        if set(logos) != {str(product.rank) for product in products[:10]}:
            raise ValueError("Preview/publish requires all Top 10 product images; render without --skip-logos")
        for logo in logos.values():
            image = Path(logo["path"])
            if not image.is_file() or _sha(image) != logo["sha256"]:
                raise ValueError("Product image changed or missing after render; run render before preview/publish")
        if preview:
            if not preview_article(markdown, cover, config_path=config_path):
                raise ValueError("WeChat local preview failed")
            return None
        payload = {"year": year, "month": month, "status": "attempting", "markdown_file": str(markdown), "cover_image": str(cover), "started_at": datetime.now(UTC).isoformat()}
        write_json(receipt_path, payload)
        try:
            result = publish_article(markdown, cover, config_path=config_path)
            media_id = result.media_id
            if not media_id:
                raise RuntimeError("WeChat returned no Media ID")
            payload.update(status="confirmed" if result.verified else "uncertain", media_id=media_id, verified=result.verified)
            write_json(receipt_path, payload)
            store.record_wechat_draft(year, month, media_id, str(markdown), str(cover), str(receipt_path), verified=result.verified)
            if not result.verified:
                raise RuntimeError("Draft created, but remote verification failed; Media ID retained")
            return media_id
        except Exception as exc:
            media_id = getattr(exc, "media_id", None) or payload.get("media_id")
            payload.update(status="uncertain", error=str(exc))
            if media_id:
                payload["media_id"] = media_id
            write_json(receipt_path, payload)
            if media_id:
                store.record_wechat_draft(year, month, str(media_id), str(markdown), str(cover), str(receipt_path), verified=False)
            raise
