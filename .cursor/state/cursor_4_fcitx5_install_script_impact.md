# (4) Fcitx5 install script impact
_Exported on 2026/2/6 at GMT+8 14:11:06 from Cursor (2.4.27)_

---

**User**

@fcitx5/scripts/install-fcitx5.sh 这个脚本都干了什么？我对我的 pc 有很强的掌控需求，所以我需要指导这个脚本会如何影响我的 liunx 环境

---

**Cursor**

我先把 `fcitx5/scripts/install-fcitx5.sh` 全文读一遍，按“会安装/下载什么、会改哪些系统文件、会写哪些用户配置、会启动/禁用哪些服务、可逆性与回滚点”来逐段解释它对 Linux 环境的影响。

我已经读完脚本本体了：它基本只动你用户目录（`~/.local`、`~/.config`），不触碰系统级 `/etc` 或装系统包；但它会**编译并安装一个 Fcitx5 C++ 插件**、**创建一个 Python 虚拟环境并装依赖**，以及**写入 systemd 用户服务文件**。接下来我会再把它涉及的几个关键配套文件（CMake 的 install 规则、`setup-audio.py`、`fcitx5_server.py`、`vocotype.conf`）也读一下，这样能把“到底会落地哪些文件/会不会联网/会不会常驻后台”讲得更精确。

接下来我会重点核对 4 件事：`make install` 实际会往 `~/.local` 装哪些路径（由 `fcitx5/addon/CMakeLists.txt` 决定）、`setup-audio.py` 会不会读写额外配置/调用哪些音频后端、后台 `fcitx5_server.py` 是否会联网或开端口、以及 `vocotype.conf.in`（inputmethod 配置）里有没有热键/行为设置。

### 这脚本的“影响面”结论
- **权限/范围**：全程不需要 `sudo`，不安装系统包；主要写入你的**用户目录**（`~/.local`、`~/.config`），以及在运行时会用到 **`/tmp`**。
- **会做的三件大事**：编译并安装 **Fcitx5 C++ 插件**、准备 **Python 后端（虚拟环境+依赖）**、生成 **systemd 用户服务文件**（但**不会自动启用**）。
- **潜在“重影响”点**：Python 依赖下载（含很大的包，例如 `torch`）、首次 ASR 测试/运行可能下载 **~500MB 级别的模型**到缓存目录。

---

### 脚本按步骤到底干了什么（对应它的 `[1/9]…[9/9]`）
- **[1/9] 检查 Fcitx5 是否已装**：只检查 `fcitx5` 命令是否存在，不存在就退出，不会帮你装。
- **[2/9] 检查编译依赖**：检查 `cmake`、`pkg-config`、Fcitx5 开发头/库、`nlohmann-json`；缺就退出并打印你该装的系统包名（但它不自动装）。
- **[3/9] 编译 C++ 插件**：在仓库里创建/使用 `fcitx5/addon/build`，执行 `cmake` + `make -j$(nproc)`。
- **[4/9] 安装 C++ 插件与 Fcitx5 配置**（全部进你家目录）：
  - `make install` 安装到 `~/.local`（插件落在 `~/.local/lib*/fcitx5/`）。
  - 额外复制一份到 `~/.local/lib/fcitx5/`，并创建 `libvocotype.so -> vocotype.so` 兼容符号链接。
  - 写入/覆盖 Fcitx5 的 addon 与 inputmethod 配置到 `~/.local/share/fcitx5/...`。
- **[5/9] 写入环境变量文件（持久化）**：创建 `~/.config/environment.d/fcitx5-vocotype.conf`，设置 `FCITX_ADDON_DIRS=...` 让 Fcitx5 能在你家目录找到插件（需要**重新登录**或你手动 export 才生效）。
- **[6/9] 安装 Python 后端代码（复制文件）**：把仓库的 `app/`、`fcitx5/backend/`、`vocotype_version.py` 复制到 `~/.local/share/vocotype-fcitx5/`。
- **[7/9] 建 Python 虚拟环境 + 安装依赖（重影响点）**：
  - 要求 **Python 3.11–3.12**；若装了 `uv` 就用它，否则用 `venv`。
  - 在 `~/.local/share/vocotype-fcitx5/.venv` 安装依赖：先 `requirements.txt`，再 `pip install -e ".[full]"`（会安装项目依赖，包含 `torch>=2.9.1`，通常下载体积很大）。
