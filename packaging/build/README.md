# 直播复盘侠打包构建链

把 `_experiments/douyin_worker_route` 的最新源码打成 **完全离线、程序/数据分离、普通用户安装即用**
的 Windows 安装程序。**不改业务监听逻辑**，只新增打包层与少量路径解析（开发态行为完全不变）。

> 2026-07-15 校正：当前正式入口是 `一键打包复盘虾.bat` → `interactive_verified_release.ps1` → `build_verified_release.ps1`。线上复盘虾更新版本已是 `1.1.14`，下一次构建必须为 `1.1.15+`。账号 `account-v1` 公钥和更新 `update-v1` 公钥必须独立；旧 `build_commercial_release.ps1` 属于卡密构建兼容入口，不再用于正式账号版发包。

首次克隆构建仓库后先执行 `git lfs pull`，确保 `vendor/douyinlive/douyinLive.exe` 不是 LFS 指针；构建脚本会再校验其固定 SHA-256。

## 文件清单

| 文件 | 作用 |
|------|------|
| `livewatch_launcher.py` | PyInstaller 桌面客户端入口。注入数据/资源路径，启动 uvicorn 后端，并用 WebView2 独立窗口与系统托盘承载控制台。 |
| `build_release.ps1` | **一键可重复构建**。开发包拷源码；商业包会先用 Nuitka 编译整个业务包，再内置 node+模型、PyInstaller 运行时、安全扫描与 ISCC 安装程序。 |
| `build_verified_release.ps1` | 当前正式商业构建入口；固定账号 / 更新双公钥、产品码、Nuitka、完整性清单和扫描。 |
| `interactive_verified_release.ps1` / `run_verified_release.ps1` | 一键 BAT 的交互与日志保留层。 |
| `build_commercial_release.ps1` | 旧卡密构建兼容入口，禁止作为当前手机号账号版正式发包入口。 |
| `check_release.ps1` | 构建产物安全扫描。发现 Cookie / 数据库 / 音频 / 日志 / 开发房间号 → 立即 `exit 1` 让构建失败。 |
| `livewatch.iss` | Inno Setup 脚本。装到安装目录；覆盖升级保数据；卸载默认保留数据 + 明确「完全删除」选项。 |
| `smoke_test.ps1` | 全新目录安装冒烟测试：启动、模型路径、数据目录、覆盖升级保数据。 |
| `assets/README_使用说明.md` | 随安装包分发的最终用户说明。 |

## 程序 / 数据 / 资源 三分离

| 类别 | 位置 | 谁写 |
|------|------|------|
| 业务模块 + Node | `<安装目录>\app\` | 安装程序（只读） |
| 模型与验证浏览器 | `<安装目录>\models\`、`<安装目录>\browsers\` | 安装程序（只读） |
| 运行时（Python/FFmpeg/各依赖） | `<安装目录>\_internal\`、`LiveWatchLauncher.exe` | 安装程序（只读） |
| 用户数据 | `%LOCALAPPDATA%\LiveWatch\data\`（cookie、rooms.json、`*.db`、`audio\`、`exports\`、`logs\`） | 运行时 |

路径解析在 `pipeline/config.py`：两个环境变量未设置时（开发态）全部回退原相对路径，**行为零变化**；
设置后（打包态）数据落 `DATA_DIR`、模型落 `RESOURCE_DIR`。

## 构建命令

```powershell
# 前置：Python 3.13（建议）+ PyInstaller + Nuitka + Node + Inno Setup 6
python -m pip install -r packaging\build\requirements-build.txt

# 最简单：双击该 BAT，输入 1.1.15 或更高版本
packaging\build\一键打包复盘虾.bat

# 等价的非交互正式构建；两项都是公钥，不能相同，也不能填私钥
$env:LIVEWATCH_ACCOUNT_PUBLIC_KEY = "account-v1 Ed25519 SPKI base64url 公钥"
$env:LIVEWATCH_UPDATE_PUBLIC_KEY = "update-v1 Ed25519 SPKI base64url 公钥"
pwsh -NoProfile -File packaging\build\build_verified_release.ps1 `
  -Version 1.1.15 `
  -AccountApiUrl "https://anyq.site" `
  -AccountPublicKey $env:LIVEWATCH_ACCOUNT_PUBLIC_KEY `
  -UpdatePublicKey $env:LIVEWATCH_UPDATE_PUBLIC_KEY

