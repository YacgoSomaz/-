# 复盘虾项目交接报告

更新时间：2026-07-20
当前分支：`main`
本轮接手前远端基线：`c78f543 Improve licensing admin and commercial integrity checks`（本文件所在提交之后请以 `git log -1` 为准）
主线目录：`C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route`
目标读者：下一位继续开发本项目的工程师或 AI Agent

## 当前发布产物（2026-07-20）

- 最新本地构建产物为 `release/LiveWatchSetup_1.1.25.exe`，SHA-256：`a5a6569fdcb42a597b6ace01d4565733d7fde9c951f784ff06784ff89e5b058a`，大小 `338,374,466` bytes。
- 对应清单为 `release/LiveWatchSetup_1.1.25.release.json`。上传 OSS 的推荐对象键：`replay-shrimp/1.1.25/LiveWatchSetup_1.1.25.exe`。
- OSS 上传完成后，必须在 anyq.site 发布后台提交 `replay_shrimp` 的签名 `update_release`；只上传 EXE 不会让客户端看到更新。
- 本包扫描通过但尚未做 Windows Authenticode 签名（状态 `NotSigned`），因此 SmartScreen 提示仍可能出现。

建议阅读顺序：`README.md` → 本文件 → `_experiments/douyin_worker_route/HANDOFF.md` → `docs/FILE_MAP.md` → `docs/TROUBLESHOOTING.md` → `CHANGELOG.md` → `DEVELOPMENT_LOG.md`。

## 0.0.1 2026-07-16 本地工作区迁移

- 项目实体文件已迁移至 `D:\qianshanzimeiti\live_watch`，文件数、总字节数、Git HEAD 与原工作区一致。
- 为兼容旧快捷方式、脚本和 AI 交接路径，`C:\Users\q2414\Desktop\live_watch` 现在是指向上述 D 盘目录的 Windows Junction；不要删除该联接本身。
- `D:\live_watch` 是另一份旧项目目录，本次未触碰；后续开发统一使用 `D:\qianshanzimeiti\live_watch` 或兼容联接路径。
- 当前 Git 工作区状态保留原有用户改动：`release/LiveWatchPortable_1.0.2.zip` 仍处于删除状态，未擅自恢复或提交。

## 0.0 2026-07-16 官网当前线上结构

官网 `https://anyq.site` 已按客户确认的三页顺序上线，不要再把下载卡片、FAQ 或技术 SHA-256 信息直接塞回购买页面：

1. `01 账户概览`：手机号账户、权益状态和“选择产品”按钮。
2. `02 选择产品`：三款产品价格卡，补充每款产品的客户可读功能说明；价格卡片下方直接展示客户端下载区；点击产品进入下一页。
3. `03 确认支付`：选中产品切换、订单摘要和微信支付；支持返回产品页。

第三页下方显示“安心购买 / 立即开通 / 专属支持”信任区和精简页脚；联系客服辅助安装固定使用微信 `cl17733174657`。三个页面的滚轮吸附和步骤条已撤销，恢复普通长页面；帮助中心仍为弹层，客户端下载直接位于产品价格区下方，不改变现有签名下载与支付接口。本地页面快照在 `.tmp-recharge-site/`（该目录被忽略，不属于复盘虾主线提交）。

> 当前修订：滚轮吸附和步骤条已撤销，恢复普通单页布局；上段说明保留为历史设计记录。当前线上版本为 `20260716-1600`，回滚点为 `/var/www/recharge-site-backups/20260716140406-single-page-rollback`。

当前线上最新视觉版本为 `20260716-1700`：在普通单页基础上扩大容器和产品卡留白，产品卡最小高度约 420px，移动端单列适配。最新回滚点为 `/var/www/recharge-site-backups/20260716140854-spacious-layout`。

> 当前线上最新收口版本为 `20260716-1518-download-inline`：删除首屏品牌小标签、购买说明勾选、产品区辅助句和结算页英文内部标签；客户端下载卡片已从弹窗移到三款产品价格卡片下方。帮助中心与联系客服弹窗保留，客服微信为 `cl17733174657`。回滚点：`/var/www/recharge-site-backups/20260716151937-downloads-inline`。

---

## 0. 一句话结论

`直播复盘侠` 已经从早期直播监听实验，演进为一个可安装、可授权、可售卖的本地桌面软件。

当前产品主线：

```text
FastAPI 后端
  + 单文件 Vue 3 / Element Plus 前端
  + SQLite 本地数据
  + ffmpeg 录音/录视频
  + SenseVoice 转写
  + AI 复盘 / 短视频拆解 / 评论获客
  + WebView2 桌面壳
  + Inno Setup 安装包
  + 手机号账号与远端会员权益服务（卡密路线已退役）
```

后续开发请优先改：

```text
C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route\pipeline
```

不要优先改根目录早期脚本，也不要再依赖旧的许可证不清晰的抖音 WSS vendor 路线。

### 0.1 2026-07-14 现状校正

- 正式账号、支付与产品入口是 `https://anyq.site`；远端 `user_products` 是三产品权益唯一来源。
- 复盘虾只接受 `replay_shrimp + livewatch`；漫剧虾、运营虾的有效权益不能解锁复盘虾。
- 客户端只以 Ed25519 验签成功且未过期的 `account_license` 解锁，根节点 `products`、旧会员字段和能量余额均不能解锁。
- 三个安装包已通过 `https://download.anyq.site`（OSS + CDN + HTTPS）发布；官网 `https://anyq.site` 展示下载链接、版本和发布日期，SHA-256 不再直接展示给客户，只用于后台与客户端完整性校验。
- 2026-07-14 最近主线回归为 `255 passed`；官网静态页契约为 `6 passed`。
- 真实采集仍未最终验收：主页有时只读到 21～22 条作品；一个约 26 条评论的视频仍只采到约 11 条。这两项不能写成已修复。

### 0.1.1 2026-07-15 WSS 互动采集校正