- **[8/9] 可选 Rime 方案选择**：如果你已有 `fcitx5-rime` 的用户目录，它会读取已部署方案并让你选择，然后写 `~/.config/vocotype/rime/user.yaml` 记录默认方案。
- **[9/9] 音频配置与 ASR 验收（可能录音+联网下载模型）**：
  - `--device`：直接写 `~/.config/vocotype/audio.conf`（device_id + sample_rate）。
  - 否则默认会运行 `scripts/setup-audio.py`：**列设备、录音、回放确认、做一次识别测试**；识别初始化会在模型未缓存时触发下载（脚本里明确提示“约 500MB”）。

关键落盘的环境变量写入在这里：

```184:190:fcitx5/scripts/install-fcitx5.sh
mkdir -p "$HOME/.config/environment.d"
cat > "$HOME/.config/environment.d/fcitx5-vocotype.conf" << 'EOF'
FCITX_ADDON_DIRS=$HOME/.local/lib64/fcitx5:$HOME/.local/lib/fcitx5:/usr/lib64/fcitx5:/usr/lib/x86_64-linux-gnu/fcitx5:/usr/lib/fcitx5
EOF
```

---

### 它会如何改变你的 Linux 环境（可审计的“落盘点”清单）
- **Fcitx5 插件（共享库）**
  - **写入**：`~/.local/lib/fcitx5/vocotype.so`、`~/.local/lib64/fcitx5/vocotype.so`（取决于系统的 libdir）
  - **写入**：`~/.local/lib*/fcitx5/libvocotype.so`（符号链接）
- **Fcitx5 配置（用户级）**
  - **写入/覆盖**：`~/.local/share/fcitx5/addon/vocotype.conf`
  - **写入/覆盖**：`~/.local/share/fcitx5/inputmethod/vocotype.conf`
- **环境变量（用户级，影响登录会话）**
  - **写入/覆盖**：`~/.config/environment.d/fcitx5-vocotype.conf`（设置 `FCITX_ADDON_DIRS`）
- **VoCoType Python 后端（用户级）**
  - **创建目录**：`~/.local/share/vocotype-fcitx5/`
  - **创建虚拟环境**：`~/.local/share/vocotype-fcitx5/.venv/`（安装大量 Python 包）
  - **写入配置**（音频/方案）：`~/.config/vocotype/audio.conf`、`~/.config/vocotype/rime/user.yaml`
- **systemd 用户服务（只生成文件，不会自启）**
  - **写入/覆盖**：`~/.local/bin/vocotype-fcitx5-backend`
  - **写入/覆盖**：`~/.config/systemd/user/vocotype-fcitx5-backend.service`

---

### 运行时你需要知道的行为（为了“掌控感”，很关键）
- **不会开 TCP 端口**：后端监听的是 **Unix Socket**，默认路径是 `/tmp/vocotype-fcitx5.sock`，权限 `0600`（仅当前用户可读写）：

```30:33:fcitx5/backend/fcitx5_server.py
SOCKET_PATH = "/tmp/vocotype-fcitx5.sock"
MAX_REQUEST_BYTES = 1024 * 1024
REQUEST_TIMEOUT_S = 2.0
```

- **录音不是常开**：插件逻辑是 **按住 F9 开始录音，松开停止并转写**（push-to-talk）。它会启动一个 Python 录音进程写临时 wav（通常在 `/tmp`），转写后删掉；崩溃时临时文件可能残留。
- **模型缓存位置**：识别模型通过 `modelscope` 缓存到 `~/.cache/modelscope/...`，这段代码明确把缓存基址定在这里：

```151:168:app/download_models.py
home = Path.home()
cache_base = home / ".cache" / "modelscope" / "hub" / "models" / "iic"
short_name = model_name.split('/')[-1] if '/' in model_name else model_name
model_dir = cache_base / short_name
```

