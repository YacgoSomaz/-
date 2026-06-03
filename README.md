# live_watch

抖音直播监听与话术采集研究工作区。当前目标是验证多技术路线在多直播间监听、弹幕入库、音频录制/转写、高并发风控压力下的可行性。

> 仅供个人学习、研究和内部验证使用。请遵守平台规则、相关法律法规和他人隐私权益。

## 当前状态

这个仓库目前不是生产部署包，而是一个研究/验证工作区。它保留了多条路线，方便回家后继续对照测试。

重要结论：

- 默认启动 `python server.py` 时，只会启动 dycast 批量控制台后端，不会自动运行 `worker/`。
- `worker/` 是 Claude 尝试的另一条后端 worker 技术路线，只有手动运行 `worker/run_worker.py` 或 `worker/run_multi.py` 才会参与。
- 当前代码可以本地启动和继续验证，但不能保证一部署就能稳定绕过抖音风控。
- 如果只是想跑现有控制台，请先忽略 `worker/` 目录。

仓库里保留了两条主要路线，方便并行测试：

1. `_experiments/dycast`
   - 当前主线工作目录。
   - 前端是 Vue/Vite 批量托管控制台。
   - 后端 `server.py` 提供 WebSocket 中继、SQLite 入库、导出服务、音频采集管理。
   - `worker/` 目录里是 Claude 正在尝试的后端 worker 路线，vendor 了 `DouyinLiveWebFetcher` 作为技术验证基础。

2. `_experiments/dycast_original_route_161517`
   - 从 2026-06-03 16:15 备份解压出来的原路线副本。
   - 已改成独立端口，方便和主线同时跑。
   - 用于高并发对照测试。

根目录的 `stream_url.py`、`recorder.py`、`transcriber.py` 是音频链路基础模块：取流、ffmpeg 切片录制、Whisper 转写。

## 端口规划

主线实例：

```text
前端控制台: http://127.0.0.1:5173/
WS 中继:    ws://localhost:8765
导出服务:   http://localhost:8766/
音频并发:   5
```

原路线副本：

```text
前端控制台: http://127.0.0.1:5174/
WS 中继:    ws://localhost:8775
导出服务:   http://localhost:8776/
音频并发:   10
```

## 快速启动

### 主线 dycast

```powershell
cd C:\Users\q2414\Desktop\live_watch\_experiments\dycast
pnpm install
python server.py
```

另开一个终端：

```powershell
cd C:\Users\q2414\Desktop\live_watch\_experiments\dycast
pnpm dev --host 127.0.0.1
```

打开：

```text
http://127.0.0.1:5173/
```

### 原路线副本

```powershell
cd C:\Users\q2414\Desktop\live_watch\_experiments\dycast_original_route_161517
pnpm install
python server.py
```

另开一个终端：

```powershell
cd C:\Users\q2414\Desktop\live_watch\_experiments\dycast_original_route_161517
pnpm dev --host 127.0.0.1 --port 5174
```

打开：

```text
http://127.0.0.1:5174/
```

## CSV 导入格式

控制台支持导入 CSV，推荐字段：

```csv
room_num,name,group,priority
10280167603,主播A,测试组,1
430322042715,主播B,测试组,2
```

也可以用直播间链接：

```csv
live_url,name,group,priority
https://live.douyin.com/10280167603,主播A,测试组,1
```

## 导出

主线实例：

```text
http://localhost:8766/
```

原路线副本：

```text
http://localhost:8776/
```

导出服务支持弹幕 CSV、弹幕 Excel、话术 CSV，以及清理本地测试数据。

## 测试命令

主线：

```powershell
cd C:\Users\q2414\Desktop\live_watch\_experiments\dycast
pnpm run build
python _test_audio_manager.py
```

原路线副本：

```powershell
cd C:\Users\q2414\Desktop\live_watch\_experiments\dycast_original_route_161517
pnpm run build
python _test_audio_manager.py
```

## 音频与转写

当前音频链路：

```text
直播间开播并连接弹幕
  -> 获取直播流地址
  -> ffmpeg 录制音频切片
  -> Whisper 转文字
  -> transcripts 入库
```

可用环境变量：

```powershell
$env:AUDIO_ENABLED="1"
$env:AUDIO_MAX_ROOMS="5"
$env:AUDIO_MODEL="base"
$env:AUDIO_SEGMENT_SEC="30"
python server.py
```

高并发测试时可以先关闭转写，只验证弹幕和连接稳定性：

```powershell
$env:AUDIO_ENABLED="0"
python server.py
```

## 后端 worker 路线

`_experiments/dycast/worker` 是新路线验证目录，目标是减少浏览器/Vite 代理在关键链路里的参与。

这个目录不会被 `server.py` 自动加载，也不会占用主线端口。它和主线是否“打架”，取决于是否手动同时运行 worker 脚本并监听同一批直播间。

重点文件：

```text
run_worker.py                       单房间 worker 验证
run_multi.py                        多房间 worker 验证
probe_audio.py                      无浏览器取流探测
make_mp3.py                         无浏览器取流并导出 mp3 验证
vendor/DouyinLiveWebFetcher/        第三方参考实现
```

注意：worker vendor 来自第三方开源项目，后续如果继续使用，需要单独核查许可证、维护成本和平台规则风险。

## 是否一部署就能用

不能这样承诺。当前仓库能保证的是：

- 代码、配置和两条测试路线已经保存到 GitHub。
- 主线 dycast 在本机验证过 `pnpm run build` 和 `_test_audio_manager.py`。
- 原路线副本也在本机验证过构建和音频管理器测试。
- 端口已经错开，主线和副本可以并行启动。

不能保证的是：

- 抖音风控状态解除。
- 任意网络环境下一定能拿到直播间页面、弹幕 WebSocket 或音频流。
- worker 路线已经达到生产可托管状态。
- 50 个号或 15 个号长期稳定并发。

回家后建议先按“小步验证”跑：

```text
1 个房间 -> 3 个房间 -> 5 个房间 -> 10 个房间
```

确认每一步能稳定入库和导出后，再继续加并发。

## 已忽略的数据

`.gitignore` 已排除：

```text
node_modules/
dist/
*.db
data/
exports/
relay_logs/
运行日志
真实弹幕样本
音视频产物
```

真实弹幕样本、数据库和导出文件不应提交到 GitHub。

## 当前问题记录

- 批量访问 `https://live.douyin.com/<room_num>` 或 `/dylive/<room_num>` 可能触发验证码/风控页。
- 30 秒切片更像是 CPU/磁盘/转写压力问题，不一定是风控主因。
- 高并发建议分路线测试：主线 5 个、原路线副本 10 个，避免同一房间重复监听。
- 更长期的方向是后端 worker 化：房间状态、WebSocket 连接、protobuf 解析、入库都尽量放到后端。

## 回家后建议步骤

```powershell
git clone https://github.com/YacgoSomaz/-.git
cd -
```

然后优先验证：

1. 主线 `dycast` 能否正常启动。
2. `worker/run_worker.py` 单房间是否可稳定拿弹幕。
3. 只录音不转写时，风控是否减少。
4. 5 + 10 双实例并发时，是否比单路线 15 个更稳定。
