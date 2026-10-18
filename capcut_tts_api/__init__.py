"""
CapCut TTS API Python SDK & Package.

Pure Python client for CapCut Text-to-Speech (TTS), Speech-to-Text (STT),
and VOD chunked audio upload workflows.
"""

from capcut_tts_api.client import CapCutClient
from capcut_tts_api.exceptions import (
    CapCutAPIError,
    CapCutError,
    CapCutSignError,
    CapCutTaskError,
    CapCutUploadError,
)
from capcut_tts_api.models import (
    DeviceConfig,
    SubtitleResult,
    UploadResult,
    Utterance,
    VoiceInfo,
    Word,
)
from capcut_tts_api.action import TTSConfigurationError, build_tts_action, parse_provider_params

__version__ = "1.5.0"

__all__ = [
    "CapCutClient",
    "DeviceConfig",
    "UploadResult",
    "SubtitleResult",
    "Utterance",
    "Word",
    "VoiceInfo",
    "CapCutError",
    "CapCutAPIError",
    "CapCutUploadError",
    "CapCutSignError",
    "CapCutTaskError",
    "TTSConfigurationError",
    "build_tts_action",
    "parse_provider_params",
    "__version__",
]