- 弹幕、点赞、进场、礼物、关注、在线人数与音视频流同属复盘虾核心业务；不得把它们误当作可删的旧路线。
- 旧的许可不明确 `vendor/DouyinLiveWebFetcher` 和 `run_worker.py` 仍禁止进入商业包；替代品是已固定版本的 MIT `jwwsjlm/douyinLive v2.0.24` 本机 sidecar。
- 商业包在 `app/sidecar/douyinLive.exe` 内置该 Windows amd64 二进制，构建前校验 SHA-256，根目录附带 `LICENSE.douyinLive.txt` 和 `THIRD_PARTY_NOTICES.md`。启动器发现该二进制时默认设置 `LIVEWATCH_DANMU_BACKEND=sidecar`。
- 房间启动前使用已验证的本机抖音 Cookie 写入 `%LOCALAPPDATA%\\LiveWatch\\data\\sidecar\\douyinlive.yaml`，启动仅监听 `127.0.0.1:1088` 的 sidecar；Cookie 不得写入安装目录、日志、清单或版本库。
- sidecar 输出 JSON 后由 `pipeline.douyin_sidecar_client.SidecarFetcher` 映射到现有 `SqliteSink`；录音、录像、转写、AI 复盘仍由主程序负责。
- 历史构建产物 `release/LiveWatchSetup_1.0.15.exe`（SHA-256 `9e3e8bd019e2730df90a304251ae9cdee595a7c63f06e2571ea8d4e384547cd3`，322.60 MB）最早引入 WSS sidecar，但它低于当前线上版本并缺少之后完成的主播身份 / 工作台修复，已废弃，不得发布。
- 2026-07-15 实测线上 `replay_shrimp` 签名更新通道返回 `1.1.14`：URL `https://download.anyq.site/replay-shrimp/1.1.14/LiveWatchSetup_1.1.14.exe`，SHA-256 `4d41794c77049d5e5e84e25a0f731f05fa81fb7bfaf5ef82174fcc3bc65fe133`，大小 `261169156` 字节。下一次商业构建固定使用 `1.1.15` 或更高。
- 2026-07-15 修复正式包运行时忽略编译版本、回退显示 `1.0.0` 的问题；`build_verified_release.ps1` 现会在耗时编译前调用 `version_guard.ps1`，拒绝不高于线上版本的输入。注意 `1.0.17 < 1.1.14`，不能把最后一段较大误认为整体版本较新。
- 一键 BAT 已进一步改为自动读取线上版本并递增最后一段，不再让运营人员手输版本；需要提升主 / 次版本时才直接调用正式 PowerShell 构建入口。
- 已生成并完成本地验收的 `release/LiveWatchSetup_1.1.15.exe`：`338291343` 字节，SHA-256 `8806d2c19cb9ba36ed41191a4548bbdfcac929f57e598c70162711a7fd13d651`。安装器、清单和编译运行时版本一致，启动 / 覆盖升级冒烟通过；尚未上传 OSS、未在发布后台签名发布，Windows Authenticode 状态仍为 `NotSigned`。
- 左侧“直播工作台”现为折叠分组，不是独立功能页；其二级固定为“实时监控”（`liveConsole`）、“直播效能”（`pre`）和“AI直播复盘”（`review`）。切换到任一子页会保持分组展开。
- `liveConsole` 已接入真实本机数据：`GET /api/live-workbench` 返回正在录制场次和最近完成场次，并以独立 `session_id` 选择。停止录制后不得清空工作台；`recording_sessions` 保存新场次的精确边界，升级前历史从 `recording_timeline` 推断。稳定转写、在线数、每分钟弹幕、录制时长、事件数和高频问题都只能落在所选场次起止时间内。
- `GET /api/live-preview/{rid}` 为工作台提供视频预览：进行中场次选取当前房间稳定封口的 MP4；历史场次额外使用 `session_start` / `session_end` 限定文件时间窗。无历史录像时仍必须展示话术和互动记录。现有分段时长为 60 秒，故录制中的首帧/刷新可能最多延迟约 60 秒；这不是额外平台拉流，禁止为了预览再起第二条 ffmpeg 或平台浏览器请求。
- 预览卡会读取视频元数据自动区分“竖屏 9:16 / 横屏 16:9”，画面始终完整居中显示；桌面宽屏固定预览辅助列、话术主列和诊断列，中等宽度将诊断下移，窄屏改为单列。“放大查看”弹窗播放同一份本机视频段，不新增平台请求。
- 实时话术和互动统计必须按当前房间 `recording_since` 截断；已结束场次还必须按 `recording_end` 封顶。起点缺失时保持空白，禁止读取同主播其他场次补位。
- “全部开始 / 全部停止”已补齐前端模板暴露、执行中防重复点击和后端错误提示。若权限网关或本地服务拒绝请求，界面必须显示失败原因，不能静默刷新。
- 当前主线完整回归为 `292 passed`；真实本地库已在全部房间停止状态下恢复 7 个最近场次，最新场次保留 7 段转写和 369 秒时长。

### 0.1.2 2026-07-16 会员授权显示链路校正

- `users.role` 只表示 RBAC 角色：普通账号应保持 `regular`，管理员才是 `admin`。严禁为了显示会员而修改角色，否则会造成后台越权。
- 软件会员的唯一事实仍是 `user_products`；桌面端的唯一授权凭据仍是 Ed25519 签名后的 `account_license.products[]`。`replay_shrimp/livewatch`、`comic_shrimp/comic_course`、`operation_shrimp/operation_course` 必须分别匹配。
- 2026-07-16 已修复“管理后台授权成功，但官网仍显示普通用户 / 暂未开通”：官网旧代码只读取精简 `user` 中已不存在的旧会员字段，现改为读取完整响应中的有效 `products[]`。
- `/api/auth/me` 现额外返回用于展示的 `membership` 摘要；它根据服务器时间剔除过期或畸形产品并汇总有效软件。该根节点摘要不得被桌面端当作解锁依据，客户端仍必须验签。
- 复盘虾设置页会员徽标已从 `account.role` 改为签名产品计算出的 `membership_status`。刚在后台开通后，客户端应重新登录或点击刷新账号权益；既有签名快照最长 600 秒失效。
- 生产回滚点：账号服务 `/home/ubuntu/recharge-api/backups/20260716091423`，官网 `/var/www/recharge-site-backups/20260716091857`。
- 本次修复后仓库主线、账号和构建契约回归为 `338 passed`；账号服务部署快照 `22 passed`，官网账户契约 `2 passed`。

