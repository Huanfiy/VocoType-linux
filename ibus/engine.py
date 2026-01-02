#!/usr/bin/env python3
"""VoCoType IBus Engine - PTT语音输入法引擎

按住F9说话，松开后识别并输入到光标处。
其他按键转发给 Rime 处理。
"""

from __future__ import annotations

import logging
import threading
import queue
import tempfile
import os
import time
from pathlib import Path
from typing import Optional, TYPE_CHECKING

import numpy as np

import gi
gi.require_version('IBus', '1.0')
from gi.repository import IBus, GLib

if TYPE_CHECKING:
    from pyrime.session import Session as RimeSession

logger = logging.getLogger(__name__)

# 音频参数
SAMPLE_RATE = 16000
DEFAULT_NATIVE_SAMPLE_RATE = 44100
BLOCK_MS = 20


def _load_audio_config():
    """从配置文件加载音频设备"""
    config_file = Path.home() / ".config" / "vocotype" / "audio.conf"
    if not config_file.exists():
        logger.warning("音频配置文件不存在: %s，使用默认设备", config_file)
        return None, DEFAULT_NATIVE_SAMPLE_RATE

    try:
        import configparser
        config = configparser.ConfigParser()
        config.read(config_file)

        device_id = config.getint('audio', 'device_id', fallback=None)
        sample_rate = config.getint('audio', 'sample_rate', fallback=DEFAULT_NATIVE_SAMPLE_RATE)

        logger.info("从配置加载: 设备=%s, 采样率=%d", device_id, sample_rate)
        return device_id, sample_rate
    except Exception as e:
        logger.warning("读取音频配置失败: %s，使用默认设备", e)
        return None, DEFAULT_NATIVE_SAMPLE_RATE


AUDIO_DEVICE, CONFIGURED_SAMPLE_RATE = _load_audio_config()