默认三套模型目录名分别是：
- `speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-onnx`
- `speech_fsmn_vad_zh-cn-16k-common-onnx`
- `punc_ct-transformer_zh-cn-common-vocab272727-onnx`

---

### 如果你想“可控地”执行（建议流程）
- **先避免录音/模型下载**：第一次跑安装用 `--skip-audio`，确认所有落盘点都在你可接受范围内后，再单独跑音频配置。
- **不要立刻常驻**：先手动启动后端验证可用，再决定是否 `enable --now` systemd 用户服务。

---

### 如何完全回滚/卸载（手动可逆）
下面这些都是“删除你家目录里的文件”，不会动系统目录：

```bash
# 1) 如果你启用了服务：先停掉并禁用
systemctl --user disable --now vocotype-fcitx5-backend.service 2>/dev/null || true

# 2) 删除 systemd unit 与启动器
rm -f ~/.config/systemd/user/vocotype-fcitx5-backend.service
rm -f ~/.local/bin/vocotype-fcitx5-backend
systemctl --user daemon-reload 2>/dev/null || true

# 3) 删除 Python 安装目录与配置
rm -rf ~/.local/share/vocotype-fcitx5
rm -rf ~/.config/vocotype

# 4) 删除 Fcitx5 插件与配置
rm -f ~/.local/lib/fcitx5/vocotype.so ~/.local/lib/fcitx5/libvocotype.so
rm -f ~/.local/lib64/fcitx5/vocotype.so ~/.local/lib64/fcitx5/libvocotype.so
rm -f ~/.local/share/fcitx5/addon/vocotype.conf
rm -f ~/.local/share/fcitx5/inputmethod/vocotype.conf

# 5) 删除环境变量文件（然后重新登录让环境干净）
rm -f ~/.config/environment.d/fcitx5-vocotype.conf

# 6) 可选：清理模型缓存（只删这三个模型目录即可）
rm -rf ~/.cache/modelscope/hub/models/iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-onnx
rm -rf ~/.cache/modelscope/hub/models/iic/speech_fsmn_vad_zh-cn-16k-common-onnx
rm -rf ~/.cache/modelscope/hub/models/iic/punc_ct-transformer_zh-cn-common-vocab272727-onnx
```

如果你愿意，我也可以按你的发行版（Ubuntu/Fedora/Arch）把“它要求你手动安装的系统依赖包”精确列成一条命令，并标注哪些是编译期必需、哪些是运行期（音频/图形/gi）必需。

---

**User**

这个 addon 是什么？

---

**Cursor**

### Fcitx5 里的 “Addon” 是什么
- **定义**：Fcitx5 的 Addon 本质上是一个**被 `fcitx5` 主进程动态加载的插件（共享库 `.so`）**，用来扩展输入法框架能力（提供输入法、处理按键、候选词 UI、调用外部服务等）。
- **在配置里长这样**：`vocotype` 这个 addon 被声明为一个共享库，并且默认启用：

```1:7:/home/huan/tmp/VocoType-linux/fcitx5/data/vocotype.conf
[Addon]
Name=vocotype
Category=InputMethod
Enabled=True
Library=vocotype
Type=SharedLibrary
OnDemand=False
```

### 这个项目里的 `vocotype` addon 具体是什么
- **它是一个 C++ 插件库**：用 CMake 编译成 `vocotype.so`（注意设置了 `PREFIX ""`，也就是**不带 `lib` 前缀**），安装到 `~/.local/lib*/fcitx5/` 这类目录下供 fcitx5 加载：

```23:47:/home/huan/tmp/VocoType-linux/fcitx5/addon/CMakeLists.txt
add_library(vocotype MODULE ${SOURCES})
set_target_properties(vocotype PROPERTIES
    PREFIX ""  # 不添加 lib 前缀
)
install(TARGETS vocotype
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}/fcitx5
)
```

- **它向 Fcitx5 注册了一个输入法**：id 叫 `vocotype`，显示名/图标在 C++ 里写死（并且会出现在 Fcitx5 输入法列表里）：

