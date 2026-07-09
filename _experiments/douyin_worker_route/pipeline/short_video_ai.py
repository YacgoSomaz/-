"""短视频 AI 拆解：后台自动取封面、提取音频、转写并调用 AI 分析。"""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import requests

from . import ai_report, config, short_video
from .sensevoice_engine import SenseVoiceEngine

DEFAULT_VISION_BASE_URL = "https://ark.cn-beijing.volces.com/api/v3"
DEFAULT_VISION_MODEL = "ep-m-20260518173100-t8kjz"


@dataclass(frozen=True)
class VisionConfig:
    base_url: str = DEFAULT_VISION_BASE_URL
    api_key: str = ""
    model: str = DEFAULT_VISION_MODEL
    timeout_sec: int = 120

    @property
    def ready(self) -> bool:
        return bool(self.base_url.strip() and self.api_key.strip() and self.model.strip())


def load_vision_config() -> VisionConfig:
    saved: dict[str, Any] = {}
    try:
        raw = json.loads(config.AI_CONFIG_PATH.read_text(encoding="utf-8")) if config.AI_CONFIG_PATH.exists() else {}
        saved = raw if isinstance(raw, dict) else {}
    except (OSError, ValueError, TypeError):
        saved = {}
    return VisionConfig(
        base_url=(
            os.environ.get("SHORT_VIDEO_VISION_BASE_URL")
            or os.environ.get("ARK_BASE_URL")
            or saved.get("vision_base_url")
            or DEFAULT_VISION_BASE_URL
        ).strip(),
        api_key=(
            os.environ.get("SHORT_VIDEO_VISION_API_KEY")
            or os.environ.get("ARK_API_KEY")
            or saved.get("vision_api_key")
            or ""
        ).strip(),
        model=(
            os.environ.get("SHORT_VIDEO_VISION_MODEL")
            or os.environ.get("ARK_VISION_MODEL")
            or saved.get("vision_model")
            or DEFAULT_VISION_MODEL
        ).strip(),
        timeout_sec=int(os.environ.get("SHORT_VIDEO_VISION_TIMEOUT_SEC") or saved.get("vision_timeout_sec") or "120"),
    )


def analyze_selected_videos(
    profile: dict[str, Any] | None,
    videos: list[dict[str, Any]] | None,
    *,
    limit: int = 10,
) -> dict[str, Any]:
    profile = profile or {}
    selected = [v for v in (videos or []) if isinstance(v, dict)][: max(1, min(25, int(limit)))]
    engine: SenseVoiceEngine | None = None
    items: list[dict[str, Any]] = []
    for video in selected:
        errors: list[str] = []
        cover = _safe_call(lambda: short_video.download_video_cover_asset(profile, video), errors, "封面获取失败")
        audio = _safe_call(lambda: short_video.download_video_mp3_asset(profile, video), errors, "音频提取失败")
        transcript = ""
        if audio.get("ok") and audio.get("path"):
            try:
                if engine is None:
                    engine = SenseVoiceEngine()
                transcript = engine.transcribe(str(audio["path"]))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"转写失败：{type(exc).__name__}: {exc}")
        if not transcript:
            transcript = _fallback_transcript(video)
        text_analysis = _safe_call(
            lambda: _analyze_transcript_with_ai(transcript, profile, video),
            errors,
            "话术AI分析失败",
        )
        if not text_analysis.get("summary"):
            text_analysis = _normalize_analysis({}, fallback="话术 AI 分析未完成，请检查 DeepSeek 配置后重试。")
        cover_analysis = _safe_call(
            lambda: _analyze_cover_with_vision(Path(str(cover["path"])), profile, video)
            if cover.get("ok") and cover.get("path")
            else {"summary": "未取得封面，无法进行画面分析。", "strengths": [], "problems": ["缺少封面"], "suggestions": ["重新解析账号或刷新作品封面。"]},
            errors,
            "封面AI分析失败",
        )
        if not cover_analysis.get("summary"):
            cover_analysis = _normalize_analysis({}, fallback="封面 AI 分析未完成，请检查多模态模型配置后重试。")
        score = _inline_score(text_analysis, cover_analysis, video)
        prediction = _inline_prediction(score, text_analysis, cover_analysis, video)
        items.append({
            "id": str(video.get("id") or ""),
            "title": str(video.get("title") or ""),
            "url": str(video.get("url") or ""),
            "cover_url": str(video.get("cover_url") or ""),
            "cover_path": str(cover.get("path") or ""),
            "audio_path": str(audio.get("path") or ""),
            "transcript": transcript,
            "text_analysis": text_analysis,
            "cover_analysis": cover_analysis,
            "score": score,
            "prediction": prediction,
            "errors": errors,
        })
    return {
        "ok": True,
        "profile": profile,
        "items": items,
        "count": len(items),
        "summary": _build_summary(items),
    }


