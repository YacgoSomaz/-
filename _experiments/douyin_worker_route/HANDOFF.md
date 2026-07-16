# 直播复盘侠主线快速接手卡

更新时间：2026-07-16
本目录是当前主程序目录：

```text
C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route
```

完整交接报告请先读：

```text
C:\Users\q2414\Desktop\live_watch\PROJECT_HANDOFF.md
```

尤其先读其中的“0.2 本次接手累计变更清单”：它列出本轮账号、采集、UI、打包、官网和分发的所有新增改动，并区分了已部署与待真实验收内容。

开发日志请读：

```text
C:\Users\q2414\Desktop\live_watch\DEVELOPMENT_LOG.md
```

第三方声明请读：

```text
C:\Users\q2414\Desktop\live_watch\THIRD_PARTY_NOTICES.md
```

重要更新：较早的商业包 `1.0.15` 已把 MIT `jwwsjlm/douyinLive v2.0.24` 固定为本机 WSS sidecar，但当前线上签名更新版本已经是 `1.1.14`。不要恢复旧的 `vendor/DouyinLiveWebFetcher` / `run_worker.py`；真实直播间互动端到端与 Windows 代码签名仍待完成。`1.0.15` 之后又修复了主播身份、直播工作台和历史场次，下一次构建必须使用 `1.1.15` 或更高，不能发布 `1.0.16` 造成版本倒退。

直播工作台现已同时支持进行中和最近完成场次。停止录制会写入 `recording_sessions`，前端按 `session_id` 保留该场的话术、互动、时长和可用录像；升级前历史数据从 `recording_timeline` 推断。禁止再把“非 recording 状态”直接等同于空工作台。

更新链路现已增加 `https://anyq.site/api/v1/releases/events?product_id=replay_shrimp` SSE 实时通知和客户端 60 秒签名检查兜底。事件只负责触发 `/api/update/check`，不能绕过 `update-v1` Ed25519 验签。强制更新会阻止运行中的业务操作。旧安装包没有监听能力，下一版必须先作为滚动升级基线发布；后台普通更新留空最低支持版本时必须使用 `0.0.0`，不能再默认填新版本。

---

## 1. 当前定位

本项目已经不是单一抖音监听脚本，而是本地商业软件：

```text
FastAPI 后端
  + Vue/Element Plus 单文件前端
  + SQLite 本地库
  + ffmpeg 录音/录视频
  + SenseVoice 转写
  + AI 直播复盘
  + 效能分析
  + 短视频中心
  + AI 获客系统
  + 手机号账号登录 / 远端会员权益
  + Inno Setup 安装包
```

开发请优先改本目录下的：

```text
pipeline/
```

---

## 2. 本地启动

```powershell
cd C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route
python -m pipeline.webui --host 127.0.0.1 --port 8848
```

访问：

```text
http://127.0.0.1:8848
```

---

## 3. 关键文件

| 文件 | 作用 |
|---|---|
| `pipeline/webui.py` | FastAPI 入口、API、前端托管 |
| `pipeline/frontend.html` | 主要前端，单文件 Vue 3 + Element Plus |
| `pipeline/config.py` | 全局配置、路径、账号服务地址 |
| `pipeline/account_client.py` | HTTPS 手机号账号服务客户端；远端会话不向前端泄露 |
| `pipeline/account_license.py` | Ed25519 `account_license` 原始字节验签、受众与到期校验 |
| `pipeline/account_manager.py` | 本机加密会话、会员状态与功能权益校验 |
| `pipeline/account_policy.py` | 本地 API 到会员权益的映射 |
| `pipeline/manager.py` | 直播房间、录音、转写、状态管理 |
| `pipeline/audio_capture.py` | ffmpeg 取流录音 |
| `pipeline/transcript_store.py` | SQLite 数据层 |
| `pipeline/export.py` | Excel/报表导出 |
| `pipeline/ai_report.py` | AI 直播复盘 |
| `pipeline/performance_analysis.py` | 效能分析 |
| `pipeline/short_video.py` | 短视频账号与作品解析 |
| `pipeline/short_video_ai.py` | 短视频 AI 评分/拆解/预测 |
| `pipeline/comment_leads.py` | AI 获客评论线索 |

