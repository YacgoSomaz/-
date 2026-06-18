# LiveWatch 项目交接文档

## 一、项目是什么

**LiveWatch** 是一个个人自用的抖音直播监控工具。
- 非商业，仅用户本人使用
- 同时监听多个直播间：弹幕抓取 + 音频录制 + 语音转文字 + 导出 Excel
- 启动方式：双击 `LiveWatch.command`（macOS）或 `启动控制台.bat`（Windows）→ 浏览器打开 `http://127.0.0.1:8848` 操作

---

## 二、目录结构

```
live_watch/                          # git 仓库根
└── _experiments/
    └── douyin_worker_route/         # ← 主工作目录（8848 端口，所有改动只在这里）
        ├── pipeline/                # 核心模块
        │   ├── config.py            # 所有路径/参数常量
        │   ├── webui.py             # FastAPI 后端 + 所有 /api/* 路由
        │   ├── frontend.html        # Vue 3 前端（CDN，无需 npm）
        │   ├── manager.py           # RoomManager：房间启停、线程托管
        │   ├── orchestrator.py      # 一次性命令行版（非 Web 用）
        │   ├── audio_capture.py     # ffmpeg segment 录音
        │   ├── sensevoice_engine.py # SenseVoice ONNX 语音转文字
        │   ├── speaker_worker.py    # 3D-Speaker 声纹识别
        │   ├── transcript_store.py  # transcripts.db 读写
        │   ├── export.py            # Excel/CSV 导出
        │   ├── browser_cookies.py   # Playwright 铸信任 cookie
        │   ├── anchor_resolver.py   # 分享链接 → 主播身份解析
        │   ├── fingerprint.py       # 统一 UA/浏览器指纹头（防风控）
        │   ├── proxy_conf.py        # 代理配置（默认关闭）
        │   ├── diagnostics.py       # 健康诊断快照
        │   ├── runtime_health.py    # 错误注册 / 风控冷却
        │   ├── recorder_rotate.py   # segment 轮转
        │   └── static/              # Element Plus / Vue CDN 离线包
        ├── vendor/DouyinLiveWebFetcher/
        │   ├── liveMan.py           # WSS 弹幕长连（已改造，防风控）
        │   └── protobuf/douyin.py   # protobuf 解析（依赖 betterproto）
        ├── run_worker.py            # WorkerFetcher：弹幕抓取单房间入口
        ├── record_multi_audio.py    # 多房间音频录制
        ├── requirements.txt         # pip 依赖
        ├── LiveWatch.command        # macOS 双击启动（自动安装+启动）
        ├── setup_macos.sh           # macOS 首次安装脚本
        └── start_macos.command      # macOS 启动脚本（不含安装）
```

> `_experiments/douyin_live_run/`（8849 端口）是另一个独立沙盒，**永远不要碰它**，也不在 git 里。

---

## 三、绝对红线（必须遵守）

| 禁止事项 | 原因 |
|---------|------|
| 不得同一 cookie 拉同一房间两次 | 并发用同一账号会触发风控封号 |
| 不得提交 `browser_cookies.json` | 抖音登录会话凭证，泄露等同密码 |
| 不得提交 `*.db`、`audio/`、`rooms.json` | 用户数据，.gitignore 已排除 |
| 不得调用弹幕/音频/签名接口（在 anchor_resolver 里） | 仅解析主播身份，不触发取流 |
| 不得在 anchor_resolver 里保存或修改 cookie | 只用临时会话，用完即弃 |
| 不得自动绕过验证码/滑块 | 风控边界，必须手动完成 |
| 所有改动只在 `douyin_worker_route/`（8848）| 8849 那个目录在跑生产，绝不动 |
| 不得复制竞品（爱复盘）反编译代码 | 法律风险 |

---

## 四、运行方式

### Windows（开发）
```
启动控制台.bat   # 或 python -m pipeline.webui
```

### macOS（老板的 MacBook）
```bash
# 首次：
chmod +x setup_macos.sh && ./setup_macos.sh

# 之后双击 LiveWatch.command 即可
# 脚本会自动检测依赖完整性并补装，然后打开浏览器
```

### 环境变量（打包/生产用，开发态不需要）
```
LIVEWATCH_DATA_DIR      用户数据目录（cookie、db、audio、exports）
LIVEWATCH_RESOURCE_DIR  模型目录（sensevoice_onnx/、speaker/）
```

---

## 五、模型文件（不在 git 里）

| 模型 | 路径（开发态） | 大小 |
|-----|-------------|------|
| SenseVoice ONNX | `../asr_bench/sensevoice_onnx/model.int8.onnx` | 228 MB |
| tokens.txt | `../asr_bench/sensevoice_onnx/tokens.txt` | 0.3 MB |
| 3D-Speaker | `../speaker_change_analysis/models/3dspeaker_eres2net_zh_16k.onnx` | 37.8 MB |
| Silero VAD | `../speaker_change_analysis/models/silero_vad.onnx` | 0.6 MB |

