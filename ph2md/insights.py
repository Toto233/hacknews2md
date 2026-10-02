from __future__ import annotations

import json
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from ph2md.models import Product


MIN_TEXT_LENGTH = 32
MAX_TEXT_LENGTH = 180
MIN_REPEATED_FRAGMENT = 18
MAX_SIMILARITY = 0.78

BANNED_PHRASES = (
    "排名靠前说明这个痛点在 PH 社区有明确需求",
    "后续要看是否有真实使用数据支撑，而不只是概念包装",
    "值得注意的是",
    "不难看出",
)


@dataclass(frozen=True)
class ProductInsight:
    rank: int
    name: str
    producthunt_url: str
    observation: str
    risk: str


class InsightPlanError(ValueError):
    """Raised when a Product Hunt editorial plan fails a publish gate."""


def load_insight_plan(
    plan_path: Path,
    products: list[Product],
    year: int,
    month: int,
) -> dict[int, ProductInsight]:
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InsightPlanError(f"cannot read insight plan {plan_path}: {exc}") from exc

    findings = audit_insight_plan(payload, products, year, month)
    if findings:
        details = "\n".join(f"- {finding}" for finding in findings)
        raise InsightPlanError(f"Product Hunt insight plan failed audit:\n{details}")

    return {
        int(item["rank"]): ProductInsight(
            rank=int(item["rank"]),
            name=str(item["name"]).strip(),
            producthunt_url=str(item["producthunt_url"]).strip(),
            observation=str(item["observation"]).strip(),
            risk=str(item["risk"]).strip(),
        )
        for item in payload["items"]
    }


def audit_insight_plan(
    payload: object,
    products: list[Product],
    year: int,
    month: int,
) -> list[str]:
    findings: list[str] = []
    if not isinstance(payload, dict):
        return ["plan root must be a JSON object"]
    if payload.get("year") != year or payload.get("month") != month:
        findings.append(f"plan period must be {year}-{month:02d}")

    raw_items = payload.get("items")
    if not isinstance(raw_items, list):
        return findings + ["items must be a JSON array"]

    expected_products = products[:10]
    expected_by_rank = {product.rank: product for product in expected_products}
    seen_ranks: set[int] = set()
    insights: list[ProductInsight] = []

    for index, item in enumerate(raw_items):
        label = f"items[{index}]"
        if not isinstance(item, dict):
            findings.append(f"{label} must be an object")
            continue
        try:
            rank = int(item.get("rank"))
        except (TypeError, ValueError):
            findings.append(f"{label}.rank must be an integer")
            continue
        if rank in seen_ranks:
            findings.append(f"rank {rank} appears more than once")
            continue
        seen_ranks.add(rank)
        product = expected_by_rank.get(rank)
        if product is None:
            findings.append(f"rank {rank} is not in the current Top 10")
            continue

        name = str(item.get("name") or "").strip()
        producthunt_url = str(item.get("producthunt_url") or "").strip()
        observation = str(item.get("observation") or "").strip()
        risk = str(item.get("risk") or "").strip()
        if name != _clean_name(product.name):
            findings.append(f"rank {rank} name does not match source product")
        if producthunt_url != product.producthunt_url:
            findings.append(f"rank {rank} Product Hunt URL does not match source")
        _audit_text(findings, rank, "observation", observation)
        _audit_text(findings, rank, "risk", risk)
        insights.append(ProductInsight(rank, name, producthunt_url, observation, risk))

    missing_ranks = sorted(set(expected_by_rank) - seen_ranks)
    if missing_ranks:
        findings.append(f"missing Top 10 ranks: {missing_ranks}")
    if len(raw_items) != len(expected_products):
        findings.append(f"items must contain exactly {len(expected_products)} Top 10 entries")

    findings.extend(_audit_repetition(insights, "observation"))
    findings.extend(_audit_repetition(insights, "risk"))
    return findings


def draft_plan_payload(products: list[Product], year: int, month: int) -> dict[str, object]:
    return {
        "year": year,
        "month": month,
        "items": [
            {
                "rank": product.rank,
                "name": _clean_name(product.name),
                "producthunt_url": product.producthunt_url,
                "tagline": product.tagline or "",
                "categories": product.categories,
                "votes": product.votes or 0,
                "comments": product.comments or 0,
                "observation": "",
                "risk": "",
            }
            for product in products[:10]
        ],
    }


def _audit_text(findings: list[str], rank: int, field: str, value: str) -> None:
    if len(value) < MIN_TEXT_LENGTH:
        findings.append(f"rank {rank} {field} is shorter than {MIN_TEXT_LENGTH} characters")
    if len(value) > MAX_TEXT_LENGTH:
        findings.append(f"rank {rank} {field} is longer than {MAX_TEXT_LENGTH} characters")
    for phrase in BANNED_PHRASES:
        if phrase in value:
            findings.append(f"rank {rank} {field} contains banned fallback phrase: {phrase}")


def _audit_repetition(insights: list[ProductInsight], field: str) -> list[str]:
    findings: list[str] = []
    for left_index, left in enumerate(insights):
        left_text = _normalize(getattr(left, field))
        if not left_text:
            continue
        for right in insights[left_index + 1 :]:
            right_text = _normalize(getattr(right, field))
            if not right_text:
                continue
            similarity = SequenceMatcher(None, left_text, right_text).ratio()
            if similarity >= MAX_SIMILARITY:
                findings.append(
                    f"{field} for ranks {left.rank} and {right.rank} is too similar ({similarity:.0%})"
                )
                continue
            match = SequenceMatcher(None, left_text, right_text).find_longest_match()
            if match.size >= MIN_REPEATED_FRAGMENT:
                fragment = left_text[match.a : match.a + match.size]
                findings.append(
                    f"{field} for ranks {left.rank} and {right.rank} repeats a long phrase: {fragment}"
                )
    return findings


def _normalize(value: str) -> str:
    return re.sub(r"[\s，。；：、“”‘’（）()《》！？!?·—-]+", "", value).lower()


def _clean_name(value: str) -> str:
    return value.replace("\xa0", " ").strip()
