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

# 询问是否集成 Rime
echo "请选择安装版本："
echo "  [1] 纯语音版（推荐新手）- 仅语音输入，依赖少"
echo "  [2] 完整版 - 语音 + Rime 拼音输入，一个输入法全搞定"
echo ""
read -r -p "请输入选项 (默认 1): " INSTALL_TYPE

ENABLE_RIME=0
case "$INSTALL_TYPE" in
    2)
        ENABLE_RIME=1
        echo ""
        echo "您选择了完整版（语音 + Rime 拼音）"
        echo ""
        echo "完整版需要额外依赖："
        echo "  - librime-devel (Rime 开发库)"
        echo "  - pyrime (Python 绑定，自动安装)"
        echo ""

        # 检测系统类型并提供安装命令
        if [ -f /etc/fedora-release ] || [ -f /etc/redhat-release ]; then
            DISTRO="Fedora/RHEL"
            INSTALL_CMD="sudo dnf install -y librime-devel ibus-rime"
            CHECK_CMD="rpm -q librime-devel"
        elif [ -f /etc/debian_version ]; then
            DISTRO="Debian/Ubuntu"
            INSTALL_CMD="sudo apt install -y librime-dev ibus-rime"
            CHECK_CMD="dpkg -l librime-dev"
        elif [ -f /etc/arch-release ]; then
            DISTRO="Arch Linux"
            INSTALL_CMD="sudo pacman -S --noconfirm librime ibus-rime"
            CHECK_CMD="pacman -Q librime"
        else
            DISTRO="未知"
            INSTALL_CMD=""
            CHECK_CMD=""
        fi

        echo "检测到系统: $DISTRO"
        echo ""

        # 检查 librime 是否已安装
        if [ -n "$CHECK_CMD" ] && eval "$CHECK_CMD" >/dev/null 2>&1; then
            echo "✓ librime 开发库已安装"
        else
            echo "⚠️  未检测到 librime 开发库"
            echo ""

            if [ -n "$INSTALL_CMD" ]; then
                echo "需要安装系统依赖，建议执行："
                echo "  $INSTALL_CMD"
                echo ""
                read -r -p "是否现在自动安装？(y/N): " AUTO_INSTALL

                if [[ "$AUTO_INSTALL" =~ ^[Yy]$ ]]; then
                    echo "正在安装系统依赖..."
                    if eval "$INSTALL_CMD"; then
                        echo "✓ 系统依赖安装成功"
                    else
                        echo "❌ 系统依赖安装失败"
                        echo "   请手动执行: $INSTALL_CMD"
                        echo "   然后重新运行安装脚本"
                        exit 1
                    fi
                else
                    echo ""
                    echo "请先手动安装系统依赖："
                    echo "  $INSTALL_CMD"
                    echo ""
                    read -r -p "已完成安装？按回车继续，或 Ctrl+C 取消..."
                fi
            else
                echo "未知的发行版，请手动安装 librime 开发库"
                echo "参考: https://github.com/rime/librime"
                echo ""
                read -r -p "已完成安装？按回车继续，或 Ctrl+C 取消..."
            fi
        fi

        echo ""
        ;;
    ""|1|*)
        ENABLE_RIME=0
        echo ""
        echo "您选择了纯语音版"
        ;;
esac

echo ""

echo "请选择 Python 环境："
echo "  [1] 使用项目虚拟环境（推荐）: $PROJECT_DIR/.venv"
echo "  [2] 使用用户级虚拟环境: $INSTALL_DIR/.venv"
echo "  [3] 使用系统 Python（省空间，需自行安装依赖）"
read -r -p "请输入选项 (默认 1): " PY_CHOICE

case "$PY_CHOICE" in
    2)
        PYTHON="$INSTALL_DIR/.venv/bin/python"
        ;;
    3)
        PYTHON="$(command -v python3)"
        USE_SYSTEM_PYTHON=1
        ;;
    ""|1|*)
        PYTHON="$PROJECT_DIR/.venv/bin/python"
        ;;
esac

# 1. 创建目录
echo "[0/5] 创建安装目录与 Python 环境..."
mkdir -p "$INSTALL_DIR"
mkdir -p "$COMPONENT_DIR"
mkdir -p "$LIBEXEC_DIR"

if [ "$USE_SYSTEM_PYTHON" != "1" ] && [ ! -x "$PYTHON" ]; then
    VENV_DIR="$(dirname "$PYTHON")/.."
    echo "创建虚拟环境: $VENV_DIR"
    if command -v uv >/dev/null 2>&1; then
        uv venv --python python3 "$VENV_DIR"
    elif command -v python3 >/dev/null 2>&1; then
        python3 -m venv "$VENV_DIR"
    else
        echo "未找到 uv 或 python3，无法创建虚拟环境。"
        echo "请先安装 uv 或 python3，再重新运行安装脚本。"
        exit 1
    fi
fi

if [ ! -x "$PYTHON" ]; then
    echo "未找到 Python 可执行文件: $PYTHON"
    echo "请确认已创建虚拟环境或系统已安装 python3。"
    exit 1
fi

if [ "$USE_SYSTEM_PYTHON" = "1" ]; then
    if ! "$PYTHON" - << 'PY'
