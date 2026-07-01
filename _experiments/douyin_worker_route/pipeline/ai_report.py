"""AI-assisted replay reports.

The model is intentionally not an agent here. 直播复盘侠 gathers local evidence
from SQLite first, asks an OpenAI-compatible chat API to summarize bounded
chunks, validates the structure, then asks for a final Markdown report.
"""

from __future__ import annotations

import json
import re
import html
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterator

import requests

from . import config
from . import export as export_mod


DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4.1-mini"
CHUNK_CHAR_LIMIT = 6000
MAX_CHUNKS = 16
WORD_LIMIT = 80

_STOP_WORDS = {
    "我们", "你们", "大家", "这个", "那个", "然后", "就是", "可以", "一下",
    "直播", "直播间", "朋友", "家人", "的话", "现在", "这边", "那边", "一个",
    "还是", "没有", "不是", "因为", "所以", "如果", "来说", "看到", "关注",
    "点击", "下方", "链接", "预约", "直接", "进行", "给到", "来到", "好吧",
    "今天", "这一个", "这一边", "这套", "这个是", "里面", "上面", "下面",
    "是否", "是不是", "什么", "多少", "怎么", "为什么", "对不", "不对",
    "对不对", "真的", "当然", "非常", "比较", "很多", "之前", "之后",
}
_STOP_SUBSTRINGS = {
    "我们", "你们", "大家", "咱们", "这个", "那个", "这边", "那边", "的话",
    "的一", "一个", "一下", "可以", "都可", "有到", "进行", "直接", "点击",
    "下方", "链接", "来看", "看一", "一看", "去看", "来给", "给大", "给到",
    "录音", "音频", "主播", "直播", "房间", "时间", "未标", "标注",
    "是不是", "是否", "什么", "对不", "不对", "好的", "老板", "家人",
    "这个", "那个", "的话", "没有", "不是", "因为", "所以", "如果",
}
_BAD_EDGE_CHARS = set("的一了到这那们个下有可都去来是我你他她它在就和及把被吗呢啊吧哦哈呀上下面里中")
_IMPORTANT_TERMS = {
    "户型", "三房", "四房", "小高层", "洋房", "现房", "精装", "精装修", "毛坯",
    "首付", "月供", "总价", "单价", "优惠", "折扣", "特价房", "认购", "定金",
    "学校", "小学", "初中", "高中", "幼儿园", "学区", "入读", "业主", "户口",
    "地铁", "商圈", "配套", "物业", "绿化率", "容积率", "车位", "交付",
    "盘龙", "昆明", "大华", "锦绣", "麓城", "云师大", "盘龙小学",
}


@dataclass(frozen=True)
class AIConfig:
    base_url: str = DEFAULT_BASE_URL
    api_key: str = ""
    model: str = DEFAULT_MODEL
    timeout_sec: int = 180

    @property
    def ready(self) -> bool:
        return bool(self.base_url.strip() and self.api_key.strip() and self.model.strip())


class AIReportError(RuntimeError):
    """User-facing report generation error."""


def load_config() -> AIConfig:
    path = config.AI_CONFIG_PATH
    if not path.exists():
        return AIConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return AIConfig()
    return AIConfig(
        base_url=str(data.get("base_url") or DEFAULT_BASE_URL).strip(),
        api_key=str(data.get("api_key") or "").strip(),
        model=str(data.get("model") or DEFAULT_MODEL).strip(),
        timeout_sec=int(data.get("timeout_sec") or 180),
    )


def public_config() -> dict[str, object]:
    cfg = load_config()
    return {
        "base_url": cfg.base_url,
        "model": cfg.model,
        "has_api_key": bool(cfg.api_key),
        "ready": cfg.ready,
        "timeout_sec": cfg.timeout_sec,
    }


