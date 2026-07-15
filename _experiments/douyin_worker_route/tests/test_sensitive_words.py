from __future__ import annotations


def test_operational_lexicon_marks_hard_diversion_and_finance_terms_as_high_risk_candidates() -> None:
    from pipeline import sensitive_words

    hits = {hit.term: hit for hit in sensitive_words.scan_text("直播间扫码添加，稳赚不赔。")}

    diversion = hits["扫码添加"]
    finance = hits["稳赚"]
    assert diversion.category_id == "diversion"
    assert diversion.severity == "high"
    assert diversion.counts_as_risk is True
    assert diversion.context_status == "高风险候选"
    assert "站外导流" in diversion.suggestion
    assert finance.category_id == "finance"
    assert finance.counts_as_risk is True


def test_cross_platform_mentions_are_advisories_not_risk_totals() -> None:
    from pipeline import sensitive_words

    hit = next(hit for hit in sensitive_words.scan_text("这个内容也会同步到小红书") if hit.term == "小红书")
    summary = sensitive_words.summarize_hits([
        {
            "term": hit.term,
            "category_name": hit.category_name,
            "severity": hit.severity,
            "context_status": hit.context_status,
            "counts_as_risk": hit.counts_as_risk,
        }
    ])

    assert hit.counts_as_risk is False
    assert hit.context_status == "提示词（不计风险）"
    assert summary["total"] == 0
    assert summary["advisory_total"] == 1