### 0.1.3 2026-07-16 运行中更新推送与强制更新校正

- 生产账号服务现提供 `GET /api/v1/releases/events?product_id=replay_shrimp` SSE。后台签名发布成功后按产品广播 `release` 事件；客户端收到事件立即调用本机 `/api/update/check`，由本机更新器重新获取并验签 `update_release`。
- SSE 消息不是安全凭据，也不能直接决定是否升级；真正权限仍来自 `update-v1` Ed25519 签名信封。客户端必须继续验证 `product_id/aud`、版本、官方 CDN 域名、字节数和 SHA-256。事件被篡改最多触发一次无害的重新检查。
- 客户端保留每 60 秒签名检查作为断线兜底。强制更新会在运行中弹出不可关闭提示并拦截业务按钮；普通更新仅提示，不阻断使用。
- 发布后台“最低支持版本”留空规则已经修复：普通更新写 `0.0.0`，强制更新才默认写新版本。不要再用 `min_supported_version=latest` 发布普通更新，否则客户端仍会按最低支持版本规则强制升级。
- 旧安装包没有 SSE / 60 秒兜底监听，服务器无法主动推送到一段不存在的客户端代码。下一版必须先作为滚动升级基线发布；安装该版之后，长期不关机的用户才能实时收到再下一版更新。
- 生产回滚点：`/home/ubuntu/recharge-api/backups/20260716094507`。公网 SSE 已验证心跳与 CORS；本轮主线 `296 passed`，仓库级 `43 passed`，合计 `339 passed`。

### 0.1.4 2026-07-16 复盘虾账号停用及时失效

- `pipeline/webui.py` 启动时刷新账号权益，并启动后台刷新线程，默认每 60 秒调用一次远端 `/api/auth/me`；远端明确返回停用/未授权状态时清除本地加密账号会话和签名权益快照。
- `pipeline/account_client.py` 的 `AccountClientError` 记录 HTTP 状态并提供 `authoritative` 分类；401/403/404/409/410 等明确拒绝会立即清缓存，网络错误则保留短时签名快照，避免断网误踢。
- 签名载荷仍最多有效 600 秒，客户端只信 `account_license.payload`，不信根节点 `user/products` 或旧会员字段。账号状态接口已复用同一刷新逻辑。
- 新增停用回归测试：服务端返回 403 后本地权益立即被清理；账号相关、更新和构建契约回归 `80 passed`。修复已编入 `1.1.16` 安装包；旧版本安装后不会自动获得本轮刷新逻辑。

### 0.1.5 2026-07-17 至 2026-07-20 更新与运行时稳定性收口

- 更新器把当前运行目录写入更新状态，并在拉起安装器时传递带引号的 `/DIR="实际安装目录"`；Inno Setup 读取已注册的 `Inno Setup: App Path`，避免用户把软件装到 D 盘后升级包又落回默认目录、桌面快捷方式继续启动旧版本。
- 安装器固定复用既有安装目录，检测旧目录无效时要求用户在目录页明确选择原目录；覆盖升级前关闭启动器 / WebView2 / 后端进程，普通卸载保留 `%LOCALAPPDATA%\LiveWatch\data`。
- 更新弹窗展示安装位置、下载百分比、下载完成和安装阶段；普通更新可后台下载，强制更新阻断业务操作。`update_release` 仍必须经过 `update-v1` Ed25519 验签，OSS 文件本身不是版本真相源。
- 完整性校验收口为最小核心集合：仅校验 `LiveWatchLauncher.exe` 与 `app/pipeline/*.pyd`；用户导入素材、导出目录、模型数据、文档和运行期数据变更不会再触发启动阻断。完整性清单生成和启动器验证使用同一 allowlist。
- 修复“放大查看”在 Vue 模板中直接调用未暴露 `nextTick` 导致的 `TypeError`：改用 `onPreviewDialogOpen` 延迟挂载预览播放器；运行时错误改为右上角短时提示“操作错误，稍后再试”，不再把原始堆栈铺满整个窗口。
- 全面收口品牌名称为“复盘虾”：前端标题、AI 报告、导出水印、FastAPI 标题、启动器、托盘菜单、安装器、快捷方式和图标均已同步；新增 `packaging/build/assets/icon-options/replay-shrimp.ico`。
- AI 复盘 SSE 响应强制按 UTF-8 解码，修复部分 OpenAI 兼容接口缺失 charset 时中文回复出现 `æ...` 乱码的问题。
- AI 复盘页面已将“AI复盘报告”和“AI专场顾问”拆为 tab；直播工作台子导航调整为“实时监控 → AI直播复盘 → AI达人雷达”，短视频中心和 AI 获客系统保持在其后。
- AI 复盘页面高度已收口：`content-review` 让复盘工作台填充内容视口，桌面宽屏不再出现外层页面滚动条；窄屏仍按响应式规则自然滚动。
- 当前工作区主线与 `packaging/build` 契约回归：`337 passed`，5 个已知弃用 / 依赖警告；`git diff --check` 通过。本地 1.1.25 包已完成构建扫描，但未代替后台完成 OSS 上传和签名发布。

### 0.2 本次接手累计变更清单（2026-07-13 至 2026-07-20）

下列内容是本轮接手后已写入当前工作区、远端账号服务或官网分发体系的累计改动。下一位接手者应把它当作本轮变更账本，而不是重新从旧卡密路线开始。

#### A. 抖音登录态、短视频与评论采集

