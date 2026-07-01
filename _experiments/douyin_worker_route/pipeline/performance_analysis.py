"""AI-led直播效能分析。

Python 只负责证据整理、状态门禁和结构化校验；直播效能分由 AI 在直播结束后
基于完整本地数据给出。触发条件：

1. 单场有效直播时长 >= 15 分钟；
2. 最近录音/转写/统计数据稳定超过 5 分钟，视为已下播或采集结束；
3. AI 配置可用。

不引入 GMV、订单、ROI 或成交归因。
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from statistics import mean, pstdev
from typing import Any

from . import ai_report, config, export


STABLE_AFTER_SEC = 5 * 60
MIN_AI_DURATION_SEC = 15 * 60
ANALYSIS_TEMPLATE = "auto"
ANALYSIS_PROMPT_VERSION = "2026-07-01-content-quality-neutral-v4"
MAX_TRANSCRIPT_CHARS = 120_000
MAX_CHAT_ROWS = 1_500
MAX_STAT_ROWS = 240
FORBIDDEN_BUSINESS_TERMS = ("GMV", "ROI", "订单", "成交归因", "成交额", "销售额")
FORBIDDEN_DECISION_PHRASES = (
    ("建议合作", "效能表现可关注"),
    ("不建议合作", "效能表现偏弱"),
    ("暂不建议合作", "效能表现偏弱"),
    ("谨慎合作", "需谨慎解读分数"),
    ("合作优先池", "重点观察池"),
    ("进入合作池", "进入观察池"),
    ("合作潜力", "直播效能"),
)

QUESTION_TERMS = (
    "多少钱", "价格", "怎么卖", "怎么买", "链接", "拍哪个", "优惠", "券",
    "发货", "多久", "售后", "退", "适合", "怎么选", "地址", "运费",
)
INTENT_TERMS = (
    "多少钱", "怎么买", "链接在哪", "拍哪个", "有没有优惠", "发货多久",
    "适合我吗", "已经拍了", "还有吗", "能不能便宜", "下单", "库存",
)
NEGATIVE_TERMS = ("不好", "太贵", "假的", "骗人", "退货", "投诉", "没用", "差评", "不行")
COMMERCE_CONTEXT_TERMS = (
    "产品", "价格", "优惠", "下单", "拍", "链接", "买", "购买", "发货", "售后",
    "效果", "功效", "改善", "保证", "承诺", "全网", "活动", "券", "正品",
    "官方", "最低价", "质量", "品质", "美白", "瘦", "减肥", "食品", "药",
)
ENTERTAINMENT_CONTEXT_TERMS = (
    "唱", "歌", "歌词", "跳舞", "音乐", "笑", "哈哈", "开玩笑", "游戏", "PK", "主播",
    "陪伴", "聊天", "气氛",
)
RISK_RULES = (
    ("站外引流敏感词", "中", ("加微信", "微信", "私信我", "站外", "二维码", "手机号", "电话联系")),
    ("医疗功效敏感词", "高", ("治疗", "治愈", "疗效", "祛病", "药效", "包治", "马上见效", "一定能瘦")),
    ("价格承诺敏感词", "中", ("全网最低", "官方最低价", "百分百保价", "无效退款", "永久保证")),
    ("攻击低俗敏感词", "中", ("傻", "滚", "垃圾", "蠢", "闭嘴")),
)


@dataclass(frozen=True)
class MetricSnapshot:
    duration_sec: float
    recorded_duration: float
    transcribed_duration: float
    completeness: float
    danmu_count: int
    event_total: int
    peak_online: int
    avg_online: float
    latest_online: int
    total_viewers: int
    like_events: int
    follow_events: int
    enter_events: int
    fansclub_events: int
    question_count: int
    intent_count: int
    negative_count: int
    transcript_chars: int
    speech_density: float
    danmu_per_min: float
    like_per_min: float
    intent_ratio: float
    online_stability: float
    high_value_member_events: int
    gift_events: int
    disconnect_count: int
    short_segment_count: int
    broken_segment_count: int
    failed_transcripts: int


def list_session_summaries() -> list[dict[str, Any]]:
    """效能分析首页。当前按直播号聚合为一场可分析直播。"""
    names = export.room_display_names()
    rows: list[dict[str, Any]] = []
    for rid in export.export_room_ids():
        try:
            bundle = export.build_bundle(str(rid), names.get(str(rid), ""))
            rows.append(_build_from_bundle(bundle, include_detail=False))
        except Exception as exc:  # noqa: BLE001 页面不能因单房间脏数据崩掉
            rows.append(_error_row(str(rid), names.get(str(rid), ""), exc))
    rows.sort(key=_sort_key, reverse=True)
    return rows


def build_session_analysis(rid: str, *, include_detail: bool = True) -> dict[str, Any]:
    names = export.room_display_names()
    rid = str(rid)
    bundle = export.build_bundle(rid, names.get(rid, ""))
    return _build_from_bundle(bundle, include_detail=include_detail)


def analyze_room(rid: str, *, force: bool = False) -> dict[str, Any]:
    """对单个已稳定直播执行 AI 效能分析并保存结果。"""
    names = export.room_display_names()
    rid = str(rid)
    bundle = export.build_bundle(rid, names.get(rid, ""))
    base = _build_from_bundle(bundle, include_detail=True)
    status = base.get("analysis_status")
    if status == "done" and not force:
        return base
    if status not in {"ready", "stale", "failed"} and not force:
        return base
    if status in {"not_eligible_short", "data_insufficient", "waiting_stable"}:
        return base

    evidence_hash, evidence = _evidence_pack(bundle, _metrics(bundle))
    cfg = ai_report.load_config()
    if not cfg.ready:
        _save_analysis(
            rid,
            evidence_hash,
            "ai_not_configured",
            None,
            "AI 尚未配置，请先在系统设置里填写 base_url、API Key 和模型名。",
        )
        return _build_from_bundle(bundle, include_detail=True)

    _save_analysis(rid, evidence_hash, "analyzing", None, "")
    try:
        raw = ai_report._chat_completion(
            cfg,
            _analysis_messages(evidence),
            temperature=0.15,
            max_tokens=3_200,
            response_format={"type": "json_object"},
        )
        parsed = ai_report._json_from_text(raw)
        normalized = _normalize_ai_result(parsed)
        _save_analysis(rid, evidence_hash, "done", normalized, "")
    except Exception as exc:  # noqa: BLE001 保存失败状态，便于前端展示和重试
        _save_analysis(rid, evidence_hash, "failed", None, str(exc))
    return _build_from_bundle(bundle, include_detail=True)


def analyze_ready_sessions(*, limit: int = 1) -> dict[str, Any]:
    """后台/按钮调用：自动分析已结束且稳定的直播，避免页面 GET 阻塞。"""
    names = export.room_display_names()
    analyzed: list[str] = []
    skipped: list[dict[str, str]] = []
    for rid in export.export_room_ids():
        if len(analyzed) >= limit:
            break
        try:
            bundle = export.build_bundle(str(rid), names.get(str(rid), ""))
            row = _build_from_bundle(bundle, include_detail=False)
            if row.get("analysis_status") in {"ready", "stale", "failed"}:
                result = analyze_room(str(rid), force=row.get("analysis_status") == "failed")
                if result.get("analysis_status") == "done":
                    analyzed.append(str(rid))
                else:
                    skipped.append({"rid": str(rid), "reason": str(result.get("analysis_status_text") or "")})
            else:
                skipped.append({"rid": str(rid), "reason": str(row.get("analysis_status_text") or "")})
        except Exception as exc:  # noqa: BLE001
            skipped.append({"rid": str(rid), "reason": str(exc)})
    return {"analyzed": analyzed, "skipped": skipped}


def _build_from_bundle(bundle: export.RoomBundle, *, include_detail: bool) -> dict[str, Any]:
    metrics = _metrics(bundle)
    risks = _risk_segments(bundle)
    frequent_questions = _frequent_questions(bundle)
    data_insufficient, data_reason = _data_insufficient(metrics)
    evidence_hash, _ = _evidence_pack(bundle, metrics)
    saved = _load_analysis(str(bundle.rid))
    status, status_text = _readiness_status(metrics, bundle, data_insufficient, data_reason, evidence_hash, saved)
    ai_result = saved.get("result") if saved and saved.get("status") == "done" and saved.get("evidence_hash") == evidence_hash else None
    normalized = _normalize_ai_result(ai_result or {}) if ai_result else None

    start_ts, end_ts = _session_range(bundle)
    confidence = _confidence(metrics.completeness)
    data_integrity = {
        "total_duration": round(metrics.duration_sec, 1),
        "recorded_duration": round(metrics.recorded_duration, 1),
        "transcribed_duration": round(metrics.transcribed_duration, 1),
        "danmu_count": metrics.danmu_count,
        "disconnect_count": metrics.disconnect_count,
        "short_segment_count": metrics.short_segment_count,
        "broken_segment_count": metrics.broken_segment_count,
        "failed_transcripts": metrics.failed_transcripts,
        "completeness": round(metrics.completeness, 3),
        "confidence": confidence,
    }

    if normalized:
        overall = normalized["final_score"]
        score_available = overall is not None
        rating = str(normalized["rating"])
        summary = str(normalized["ai_summary"])
        positive_score = normalized["positive_score"]
        risk_deduction = normalized["risk_deduction"]
        data_missing_deduction = normalized["data_missing_deduction"]
        recommendation = _recommendation(rating, normalized.get("suggestions") or [])
        track = normalized["track"]
        score_template = normalized["template"]
        dimensions = normalized["dimensions"]
        risk_review = normalized["risk_review"]
        positives = normalized["key_positive_reasons"]
        deductions = normalized["key_deduction_reasons"]
        ai_confidence = normalized["confidence"]
    else:
        overall = None
        score_available = False
        rating = "数据不足" if status in {"data_insufficient", "not_eligible_short"} else "待分析"
        summary = status_text
        positive_score = None
        risk_deduction = None
        data_missing_deduction = None
        recommendation = ""
        track = "待AI识别"
        score_template = "待AI选择"
        dimensions = []
        risk_review = []
        positives = _key_positive_reasons(metrics)
        deductions = [status_text] if status_text else _key_deduction_reasons(metrics, risks, data_reason)
        ai_confidence = confidence

    row = {
        "session_id": str(bundle.rid),
        "rid": str(bundle.rid),
        "anchor_name": bundle.nickname or str(bundle.rid),
        "avatar_url": "",
        "live_start": _fmt_dt(start_ts),
        "live_end": _fmt_dt(end_ts),
        "live_time": _fmt_range(start_ts, end_ts),
        "duration_sec": round(metrics.duration_sec, 1),
        "duration_text": _fmt_duration(metrics.duration_sec),
        "monitor_completeness": round(metrics.completeness * 100),
        "score_available": score_available,
        "score_source": "ai" if normalized else "pending",
        "score_template": score_template,
        "track": track,
        "data_status": _data_status(status),
        "data_status_reason": data_reason or status_text,
        "analysis_status": status if not normalized else "done",
        "analysis_status_text": "AI已完成效能分析" if normalized else status_text,
        "analysis_updated_at": _fmt_dt(saved.get("updated_ts")) if saved else "",
        "evidence_hash": evidence_hash,
        "positive_score": positive_score,
        "risk_deduction": risk_deduction,
        "data_missing_deduction": data_missing_deduction,
        "risk_hard_cap": None,
        "severe_risk_count": sum(1 for r in risks if r.get("risk_level") in {"高", "严重"}),
        "overall_score": overall,
        "rating": rating,
        "recommendation": recommendation,
        "risk_count": len(risks),
        "frequent_question_count": len(frequent_questions),
        "ai_confidence": ai_confidence,
        "ai_summary": summary,
        "transcribed": bool(bundle.transcripts),
        "analysis_generated": bool(normalized),
        "data_integrity": data_integrity,
        "metrics": _metrics_dict(metrics),
        "key_positive_reasons": positives,
        "key_deduction_reasons": deductions,
    }
    if include_detail:
        row.update({
            "dimensions": dimensions,
            "risk_review": risk_review,
            "highlight_segments": _highlight_segments(bundle),
            "low_efficiency_segments": _low_efficiency_segments(bundle),
            "risk_segments": risks,
            "frequent_questions": frequent_questions,
            "high_intent_danmu": _high_intent_danmu(bundle),
            "negative_feedback": _negative_feedback(bundle),
            "unanswered_questions": _unanswered_questions(bundle, frequent_questions),
            "suggestions": normalized.get("suggestions", []) if normalized else [],
        })
    return row


def _readiness_status(
    metrics: MetricSnapshot,
    bundle: export.RoomBundle,
    insufficient: bool,
    insufficient_reason: str,
    evidence_hash: str,
    saved: dict[str, Any] | None,
) -> tuple[str, str]:
    if insufficient:
        return "data_insufficient", insufficient_reason or "暂无足够数据，请先完成监听、转写或弹幕采集。"
    if metrics.duration_sec < MIN_AI_DURATION_SEC:
        return "not_eligible_short", "单场直播时间未超过 15 分钟，暂不采用 AI 效能分析。"
    latest = _latest_data_ts(bundle)
    quiet_sec = time.time() - latest if latest else 0
    if latest and quiet_sec < STABLE_AFTER_SEC:
        return "waiting_stable", f"等待直播结束：最近仍有录音或转写落袋，需稳定 5 分钟后自动分析。"
    if saved and saved.get("status") == "done" and saved.get("evidence_hash") == evidence_hash:
        return "done", "AI已完成效能分析"
    if saved and saved.get("status") == "failed":
        return "failed", str(saved.get("error") or "上次 AI 分析失败，可重新分析。")
    if saved and saved.get("status") == "analyzing":
        return "analyzing", "AI正在分析这场直播，请稍候。"
    if saved and saved.get("evidence_hash") and saved.get("evidence_hash") != evidence_hash:
        return "stale", "采集数据已有更新，建议重新生成 AI 效能分析。"
    return "ready", "直播已结束且稳定超过 5 分钟，可以开始 AI 效能分析。"


def _analysis_messages(evidence: dict[str, Any]) -> list[dict[str, str]]:
    schema = {
        "track": "带货型直播|娱乐/聊天型直播|游戏/内容型直播|未分类",
        "template": "带货型直播|娱乐/聊天型直播|游戏/内容型直播|通用模板",
        "positive_score": "0-100",
        "risk_deduction": "0-20",
        "data_missing_deduction": "0-10",
        "final_score": "0-100 或 null",
        "rating": "优秀|良好|一般|较弱|低分|数据不足",
        "ai_summary": "80-180字中文结论",
        "key_positive_reasons": ["关键加分原因"],
        "key_deduction_reasons": ["关键扣分原因"],
        "dimensions": [{"name": "维度名", "score": 0, "max_score": 0, "reason": "必须引用证据"}],
        "risk_review": [{"risk_type": "风险类型", "level": "轻微|中等|严重|待复核", "is_real_risk": True, "deduction": 0, "evidence": "原话", "reason": "判断原因"}],
        "suggestions": ["中性的复盘观察点，不允许出现建议合作或不建议合作"],
        "confidence": "高|中|低",
    }
    system = (
        "你是「直播复盘侠」的效能分析智能体。你必须亲自阅读证据包中的直播数据、"
        "话术、弹幕、统计和事件，再判断直播赛道、评分模板和直播效能分。"
        "Python 只负责提供证据，不允许你照搬机械权重，也不允许输出合作建议。"
        "评分公式必须是：直播效能分 = 内容与互动效能分 - 敏感词扣分 - 数据缺失扣分。"
        "风险合规只按证据包里的敏感词候选处理，不要自行扩大为违规判断；数据不足时 final_score 必须为 null。"
        "注意：能进入本分析的直播已经通过时长和稳定性门禁，原则上必须给出 final_score；"
        "互动少、弹幕少、无人提问、无购买意图只能作为效能弱项，不能直接判为数据不足。"
        "只有证据包几乎没有话术、弹幕、统计和时间信息时，才允许 rating=数据不足 且 final_score=null。"
        "内容质量必须占分数大头：请重点评估主播话术是否连续、信息是否清楚、节奏是否稳定、"
        "是否能承接弹幕、是否有有效互动引导、是否有可复用表达。观看热度和互动数据是重要辅助，"
        "但不能替代内容质量本身。"
        "赛道权重必须区别处理："
        "1）娱乐/聊天型直播：内容氛围、陪伴感、才艺/聊天连续性、弹幕密度、粉丝团/social 和强关系互动优先，人数热度权重较低。"
        "2）带货型直播：商品讲解质量、卖点清晰度、疑虑回应、行动引导和话术承接优先；人数、进场/member、峰值在线、累计观看和热度权重较高，但仍服务于内容转化力判断。"
        "3）游戏/内容型直播：内容持续性、讨论度、控场、高光片段和粉丝粘性优先，人数和热度中等权重。"
        "不要引入 GMV、订单、ROI、成交归因、销售额等概念；「已经拍了」只能当用户反馈。"
        "低信息片段只是候选线索，可能来自沉默、音乐、ASR漏识别或主播停顿，不能直接认定为低效。"
        "敏感词片段只做复核提示，扣分应轻，除非证据中明确出现站外引流、医疗功效、价格承诺等敏感词。"
        "禁止输出「建议合作」「不建议合作」「进入合作池」「合作优先」等替用户做选择的结论；只输出分数、评级和证据。"
        "只输出合法 JSON。"
    )
    user = (
        "请基于以下完整证据包进行 AI 效能分析。输出必须符合这个 JSON schema：\n"
        + json.dumps(schema, ensure_ascii=False)
        + "\n\n证据包：\n"
        + json.dumps(evidence, ensure_ascii=False, default=str)
    )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def _evidence_pack(bundle: export.RoomBundle, metrics: MetricSnapshot) -> tuple[str, dict[str, Any]]:
    transcript_rows: list[dict[str, Any]] = []
    used_chars = 0
    transcript_truncated = False
    for t in sorted(bundle.transcripts, key=lambda x: (x.capture_start or x.segment_ts or 0)):
        text = (t.text or "").strip()
        if not text:
            continue
        if used_chars + len(text) > MAX_TRANSCRIPT_CHARS:
            transcript_truncated = True
            break
        used_chars += len(text)
        transcript_rows.append({
            "start": _fmt_dt(t.capture_start or t.segment_ts),
            "end": _fmt_dt(t.capture_end or ((t.capture_start or t.segment_ts) + (t.duration_sec or 0))),
            "duration_sec": t.duration_sec,
            "speaker": getattr(t, "speaker_label", "") or "",
            "audio": t.mp3_name,
            "text": text,
        })
    chat_rows = [
        {"user": user, "content": content}
        for user, content in (bundle.chats or [])[:MAX_CHAT_ROWS]
        if content
    ]
    stat_rows = [
        {"time": _fmt_dt(ts), "online": cur, "total_viewers": pv}
        for ts, cur, pv in (bundle.stats or [])[-MAX_STAT_ROWS:]
    ]
    timeline_rows = [
        {
            "seq": r.seq,
            "kind": r.kind,
            "status": r.status,
            "start": _fmt_dt(r.capture_start),
            "end": _fmt_dt(r.capture_end),
            "duration_sec": r.duration_sec,
            "file": r.file_path,
            "transcribed": r.transcribed,
        }
        for r in (bundle.timeline or [])[-800:]
    ]
    evidence = {
        "room_id": str(bundle.rid),
        "anchor_name": bundle.nickname or str(bundle.rid),
        "live_time": _fmt_range(*_session_range(bundle)),
        "metrics": _metrics_dict(metrics),
        "data_integrity": {
            "duration_sec": round(metrics.duration_sec, 1),
            "recorded_duration": round(metrics.recorded_duration, 1),
            "transcribed_duration": round(metrics.transcribed_duration, 1),
            "completeness": round(metrics.completeness, 3),
            "disconnect_count": metrics.disconnect_count,
            "short_segment_count": metrics.short_segment_count,
            "broken_segment_count": metrics.broken_segment_count,
            "failed_transcripts": metrics.failed_transcripts,
        },
        "event_counts": dict(bundle.event_counts or {}),
        "frequent_questions": _frequent_questions(bundle),
        "high_intent_danmu": _high_intent_danmu(bundle)[:80],
        "risk_candidates": _risk_segments(bundle),
        "stats_samples": stat_rows,
        "timeline": timeline_rows,
        "transcripts": transcript_rows,
        "transcript_truncated": transcript_truncated,
        "chats": chat_rows,
        "chat_truncated": len(bundle.chats or []) > len(chat_rows),
        "rules": {
            "analysis_prompt_version": ANALYSIS_PROMPT_VERSION,
            "min_duration_for_ai_sec": MIN_AI_DURATION_SEC,
            "stable_after_sec": STABLE_AFTER_SEC,
            "final_formula": "positive_score - risk_deduction - data_missing_deduction",
            "track_weighting": {
                "娱乐/聊天型直播": "降低人数/热度权重，提高弹幕密度、粉丝团/social、氛围、陪伴感和强关系互动权重。",
                "带货型直播": "提高人数/热度/进场权重，同时看购买意图、咨询、疑虑回应和话术承接。",
                "游戏/内容型直播": "人数热度中等权重，重点看内容持续性、讨论度、控场和粉丝粘性。",
            },
            "risk_deduction_cap": 20,
            "data_missing_deduction_cap": 10,
        },
    }
    digest = hashlib.sha256(json.dumps(evidence, ensure_ascii=False, sort_keys=True, default=str).encode("utf-8")).hexdigest()
    return digest, evidence


def _normalize_ai_result(data: dict[str, Any]) -> dict[str, Any]:
    positive = _num(data.get("positive_score"), 0, 100)
    risk = _num(data.get("risk_deduction"), 0, 20)
    missing = _num(data.get("data_missing_deduction"), 0, 10)
    raw_final = data.get("final_score")
    # 已通过后端时长/稳定性门禁并调用 AI 的场次，不能因为“互动少”逃成数据不足。
    # 这里仍以 AI 给的三项分为基础，只做公式一致性校验。
    final = int(_clamp(round(positive - risk - missing), 0, 100)) if raw_final is not None or positive > 0 else None
    # 评级必须由最终分数统一映射，避免 AI 出现“67分但评级良好”这类口径不一致。
    rating = _rating(final)
    out = {
        "track": _safe_text(data.get("track") or "未分类", 40),
        "template": _safe_text(data.get("template") or "通用模板", 40),
        "positive_score": int(round(positive)),
        "risk_deduction": int(round(risk)),
        "data_missing_deduction": int(round(missing)),
        "final_score": final,
        "rating": rating,
        "ai_summary": _safe_text(data.get("ai_summary") or "AI已完成分析。", 260),
        "key_positive_reasons": _safe_list(data.get("key_positive_reasons"), 8),
        "key_deduction_reasons": _safe_list(data.get("key_deduction_reasons"), 8),
        "dimensions": _safe_dimensions(data.get("dimensions")),
        "risk_review": _safe_risk_review(data.get("risk_review")),
        "suggestions": _safe_list(data.get("suggestions"), 8),
        "confidence": _safe_text(data.get("confidence") or "中", 10),
    }
    return out


def _safe_dimensions(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    out: list[dict[str, Any]] = []
    for row in rows[:8]:
        if not isinstance(row, dict):
            continue
        out.append({
            "key": _safe_text(row.get("key") or row.get("name") or "", 40),
            "name": _safe_text(row.get("name") or "AI判断维度", 40),
            "score": int(_num(row.get("score"), 0, 100)),
            "max_score": int(_num(row.get("max_score"), 0, 100)),
            "positive_reasons": _safe_list(row.get("positive_reasons") or row.get("reason"), 4),
            "negative_reasons": _safe_list(row.get("negative_reasons"), 4),
            "evidence": row.get("evidence") if isinstance(row.get("evidence"), list) else [],
            "suggestions": _safe_list(row.get("suggestions"), 4),
            "reason": _safe_text(row.get("reason") or "", 220),
        })
    return out


def _safe_risk_review(value: Any) -> list[dict[str, Any]]:
    rows = value if isinstance(value, list) else []
    out: list[dict[str, Any]] = []
    for row in rows[:30]:
        if not isinstance(row, dict):
            continue
        out.append({
            "risk_type": _safe_text(row.get("risk_type") or "", 40),
            "level": _safe_text(row.get("level") or "待复核", 12),
            "is_real_risk": bool(row.get("is_real_risk")),
            "deduction": int(_num(row.get("deduction"), 0, 20)),
            "evidence": _safe_text(row.get("evidence") or "", 180),
            "reason": _safe_text(row.get("reason") or "", 220),
        })
    return out


def _safe_list(value: Any, limit: int) -> list[str]:
    if isinstance(value, str):
        values = [value]
    elif isinstance(value, list):
        values = value
    else:
        values = []
    return [_safe_text(v, 180) for v in values[:limit] if str(v or "").strip()]


def _safe_text(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    for term in FORBIDDEN_BUSINESS_TERMS:
        text = text.replace(term, "商业结果")
    for old, new in FORBIDDEN_DECISION_PHRASES:
        text = text.replace(old, new)
    return text[:limit]


def _num(value: Any, low: float, high: float) -> float:
    try:
        n = float(value)
    except (TypeError, ValueError):
        n = low
    return _clamp(n, low, high)


def _conn() -> sqlite3.Connection:
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS performance_ai_analysis (
            room_id TEXT NOT NULL,
            template TEXT NOT NULL DEFAULT 'auto',
            evidence_hash TEXT NOT NULL,
            status TEXT NOT NULL,
            result_json TEXT,
            error TEXT,
            created_ts REAL NOT NULL,
            updated_ts REAL NOT NULL,
            analyzed_ts REAL,
            PRIMARY KEY(room_id, template)
        )
        """
    )
    return conn


