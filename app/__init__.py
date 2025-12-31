"""Core runtime package for the VoCoType Linux IBus application."""

from vocotype_version import __version__
from .config import DEFAULT_CONFIG, ensure_logging_dir, load_config
from .audio_capture import AudioCapture
from .transcribe import TranscriptionWorker, TranscriptionResult

__all__ = [
    "DEFAULT_CONFIG",
    "ensure_logging_dir",
    "load_config",
    "AudioCapture",
    "TranscriptionWorker",
    "TranscriptionResult",
    "__version__",
]
