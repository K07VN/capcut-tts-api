"""
Data models and dataclasses for CapCut TTS API client.
"""

from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Union
import json
import re
from pathlib import Path
from copy import deepcopy

from capcut_tts_api.config import DEFAULT_DEVICE


@dataclass
class DeviceConfig:
    """
    Device profile and identity configuration for CapCut request signing.
    """

    aid: str = DEFAULT_DEVICE["aid"]
    app_name: str = DEFAULT_DEVICE["app_name"]
    appvr: str = DEFAULT_DEVICE["appvr"]
    version_name: str = DEFAULT_DEVICE["version_name"]
    version_code: str = DEFAULT_DEVICE["version_code"]
    channel: str = DEFAULT_DEVICE["channel"]
    device_platform: str = DEFAULT_DEVICE["device_platform"]
    device_type: str = DEFAULT_DEVICE["device_type"]
    device_brand: str = DEFAULT_DEVICE["device_brand"]
    os_version: str = DEFAULT_DEVICE["os_version"]
    device_id: str = DEFAULT_DEVICE["device_id"]
    iid: str = DEFAULT_DEVICE["iid"]
    region: str = DEFAULT_DEVICE["region"]
    loc: str = DEFAULT_DEVICE["loc"]
    lan: str = DEFAULT_DEVICE["lan"]
    pf: str = DEFAULT_DEVICE["pf"]
    tdid: str = DEFAULT_DEVICE["tdid"]

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DeviceConfig":
        """Create a DeviceConfig instance from a dictionary, using default values for missing keys."""
        merged = deepcopy(DEFAULT_DEVICE)
        merged.update(data)
        return cls(**{k: v for k, v in merged.items() if k in cls.__dataclass_fields__})

    @classmethod
    def from_json_file(cls, path: Union[str, Path]) -> "DeviceConfig":
        """Load device config from a JSON file."""
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        return cls.from_dict(data)

    def to_dict(self) -> Dict[str, str]:
        """Convert device config to dictionary representation."""
        return asdict(self)


@dataclass
class UploadResult:
    """
    Result metadata of a media upload to CapCut VOD space.
    """

    vid: str
    md5: str
    local_md5: str
    duration_ms: int
    format: Optional[str] = None
    size: int = 0
    file_type: Optional[str] = None
    store_uri: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Word:
    """Word-level timing information for STT subtitles."""

    text: str
    start_time: int
    end_time: int
    blank_duration: int = 0


@dataclass
class Utterance:
    """Subtitle sentence block timing and text."""

    text: str
    start_time: int
    end_time: int
    words: List[Word] = field(default_factory=list)
    translation_text: Optional[str] = None