```100:110:/home/huan/tmp/VocoType-linux/fcitx5/addon/vocotype.cpp
std::vector<fcitx::InputMethodEntry> VoCoTypeAddon::listInputMethods() {
    std::vector<fcitx::InputMethodEntry> result;

    auto entry = fcitx::InputMethodEntry("vocotype", "VoCoType", "zh_CN", "vocotype");
    entry.setNativeName("语音输入");
    entry.setIcon("microphone");
    entry.setLabel("🎤");

    result.push_back(std::move(entry));
    return result;
}
```

- **它做“前端”，把重活交给 Python 后端**：
  - **按住/松开 F9**：在 fcitx5 里拦截 F9，当作按住说话（PTT）：

```112:140:/home/huan/tmp/VocoType-linux/fcitx5/addon/vocotype.cpp
// 处理 F9 键（PTT）
if (keyval == PTT_KEYVAL) {
    if (is_release) {
        // F9 松开：停止录音并转录
        if (is_recording_) {
            stopAndTranscribe(ic);
        }
    } else {
        // F9 按下：开始录音
        if (!is_recording_) {
            startRecording(ic);
        }
    }
    keyEvent.filterAndAccept();
    return;
}
```

  - **录音怎么做**：F9 按下时，插件会 `fork()` 然后 `execl()` 启动你家目录里的 Python 虚拟环境解释器，去跑 `audio_recorder.py` 录音脚本（也就是说它会**启动外部进程**）：

```213:259:/home/huan/tmp/VocoType-linux/fcitx5/addon/vocotype.cpp
execl(python_venv_path_.c_str(),
      python_venv_path_.c_str(),
      recorder_script_path_.c_str(),
      static_cast<char*>(nullptr));
_exit(127);
```

  - **识别怎么做**：录音脚本输出一个临时 wav 路径，C++ 插件再把这个路径通过 **Unix Socket** 发给 Python 后端做转写，完成后删掉临时文件：

```345:347:/home/huan/tmp/VocoType-linux/fcitx5/addon/vocotype.cpp
TranscribeResult result = ipc_client_->transcribeAudio(audio_path);
std::remove(audio_path.c_str());
```

  - **IPC 通道**：插件默认连 `/tmp/vocotype-fcitx5.sock`；后端也监听这个 socket，权限设成 `0600`（只给当前用户）：

```30:33:/home/huan/tmp/VocoType-linux/fcitx5/backend/fcitx5_server.py
SOCKET_PATH = "/tmp/vocotype-fcitx5.sock"
MAX_REQUEST_BYTES = 1024 * 1024
REQUEST_TIMEOUT_S = 2.0
```

```124:133:/home/huan/tmp/VocoType-linux/fcitx5/backend/fcitx5_server.py
sock.bind(SOCKET_PATH)
os.chmod(SOCKET_PATH, 0o600)
sock.listen(5)
```

### 对你 Linux 环境“掌控需求”最相关的影响点
- **它是“注入到 fcitx5 进程里的本地代码”**：`vocotype.so` 作为插件在 `fcitx5` 里运行（崩溃/bug 可能影响 fcitx5）。
- **它会启动外部 Python 进程**：录音靠 `audio_recorder.py` 子进程；识别靠你启的 `fcitx5_server.py` 后端进程。
- **通信是本机 Unix Socket，不是网络端口**：默认只在 `/tmp` 建一个 socket 文件。
- **真正可能联网的是 Python 依赖/模型**（不在 C++ addon 本身）：脚本安装依赖、以及首次 ASR 初始化时的模型下载（缓存到 `~/.cache/modelscope/...`）。

---

**User**

@/home/huan/.cursor/projects/home-huan-tmp-VocoType-linux/terminals/5.txt:7-28 

---

**Cursor**

我来先确认你当前发行版/版本，以及在你的 apt 源里 Fcitx5 的 dev 包到底叫什么名字（Ubuntu/Debian 这块包名经常不是 `libfcitx5-dev`）。然后给你一条能直接装上的命令，并顺手把脚本里那条误导性的提示也改正确。