def save_config(payload: dict[str, object]) -> dict[str, object]:
    old = load_config()
    base_url = str(payload.get("base_url") or old.base_url or DEFAULT_BASE_URL).strip()
    model = str(payload.get("model") or old.model or DEFAULT_MODEL).strip()
    timeout_sec = int(payload.get("timeout_sec") or old.timeout_sec or 180)
    clear_key = bool(payload.get("clear_api_key"))
    raw_key = payload.get("api_key")
    if clear_key:
        api_key = ""
    elif raw_key is None or str(raw_key).strip() == "":
        api_key = old.api_key
    else:
        api_key = str(raw_key).strip()
    cfg = AIConfig(base_url=base_url, api_key=api_key, model=model, timeout_sec=timeout_sec)
    config.AI_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    config.AI_CONFIG_PATH.write_text(
        json.dumps(
            {
                "base_url": cfg.base_url,
                "api_key": cfg.api_key,
                "model": cfg.model,
                "timeout_sec": cfg.timeout_sec,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return public_config()


def _chat_url(base_url: str) -> str:
    url = base_url.strip().rstrip("/")
    if url.endswith("/chat/completions"):
        return url
    return url + "/chat/completions"


def _chat_completion(
    cfg: AIConfig,
    messages: list[dict[str, str]],
    *,
    temperature: float = 0.2,
    max_tokens: int = 1800,
    response_format: dict[str, str] | None = None,
) -> str:
    if not cfg.ready:
        raise AIReportError("AI 尚未配置，请先在系统设置里填写 base_url、API Key 和模型名。")
    payload: dict[str, object] = {
        "model": cfg.model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if response_format:
        payload["response_format"] = response_format
    headers = {
        "Authorization": f"Bearer {cfg.api_key}",
        "Content-Type": "application/json",
    }
    try:
        resp = requests.post(
            _chat_url(cfg.base_url),
            headers=headers,
            json=payload,
            timeout=cfg.timeout_sec,
        )
        if resp.status_code == 400 and response_format:
            payload.pop("response_format", None)
            resp = requests.post(
                _chat_url(cfg.base_url),
                headers=headers,
                json=payload,
                timeout=cfg.timeout_sec,
            )
    except requests.RequestException as exc:
        raise AIReportError(f"AI 请求失败：{exc}") from exc
    if resp.status_code >= 400:
        text = (resp.text or "")[:500]
        raise AIReportError(f"AI 接口返回 HTTP {resp.status_code}: {text}")
    try:
        data = resp.json()
        return str(data["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise AIReportError("AI 返回格式异常，无法读取 message.content。") from exc


def test_config() -> dict[str, object]:
    cfg = load_config()
    text = _chat_completion(
        cfg,
        [
            {"role": "system", "content": "你是一个接口连通性测试助手。"},
            {"role": "user", "content": "只回复：OK"},
        ],
        max_tokens=20,
        temperature=0,
    )
    return {"ok": True, "reply": text[:100]}


def _fmt_time(ts: int | float | None) -> str:
    if ts is None:
        return ""
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d %H:%M:%S")
    except (OSError, OverflowError, ValueError):
        return str(ts)


def _bundle_overview(bundle: export_mod.RoomBundle) -> dict[str, object]:
    peak = max((s[1] for s in bundle.stats), default=0)
    last_pv = bundle.stats[-1][2] if bundle.stats else 0
    return {
        "room_id": bundle.rid,
        "nickname": bundle.nickname or bundle.rid,
        "transcript_segments": len(bundle.transcripts),
        "transcript_chars": sum(t.char_count for t in bundle.transcripts),
        "chat_count": len(bundle.chats),
        "event_counts": bundle.event_counts,
        "online_peak": peak,
        "platform_pv_latest": last_pv,
    }


def _load_bundles(rids: list[str]) -> list[export_mod.RoomBundle]:
    ids = [str(rid).strip() for rid in rids if str(rid).strip()]
    if not ids:
        raise AIReportError("请先选择至少一个主播。")
    speaker_labels = export_mod.load_speaker_labels()
    names = export_mod.room_display_names()
    bundles = [export_mod.build_bundle(rid, names.get(rid, ""), speaker_labels) for rid in ids]
    bundles = [b for b in bundles if b.transcripts]
    if not bundles:
        raise AIReportError("所选主播暂无已转写话术，不能生成复盘。")
    return bundles


def _transcript_line(room: export_mod.RoomBundle, item: export_mod.TranscriptRow) -> str:
    start = item.capture_start if item.capture_start is not None else item.segment_ts
    end = item.capture_end
    speaker = f"[{item.speaker_label}]" if item.speaker_label else ""
    text = (item.text or "").replace("\n", " ").strip()
    return (
        f"[{room.nickname or room.rid}][{_fmt_time(start)} - {_fmt_time(end)}]"
        f"{speaker} {text}"
    )


def _all_text(bundles: list[export_mod.RoomBundle], limit: int = 160_000) -> str:
    parts: list[str] = []
    total = 0
    for bundle in bundles:
        for item in bundle.transcripts:
            text = (item.text or "").replace("\n", " ").strip()
            if not text:
                continue
            line = _transcript_line(bundle, item)
            parts.append(line)
            total += len(line)
            if total >= limit:
                return "\n".join(parts)
    return "\n".join(parts)


def _plain_transcript_text(bundles: list[export_mod.RoomBundle], limit: int = 160_000) -> str:
    parts: list[str] = []
    total = 0
    for bundle in bundles:
        for item in bundle.transcripts:
            text = (item.text or "").replace("\n", " ").strip()
            if not text:
                continue
            parts.append(text)
            total += len(text)
            if total >= limit:
                return "\n".join(parts)
    return "\n".join(parts)


def _good_word(word: str) -> bool:
    if not (2 <= len(word) <= 8):
        return False
    if not re.fullmatch(r"[\u4e00-\u9fff]+", word):
        return False
    if word in _STOP_WORDS:
        return False
    if any(s in word for s in _STOP_SUBSTRINGS):
        return False
    if word[0] in _BAD_EDGE_CHARS or word[-1] in _BAD_EDGE_CHARS:
        return False
    return True


def _important_terms(text: str) -> list[str]:
    hits: list[str] = []
    for term in _IMPORTANT_TERMS:
        hits.extend([term] * len(re.findall(re.escape(term), text)))
    money_patterns = [
        r"\d+(?:\.\d+)?万(?:左右|多|起)?",
        r"\d+(?:\.\d+)?平(?:米)?",
        r"\d+(?:\.\d+)?%?",
        r"\d+房",
    ]
    for pattern in money_patterns:
        for m in re.findall(pattern, text):
            if 2 <= len(m) <= 8:
                hits.append(m)
    return hits


def _tokenize_words(text: str) -> list[str]:
    important = _important_terms(text)
    try:
        import jieba  # type: ignore

        words = important[:]
        for word in jieba.cut(text):
            word = str(word).strip()
            if _good_word(word):
                words.append(word)
        if words:
            return words
    except Exception:
        pass

    clean = re.sub(r"[^\u4e00-\u9fffA-Za-z0-9]+", "", text)
    words: list[str] = important[:]
    for n in (2, 3, 4):
        for i in range(0, max(0, len(clean) - n + 1)):
            word = clean[i:i + n]
            if _good_word(word):
                words.append(word)
    return words


def word_cloud(rids: list[str], limit: int = WORD_LIMIT) -> dict[str, object]:
    bundles = _load_bundles(rids)
    text = _plain_transcript_text(bundles)
    counter = Counter(_tokenize_words(text))
    words = [
        {"word": word, "count": count}
        for word, count in counter.most_common(max(1, min(200, limit)))
        if count >= 2
    ]
    max_count = words[0]["count"] if words else 0
    for item in words:
        item["weight"] = round(float(item["count"]) / float(max_count or 1), 4)
    return {
        "rooms": [_bundle_overview(b) for b in bundles],
        "words": words,
        "total_words": sum(counter.values()),
    }


def _local_brief(report: str, limit: int = 220) -> str:
    plain = re.sub(r"```[\s\S]*?```", " ", report or "")
    plain = re.sub(r"^#{1,6}\s*", "", plain, flags=re.M)
    plain = re.sub(r"[*_>`\-]+", "", plain)
    plain = re.sub(r"\s+", " ", plain).strip()
    if len(plain) <= limit:
        return plain or "报告已生成，请下载完整 PDF 查看。"
    brief = plain[:limit]
    brief = re.sub(r"[，。；、：,.!?！？][^，。；、：,.!?！？]*$", "", brief)
    return (brief or plain[:limit]).strip() + "…"


def _brief_report(cfg: AIConfig, report: str) -> str:
    if not cfg.ready:
        return _local_brief(report)
    system = (
        "你是直播复盘报告编辑。请把完整报告压缩成一段中文简报，"
        "必须控制在 180 到 220 个汉字左右，只保留结论、核心发现和最重要建议。"
        "不要写标题，不要 Markdown，不要寒暄，不要说“根据报告”。"
    )
    user = "完整报告如下：\n\n" + (report or "")[:30_000]
    try:
        brief = _chat_completion(
            cfg,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            temperature=0.2,
            max_tokens=500,
        )
    except AIReportError:
        return _local_brief(report)
    brief = re.sub(r"\s+", " ", brief).strip()
    brief = re.sub(r"^(好的|以下是|简报[:：]?|复盘简报[:：]?)\s*", "", brief)
    return _local_brief(brief, 230)


def _build_chunks(bundles: list[export_mod.RoomBundle]) -> tuple[list[dict[str, object]], bool]:
    chunks: list[dict[str, object]] = []
    truncated = False
    current_lines: list[str] = []
    current_rooms: set[str] = set()
    current_chars = 0

    def flush() -> None:
        nonlocal current_lines, current_rooms, current_chars
        if not current_lines:
            return
        chunks.append({
            "rooms": sorted(current_rooms),
            "text": "\n".join(current_lines),
            "char_count": current_chars,
        })
        current_lines = []
        current_rooms = set()
        current_chars = 0

    for bundle in bundles:
        for item in bundle.transcripts:
            line = _transcript_line(bundle, item)
            if current_lines and current_chars + len(line) > CHUNK_CHAR_LIMIT:
                flush()
                if len(chunks) >= MAX_CHUNKS:
                    truncated = True
                    return chunks, truncated
            current_lines.append(line)
            current_rooms.add(bundle.rid)
            current_chars += len(line)
    flush()
    if len(chunks) > MAX_CHUNKS:
        truncated = True
        chunks = chunks[:MAX_CHUNKS]
    return chunks, truncated


def _json_from_text(text: str) -> dict[str, object]:
    raw = text.strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.I)
        raw = re.sub(r"\s*```$", "", raw)
    try:
        data = json.loads(raw)
    except ValueError:
        m = re.search(r"\{[\s\S]*\}", raw)
        if not m:
            raise
        data = json.loads(m.group(0))
    if not isinstance(data, dict):
        raise ValueError("JSON root must be object")
    return data


def _normalize_summary(data: dict[str, object]) -> dict[str, object]:
    keys = {
        "themes": [],
        "selling_points": [],
        "prices": [],
        "promotions": [],
        "audience_questions": [],
        "risk_claims": [],
        "evidence": [],
    }
    out: dict[str, object] = {}
    for key, default in keys.items():
        value = data.get(key, default)
        out[key] = value if isinstance(value, list) else default
    out["summary"] = str(data.get("summary") or "").strip()
    return out


def _summarize_chunk(cfg: AIConfig, chunk: dict[str, object]) -> dict[str, object]:
    system = (
        "你是直播复盘分析师。只根据用户给出的直播转写证据做结构化提取，"
        "不能编造价格、活动、产品名。输出必须是 JSON，不要 Markdown。"
    )
    schema_hint = (
        "返回 JSON 对象，字段：summary 字符串；themes/selling_points/prices/"
        "promotions/audience_questions/risk_claims/evidence 均为数组。"
        "evidence 每项包含 time、quote、type。quote 必须来自输入原文。"
    )
    user = f"{schema_hint}\n\n直播转写片段：\n{chunk['text']}"
    for attempt in range(2):
        content = _chat_completion(
            cfg,
            [{"role": "system", "content": system}, {"role": "user", "content": user}],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=2200,
        )
        try:
            return _normalize_summary(_json_from_text(content))
        except ValueError:
            user = "上一次输出不是合法 JSON。请只返回 JSON 对象，不要解释。\n\n" + user
            if attempt == 1:
                raise AIReportError("AI 分段摘要不是合法 JSON，重试后仍失败。")
    raise AIReportError("AI 分段摘要失败。")


def _local_fallback_summary(chunk: dict[str, object]) -> dict[str, object]:
    lines = str(chunk.get("text") or "").splitlines()
    evidence = []
    for line in lines[:5]:
        evidence.append({"time": line[0:32], "quote": line[-180:], "type": "原文样本"})
    return {
        "summary": "本段保留原文样本，未调用 AI 结构化分析。",
        "themes": [],
        "selling_points": [],
        "prices": [],
        "promotions": [],
        "audience_questions": [],
        "risk_claims": [],
        "evidence": evidence,
    }


def _final_report(cfg: AIConfig, overviews: list[dict[str, object]], summaries: list[dict[str, object]], truncated: bool) -> str:
    system = (
        "你是严谨的直播竞品复盘顾问。根据结构化摘要生成中文 Markdown 报告。"
        "语气必须专业、克制、像咨询报告；禁止出现“好的”“老板”“以下是”“根据你提供”等对话式套话。"
        "第一行必须是 Markdown 一级标题。所有关键结论必须引用 evidence 中的时间或原文。"
        "不要编造不存在的信息。"
    )
    user = json.dumps(
        {
            "overviews": overviews,
            "chunk_summaries": summaries,
            "truncated": truncated,
            "required_sections": [
                "一、结论摘要",
                "二、核心卖点与话术结构",
                "三、价格/优惠/活动",
                "四、观众关注点",
                "五、风险话术",
                "六、可复用话术",
                "七、时间点证据",
                "八、后续建议",
            ],
        },
        ensure_ascii=False,
    )
    report = _chat_completion(
        cfg,
        [{"role": "system", "content": system}, {"role": "user", "content": user}],
        temperature=0.25,
        max_tokens=4200,
    )
    return _clean_report_markdown(report)


def _clean_report_markdown(text: str) -> str:
    raw = (text or "").strip()
    raw = re.sub(r"^```(?:markdown|md)?\s*", "", raw, flags=re.I)
    raw = re.sub(r"\s*```$", "", raw)
    lines = [line.rstrip() for line in raw.splitlines()]
    while lines and not lines[0].strip():
        lines.pop(0)
    junk_patterns = [
        r"^好的[，,、\s]*(老板|老[板闆])?[，,、\s]*",
        r"^老板[，,、\s]*",
        r"^以下是[^\n]*[:：]?\s*",
        r"^根据你提供的[^\n]*[:：]?\s*",
        r"^---+$",
    ]
    while lines:
        first = lines[0].strip()
        changed = False
        for pat in junk_patterns:
            new_first = re.sub(pat, "", first, flags=re.I)
            if new_first != first:
                if new_first:
                    lines[0] = new_first
                else:
                    lines.pop(0)
                changed = True
                break
        if not changed:
            break
    cleaned = "\n".join(lines).strip()
    if cleaned and not cleaned.startswith("#"):
        cleaned = "# AI 直播复盘报告\n\n" + cleaned
    return cleaned + "\n"


def _fallback_markdown(overviews: list[dict[str, object]], summaries: list[dict[str, object]], truncated: bool) -> str:
    lines = ["# AI 直播复盘报告", ""]
    lines.append("> 该报告为本地兜底版本，未完成 AI 总结。")
    if truncated:
        lines.append("> 注意：本次只处理了前半部分文本，完整长直播需分批继续分析。")
    lines += ["", "## 数据概览"]
    for item in overviews:
        lines.append(
            f"- {item['nickname']}：话术 {item['transcript_segments']} 段，"
            f"{item['transcript_chars']} 字，弹幕 {item['chat_count']} 条，"
            f"在线峰值 {item['online_peak']}"
        )
    lines += ["", "## 原文证据样本"]
    for idx, summary in enumerate(summaries, start=1):
        lines.append(f"### 片段 {idx}")
        for ev in summary.get("evidence", [])[:5]:
            if isinstance(ev, dict):
                lines.append(f"- {ev.get('time', '')}：{ev.get('quote', '')}")
    return "\n".join(lines) + "\n"


def _safe_report_name(base: str) -> str:
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", base).strip().rstrip(" .")
    return (stem or "AI复盘")[:80]


def _markdown_to_pdf(markdown: str, path: Path) -> None:
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.pdfbase import pdfmetrics
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont
        from reportlab.platypus import PageBreak, Paragraph, SimpleDocTemplate, Spacer
    except Exception as exc:  # pragma: no cover - dependency is environment-specific
        raise AIReportError("缺少 PDF 生成依赖 reportlab，请安装后重新生成报告。") from exc

    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    font = "STSong-Light"
    styles = getSampleStyleSheet()
    base = ParagraphStyle(
        "LiveWatchBase",
        parent=styles["Normal"],
        fontName=font,
        fontSize=10.5,
        leading=17,
        textColor=colors.HexColor("#1f2937"),
        alignment=TA_LEFT,
        spaceAfter=5,
    )
    h1 = ParagraphStyle(
        "LiveWatchH1",
        parent=base,
        fontSize=18,
        leading=24,
        textColor=colors.HexColor("#111827"),
        spaceBefore=4,
        spaceAfter=12,
    )
    h2 = ParagraphStyle(
        "LiveWatchH2",
        parent=base,
        fontSize=14,
        leading=20,
        textColor=colors.HexColor("#111827"),
        spaceBefore=12,
        spaceAfter=7,
    )
    h3 = ParagraphStyle(
        "LiveWatchH3",
        parent=base,
        fontSize=12,
        leading=18,
        textColor=colors.HexColor("#374151"),
        spaceBefore=9,
        spaceAfter=5,
    )
    bullet = ParagraphStyle(
        "LiveWatchBullet",
        parent=base,
        leftIndent=12,
        firstLineIndent=-8,
    )
    quote = ParagraphStyle(
        "LiveWatchQuote",
        parent=base,
        leftIndent=8,
        textColor=colors.HexColor("#475569"),
        backColor=colors.HexColor("#f7faff"),
        borderColor=colors.HexColor("#d8e3f5"),
        borderWidth=0.5,
        borderPadding=5,
    )

    def inline_md(text: str) -> str:
        escaped = html.escape(text.strip())
        escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
        return escaped

    story: list[object] = []
    for raw in (markdown or "").replace("\r", "").split("\n"):
        line = raw.strip()
        if not line:
            story.append(Spacer(1, 3))
            continue
        if line == "---":
            story.append(Spacer(1, 8))
            continue
        if line.startswith("# "):
            if story:
                story.append(Spacer(1, 4))
            story.append(Paragraph(inline_md(line[2:]), h1))
        elif line.startswith("## "):
            story.append(Paragraph(inline_md(line[3:]), h2))
        elif line.startswith("### "):
            story.append(Paragraph(inline_md(line[4:]), h3))
        elif line.startswith(">"):
            story.append(Paragraph(inline_md(line.lstrip("> ")), quote))
        elif re.match(r"^[-*]\s+", line):
            story.append(Paragraph("• " + inline_md(re.sub(r"^[-*]\s+", "", line)), bullet))
        else:
            story.append(Paragraph(inline_md(line), base))

    if not story:
        story.append(Paragraph("报告为空。", base))

    path.parent.mkdir(parents=True, exist_ok=True)
    doc = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=path.stem,
    )
    doc.build(story)


def generate_report(rids: list[str]) -> dict[str, object]:
    bundles = _load_bundles(rids)
    cfg = load_config()
    chunks, truncated = _build_chunks(bundles)
    if not chunks:
        raise AIReportError("没有可分析的话术文本。")

    overviews = [_bundle_overview(b) for b in bundles]
    summaries: list[dict[str, object]] = []
    for chunk in chunks:
        if cfg.ready:
            summaries.append(_summarize_chunk(cfg, chunk))
        else:
            summaries.append(_local_fallback_summary(chunk))

    if cfg.ready:
        try:
            report = _final_report(cfg, overviews, summaries, truncated)
        except AIReportError:
            report = _fallback_markdown(overviews, summaries, truncated)
    else:
        report = _fallback_markdown(overviews, summaries, truncated)

    title = "、".join((b.nickname or b.rid) for b in bundles[:3])
    if len(bundles) > 3:
        title += f"等{len(bundles)}个主播"
    filename = _safe_report_name(f"AI复盘_{title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}") + ".md"
    config.AI_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.AI_REPORT_DIR / filename
    path.write_text(report, encoding="utf-8")
    brief = _brief_report(cfg, report)
    pdf_filename = filename[:-3] + ".pdf"
    pdf_path = config.AI_REPORT_DIR / pdf_filename
    _markdown_to_pdf(report, pdf_path)
    return {
        "ok": True,
        "path": str(path),
        "pdf_path": str(pdf_path),
        "dir": str(path.parent),
        "filename": filename,
        "pdf_filename": pdf_filename,
        "rooms": len(bundles),
        "chunks": len(chunks),
        "truncated": truncated,
        "used_ai": cfg.ready,
        "brief": brief,
        "preview": report[:4000],
    }


def generate_report_events(rids: list[str]) -> Iterator[dict[str, object]]:
    started = time.time()
    yield {"type": "start", "message": "开始读取本地直播数据", "progress": 3}
    bundles = _load_bundles(rids)
    overviews = [_bundle_overview(b) for b in bundles]
    words_payload = word_cloud([b.rid for b in bundles], limit=60)
    yield {
        "type": "evidence",
        "message": f"已载入 {len(bundles)} 个主播、{sum(len(b.transcripts) for b in bundles)} 段话术",
        "progress": 10,
        "rooms": overviews,
        "words": words_payload["words"],
    }

    cfg = load_config()
    chunks, truncated = _build_chunks(bundles)
    if not chunks:
        raise AIReportError("没有可分析的话术文本。")
    summaries: list[dict[str, object]] = []
    total = len(chunks)
    for idx, chunk in enumerate(chunks, start=1):
        yield {
            "type": "chunk_start",
            "message": f"正在分析第 {idx}/{total} 个文本块",
            "progress": 10 + int(idx / max(total, 1) * 58),
            "chunk": idx,
            "chunks": total,
        }
        if cfg.ready:
            summary = _summarize_chunk(cfg, chunk)
        else:
            summary = _local_fallback_summary(chunk)
        summaries.append(summary)
        yield {
            "type": "chunk_done",
            "message": f"第 {idx}/{total} 个文本块分析完成",
            "progress": 14 + int(idx / max(total, 1) * 58),
            "chunk": idx,
            "summary": summary.get("summary", ""),
        }

    yield {"type": "final_start", "message": "正在汇总结论并生成复盘报告", "progress": 78}
    if cfg.ready:
        try:
            report = _final_report(cfg, overviews, summaries, truncated)
            used_ai = True
        except AIReportError as exc:
            yield {"type": "warning", "message": f"AI 终稿生成失败，改用本地证据草稿：{exc}", "progress": 82}
            report = _fallback_markdown(overviews, summaries, truncated)
            used_ai = False
    else:
        report = _fallback_markdown(overviews, summaries, truncated)
        used_ai = False

    yield {"type": "brief_start", "message": "正在压缩生成 200 字复盘简报", "progress": 90}
    brief = _brief_report(cfg, report)
    title = "、".join((b.nickname or b.rid) for b in bundles[:3])
    if len(bundles) > 3:
        title += f"等{len(bundles)}个主播"
    filename = _safe_report_name(f"AI复盘_{title}_{datetime.now().strftime('%Y%m%d_%H%M%S')}") + ".md"
    config.AI_REPORT_DIR.mkdir(parents=True, exist_ok=True)
    path = config.AI_REPORT_DIR / filename
    path.write_text(report, encoding="utf-8")
    pdf_filename = filename[:-3] + ".pdf"
    pdf_path = config.AI_REPORT_DIR / pdf_filename
    _markdown_to_pdf(report, pdf_path)
    elapsed = round(time.time() - started, 1)
    yield {
        "type": "done",
        "message": f"复盘完成，用时 {elapsed} 秒",
        "progress": 100,
        "ok": True,
        "path": str(path),
        "pdf_path": str(pdf_path),
        "dir": str(path.parent),
        "filename": filename,
        "pdf_filename": pdf_filename,
        "rooms": len(bundles),
        "chunks": len(chunks),
        "truncated": truncated,
        "used_ai": used_ai,
        "brief": brief,
        "preview": report[:8000],
    }


def answer_question(rids: list[str], messages: list[dict[str, str]]) -> dict[str, object]:
    bundles = _load_bundles(rids)
    cfg = load_config()
    if not cfg.ready:
        raise AIReportError("AI 尚未配置，无法追问。")
    safe_messages: list[dict[str, str]] = []
    for msg in messages[-10:]:
        role = msg.get("role") if isinstance(msg, dict) else ""
        content = str(msg.get("content") or "")[:2000] if isinstance(msg, dict) else ""
        if isinstance(msg, dict) and msg.get("thinking"):
            continue
        if content.strip() in {"AI 正在思考", "AI正在思考"}:
            continue
        if role in {"user", "assistant"} and content.strip():
            safe_messages.append({"role": role, "content": content.strip()})
    if not safe_messages or safe_messages[-1]["role"] != "user":
        raise AIReportError("请输入要追问的问题。")
    evidence = _all_text(bundles, limit=45_000)
    overview = json.dumps([_bundle_overview(b) for b in bundles], ensure_ascii=False)
    word_data = json.dumps(word_cloud([b.rid for b in bundles], limit=40)["words"], ensure_ascii=False)
    system = (
        "你是直播复盘侠的直播复盘智能体。你只能根据提供的本地直播证据回答，"
        "如果证据不足就明确说证据不足。回答要给出可追溯的时间点或原话。"
    )
    context = (
        f"主播概览：{overview}\n\n"
        f"高频词：{word_data}\n\n"
        f"直播转写证据（可能截断）：\n{evidence}"
    )
    content = _chat_completion(
        cfg,
        [{"role": "system", "content": system}, {"role": "user", "content": context}] + safe_messages,
        temperature=0.25,
        max_tokens=2600,
    )
    return {"ok": True, "answer": content}
