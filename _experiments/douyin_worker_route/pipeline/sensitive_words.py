"""Sensitive-word regex scanning for replay/performance review.

The scanner only produces review candidates. A hit does not mean the
sentence is illegal or commercially risky without human/context review.
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable



def _runtime_lexicon_path(name: str) -> Path:
    """Use public data next to the compiled package in commercial builds."""
    packaged_root = os.environ.get("LIVEWATCH_PIPELINE_DATA_DIR")
    if packaged_root:
        packaged = Path(packaged_root) / "lexicons" / name
        if packaged.is_file():
            return packaged
    return Path(__file__).resolve().parent / "lexicons" / name


LEXICON_PATH = _runtime_lexicon_path("sensitive_regex_seed.json")
YUNYINGXIA_LEXICON_PATH = _runtime_lexicon_path("yunyingxia_forbidden_words.v1.json")
DEFAULT_SUGGESTION = "仅作为敏感表达复核线索，请结合本场语境确认后再调整话术。"
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
    suggestion: str
    counts_as_risk: bool
    context: str
    context_status: str
    start: int
    end: int


_LEXICON_CACHE: dict[str, Any] | None = None
_PATTERN_CACHE: list[dict[str, Any]] | None = None


def load_lexicon() -> dict[str, Any]:
    global _LEXICON_CACHE
    if _LEXICON_CACHE is None:
        legacy = _read_lexicon_file(LEXICON_PATH)
        operational = _read_lexicon_file(YUNYINGXIA_LEXICON_PATH)
        # The operational library is first so its category, severity and rewrite
        # suggestion take precedence over older seed terms with the same spelling.
        _LEXICON_CACHE = {
            "version": max(int(legacy.get("version") or 0), 1),
            "matching_policy": legacy.get("matching_policy") or {},
            "categories": [
                *_operational_categories(operational),
                *(legacy.get("categories") or []),
            ],
        }
    return _LEXICON_CACHE


def _read_lexicon_file(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _operational_categories(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Adapt the maintained 运营虾 export without hand-copying its terms.

    Low-severity cross-platform mentions remain visible as editorial prompts but
    deliberately do not increase the sensitive-risk total.
    """
    rows: list[dict[str, Any]] = []
    for source in payload.get("categories") or []:
        if not isinstance(source, dict):
            continue
        category_id = str(source.get("category") or "").strip()
        label = str(source.get("label") or category_id or "敏感表达").strip()
        severity = str(source.get("severity") or "medium").strip().lower()
        suggestion = str(source.get("suggestion") or DEFAULT_SUGGESTION).strip()
        terms = [
            {"term": str(word).strip(), "regex": re.escape(str(word).strip())}
            for word in source.get("words") or []
            if str(word).strip()
        ]
        if not terms:
            continue
        rows.append({
            "id": category_id,
            "name": label,
            "default_severity": severity,
            "default_suggestion": suggestion,
            "counts_as_risk": severity != "low",
            "terms": terms,
        })
    return rows


def _patterns() -> list[dict[str, Any]]:
    global _PATTERN_CACHE
    if _PATTERN_CACHE is not None:
        return _PATTERN_CACHE

    rows: list[dict[str, Any]] = []
    seen_terms: set[str] = set()
    for category in load_lexicon().get("categories", []):
        category_id = str(category.get("id") or "")
        category_name = str(category.get("name") or category_id or "敏感词")
        severity = str(category.get("default_severity") or "medium")
        suggestion = str(category.get("default_suggestion") or DEFAULT_SUGGESTION)
        counts_as_risk = bool(category.get("counts_as_risk", severity.lower() != "low"))
        for term in category.get("terms", []):
            label = str(term.get("term") or "").strip()
            pattern = str(term.get("regex") or label).strip()
            if not label or not pattern:
                continue
            term_key = label.casefold()
            if term_key in seen_terms:
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
                "suggestion": str(term.get("suggestion") or suggestion),
                "counts_as_risk": bool(term.get("counts_as_risk", counts_as_risk)),
                "regex": compiled,
            })
            seen_terms.add(term_key)
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
            if not row["counts_as_risk"]:
                context_status = "提示词（不计风险）"
            elif str(row["severity"]).lower() == "high":
                context_status = "高风险候选"
            else:
                context_status = "语境较明确" if _has_context_keyword(context) else "待人工复核"
            hits.append(SensitiveHit(
                term=row["term"],
                category_id=row["category_id"],
                category_name=row["category_name"],
                severity=row["severity"],
                suggestion=row["suggestion"],
                counts_as_risk=row["counts_as_risk"],
                context=context,
                context_status=context_status,
                start=start,
                end=end,
            ))
            occupied.append((start, end))
    return sorted(hits, key=lambda item: item.start)


def summarize_hits(rows: Iterable[dict[str, Any]], *, sample_limit: int = 12) -> dict[str, Any]:
    materialized = list(rows)
    risk_rows = [row for row in materialized if row.get("counts_as_risk", True)]
    advisory_rows = [row for row in materialized if not row.get("counts_as_risk", True)]
    term_counts = Counter(str(row.get("term") or "") for row in risk_rows if row.get("term"))
    category_counts = Counter(str(row.get("category_name") or "") for row in risk_rows if row.get("category_name"))
    severity_counts = Counter(str(row.get("severity") or "medium") for row in risk_rows)
    context_counts = Counter(str(row.get("context_status") or "待人工复核") for row in materialized)

    return {
        "total": len(risk_rows),
        "advisory_total": len(advisory_rows),
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
        "advisory_terms": [
            {"term": term, "count": count}
            for term, count in Counter(
                str(row.get("term") or "") for row in advisory_rows if row.get("term")
            ).most_common(10)
        ],
        "samples": materialized[:sample_limit],
    }


def _has_context_keyword(context: str) -> bool:
    return any(keyword in context for keyword in CONTEXT_KEYWORDS)