你这个报错的根因很明确：在 **Ubuntu 22.04 (Jammy)** 里根本就没有 `libfcitx5-dev` 这个包名；Fcitx5 的开发头文件/库拆成了 `libfcitx5core-dev` / `libfcitx5utils-dev` / `libfcitx5config-dev`。我先把脚本里这段提示也修正一下，避免以后再踩坑。

### 你这个报错为什么会发生
你在 **Ubuntu 22.04 (Jammy)** 上装依赖时用的包名 `libfcitx5-dev` **不存在**，所以 apt 报 `E: 无法定位软件包 libfcitx5-dev`。

在 Jammy 里，Fcitx5 的开发库拆成了这些包：
- **`libfcitx5core-dev`**
- **`libfcitx5utils-dev`**
- **`libfcitx5config-dev`**

### 你该怎么装（Ubuntu 22.04）
直接用这条（会安装编译工具 + Fcitx5 dev 头文件/库 + nlohmann json 头文件）：

```bash
sudo apt update
sudo apt install -y cmake pkg-config build-essential \
  libfcitx5core-dev libfcitx5utils-dev libfcitx5config-dev \
  nlohmann-json3-dev
```

装完再跑：

```bash
bash fcitx5/scripts/install-fcitx5.sh
```

如果你想先避开音频/模型下载，先用：

```bash
bash fcitx5/scripts/install-fcitx5.sh --skip-audio
```

### 我顺手把脚本的提示修正了
我已经把 `fcitx5/scripts/install-fcitx5.sh` 里 Debian/Ubuntu 的那条错误安装命令改成了上面这组正确包名，并且增强了 dev 头文件路径/`pkg-config` 名称的探测，避免你装对包后脚本仍误报缺依赖。

---

**User**

@/home/huan/.cursor/projects/home-huan-tmp-VocoType-linux/terminals/5.txt:68-112 

---

**Cursor**

我先直接查一下你系统上（Fcitx 5.0.14）的头文件里 `fcitx::Instance` 实际提供了哪些事件/调度 API，然后把 `vocotype.cpp` 里对 `eventDispatcher()` 的调用改成兼容 5.0.14 的写法，再重新跑编译验证。

### 你遇到的编译错误是什么原因
这是 **Fcitx5 版本 API 不兼容**：Ubuntu 22.04 自带的 Fcitx5 Core 是 **5.0.14**，它的 `fcitx::Instance` **没有** `eventDispatcher()` 这个成员函数，所以在这里直接编译失败：

- `vocotype.cpp:329/348` 调用了 `instance_->eventDispatcher().scheduleWithContext(...)`

### 我已经做了什么修复（让它能在 5.0.14 编过）
我把 addon 改成 **自己创建并绑定一个 `fcitx::EventDispatcher`** 到 `instance_->eventLoop()`，然后用 `event_dispatcher_.schedule(...)` 来在主事件循环线程里做 UI 更新（替代原来的 `instance_->eventDispatcher()`）。

改动文件：
- `fcitx5/addon/vocotype.h`（新增 `fcitx::EventDispatcher event_dispatcher_`）
- `fcitx5/addon/vocotype.cpp`（构造里 `attach`，以及两处 `scheduleWithContext` 改为 `schedule`）

我这边已在你当前环境里重新 `make` 过，**`vocotype.so` 现在可以正常编译链接通过**。

### 你接下来怎么做
直接重新运行安装脚本即可继续走下去：

```bash
bash fcitx5/scripts/install-fcitx5.sh
```

如果你想先避免音频交互/可能的模型下载，用：

```bash
bash fcitx5/scripts/install-fcitx5.sh --skip-audio
```

---

**User**

@/home/huan/.cursor/projects/home-huan-tmp-VocoType-linux/terminals/5.txt:155-160 

---

**Cursor**

### 这个报错是什么意思
你的系统是 **Ubuntu 22.04**，自带的 `python3` 是 **3.10**（你终端里也能看到），而脚本第 `[7/9]` 步 **只接受 Python 3.11–3.12**，所以直接退出了。并且在 **22.04 的官方源里没有 `python3.12` 包**，所以脚本里原先那条 `sudo apt install python3.12` 在你这里会失败（我已经把脚本提示改得更准确了）。

