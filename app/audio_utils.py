"""音频处理工具模块

提供音频配置加载和重采样等通用功能，供 IBus 和 Fcitx5 共享使用。
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# 目标采样率（ASR 模型需要）
SAMPLE_RATE = 16000
# 默认原生采样率
DEFAULT_NATIVE_SAMPLE_RATE = 44100


def load_audio_config() -> tuple[int | str | None, int]:
    """从配置文件加载音频设备配置

    Returns:
        (device, sample_rate): 设备（可能为 None、整数 ID 或字符串名称）和采样率
    """
    config_file = Path.home() / ".config" / "vocotype" / "audio.conf"
    if not config_file.exists():
        logger.warning("音频配置文件不存在: %s，使用默认设备", config_file)
        return None, DEFAULT_NATIVE_SAMPLE_RATE

    try:
        import configparser
        config = configparser.ConfigParser()
        config.read(config_file)

        # 优先使用 device_name（更稳定），回退到 device_id（向后兼容）
        device_name = config.get('audio', 'device_name', fallback=None)
        if device_name:
            sample_rate = config.getint('audio', 'sample_rate', fallback=DEFAULT_NATIVE_SAMPLE_RATE)
            logger.info("从配置加载: 设备=%s, 采样率=%d", device_name, sample_rate)
            return device_name, sample_rate

        device_id = config.getint('audio', 'device_id', fallback=None)
        sample_rate = config.getint('audio', 'sample_rate', fallback=DEFAULT_NATIVE_SAMPLE_RATE)

        logger.info("从配置加载: 设备=%s, 采样率=%d", device_id, sample_rate)
        return device_id, sample_rate
    except Exception as e:
        logger.warning("读取音频配置失败: %s，使用默认设备", e)
        return None, DEFAULT_NATIVE_SAMPLE_RATE


def resample_audio(audio: np.ndarray, orig_sr: int, target_sr: int) -> np.ndarray:
    """重采样音频到目标采样率

    Args:
        audio: 原始音频数据
        orig_sr: 原始采样率
        target_sr: 目标采样率

    Returns:
        重采样后的音频数据
    """
    if orig_sr == target_sr:
        return audio
    duration = len(audio) / orig_sr
    target_length = int(duration * target_sr)
    indices = np.linspace(0, len(audio) - 1, target_length)
    return np.interp(indices, np.arange(len(audio)), audio.astype(np.float32)).astype(np.int16)