@dataclass
class SubtitleResult:
    """Parsed STT transcription result containing utterances."""

    utterances: List[Utterance] = field(default_factory=list)
    full_text: str = ""
    full_translation_text: str = ""

    @classmethod
    def from_srt(cls, path: Union[str, Path]) -> "SubtitleResult":
        """Read a UTF-8 SubRip file into timed utterances for TTS workflows."""
        content = Path(path).read_text(encoding="utf-8-sig")
        blocks = re.split(r"\r?\n\s*\r?\n", content.strip()) if content.strip() else []
        utterances: List[Utterance] = []
        for block in blocks:
            lines = block.splitlines()
            timing_index = next((i for i, line in enumerate(lines) if "-->" in line), None)
            if timing_index is None:
                continue
            timing = lines[timing_index]
            match = re.match(r"\s*(\S+)\s*-->\s*(\S+)", timing)
            if not match:
                raise ValueError(f"Invalid SRT timing line: {timing!r}")
            start = cls._parse_srt_timestamp(match.group(1))
            end = cls._parse_srt_timestamp(match.group(2))
            text = "\n".join(lines[timing_index + 1:]).strip()
            if text:
                utterances.append(Utterance(text=text, start_time=start, end_time=max(start, end)))
        return cls(utterances=utterances, full_text=" ".join(u.text for u in utterances))

    @staticmethod
    def _parse_srt_timestamp(value: str) -> int:
        match = re.fullmatch(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})", value.strip())
        if not match:
            raise ValueError(f"Invalid SRT timestamp: {value!r}")
        hours, minutes, seconds, millis = (int(part) for part in match.groups())
        return ((hours * 60 + minutes) * 60 + seconds) * 1000 + millis

    @classmethod
    def from_payload(cls, payload: Dict[str, Any]) -> "SubtitleResult":
        """Parse subtitle payload dictionary into SubtitleResult object."""
        if not isinstance(payload, dict):
            return cls()
        raw_utterances = payload.get("utterances") or []
        utterance_list = []
        text_parts = []
        translation_parts = []

        for item in raw_utterances:
            words = [
                Word(
                    text=w.get("text", ""),
                    start_time=w.get("start_time", 0),
                    end_time=w.get("end_time", 0),
                    blank_duration=w.get("blank_duration", 0),
                )
                for w in item.get("words", [])
            ]
            text = item.get("text", "")
            translation_text = item.get("translation_text")
            if text:
                text_parts.append(text)
            if translation_text:
                translation_parts.append(translation_text)
            utterance_list.append(
                Utterance(
                    text=text,
                    start_time=item.get("start_time", 0),
                    end_time=item.get("end_time", 0),
                    words=words,
                    translation_text=translation_text,
                )
            )
        return cls(
            utterances=utterance_list,
            full_text=" ".join(text_parts),
            full_translation_text=" ".join(translation_parts),
        )

    @staticmethod
    def _srt_timestamp(milliseconds: Union[int, float]) -> str:
        """Format millisecond timestamps as the SRT HH:MM:SS,mmm form."""
        total_ms = max(0, int(round(float(milliseconds))))
        hours, remainder = divmod(total_ms, 3_600_000)
        minutes, remainder = divmod(remainder, 60_000)
        seconds, millis = divmod(remainder, 1_000)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"

    def to_srt(self, use_translation: bool = False) -> str:
        """Serialize utterances to SRT; use observed translation_text if requested."""
        blocks = []
        for index, utterance in enumerate(self.utterances, 1):
            selected = (
                utterance.translation_text
                if use_translation and utterance.translation_text
                else utterance.text
            )
            text = str(selected or "").replace("\r\n", "\n").replace("\r", "\n").strip()
            if not text:
                continue
            start = max(0, int(round(float(utterance.start_time))))
            end = max(start, int(round(float(utterance.end_time))))
            blocks.append(
                f"{len(blocks) + 1}\n"
                f"{self._srt_timestamp(start)} --> {self._srt_timestamp(end)}\n"
                f"{text}"
            )
        return "\n\n".join(blocks) + ("\n" if blocks else "")

    def write_srt(self, path: Union[str, Path], use_translation: bool = False) -> Path:
        """Write UTF-8 SRT and return its path."""
        output = Path(path)
        output.write_text(self.to_srt(use_translation=use_translation), encoding="utf-8", newline="\n")
        return output


@dataclass
class VoiceInfo:
    """Voice metadata object representing available CapCut TTS voices."""

    voice_type: str
    display_name: str
    resource_id: str
    lang: str
    lan: str
    captured_at: Optional[str] = None
    catalog_kind: Optional[str] = None
    source: Optional[str] = None
    service_compatibility: Optional[str] = None

    @classmethod
    def load_catalog(cls, file_path: Union[str, Path]) -> List["VoiceInfo"]:
        """Load list of voices from Voice.json catalog file."""
        path = Path(file_path)
        if not path.exists():
            return []
        with open(path, "r", encoding="utf-8") as fp:
            data = json.load(fp)
        # Voice.json also carries explicitly tagged records recovered from
        # the local digital-human asset cache. They are useful metadata, but
        # are not proven to be TTS service speakers and must not be silently
        # returned as such by this legacy TTS catalog loader.
        return [cls(**item) for item in data if item.get("catalog_kind") != "digital_human_voice"]
