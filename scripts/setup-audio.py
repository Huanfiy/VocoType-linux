#!/usr/bin/env python3
"""VoCoType 音频设备配置向导

交互式配置音频输入设备并测试录音和识别功能。
"""

from __future__ import annotations

import sys
import os
import threading
import queue
from pathlib import Path

import numpy as np
import sounddevice as sd

# 添加项目根目录到 path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.wave_writer import write_wav

TARGET_SAMPLE_RATE = 16000
BLOCK_MS = 20
CONFIG_DIR = Path.home() / ".config" / "vocotype"
CONFIG_FILE = CONFIG_DIR / "audio.conf"


def print_header(text: str):
    """打印标题"""
    print("\n" + "=" * 60)
    print(f"  {text}")
    print("=" * 60)


def list_audio_devices() -> list[tuple[int, dict]]:
    """列出所有输入设备，返回 (索引, 设备信息) 列表"""
    devices = sd.query_devices()
    input_devices = []

    for i, dev in enumerate(devices):
        if dev['max_input_channels'] > 0:
            input_devices.append((i, dev))

    return input_devices


def display_devices(devices: list[tuple[int, dict]]) -> None:
    """显示设备列表"""
    print_header("可用的音频输入设备")
    print()

    default_input = sd.default.device[0]

    for idx, dev in devices:
        marker = " ← 系统默认" if idx == default_input else ""
        print(f"  [{idx}] {dev['name']}")
        print(f"      输入通道: {dev['max_input_channels']}, "
              f"采样率: {int(dev['default_samplerate'])}Hz{marker}")
        print()


def select_device(devices: list[tuple[int, dict]]) -> tuple[int, int]:
    """让用户选择设备，返回 (设备ID, 采样率)"""
    while True:
        try:
            choice = input("请输入设备编号: ").strip()
            device_id = int(choice)

            # 检查是否在可用列表中
            for idx, dev in devices:
                if idx == device_id:
                    sample_rate = int(dev['default_samplerate'])
                    print(f"\n✓ 已选择: [{device_id}] {dev['name']} ({sample_rate}Hz)")
                    return device_id, sample_rate

            print(f"❌ 设备 {device_id} 不是有效的输入设备，请重新选择")
        except ValueError:
            print("❌ 请输入有效的数字")
        except KeyboardInterrupt:
            print("\n\n用户取消")
            sys.exit(0)


def record_test_audio(device_id: int, sample_rate: int) -> np.ndarray:
    """录制测试音频，返回音频数据"""
    print_header("录音测试")
    print("\n准备录音...")
    print("  1. 按 Enter 开始录音")
    print("  2. 对着麦克风说一句话（例如：\"测试麦克风\"）")
    print("  3. 说完后按 Enter 停止录音\n")

    frames: list[np.ndarray] = []
    stop_event = threading.Event()
    audio_queue: queue.Queue = queue.Queue(maxsize=200)

    block_size = int(sample_rate * BLOCK_MS / 1000)

    def audio_callback(indata, frame_count, time_info, status):
        if status:
            print(f"音频状态: {status}")
        try:
            audio_queue.put_nowait(indata.copy())
        except queue.Full:
            pass

    def capture_thread():
        while not stop_event.is_set():
            try:
                frame = audio_queue.get(timeout=0.1)
                frames.append(frame)
            except queue.Empty:
                continue

    # 等待开始
    input("按 Enter 开始录音...")

    # 启动音频流
    stream = sd.InputStream(
        samplerate=sample_rate,
        blocksize=block_size,
        device=device_id,
        channels=1,
        dtype='int16',
        callback=audio_callback,
    )
    stream.start()

    # 启动采集线程
    collector = threading.Thread(target=capture_thread, daemon=True)
    collector.start()

    print("🎤 正在录音... 对着麦克风说话，完成后按 Enter 停止")

    # 等待停止
    input()

    # 停止录音
    stop_event.set()
    stream.stop()
    stream.close()
    collector.join(timeout=1.0)

    if not frames:
        print("❌ 没有采集到音频数据")
        return None

    # 合并音频帧
    audio_data = np.concatenate(frames).flatten()
    duration = len(audio_data) / sample_rate
    max_amplitude = np.max(np.abs(audio_data))

    print(f"\n✓ 录音完成: {duration:.2f}秒, 最大振幅: {max_amplitude}")

    if max_amplitude < 100:
        print("⚠️  警告: 音频信号非常弱，可能麦克风未工作")

    return audio_data


