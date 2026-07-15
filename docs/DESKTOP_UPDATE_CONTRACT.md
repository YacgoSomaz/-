# 三产品桌面更新协议（冻结版 v1）

适用产品：

- `replay_shrimp`（复盘虾）
- `comic_shrimp`（漫剧虾）
- `operation_shrimp`（运营虾）

上传 OSS **不会**触发客户端更新。只有管理员在账户服务发布一条签名更新记录后，客户端才会看到新版。

## 服务端

公开接口：

```text
GET /api/v1/releases/latest?product_id=<fixed product_id>
```

成功时只消费 `update_release`；根节点的任何版本、链接、强制更新字段均不是授权数据。

```json
{
  "ok": true,
  "update_release": {
    "schema": "anyq.desktop-update.v1",
    "alg": "Ed25519",
    "key_id": "update-v1",
    "payload": "base64url(UTF-8 JSON)",
    "signature": "base64url(Ed25519 signature)"
  }
}
```

没有已发布版本时返回 `{"ok":true,"update_release":null}`。

签名载荷固定包含：

```json
{
  "typ": "desktop-release",
  "iss": "https://anyq.site",
  "aud": "replay_shrimp",
  "issued_at": 1784068800,
  "signed_until": 1784072400,
  "product_id": "replay_shrimp",
  "version": "1.0.13",
  "min_supported_version": "1.0.12",
  "mandatory": false,
  "installer_url": "https://download.anyq.site/replay-shrimp/1.0.13/ReplayShrimpSetup_1.0.13.exe",
  "sha256": "<64位小写hex>",
  "size_bytes": 314182000,
  "notes": "修复说明",
  "published_at": "2026-07-14T12:00:00.000Z"
}
```

`aud` 与 `product_id` 必须等于编译到当前客户端的产品码；不能由网页、配置文件或用户输入选择。

生产环境必须配置独立于 `account-v1` 的密钥：

```text
UPDATE_SIGNING_PRIVATE_KEY=<base64url PKCS#8 DER Ed25519 私钥，仅服务器 .env>
UPDATE_SIGNING_KEY_ID=update-v1
UPDATE_RELEASE_TTL_SECONDS=3600
```

客户端只内置对应 SPKI DER 公钥（`update-v1`），绝不携带该私钥。账户权益继续使用独立的 `account-v1` 密钥，两个用途不能共用密钥。

管理员接口（登录账户 `role=admin` 且同源请求）：

```text
GET  /api/v1/admin/releases
POST /api/v1/admin/releases
POST /api/v1/admin/releases/:id/publish
POST /api/v1/admin/releases/:id/revoke
```

发布流程只允许 `draft → published`；撤回后不再对外返回。服务端保存 `product_releases`，不从 OSS 目录推断版本。

Nginx 必须让 `/api/` 代理到账户服务，且该规则要位于静态站点 `try_files` 之前。否则 `/api/v1/releases/latest` 会被静态首页吞掉，客户端会收到 HTML 而不是 JSON。

## 客户端必须执行的校验

1. 请求固定为自身 `product_id`，只能使用 HTTPS。
2. 验证 schema、算法、`key_id`、Ed25519 签名、签发方、受众、签名有效期，且拒绝 JSON 重复字段。
3. 只接受 `https://download.anyq.site/.../*.exe`，无查询串、无片段。
4. 拒绝降级或同版本覆盖；下载后同时核验字节数与 SHA-256。
5. `mandatory=true` 或 `current_version < min_supported_version` 才显示必须升级。普通更新只能提示，不能阻止用户继续使用。
6. 安装时打开可见安装向导；不要把“静默覆盖安装”作为默认行为。

## 每次发布操作

1. 打包、代码签名并在干净 Windows 环境试装。
2. 上传到不可覆盖的版本路径，例如 `replay-shrimp/1.0.13/ReplayShrimpSetup_1.0.13.exe`。
3. 本地计算 SHA-256 和文件大小，创建草稿记录。
4. 管理员复核产品码、版本、URL、大小和哈希后发布。
5. 用三款已安装客户端分别验证：只有对应产品能看到该更新，篡改返回内容不会下载。

旧版客户端曾使用已废弃的 `/v1/update`，无法自动获得这次修复；第一次迁移版需要从官网下载页或客服辅助安装入口分发。