def _safe_call(fn, errors: list[str], prefix: str) -> dict[str, Any]:
    try:
        result = fn()
        return result if isinstance(result, dict) else {"ok": False, "error": "返回格式异常"}
    except Exception as exc:  # noqa: BLE001
        errors.append(f"{prefix}：{type(exc).__name__}: {exc}")
        return {"ok": False, "error": f"{prefix}：{type(exc).__name__}"}


def _fallback_transcript(video: dict[str, Any]) -> str:
    title = str(video.get("title") or "").strip()
    return title or "暂无可用转写文本。"


def _analyze_transcript_with_ai(transcript: str, profile: dict[str, Any], video: dict[str, Any]) -> dict[str, Any]:
    cfg = ai_report.load_config()
    prompt = {
        "主播": profile.get("nickname") or profile.get("sec_user_id") or "未知账号",
        "标题": video.get("title") or "",
        "转写文本": transcript[:12000],
    }
    content = ai_report._chat_completion(
        cfg,
        [
            {
                "role": "system",
                "content": (
                    "你是短视频运营拆解顾问，擅长房产、带货和泛内容短视频复盘。"
                    "只输出 JSON，不要 Markdown。必须给出足够具体、可执行的运营判断。"
                    "字段：summary, strengths, problems, suggestions, hooks, script_structure, "
                    "opening_hook, selling_points, audience_fit, conversion_path, pacing, reusable_lines, rewrite_suggestions, evidence, "
                    "score, prediction。score 里包含 overall_score 和 dimensions；prediction 里包含 prediction_bucket、confidence、reasons、may_win、may_lose。"
                    "除 summary 外，其他字段都是中文字符串数组，每项尽量包含具体依据或改法。"
                ),
            },
            {
                "role": "user",
                "content": (
                    "请基于短视频标题和转写文本，做一份面向运营人员的短视频拆解。"
                    "要求：1) 不要只给一句泛泛总结；2) 必须拆开分析开头3秒、核心卖点、目标用户、信任证据、节奏、行动引导；"
                    "3) 如果文本很短，也要基于标题、标签和已有转写判断缺失项；4) 给出至少3条具体改写建议；"
                    "5) 顺手给出作品潜力评分和相对爆款预测，不要预测具体播放量。"
                    "\n输入：\n"
                )
                + json.dumps(prompt, ensure_ascii=False),
            },
        ],
        temperature=0.2,
        max_tokens=2600,
        response_format={"type": "json_object"},
    )
    data = _parse_json_object(content)
    return _normalize_analysis(data, fallback="话术分析已完成。")


