# 直播复盘侠打包构建链

把 `_experiments/douyin_worker_route` 的最新源码打成 **完全离线、程序/数据分离、普通用户安装即用**
的 Windows 安装程序。**不改业务监听逻辑**，只新增打包层与少量路径解析（开发态行为完全不变）。

## 文件清单

| 文件 | 作用 |
|------|------|
| `livewatch_launcher.py` | PyInstaller 桌面客户端入口。注入数据/资源路径，启动 uvicorn 后端，并用 WebView2 独立窗口与系统托盘承载控制台。 |
| `build_release.ps1` | **一键可重复构建**。开发包拷源码；商业包会先用 Nuitka 编译整个业务包，再内置 node+模型、PyInstaller 运行时、安全扫描与 ISCC 安装程序。 |
| `build_commercial_release.ps1` | **一键商业加固构建入口**。自动固定 `-Commercial`，从环境变量或授权服务器取公钥，再调用 `build_release.ps1`；不保存后台 token。 |
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
# 前置：Python + PyInstaller、Nuitka、Node（取 node.exe）、Inno Setup 6（提供 ISCC.exe）
python -m pip install -r packaging\build\requirements-build.txt
pwsh -File packaging\build\build_release.ps1 -Version 1.0.0

# 只产 staging、不编译安装程序：
pwsh -File packaging\build\build_release.ps1 -SkipInstaller

# 商业包：仅嵌入公钥和 HTTPS 授权服务地址；业务 pipeline 不携带 .py 源码
pwsh -File packaging\build\build_release.ps1 -Commercial `
  -LicenseServerUrl "https://license.example.com" `
  -LicensePublicKey "Ed25519_base64url_公钥" `
  -Version 1.1.0

# 推荐商业发包入口：固定商业加固流水线。
# 方式 A：直接给授权公钥（最适合离线构建机）。
$env:LIVEWATCH_LICENSE_PUBLIC_KEY = "Ed25519_base64url_公钥"
pwsh -File packaging\build\build_commercial_release.ps1 -Version 1.1.0

# 方式 B：临时用管理后台令牌拉取公钥；令牌不会写进安装包。
$env:LIVEWATCH_LICENSE_ADMIN_TOKEN = "管理后台令牌"
pwsh -File packaging\build\build_commercial_release.ps1 `
  -LicenseServerUrl "https://license.runmo.art" `
  -Version 1.1.0

# 可选：给启动器与安装程序加 Windows Authenticode 签名。
# 证书安装到当前 Windows 用户的证书存储后，填入证书指纹即可。
pwsh -File packaging\build\build_commercial_release.ps1 `
  -CodeSignThumbprint "证书SHA1指纹" `
  -Version 1.1.0

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

当前发放版本：

```text
Version: 1.0.2
URL:     https://license.runmo.art/downloads/LiveWatchSetup_1.0.2.exe
SHA256:  53D6E00CF285E1DE31E14FD57E4155B16B9D23A1482D14974DCA8A6503DF1F72
Bytes:   329330062

Portable URL:    https://license.runmo.art/downloads/LiveWatchPortable_1.0.2.zip
Portable SHA256: 34D0AFC96CDB4AC0B0F51F6E01DBF6E9E96FD9C22606C11F3FF6BED051740BE6
Portable Bytes:  391625121
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
- 每次商业发包建议只跑 `build_commercial_release.ps1`。它会自动进入商业模式，避免漏掉授权、
  Nuitka 编译、完整性签名或安全扫描。授权后台 token 只从环境变量读取，不写入仓库和安装包。
- 开发构建用**白名单**拷贝；商业构建把 `pipeline` 编译为单一 `.pyd`，并由扫描器拒绝任何业务 `.py` 源码。旧 `vendor\`、`run_worker.py`
  已不再允许进入产物），天然排除 `audio\`、`*.db`、
  `browser_cookies.json`、`rooms.json`、`exports\`、日志、样本、`__pycache__`、`_scratch*`。
- 安全扫描是构建的**强制关卡**，扫到任何敏感物即让整个构建失败；若产物含旧 AGPL vendor
  或 `run_worker.py`，也会失败。


