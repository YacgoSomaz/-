# 故障定位与快速排错

更新时间：2026-07-16

本手册按“用户看到的现象”定位。不要先大范围重写；先确认状态、数据库证据和最小回归，再改对应模块。

## 1. 通用排错顺序

1. 确认当前运行的是源码进程还是已安装版本，记录版本号和端口。
2. 调用 `/api/status`、`/api/diagnostics`；若返回 401/403，先处理手机号登录 / 产品权益。
3. 检查 `%LOCALAPPDATA%\LiveWatch\data\logs\` 或开发态日志，但不要把日志提交 Git。
4. 确认 `events.db`、`transcripts.db`、媒体文件是否有新记录。
5. 用 [`FILE_MAP.md`](FILE_MAP.md) 找主文件和测试，先写 / 运行复现测试。
6. 修复后跑专项测试，再跑完整 `python -m pytest -q`。

## 2. 停止录制后工作台空白

已修复，防回归检查：

- `pipeline/manager.py` 停止或下播时是否调用 `TranscriptStore.complete_session`。
- `transcripts.db/recording_sessions` 是否存在正确 `started_ts / ended_ts`。
- 老数据是否能从 `recording_timeline` 连续片段推断。
- `/api/live-workbench` 是否返回 `phase=completed` 和独立 `session_id`。
- 前端下拉值必须是 `room.session_id`，不能只用 `rid`。

相关文件：`manager.py`、`transcript_store.py`、`live_workbench.py`、`frontend.html`。

回归：

```powershell
python -m pytest tests/test_live_workbench.py tests/test_video_preview.py tests/test_frontend_contract.py -q
```

## 3. 实时话术出现几天前 / 上一场内容

典型原因：只按房间 ID 查数据，没有按场次起止时间过滤，或把毫秒事件时间和秒级录制时间混用。

检查：

- 实时场次：`recording_since <= transcript_time / event_time`。
- 历史场次：还必须满足 `time <= recording_end`。
- `events.ts` 使用毫秒；`recording_since`、`recording_end` 使用秒。
- 起点为 0 时必须返回空，不允许用全部历史补位。

主文件：`pipeline/live_workbench.py`。

## 4. 工作台看不到正在录制房间

检查 `/api/status` 对该房间是否满足：

```text
phase = recording
recording_since > 0
```

若数据大盘显示录制中但 API 不是 recording，定位 `pipeline/manager.py` 的 `_danmu_loop` 状态迁移、音频线程和重连分支。若 API 正确但前端没有，检查 `fetchLiveWorkbench` 与 `selectedRid`。

## 5. 直播预览不显示 / 404 / 播错场次

录制中的首段视频必须先封口，现有 60 秒分段可能造成最多约 60 秒延迟。

检查：

- 数据大盘是否开启 `record_video`。
- 房间视频目录是否有大于 50 KB 且 3 秒内不再写入的 MP4。
- 历史预览请求是否带 `session_start` 和 `session_end`。
- `video_preview.latest_sealed_video` 是否按时间窗排除了前后场次文件。

禁止为预览另起抖音页面或第二条平台拉流；预览只复用本机录制段。

## 6. 横屏 / 竖屏画面太小、裁切或挤压其他区域

前端依赖 `<video loadedmetadata>` 的 `videoWidth / videoHeight` 设置 `portrait / landscape`。画面必须 `object-fit: contain`，预览列有固定上限，放大弹窗复用同一 URL。

定位：`pipeline/frontend.html` 中：

```text
updatePreviewOrientation
live-preview-stage.is-portrait
live-preview-stage.is-landscape
live-console-grid
```

至少检查 1920×1080、1280×720、1024×768 和一个真实 9:16 视频。

## 7. “全部开始 / 全部停止”没有反应

检查顺序：

1. 前端函数是否在 Vue `return{...}` 中暴露。
2. `/api/rooms/start-all` 或 `/api/rooms/stop-all` 是否返回 `ok` 与数量。
3. 手机号账号是否拥有 `replay_shrimp + livewatch`。
4. `RoomManager.start_all / stop_all` 是否返回实际变更数量。

前端不得吞掉 403/500 后只刷新页面，必须显示服务端失败原因。

## 8. 解析目标主播后，列表变成登录账号昵称 / 头像

这是“Cookie 所属账号资料污染目标主播身份”。已修复，但后续改 WSS / 页面解析时容易复发。

规则：

- 分享链接解析得到的目标昵称是身份锚点。
- 连接返回昵称与锚点不一致时，不能覆盖昵称，也不能把其头像写给目标主播。
- 只有目标资料为空，或返回身份与锚点一致时才补充资料。

定位：`anchor_resolver.py`、`anchor_profiles.py`、`manager.py`。

回归：`test_anchor_resolver.py`、`test_room_metadata.py`。

## 9. 主播头像一直加载失败

检查解析响应是否有公开头像 URL、缓存是否可写、远端 URL 是否过期。前端图片失败后会调用主播刷新接口，但不能因此用登录账号资料替代。

定位：`anchor_resolver.py`、`anchor_profiles.py`、`frontend.html` 的 `handleAvatarError / refreshAnchorByRid`。

## 10. 弹幕、点赞、进场、在线人数全部为 0

音视频能录制不代表 WSS 互动正常。

检查：

- 商业包是否包含 `app/sidecar/douyinLive.exe`。
- 启动器是否设置 `LIVEWATCH_DANMU_BACKEND=sidecar`。
- `%LOCALAPPDATA%\LiveWatch\data\sidecar\douyinlive.yaml` 是否已从统一 Cookie 生成。
- `127.0.0.1:1088` 是否监听。
- `douyin_sidecar_client.py` 是否收到 JSON 并写入 `events.db`。

不得恢复旧 `vendor/DouyinLiveWebFetcher` 或 `run_worker.py`。

## 11. 未扫码就显示“已登录” / 三个模块分别登录

检查 `browser_cookies.py` 的真实登录判断，不能仅因存在 Cookie 文件、浏览器 profile 或任意 cookie 就认定登录。

直播、短视频和评论采集必须消费同一个受保护 Cookie 状态；Edge / Chrome 只负责用户完成授权，不应各生成互不兼容的业务身份。

回归：`test_browser_cookies.py` 及三个调用方测试。

## 12. 主页作品只能得到 21～22 条

当前仍需真实验收，不能写成完全解决。

定位 `pipeline/short_video.py`：

- 首屏接口是否返回游标和 `has_more`。
- 页面滚动后是否等待新的网络响应，而不是只读 DOM。
- 增量结果是否按作品 ID / 规范 URL 合并。
- 缓存合并必须只增不减，不能用一次较少结果覆盖旧缓存。
- 登录态 / 风控发生时要返回诊断原因，不要伪装为“已经全部读取”。

验收目标：用户给定主页稳定超过 30 条。

## 13. 评论总数 26，但只采到 11 / 回复缺失

当前仍需真实验收。

定位 `pipeline/comment_leads.py`：

- 同时检查网络 API 响应与评论面板滚动。
- 顶级评论分页和回复分页是两套游标。
- 可见“展开回复”需要触发并等待响应。
- 去重只按 `comment_id`；不能按昵称或评论文案去重。
- UI 应展示平台总数、顶级已采、回复已采、去重数、失败 / 停止原因。

回归：`test_comment_leads.py`。最终必须用用户指定真实视频核对。

## 14. 手机号登录成功但仍提示无会员 / 权益签名失败

检查：

- 远端返回是否包含 `account_license`。
- `schema / alg / key_id / typ / iss / aud / signed_until` 是否符合冻结协议。
- `aud` 必须是 `replay_shrimp`。
- `products` 中必须有 active 的 `replay_shrimp`，且 entitlements 包含 `livewatch`，未过期。
- 客户端账号公钥是否与服务器 `account-v1` 私钥配对。

抓包修改未签名根字段不会生效；验签失败必须拒绝，不能回退旧会员字段。

## 15. 上传 OSS 新安装包后，客户端没有更新

这是预期行为：OSS 只是文件存储，不是版本真相源。

检查：

1. `https://anyq.site/api/v1/releases/latest?product_id=replay_shrimp` 是否存在。
2. 是否发布了 `update-v1` 私钥签名的 `update_release`。
3. 下载 URL 是否固定为 `https://download.anyq.site/...`。
4. 版本、字节数、SHA-256 是否与 OSS 文件一致。
5. 客户端内置的更新公钥是否正确；不能使用账号公钥。