- `pipeline/browser_cookies.py`：统一直播、短视频和 AI 获客使用的抖音 Cookie 存储；增加真实会话判断、共享状态、自动刷新和安全存储约束。
- `pipeline/short_video.py`：主页作品读取支持增量目标、滚动等待、缓存合并不缩水、作品 URL 去重、登录态不足时的明确提示；旧的短视频 Cookie 可迁移到统一存储。
- `pipeline/comment_leads.py`：评论采集增加浏览器网络响应解析、评论面板滚动、顶级评论 / 回复分页、可见回复展开、回复统计和采集诊断元数据。
- 评论标准化保存 `comment_id`、`parent_comment_id`、回复层级、评论人公开资料、IP 属地、点赞、回复数和话术；去重键是 `comment_id`，不是评论内容。
- `pipeline/webui.py` 与 `pipeline/frontend.html`：主页作品选择、评论采集结果、当前行数和登录状态前置拦截均已补充。未登录点击业务动作应优先进入账号登录，不应先报“未粘贴主页链接”。

**状态：代码和自动化测试已补；真实主页 >30 条、真实视频评论 26 条完整采集仍待验收。**

#### B. 手机号账号、三产品权益与安全协议

- 新增 `pipeline/account_client.py`、`account_license.py`、`account_manager.py`、`account_policy.py`，并在 `webui.py` 公开本地 `/api/account/*` 登录、刷新、续费跳转、退出接口。
- 客户端从卡密输入 / 激活迁移到手机号验证码登录；远端 session 只保存在本机受保护存储，绝不返回给浏览器前端。
- 本地只接受服务端 Ed25519 签名的 `account_license`；验签覆盖原始 payload、算法、`key_id`、签发方、产品受众、签发 / 到期时间、重复 key 和产品权益。
- 固定复盘虾产品受众为 `replay_shrimp`，只检查 `livewatch`；旧的 `membership_expires_at`、`is_member`、余额和根节点 `products` 不能作为解锁后门。
- 增加一次性 `web_handoff`，客户端可安全跳转官网续费，票据仅 60 秒、单次消费，且只在 URL fragment 中短暂出现。
- 新增并冻结 `docs/ACCOUNT_PRODUCT_CONTRACT.md`：三产品 ID、价格、权益、`user_products`、付款回调、签名字段与团队改动边界以该文件为唯一规范。
- 产品管理后台已新增“会员授权” Tab：只允许管理员二次解锁后为已注册手机号开通指定产品，所有写入进入 `user_products` 并记录 `admin_product_grants`；接口和排错见 `docs/ADMIN_CONSOLE.md`。
- 同一 Tab 现可“立即停用”单个生效中产品：数据库立刻过期且写入 `action=expire` 审计；既有客户端签名快照最长约 600 秒失效。手机号前端校验转义错误已在生产修复。

**状态：复盘虾已完成验签与跨产品拒绝测试；三个产品的远端 `user_products`、官网套餐和支付链路已部署。仍需分别做三个正式安装包的登录、续费、过期和跨产品端到端验收。**

#### C. 前端体验和错误提示

- 手机号登录改为独立弹窗，验证码发送按钮与倒计时可见；登录弹窗仅通过明确关闭按钮关闭，避免误触遮罩关闭。
- 隐藏账号内部 ID；账户区域只展示脱敏手机号和用户可理解的会员信息。
- 登录前的功能入口、无权益、签名刷新失败和解析失败的提示分层处理，避免把内部错误直接呈现给用户。
- 评论区补充采集数量展示方向；账号设置、短视频中心、AI 获客和复盘报告的前端契约测试已同步扩展。

**状态：UI 契约已测；请在安装包端再次检查所有提示语和小屏布局。**

#### D. 打包、加固与发布检查

- `packaging/build/build_release.ps1` 改为账号版构建参数：账号 API、账号公钥和固定 `replay_shrimp` 产品码必填；商业构建将业务 `pipeline` 用 Nuitka 编译，并只内置公钥。
- 完整性签名密钥格式增加校验；发布扫描新增 `account_session.json`，防止 Cookie、数据库、音视频、导出、AI Key、session 或私钥进入包体。
- 安装包冒烟检查兼容已编译 `pipeline*.pyd`，不再错误假定商业包内一定存在业务 `.py`。
- 已打出历史 `1.0.15` WSS sidecar 候选，但它低于线上版本，仍不得发布；当前本地最新构建为 `1.1.25`。线上签名更新接口已部署，Windows 代码签名、OSS 上传和新版真实安装验收仍待完成。
- `integrity_manifest.py` 与 `packaging/livewatch_launcher.py` 现在共享最小核心校验范围：启动器本体和 `app/pipeline/*.pyd`；不要把用户数据、素材、导出、模型或文档重新加入清单。
- `updater.py`、`livewatch.iss`、`livewatch_launcher.py` 和 `frontend.html` 共同负责安装目录传递、覆盖升级和下载进度展示；修改其中任一处必须同时跑更新器与安装器契约测试。

#### E. 官网、支付页与安装包分发

- 远端 `anyq.site` 已改为统一三产品官网：手机号登录、账户概览、三产品套餐、微信支付、客户端下载和联系客服辅助安装。
- 官网续费不传递 Cookie、验证码或长期会话；桌面端用一次性网页登录交接进入官网。
- 建立 `download.anyq.site`：阿里云 OSS Bucket、CDN、大文件下载缓存、Range 回源、Referer 防盗链和 HTTPS 证书均已配置。
- 复盘虾 `1.0.12`、漫剧虾 `0.1.13`、运营虾 `0.1.12` 已上传并从公网验证下载；官网客户页面显示三者版本与发布日期，发布后台仍保留对应 SHA-256。官网当前采用“账户概览 → 产品价格 → 订单确认 / 支付 → 下载”的客户流程。

#### F. 测试、文档与工作区约束

- 新增账号客户端、验签、会话管理、API 权限映射、打包契约和 WebUI 测试；评论、短视频、Cookie、前端、效能分析相关测试同步扩展。
- 本轮最近完整主线回归：`292 passed`；加上旧授权兼容服务和构建 / 安装器契约的仓库级验证为 `331 passed`；本轮 Markdown 相对链接和 `git diff --check` 通过。
- 更新 `.gitignore`、发布扫描与交接文档，明确禁止真实 Cookie、AI Key、session、数据库、私钥和安装期数据进入仓库或安装包。
- `.tmp-recharge-api`、`.tmp-recharge-site`、独立 `lead_shrimp`、构建日志和安装包均已从复盘虾提交范围排除；旧原型迁移 / 删除作为本轮主线收口记录保留。接手者仍须先检查差异，不能 reset、checkout 或无脑 add。
- 远端账号服务的本次会员授权部署已在生产目录生成 `backups/20260715211315`；`.tmp-recharge-api` 只是本机快照，下一位 AI 必须先读取生产现状再修改，禁止用旧快照覆盖服务器。

