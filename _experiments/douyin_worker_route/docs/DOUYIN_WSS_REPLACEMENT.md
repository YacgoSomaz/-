# 抖音事件后端替换状态

## 当前结论

项目默认不再内置旧的 DouyinLiveWebFetcher / run_worker 路线。桌面端和开发态默认使用：

```text
LIVEWATCH_DANMU_BACKEND=audio_only
```

`audio_only` 是项目自有的轻量开播探测后端：它只用已有信任 Cookie 请求直播间页并解析可播放流，负责驱动录音、录像、转写和 AI 复盘，不连接弹幕 WSS，也不写入弹幕/点赞/进场事件。

如果后续需要弹幕/进场/点赞事件，应接入外部事件服务：

```text
LIVEWATCH_DANMU_BACKEND=sidecar
LIVEWATCH_DOUYIN_SIDECAR_WS=ws://127.0.0.1:8787
```

sidecar 必须作为独立组件维护许可证和来源声明，主项目只通过 JSON WebSocket 接收事件并写入 `SqliteSink`。

## 已完成

- `pipeline.audio_capture` 使用项目自有取流逻辑，不导入旧 WSS 内核。
- `pipeline.audio_only_fetcher.AudioOnlyFetcher` 成为默认后端，用直播流可用性判断开播状态。
- `pipeline.danmu_backend` 只支持 `audio_only` 与 `sidecar`，不再支持 `vendor`。
- `pipeline.manager` 通过后端工厂接入状态回调，默认不需要旧 worker。
- 打包脚本采用白名单拷贝，不打包 `vendor/` 或 `run_worker.py`。
- 安全扫描发现旧 vendor 或 `run_worker.py` 会直接失败。

## 功能边界

`audio_only` 能保留核心正向业务链路：

- 直播开播探测
- 音频/视频录制
- SenseVoice 转写
- 声纹标注
- AI 复盘与导出

`audio_only` 不产生这些数据：

- 弹幕文本
- 点赞事件
- 进场/member 事件
- social/fansclub 事件

这些数据需要由后续自研或许可证清晰的外部 sidecar 提供。

## 后续路线

1. 保持主程序默认 `audio_only`，确保安装包不包含许可证不明代码。
2. 如需恢复弹幕事件，优先实现自研 sidecar 或接入 MIT/Apache 等明确许可的外部 sidecar。
3. sidecar 与主程序之间只传 JSON 事件，主程序不复制第三方协议实现源码。
4. 第三方组件进入发行包前，必须补齐 LICENSE 与 THIRD_PARTY_NOTICES。

## 已验证的外部 sidecar

已用 `jwwsjlm/douyinLive` 的 `v2.0.18` Docker 镜像做过本机验证。该项目仓库标注 MIT License，服务输出格式包含 `live_status`、`method`、`livename`、`avatarThumb`，可被 `pipeline.douyin_sidecar_client.SidecarFetcher` 直接消费。

本机验证命令示意：

```powershell
# 1. 准备外部 sidecar 配置 config.yaml，cookie 使用本机已验证的抖音 Cookie。
#    不要把 config.yaml 提交进仓库。

# 2. 启动外部 sidecar，默认监听 1088。
docker run -d --name livewatch-douyin-sidecar `
  -p 1088:1088 `
  -v "$env:TEMP\livewatch-douyin-sidecar\config.yaml:/app/config.yaml" `
  ghcr.io/jwwsjlm/douyinlive:v2.0.18

# 3. 启动主程序时切到 sidecar 后端。
$env:LIVEWATCH_DANMU_BACKEND="sidecar"
$env:LIVEWATCH_DOUYIN_SIDECAR_WS="ws://127.0.0.1:1088"
python -m pipeline.webui --port 8848
```

验证结果：连接 `127453393722` 时，sidecar 返回 `live_status=true`，主程序通过 sidecar 写入 `multi_events.db` 的 `stat` 事件，例如：

```text
event_type=stat
content=current=2734;total_pv=8167176
```

目前确认可用的数据：开播状态、主播昵称/头像、直播统计事件。弹幕、点赞、进场、礼物等事件取决于直播间是否实时产生对应消息，以及外部 sidecar 对该消息类型的解析覆盖。