定位：`update_release.py`、`updater.py`、更新后台和 [`DESKTOP_UPDATE_CONTRACT.md`](DESKTOP_UPDATE_CONTRACT.md)。

如果“用户一直开着软件收不到刚发布的更新”，再检查：

1. 该安装包是否已经包含 `EventSource(/api/v1/releases/events)` 和 60 秒兜底检查；旧安装包无法由服务器凭空增加监听能力。
2. 公网 SSE 是否返回 `200 text/event-stream`、`event: ready`，约 15 秒是否出现心跳。
3. 发布动作是否真正执行到“签名发布”，而不只是把 EXE 上传 OSS 或只创建草稿。
4. `product_id` 是否与客户端固定产品一致；事件按产品隔离。
5. 若普通更新却被强制，检查 `min_supported_version` 是否误填为新版本；普通更新留空应记录 `0.0.0`。

## 16. 安装新版提示无法关闭程序 / 覆盖后启动不了 / 卸载不干净

定位：`packaging/build/livewatch.iss` 和 `livewatch_launcher.py`。

必须验证：

- 安装前关闭托盘、WebView2、启动器和后端子进程。
- 覆盖升级复用固定 AppId 与安装目录。
- 用户数据在 `%LOCALAPPDATA%\LiveWatch\data`，普通卸载默认保留。
- “完全删除”才移除数据。
- 单实例：重复点快捷方式应聚焦现有窗口，不再多开。
- 已安装后再次运行同版本安装包的行为必须明确，不出现无目录的异常安装器。

