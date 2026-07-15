# 50 个抖音直播间监听方案

## 当前已验证

- `dycast` 可以连接单个抖音直播间并解析实时弹幕。
- 转发地址填 `ws://localhost:8765` 后，弹幕可进入本地 collector。
- collector 会双写：
  - 原始 JSONL：`_experiments/dycast/relay_logs/`
  - 结构化 SQLite：`_experiments/dycast/dycast_messages.db`
- 导出脚本：`_experiments/dycast/export_messages.py`

## 立即可用的导出命令

导出全部消息：

```powershell
python _experiments\dycast\export_messages.py --format csv --out exports\all_messages.csv
```

只导出某个房间：

```powershell
python _experiments\dycast\export_messages.py --room 430322042715 --format csv --out exports\room_430322042715.csv
```

只导出评论消息：

```powershell
python _experiments\dycast\export_messages.py --method WebcastChatMessage --format csv --out exports\chat_messages.csv
```

按时间导出：

```powershell
python _experiments\dycast\export_messages.py --from-time 2026-06-03T00:00:00+00:00 --to-time 2026-06-03T12:00:00+00:00 --format csv --out exports\range.csv
```

## 50 个账号的推荐架构

不要长期用 50 个可视化页面手动监听。正式版建议拆成 5 层：

1. 账号配置层
   - 文件：`rooms.json`
   - 字段：账号名、直播间号、分组、优先级、是否启用、常见开播时间段。

2. 开播探测层
   - 每 1-3 分钟轮询账号直播页。
   - 只对“正在直播”的账号启动监听任务。
   - 未开播账号不占用 WebSocket 连接。

3. 监听任务池
   - 限制同时监听数量，例如 8-15 个。
   - 每个任务负责一个直播间：连接、解析、断线重连、结束检测。
   - 对高优先级账号优先抢占任务位。

4. 统一存储层
   - SQLite 适合 MVP。
   - 正式跑 50 个账号建议换 PostgreSQL。
   - 核心表：直播间、直播场次、弹幕消息、话术转写、关键词命中。

5. 导出和分析层
   - CSV/JSONL 导出。
   - 后续可加关键词统计、用户高频词、竞品价格识别、直播复盘摘要。

## 当前实验版的限制

- dycast 页面一次只能连一个直播间，适合验证能力。
- 50 个账号需要把 dycast 的连接和解析逻辑搬到后台 worker，或用 Playwright 批量打开 headless 页面。
- 批量监听要做限流和重连，避免一次性连接太多导致账号/IP 风控。
- 竞争对手直播间数据采集需要确认平台条款和内部合规边界。

## 下一步开发顺序

1. 先把 `rooms.example.json` 复制成 `rooms.json`，填入 50 个账号。
2. 做开播探测脚本，只输出“哪些账号正在直播”。
3. 做任务池，只监听正在直播的账号。
4. 把评论写入现在的 SQLite collector 表。
5. 加导出页面或定时导出任务。
