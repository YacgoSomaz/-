# 直播复盘侠（LiveWatch / 复盘虾）

直播复盘侠是一套 Windows 本地商业软件，用于抖音直播录制、互动采集、语音转写、实时工作台、直播效能分析、AI 复盘、短视频分析和评论线索整理。

当前开发主线：

```text
_experiments/douyin_worker_route/
```

> 合规边界：只处理用户自行授权登录后可见的数据；不绕过验证码或平台风控，不自动私信。Cookie、手机号会话、AI Key、数据库、录音录像、签名私钥、支付密钥和服务器密码禁止进入 Git。

## 接手必读（按顺序）

1. [`README.md`](README.md)：项目入口、启动、测试与发布边界。
2. [`PROJECT_HANDOFF.md`](PROJECT_HANDOFF.md)：完整现状、架构、线上协议、已知问题、下一步。
3. [`_experiments/douyin_worker_route/HANDOFF.md`](_experiments/douyin_worker_route/HANDOFF.md)：主线快速接手卡。
4. [`docs/FILE_MAP.md`](docs/FILE_MAP.md)：目录和模块职责，修改时从这里定位文件。
5. [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)：按故障现象定位源码、数据和回归测试。
6. [`CHANGELOG.md`](CHANGELOG.md)：版本级变更摘要。
7. [`DEVELOPMENT_LOG.md`](DEVELOPMENT_LOG.md)：按日期记录的详细开发过程。

账号与更新协议分别以 [`docs/ACCOUNT_PRODUCT_CONTRACT.md`](docs/ACCOUNT_PRODUCT_CONTRACT.md) 和 [`docs/DESKTOP_UPDATE_CONTRACT.md`](docs/DESKTOP_UPDATE_CONTRACT.md) 为准；产品管理后台、人工会员授权和生产备份见 [`docs/ADMIN_CONSOLE.md`](docs/ADMIN_CONSOLE.md)。不要在三个客户端中各自发明字段。

## 当前状态（2026-07-15）

- 主线完整回归：`292 passed`；连同 `licensing_server` 和 `packaging/build` 契约的仓库级验证：`331 passed`。
- 线上签名更新通道当前复盘虾版本为 `1.1.14`，对应 `replay-shrimp/1.1.14/LiveWatchSetup_1.1.14.exe`。
- 较早的本地 `1.0.15` WSS sidecar 候选已经低于线上版本号，且不包含之后完成的主播身份保护和直播工作台修复，只能保留为历史构建记录，不能再发布。
- 下一次商业构建必须使用 `1.1.15` 或更高版本，不能使用旧文档曾写过的 `1.0.16`。
- 本地开发服务已验证可在 `127.0.0.1:8899` 运行；默认命令仍可使用 8848。
- 直播工作台支持进行中与最近完成场次。停止录制后，话术、互动、时长和可用录像不会消失。

正式安装包通过 `https://download.anyq.site`（OSS + CDN + HTTPS）分发，产品与续费入口为 `https://anyq.site`。安装包二进制不通过源码仓库发放。

## 核心架构

```text
WebView2 / 浏览器
        │
        ▼
FastAPI（pipeline/webui.py）
        │
        ├─ RoomManager：房间状态、WSS sidecar、音视频录制、批量控制
        ├─ SQLite：events / transcripts / recording_timeline / recording_sessions
        ├─ SenseVoice：本机转写
        ├─ 直播工作台 / 效能分析 / AI 直播复盘
        ├─ 短视频中心 / 评论线索
        └─ 手机号账号会话 + Ed25519 权益验签 + Ed25519 更新验签

远端 anyq.site
        ├─ 手机号短信登录与受保护 session
        ├─ user_products（三产品权益唯一来源）
        ├─ account_license（短时 Ed25519 权益快照）
        ├─ web_handoff（一次性官网登录交接）
        ├─ 微信支付回调
        └─ update_release（签名更新清单）
```

复盘虾只接受：

```text
product_id = replay_shrimp
entitlement = livewatch
```

客户端根节点 `products`、旧会员字段、余额或卡密缓存都不能直接解锁。最终权益来源是服务端 `user_products`，客户端只消费验签成功且未过期的 `account_license`。

## 已实现能力

- 直播房间添加、刷新、启停和多房间管理。
- WSS 弹幕、点赞、进场、礼物、关注、粉丝团、在线统计采集。
- ffmpeg 音频与可选视频分段录制，断流和封口片段台账。
- SenseVoice 本机转写、话术入库、时间线和导出。
- 直播工作台：进行中 / 历史场次选择、横竖屏预览、话术、互动和高频问题。
- 直播效能分析和 AI 直播复盘、追问、HTML / Markdown / PDF 报告。
- 短视频主页解析、作品选择、评分、拆解、预测和对标学习。
- 评论线索：顶级评论与回复、评论 ID 去重、IP 属地、点赞和回复统计。
- 手机号登录、产品隔离、签名权益、账户中心与一次性续费跳转。
- 签名更新客户端、商业构建、安全扫描、Inno Setup 安装器。

## 目录结构