def _analyze_cover_with_vision(cover_path: Path, profile: dict[str, Any], video: dict[str, Any]) -> dict[str, Any]:
    cfg = load_vision_config()
    if not cfg.ready:
        return {
            "summary": "多模态模型尚未配置，暂未进行封面画面分析。",
            "strengths": [],
            "problems": ["缺少多模态 API Key"],
            "suggestions": ["请在系统设置的短视频封面识别中配置多模态 API Key 后重试。"],
        }
    mime = _image_mime(cover_path)
    encoded = base64.b64encode(cover_path.read_bytes()).decode("ascii")
    messages = [
        {
            "role": "system",
            "content": "你是短视频封面与画面运营分析师。只输出 JSON，不要 Markdown。",
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": (
                        "请分析这张短视频封面，输出 JSON 字段：summary, strengths, problems, suggestions, visual_keywords。"
                        "重点看：主体是否明确、文字是否抢眼、利益点是否清楚、画面证据是否充分、用户第一眼能否理解、是否适合点击。"
                        "suggestions 至少给 4 条，分别覆盖：标题文字、构图层次、利益点、信任/证据、行动引导。"
                        f"\n账号：{profile.get('nickname') or ''}\n标题：{video.get('title') or ''}"
                    ),
                },
                {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{encoded}"}},
            ],
        },
    ]
    payload = {
        "model": cfg.model,
        "messages": messages,
        "temperature": 0.2,
        "max_tokens": 1800,
        "response_format": {"type": "json_object"},
    }
    try:
        resp = requests.post(
            _chat_url(cfg.base_url),
            headers={"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"},
            json=payload,
            timeout=cfg.timeout_sec,
        )
        if resp.status_code == 400:
            payload.pop("response_format", None)
            resp = requests.post(
                _chat_url(cfg.base_url),
                headers={"Authorization": f"Bearer {cfg.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=cfg.timeout_sec,
            )
    except requests.RequestException as exc:
        raise RuntimeError(f"多模态请求失败：{exc}") from exc
    if resp.status_code >= 400:
        raise RuntimeError(f"多模态接口 HTTP {resp.status_code}: {(resp.text or '')[:300]}")
    data = resp.json()
    content = str(data["choices"][0]["message"]["content"] or "")
    return _normalize_analysis(_parse_json_object(content), fallback="封面分析已完成。")


def _chat_url(base_url: str) -> str:
    base = base_url.strip().rstrip("/")
    return base if base.endswith("/chat/completions") else base + "/chat/completions"


def _parse_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    try:
        data = json.loads(text)
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.S)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}


def _normalize_analysis(data: dict[str, Any], *, fallback: str) -> dict[str, Any]:
    def arr(key: str) -> list[str]:
        value = data.get(key)
        if isinstance(value, list):
            return [str(x).strip() for x in value if str(x).strip()][:8]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    return {
        "summary": str(data.get("summary") or fallback).strip(),
        "strengths": arr("strengths"),
        "problems": arr("problems"),
        "suggestions": arr("suggestions"),
        "hooks": arr("hooks"),
        "script_structure": arr("script_structure"),
        "visual_keywords": arr("visual_keywords"),
        "opening_hook": arr("opening_hook"),
        "selling_points": arr("selling_points"),
        "audience_fit": arr("audience_fit"),
        "conversion_path": arr("conversion_path"),
        "pacing": arr("pacing"),
        "reusable_lines": arr("reusable_lines"),
        "rewrite_suggestions": arr("rewrite_suggestions"),
        "evidence": arr("evidence"),
        "score": data.get("score") if isinstance(data.get("score"), dict) else {},
        "prediction": data.get("prediction") if isinstance(data.get("prediction"), dict) else {},
    }


def _inline_score(text_analysis: dict[str, Any], cover_analysis: dict[str, Any], video: dict[str, Any]) -> dict[str, Any]:
    raw = text_analysis.get("score") if isinstance(text_analysis.get("score"), dict) else {}
    dims = raw.get("dimensions") if isinstance(raw.get("dimensions"), list) else []
    normalized_dims: list[dict[str, Any]] = []
    for dim in dims[:8]:
        if not isinstance(dim, dict):
            continue
        name = str(dim.get("name") or "").strip()
        if not name:
            continue
        max_score = int(_num(dim.get("max_score"), 10) or 10)
        score = max(0, min(max_score, int(round(_num(dim.get("score"), 0)))))
        normalized_dims.append({
            "name": name[:20],
            "score": score,
            "max_score": max_score,
            "evidence": str(dim.get("evidence") or dim.get("suggestion") or "")[:160],
            "suggestion": str(dim.get("suggestion") or "")[:160],
        })
    if not normalized_dims:
        normalized_dims = _fallback_dimensions(text_analysis, cover_analysis, video)
    overall = int(round(_num(raw.get("overall_score"), 0)))
    if overall <= 0:
        total = sum(d["score"] for d in normalized_dims)
        max_total = max(1, sum(d["max_score"] for d in normalized_dims))
        overall = int(round(total / max_total * 100))
    return {
        "overall_score": max(0, min(100, overall)),
        "template": str(raw.get("template") or "短视频综合拆解"),
        "dimensions": normalized_dims,
        "highlights": _merge_lists(text_analysis.get("strengths"), cover_analysis.get("strengths"))[:5],
        "problems": _merge_lists(text_analysis.get("problems"), cover_analysis.get("problems"))[:5],
        "rewrite_suggestions": _merge_lists(text_analysis.get("rewrite_suggestions"), text_analysis.get("suggestions"), cover_analysis.get("suggestions"))[:6],
        "compliance_flags": [],
    }


