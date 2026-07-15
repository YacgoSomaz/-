# 文件结构与功能地图

更新时间：2026-07-15

用途：让下一位工程师或 AI 从“功能 / 故障现象”快速定位到主文件、数据来源和回归测试。完整业务现状见 [`../PROJECT_HANDOFF.md`](../PROJECT_HANDOFF.md)，具体排障步骤见 [`TROUBLESHOOTING.md`](TROUBLESHOOTING.md)。

## 1. 仓库边界

| 路径 | 定位 | 修改规则 |
|---|---|---|
| `_experiments/douyin_worker_route/` | 当前复盘虾主线 | 新功能优先在这里实现 |
| `packaging/build/` | Windows 商业构建与安装器 | 发布问题改这里，同时跑构建契约测试 |
| `docs/` | 冻结协议、文件地图与排障文档 | 协议变更必须同步三个客户端 |
| `licensing_server/` | 旧卡密服务兼容代码 | 不是当前手机号账号 / `user_products` 真相源 |
| `archive/legacy_root_prototype/` | 早期根目录原型 | 仅考古，不从这里恢复主线 |
| `_experiments/dycast*` | 已移除旧实验路线 | 不恢复许可证不清晰的抓取 vendor |
| `lead_shrimp/` | 独立获客虾项目 | 已从本仓库忽略，不混入复盘虾提交 |
| `.tmp-recharge-*` | 远端官网 / 服务临时副本 | 只用于本机部署核对，不入 Git |

远端账号服务、版本发布后台与人工会员授权不在本仓库保存生产源码；接口、安全边界、备份位置和排错入口见 [`ADMIN_CONSOLE.md`](ADMIN_CONSOLE.md)。

## 2. 主线入口与编排

主线目录：`_experiments/douyin_worker_route/`

| 文件 | 主要职责 | 常见故障入口 | 主要测试 |
|---|---|---|---|
| `pipeline/webui.py` | FastAPI 应用、API 路由、前端托管、权限入口 | 接口 404/403、参数不一致、按钮调用失败 | `test_account_webui.py`、`test_live_workbench.py`、各业务 API 测试 |
| `pipeline/frontend.html` | Vue 3 + Element Plus 单文件前端 | 布局、按钮、登录弹窗、状态文字、数据绑定错误 | `test_frontend_contract.py`、浏览器烟测 |
| `pipeline/config.py` | 开发 / 安装态路径、环境变量、服务 URL、产品码 | 数据写错目录、公钥缺失、安装后找不到资源 | `test_config_paths.py`、账号 / 构建契约测试 |
| `pipeline/manager.py` | 房间生命周期、启停、WSS、音视频、转写线程、状态汇总 | 开始/停止失效、录制状态不准、主播资料污染 | `test_manager*`、`test_room_metadata.py`、`test_live_workbench.py` |
| `pipeline/orchestrator.py` | 采集与转写流程编排 | 队列不推进、任务状态卡住 | 对应编排 / 转写测试 |
| `pipeline/runtime_health.py` | 运行时健康与保活 | 进程存在但服务不可用 | 运行时健康测试 |
| `pipeline/diagnostics.py` | 本机只读诊断快照 | 用户只看到“解析失败”而无快速排错信息 | 诊断接口与前端契约 |
| `pipeline/web_security.py` | 本地 Web 安全头、来源和请求约束 | 本地接口被错误拦截或跨域放开过度 | Web 安全测试 |

## 3. 直播采集、录制与转写

| 文件 | 主要职责 | 常见故障入口 | 主要测试 |
|---|---|---|---|
| `pipeline/danmu_backend.py` | 弹幕后端选择与统一接口 | sidecar / audio_only 路线选错 | sidecar / 后端契约测试 |
| `pipeline/sidecar_runtime.py` | 启动、配置和关闭本机 `douyinLive` sidecar | 1088 端口、配置、Cookie 未传入 | `test_sidecar_runtime.py` |
| `pipeline/douyin_sidecar_client.py` | sidecar JSON 事件映射到主程序 | 弹幕、点赞、进场、在线数缺失 | sidecar client 测试 / 真实直播验收 |
| `pipeline/audio_only_fetcher.py` | 无 WSS 时的音频保底路线 | 有音频但无互动；不应误当完整采集 | 后端选择测试 |
| `pipeline/audio_capture.py` | ffmpeg 拉流与音频 / 视频录制 | ffmpeg 启动失败、流地址失效、文件不落盘 | 音频捕获与冒烟测试 |
| `pipeline/recorder_rotate.py` | 固定时长分段、封口、短段 / partial 处理 | 最后一段丢失、停止后无转写 | 录制恢复 / 时间线测试 |
| `pipeline/transcript_store.py` | `transcripts`、`recording_timeline`、`recording_sessions` | 停止后记录消失、场次边界不准、重复片段 | `test_live_workbench.py`、转写恢复测试 |
| `pipeline/transcribe_batch.py` | 批量扫描已封口片段并转写 | 封口文件存在但没进入转写 | 转写批处理测试 |
| `pipeline/sensevoice_engine.py` | SenseVoice 本地 ASR | 模型路径、音频格式、推理异常 | ASR / 安装冒烟 |
| `pipeline/speaker_worker.py` | 发言人片段合并与标签 | A/B/C 标签错位 | `test_speaker_merge.py` |
| `pipeline/event_sink.py` | 互动事件 SQLite 落库 | 事件采到了但统计为 0 | 事件映射 / 导出测试 |