```text
live_watch/
├─ _experiments/douyin_worker_route/  # 当前产品主线
│  ├─ pipeline/                       # 后端、单文件前端和业务模块
│  ├─ tests/                          # 主线 pytest 回归
│  ├─ third_party/                    # 允许使用的方法论参考
│  ├─ HANDOFF.md                      # 主线快速接手卡
│  └─ THIRD_PARTY_NOTICES.md          # 第三方许可与固定哈希
├─ packaging/build/                   # 商业编译、启动器、安装器、扫描与测试
├─ licensing_server/                  # 旧卡密服务兼容代码；不是当前账号权益真相源
├─ docs/                              # 冻结协议、文件地图、排障手册和安全文档
├─ archive/legacy_root_prototype/     # 早期根目录原型，仅供考古
├─ PROJECT_HANDOFF.md                 # 完整项目交接
├─ DEVELOPMENT_LOG.md                 # 详细开发日志
└─ CHANGELOG.md                       # 版本级变更摘要
```

完整逐文件职责见 [`docs/FILE_MAP.md`](docs/FILE_MAP.md)。不要从根目录旧脚本或已删除的 `dycast` 原型继续开发。

## 本地启动

```powershell
cd C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route
python -m pip install -r requirements.txt
python -m pipeline.webui --host 127.0.0.1 --port 8848
```

打开：

```text
http://127.0.0.1:8848
```

若 8848 被占用，可改为 8899。开发态账号权限是否强制由本地配置控制；商业包必须携带账号验签公钥并强制服务端权益校验。

常用数据位置：

```text
开发态：_experiments/douyin_worker_route/ 下的本地数据路径
安装态：%LOCALAPPDATA%\LiveWatch\data\
```

## 测试

主线测试：

```powershell
cd C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route
python -m pytest -q
```

仓库级专项测试：

```powershell
cd C:\Users\q2414\Desktop\live_watch
$env:PYTHONPATH="$PWD\_experiments\douyin_worker_route"
python -m pytest licensing_server\tests packaging\build\test_*.py -q
```

关键修改对应测试：

| 修改范围 | 至少运行 |
|---|---|
| 直播工作台 / 场次 | `test_live_workbench.py test_video_preview.py test_frontend_contract.py` |
| 账号 / 权益 | `test_account_*.py test_account_policy.py test_account_webui.py` |
| 更新器 | `test_update_release.py test_updater.py` 与构建更新契约测试 |
| 短视频 / 评论 | `test_short_video.py test_comment_leads.py test_browser_cookies.py` |
| 安装器 / 商业包 | `packaging/build/test_*.py`、`check_release.ps1`、`smoke_test.ps1` |

## 商业构建

推荐从仓库根目录双击或运行：

```text
packaging\build\一键打包复盘虾.bat
```

脚本会要求输入版本号，并进入经校验的商业构建流程。下一次版本不得低于 `1.1.15`。

完整参数与前置依赖见 [`packaging/build/README.md`](packaging/build/README.md)。构建时必须具备：

- 账号权益 `account-v1` 公钥。
- 自动更新 `update-v1` 公钥；不能拿账号公钥替代。
- Inno Setup 6。
- Python、Node 和 Nuitka 构建依赖。
- 固定哈希的 `douyinLive v2.0.24` sidecar。

Windows 代码签名证书只通过证书存储 / 硬件介质使用，私钥不能进入项目。商业构建完成后还要做：安装冒烟、覆盖升级、卸载保数据、单实例、更新接口和真实账号权益测试。

## 发布与自动更新

仅把 EXE 上传 OSS 不会自动触发客户端更新。正确流程：

1. 构建并验收新安装包。
2. 计算 SHA-256 和字节数。
3. 上传到新版本对象路径，例如 `replay-shrimp/1.1.15/...exe`，不要覆盖旧路径。
4. 在更新管理后台发布对应 `product_id` 的签名 `update_release`。
5. 客户端从 `https://anyq.site/api/v1/releases/latest?...` 获取并用 `update-v1` 公钥验签。
6. 客户端再校验固定下载域名、版本、文件大小和 SHA-256 后安装。

协议字段以 [`docs/DESKTOP_UPDATE_CONTRACT.md`](docs/DESKTOP_UPDATE_CONTRACT.md) 为准。

## Git 与敏感数据纪律

以下内容不得提交：

- `.env`、AccessKey、密码、后台 token、短信验证码、支付密钥。
- `account_session.json`、Cookie、浏览器 profile、AI Key。
- `*.db`、录音、录像、导出、缓存、日志和本机诊断文件。
- 私钥、证书私钥、`*.pem`、`*.key`、`*.pfx`。
- `release/`、`staging/`、模型大文件和临时官网副本。
- 独立项目 `lead_shrimp/`。

提交前必须运行：

```powershell
git diff --check
git status --short
python -m pytest -q
```

再对待提交清单做敏感信息扫描。公钥、SHA-256 和第三方许可证可以提交；私钥和真实凭据绝对不行。

## 当前已知问题与下一步

1. 真实主页作品有时仍停在 21～22 条，需继续验证滚动 / 游标增量能稳定超过 30 条。
2. 约 26 条评论的视频曾只采到约 11 条，需真实验证顶级评论、回复展开、网络分页与 UI 数量诊断。
3. Edge / Chrome 的抖音登录态仍需做三模块统一复用的安装包端到端验收。
4. 线上已经是 `1.1.14`；下一包必须使用 `1.1.15+`，且包含主播身份与直播工作台修复。
5. WSS sidecar 已进构建链，但仍需真实直播验证弹幕、点赞、进场、在线数和音视频同步。
6. Windows 代码签名、OSS 新包上传、CDN 校验和签名更新发布仍需按正式发布流程完成。
7. 三产品登录、续费、到期、跨产品拒绝仍需各自做安装包端到端验收。

遇到具体故障先查 [`docs/TROUBLESHOOTING.md`](docs/TROUBLESHOOTING.md)，再修改对应文件和测试。
