#!/bin/bash
# LiveWatch — 双击即用
# 首次运行自动安装环境，之后直接启动
set -e

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/.venv"

# ---- 首次：自动装环境 ----
if [ ! -d "$VENV" ]; then
    echo "首次运行，正在配置环境（约 3-5 分钟）..."
    echo ""

    # Homebrew
    if ! command -v brew &>/dev/null; then
        echo "正在安装 Homebrew..."
        /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
        eval "$(/opt/homebrew/bin/brew shellenv 2>/dev/null || /usr/local/bin/brew shellenv 2>/dev/null)"
    fi

    # Python
    if ! command -v python3 &>/dev/null; then
        echo "正在安装 Python..."
        brew install python@3.13
    fi

    # Node.js
    if ! command -v node &>/dev/null; then
        echo "正在安装 Node.js..."
        brew install node
    fi

    # 虚拟环境 + 依赖
    echo "正在安装依赖..."
    python3 -m venv "$VENV"
    source "$VENV/bin/activate"
    pip install --upgrade pip -q
    pip install -r "$HERE/requirements.txt" -q
    python -m playwright install chromium

    echo ""
    echo "环境配置完成！"
    echo ""
fi

# ---- 依赖完整性检查（venv 存在但安装不完整时自动补装） ----
source "$VENV/bin/activate"
if ! python -c "import uvicorn" 2>/dev/null; then
    echo "检测到依赖不完整，正在补装..."
    pip install -r "$HERE/requirements.txt" -q
    python -m playwright install chromium
fi

# ---- 启动 ----
cd "$HERE"

export LIVEWATCH_RESOURCE_DIR="$HERE/models"

echo "LiveWatch 启动中..."
echo "按 Ctrl+C 停止"
echo ""

(sleep 2 && open "http://127.0.0.1:8848") &

python -m pipeline.webui --host 127.0.0.1 --port 8848