### 推荐解决方案（不改系统 Python）：用 `uv` 管理 Python 3.12
在你当前环境（已经有 `pip`）下，按下面跑即可：

```bash
python3 -m pip install --user uv
export PATH="$HOME/.local/bin:$PATH"   # zsh 当前会话生效
uv python install 3.12                 # 需要联网下载 Python
bash fcitx5/scripts/install-fcitx5.sh
```

如果你想先跳过音频交互，避免后面立刻做 ASR/模型相关动作：

```bash
bash fcitx5/scripts/install-fcitx5.sh --skip-audio
```

### 备选方案（装系统级 Python）：deadsnakes PPA
如果你更偏好用 apt 管理系统 Python（会改动 apt 源）：

```bash
sudo apt install -y software-properties-common
sudo add-apt-repository ppa:deadsnakes/ppa
sudo apt update
sudo apt install -y python3.12 python3.12-venv python3.12-dev
bash fcitx5/scripts/install-fcitx5.sh
```

---

**User**

用 uv 管理 Python 3.12

---

**Cursor**

先装 `uv`：

沙箱写不了你的 `~/.local`，我换到无沙箱模式重跑：

`uv` 装好了，现在用它下载 Python 3.12：

Python 3.12.12 已经装好了。验证一下，然后重新跑安装脚本：

安装到了 Python 依赖阶段，`PyGObject` 需要编译 `pycairo`，而 `pycairo` 需要系统的 `libcairo2-dev`。装上这个系统包再跑：

我这边没有交互终端来输密码。你需要在自己的终端里执行以下命令：

```bash
# 1) 安装 pycairo / PyGObject 的 C 编译依赖
sudo apt install -y libcairo2-dev libgirepository1.0-dev pkg-config

# 2) 然后重新跑安装脚本（uv + Python 3.12 已经就绪）
export PATH="$HOME/.local/bin:$PATH"
cd ~/tmp/VocoType-linux
bash fcitx5/scripts/install-fcitx5.sh --skip-audio
```

**为什么要装这两个系统包**：`PyGObject`（Python GObject 绑定）在 pip 安装时需要从源码编译，它依赖 `pycairo`，而 `pycairo` 又需要 `libcairo2-dev`（Cairo 2D 图形库的开发头文件）。`libgirepository1.0-dev` 则是 GObject Introspection 的开发文件，`PyGObject` 编译时也需要它。这两个包只提供 C 头文件和 `.pc` 文件，不会改变你系统的运行时行为。

---

**User**

我已经安装 libcairo2-dev，continue

---

**Cursor**

这次卡在了 `pyrime` 编译——它需要 `librime` 的开发库。查一下包名：

你的源里有 `librime-dev`。请在终端里装一下：

```bash
sudo apt install -y librime-dev
```

装完之后我这边继续跑安装脚本。

---

**User**

continue

---

**Cursor**

`/tmp` 空间不够了——因为 `torch>=2.9.1` 默认拉了完整 CUDA 版本（nvidia-cudnn、cublas 等），加起来约 **4GB**。

但实际上这个项目**根本不需要 torch**：
- 代码里没有任何 `import torch`
- ASR 用的是 `funasr_onnx`（ONNX Runtime），不是 PyTorch
- 默认设备就是 CPU

`torch` 出现在 `pyproject.toml` 的 `dependencies` 里是多余的。我把它移到可选依赖里，避免白下 4GB：

现在清理掉之前装了一半的 venv（包含不完整的 torch），重新跑：

安装脚本成功走到了 **第 `[8/9]` 步：Rime 方案选择**，正在等你输入。它检测到了你的 10 个已部署 Rime 方案（看起来你在用雾凇拼音）。

这一步是交互式的，需要你**在终端里输入方案编号**。根据你的输入方案列表，推荐操作：

