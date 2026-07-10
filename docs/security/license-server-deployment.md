# 商业授权服务器部署

## 需要准备的资源

- 一台 Linux VPS：前期 `1 核 / 1 GB 内存 / 10 GB 磁盘` 足够。
- 一个域名或二级域名，例如 `license.example.com`。
- DNS 管理权限，用于把该域名的 A 记录指向 VPS 公网 IP。

域名不是程序运行的硬条件，但生产激活必须走 HTTPS。用域名配免费 TLS 证书是最稳的做法；不要让客户安装包访问裸 IP 或忽略证书错误。

## 服务器安装

以下以 Ubuntu 24.04 为例：

```bash
sudo apt update
sudo apt install -y python3-venv caddy
sudo useradd --system --create-home --shell /usr/sbin/nologin livewatch-license
sudo mkdir -p /opt/livewatch-license
sudo chown -R livewatch-license:livewatch-license /opt/livewatch-license
```

把仓库中的 `licensing_server/` 上传或从私有 Git 仓库拉到 `/opt/livewatch-license/app/licensing_server`。在服务器上创建虚拟环境并安装依赖：

```bash
sudo -u livewatch-license python3 -m venv /opt/livewatch-license/venv
sudo -u livewatch-license /opt/livewatch-license/venv/bin/pip install -r /opt/livewatch-license/app/licensing_server/requirements.txt
```

创建 `/etc/livewatch-license.env`，权限必须是 `600`：

```ini
LICENSE_DB_PATH=/var/lib/livewatch-license/licenses.db
LICENSE_SIGNING_PRIVATE_KEY=服务器生成的base64url私钥
LICENSE_TOKEN_HASH_SECRET=至少32位随机字符串
LICENSE_ADMIN_TOKEN=至少32位随机字符串
LICENSE_PRODUCT_CODE=live_replay_xia
LICENSE_DOCUMENT_DAYS=3
LICENSE_GRACE_DAYS=1
LICENSE_RATE_LIMIT_WINDOW_SEC=60
LICENSE_RATE_LIMIT_ACTIVATE=8
LICENSE_RATE_LIMIT_REFRESH=60
LICENSE_TRUSTED_PROXY_IPS=127.0.0.1,::1
```

```bash
sudo install -d -o livewatch-license -g livewatch-license /var/lib/livewatch-license
sudo chown root:livewatch-license /etc/livewatch-license.env
sudo chmod 640 /etc/livewatch-license.env
```

创建 `/etc/systemd/system/livewatch-license.service`：

```ini
[Unit]
Description=LiveWatch licensing service
After=network.target

[Service]
User=livewatch-license
Group=livewatch-license
WorkingDirectory=/opt/livewatch-license/app
EnvironmentFile=/etc/livewatch-license.env
ExecStart=/opt/livewatch-license/venv/bin/uvicorn --factory licensing_server.app:create_app_from_env --host 127.0.0.1 --port 9077
Restart=always
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true

[Install]
WantedBy=multi-user.target
```

启动服务：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now livewatch-license
sudo systemctl status livewatch-license
```

## HTTPS 与域名

把 DNS 的 `license.example.com` A 记录指向服务器公网 IP，随后配置 `/etc/caddy/Caddyfile`：

```caddy
license.example.com {
    reverse_proxy 127.0.0.1:9077
}
```

```bash
sudo caddy validate --config /etc/caddy/Caddyfile
sudo systemctl reload caddy
curl https://license.example.com/v1/health
```

预期返回：

```json
{"ok":true}
```

授权管理台地址：`https://license.example.com/admin`。首次访问输入 `LICENSE_ADMIN_TOKEN` 后即可发卡、查看设备、冻结与解绑；令牌不会写入浏览器本地存储。

公开的激活、刷新接口按来源 IP 限流：默认激活每分钟 8 次、刷新每分钟 60 次。服务仅监听
`127.0.0.1`，由 Caddy 写入 `X-Forwarded-For`；因此不要把 Uvicorn 直接暴露在公网，也不要把
不可信 IP 加进 `LICENSE_TRUSTED_PROXY_IPS`。

## 商业安装包构建

将服务端生成的 `LIVEWATCH_LICENSE_PUBLIC_KEY` 作为构建参数传入。私钥绝不能传给本地安装包构建脚本。

```powershell
pwsh -File packaging\build\build_release.ps1 -Commercial `
  -LicenseServerUrl "https://license.example.com" `
  -LicensePublicKey "服务端对应的Ed25519公钥" `
  -Version "1.1.0"
```

商业包首次启动显示卡密输入框；不激活时，商业功能会返回“需要有效商业授权”。

## 运营规则

- 默认一张卡绑定一台设备；客户换电脑时先解绑旧设备，再让其重新激活。
- 冻结用于退款、测试期结束或异常使用；联网客户端会在下一次刷新时停用。
- 每天备份 `/var/lib/livewatch-license/licenses.db`，备份文件加密并放到与主机不同的位置。
- 私钥一旦泄露，必须生成新密钥对、升级客户端公钥并重新签发全部授权。
