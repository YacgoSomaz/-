# 项目接手报告

接手对象：直播复盘侠  
主线目录：`_experiments/douyin_worker_route`  
当前分支：`main`  
目标读者：继续开发本项目的工程师或 AI Agent

## 一、先读结论

这个项目已经不是早期的 dycast 研究脚本。当前主线是一个本地桌面应用：

```text
FastAPI 后端 + 单文件 Vue/Element Plus 前端 + SQLite 本地库
  -> WebView2 桌面壳
  -> Inno Setup 安装包
  -> 卡密授权服务器
```

新开发优先改：

```text
_experiments/douyin_worker_route/pipeline/
```

不要优先改根目录早期脚本，除非明确是在做历史兼容或迁移。

## 二、运行方式

开发态：

```powershell
cd C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route
python -m pipeline.webui --host 127.0.0.1 --port 8848
```

商业安装包构建：

```powershell
cd C:\Users\q2414\Desktop\live_watch
pwsh -NoProfile -File packaging\build\build_commercial_release.ps1 `
  -LicenseServerUrl "https://license.runmo.art" `
  -LicensePublicKey "<Ed25519 公钥>" `
  -Version "1.0.0"
```

授权服务本地测试：

```powershell
$env:PYTHONPATH="C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route"
python -m pytest licensing_server\tests -q
```

全量重点测试：

```powershell
$env:PYTHONPATH="C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route"
python -m pytest _experiments\douyin_worker_route\tests licensing_server\tests -q
```

## 三、关键模块地图

### 桌面主程序

| 文件 | 作用 |
|---|---|
| `pipeline/webui.py` | FastAPI 入口、所有 `/api/*`、授权中间件、静态前端托管 |
| `pipeline/frontend.html` | 当前全部前端页面，单文件 Vue 3 + Element Plus |
| `pipeline/config.py` | 路径、模型、授权、录音、转写、短视频、评论线索等配置 |
| `pipeline/manager.py` | 房间监听、音频线程、转写线程、状态管理 |
| `pipeline/audio_capture.py` | ffmpeg 取流、录音、封口、断流处理 |
| `pipeline/transcript_store.py` | SQLite 表结构、话术、事件、录音台账 |
| `pipeline/export.py` | Excel/汇总导出 |
| `pipeline/ai_report.py` | AI 直播复盘、报告、追问 |
| `pipeline/performance_analysis.py` | 直播效能分析 |
| `pipeline/short_video.py` | 抖音短视频账号/作品解析、封面/音频资产 |
| `pipeline/short_video_ai.py` | 短视频 AI 评分、预测、拆解、对标学习 |
| `pipeline/comment_leads.py` | AI获客评论线索 |
| `pipeline/anchor_profiles.py` | 主播资料与头像缓存 |

### 授权系统

| 文件 | 作用 |
|---|---|
| `pipeline/license_manager.py` | 本地授权验签、特性判断、设备绑定状态 |
| `pipeline/license_client.py` | 调用授权服务器激活/刷新 |
| `pipeline/license_policy.py` | 哪些 API 需要哪些 feature |
| `pipeline/license_refresh.py` | 后台定时刷新授权 |
| `pipeline/license_clock.py` | 本地时钟回拨检测 |
| `licensing_server/app.py` | 授权服务器 FastAPI API 与管理后台路由 |
| `licensing_server/service.py` | 卡密、设备、签名、刷新、冻结、解绑 |
| `licensing_server/admin_console.py` | 自包含授权管理台 HTML |

### 安装包

| 文件 | 作用 |
|---|---|
| `packaging/build/livewatch_launcher.py` | WebView2 桌面启动器 |
| `packaging/build/build_release.ps1` | 一键构建开发包/商业包 |
| `packaging/build/check_release.ps1` | PowerShell 安全扫描 |
| `packaging/build/check_release.py` | Python 安全扫描，商业包源码检查 |
| `packaging/build/livewatch.iss` | Inno Setup 安装脚本 |
| `packaging/build/assets/livewatch.ico` | 程序图标 |

## 四、不要提交的内容

这些内容必须保持本地私有：

```text
*.db
audio/
video/
exports/
logs/
browser_cookies.json
short_video_cookies.json
ai_config.json
license.json
license_clock.json
comment_leads*.json
avatar_cache/
short_video_assets/
_experiments/asr_bench/
_experiments/speaker_change_analysis/
staging/
release/
*.pem
*.key
*.pfx
.env
```

提交前必须看：

```powershell
git status --short
git diff --stat
```

如果要 `git add`，请逐文件添加，不要 `git add .`。

## 五、最近一次重要改动

### 授权过期与后台冻结立即生效

问题：

```text
卡密过期后仍可继续使用，后台冻结设备后也不影响已安装客户端。
```

根因：

- 服务端给显式过期卡密仍叠加了离线宽限期，1 分钟测试卡实际被延长。
- 客户端授权刷新周期过长，旧安装包可能数小时后才感知后台状态变化。
- 服务器明确拒绝刷新时，客户端以前按普通网络失败处理，继续信任本地缓存。

修复：

- `licensing_server/service.py`：显式过期卡密不再额外叠加 grace。
- `pipeline/license_client.py`：新增 `LicenseServerDenial`，区分服务器拒绝和网络失败。
- `pipeline/license_manager.py`：新增 `clear_license_doc()`，服务器拒绝时清除本地授权缓存。
- `pipeline/license_refresh.py`：刷新遇到冻结/过期返回 `revoked: ...`。
- `pipeline/config.py`：授权刷新默认约 60 秒一次，最低允许 30 秒。
- 已部署到线上授权服务器并重启 `livewatch-license.service`。
- 已构建商业安装包 `release/LiveWatchSetup_1.0.9.exe`。

验证：

```powershell
$env:PYTHONPATH="D:\live_watch\_experiments\douyin_worker_route"
python -m pytest licensing_server\tests `
  _experiments\douyin_worker_route\tests\test_license_client.py `
  _experiments\douyin_worker_route\tests\test_license_refresh.py `
  _experiments\douyin_worker_route\tests\test_license_manager.py -q
```

本次验证结果：`38 passed`。

安装包：

```text
release\LiveWatchSetup_1.0.9.exe
SHA256: 11CCBEA90B73C5BFA1601FB9460CD42A62BCA273BD4EBF697EB5CA9CCABDA71C
大小:   329297137 bytes
```

接手提醒：冻结/过期不是毫秒级断开，而是在启动刷新或下一次授权刷新时生效，默认约 60 秒内。旧客户端必须覆盖安装 1.0.9 或之后版本才包含本地清缓存修复。

## 六、当前产品问题清单

优先级从高到低：

1. 短视频中心“继续加十条/自定义条数”仍可能只能取到初始 20 条，需要完善页面滚动加载。
2. 短视频 AI 工作台历史报告需要更好地绑定到单个作品，支持查看、下载 Markdown。
3. 短视频 AI 评分和 AI 拆解应合并为一个动作，减少用户等待。
4. AI 获客系统应改成“主页 -> 作品列表 -> 选择视频 -> 评论采集”，再升级定时监控。
5. AI 复盘报告 HTML 已经好于纯文本，但还需继续优化图文混排和 PDF/HTML 导出体验。
6. 授权管理台目前是单管理员令牌，后续可加管理员账号、日志筛选、卡密导出。
7. 商业安装包未做代码签名，用户首次安装可能被 SmartScreen 提醒。
8. 自动更新还未实现；当前用户仍需下载安装新安装包覆盖安装。

## 七、开发原则

- 不要再引入许可证不明的抖音 WSS 内核源码。
- 不要把平台 cookie、AI Key、卡密、服务器密码写进源码。
- 不要用自动私信、绕验证、绕风控作为产品卖点。
- 前端面向低门槛用户，文案要短，按钮要明确，避免技术术语。
- AI 功能必须有进度提示，否则用户会认为卡住。
- 所有报告最好有 Markdown 下载，方便后续沉淀到知识库。
- 商业包必须通过 `check_release` 扫描，不允许带数据库、录音、cookie、源码泄漏。

## 八、建议下一位 AI 的第一步

1. 先运行测试确认环境：

   ```powershell
   $env:PYTHONPATH="C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route"
   python -m pytest licensing_server\tests -q
   ```

2. 如继续动授权，先运行授权专项回归：

   ```powershell
   $env:PYTHONPATH="D:\live_watch\_experiments\douyin_worker_route"
   python -m pytest licensing_server\tests `
     _experiments\douyin_worker_route\tests\test_license_client.py `
     _experiments\douyin_worker_route\tests\test_license_refresh.py `
     _experiments\douyin_worker_route\tests\test_license_manager.py -q
   ```

3. 打开主线前端：

   ```powershell
   cd _experiments\douyin_worker_route
   python -m pipeline.webui --host 127.0.0.1 --port 8848
   ```

4. 优先处理短视频中心作品加载超过 20 条的问题。

5. 修改前先截图当前 UI，修改后用浏览器截图对比，不要只凭代码判断。