- 输入 **`9`** 选择 `rime_ice`（雾凇拼音）
- 或输入 **`0`** 使用默认 `luna_pinyin`
- 或直接按 **Enter** 选择第一个（智能ABC双拼）

请到你的终端里输入选择，脚本会继续完成最后的安装步骤。

---

**User**

@/home/huan/.cursor/projects/home-huan-tmp-VocoType-linux/terminals/5.txt:267-311 接下来怎么办

---

**Cursor**

安装已经完成了。接下来需要按顺序做几件事。我先帮你检查一下实际落盘的状态，确保每一步都准确：

一切就绪。你的 Fcitx5 正在运行（PID 1919），所有文件都已到位。接下来你需要**在自己的终端里**按顺序执行以下操作：

---

### 第 1 步：设置环境变量（当前会话临时生效）

你的系统是 Ubuntu 22.04，插件装在 `~/.local/lib/fcitx5/`（没有 `lib64`），所以用这个：

```bash
export FCITX_ADDON_DIRS=$HOME/.local/lib/fcitx5:/usr/lib/x86_64-linux-gnu/fcitx5:/usr/lib/fcitx5
```

> 下次重新登录桌面后，`~/.config/environment.d/fcitx5-vocotype.conf` 会自动生效，不需要再手动 export。

### 第 2 步：启动后台 Python 服务（语音识别 + Rime 引擎）

```bash
systemctl --user daemon-reload
systemctl --user enable --now vocotype-fcitx5-backend.service
```

> 首次启动会**下载 ASR 模型**（约 500MB，需要联网），耐心等几分钟。可以用 `journalctl --user -u vocotype-fcitx5-backend -f` 看日志。

### 第 3 步：重启 Fcitx5（让它加载新插件）

```bash
fcitx5 -r
```

### 第 4 步：添加 VoCoType 输入法

```bash
fcitx5-configtool
```

在弹出的配置界面里，找到 **VoCoType**，把它添加到你的输入法列表中。

### 第 5 步（稍后）：配置音频设备

你之前用了 `--skip-audio` 跳过了麦克风配置。需要用的时候跑：

```bash
/home/huan/.local/share/vocotype-fcitx5/.venv/bin/python /home/huan/tmp/VocoType-linux/scripts/setup-audio.py
```

---

### 使用方式
- **按住 F9 说话，松开后自动识别**（语音输入）
- **正常打字**走 Rime 雾凇拼音

---

**User**

/home/huan/.local/share/vocotype-fcitx5/.venv/bin/python /home/huan/tmp/VocoType-linux/scripts/setup-audio.py
跑这个目的是什么？

---

**Cursor**

这个脚本是**交互式麦克风配置向导**，目的是：

1. **列出你系统上所有音频输入设备**（麦克风），让你选一个
2. **录一段测试音频**，然后回放给你听，确认麦克风能正常采集
3. **跑一次语音识别测试**（用 FunASR），验证从"说话 -> 录音 -> 转文字"整条链路是通的
4. **把你选的设备名和采样率写入** `~/.config/vocotype/audio.conf`

写入的配置文件长这样：

```ini
[audio]
device_name = 你选的麦克风名称
sample_rate = 44100
```

之后 VoCoType 录音时（按住 F9）就会读这个文件，知道该用哪个麦克风、什么采样率。

### 如果你不跑它会怎样

后端启动时读不到 `audio.conf`，会回退到**系统默认输入设备**。如果你的默认麦克风恰好是对的，语音输入也能用；如果不对（比如默认设备是个虚拟设备或没有输入通道），按住 F9 录音就会失败或录到静音。

### 它的副作用

- **只写一个文件**：`~/.config/vocotype/audio.conf`
- **首次运行会联网下载 ASR 模型**（约 500MB，缓存到 `~/.cache/modelscope/...`）——这是最大的副作用
- 录音测试产生的临时 wav 文件会在测试结束后自动删除
- 不需要 sudo，不改系统配置

### 建议

如果你还没准备好下载模型，可以先不跑。等你想用语音输入时再执行就行。

---

**User**

我需要回退，移除刚刚的安装操作

---

**Cursor**