---

## 1. 当前仓库状态

远端仓库：`origin/main`
Git LFS：安装包走 LFS 管理。
当前 `_experiments` 只保留主线项目和运行所需模型目录：

```text
_experiments/douyin_worker_route/
_experiments/asr_bench/
_experiments/speaker_change_analysis/
```

其中 `douyin_worker_route` 是当前开发主线；`asr_bench` 与 `speaker_change_analysis` 只保留模型文件，默认不要提交大模型二进制。

当前账号权益刷新默认值：

```text
LIVEWATCH_ACCOUNT_REFRESH_INTERVAL_SEC 默认 600 秒
```

也就是客户端账号权益约 10 分钟自动刷新一次；签名权益快照的最长有效期也为 10 分钟。过期或服务端明确拒绝时，本机受保护 session / 权益快照会被清除。旧 `LIVEWATCH_LICENSE_REFRESH_INTERVAL_SEC` 属于卡密兼容路线，不能再作为新账号权限判断依据。

---

## 2. 产品功能总览

### 2.1 直播监听

已实现：

- 手动添加抖音直播间/直播号。
- 多房间监听。
- 弹幕/评论事件采集。
- 进入直播间、点赞、关注、粉丝团等事件采集。
- 在线人数、累计观看、点赞等直播数据记录。
- 录音分段落袋。
- 录制状态、断流、等待、异常等状态展示。
- 直播数据导出 Excel。
- 本地清理直播间数据。

设计边界：

- 不做自动绕验证码。
- 不做自动私信。
- 不把平台登录凭证提交到 Git。
- 遇到风控需要用户自己完成平台验证。

### 2.2 音频、转写、发言人

已实现：

- ffmpeg 拉流录音。
- SenseVoice ONNX 本地转写。
- 录音片段台账。
- 转写结果入库。
- 声纹/发言人 A、B、C 标注。
- Excel 导出里带发言人字段。

重要历史结论：

- 早期“多个房间轮流录一分钟”会漏大量音频，已经废弃。
- 当前方向是每个房间独立连续录制，尽量保证时间线可追溯。
- 不足 60 秒的片段也尽量保留，方便用户回溯。

### 2.3 AI 直播复盘

已实现：

- 选择主播/直播数据后生成 AI 复盘。
- AI 处理进度动画。
- 复盘简报。
- 完整 HTML 报告。
- PDF 导出。
- Markdown 下载方向已经纳入产品要求。
- 追问上下文，支持基于当前主播数据继续问。

用户非常在意体验：

- 处理过程必须有明显进度反馈。
- 不要让用户以为卡住。
- 报告不能是一大坨文字，需要图文混排、卡片、图表、摘要。
- 用户群体偏非技术，文案要短、直白、运营语言化。

### 2.4 效能分析

已实现：

- 直播效能评分页。
- 以直播数据和 AI 结果为依据展示评分。
- 支持按天/场次方向继续优化。

产品方向：

- 不要只用 Python 硬编码评分。
- Python 负责稳定指标、归一化、可视化。
- AI 负责语义判断、内容质量、运营诊断。
- 敏感词主要作为风险提示，不应重度压低评分。

### 2.5 短视频中心

已实现：

- 粘贴抖音主页链接解析账号。
- 解析作品列表。
- 展示作品封面、标题、点赞数。
- 选择作品进入 AI 工作台。
- 下载/查看逐字稿方向已接入。
- AI 评分、AI 拆解、爆款预测、对标学习方向已接入。
- 参考并改造 `XBuilderLAB/cheat-on-content` 的 MIT 方法论。

当前重要问题：

- 主页解析超过初始 20 条作品仍不稳定。
- 用户明确说抖音主页是“往下滑动加载”，不是传统翻页。
- “继续加十条/自定义条数”仍需继续修。
- AI评分和AI拆解应合并为一个动作，结果绑定到单个作品。
- AI 工作台和作品解析已逐步拆分，但前端仍需继续打磨。

### 2.6 AI 获客系统

已实现：

- 新增 `AI获客系统` tab。
- 输入抖音主页/视频后解析作品。
- 选择视频后采集评论。
- 评论去重入库。
- 展示评论人、评论内容、IP属地、时间。
- “主页”入口已经改为更业务化的“去联系”方向。

产品方向：

- 用户真正需要的是：监控竞品主页新作品评论。
- 流程应是：主页 -> 作品列表 -> 选择作品 -> 采集评论 -> AI 清洗线索 -> 客服跟进。
- 不建议自动批量私信，容易触发平台风险。
- 后续应加每天定时扫竞品新作品评论，例如每天早上 8 点。

### 2.7 手机号账号、产品权益与安装包

已实现：

- 手机号短信登录、系统保护的本机远端会话。
- 远端 `user_products` 三产品独立权益；复盘虾固定组合为 `replay_shrimp + livewatch`。
- Ed25519 `account_license` 原始字节验签、本地短时权益缓存与联网刷新。
- `web_handoff` 单次网页登录交接；Cookie、验证码和长期 session 不进入 URL 或前端。
- 微信支付官方回调是唯一权益开通来源；客户端只展示二维码和订单状态。
- Inno Setup 安装包。
- 商业包完整性清单与启动校验。
- 构建扫描阻止 cookie、db、日志、音频、源码等泄漏。

历史卡密后台：

```text
https://license.runmo.art/admin
```

新产品账号入口不是该后台，而是 `https://anyq.site`。不要把管理员令牌、服务器密码、私钥、短信或支付密钥写进仓库或报告。

---

## 3. 关键目录地图

