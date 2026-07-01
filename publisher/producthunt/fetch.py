from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import httpx

from publisher.producthunt.extractor import parse_leaderboard_html
from publisher.producthunt.models import FetchResult
from src.security.url_validator import validate_url

PRODUCTHUNT_HOST = "www.producthunt.com"


class FetchError(RuntimeError):
    pass


def build_leaderboard_url(year: int, month: int) -> str:
    return f"https://{PRODUCTHUNT_HOST}/leaderboard/monthly/{year}/{month}"


def fetch_leaderboard(
    year: int,
    month: int,
    limit: int = 25,
    transport: httpx.BaseTransport | None = None,
    debug_dir: Path | None = None,
) -> FetchResult:
    url = build_leaderboard_url(year, month)
    try:
        validate_url(url)
    except Exception as exc:
        raise FetchError(str(exc)) from exc
    if urlparse(url).hostname != PRODUCTHUNT_HOST:
        raise FetchError(f"invalid Product Hunt host: {url}")

    try:
        with httpx.Client(
            timeout=20,
            follow_redirects=True,
            transport=transport,
            headers={
                "User-Agent": "hn2md-producthunt/0.1 (+https://www.producthunt.com)",
                "Accept": "text/html,application/xhtml+xml",
            },
        ) as client:
            response = client.get(url)
            response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        raise FetchError(f"Product Hunt returned HTTP {status}") from exc
    except httpx.HTTPError as exc:
        raise FetchError(f"Product Hunt request failed: {exc}") from exc

    products = parse_leaderboard_html(response.text, year=year, month=month, limit=limit)
    warnings: list[dict[str, str]] = []
    if not products:
        warning = {"reason": "no_products_parsed"}
        if debug_dir is not None:
            debug_path = _write_debug_html(debug_dir, year, month, response.text)
            warning["debug_html"] = str(debug_path)
        warnings.append(warning)
    return FetchResult(year=year, month=month, url=url, products=products, warnings=warnings)


def fetch_leaderboard_from_html_file(html_file: Path, year: int, month: int, limit: int = 25) -> FetchResult:
    html = html_file.read_text(encoding="utf-8")
    products = parse_leaderboard_html(html, year=year, month=month, limit=limit)
    warnings: list[dict[str, str]] = []
    if not products:
        warnings.append({"reason": "no_products_parsed", "debug_html": str(html_file)})
    return FetchResult(
        year=year,
        month=month,
        url=f"file:{html_file.as_posix()}",
        products=products,
        warnings=warnings,
    )


def _write_debug_html(debug_dir: Path, year: int, month: int, html: str) -> Path:
    debug_dir.mkdir(parents=True, exist_ok=True)
    debug_path = debug_dir / f"leaderboard_{year}{month:02d}.html"
    debug_path.write_text(html, encoding="utf-8")
    return debug_path