def _inline_prediction(
    score: dict[str, Any],
    text_analysis: dict[str, Any],
    cover_analysis: dict[str, Any],
    video: dict[str, Any],
) -> dict[str, Any]:
    raw = text_analysis.get("prediction") if isinstance(text_analysis.get("prediction"), dict) else {}
    overall = int(score.get("overall_score") or 0)
    bucket = str(raw.get("prediction_bucket") or "").strip()
    if not bucket:
        if overall >= 86:
            bucket = "爆款潜力"
        elif overall >= 76:
            bucket = "高潜力"
        elif overall >= 64:
            bucket = "中高潜力"
        elif overall >= 50:
            bucket = "普通潜力"
        else:
            bucket = "低潜力"
    confidence = _num(raw.get("confidence"), 0)
    if confidence <= 0:
        confidence = min(0.88, max(0.48, 0.45 + overall / 180))
    return {
        "prediction_bucket": bucket,
        "confidence": round(float(confidence), 2),
        "reasons": _merge_lists(raw.get("reasons"), text_analysis.get("strengths"), cover_analysis.get("strengths"))[:4],
        "may_win": _merge_lists(raw.get("may_win"), text_analysis.get("hooks"), cover_analysis.get("visual_keywords"))[:4],
        "may_lose": _merge_lists(raw.get("may_lose"), text_analysis.get("problems"), cover_analysis.get("problems"))[:4],
        "similar_history": [],
    }


def _fallback_dimensions(text_analysis: dict[str, Any], cover_analysis: dict[str, Any], video: dict[str, Any]) -> list[dict[str, Any]]:
    positives = len(_merge_lists(text_analysis.get("strengths"), cover_analysis.get("strengths")))
    problems = len(_merge_lists(text_analysis.get("problems"), cover_analysis.get("problems")))
    suggestions = len(_merge_lists(text_analysis.get("suggestions"), cover_analysis.get("suggestions")))
    like_bonus = min(4, int(_num(video.get("like_count"), 0) ** 0.35)) if _num(video.get("like_count"), 0) > 0 else 0
    values = [
        ("开头钩子", 6 + min(3, len(text_analysis.get("opening_hook") or [])) + like_bonus // 2, "看前3秒是否能迅速交代利益点和观看理由。"),
        ("卖点表达", 5 + min(4, len(text_analysis.get("selling_points") or [])) + min(2, positives), "看房源、产品或内容价值是否被清楚说出来。"),
        ("画面证据", 5 + min(4, len(cover_analysis.get("strengths") or [])) - min(2, len(cover_analysis.get("problems") or [])), "看封面和画面是否提供真实可感知的证据。"),
        ("受众命中", 5 + min(3, len(text_analysis.get("audience_fit") or [])) + like_bonus // 2, "看目标人群是否明确，是否能降低用户理解成本。"),
        ("行动引导", 4 + min(4, len(text_analysis.get("conversion_path") or [])) + min(2, suggestions), "看是否有自然的评论、咨询、收藏或点击理由。"),
    ]
    dims = []
    for name, score, evidence in values:
        score = max(1, min(10, int(score) - max(0, problems - positives) // 2))
        dims.append({"name": name, "score": score, "max_score": 10, "evidence": evidence, "suggestion": ""})
    return dims


def _merge_lists(*values: Any) -> list[str]:
    merged: list[str] = []
    for value in values:
        if isinstance(value, list):
            for item in value:
                text = str(item).strip()
                if text and text not in merged:
                    merged.append(text)
        elif isinstance(value, str) and value.strip() and value.strip() not in merged:
            merged.append(value.strip())
    return merged


def _num(value: Any, default: float = 0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _image_mime(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"


def _build_summary(items: list[dict[str, Any]]) -> str:
    if not items:
        return "暂无作品可分析。"
    ok = sum(1 for item in items if not item.get("errors"))
    return f"已拆解 {len(items)} 个作品，其中 {ok} 个作品素材和 AI 分析链路完整。"