def _load_analysis(room_id: str, template: str = ANALYSIS_TEMPLATE) -> dict[str, Any] | None:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM performance_ai_analysis WHERE room_id=? AND template=?",
            (str(room_id), template),
        ).fetchone()
    if not row:
        return None
    data = dict(row)
    try:
        data["result"] = json.loads(data.get("result_json") or "{}")
    except ValueError:
        data["result"] = {}
    return data


def _save_analysis(room_id: str, evidence_hash: str, status: str, result: dict[str, Any] | None, error: str) -> None:
    now = time.time()
    with _conn() as conn:
        conn.execute(
            """
            INSERT INTO performance_ai_analysis(room_id, template, evidence_hash, status, result_json, error, created_ts, updated_ts, analyzed_ts)
            VALUES(?,?,?,?,?,?,?,?,?)
            ON CONFLICT(room_id, template) DO UPDATE SET
              evidence_hash=excluded.evidence_hash,
              status=excluded.status,
              result_json=excluded.result_json,
              error=excluded.error,
              updated_ts=excluded.updated_ts,
              analyzed_ts=excluded.analyzed_ts
            """,
            (
                str(room_id),
                ANALYSIS_TEMPLATE,
                evidence_hash,
                status,
                json.dumps(result, ensure_ascii=False) if result else None,
                error,
                now,
                now,
                now if status in {"done", "failed"} else None,
            ),
        )


