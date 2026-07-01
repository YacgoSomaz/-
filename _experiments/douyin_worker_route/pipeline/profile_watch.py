"""匿名 headless 渲染抖音主页，判断主播是否开播并提取直播号(web_rid)。

专供「待开播」主播的开播探测使用。未开播主播只有主页链接（www.douyin.com/user/<sec_uid>），
而主页的 HTML 是纯 JS 引导壳（requests 抓不到任何字段），直播号也只在开播时才公开。本模块
用浏览器真实渲染主页，开播时主页会出现指向直播间的链接 live.douyin.com/<直播号>，从中抠号。

风控设计（与本仓红线一致）：
  - 注入已铸好的信任 cookie（与主程序到处复用的同一套），headless 渲染才能过抖音反爬挑战；
    实测匿名 headless 必被验证页拦截。用同一信任 cookie 看公开主页，不增加新的账号暴露面。
  - 公开主页防护弱于直播间，配合信任 cookie 可用 headless（无可见窗口骚扰，区别于铸 cookie 的有头浏览器）。
  - 只读导航：只渲染主页、读 DOM。绝不拉弹幕/音频流、不调 a_bogus 签名接口、不保存改写 cookie。
  - 调用方负责长间隔 + 串行 + 数量上限 + 撞验证页全局冷却，本模块只做单次探测。

入口：check_profile(sec_user_id, timeout_sec, cookie_jar) -> dict
返回：{"ok","is_live","web_id","nickname","avatar_url","state"}
  state ∈ {"live","offline","challenge","error"}
"""

from __future__ import annotations

import logging
import re

from .fingerprint import USER_AGENT as _UA

log = logging.getLogger(__name__)

_PROFILE_BASE = "https://www.douyin.com/user/"

# 只认「路径形式」的直播间链接 live.douyin.com/<直播号>，该号即本主播的 web_rid。
# 关键：主播未开播时主页只有无数字的导航链 live.douyin.com/?from_nav=1（不匹配）；侧边栏
# 推荐的别的主播用的是查询形式 douyin.com/handle?web_rid=...（也不匹配）。只有本人开播时
# 头像直播徽章才会给出 live.douyin.com/<数字> 路径链——实测离线主页该形式为零，避免抓错人。
_LIVE_LINK_RE = re.compile(r"live\.douyin\.com/(\d{5,})")
# 真验证页标记：必须是页面可见文本里的「安全验证/滑块验证」，不是预加载的 captcha 脚本名
#（主页正常也会内联 captcha/VerifyCenter 脚本，绝不能据此判验证页，否则永远误判）。
_REAL_CHALLENGE_MARKERS = ("安全验证", "滑块验证", "拖动滑块", "完成安全验证")


def _content_safe(page) -> str:
    try:
        return page.content()
    except Exception:  # noqa: BLE001  渲染/导航途中 content() 可能撞导航
        return ""


def _body_text(page) -> str:
    try:
        return (page.eval_on_selector("body", "el => el.innerText") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _extract_web_rid(page, html: str) -> str:
    """提本主播直播号：优先读 DOM 里的直播间链接，再退回正文路径形式正则。只认路径形式。"""
    try:
        for el in page.query_selector_all('a[href*="live.douyin.com/"]'):
            m = _LIVE_LINK_RE.search(el.get_attribute("href") or "")
            if m:
                return m.group(1)
    except Exception:  # noqa: BLE001
        pass
    m = _LIVE_LINK_RE.search(html)
    return m.group(1) if m else ""


def _nickname_from_title(title: str) -> str:
    """从主页标题取本主播昵称：标题形如「<昵称>的抖音 - 抖音」「<昵称>的主页 - 抖音」。

    只用标题、不碰 HTML 里的 "nickname" 字段——后者会混入侧边栏推荐主播的昵称。
    """
    title = (title or "").strip()
    if title.endswith(" - 抖音"):
        title = title[: -len(" - 抖音")].strip()
    for suffix in ("的抖音", "的主页"):
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()
            break
    return "" if title in ("", "抖音") else title


def _cookie_records(cookie_jar: dict[str, str] | None) -> list[dict[str, str]]:
    """把 name->value 的信任 cookie 转成 playwright add_cookies 需要的记录，绑到 .douyin.com。"""
    if not cookie_jar:
        return []
    return [
        {"name": k, "value": v, "domain": ".douyin.com", "path": "/"}
        for k, v in cookie_jar.items()
        if k and v
    ]


def check_profile(
    sec_user_id: str,
    timeout_sec: int = 25,
    cookie_jar: dict[str, str] | None = None,
) -> dict[str, object]:
    """渲染一次主播主页，返回开播状态与直播号。任何异常都降级返回，绝不抛出。

    cookie_jar：已铸好的信任 cookie（browser_cookies.cached_jar()）。headless 渲染抖音必须带它过挑战。
    """
    out: dict[str, object] = {
        "ok": False,
        "is_live": None,
        "web_id": "",
        "nickname": "",
        "avatar_url": "",
        "state": "error",
    }
    sec_user_id = (sec_user_id or "").strip()
    if not sec_user_id:
        return out

    try:
        from playwright.sync_api import sync_playwright
    except Exception:  # noqa: BLE001  打包缺 playwright 时不让轮询线程崩
        log.debug("profile_watch: playwright 不可用")
        return out

    url = _PROFILE_BASE + sec_user_id
    with sync_playwright() as p:
        browser = None
        try:
            browser = p.chromium.launch(headless=True)
        except Exception:  # noqa: BLE001
            return out
        try:
            ctx = browser.new_context(user_agent=_UA, viewport={"width": 1280, "height": 800})
            records = _cookie_records(cookie_jar)
            if records:
                try:
                    ctx.add_cookies(records)
                except Exception:  # noqa: BLE001  cookie 注入失败不致命，继续尝试渲染
                    pass
            page = ctx.new_page()
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=timeout_sec * 1000)
            except Exception:  # noqa: BLE001  导航超时/被拒：本次探测失败，留待下轮
                return out

            # 轮询渲染：先等本主播昵称（标题）出现说明主页已渲染好；其间一旦发现路径形式
            # 直播链就判开播。「页面渲染好且无直播链」= 未开播；始终拿不到昵称才进一步判验证/失败。
            web_id = ""
            nickname = ""
            rounds = max(1, int(timeout_sec / 1.5))
            for _ in range(rounds):
                page.wait_for_timeout(1500)
                html = _content_safe(page)
                if not html:
                    continue
                web_id = _extract_web_rid(page, html)
                if web_id:
                    break
                if not nickname:
                    try:
                        nickname = _nickname_from_title(page.title() or "")
                    except Exception:  # noqa: BLE001
                        nickname = ""
                if nickname:
                    break  # 主页已渲染、本主播昵称已出，且无直播链 → 未开播

            if web_id:
                out.update(ok=True, is_live=True, web_id=web_id, nickname=nickname, state="live")
                return out
            if nickname:
                out.update(ok=True, is_live=False, nickname=nickname, state="offline")
                return out
            # 始终没渲染出主播信息：区分「真验证页」与「一时加载失败」，前者才升级全局冷却。
            out["state"] = "challenge" if any(m in _body_text(page) for m in _REAL_CHALLENGE_MARKERS) else "error"
            return out
        finally:
            try:
                browser.close()
            except Exception:  # noqa: BLE001
                pass
