#!/bin/bash
# LiveWatch macOS 一键安装脚本
# 用法: chmod +x setup_macos.sh && ./setup_macos.sh
set -e

echo "=============================="
echo "  LiveWatch macOS 安装脚本"
echo "=============================="
echo ""

HERE="$(cd "$(dirname "$0")" && pwd)"
VENV="$HERE/.venv"

# ---- 1. 检查 Python ----
echo "[1/6] 检查 Python..."
if command -v python3 &>/dev/null; then
    PY=$(command -v python3)
    PY_VER=$($PY --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
    MAJOR=$(echo "$PY_VER" | cut -d. -f1)
    MINOR=$(echo "$PY_VER" | cut -d. -f2)
    if [ "$MAJOR" -lt 3 ] || { [ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 11 ]; }; then
        echo "  需要 Python 3.11+，当前 $PY_VER"
        echo "  请安装: brew install python@3.13"
        exit 1
    fi
    echo "  Python $PY_VER OK"
else
    echo "  未找到 python3，请安装:"
    echo "    brew install python@3.13"
    echo "  或从 https://www.python.org/downloads/ 下载"
    exit 1
fi

# ---- 2. 检查 Node.js ----
echo "[2/6] 检查 Node.js..."
if command -v node &>/dev/null; then
    echo "  Node $(node --version) OK"
else
    echo "  未找到 node，请安装:"
    echo "    brew install node"
    exit 1
fi

# ---- 3. 创建虚拟环境 ----
echo "[3/6] 创建虚拟环境..."
if [ ! -d "$VENV" ]; then
    $PY -m venv "$VENV"
    echo "  已创建 $VENV"
else
    echo "  已存在，跳过"
fi
source "$VENV/bin/activate"

# ---- 4. 安装依赖 ----
echo "[4/6] 安装 Python 依赖..."
pip install --upgrade pip -q
pip install -r "$HERE/requirements.txt" -q
echo "  依赖安装完成"

# ---- 5. 安装 Playwright 浏览器 ----
echo "[5/6] 安装 Playwright Chromium（用于 Cookie 验证）..."
python -m playwright install chromium
echo "  Chromium 安装完成"

# ---- 6. 检查模型 ----
echo "[6/6] 检查 ASR 模型..."
ASR_DIR="$HERE/../asr_bench/sensevoice_onnx"
SPK_DIR="$HERE/../speaker_change_analysis/models"
if [ -f "$ASR_DIR/model.int8.onnx" ]; then
    echo "  SenseVoice 模型 OK"
else
    echo "  [!] 未找到 SenseVoice 模型"
    echo "      请将 sensevoice_onnx/ 放到 $ASR_DIR"
    echo "      (转写功能暂不可用，其他功能正常)"
fi
if [ -f "$SPK_DIR/3dspeaker_eres2net_zh_16k.onnx" ]; then
    echo "  3D-Speaker 模型 OK"
else
    echo "  [!] 未找到声纹模型（可选，不影响主功能）"
fi

# ---- 完成 ----
echo ""
echo "=============================="
echo "  安装完成！"
echo ""
echo "  启动方式:"
echo "    ./start_macos.sh"
echo ""
echo "  然后在浏览器打开:"
echo "    http://localhost:8848"
echo "=============================="