核心数据关系：

```text
events.db/events
  └─ room_id / live_id + ts(毫秒)

transcripts.db/recording_sessions
  └─ room_id + started_ts + ended_ts
      ├─ recording_timeline（每个封口媒体段）
      └─ transcripts（每段稳定转写）
```

时间单位红线：事件表通常为毫秒，录制场次和转写时间为秒。混用会导致“历史数据串入当前场次”或“全部为 0”。

## 4. 直播工作台、效能与 AI 复盘

| 文件 | 主要职责 | 常见故障入口 | 主要测试 |
|---|---|---|---|
| `pipeline/live_workbench.py` | 进行中 / 历史场次快照、话术和事件时间窗、高频问题 | 停止后空白、旧话术混入、房间选错 | `test_live_workbench.py` |
| `pipeline/video_preview.py` | 选择稳定封口 MP4，历史场次按时间窗过滤 | 预览 404、播放到别的场次、读取正在写文件 | `test_video_preview.py` |
| `pipeline/performance_analysis.py` | 直播效能指标、评分与场次资料 | 主播昵称/头像错、指标来源不一致 | `test_performance_analysis.py` |
| `pipeline/ai_report.py` | AI 复盘流水线、追问、报告内容 | 请求失败、进度卡住、报告不完整 | `test_ai_report.py` |
| `pipeline/export.py` | Excel / Markdown 等本地导出 | 字段缺失、导出目录错误 | 导出测试 |
| `pipeline/sensitive_words.py` | 风险候选、提示词和替换建议 | 普通提示被当违规、词库未打包 | `test_sensitive_words.py`、构建 sidecar/词库契约 |
| `pipeline/lexicons/*.json` | 规则种子和运营虾词库快照 | 内容分级和运行时资源遗漏 | `test_sensitive_words.py`、`test_sidecar_packaging_contract.py` |
| `pipeline/ai_skills/*.md` | AI 直播分析角色与领域提示 | 报告口径、评分解释和行业路由 | AI 报告测试 / 人工验收 |
| `pipeline/knowledge/live_replay_knowledge.md` | 复盘知识底稿 | AI 建议缺业务上下文 | AI 报告人工验收 |

前端直播工作台仍在 `pipeline/frontend.html`，搜索这些锚点定位：

```text
liveConsole
fetchLiveWorkbench
syncLivePreview
live-console-grid
```

## 5. 主播身份、Cookie、短视频和评论

| 文件 | 主要职责 | 常见故障入口 | 主要测试 |
|---|---|---|---|
| `pipeline/anchor_resolver.py` | 从分享链接解析目标主播身份 | 解析失败、昵称和头像为空 | `test_anchor_resolver.py` |
| `pipeline/anchor_profiles.py` | 主播资料缓存与合并 | 列表资料不更新或旧资料覆盖 | `test_room_metadata.py` |
| `pipeline/browser_cookies.py` | 统一抖音信任 Cookie、真实登录判断、刷新 | 未扫码却显示已登录、Edge/Chrome 不复用 | `test_browser_cookies.py` |
| `pipeline/profile_watch.py` | 主页 / 直播状态监控 | 主播上下播判断延迟 | 主页监控测试 |
| `pipeline/short_video.py` | 主页作品解析、滚动 / 游标、作品缓存合并 | 只能拿 21～22 条、缓存越读越少 | `test_short_video.py` |
| `pipeline/short_video_ai.py` | 作品评分、拆解、预测和对标学习 | 报告没绑定单作品、评分与拆解重复调用 | 短视频 AI 测试 |
| `pipeline/comment_leads.py` | 评论网络响应、面板滚动、回复展开、分页和线索标准化 | 26 条只拿 11 条、回复漏抓、错误去重 | `test_comment_leads.py` |

评论去重只能使用平台 `comment_id`。不能按昵称或文案去重，因为相同话术本身是意向判断证据；回复也必须保留 `parent_comment_id` 和层级。

## 6. 手机号账号、权益与旧卡密兼容