def _metrics(bundle: export.RoomBundle) -> MetricSnapshot:
    timeline = bundle.timeline
    duration = _duration_from_timeline_or_transcripts(bundle)
    recorded = sum(float(r.duration_sec or 0) for r in timeline if r.file_path and r.status in {"ok", "short", "partial"})
    transcribed = sum(float(t.duration_sec or 0) for t in bundle.transcripts)
    if recorded <= 0:
        recorded = transcribed
    completeness = _clamp(recorded / duration if duration > 0 else (1.0 if recorded > 0 else 0.0), 0.0, 1.0)
    stats = bundle.stats or []
    online_values = [int(s[1] or 0) for s in stats]
    peak_online = max(online_values, default=0)
    avg_online = mean(online_values) if online_values else 0.0
    latest_online = int(stats[-1][1]) if stats else 0
    total_viewers = max((int(s[2] or 0) for s in stats), default=0)
    counts = {str(k).lower(): int(v or 0) for k, v in bundle.event_counts.items()}
    text = "\n".join(t.text or "" for t in bundle.transcripts)
    chat_texts = [c for _, c in bundle.chats if c]
    danmu_count = len(bundle.chats)
    like_events = _sum_matching(counts, "like", "点赞")
    follow_events = _sum_matching(counts, "follow", "social", "关注")
    enter_events = _sum_matching(counts, "member", "enter", "join", "进入")
    fansclub_events = _sum_matching(counts, "fansclub", "fanclub", "club", "粉丝团", "会员")
    gift_events = _sum_matching(counts, "gift", "礼物")  # TODO: 确认礼物事件结构后再做价值/人数拆分。
    return MetricSnapshot(
        duration_sec=duration,
        recorded_duration=recorded,
        transcribed_duration=transcribed,
        completeness=completeness,
        danmu_count=danmu_count,
        event_total=sum(counts.values()),
        peak_online=peak_online,
        avg_online=avg_online,
        latest_online=latest_online,
        total_viewers=total_viewers,
        like_events=like_events,
        follow_events=follow_events,
        enter_events=enter_events,
        fansclub_events=fansclub_events,
        question_count=sum(_contains_any(c, QUESTION_TERMS) for c in chat_texts),
        intent_count=sum(_contains_any(c, INTENT_TERMS) for c in chat_texts),
        negative_count=sum(_contains_any(c, NEGATIVE_TERMS) for c in chat_texts),
        transcript_chars=len(text),
        speech_density=_density(len(text), duration),
        danmu_per_min=_density(danmu_count, duration),
        like_per_min=_density(like_events, duration),
        intent_ratio=(sum(_contains_any(c, INTENT_TERMS) for c in chat_texts) / danmu_count) if danmu_count else 0.0,
        online_stability=_online_stability(online_values),
        high_value_member_events=0,
        gift_events=gift_events,
        disconnect_count=sum(1 for r in timeline if r.status == "gap" or r.kind == "gap"),
        short_segment_count=sum(1 for r in timeline if r.status == "short" or r.kind == "short"),
        broken_segment_count=sum(1 for r in timeline if r.status in {"partial", "failed"} or r.kind == "partial"),
        failed_transcripts=sum(1 for r in timeline if r.file_path and not r.transcribed and r.status in {"ok", "short"}),
    )