def resample_audio(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """重采样音频"""
    if orig_sr == target_sr:
        return audio
    duration = len(audio) / orig_sr
    target_length = int(duration * target_sr)
    indices = np.linspace(0, len(audio) - 1, target_length)
    return np.interp(indices, np.arange(len(audio)), audio.astype(np.float32)).astype(np.int16)


def playback_test(audio_data: np.ndarray, sample_rate: int) -> bool:
    """播放录音并让用户确认，返回是否能听到"""
    print_header("播放录音")
    print("\n正在播放刚才的录音...")

    # 播放音频
    sd.play(audio_data, samplerate=sample_rate)
    sd.wait()  # 等待播放完成

    print("\n播放完成！")

    while True:
        answer = input("你能听得清楚吗? (y/n): ").strip().lower()
        if answer in ('y', 'yes', '是', 'Y'):
            return True
        elif answer in ('n', 'no', '否', 'N'):
            print("\n设备可能选择不正确，让我们重新选择...")
            return False
        else:
            print("请输入 y (是) 或 n (否)")


def test_asr_recognition(audio_data: np.ndarray, sample_rate: int) -> bool:
    """测试 ASR 识别，返回是否成功"""
    print_header("语音识别测试")
    print("\n正在初始化语音识别引擎...")
    print("（首次运行会下载模型，约 500MB，请稍候...）\n")

    try:
        from app.funasr_server import FunASRServer

        # 初始化 FunASR
        asr_server = FunASRServer()
        result = asr_server.initialize()

        if not result["success"]:
            print(f"❌ 识别引擎初始化失败: {result.get('error')}")
            return False

        print("✓ 识别引擎初始化成功\n")

        # 重采样到 16kHz
        if sample_rate != TARGET_SAMPLE_RATE:
            print(f"重采样音频: {sample_rate}Hz -> {TARGET_SAMPLE_RATE}Hz")
            audio_16k = resample_audio(audio_data, sample_rate, TARGET_SAMPLE_RATE)
        else:
            audio_16k = audio_data

        # 保存临时文件
        import tempfile
        with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as f:
            temp_path = f.name
            write_wav(Path(temp_path), audio_16k.tobytes(), TARGET_SAMPLE_RATE)

        try:
            # 识别
            print("正在识别...")
            result = asr_server.transcribe_audio(temp_path)

            if result.get("success"):
                text = result.get("text", "").strip()
                if text:
                    print(f"\n{'='*60}")
                    print(f"识别结果: {text}")
                    print(f"{'='*60}\n")

                    # 询问用户识别结果是否基本一致
                    while True:
                        answer = input("识别结果和你说的话是否基本一致? (y=一致/n=完全不对): ").strip().lower()
                        if answer in ('y', 'yes', '是', 'Y'):
                            print("\n✓ 识别效果良好！")
                            return True
                        elif answer in ('n', 'no', '否', 'N'):
                            return False
                        else:
                            print("请输入 y (一致) 或 n (不对)")
                else:
                    print("\n❌ 识别结果为空（没有识别到任何内容），可能是:")
                    print("   - 没有说话或说话时间太短")
                    print("   - 环境噪音太大")
                    print("   - 麦克风音量太小\n")
                    return False
            else:
                print(f"\n❌ 识别失败: {result.get('error')}")
                return False
        finally:
            # 删除临时文件
            try:
                os.unlink(temp_path)
            except:
                pass

            # 清理资源
            try:
                asr_server.cleanup()
            except:
                pass

    except Exception as e:
        print(f"\n❌ 识别测试出错: {e}")
        import traceback
        traceback.print_exc()
        return False


def save_config(device_id: int, sample_rate: int) -> None:
    """保存音频配置到文件"""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    config_content = f"""[audio]
device_id = {device_id}
sample_rate = {sample_rate}
"""

    CONFIG_FILE.write_text(config_content)
    print(f"\n✓ 配置已保存到: {CONFIG_FILE}")


def main():
    """主流程"""
    print("\n" + "🎤" * 20)
    print("  VoCoType 音频设备配置向导")
    print("🎤" * 20)

    # 1. 列出设备
    devices = list_audio_devices()

    if not devices:
        print("\n❌ 错误: 没有找到可用的音频输入设备")
        sys.exit(1)

    # 主循环：选择设备 -> 录音 -> 播放确认
    while True:
        # 2. 显示并选择设备
        display_devices(devices)
        device_id, sample_rate = select_device(devices)

        # 录音-播放-ASR测试循环
        while True:
            # 3. 录音测试
            audio_data = record_test_audio(device_id, sample_rate)

            if audio_data is None:
                retry = input("\n录音失败，是否重试? (y/n): ").strip().lower()
                if retry in ('y', 'yes', '是'):
                    continue
                else:
                    print("返回设备选择...")
                    break

            # 4. 播放测试
            can_hear = playback_test(audio_data, sample_rate)

            if not can_hear:
                # 重新选择设备
                break

            # 5. ASR 识别测试
            asr_success = test_asr_recognition(audio_data, sample_rate)

            if asr_success:
                # 6. 保存配置
                save_config(device_id, sample_rate)

                print("\n" + "🎉" * 20)
                print("  配置完成！音频设备已就绪。")
                print("🎉" * 20 + "\n")
                return
            else:
                # ASR 失败，询问是否重新录音
                retry = input("\n识别失败，是否重新录音测试? (y/n): ").strip().lower()
                if retry in ('y', 'yes', '是'):
                    continue  # 重新录音
                else:
                    change = input("是否更换设备? (y/n): ").strip().lower()
                    if change in ('y', 'yes', '是'):
                        break  # 重新选择设备
                    else:
                        print("\n配置未完成，退出。")
                        sys.exit(1)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n用户取消配置")
        sys.exit(0)