| 文件 | 主要职责 | 常见故障入口 | 主要测试 |
|---|---|---|---|
| `pipeline/account_client.py` | HTTPS 手机号账号 API 客户端 | 验证码、登录、刷新、handoff 请求失败 | `test_account_client.py` |
| `pipeline/account_license.py` | 原始 payload Ed25519 验签、受众、时间和重复 key 校验 | “权益签名校验失败”、抓包改字段 | `test_account_license.py` |
| `pipeline/account_manager.py` | 受保护 session、账号状态、权益刷新 | 登录后仍无权限、过期未退出 | `test_account_manager.py` |
| `pipeline/account_policy.py` | 本地 API → `livewatch` 功能映射 | 某按钮错误放行或错误拦截 | `test_account_policy.py` |
| `pipeline/license_*.py` | 旧卡密客户端兼容与历史测试 | 不得作为新账号权限后门 | `test_license_*.py` |
| `pipeline/fingerprint.py` | 旧设备指纹 / 兼容逻辑 | 设备绑定历史问题 | 指纹 / 卡密兼容测试 |
| `docs/ACCOUNT_PRODUCT_CONTRACT.md` | 三产品冻结协议 | 三客户端产品 ID、权益字段冲突 | 协议审查 + 各客户端测试 |

当前固定值：`replay_shrimp + livewatch`。账号公钥可以进客户端，私钥只在服务端。

## 7. 自动更新与完整性

| 文件 | 主要职责 | 常见故障入口 | 主要测试 |
|---|---|---|---|
| `pipeline/update_release.py` | `update_release` 信封验签和字段校验 | 清单被篡改、错误产品 / 受众 | `test_update_release.py` |
| `pipeline/updater.py` | 查询最新版本、下载、大小 / SHA-256 校验、拉起安装 | 上传 OSS 后无提示、下载后不安装 | `test_updater.py` |
| `pipeline/integrity_manifest.py` | 本地程序完整性清单 | 文件被替换或漏打包 | 完整性 / 构建测试 |
| `docs/DESKTOP_UPDATE_CONTRACT.md` | 三端统一更新协议 | 客户端与服务端各说各话 | 更新契约测试 |

仅上传 OSS 不等于发布更新；服务端必须生成 `update-v1` 私钥签名的版本记录。

## 8. Windows 构建与安装

| 文件 | 主要职责 | 常见故障入口 | 主要测试 |
|---|---|---|---|
| `packaging/build/一键打包复盘虾.bat` | 用户输入版本号的一键入口 | 闪退、找不到 Node / PowerShell | `test_verified_release_bat_contract.py` |
| `interactive_verified_release.ps1` | 交互参数、依赖发现、日志保留 | 窗口消失、错误不可见 | `test_verified_release_script.py` |
| `run_verified_release.ps1` | 稳定调用正式构建 | 参数或退出码丢失 | 同上 |
| `build_verified_release.ps1` | 构建前检查与正式流水线 | 漏公钥、漏文件、版本错误 | 构建脚本测试 |
| `build_release.ps1` | Nuitka / PyInstaller / sidecar / 资源 / ISCC 总构建 | 编译慢、页面文件不足、资源缺失 | `test_sidecar_packaging_contract.py` 等 |
| `check_release.py/.ps1` | 产物敏感扫描和商业约束 | Cookie / 源码 / 私钥进入包体 | `test_release_scan.py` |
| `livewatch_launcher.py` | 单实例、本地后端、WebView2、更新拉起 | 多开、二次点击不聚焦、启动即退 | `test_launcher_update_contract.py` |
| `livewatch.iss` | Inno 安装、覆盖升级、卸载和进程关闭 | 无目录安装器、覆盖后启动不了、卸载不干净 | `test_installer_contract.py`、`smoke_test.ps1` |
| `vendor/douyinlive/` | 固定 MIT sidecar、许可证和示例 | 二进制缺失 / 哈希不符 | 构建 SHA-256 检查 |

`release/`、`staging/` 和构建日志是本机产物，不提交源码仓库。

## 9. 测试目录索引

所有主线测试在 `_experiments/douyin_worker_route/tests/`。

| 测试前缀 | 覆盖范围 |
|---|---|
| `test_live_workbench*` / `test_video_preview*` | 场次、停止保留、历史录像 |
| `test_frontend_contract*` | UI 元素、函数暴露、提示和响应式契约 |
| `test_room_metadata*` / `test_anchor_resolver*` | 主播身份与头像 |
| `test_browser_cookies*` | 抖音真实登录态 |
| `test_short_video*` / `test_comment_leads*` | 作品和评论采集 |
| `test_account_*` | 手机号账号、签名权益和接口权限 |
| `test_update_*` / `test_updater*` | 签名更新 |
| `test_release_scan*` / 根目录 `packaging/build/test_*` | 商业包、安装、启动和安全扫描 |

## 10. 修改联动规则

- 改账号字段：同时核对账号协议、远端服务、三个客户端、官网、构建公钥和测试。
- 改更新字段：同时核对更新协议、远端签名服务、三个客户端、管理后台和构建公钥。
- 改录制状态：同时核对 `manager.py`、场次表、工作台、效能分析、导出和停止 / 重连测试。
- 改 Cookie：同时核对直播、短视频、评论三个消费者，不能再各建一份登录态。
- 改安装器：必须做全新安装、覆盖升级、卸载保数据、完全删除、单实例和更新安装测试。
- 改第三方采集组件：先核对许可证、固定版本、SHA-256、声明和构建扫描。