---

## 4. 测试

主线回归测试：

```powershell
$env:PYTHONPATH='C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route'
python -m pytest -q
```

最近一次结果：`296 passed`；另有仓库级账号 / 构建契约 `43 passed`，合计 `339 passed`。

仓库根目录同时运行主线、`licensing_server` 与 `packaging/build` 契约：`331 passed`。

当前线上签名更新版本：`1.1.14`

- 下载：`https://download.anyq.site/replay-shrimp/1.1.14/LiveWatchSetup_1.1.14.exe`
- SHA-256：`4D41794C77049D5E5E84E25A0F731F05FA81FB7BFAF5EF82174FCC3BC65FE133`
- 字节数：`261169156`

旧本地 `1.0.15` 候选已废弃（低于线上版本且不含本轮修复）；下一次商业构建版本：`1.1.15`。

---

## 5. 当前优先级

1. 真实主页读取超过 30 条作品仍不稳定，现象是有时只得到 21～22 条。
2. 评论采集需达到平台实际数量：目标视频约 26 条评论时现仅约 11 条；UI 应显示平台总数、已采集、回复、去重与原因。
3. 去重只按平台 `comment_id`；相同话术和回复也必须保留，不能按评论内容或昵称去重。
4. Edge 与 Chrome 登录后，直播、短视频、AI 获客要复用同一真实登录态；未扫码时不能误显示已登录。
5. 短视频 AI 评分和 AI 拆解要合并成一次动作，报告要绑定单个作品，历史支持查看、下载、Markdown。
6. AI 获客从“选视频采评论”升级为“主页新作品监控”。
7. 继续验收一次性续费交接、三产品签名权益隔离、支付成功后的客户端刷新；服务端 `user_products` 是唯一真相源。
8. 商业安装包已接入账号公钥、更新公钥、Nuitka 和完整性检查；线上三产品签名更新接口已返回 200，仍需对 `1.1.15` 做完整下载、覆盖安装与 Windows 代码签名验收。

直播工作台补充约束：实时场次按 `recording_since` 读取，已结束场次必须同时按 `recording_since` 与 `recording_end` 截断；选择值使用独立 `session_id`，不得按主播 / 房间号混读多场数据。停止后不得清空最近场次；“全部开始 / 全部停止”必须保留显式成功/失败提示。任何修改都要跑 `test_live_workbench.py`、`test_video_preview.py` 与 `test_frontend_contract.py`。

直播预览布局：用视频元数据判断 `portrait / landscape`，卡片固定为辅助列，比例变化不能挤压实时话术；宽屏三栏、中屏两栏、窄屏单列。放大弹窗必须复用 `/api/live-preview/{rid}` 的本机录制段，禁止为预览额外打开抖音页面或第二条平台拉流。

---

## 6. 红线

- 不提交 cookie。
- 不提交 AI Key。
- 不提交卡密、授权私钥、服务器密码、远端会话或一次性登录凭据。
- 不提交数据库、录音、视频、导出文件。
- 不引入许可证不清晰的第三方抓取核心。
- 不做自动绕验证码、自动私信、绕平台限制。

---

## 7. Git 注意

仓库根目录是：

```text
C:\Users\q2414\Desktop\live_watch
```

提交前先看：

```powershell
git status --short
git diff --stat
```

当前 `_experiments` 保留目录：

```text
_experiments/douyin_worker_route/
_experiments/asr_bench/
_experiments/speaker_change_analysis/
```

`douyin_worker_route` 是主线；两个模型目录默认不要提交大模型二进制。
