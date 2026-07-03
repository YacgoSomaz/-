"""Sensitive-word regex scanning for replay/performance review.

The scanner only produces review candidates. A hit does not mean the
sentence is illegal or commercially risky without human/context review.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


LEXICON_PATH = Path(__file__).resolve().parent / "lexicons" / "sensitive_regex_seed.json"
CONTEXT_KEYWORDS = (
    "产品", "价格", "优惠", "活动", "销量", "效果", "功效", "质量", "品质", "保证",
    "承诺", "官方", "认证", "平台", "品牌", "房", "楼盘", "户型", "公摊", "下单",
    "链接", "购买", "售后", "正品", "最低", "最高", "最好", "最大", "第一",
)


@dataclass(frozen=True)
class SensitiveHit:
    term: str
    category_id: str
    category_name: str
    severity: str
    context: str
    context_status: str
    start: int
    end: int


_LEXICON_CACHE: dict[str, Any] | None = None
_PATTERN_CACHE: list[dict[str, Any]] | None = None


def load_lexicon() -> dict[str, Any]:
    global _LEXICON_CACHE
    if _LEXICON_CACHE is None:
        try:
            _LEXICON_CACHE = json.loads(LEXICON_PATH.read_text(encoding="utf-8"))
        except FileNotFoundError:
            _LEXICON_CACHE = {"version": 0, "categories": []}
    return _LEXICON_CACHE


def _patterns() -> list[dict[str, Any]]:
    global _PATTERN_CACHE
    if _PATTERN_CACHE is not None:
        return _PATTERN_CACHE

    rows: list[dict[str, Any]] = []
    for category in load_lexicon().get("categories", []):
        category_id = str(category.get("id") or "")
        category_name = str(category.get("name") or category_id or "敏感词")
        severity = str(category.get("default_severity") or "medium")
        for term in category.get("terms", []):
            label = str(term.get("term") or "").strip()
            pattern = str(term.get("regex") or label).strip()
            if not label or not pattern:
                continue
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error:
                compiled = re.compile(re.escape(label), re.IGNORECASE)
            rows.append({
                "term": label,
                "category_id": category_id,
                "category_name": category_name,
                "severity": severity,
                "regex": compiled,
            })
    # Longer terms first avoids showing both "认证" and "平台认证" for the same span.
    rows.sort(key=lambda item: len(str(item["term"])), reverse=True)
    _PATTERN_CACHE = rows
    return rows


def scan_text(text: str, *, context_window: int | None = None) -> list[SensitiveHit]:
    text = text or ""
    if not text:
        return []
    window = context_window
    if window is None:
        window = int(load_lexicon().get("matching_policy", {}).get("context_window_chars") or 30)

    hits: list[SensitiveHit] = []
    occupied: list[tuple[int, int]] = []
    for row in _patterns():
        for match in row["regex"].finditer(text):
            start, end = match.span()
            if any(not (end <= used_start or start >= used_end) for used_start, used_end in occupied):
                continue
            left = max(0, start - window)
            right = min(len(text), end + window)
            context = text[left:right].strip()
            context_status = "语境较明确" if _has_context_keyword(context) else "待人工复核"
            hits.append(SensitiveHit(
                term=row["term"],
                category_id=row["category_id"],
                category_name=row["category_name"],
                severity=row["severity"],
                context=context,
                context_status=context_status,
                start=start,
                end=end,
            ))
            occupied.append((start, end))
    return sorted(hits, key=lambda item: item.start)


def summarize_hits(rows: Iterable[dict[str, Any]], *, sample_limit: int = 12) -> dict[str, Any]:
    materialized = list(rows)
    term_counts = Counter(str(row.get("term") or "") for row in materialized if row.get("term"))
    category_counts = Counter(str(row.get("category_name") or "") for row in materialized if row.get("category_name"))
    severity_counts = Counter(str(row.get("severity") or "medium") for row in materialized)
    context_counts = Counter(str(row.get("context_status") or "待人工复核") for row in materialized)

    return {
        "total": len(materialized),
        "unique_terms": len(term_counts),
        "by_severity": dict(severity_counts),
        "by_context_status": dict(context_counts),
        "by_category": [
            {"category": category, "count": count}
            for category, count in category_counts.most_common()
        ],
        "top_terms": [
            {"term": term, "count": count}
            for term, count in term_counts.most_common(10)
        ],
        "samples": materialized[:sample_limit],
    }


def _has_context_keyword(context: str) -> bool:
    return any(keyword in context for keyword in CONTEXT_KEYWORDS)