def resample_audio(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """重采样音频到目标采样率"""
    if orig_sr == target_sr:
        return audio
    duration = len(audio) / orig_sr
    target_length = int(duration * target_sr)
    indices = np.linspace(0, len(audio) - 1, target_length)
    return np.interp(indices, np.arange(len(audio)), audio.astype(np.float32)).astype(np.int16)


class VoCoTypeEngine(IBus.Engine):
    """VoCoType IBus语音输入引擎"""

    __gtype_name__ = 'VoCoTypeEngine'

    # PTT触发键
    PTT_KEYVAL = IBus.KEY_F9

    def __init__(self, bus: IBus.Bus, object_path: str):
        # 需要显式传入 DBus 连接与 object_path，避免 GLib g_variant object_path 断言失败。
        super().__init__(connection=bus.get_connection(), object_path=object_path)
        self._bus = bus

        # 状态
        self._is_recording = False
        self._audio_frames: list[np.ndarray] = []
        self._audio_queue: queue.Queue = queue.Queue(maxsize=500)
        self._stop_event = threading.Event()
        self._capture_thread: Optional[threading.Thread] = None
        self._stream = None

        # ASR服务器（懒加载）
        self._asr_server = None
        self._asr_initializing = False
        self._asr_ready = threading.Event()
        self._native_sample_rate = CONFIGURED_SAMPLE_RATE

        # Rime 集成（使用 pyrime 直接调用 librime）
        # 如果未安装 pyrime，则禁用 Rime 集成
        self._rime_session: Optional[RimeSession] = None
        self._rime_available = self._check_rime_available()
        self._rime_enabled = self._rime_available  # 只有 pyrime 可用时才启用
        self._rime_init_lock = threading.Lock()

        if self._rime_available:
            logger.info("VoCoTypeEngine 实例已创建（Rime 集成已启用）")
        else:
            logger.info("VoCoTypeEngine 实例已创建（纯语音模式，Rime 集成未启用）")

    def _check_rime_available(self) -> bool:
        """检查 pyrime 是否可用"""
        try:
            import pyrime
            return True
        except ImportError:
            logger.info("pyrime 未安装，Rime 集成功能将被禁用")
            return False

    def _resolve_input_device(self, sd):
        """选择可用的输入设备，优先使用显式配置。"""
        if AUDIO_DEVICE is not None:
            try:
                info = sd.query_devices(AUDIO_DEVICE)
                if info.get("max_input_channels", 0) > 0:
                    return AUDIO_DEVICE
                logger.warning("设备 %s 无输入通道，回退选择输入设备", AUDIO_DEVICE)
            except Exception as exc:
                logger.warning("查询设备 %s 失败: %s", AUDIO_DEVICE, exc)

        try:
            devices = sd.query_devices()
            for idx, info in enumerate(devices):
                if info.get("max_input_channels", 0) > 0:
                    logger.info("回退至输入设备 #%s (%s)", idx, info.get("name", "unknown"))
                    return idx
        except Exception as exc:
            logger.warning("查询输入设备列表失败: %s", exc)

        return None

    def _resolve_sample_rate(self, sd, device, preferred):
        """选择可用采样率，优先使用指定值。"""
        if preferred:
            try:
                sd.check_input_settings(
                    device=device,
                    samplerate=preferred,
                    channels=1,
                    dtype="int16",
                )
                return preferred
            except Exception:
                pass

        try:
            info = sd.query_devices(device if device is not None else None, kind="input")
            default_sr = int(info.get("default_samplerate", 0)) if info else 0
            if default_sr:
                sd.check_input_settings(
                    device=device,
                    samplerate=default_sr,
                    channels=1,
                    dtype="int16",
                )
                return default_sr
        except Exception:
            pass

        return preferred or SAMPLE_RATE

    def _init_rime_session(self):
        """初始化 Rime Session（懒加载）"""
        if self._rime_session is not None:
            return True

        with self._rime_init_lock:
            if self._rime_session is not None:
                return True

            try:
                # 确保日志目录存在
                log_dir = Path.home() / ".local" / "share" / "vocotype" / "rime"
                log_dir.mkdir(parents=True, exist_ok=True)

                from pyrime.api import Traits, API
                from pyrime.session import Session
                from pyrime.ime import Context

                # 使用 ibus-rime 的用户数据目录
                user_data_dir = Path.home() / ".config" / "ibus" / "rime"
                if not user_data_dir.exists():
                    user_data_dir.mkdir(parents=True, exist_ok=True)

                # 查找共享数据目录
                shared_dirs = [
                    Path("/usr/share/rime-data"),
                    Path("/usr/local/share/rime-data"),
                ]
                shared_data_dir = next((d for d in shared_dirs if d.exists()), None)
                if shared_data_dir is None:
                    logger.error("找不到 Rime 共享数据目录")
                    return False

                traits = Traits(
                    shared_data_dir=str(shared_data_dir),
                    user_data_dir=str(user_data_dir),
                    log_dir=str(log_dir),
                    distribution_name="VoCoType",
                    distribution_code_name="vocotype",
                    distribution_version="1.0",
                    app_name="rime.vocotype",
                )

                api = API()
                self._rime_session = Session(traits=traits, api=api)
                logger.info("Rime Session 已创建，schema: %s", self._rime_session.get_current_schema())
                return True

            except Exception as exc:
                logger.error("初始化 Rime Session 失败: %s", exc)
                import traceback
                traceback.print_exc()
                return False

    def do_enable(self):
        """引擎启用"""
        logger.info("Engine enabled")

    def do_disable(self):
        """引擎禁用"""
        logger.info("Engine disabled")
        if self._is_recording:
            self._stop_recording()
        # 清除 Rime 组合
        if self._rime_session:
            try:
                self._rime_session.clear_composition()
            except Exception:
                pass
        self._clear_preedit()
        self.hide_lookup_table()

    def do_focus_in(self):
        """获得输入焦点"""
        logger.info("Engine got focus")

    def do_focus_out(self):
        """失去输入焦点"""
        logger.info("Engine lost focus")
        if self._is_recording:
            self._stop_recording()
        # 清除 Rime 组合
        if self._rime_session:
            try:
                self._rime_session.clear_composition()
            except Exception:
                pass
        self._clear_preedit()
        self.hide_lookup_table()

    def _ensure_asr_ready(self):
        """确保ASR服务器已初始化（懒加载）"""
        if self._asr_server is not None:
            return True

        if self._asr_initializing:
            # 等待初始化完成
            return self._asr_ready.wait(timeout=60)

        self._asr_initializing = True

        def init_asr():
            try:
                logger.info("开始初始化FunASR...")
                from app.funasr_server import FunASRServer
                self._asr_server = FunASRServer()
                result = self._asr_server.initialize()
                if result["success"]:
                    logger.info("FunASR初始化成功")
                    self._asr_ready.set()
                else:
                    logger.error(f"FunASR初始化失败: {result.get('error')}")
                    self._asr_server = None
            except Exception as e:
                logger.error(f"FunASR初始化异常: {e}")
                self._asr_server = None
            finally:
                self._asr_initializing = False

        # 后台初始化
        threading.Thread(target=init_asr, daemon=True).start()
        return False

    def do_process_key_event(self, keyval, keycode, state):
        """处理按键事件"""
        # 调试：记录所有按键
        is_release = bool(state & IBus.ModifierType.RELEASE_MASK)
        logger.info(f"Key event: keyval={keyval}, keycode={keycode}, state={state}, is_release={is_release}, F9={self.PTT_KEYVAL}")

        # 检查是否是松开事件
        is_release = bool(state & IBus.ModifierType.RELEASE_MASK)

        # 只处理F9键
        if keyval != self.PTT_KEYVAL:
            if self._is_ibus_switch_hotkey(keyval, state):
                return False
            return self._forward_key_to_rime(keyval, keycode, state)

        if not is_release:
            # F9按下 -> 开始录音
            if not self._is_recording:
                self._start_recording()
            return True
        else:
            # F9松开 -> 停止录音并转录
            if self._is_recording:
                self._stop_and_transcribe()
            return True

    def _forward_key_to_rime(self, keyval, keycode, state) -> bool:
        """将按键事件转发给 Rime（使用 pyrime）"""
        if not self._rime_enabled:
            return False

        # 懒加载初始化 Rime
        if not self._init_rime_session():
            return False

        try:
            # 将 IBus modifier 转换为 Rime modifier
            # IBus 和 Rime 都使用 X11 keysym 和类似的 modifier mask
            is_release = bool(state & IBus.ModifierType.RELEASE_MASK)

            # Rime 不处理 key release 事件
            if is_release:
                return False

            # 构建 Rime modifier mask
            rime_mask = 0
            if state & IBus.ModifierType.SHIFT_MASK:
                rime_mask |= 1 << 0  # kShiftMask
            if state & IBus.ModifierType.LOCK_MASK:
                rime_mask |= 1 << 1  # kLockMask
            if state & IBus.ModifierType.CONTROL_MASK:
                rime_mask |= 1 << 2  # kControlMask
            if state & IBus.ModifierType.MOD1_MASK:
                rime_mask |= 1 << 3  # kAltMask

            # 处理按键
            handled = self._rime_session.process_key(keyval, rime_mask)

            # 检查是否有提交的文本
            commit = self._rime_session.get_commit()
            if commit and commit.text:
                self._clear_preedit()
                self.hide_lookup_table()
                self.commit_text(IBus.Text.new_from_string(commit.text))
                logger.info("Rime 提交文本: %s", commit.text)

            # 更新预编辑和候选词
            context = self._rime_session.get_context()
            if context:
                self._update_rime_ui(context)
            else:
                self._clear_preedit()
                self.hide_lookup_table()

            return handled

        except Exception as exc:
            logger.error("Rime 处理按键失败: %s", exc)
            import traceback
            traceback.print_exc()
            return False

    def _update_rime_ui(self, context):
        """根据 Rime Context 更新 IBus UI"""
        try:
            # 更新预编辑文本
            preedit_text = context.composition.preedit or ""
            if preedit_text:
                ibus_text = IBus.Text.new_from_string(preedit_text)
                # 添加下划线样式
                ibus_text.append_attribute(
                    IBus.AttrType.UNDERLINE,
                    IBus.AttrUnderline.SINGLE,
                    0,
                    len(preedit_text)
                )
                cursor_pos = context.composition.cursor_pos
                self.update_preedit_text(ibus_text, cursor_pos, True)
            else:
                self._clear_preedit()

            # 更新候选词列表
            menu = context.menu
            if menu.candidates:
                lookup_table = IBus.LookupTable.new(
                    page_size=menu.page_size,
                    cursor_pos=menu.highlighted_candidate_index,
                    cursor_visible=True,
                    round=False
                )

                for i, candidate in enumerate(menu.candidates):
                    text = candidate.text
                    if candidate.comment:
                        text = f"{text} {candidate.comment}"
                    lookup_table.append_candidate(IBus.Text.new_from_string(text))

                self.update_lookup_table(lookup_table, True)
            else:
                self.hide_lookup_table()

        except Exception as exc:
            logger.warning("更新 Rime UI 失败: %s", exc)

    def _is_ibus_switch_hotkey(self, keyval, state) -> bool:
        """让输入法切换热键走 IBus 全局处理"""
        if keyval == IBus.KEY_space and state & IBus.ModifierType.CONTROL_MASK:
            return True
        if keyval == IBus.KEY_space and state & (IBus.ModifierType.SUPER_MASK | IBus.ModifierType.MOD4_MASK):
            return True
        if keyval in (IBus.KEY_Shift_L, IBus.KEY_Shift_R) and state & IBus.ModifierType.MOD1_MASK:
            return True
        if keyval in (IBus.KEY_Shift_L, IBus.KEY_Shift_R) and state & IBus.ModifierType.CONTROL_MASK:
            return True
        return False

    def _start_recording(self):
        """开始录音"""
        if self._is_recording:
            return

        try:
            import sounddevice as sd

            self._is_recording = True
            self._audio_frames.clear()
            self._stop_event.clear()

            # 清空队列
            while not self._audio_queue.empty():
                try:
                    self._audio_queue.get_nowait()
                except queue.Empty:
                    break

            device = self._resolve_input_device(sd)
            sample_rate = self._resolve_sample_rate(sd, device, CONFIGURED_SAMPLE_RATE)
            self._native_sample_rate = sample_rate
            block_size = int(sample_rate * BLOCK_MS / 1000)

            def audio_callback(indata, frame_count, time_info, status):
                if status:
                    logger.warning(f"音频状态: {status}")
                try:
                    self._audio_queue.put_nowait(indata.copy())
                except queue.Full:
                    pass

            # 创建音频流
            self._stream = sd.InputStream(
                samplerate=sample_rate,
                blocksize=block_size,
                device=device,
                channels=1,
                dtype='int16',
                callback=audio_callback,
            )
            self._stream.start()

            # 启动采集线程
            def capture_loop():
                while not self._stop_event.is_set():
                    try:
                        frame = self._audio_queue.get(timeout=0.1)
                        self._audio_frames.append(frame)
                    except queue.Empty:
                        continue

            self._capture_thread = threading.Thread(target=capture_loop, daemon=True)
            self._capture_thread.start()

            # 显示录音状态
            self._update_preedit("🎤 录音中...")
            logger.info("开始录音")

            # 确保ASR已初始化
            self._ensure_asr_ready()

        except Exception as e:
            logger.error(f"启动录音失败: {e}")
            self._is_recording = False
            self._update_preedit(f"❌ 录音失败: {e}")
            GLib.timeout_add(2000, self._clear_preedit)

    def _stop_recording(self):
        """停止录音（不转录）"""
        if not self._is_recording:
            return

        self._stop_event.set()

        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except:
                pass
            self._stream = None

        if self._capture_thread:
            self._capture_thread.join(timeout=1.0)
            self._capture_thread = None

        self._is_recording = False
        self._clear_preedit()
        logger.info("录音已停止")

    def _stop_and_transcribe(self):
        """停止录音并转录"""
        if not self._is_recording:
            return

        # 停止录音
        self._stop_event.set()

        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except:
                pass
            self._stream = None

        if self._capture_thread:
            self._capture_thread.join(timeout=1.0)
            self._capture_thread = None

        self._is_recording = False

        # 检查是否有音频数据
        if not self._audio_frames:
            self._clear_preedit()
            return

        # 合并音频
        audio_data = np.concatenate(self._audio_frames).flatten()
        self._audio_frames.clear()

        duration = len(audio_data) / self._native_sample_rate
        logger.info(f"录音完成，时长: {duration:.2f}秒")

        # 检查是否太短
        if duration < 0.3:
            self._clear_preedit()
            return

        # 显示识别中状态
        self._update_preedit("⏳ 识别中...")

        # 在后台线程中转录
        def do_transcribe():
            try:
                # 重采样
                audio_16k = resample_audio(audio_data, self._native_sample_rate, SAMPLE_RATE)

                # 写入临时文件
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
                    temp_path = f.name
                    from app.wave_writer import write_wav
                    write_wav(Path(temp_path), audio_16k.tobytes(), SAMPLE_RATE)

                try:
                    # 等待ASR就绪
                    if not self._asr_ready.wait(timeout=30):
                        GLib.idle_add(self._show_error, "ASR未就绪")
                        return

                    # 转录
                    result = self._asr_server.transcribe_audio(temp_path)

                    if result.get("success"):
                        text = result.get("text", "").strip()
                        if text:
                            GLib.idle_add(self._commit_text, text)
                        else:
                            GLib.idle_add(self._clear_preedit)
                    else:
                        error = result.get("error", "未知错误")
                        GLib.idle_add(self._show_error, error)
                finally:
                    # 删除临时文件
                    try:
                        os.unlink(temp_path)
                    except:
                        pass

            except Exception as e:
                logger.error(f"转录失败: {e}")
                GLib.idle_add(self._show_error, str(e))

        threading.Thread(target=do_transcribe, daemon=True).start()

    def _update_preedit(self, text: str):
        """更新预编辑文本"""
        preedit = IBus.Text.new_from_string(text)
        self.update_preedit_text(preedit, len(text), True)

    def _clear_preedit(self):
        """清除预编辑文本"""
        self.update_preedit_text(IBus.Text.new_from_string(""), 0, False)
        return False  # 用于GLib.timeout_add

    def _commit_text(self, text: str):
        """提交文本到应用"""
        self._clear_preedit()
        self.commit_text(IBus.Text.new_from_string(text))
        logger.info(f"已提交文本: {text}")
        return False

    def _show_error(self, error: str):
        """显示错误信息"""
        self._update_preedit(f"❌ {error}")
        GLib.timeout_add(2000, self._clear_preedit)
        return False
