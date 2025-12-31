#!/bin/bash
# VoCoType Linux IBus 语音输入法安装脚本（用户级安装）
# 基于 VoCoType 核心引擎: https://github.com/233stone/vocotype-cli

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"

# 用户级安装路径
INSTALL_DIR="$HOME/.local/share/vocotype"
COMPONENT_DIR="$HOME/.local/share/ibus/component"
LIBEXEC_DIR="$HOME/.local/libexec"

echo "=== VoCoType IBus 语音输入法安装 ==="
echo "项目目录: $PROJECT_DIR"
echo "安装目录: $INSTALL_DIR"
echo ""

# 0. 音频设备配置
echo "[0/5] 音频设备配置..."
echo ""
echo "首先需要配置您的麦克风设备。"
echo "这个过程会："
echo "  - 列出可用的音频输入设备"
echo "  - 测试录音和播放"
echo "  - 验证语音识别效果"
echo ""

if ! "$PROJECT_DIR/.venv/bin/python" "$PROJECT_DIR/scripts/setup-audio.py"; then
    echo ""
    echo "音频配置失败或被取消。"
    echo "请稍后运行以下命令重新配置："
    echo "  $PROJECT_DIR/.venv/bin/python $PROJECT_DIR/scripts/setup-audio.py"
    exit 1
fi

echo ""

# 1. 创建目录
echo "[1/5] 创建安装目录..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$COMPONENT_DIR"
mkdir -p "$LIBEXEC_DIR"

# 2. 复制项目文件
echo "[2/5] 复制项目文件..."
cp -r "$PROJECT_DIR/app" "$INSTALL_DIR/"
cp -r "$PROJECT_DIR/ibus" "$INSTALL_DIR/"

# 3. 创建启动脚本
echo "[3/5] 创建启动脚本..."
cat > "$LIBEXEC_DIR/ibus-engine-vocotype" << 'LAUNCHER'
#!/bin/bash
# VoCoType IBus Engine Launcher

VOCOTYPE_HOME="$HOME/.local/share/vocotype"
PROJECT_DIR="VOCOTYPE_PROJECT_DIR"

# 使用项目虚拟环境Python
PYTHON="$PROJECT_DIR/.venv/bin/python"

export PYTHONPATH="$VOCOTYPE_HOME:$PYTHONPATH"
export PYTHONIOENCODING=UTF-8

exec $PYTHON "$VOCOTYPE_HOME/ibus/main.py" "$@"
LAUNCHER

# 替换项目目录路径
sed -i "s|VOCOTYPE_PROJECT_DIR|$PROJECT_DIR|g" "$LIBEXEC_DIR/ibus-engine-vocotype"
chmod +x "$LIBEXEC_DIR/ibus-engine-vocotype"

# 4. 安装IBus组件文件
echo "[4/5] 安装IBus组件配置..."
EXEC_PATH="$LIBEXEC_DIR/ibus-engine-vocotype"
VOCOTYPE_VERSION="1.0.0"
if VOCOTYPE_VERSION=$(PYTHONPATH="$PROJECT_DIR" "$PROJECT_DIR/.venv/bin/python" - << 'PY'
from vocotype_version import __version__
print(__version__)
PY
); then
    :
else
    VOCOTYPE_VERSION="1.0.0"
fi

sed -e "s|VOCOTYPE_EXEC_PATH|$EXEC_PATH|g" \
    -e "s|VOCOTYPE_VERSION|$VOCOTYPE_VERSION|g" \
    "$PROJECT_DIR/data/ibus/vocotype.xml.in" > "$COMPONENT_DIR/vocotype.xml"

echo ""
echo "=== 安装完成 ==="
echo ""
echo "请执行以下步骤完成配置："
echo ""
echo "1. 重启IBus:"
echo "   ibus restart"
echo ""
echo "2. 添加输入法:"
echo "   设置 → 键盘 → 输入源 → +"
echo "   → 滑到最底下点三个点(⋮)"
echo "   → 搜索 'voco' → 中文 → VoCoType Voice Input"
echo ""
echo "3. 使用方法:"
echo "   - 切换到VoCoType输入法"
echo "   - 按住F9说话，松开后自动识别并输入"
echo ""