def _data_insufficient(m: MetricSnapshot) -> tuple[bool, str]:
    has_any_signal = bool(
        m.danmu_count or m.transcript_chars or m.like_events or m.follow_events
        or m.enter_events or m.fansclub_events or m.total_viewers or m.peak_online
    )
    if m.duration_sec <= 0:
        return True, "缺少关键时间信息，无法判断有效直播"
    if m.duration_sec < 300:
        return True, "直播有效时长不足 5 分钟"
    if m.completeness < 0.30:
        return True, "监听完整度低于 30%"
    if not has_any_signal:
        return True, "弹幕、转写、互动数据均为空"
    return False, ""


def _latest_data_ts(bundle: export.RoomBundle) -> float:
    stamps: list[float] = []
    for r in bundle.timeline:
        if r.capture_end:
            stamps.append(float(r.capture_end))
    for t in bundle.transcripts:
        stamps.append(float(t.capture_end or t.segment_ts or 0))
    for ts, _, _ in bundle.stats:
        stamps.append(float(ts / 1000 if ts > 1_000_000_000_000 else ts))
    room_dir = config.AUDIO_DIR / str(bundle.rid)
    if room_dir.exists():
        for path in room_dir.glob("*.mp3"):
            try:
                stamps.append(path.stat().st_mtime)
            except OSError:
                pass
    return max(stamps, default=0.0)