# 可选代码签名
pwsh -NoProfile -File packaging\build\build_verified_release.ps1 `
  -Version 1.1.15 `
  -AccountPublicKey $env:LIVEWATCH_ACCOUNT_PUBLIC_KEY `
  -UpdatePublicKey $env:LIVEWATCH_UPDATE_PUBLIC_KEY `
  -CodeSignThumbprint "证书 SHA1 指纹"

# 单独跑安全扫描 / 冒烟测试：
pwsh -File packaging\build\check_release.ps1 -Target staging\LiveWatch
pwsh -File packaging\build\smoke_test.ps1
```

产物：`release\LiveWatchSetup_<版本>.exe`

## 官方下载页与校验安装

商业安装包上传到服务器后，对外请发官方下载页，不要让用户从 GitHub ZIP 或 LFS 指针文件获取：

```text
https://license.runmo.art/downloads/
```

优先发放 `InstallLiveWatchPortable.ps1`：它下载便携 ZIP，检查文件大小与 SHA256，
校验通过才会解压到本机程序目录并创建桌面快捷方式。这个路径不需要直接运行下载后的未签名 EXE，
能减少 Windows / Edge 的安全下载确认。脚本会优先调用系统自带 `curl.exe` 显示实时下载进度，
再回退到 PowerShell 流式下载；开发排障时可用 `-ArchivePath <本地zip>` 跳过重复下载。

`InstallLiveWatch.ps1` 是备用在线校验安装脚本：下载完整 EXE 安装包后，会同时检查文件大小与 SHA256，
校验通过才会启动 Inno Setup。两个脚本都不包含卡密、后台令牌、AI Key、私钥或任何用户数据。

当前签名更新通道版本（2026-07-15 实测）：

```text
Version: 1.1.14
URL:     https://download.anyq.site/replay-shrimp/1.1.14/LiveWatchSetup_1.1.14.exe
SHA256:  4D41794C77049D5E5E84E25A0F731F05FA81FB7BFAF5EF82174FCC3BC65FE133
Bytes:   261169156
```

未签名安装包在 Windows / Edge 上可能触发 SmartScreen 或安全下载确认。构建链能保证完整性、
校验和和自动更新，但无法伪造系统信任；要显著减少安全提示，需要购买受信任代码签名证书，
然后使用 `-CodeSignThumbprint` 构建。

## Windows 代码签名（建议商业发放启用）

`-CodeSignThumbprint` 是可选项：构建脚本会自动查找 `signtool.exe`，给
`LiveWatchLauncher.exe` 与最终 `LiveWatchSetup*.exe` 签名，并用 Windows
`Get-AuthenticodeSignature` 验签。它不隐藏业务逻辑，但能证明软件来源、检测被篡改，
并减少 Windows SmartScreen 对新安装包的拦截概率。需要另行购买受信任的代码签名证书；
私钥只应保留在证书存储或硬件令牌中，绝不能放进仓库或安装包。

## 可重复性

- 每次构建先 `Remove-Item` 清空 `staging\`，再全自动重建——**没有任何手工复制步骤**。
- 每次商业发包只跑 `一键打包复盘虾.bat` 或 `build_verified_release.ps1`，避免漏掉账号 / 更新公钥、
  Nuitka 编译、完整性签名或安全扫描。客户端只携带公钥，不读取任何后台 token 或私钥。
- 开发构建用**白名单**拷贝；商业构建把 `pipeline` 编译为单一 `.pyd`，并由扫描器拒绝任何业务 `.py` 源码。旧 `vendor\`、`run_worker.py`
  已不再允许进入产物），天然排除 `audio\`、`*.db`、
  `browser_cookies.json`、`rooms.json`、`exports\`、日志、样本、`__pycache__`、`_scratch*`。
- 安全扫描是构建的**强制关卡**，扫到任何敏感物即让整个构建失败；若产物含旧 AGPL vendor
  或 `run_worker.py`，也会失败。


