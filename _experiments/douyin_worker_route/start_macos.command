#!/bin/bash
# LiveWatch macOS 启动脚本
# 双击或终端执行: ./start_macos.command
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/.venv"

if [ ! -d "$VENV" ]; then
    echo "尚未安装，请先运行: ./setup_macos.sh"
    exit 1
fi

source "$VENV/bin/activate"
cd "$HERE"

echo "LiveWatch 启动中..."
echo "浏览器打开: http://127.0.0.1:8848"
echo "按 Ctrl+C 停止"
echo ""

# 启动后自动打开浏览器
(sleep 2 && open "http://127.0.0.1:8848") &

python -m pipeline.webui --host 127.0.0.1 --port 8848
