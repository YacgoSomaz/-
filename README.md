# 直播复盘侠

直播复盘侠是一套本地安装运行的直播与短视频运营分析工具。当前主线位于
`_experiments/douyin_worker_route`，已经从早期研究脚本演进为 Windows 桌面安装包、
本地数据落库、商业卡密授权、AI 复盘、短视频拆解和评论线索采集的一体化产品原型。

> 合规提醒：本项目只处理用户自行配置、授权登录态下可见的公开内容。不要绕过登录、
> 验证码、平台风控或批量自动私信。真实 cookie、卡密、AI Key、录音、数据库和导出文件
> 均不得提交到仓库。

## 当前核心能力

- 直播监听：添加主播或直播间，监听弹幕、进场、点赞、关注、粉丝团等事件。
- 音频录制：按直播流录制音频，保留原始分段，支持断流台账与后续溯源。
- 语音转写：本地 SenseVoice 语音识别，支持话术入库、导出和 AI 复盘。
- 声纹标注：对转写片段标注发言人 A/B/C，导出时可带发言人。
- 数据导出：按主播、汇总表、录音时间轴、弹幕事件和话术生成 Excel。
- AI 直播复盘：基于话术、弹幕、互动数据生成运营复盘、追问和报告下载。
- 效能分析：按直播场次展示评分、热度、互动、内容质量和风险提示。
- 短视频中心：解析抖音账号作品，选择作品进入 AI 工作台，生成作品潜力分、拆解报告、爆款预测和对标学习。
- AI 获客系统：配置公开视频或主页作品，采集评论线索，清洗后给客服跟进。
- 商业授权：本地安装包通过卡密激活，支持设备绑定、冻结、解绑和授权刷新。
- 安装包：Inno Setup + PyInstaller + 可选 Nuitka 商业编译，默认安装到 `C:\Program Files\LiveWatch`。

## 目录结构

```text
.
├── _experiments/douyin_worker_route/     # 当前主线产品代码
│   ├── pipeline/                         # FastAPI 后端、前端 HTML、业务模块
│   ├── tests/                            # 主线测试
│   ├── third_party/cheat_on_content/     # MIT 短视频评分方法论参考
│   └── THIRD_PARTY_NOTICES.md            # 第三方声明
├── licensing_server/                     # 卡密授权服务器
├── packaging/build/                      # Windows 安装包构建链
├── docs/security/                        # 授权服务器部署说明
├── docs/superpowers/plans/               # 近期重要开发计划
├── DEVELOPMENT_LOG.md                    # 项目开发日志
└── PROJECT_HANDOFF.md                    # 给下一位开发者/AI 的接手报告
```

早期根目录脚本和旧实验目录仍保留作历史参考，但新开发优先围绕
`_experiments/douyin_worker_route` 进行。

## 本地开发启动

```powershell
cd C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route
python -m pipeline.webui --host 127.0.0.1 --port 8848
```

浏览器打开：

```text
http://127.0.0.1:8848
```

常用环境变量：

```powershell
# AI 配置建议在系统设置页面填写，避免写入源码
$env:LIVEWATCH_DANMU_BACKEND="audio_only"
$env:LIVEWATCH_LICENSE_ENFORCE="0"       # 开发态默认不强制，商业包编译期强制
$env:LIVEWATCH_DATA_DIR="D:\LiveWatchData" # 可选：指定本地数据目录
```

## 授权服务器

授权服务代码在 `licensing_server/`。线上服务当前通过 systemd 运行在：

```text
https://license.runmo.art/
```

管理后台入口：

```text
https://license.runmo.art/admin
```

根路径 `/` 已重定向到 `/admin`。管理后台需要输入服务器环境变量
`LICENSE_ADMIN_TOKEN`，令牌只在当前浏览器页面内存中使用，不保存到网页或仓库。

本地启动授权服务示例：

```powershell
cd C:\Users\q2414\Desktop\live_watch
python -m venv .venv-license
.\.venv-license\Scripts\Activate.ps1
pip install -r licensing_server\requirements.txt

$env:LICENSE_DB_PATH=".\license_data\licenses.db"
$env:LICENSE_SIGNING_PRIVATE_KEY="<Ed25519 私钥>"
$env:LICENSE_TOKEN_HASH_SECRET="<随机长密钥>"
$env:LICENSE_ADMIN_TOKEN="<管理员令牌，至少16位>"
uvicorn --factory licensing_server.app:create_app_from_env --host 127.0.0.1 --port 60001
```