### 3.1 主程序目录

```text
_experiments/douyin_worker_route/
├── pipeline/
│   ├── webui.py
│   ├── frontend.html
│   ├── config.py
│   ├── manager.py
│   ├── audio_capture.py
│   ├── transcript_store.py
│   ├── export.py
│   ├── ai_report.py
│   ├── performance_analysis.py
│   ├── short_video.py
│   ├── short_video_ai.py
│   ├── comment_leads.py
│   ├── anchor_profiles.py
│   ├── license_manager.py
│   ├── license_client.py
│   ├── license_policy.py
│   ├── license_refresh.py
│   └── license_clock.py
├── tests/
└── HANDOFF.md
```

### 3.2 授权服务器

```text
licensing_server/
├── app.py
├── service.py
├── admin_console.py
├── README.md
└── tests/
```

### 3.3 打包构建

```text
packaging/build/
├── livewatch_launcher.py
├── build_release.ps1
├── build_commercial_release.ps1
├── check_release.ps1
├── check_release.py
├── livewatch.iss
└── assets/
```

### 3.4 第三方声明

```text
THIRD_PARTY_NOTICES.md
third_party/cheat_on_content/
docs/DOUYIN_WSS_REPLACEMENT.md
```

---

## 4. 核心模块说明

| 文件 | 作用 |
|---|---|
| `pipeline/webui.py` | FastAPI 入口，托管前端，提供所有 `/api/*` |
| `pipeline/frontend.html` | 当前主要前端，单文件 Vue 3 + Element Plus |
| `pipeline/config.py` | 路径、模型、授权、录音、转写、AI、短视频配置 |
| `pipeline/manager.py` | 房间监听、录音线程、转写线程、状态管理 |
| `pipeline/audio_capture.py` | ffmpeg 取流、录音、封口、短段处理 |
| `pipeline/transcript_store.py` | SQLite 表结构、话术、事件、录音台账 |
| `pipeline/export.py` | Excel、汇总、报表导出 |
| `pipeline/ai_report.py` | AI 直播复盘、报告生成、追问 |
| `pipeline/performance_analysis.py` | 效能分析数据与评分逻辑 |
| `pipeline/short_video.py` | 抖音账号/作品解析、封面、音频、逐字稿 |
| `pipeline/short_video_ai.py` | 短视频 AI 评分、预测、拆解、对标学习 |
| `pipeline/comment_leads.py` | 评论线索采集、清洗、导出 |
| `pipeline/anchor_profiles.py` | 主播资料、头像缓存 |
| `pipeline/license_manager.py` | 本地授权缓存、验签、特性判断 |
| `pipeline/license_client.py` | 调用授权服务器激活/刷新 |
| `pipeline/license_policy.py` | API 与授权 feature 的对应关系 |
| `pipeline/license_refresh.py` | 后台定时刷新授权 |
| `pipeline/account_client.py` | HTTPS 手机号账号服务客户端，不向前端泄露远端 session |
| `pipeline/account_license.py` | `account_license` Ed25519 验签、schema、时间和受众校验 |
| `pipeline/account_manager.py` | 本机受保护 session、权益快照与登录状态 |
| `pipeline/account_policy.py` | 本地 API 到 `livewatch` 会员权益的映射 |
| `licensing_server/app.py` | 授权服务器 API 与后台路由 |
| `licensing_server/service.py` | 卡密、设备、签名、冻结、删除 |
| `licensing_server/admin_console.py` | 授权管理台 HTML |

---

## 5. 本地开发运行

开发态启动：

```powershell
cd C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route
python -m pipeline.webui --host 127.0.0.1 --port 8848
```

浏览器打开：

```text
http://127.0.0.1:8848
```

如果端口被占用，先找旧进程：

```powershell
Get-NetTCPConnection -LocalPort 8848 -ErrorAction SilentlyContinue
```

---

## 6. 测试命令

授权与构建核心测试：

```powershell
$env:PYTHONPATH='C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route'
python -m pytest licensing_server\tests\test_api.py licensing_server\tests\test_service.py _experiments\douyin_worker_route\tests\test_build_script_contract.py _experiments\douyin_worker_route\tests\test_integrity_manifest.py _experiments\douyin_worker_route\tests\test_license_client.py _experiments\douyin_worker_route\tests\test_license_refresh.py -q
```

2026-07-14 最近一次主线验证结果：

```text
255 passed
```

如果改前端，建议额外用 Playwright 或浏览器截图检查，不要只看代码。

如果改授权，至少跑：

```powershell
$env:PYTHONPATH='C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route'
python -m pytest licensing_server\tests _experiments\douyin_worker_route\tests\test_license_client.py _experiments\douyin_worker_route\tests\test_license_refresh.py -q
```

---

## 7. 打包与发布

账号版商业包构建大致流程：

```powershell
cd C:\Users\q2414\Desktop\live_watch
$env:LIVEWATCH_ACCOUNT_PUBLIC_KEY = "<account-v1 Ed25519 公钥，绝不是私钥>"
$env:LIVEWATCH_UPDATE_PUBLIC_KEY = "<update-v1 Ed25519 公钥，绝不是私钥>"
pwsh -NoProfile -File packaging\build\build_verified_release.ps1 -Version "1.1.25" -AccountApiUrl "https://anyq.site" -AccountPublicKey $env:LIVEWATCH_ACCOUNT_PUBLIC_KEY -UpdatePublicKey $env:LIVEWATCH_UPDATE_PUBLIC_KEY
```

当前线上签名更新版本：

```text
replay_shrimp 1.1.14
```

官方分发信息：

```text
下载地址: https://download.anyq.site/replay-shrimp/1.1.14/LiveWatchSetup_1.1.14.exe
SHA256: 4D41794C77049D5E5E84E25A0F731F05FA81FB7BFAF5EF82174FCC3BC65FE133
大小: 261169156 bytes
```

商业包必须注意：