macOS 打包版模型放在 `LiveWatch/models/sensevoice_onnx/` 和 `LiveWatch/models/speaker/` 下，`LIVEWATCH_RESOURCE_DIR` 指向 `LiveWatch/models/`。

---

## 六、数据库结构

| 数据库 | 内容 |
|--------|------|
| `transcripts.db` | 转写结果（speaker、text、start_ms、end_ms、rid 等） |
| `multi_events.db` | 弹幕/礼物/评论等直播事件（由 run_worker.py 写入） |
| `speaker_labels.db` | 声纹聚类标签 |

---

## 七、防风控设计（fingerprint.py）

所有 HTTP/WS 请求统一从 `pipeline/fingerprint.py` 取头：
- UA：Chrome 140 / Edge 140，平台自适应（Windows / macOS）
- `sec-ch-ua`、`sec-fetch-*` 与 UA 版本严格一致
- WSS 端点：从 5 个 webcast 服务器随机选取（`pick_wss_host()`）
- 心跳间隔：10s（原来是 5s，过于频繁）
- WebSocket `browser_version` 参数与 UA 匹配（之前 UA 是 140 但参数是 126，矛盾被识别）

代理支持：`proxy_conf.py`，默认关闭。有节点时在界面"网络与代理"填写，或写入 `DATA_DIR/proxy.txt`。

---

## 八、anchor_resolver 字段约定

```python
@dataclass
class ResolvedAnchor:
    source_url: str       # 原始输入 URL（分享链接或直播页）
    anchor_name: str      # 主播昵称（取不到为空串）
    avatar_url: str       # 头像 URL（取不到为空串）
    sec_user_id: str      # 抖音 sec_uid（取不到为空串）
    web_id: str           # 直播号（web_rid），即用户添加房间用的 ID ← 关键字段
    room_id: str          # room_id（与 web_id 不同，从直播页解析）
    is_live: bool | None  # True=在播，False=未播，None=未能判断
```

**重要**：`web_id` 就是 `web_rid`（直播号）。`is_live` 只有 `False` 或 `None`，永远不会返回 `True`（直播状态检测只做保守判断）。

---

## 九、当前未解决问题（需要下一个 AI 处理）

### 1. macOS Python 3.14 兼容性问题（紧急）

老板 MacBook 装的是 Python 3.14，导致 `betterproto` 等包无法安装。

**修复方案**：让老板安装 Python 3.12，并更新 `LiveWatch.command` 优先使用 `python3.12`：

```bash
# 让老板执行
brew install python@3.12
rm -rf ~/Downloads/.../LiveWatch/.venv
python3.12 -m venv ~/Downloads/.../LiveWatch/.venv
```

同时 `LiveWatch.command` 里的 venv 创建命令改为优先用 `python3.12`：
```bash
PY=$(command -v python3.12 || command -v python3.11 || command -v python3)
$PY -m venv "$VENV"
```

### 2. macOS 模型文件未打包

老板那边还没有 SenseVoice 和 3D-Speaker 模型，语音转文字功能不可用。需要把模型文件（约 267 MB）单独传给他，放到 `LiveWatch/models/` 下。

### 3. requirements.txt 包名已修正

`python-betterproto` → `betterproto`（已改，需重新发给老板）

---

## 十、Windows 打包流程（参考，不需要改）

1. 准备好空白 staging 目录（无 cookie、无 db、无音频）
2. 运行 `packaging/build.ps1`（PyInstaller + 模型复制 + Inno Setup）
3. 输出：`release/LiveWatchSetup_x.x.x.exe`（约 500MB，含 Python + 模型 + Chromium）
4. 安装后数据落在 `%LOCALAPPDATA%\LiveWatch\data\`，升级不丢数据

---

## 十一、git 历史

```
3e3fc3c feat: pipeline module, anti-risk-control, macOS support  ← 最新
d61a2f2 Separate worker route from dycast
23831ee Improve escaped m3u8 parsing
b9fcda4 Clarify route isolation and deploy status
015e2f1 Prefer signed m3u8 streams
```

所有核心代码已在 `3e3fc3c` 提交。如需回退，用 `git checkout d61a2f2 -- <file>`。

---

## 十二、与竞品的主要差距

竞品（爱复盘）用 CefSharp 嵌入 Chromium，DevTools WebSocket 拦截页面发起的 WSS，看起来完全是真浏览器。我们是自己构造 WSS 连接，风控辨别难度更高。

目前做的防风控措施：浏览器指纹头一致、WSS 端点随机、心跳优化、UA/browser_version 对齐。

下一步如果风控压力增大，可考虑：接入代理池（用户已有 Xray 节点）或研究 mitmproxy 拦截真实浏览器流量。