def _risk_segments(bundle: export.RoomBundle) -> list[dict[str, Any]]:
    risks = []
    for t in bundle.transcripts:
        text = t.text or ""
        for risk_type, level, terms in RISK_RULES:
            matched = [term for term in terms if term in text]
            if matched:
                if not _risk_context_allowed(risk_type, text):
                    continue
                risks.append({
                    "start_time": _fmt_dt(t.capture_start or t.segment_ts),
                    "end_time": _fmt_dt(t.capture_end or ((t.capture_start or t.segment_ts) + (t.duration_sec or 0))),
                    "type": "敏感词候选",
                    "risk_type": risk_type,
                    "risk_level": level,
                    "speech": _clip(text, 140),
                    "ai_judgement": f"命中{risk_type}：{'、'.join(matched[:4])}",
                    "suggestion": "仅作为敏感词复核线索，不自动代表违规或合作判断。",
                    "audio_path": t.mp3_name,
                })
                break
    return risks[:30]


def _risk_context_allowed(risk_type: str, text: str) -> bool:
    # 风险合规在本版本只做敏感词候选，不再做宽泛语义扩展。
    # 这里保留函数形态，方便后续接入人工词库或更细的上下文复核。
    return True


def _frequent_questions(bundle: export.RoomBundle) -> list[dict[str, Any]]:
    counter: Counter[str] = Counter()
    samples: dict[str, str] = {}
    for _, content in bundle.chats:
        for term in QUESTION_TERMS:
            if term in (content or ""):
                counter[term] += 1
                samples.setdefault(term, content)
    return [{"question": term, "count": count, "sample": samples.get(term, "")} for term, count in counter.most_common(12)]