- 不允许带 `.py` 业务源码泄漏。
- 不允许带 cookie、db、audio、exports、logs。
- 不允许带 AI Key。
- 账号公钥和更新公钥可以进入客户端，但用途必须分离；服务端私钥绝不能进入客户端。
- 每次正式包都要跑 `check_release`。
- 新包必须上传到新的版本对象路径；先验证 SHA-256、HTTP 200、`Content-Length` 与 `Accept-Ranges`，再更新官网链接和校验值。

---

## 8. 历史卡密授权服务器与管理后台（非新产品入口）

线上入口：

```text
https://license.runmo.art/admin
```

线上服务形态：

```text
nginx HTTPS 反代 -> 127.0.0.1:60001 -> FastAPI licensing_server
systemd 服务: livewatch-license.service
```

2026-07-13 已部署管理台改动：

- 标题改为 `直播复盘侠 · 授权管理台`。
- 删除无用的 `卡密前缀` 列。
- 删除 `干净授权` 列。
- 前端隐藏 `解绑` 按钮。
- 新增卡密删除按钮。
- 新增 `/admin/session` 管理员信任会话。
- 同一 IP、同一浏览器设备指纹、同一信任 cookie 命中时，24 小时内不用反复输入管理员令牌。
- 新卡保存完整卡密；旧卡如果没有加密记录会显示“旧卡未保存”。
- 卡密有效期下拉支持：1 分钟、一周、一个月、半年、一年。

线上改动前备份目录：

```text
/opt/livewatch-license/backup_admin_patch_20260713_115929
```

不要在文档、README、提交信息里写服务器密码、管理员 token、私钥。

---

## 9. 数据目录与禁止提交内容

开发态数据通常落在：

```text
_experiments/douyin_worker_route/
```

安装版用户数据通常落在：

```text
%LOCALAPPDATA%\LiveWatch\data
```

禁止提交：

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

不要无脑 `git add .`。

---

## 10. 最近关键改动

### 10.1 授权立即生效方向

已完成：

- 客户端默认每 10 分钟刷新授权。
- 服务器明确拒绝时，客户端不再当普通网络失败处理。
- 过期、冻结、删除会让客户端清掉本地可用状态。
- 管理后台可删除卡密。
- 线上后台已部署新版 UI。

### 10.2 商业完整性方向

已完成：

- 构建时生成完整性清单。
- 启动时校验关键文件。
- 后续新增普通文件也会被检查。
- 发布包扫描敏感文件。
- 构建脚本和测试已纳入回归。

### 10.3 UI 与产品方向

近期大量前端改动集中在：

- 短视频中心。
- AI 工作台。
- AI 获客系统。
- AI 复盘报告动效。
- 授权与系统设置。

用户对 UI 的要求很高：

- 看起来要像成熟商业软件。
- 文案要短。
- 操作链路要少。
- 用户不懂技术，不要展示过多内部术语。
- AI 等待过程必须“看起来在工作”。

---

## 11. 当前主要问题与优先级

### P0：短视频中心超过 20 条作品仍不稳定

用户明确说抖音主页不是翻页，是往下滑动加载。
当前“继续加十条/自定义条数”仍可能只能拿到初始 20 条。
真实账号已出现只读取 21～22 条的情况；验收目标应是在真实已登录主页稳定超过 30 条，而不是只验证按钮存在。
需要继续改 `pipeline/short_video.py` 和前端调用链。

### P0：评论完整性、数量展示与话术保留

用户给出的目标视频页面约有 26 条评论，当前实际只采到约 11 条，评论区 UI 也未明确展示平台总数、顶级评论数、已采集数、回复数、去重数和未采集原因。

- 重点检查 `pipeline/comment_leads.py` 的评论面板滚动、网络响应、顶级评论分页、回复分页与回复展开。
- 去重只允许按平台 `comment_id`；不同用户的相同话术、同一用户的不同评论和所有回复均必须保留，不能按昵称或评论文案去重。
- 未登录时不能误显示已登录；Edge / Chrome 登录后，直播、短视频和 AI 获客应共用同一真实有效抖音 Cookie。

### P0：AI 工作台与报告历史需要继续整理

用户希望：

- AI评分和AI拆解合并为一次动作。
- 报告绑定到单个作品。
- 历史报告可查看、下载。
- 下载支持 Markdown。
- 工作台队列可删除。
- 发送到工作台应追加，不应替换全部。

### P1：AI 获客系统要改成主页监控模型

当前已能采集选中视频评论。
下一步产品形态应是：

```text
添加竞品主页
  -> 解析主页作品
  -> 用户选择作品
  -> 采集评论
  -> AI 清洗线索
  -> 客服跟进
  -> 后续定时监控新作品
```

### P1：AI 复盘报告可读性仍需优化

用户不满意大段文字。
方向：

- 图文混排。
- 卡片化。
- 雷达图、趋势图、指标条。
- 少写技术词。
- 报告要适合直接给运营看。

### P1：账号体验与商业化还需继续验收

- 未登录点击受限功能时应先提示登录；无复盘虾权益时应提示“没有复盘虾会员权益”，不要向用户暴露解析、签名或网络内部错误。
- 三产品购买、登录、续费交接、签名验签、过期和跨产品隔离要继续做安装包端到端验收。

### P2：签名自动更新已接通，仍需新版端到端验收

- 客户端已实现 `update-v1` Ed25519 验签、固定产品 / 下载域名、版本、大小与 SHA-256 校验。
- 2026-07-16 账号服务已上线按产品隔离的 SSE 发布通知；新客户端接收后立即做签名检查，并以 60 秒轮询兜底。强制更新在运行中会阻止业务操作。
- 2026-07-15 实测三个线上接口均为 HTTP 200，并返回 `anyq.desktop-update.v1` 签名信封：`replay_shrimp=1.1.14`、`operation_shrimp=0.1.13`、`comic_shrimp=0.1.14`。
- 当前本地已构建到 `1.1.25`，但仍需从后台签名发布，使用安装在自定义目录的客户端完成“发现更新 → 下载 → 校验 → 覆盖安装 → 数据保留 → 新版启动”；再发布一个测试版本验证基线客户端在不重启情况下收到 SSE 并强制更新。

### P2：代码签名未做