完整部署见：

```text
docs/security/license-server-deployment.md
```

## Windows 安装包构建

构建脚本位于 `packaging/build/`。商业构建会把 `pipeline` 编译为二进制模块，
安装包中不携带业务 `.py` 源码，只内置授权公钥和授权服务地址。日常发包建议使用
`build_commercial_release.ps1`，它会自动固定商业加固参数，避免漏掉编译、授权和完整性校验步骤。

```powershell
python -m pip install -r packaging\build\requirements-build.txt

# 方式 A：构建机提前放入授权公钥。
$env:LIVEWATCH_LICENSE_PUBLIC_KEY = "<Ed25519 公钥>"
pwsh -NoProfile -File packaging\build\build_commercial_release.ps1 `
  -Version "1.0.0"

# 方式 B：用管理后台令牌临时拉取公钥；令牌不会写进安装包。
$env:LIVEWATCH_LICENSE_ADMIN_TOKEN = "<管理后台令牌>"
pwsh -NoProfile -File packaging\build\build_commercial_release.ps1 `
  -LicenseServerUrl "https://license.runmo.art" `
  -Version "1.0.0"
```

产物：

```text
release\LiveWatchSetup_1.0.0.exe
```

## 对外发放安装包

不要让用户从 GitHub ZIP、源码仓库或 LFS 指针文件里拿安装包。商业发放请使用官方下载页：

```text
https://license.runmo.art/downloads/
```

下载页提供两种方式：

- 直接下载 `LiveWatchSetup_<版本>.exe`
- 推荐使用在线校验安装命令：先下载安装包，校验 SHA256 与官方值一致，再启动安装

当前 `1.0.2` 安装包信息：

```text
URL:    https://license.runmo.art/downloads/LiveWatchSetup_1.0.2.exe
SHA256: 53D6E00CF285E1DE31E14FD57E4155B16B9D23A1482D14974DCA8A6503DF1F72
大小:   329330062 bytes
```

注意：Windows / Edge 对未签名的新 EXE 可能出现 SmartScreen 或安全下载确认。这不是安装包缺文件，
而是缺少受信任代码签名证书导致的信誉提示。当前构建链已经支持 `-CodeSignThumbprint`，
后续购买代码签名证书后，在商业构建命令中加入该参数即可给启动器和安装包签名。

可选代码签名：

```powershell
pwsh -NoProfile -File packaging\build\build_commercial_release.ps1 `
  -CodeSignThumbprint "<证书SHA1指纹>" `
  -Version "1.0.0"
```

## 测试

推荐在仓库根目录执行：

```powershell
$env:PYTHONPATH="C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route"
python -m pytest _experiments\douyin_worker_route\tests licensing_server\tests -q
```

授权服务专项测试：

```powershell
$env:PYTHONPATH="C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route"
python -m pytest licensing_server\tests -q
```

构建产物安全扫描：

```powershell
pwsh -NoProfile -File packaging\build\check_release.ps1 -Target staging\LiveWatch
python packaging\build\check_release.py staging\LiveWatch --commercial
```

## Git 与敏感数据纪律

不要提交以下内容：

- `browser_cookies.json`、`short_video_cookies.json`
- `ai_config.json`、`.env`、`*.pem`、`*.key`、`*.pfx`
- `license.json`、`license_clock.json`
- `*.db`、录音、视频、导出、日志、缓存
- 模型目录 `_experiments/asr_bench/`、声纹模型目录、大体积 staging/release 产物

提交前建议运行：

```powershell
git status --short
git diff --stat
```

只选择性 `git add` 本次真实要提交的源码和文档。

## 下一步优先级

1. 完善短视频中心的主页作品滚动解析，突破初始 20 条限制。
2. 优化短视频 AI 工作台历史报告、Markdown 下载、报告卡片展示。
3. 给 AI 获客系统加入主页新作品监控，再把新视频评论转成线索。
4. 继续降低 AI 报告耗时，并保留清晰的进度可视化。
5. 购买代码签名证书，给商业安装包签名，减少 Windows SmartScreen 提示。