def _unanswered_questions(bundle: export.RoomBundle, questions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    transcript_text = "\n".join(t.text or "" for t in bundle.transcripts)
    rows = []
    for q in questions[:8]:
        term = q["question"]
        answered = transcript_text.count(term)
        if q["count"] >= 2 and answered < max(1, math.ceil(q["count"] * 0.25)):
            rows.append({
                "question": term,
                "count": q["count"],
                "response_count": answered,
                "status": "回应不足" if answered else "未明确回应",
                "suggestion": f"建议主播对「{term}」形成固定回应话术",
            })
    return rows


def _highlight_segments(bundle: export.RoomBundle) -> list[dict[str, Any]]:
    rows = sorted(bundle.transcripts, key=lambda t: (t.char_count, t.duration_sec or 0), reverse=True)[:5]
    return [_segment(t, "高信息片段", "话术信息量较高，适合交给 AI 作为正向证据。", "沉淀为可复用话术并观察对应弹幕反馈。") for t in rows]


def _low_efficiency_segments(bundle: export.RoomBundle) -> list[dict[str, Any]]:
    rows = [t for t in bundle.transcripts if (t.duration_sec or 0) >= 20 and (t.char_count or 0) < 20][:5]
    return [_segment(t, "低信息候选", "按规则命中：该段时长较长但转写字数较少，可能是沉默、音乐、噪声、ASR漏识别或主播停顿。", "仅作为回听定位线索，不直接认定为低效。") for t in rows]


def _segment(t: export.TranscriptRow, typ: str, judgement: str, suggestion: str) -> dict[str, Any]:
    return {
        "start_time": _fmt_dt(t.capture_start or t.segment_ts),
        "end_time": _fmt_dt(t.capture_end or ((t.capture_start or t.segment_ts) + (t.duration_sec or 0))),
        "type": typ,
        "ai_judgement": judgement,
        "speech": _clip(t.text, 160),
        "danmu": "",
        "suggestion": suggestion,
        "audio_path": t.mp3_name,
    }


def _high_intent_danmu(bundle: export.RoomBundle) -> list[dict[str, str]]:
    return [{"user": u, "content": c} for u, c in bundle.chats if _contains_any(c, INTENT_TERMS)][:80]


def _negative_feedback(bundle: export.RoomBundle) -> list[dict[str, str]]:
    return [{"user": u, "content": c} for u, c in bundle.chats if _contains_any(c, NEGATIVE_TERMS)][:40]


def _session_range(bundle: export.RoomBundle) -> tuple[float | None, float | None]:
    starts: list[float] = []
    ends: list[float] = []
    for r in bundle.timeline:
        if r.capture_start:
            starts.append(float(r.capture_start))
        if r.capture_end:
            ends.append(float(r.capture_end))
    for t in bundle.transcripts:
        starts.append(float(t.capture_start or t.segment_ts))
        ends.append(float(t.capture_end or ((t.capture_start or t.segment_ts) + (t.duration_sec or 0))))
    for ts, _, _ in bundle.stats:
        sec = ts / 1000 if ts > 1_000_000_000_000 else ts
        starts.append(float(sec))
        ends.append(float(sec))
    return (min(starts) if starts else None, max(ends) if ends else None)


def _duration_from_timeline_or_transcripts(bundle: export.RoomBundle) -> float:
    start, end = _session_range(bundle)
    if start and end and end > start:
        return float(end - start)
    duration = sum(float(r.duration_sec or 0) for r in bundle.timeline)
    if duration <= 0:
        duration = sum(float(t.duration_sec or 0) for t in bundle.transcripts)
    return duration


def _metrics_dict(m: MetricSnapshot) -> dict[str, Any]:
    return {
        "total_viewers": m.total_viewers,
        "peak_online": m.peak_online,
        "avg_online": round(m.avg_online, 1),
        "latest_online": m.latest_online,
        "enter_events": m.enter_events,
        "danmu_count": m.danmu_count,
        "danmu_per_min": round(m.danmu_per_min, 2),
        "like_events": m.like_events,
        "like_per_min": round(m.like_per_min, 2),
        "social_events": m.follow_events,
        "fansclub_events": m.fansclub_events,
        "question_count": m.question_count,
        "intent_count": m.intent_count,
        "intent_ratio": round(m.intent_ratio, 4),
        "transcript_chars": m.transcript_chars,
        "speech_density": round(m.speech_density, 2),
        "online_stability": round(m.online_stability, 3),
        "gift_events": m.gift_events,
    }


def _key_positive_reasons(m: MetricSnapshot) -> list[str]:
    reasons = []
    if m.total_viewers or m.peak_online:
        reasons.append(f"观看热度：累计观看 {m.total_viewers}，峰值在线 {m.peak_online}")
    if m.enter_events:
        reasons.append(f"进场活跃：member/进场 {m.enter_events} 次")
    if m.danmu_count or m.like_events:
        reasons.append(f"互动活跃：弹幕 {m.danmu_count} 条，点赞 {m.like_events} 次")
    if m.follow_events or m.fansclub_events:
        reasons.append(f"强关系互动：social {m.follow_events}，fansclub {m.fansclub_events}")
    if m.intent_count:
        reasons.append(f"用户意图：高意图弹幕 {m.intent_count} 条")
    return reasons or ["暂无明显加分信号，等待 AI 结合上下文判断"]


def _key_deduction_reasons(m: MetricSnapshot, risks: list[dict[str, Any]], insufficient_reason: str) -> list[str]:
    reasons = []
    if insufficient_reason:
        reasons.append(insufficient_reason)
    if risks:
        top = Counter(r["risk_type"] for r in risks).most_common(3)
        reasons.append("敏感词候选：" + "、".join(f"{k}{v}条" for k, v in top))
    if m.disconnect_count or m.short_segment_count or m.broken_segment_count:
        reasons.append(f"录制异常：断流{m.disconnect_count}、短段{m.short_segment_count}、残段{m.broken_segment_count}")
    return reasons or ["暂无明显扣分项，等待 AI 结合上下文判断"]


def _data_status(status: str) -> str:
    return {
        "done": "AI已分析",
        "ready": "待AI分析",
        "stale": "需重新分析",
        "failed": "分析失败",
        "analyzing": "分析中",
        "waiting_stable": "等待下播",
        "not_eligible_short": "时长不足",
        "data_insufficient": "数据不足",
        "ai_not_configured": "AI未配置",
    }.get(status, status)


def _recommendation(rating: str, suggestions: list[str]) -> str:
    return ""


def _rating(score: int | None) -> str:
    if score is None:
        return "数据不足"
    if score >= 85:
        return "优秀"
    if score >= 75:
        return "良好"
    if score >= 60:
        return "一般"
    if score >= 45:
        return "较弱"
    return "低分"


def _confidence(completeness: float) -> str:
    pct = completeness * 100
    if pct >= 90:
        return "高"
    if pct >= 70:
        return "中"
    return "低"


def _sort_key(row: dict[str, Any]) -> tuple[int, int, int]:
    status_rank = {"done": 4, "ready": 3, "stale": 3, "failed": 2, "waiting_stable": 1}.get(str(row.get("analysis_status")), 0)
    score = row.get("overall_score")
    score_num = int(score) if isinstance(score, (int, float)) else -1
    danmu = int((row.get("metrics") or {}).get("danmu_count") or 0)
    return status_rank, score_num, danmu


def _error_row(rid: str, name: str, exc: Exception) -> dict[str, Any]:
    return {
        "session_id": rid,
        "rid": rid,
        "anchor_name": name or rid,
        "score_available": False,
        "overall_score": None,
        "rating": "数据不足",
        "analysis_status": "failed",
        "analysis_status_text": f"读取数据失败：{exc}",
        "data_status": "读取失败",
        "ai_summary": f"读取数据失败：{exc}",
        "metrics": {},
        "transcribed": False,
    }


def _density(count: float, duration_sec: float) -> float:
    return count / max(1.0, duration_sec / 60.0)


def _online_stability(values: list[int]) -> float:
    positive = [v for v in values if v > 0]
    if len(positive) < 2:
        return 0.0
    avg = mean(positive)
    if avg <= 0:
        return 0.0
    return _clamp(1.0 - (pstdev(positive) / max(avg, 1.0)), 0.0, 1.0)


def _sum_matching(counts: dict[str, int], *needles: str) -> int:
    return sum(v for k, v in counts.items() if any(n.lower() in k.lower() for n in needles))


def _contains_any(text: str, terms: tuple[str, ...]) -> bool:
    return any(term in (text or "") for term in terms)


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _clip(text: str, limit: int) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= limit else text[:limit] + "..."


def _fmt_dt(ts: float | int | None) -> str:
    if not ts:
        return "暂无数据"
    if ts > 1_000_000_000_000:
        ts = ts / 1000
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, OSError, OverflowError):
        return "暂无数据"


def _fmt_range(start: float | None, end: float | None) -> str:
    if not start:
        return "暂无数据"
    if not end or int(start) == int(end):
        return _fmt_dt(start)
    return f"{_fmt_dt(start)} - {_fmt_dt(end)}"


def _fmt_duration(sec: float) -> str:
    sec = int(max(0, sec or 0))
    if sec <= 0:
        return "暂无数据"
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}小时{m}分钟"
    if m:
        return f"{m}分钟{s}秒"
    return f"{s}秒"
