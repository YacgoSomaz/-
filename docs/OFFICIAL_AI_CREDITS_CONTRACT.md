# 官方 AI 算力与积分协议

更新时间：2026-07-22。此协议适用于复盘虾、漫剧虾、运营虾。

## 目标

客户端同时保留两种 AI 来源：

- `custom`：用户自行在本机配置 OpenAI 兼容地址、模型和 API Key；费用由用户自己的供应商承担。
- `official`：客户端不接触模型地址或密钥，调用 `anyq.site` 官方算力服务；按任务扣算力积分。

官方模式不能由客户端提交或覆盖 `api_key`、`api_base`、`model`、`provider`、`system_prompt`。服务端是产品权益、余额、任务价格和扣费的唯一可信来源。

## 固定产品和任务

| 产品 | product_id | 所需权益 | task_type | 默认积分 |
| --- | --- | --- | --- | ---: |
| 复盘虾 | `replay_shrimp` | `livewatch` | `replay_report` | 60 |
| 复盘虾 | `replay_shrimp` | `livewatch` | `replay_advisor` | 8 |
| 漫剧虾 | `comic_shrimp` | `comic_course` | `comic_creation` | 30 |
| 运营虾 | `operation_shrimp` | `operation_course` | `operation_analysis` | 20 |
| 漫剧虾 | `comic_shrimp` | `comic_course` | `comic_image` | 30 |
| 运营虾 | `operation_shrimp` | `operation_course` | `operation_image` | 30 |

客户端不得使用其他产品的任务，也不得硬编码积分价格；应始终读取服务端任务目录。

## 客户端接口

所有请求必须走 HTTPS，携带当前产品的固定请求头：

```http
X-Product-Code: replay_shrimp
```

桌面端应通过其已加密保存的远端登录会话转发请求，绝不把远端会话 Cookie 暴露给本地网页 UI。

### 读取余额与任务目录

```http
GET /api/v1/ai/catalog?product_id=replay_shrimp
```

返回重点字段：

```json
{
  "ok": true,
  "product_id": "replay_shrimp",
  "balance": 120,
  "official_ai": {"enabled": true, "configured": true, "provider": "openai_compatible", "label": "官方 AI 算力"},
  "tasks": [{"task_type":"replay_report","name":"AI直播复盘报告","credits":60,"max_input_chars":18000,"enabled":true,"available":true}]
}
```

`configured=false` 时应展示“官方算力暂未开放”，不要自动降级到用户本机模型；只有用户主动选择 `custom` 才使用本地配置。

图片任务的 `output_kind` 为 `image`，成功任务通过 `job.result_assets` 返回安全下载地址。客户端只能使用该地址展示或下载图片，不得拼接 OSS/CDN 路径；图片结果默认 24 小时后过期。

### 创建官方任务

```http
POST /api/v1/ai/jobs
Content-Type: application/json
X-Product-Code: replay_shrimp
```

```json
{
  "product_id": "replay_shrimp",
  "task_type": "replay_report",
  "input_text": "客户端按本地数据整理后的证据文本",
  "idempotency_key": "每次用户动作生成的 UUID"
}
```

同一次点击、网络重试和查询必须复用同一 `idempotency_key`，不得重复扣费。成功返回 `job.result_text`；若返回 `202`，轮询下列查询接口。

```http
GET /api/v1/ai/jobs/:id
```

## 复盘虾客户端实现（2026-07-22）

- 设置页允许用户显式选择 `custom` 或 `official`；默认保持 `custom`，官方模式不可用时必须自动回到 `custom`，不能静默替换用户的本地模型。
- `official` 的报告请求只产生一次 `replay_report` 任务：客户端先从所选房间整理主播概览、高频词和转写证据，并将总输入限制为 18,000 字符。
- `official` 的“AI 专场顾问”只产生一次 `replay_advisor` 任务：包含最近对话和当前选中场次证据，总输入限制为 12,000 字符。
- 官方返回文本后仍由客户端写入本地 Markdown/HTML 报告；PDF 保持按需导出，报告历史接口无需感知服务端模型实现。
- 复盘虾本地代理只可调用当前固定产品 `replay_shrimp` 的上述两个任务；禁止转发浏览器任意构造的 `product_id`、`task_type`、价格或模型字段。

## 错误码与前端行为

| code | 展示/动作 |
| --- | --- |
| `AI_NOT_CONFIGURED` | 官方算力暂未开放；保留本地配置入口 |
| `AI_CREDITS_INSUFFICIENT` | 积分不足，跳转官网充值/联系管理员 |
| `AI_PRODUCT_NOT_ENTITLED` | 当前账号未开通本软件会员权益 |
| `AI_TASK_DISABLED` | 该官方 AI 服务暂未开放 |
| `AI_RATE_LIMITED` | 请求过于频繁，请稍后再试 |
| `AI_UPSTREAM_*` | 本次失败，积分会自动退回，请稍后再试 |

## 服务端字段与安全规范

- `ai_task_rules`：任务类型、产品绑定、显示名称、积分价格、输入/输出上限、启停状态。产品绑定不可由后台改写。
- `ai_credit_ledger`：每次预扣、结算、退款和后台调整都记录，余额不得小于零。
- `ai_jobs`：仅保存 `input_sha256`，不保存原始输入；成功结果最多保存 24 小时以支持幂等重试，随后自动清理。
- 服务端在调用模型前预扣积分；上游错误、超时或进程中断会退款。
- 管理后台的“官方AI算力 → 模型配置”可维护语言模型和图片模型。管理员每次保存时须重新填写完整地址、模型标识和 API Key；密钥永不回显。
- 模型地址、模型标识及 API Key 使用 AES-256-GCM 加密保存到 `official_ai_model_configs`；公开接口和日志不得返回其明文。
- 唯一需要长期保留在服务器环境变量的是 `OFFICIAL_AI_CONFIG_MASTER_KEY`，它只用于解密后台保存的模型配置，不能在后台读取或下载。`OFFICIAL_AI_TIMEOUT_MS` 可选保留在环境变量中。
- 图片模型即使已配置，也只有在对应产品任务明确接入后才可对用户开放和扣积分；不得把“已配置”表述为“已可生成”。
