# 直播复盘侠第三方声明

本文档记录直播复盘侠当前直接使用或可选接入的第三方组件、来源与分发边界。本文档不是法律意见；正式商业发行前仍建议由负责人做一次许可证复核。

## 项目自有代码

直播复盘侠主程序的录音、转写、声纹、AI 复盘、导出、前端控制台、数据库台账与 sidecar JSON 接入适配层为项目自有实现。

主程序默认运行模式：

```text
LIVEWATCH_DANMU_BACKEND=audio_only
```

该模式不内置抖音弹幕 WSS 内核，仅通过已验证 Cookie 探测直播流并驱动录音/录像/转写/复盘。

## 抖音弹幕事件 sidecar（可选外部组件）

名称：`jwwsjlm/douyinLive`

来源：`https://github.com/jwwsjlm/douyinLive`

许可证：MIT License

用途：作为独立外部进程或 Docker 容器提供本地 WebSocket 服务，输出 JSON 事件。直播复盘侠只连接本地 `ws://127.0.0.1:1088/ws/<直播间号>` 并接收事件，不复制该项目源码进主程序。

当前验证版本：

```text
ghcr.io/jwwsjlm/douyinlive:v2.0.18
```

当前已验证事件：

- `live_status`：开播/下播状态
- `WebcastChatMessage`：弹幕
- `WebcastMemberMessage`：进场
- `WebcastRoomStatsMessage` / `WebcastRoomUserSeqMessage`：在线与累计观看统计
- `WebcastLikeMessage`、`WebcastSocialMessage`、`WebcastFansclubMessage`、`WebcastGiftMessage`：主程序保留映射，实际可用性取决于外部 sidecar 与直播间实时事件

发行边界：

- 若安装包不内置该 sidecar，只需在文档中说明可选接入来源。
- 若未来把该 sidecar 二进制、Docker 镜像或其源码随安装包分发，必须同时附带该项目 MIT License 与版权声明。
- 不得把该 sidecar 的源码直接复制进主程序后删除原始许可证声明。

## 已移除的旧 WSS 内核

旧路径：

```text
run_worker.py
vendor/DouyinLiveWebFetcher/
```

当前状态：

- 不再作为默认后端。
- 不再进入安装包。
- 构建安全扫描会拦截旧 `vendor/DouyinLiveWebFetcher` 或 `run_worker.py`。

## 前端静态库

主程序前端使用以下随包静态文件：

- Vue 3 runtime：文件内声明 MIT License。
- Element Plus：文件内声明 MIT License，并包含 Lodash / Underscore 等上游许可提示。

如未来替换或升级前端静态库，应保留其文件头许可证声明。

## 短视频评分与预测工作流参考

名称：`XBuilderLAB/cheat-on-content`

来源：`https://github.com/XBuilderLAB/cheat-on-content`

许可证：MIT License

用途：本产品部分短视频评分、预测、复盘工作流参考并改造自该项目的方法论与提示词结构，用于「作品潜力分」「爆款预测」「对标账号学习」「发布后复盘」等本地产品能力。

本产品不在用户界面暴露该项目名称，不把其命令、skill、rubric、prompt 等原始概念直接呈现给最终用户；用户只看到面向运营场景的分数、预测区间、加分点、问题点、优化建议与复盘结论。

随项目保留的参考材料路径：

```text
third_party/cheat_on_content/
```

分发要求：

- 若安装包分发上述参考材料，应同时保留该项目 MIT License。
- 若未来继续改造其工作流，应在本文档中保留来源说明。
- 不得删除原项目许可证后声称该参考材料为项目自有原创。

## AI / ASR / 声纹模型

安装包当前会携带语音识别、声纹与 VAD 相关模型文件。当前项目按以下来源登记：

- SenseVoice / FunASR 语音识别模型
  - 本地文件：`models/sensevoice_onnx/model.int8.onnx`、`models/sensevoice_onnx/tokens.txt`
  - 上游：FunAudioLLM/SenseVoice、modelscope/FunASR
  - 许可证登记：SenseVoice 仓库的 LICENSE 指向 FunASR；FunASR 模型权重使用 `FunASR Model Open Source License Agreement Version 1.1`。
  - 分发要求：保留模型名称、来源与作者信息；正式发行时建议随包附带该模型许可证全文或许可证链接。
- 3D-Speaker 声纹模型
  - 本地文件：`models/speaker/3dspeaker_eres2net_zh_16k.onnx`
  - 上游：modelscope/3D-Speaker
  - 许可证登记：Apache License 2.0。
  - 分发要求：保留 Apache-2.0 许可证与版权声明。
- Silero VAD 模型
  - 本地文件：`models/speaker/silero_vad.onnx`
  - 上游：snakers4/silero-vad
  - 许可证登记：MIT License。
  - 分发要求：保留 MIT 许可证与版权声明。

说明：模型文件本身不进入 Git；安装包构建脚本从本地模型目录复制到 staging，并由安全扫描阻止数据库、录音、Cookie、AI Key 等用户数据进入安装包。

## 使用边界

直播复盘侠用于本机处理用户自行配置的公开直播监听、录音、转写和复盘。用户应自行确认其使用场景符合平台规则、当地法律法规及内部合规要求。
