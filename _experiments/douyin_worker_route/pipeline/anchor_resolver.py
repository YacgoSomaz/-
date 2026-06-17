"""主播分享链接解析：把用户粘贴的各种抖音输入归一成「主播身份」。

支持输入形态：
  1. 完整抖音分享文案（混杂表情/话题/口令/噪声）
  2. v.douyin.com 短链（需跟随跳转才能拿到真实地址）
  3. live.douyin.com 直播链接
  4. 抖音主播主页链接 www.douyin.com/user/<sec_uid>
  5. 旧版纯数字直播号（web_rid）

设计原则（与本仓既有风控红线一致）：
  - 只做「读」：跟随短链跳转 + 可选地 GET 一次落地页提字段。绝不调用弹幕 / 音频流 /
    a_bogus 等签名接口，绝不保存或改写任何 Cookie 文件，本次请求用的临时会话用完即弃。
  - 防 SSRF：手动逐跳跟随跳转，每一跳都先校验主机在抖音域白名单内才请求；越界跳转直接停在
    当前 URL 不再跟随；跳转次数有硬上限；每个请求都带超时，绝不无限重试。
  - 解析尽力而为：昵称 / 头像 / room_id / is_live 取不到就留空，不抛异常；只有「输入里压根
    找不到抖音链接也不是纯数字直播号」才抛 AnchorResolveError，给接入层一个明确信号。

入口：resolve_anchor(user_input, timeout_sec=10) -> ResolvedAnchor
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urljoin, urlsplit

import requests

from .runtime_health import classify_room_page

log = logging.getLogger(__name__)

# 抖音相关域白名单（registrable domain）。短链最终多落在 iesdouyin / amemv 的分享域。
_ALLOWED_DOMAINS = ("douyin.com", "iesdouyin.com", "amemv.com")

_MAX_REDIRECTS = 5            # 短链跳转硬上限，防跳转环 / 放大型 SSRF
_REDIRECT_STATUS = (301, 302, 303, 307, 308)
_LIVE_BASE = "https://live.douyin.com/"

from .fingerprint import USER_AGENT as _UA, PAGE_HEADERS as _FP_HEADERS

_HEADERS = dict(_FP_HEADERS)
_HEADERS["Referer"] = _LIVE_BASE

# 从混杂文本里抓第一个抖音 URL：允许省略 scheme，主机必须落在抖音域上。
# 字符类排除空白与中文标点，避免把后面的「1@9.com :0pm」之类噪声粘进来。
_URL_RE = re.compile(
    r"(?:https?://)?(?:[\w-]+\.)*(?:douyin|iesdouyin|amemv)\.com/[^\s一-鿿，。！？、；：）】》「」]*",
    re.I,
)
# 抖音分享文案常把昵称放在【】里，作为无网络时的昵称兜底。
_NAME_RE = re.compile(r"【([^】]{1,40})】")
# sec_user_id 形如 MS4wLjABAAAA...，包含字母数字下划线和连字符。
_SEC_UID_RE = re.compile(r"(MS4w[\w-]{6,})")


class AnchorResolveError(ValueError):
    """输入里找不到任何可用的抖音链接或直播号——给接入层一个明确的失败信号。"""


@dataclass(frozen=True)
class ResolvedAnchor:
    original_input: str
    source_url: str
    anchor_name: str | None
    avatar_url: str | None
    sec_user_id: str | None
    web_id: str | None
    room_id: str | None
    is_live: bool | None


def resolve_anchor(
    user_input: str,
    timeout_sec: int = 10,
    *,
    session: requests.Session | None = None,
    fetch_page: bool = True,
    cookie_header: str = "",
) -> ResolvedAnchor:
    """把一段用户输入解析成 ResolvedAnchor。

    timeout_sec 同时作用于每一跳跳转与落地页抓取。session/fetch_page 为可选注入点：
    测试传入假 session 即可全程零真实网络；fetch_page=False 时只做离线结构化解析。
    """
    if not user_input or not user_input.strip():
        raise AnchorResolveError("输入为空")

    text = user_input.strip()
    start_url = _extract_url(text)
    if start_url is None:
        numeric = _extract_numeric_id(text)
        if numeric is None:
            raise AnchorResolveError("未在输入中找到抖音链接或直播号")
        start_url = f"{_LIVE_BASE}{numeric}"

    name_hint = _name_from_text(text)

    final_url = start_url
    page_html = ""
    failures: list[str] = []
    if fetch_page:
        sess = session or requests.Session()
        if session is None:
            from .proxy_conf import requests_proxies
            _px = requests_proxies()
            if _px:
                sess.proxies.update(_px)
        try:
            final_url, page_html, failures = _follow(
                start_url, timeout_sec, sess, cookie_header=cookie_header
            )
        finally:
            if session is None:  # 只关闭自建会话；注入的会话由调用方掌控生命周期。
                _safe_close(sess)

    fields = _classify(final_url)
    page = _parse_page(page_html, failures) if page_html else {}

    if failures:
        log.debug("anchor 解析降级：input=%r failures=%s", text[:60], failures)

    return ResolvedAnchor(
        original_input=user_input,
        source_url=final_url,
        anchor_name=page.get("nickname") or name_hint,
        avatar_url=page.get("avatar_url"),
        sec_user_id=fields.get("sec_user_id") or page.get("sec_user_id"),
        web_id=fields.get("web_id"),
        room_id=fields.get("room_id") or page.get("room_id"),
        is_live=page.get("is_live"),
    )


# ---------------------------------------------------------------- 文本提取

def _extract_url(text: str) -> str | None:
    """抓混杂文本里的第一个抖音 URL；补全 scheme 并清掉尾部黏连的标点。"""
    m = _URL_RE.search(text)
    if not m:
        return None
    url = m.group(0).rstrip(".,;)]'\"")
    if not url.lower().startswith(("http://", "https://")):
        url = "https://" + url
    return url


def _extract_numeric_id(text: str) -> str | None:
    """旧版纯数字直播号：整段去空白后是 6~19 位数字才认，避免从散文里乱捞数字。"""
    t = text.strip()
    return t if t.isdigit() and 6 <= len(t) <= 19 else None


def _name_from_text(text: str) -> str | None:
    m = _NAME_RE.search(text)
    if not m:
        return None
    name = m.group(1).strip()
    return name or None


# ---------------------------------------------------------------- 跳转跟随（SSRF 防护）

def _host_of(url: str) -> str:
    try:
        return (urlsplit(url).hostname or "").lower()
    except ValueError:
        return ""


def _host_allowed(host: str) -> bool:
    host = (host or "").lower().strip(".")
    return any(host == d or host.endswith("." + d) for d in _ALLOWED_DOMAINS)


def _follow(
    start_url: str,
    timeout_sec: int,
    session: requests.Session,
    *,
    cookie_header: str = "",
) -> tuple[str, str, list[str]]:
    """逐跳跟随跳转，返回 (落地 URL, 落地页正文, 失败原因列表)。

    每跳前先校验主机白名单：越界则停在当前 URL、不再请求；只有命中白名单的主机才发起请求。
    非跳转响应即落地，读其正文用于提字段；任何网络异常都记录并降级返回，绝不抛出。
    """
    failures: list[str] = []
    url = start_url
    for _ in range(_MAX_REDIRECTS + 1):
        if not _host_allowed(_host_of(url)):
            failures.append(f"off_domain_blocked:{_host_of(url)}")
            return url, "", failures
        try:
            headers = dict(_HEADERS)
            if cookie_header:
                headers["Cookie"] = cookie_header
            resp = session.get(url, allow_redirects=False, timeout=timeout_sec, headers=headers)
        except Exception as exc:  # noqa: BLE001  网络层任何异常都降级，不让解析崩。
            failures.append(f"request_error:{type(exc).__name__}")
            return url, "", failures

        status = int(getattr(resp, "status_code", 0) or 0)
        if status in _REDIRECT_STATUS:
            location = _header(resp, "Location")
            if not location:
                failures.append("redirect_without_location")
                return url, "", failures
            nxt = urljoin(url, location)
            if not _host_allowed(_host_of(nxt)):
                # 越界跳转：停在当前 URL，绝不请求站外地址。
                failures.append(f"off_domain_blocked:{_host_of(nxt)}")
                return url, "", failures
            url = nxt
            continue
        return url, getattr(resp, "text", "") or "", failures

    failures.append("too_many_redirects")
    return url, "", failures


def _header(resp: object, name: str) -> str:
    headers = getattr(resp, "headers", None)
    if headers is None:
        return ""
    getter = getattr(headers, "get", None)
    if getter is None:
        return ""
    return getter(name) or getter(name.lower()) or ""


def _safe_close(session: requests.Session) -> None:
    try:
        session.close()
    except Exception:  # noqa: BLE001
        pass


# ---------------------------------------------------------------- URL 结构化解析

def _classify(url: str) -> dict[str, str]:
    """从落地 URL 的路径与查询串提取 web_id / room_id / sec_user_id（无网络）。"""
    out: dict[str, str] = {}
    parts = urlsplit(url)
    host = (parts.hostname or "").lower()
    path = parts.path or ""
    qs = parse_qs(parts.query or "")

    for key in ("room_id", "room_id_str"):
        if qs.get(key):
            out["room_id"] = qs[key][0]
            break
    for key in ("sec_user_id", "sec_uid"):
        if qs.get(key):
            out["sec_user_id"] = qs[key][0]
            break
    if qs.get("web_rid"):
        out["web_id"] = qs["web_rid"][0]

    m = re.search(r"/(?:share/)?user/(MS4w[\w-]+)", path)
    if m:
        out.setdefault("sec_user_id", m.group(1))
    m = re.search(r"/(?:share/live|webcast/reflow)/(\d+)", path)
    if m:
        out.setdefault("room_id", m.group(1))
    if "live.douyin.com" in host:
        m = re.match(r"^/(\d+)", path)
        if m:
            out.setdefault("web_id", m.group(1))

    if "sec_user_id" not in out:
        m = _SEC_UID_RE.search(url)
        if m:
            out["sec_user_id"] = m.group(1)
    return out


# ---------------------------------------------------------------- 落地页尽力解析

_CHALLENGE_MARKERS = (
    "captcha",
    "verifycenter",
    "verify-center",
    "security verification",
    "安全验证",
    "滑块验证",
)
_ENDED_MARKERS = ("直播已结束", "本场直播已结束", "已下播")

_ROOMID_RES = (
    re.compile(r'"roomId"\s*:\s*"(\d+)"'),
    re.compile(r'roomId\\":\\"(\d+)'),
)
_NICK_RES = (
    re.compile(r'"nickname"\s*:\s*"([^"]{1,40})"'),
    re.compile(r'nickname\\":\\"([^"\\]{1,40})'),
    re.compile(r'"anchor"\s*:\s*\{.*?"nickname"\s*:\s*"([^"]{1,80})"', re.DOTALL),
    re.compile(r'anchor\\":\{.*?nickname\\":\\"([^"\\]{1,80})', re.DOTALL),
)
_AVATAR_RES = (
    re.compile(r'"avatar_thumb"\s*:\s*\{.*?"url_list"\s*:\s*\[\s*"([^"]+)"', re.DOTALL),
    re.compile(r'avatar_thumb\\":\{.*?url_list\\":\[\\"([^"\\]+)', re.DOTALL),
    re.compile(r'"avatarThumb"\s*:\s*\{.*?"urlList"\s*:\s*\[\s*"([^"]+)"', re.DOTALL),
)
_STATUS_RES = (
    re.compile(r'"roomStore"\s*:\s*\{.*?"roomInfo"\s*:\s*\{.*?"room"\s*:\s*\{.*?"status"\s*:\s*(\d+)', re.DOTALL),
    re.compile(r'roomStore\\":\{.*?roomInfo\\":\{.*?room\\":\{.*?status\\":(\d+)', re.DOTALL),
    re.compile(r'roomStore.*?roomInfo.*?room.*?status"?\s*:\s*(\d+)', re.DOTALL),
)


def _looks_like_challenge(html: str) -> bool:
    return classify_room_page(html) == "challenge"


def _parse_page(html: str, failures: list[str]) -> dict[str, object]:
    """尽力从落地页 HTML 提 room_id / 昵称 / 头像 / 是否在播；命中验证墙直接放弃。"""
    if _looks_like_challenge(html):
        failures.append("challenge_page")
        return {}

    normalized = _decode_page_value(html)
    out: dict[str, object] = {}
    out.update(_first_group(normalized, _ROOMID_RES, "room_id"))
    nickname = _first_valid_match(normalized, _NICK_RES)
    if nickname:
        out["nickname"] = _decode_page_value(nickname)
    avatar = _first_match(normalized, _AVATAR_RES)
    if avatar:
        out["avatar_url"] = _decode_page_value(avatar)

    if any(marker in normalized for marker in _ENDED_MARKERS):
        out["is_live"] = False
    else:
        status = _first_match(normalized, _STATUS_RES)
        if status is not None:
            out["is_live"] = status == "2"
    return out


def _first_group(html: str, patterns: tuple[re.Pattern, ...], key: str) -> dict[str, str]:
    for pat in patterns:
        m = pat.search(html)
        if m:
            return {key: _decode_page_value(m.group(1))}
    return {}


def _first_match(html: str, patterns: tuple[re.Pattern, ...]) -> str | None:
    for pat in patterns:
        m = pat.search(html)
        if m:
            return m.group(1)
    return None


def _first_valid_match(html: str, patterns: tuple[re.Pattern, ...]) -> str | None:
    """Return the first meaningful metadata value, skipping page placeholders."""
    invalid = {"undefined", "$undefined", "null", "none", ""}
    for pat in patterns:
        for match in pat.finditer(html):
            value = _decode_page_value(match.group(1)).strip()
            if value.lower() not in invalid and not value.startswith("$"):
                return value
    return None


def _decode_page_value(value: str) -> str:
    return (
        value.replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("\\/", "/")
        .replace('\\"', '"')
    )