## 17. 一键打包闪退 / 找不到 Node / 编译特别慢

先从终端运行 `packaging/build/一键打包复盘虾.bat`，查看 `packaging/build/build-last.log`；日志不提交 Git。

常见原因：

- Node 不在 PATH：脚本应优先发现工作区内置 Node 或允许 `-NodeExe`。
- Nuitka 首次下载 Zig / 编译缓存，第一次明显较慢。
- Python 3.14 是实验支持，建议构建机使用 Python 3.13。
- “页面文件太小”是 Windows 虚拟内存不足；关闭大型程序、增大系统分页文件后再编译。
- sidecar、公钥、模型、Inno Setup 任一缺失都应前置失败，不允许产出残缺包。

不要为了变快跳过商业编译、完整性清单或安全扫描。

## 18. SmartScreen 阻止未知应用

SHA-256、HTTPS 和应用内签名不能替代 Windows Authenticode。要降低提示，需要受信任的代码签名证书，并持续积累发布者信誉。

签名前仍应：官网提供 SHA-256、“联系客服辅助安装”入口和清晰的 Windows“更多信息 → 仍要运行”说明。不要伪造证书或诱导关闭系统安全功能。

## 19. 修复完成的交付检查

```powershell
git diff --check
python -m pytest -q
```

然后同步：

- `CHANGELOG.md`：用户 / 发布者可理解的变化。
- `DEVELOPMENT_LOG.md`：日期、原因、实现和验证。
- `PROJECT_HANDOFF.md`：架构、线上状态、已知问题和下一步。
- `HANDOFF.md`：下一位 AI 的短接手卡。
- 本文件：若新增了新的故障模式或定位路径。

## 20. 2026-07-20 交付收口故障定位

### 更新后仍显示旧版本 / 用户改到 D 盘

检查 `pipeline/updater.py` 的 `install_dir` 是否来自当前冻结目录，和 `packaging/build/livewatch.iss` 是否读取 `Inno Setup: App Path`。更新安装器必须收到带引号的 `/DIR="实际目录"`；只上传 EXE 或只替换快捷方式都不能保证覆盖原目录。先看更新弹窗显示的安装目录，再看该目录下启动器的文件时间和版本。

### 修改素材、导出路径或本地数据后完整性失败

检查 `pipeline/integrity_manifest.py` 的 allowlist。当前只应校验启动器和 `app/pipeline/*.pyd` 核心文件；素材、导出、模型、SQLite 数据库、缓存和用户自定义目录不得写入完整性清单。

### 点击放大查看出现 `nextTick is not a function`

检查 `pipeline/frontend.html` 的模板事件必须调用显式 `onPreviewDialogOpen`，由函数内部调度 `attachExpandedLivePreviewPlayer`。不要在模板中把未暴露的 Vue `nextTick` 当作方法调用。

### AI 复盘中文乱码

检查 `pipeline/ai_report.py` 是否在读取 SSE `iter_lines()` 前设置 `resp.encoding = "utf-8"`。这类乱码是响应字符集声明不完整导致，不是账号权益签名或安装器加密导致。

### 用户看到整屏原始错误堆栈

检查 `pipeline/frontend.html` 的 `app.config.errorHandler`：它应把异常写入控制台 / `window.__livewatchLastError`，并只显示短提示“操作错误，稍后再试”。不要把完整 traceback 插入页面。

### AI 复盘报告与顾问内容同时挤在页面

这是页面结构问题，不是 AI 接口问题。检查 `aiReviewTab` 和 `.ai-review-tabs`：默认展示“AI复盘报告”，需要连续追问时切换到“AI专场顾问”。侧边栏中的直播工作台子项应保持“实时监控 → AI直播复盘 → AI达人雷达”。

### AI 复盘页出现额外页面滚动条

这是高度约束叠加问题，不是报告内容本身异常。复盘视图必须带 `:class="{'content-review':view==='review'}"`，并由 `.content.content-review` 隐藏外层溢出、让 `.content.content-review .ai-workspace` 使用 `height:100%`；不要再给该视图叠加独立的 `100vh` 页面滚动容器。窄屏媒体规则仍可恢复 `overflow:visible`，让内容自然向下滚动。