安装包未签名，可能被 SmartScreen 或杀软提示。

---

## 12. 技术边界与合规提醒

必须遵守：

- 不提交平台 cookie。
- 不提交 AI Key。
- 不提交用户数据。
- 不提交服务器密码。
- 不提交授权私钥。
- 不引入许可证不清晰的第三方抓取核心。
- 不把自动绕验证码、自动私信、绕平台限制作为功能。

当前第三方策略：

- `cheat-on-content` 是 MIT，可保留声明并包装使用。
- 抖音直播 WSS 旧 vendor 路线已经尽量剥离，当前只保留必要参考声明，不应再扩大依赖。
- 如需要替代弹幕/协议实现，优先找 MIT/Apache/BSD 等明确可商用许可。

---

## 13. 下一个 AI 接手建议流程

1. 先读本文件。
2. 再读：

   ```text
   README.md
   DEVELOPMENT_LOG.md
   THIRD_PARTY_NOTICES.md
   _experiments/douyin_worker_route/HANDOFF.md
   ```

3. 看当前状态：

   ```powershell
   git status --short
   git log --oneline -5
   ```

4. 跑授权核心测试：

   ```powershell
   $env:PYTHONPATH='C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route'
   python -m pytest licensing_server\tests\test_api.py licensing_server\tests\test_service.py _experiments\douyin_worker_route\tests\test_license_client.py _experiments\douyin_worker_route\tests\test_license_refresh.py -q
   ```

5. 启动开发服务：

   ```powershell
   cd C:\Users\q2414\Desktop\live_watch\_experiments\douyin_worker_route
   python -m pipeline.webui --host 127.0.0.1 --port 8848
   ```

6. 优先处理真实主页超过 30 条作品和真实评论完整采集问题。
7. 修改前截图，修改后也截图。这个项目的前端体验非常重要。
8. 改账号、支付或权益时，必须同时考虑客户端、本地缓存、签名契约、服务端、官网和安装包；不能再以旧卡密字段为授权来源。

---

## 14. 常见坑

### 14.1 前端是单文件

主要前端都在：

```text
_experiments/douyin_worker_route/pipeline/frontend.html
```

这个文件很大，改动时要特别注意 Vue 模板语法和 CSS 作用域。

### 14.2 不要让页面出现横向滚动

用户多次反馈前端超出范围、布局难用。
改 UI 时请用浏览器全屏截图检查。

### 14.3 Playwright 浏览器资源

商业包曾出现：

```text
Executable doesn't exist ... chrome-headless-shell.exe
```

说明打包时浏览器资源路径或 `PLAYWRIGHT_BROWSERS_PATH` 不对。
相关逻辑在：

```text
packaging/build/livewatch_launcher.py
packaging/build/build_release.ps1
```

### 14.4 授权公钥必须和线上私钥匹配

如果客户端提示“授权验签失败”，优先检查：

- 安装包内置公钥是否是线上授权服务对应公钥。
- 线上服务是否换过密钥。
- 客户端是否拿到旧服务返回。
- 本地旧授权缓存是否污染。

### 14.5 管理台看不到变化

管理台是线上服务器部署的独立文件，不是本地改完就自动生效。
上次就是先本地改了，用户打开线上没变化。
需要部署到线上并重启 `livewatch-license.service`。

### 14.6 不要过度相信 AI 评分

用户多次强调：

- AI 要看全部数据。
- Python 只做数据统计和可视化。
- 最终运营判断要更像商业分析报告。
- 分数要能解释，不要所有主播都很接近。

---

## 15. 当前交接结论

这个项目现在能继续开发，也已经具备商业化雏形。
最需要下一位接手者注意的是：不要再把它当作单一爬虫项目，它已经是一个“本地商业软件 + 授权服务 + AI 运营分析工具”的组合系统。

下一步建议优先级：

```text
1. 修真实主页读取超过 30 条作品、指定视频评论完整采集与数量展示
2. 统一并实测 Edge / Chrome 抖音登录态在三个模块的复用
3. 整理短视频 AI 工作台和报告历史
4. 完善 AI 获客系统的主页监控链路
5. 构建并签名发布 `1.1.25+`，完成账号、自动更新、覆盖安装和数据保留端到端验收
```

## 16. 2026-07-17 线上 OSS 版本保留策略

安装包不再无限堆积在 OSS。线上 `recharge-api` 已部署 `release-retention.js`，按产品分别执行以下规则：

1. 以语义化版本排序，每个产品保留最新 3 个已发布版本。
2. 超出窗口的已发布版本、以及已撤回版本进入 7 天回收期；回收期内不会删除。
3. 回收期结束时服务端重新计算保留窗口，仍然过期才用 OSS 签名 DELETE 删除对应对象，并把发布记录标记为 `archived`。
4. 草稿、当前最新版本、重新回到最新 3 个的版本始终受保护；长期不发布新版本不会误删当前版本。
5. 任务启动后 10 秒首次运行，此后每 6 小时运行；失败任务每小时重试，状态保存在 SQLite `release_retention_jobs`。

管理后台版本发布页的“旧版本自动清理”卡片可查看待清理/已清理/失败数量并手动触发一次检查。首次上线仅排队，不会立即删除：复盘虾 `1.1.14`、已撤回 `0.1.21`、运营虾 `0.1.13` 的回收时间为 2026-07-24。远端备份在 `/home/ubuntu/recharge-api/backups/retention-20260717011800`。

## 17. 2026-07-20 本地交付收口

- 当前提交范围只包含复盘虾主线、打包脚本、测试和交接文档；漫剧虾、运营虾由各自 AI 维护，不在本仓库修改。
- 2026-07-20 验证命令：`$env:PYTHONPATH="$PWD\_experiments\douyin_worker_route"; python -m pytest _experiments\douyin_worker_route\tests packaging\build -q`，结果 `337 passed`、5 warnings。
- 交付前必须再次确认 `release/LiveWatchSetup_1.1.25.exe` 的 SHA-256、OSS 对象键、后台 `update_release` 产品码和 `update-v1` 签名公钥；本地构建成功不等于线上已发布。