import numpy  # noqa: F401
import sounddevice  # noqa: F401
import soundfile  # noqa: F401
PY
    then
        echo "系统 Python 缺少依赖。请先执行："
        echo "  pip install -r $PROJECT_DIR/requirements.txt"
        exit 1
    fi
else
    echo "安装依赖到虚拟环境..."
    if command -v uv >/dev/null 2>&1; then
        uv pip install --python "$PYTHON" -r "$PROJECT_DIR/requirements.txt"
    else
        "$PYTHON" -m pip install -r "$PROJECT_DIR/requirements.txt"
    fi

    # 如果启用 Rime，安装 pyrime
    if [ "$ENABLE_RIME" = "1" ]; then
        echo ""
        echo "安装 pyrime（Rime Python 绑定）..."
        if command -v uv >/dev/null 2>&1; then
            if ! uv pip install --python "$PYTHON" pyrime; then
                echo "⚠️  pyrime 安装失败"
                echo "   这可能是因为 librime-devel 未正确安装"
                echo "   VoCoType 将以纯语音模式运行"
                ENABLE_RIME=0
            fi
        else
            if ! "$PYTHON" -m pip install pyrime; then
                echo "⚠️  pyrime 安装失败"
                echo "   这可能是因为 librime-devel 未正确安装"
                echo "   VoCoType 将以纯语音模式运行"
                ENABLE_RIME=0
            fi
        fi
    fi
fi

# 1. 音频设备配置
echo "[1/5] 音频设备配置..."
echo ""
echo "首先需要配置您的麦克风设备。"
echo "这个过程会："
echo "  - 列出可用的音频输入设备"
echo "  - 测试录音和播放"
echo "  - 验证语音识别效果"
echo ""

if ! "$PYTHON" "$PROJECT_DIR/scripts/setup-audio.py"; then
    echo ""
    echo "音频配置失败或被取消。"
    echo "请稍后运行以下命令重新配置："
    echo "  $PYTHON $PROJECT_DIR/scripts/setup-audio.py"
    exit 1
fi

echo ""

# 2. 复制项目文件
echo "[2/5] 复制项目文件..."
cp -r "$PROJECT_DIR/app" "$INSTALL_DIR/"
cp -r "$PROJECT_DIR/ibus" "$INSTALL_DIR/"
cp "$PROJECT_DIR/vocotype_version.py" "$INSTALL_DIR/"

# 3. 创建启动脚本
echo "[3/5] 创建启动脚本..."
cat > "$LIBEXEC_DIR/ibus-engine-vocotype" << 'LAUNCHER'
#!/bin/bash
# VoCoType IBus Engine Launcher

VOCOTYPE_HOME="$HOME/.local/share/vocotype"
PROJECT_DIR="VOCOTYPE_PROJECT_DIR"

# 使用项目虚拟环境Python
PYTHON="VOCOTYPE_PYTHON"

export PYTHONPATH="$VOCOTYPE_HOME:$PYTHONPATH"
export PYTHONIOENCODING=UTF-8

exec $PYTHON "$VOCOTYPE_HOME/ibus/main.py" "$@"
LAUNCHER

# 替换项目目录路径
sed -i "s|VOCOTYPE_PROJECT_DIR|$PROJECT_DIR|g" "$LIBEXEC_DIR/ibus-engine-vocotype"
sed -i "s|VOCOTYPE_PYTHON|$PYTHON|g" "$LIBEXEC_DIR/ibus-engine-vocotype"
chmod +x "$LIBEXEC_DIR/ibus-engine-vocotype"

# 4. 安装IBus组件文件
echo "[4/5] 安装IBus组件配置..."
EXEC_PATH="$LIBEXEC_DIR/ibus-engine-vocotype"
VOCOTYPE_VERSION="1.0.0"
if VOCOTYPE_VERSION=$(PYTHONPATH="$PROJECT_DIR" "$PYTHON" - << 'PY'
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

if [ "$ENABLE_RIME" = "1" ]; then
    echo "✨ 已安装完整版（语音 + Rime 拼音）"
else
    echo "🎤 已安装纯语音版"
fi

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

if [ "$ENABLE_RIME" = "1" ]; then
    echo "3. 使用方法（完整版）:"
    echo "   - 切换到VoCoType输入法"
    echo "   - 语音输入：按住F9说话，松开后自动识别并输入"
    echo "   - 拼音输入：直接打字，Rime会显示候选词"
    echo ""
    echo "配置说明："
    echo "   - Rime 配置目录: ~/.config/ibus/rime/"
    echo "   - 与 ibus-rime 共享词库和配置"
    echo "   - 如需调整 Rime 设置，请编辑该目录下的 yaml 文件"
else
    echo "3. 使用方法（纯语音版）:"
    echo "   - 切换到VoCoType输入法"
    echo "   - 按住F9说话，松开后自动识别并输入"
    echo ""
    echo "提示："
    echo "   - 如需拼音输入，请安装并切换到其他拼音输入法（如 ibus-rime）"
    echo "   - 如果以后想升级到完整版，请重新运行安装脚本并选择选项 2"
fi

echo ""
