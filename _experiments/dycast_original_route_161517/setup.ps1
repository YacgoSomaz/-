# 一键环境准备脚本（PowerShell）
# 运行前确保 Python 3.11+ 已安装

Write-Host "=== 安装 Python 依赖 ===" -ForegroundColor Cyan
pip install -r requirements.txt

Write-Host "`n=== 安装 Playwright 浏览器 ===" -ForegroundColor Cyan
playwright install chromium

Write-Host "`n=== 编译 Protobuf ===" -ForegroundColor Cyan
# 需要 protoc，可从 https://github.com/protocolbuffers/protobuf/releases 下载
# 或用 pip install grpcio-tools
python -m grpc_tools.protoc -I. --python_out=. douyin.proto
if ($LASTEXITCODE -ne 0) {
    Write-Host "grpcio-tools 未安装，尝试备用方式..." -ForegroundColor Yellow
    pip install grpcio-tools
    python -m grpc_tools.protoc -I. --python_out=. douyin.proto
}

Write-Host "`n=== 检查 ffmpeg ===" -ForegroundColor Cyan
try {
    $null = & ffmpeg -version 2>&1
    Write-Host "ffmpeg 已就绪" -ForegroundColor Green
} catch {
    Write-Host "ffmpeg 未找到，请下载并添加到 PATH:" -ForegroundColor Red
    Write-Host "  https://github.com/BtbN/FFmpeg-Builds/releases" -ForegroundColor Yellow
}

Write-Host "`n=== 检查 streamlink ===" -ForegroundColor Cyan
try {
    $null = & streamlink --version 2>&1
    Write-Host "streamlink 已就绪" -ForegroundColor Green
} catch {
    Write-Host "streamlink 未找到，正在安装..." -ForegroundColor Yellow
    pip install streamlink
}

Write-Host "`n=== 环境准备完成 ===" -ForegroundColor Green
Write-Host "运行方式：" -ForegroundColor White
Write-Host '  $env:DOUYIN_LIVE_URL="https://live.douyin.com/你的直播间ID"'
Write-Host "  python main.py"
Write-Host "  python main.py --comments-only   # 只监听评论"
Write-Host "  python main.py --audio-only      # 只录音转写"