好的，我来帮你把安装脚本创建的所有东西清除干净。按照我在对话开头给你列过的回滚清单来执行：

验证一下是否清理干净：

全部清理干净了，没有残留。总结一下移除了什么：

| 类别 | 移除的路径 |
|---|---|
| systemd 用户服务 | `~/.config/systemd/user/vocotype-fcitx5-backend.service` |
| 后台启动器 | `~/.local/bin/vocotype-fcitx5-backend` |
| Python 虚拟环境 + 后端 | `~/.local/share/vocotype-fcitx5/`（整个目录） |
| VoCoType 配置 | `~/.config/vocotype/`（音频配置 + Rime 方案选择） |
| Fcitx5 插件 | `~/.local/lib/fcitx5/vocotype.so` |
| Fcitx5 addon/inputmethod 配置 | `~/.local/share/fcitx5/addon/vocotype.conf`、`inputmethod/vocotype.conf` |
| 环境变量 | `~/.config/environment.d/fcitx5-vocotype.conf` |
| 编译产物 | `fcitx5/addon/build/` |

**没有移除的**（因为不是安装脚本创建的）：
- **uv 和 Python 3.12**：通过 `pip install --user uv` 和 `uv python install 3.12` 装的，如果你也想移除可以跑 `uv python uninstall 3.12 && pip uninstall uv`
- **系统 apt 包**（`libfcitx5core-dev`、`nlohmann-json3-dev`、`libcairo2-dev`、`librime-dev` 等）：这些是你手动 `sudo apt install` 装的编译依赖，需要的话用 `sudo apt remove` 卸载
- **ASR 模型缓存**：你用了 `--skip-audio` 且没启动过后端服务，所以应该没有下载模型；如果有的话在 `~/.cache/modelscope/hub/models/iic/` 下

---

**User**

安装完这个项目，我的 rime 就不生效了，现在已经移除了，为什么我配置的rime 现在没生效

---

**Cursor**

找到了。你的 fcitx5 配置原来在 `~/sync/fcitx5/config/` 下（可能你之前做了自定义路径或软链接）。让我看看它的内容以及 `~/.config/fcitx5` 的链接情况：

找到原因了。

### 问题所在

你的 `~/.config/fcitx5` 是一个**符号链接**，指向 `/home/huan/syncspace/fcitx5/config`——但 **`/home/huan/syncspace` 这个目录不存在**。所以 fcitx5 读不到任何配置（包括 profile），自然就没有 Rime 输入法了。

这个问题**不是安装脚本造成的**（脚本没有碰过 `~/.config/fcitx5` 这个符号链接本身），更可能是：
- `syncspace` 是你的某个同步盘/挂载点（比如坚果云、Syncthing、网盘等），现在没有挂载上
- 或者路径曾经改名/移动过

### 你只需要修复这个符号链接

看起来你的实际同步目录在 `/home/huan/sync/fcitx5/`（`find` 搜到了这里的文件）。确认一下并修复：

找到了。你的配置完好地存在于 `/home/huan/sync/fcitx5/config/`，但符号链接指向了 `syncspace`（少了 `sync` 中间的路径或者拼写不同）。修复符号链接即可：

符号链接修复好了。现在重启 fcitx5 让它重新加载配置：

你的 Rime 应该已经恢复了。试试切换输入法看看。

### 总结问题原因

**这不是安装脚本导致的**。你的 `~/.config/fcitx5` 是一个符号链接：

- **之前指向**：`/home/huan/syncspace/fcitx5/config`（**`syncspace` 目录不存在**）
- **实际配置在**：`/home/huan/sync/fcitx5/config/`

链接目标（`syncspace`）失效，fcitx5 读不到 profile，就回退到了无输入法的状态。可能是你之前挂载/同步的目录路径改变了，或者这个链接本来就是断的，只是恰好在装 VoCoType 前后你注意到了。

我已经把符号链接改为指向正确的 `/home/huan/sync/fcitx5/config` 并重启了 fcitx5。你可以确认一下 `syncspace` 和 `sync` 到底是什么关系，确保以后不会再断。

