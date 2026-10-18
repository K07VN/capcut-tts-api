"""Builders for the local Lyra draft TTS action contract."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


TTS_OPTIONAL_FIELDS = frozenset("""emotion emotion_scale resource_id res_id tone_name tone_speaker mock_tone_speaker tts_speaker speaker tone_type tone_platform tone_category tone_category_id tone_category_name tone_second_category_id tone_second_category_name tone_effect_id third_resource_id tone_emotion_name_key tone_emotion_style tone_emotion_role tone_emotion_selection tone_emotion_scale moyin_emotion sami_emotion sami_emotion_scale is_clone_tone is_ai_clone_tone tone_sample_rate enable_text_seg need_bind_text replace_audio_segment_ids tone_sample_rate audio_path audio_format network_mode output_dir write_to_draft copy_to_draft commit_immediately should_replace is_auto_update need_insert_target_track target_duration source_start_time source_duration target_track_index replace audio_track_index tts_task_id tts_generate_scene cloned_model_type algo_type from enter_from source_from cache_key sample_rate pitch_rate phoneme_size max_paragraph_phoneme_size duration duration_us duration_ms start_time start_time_us start_time_ms source_duration_us source_duration_ms source_start_time_us source_start_time_ms is_ugc tone_info use_cache flush_sentence disable_newline_strategy download volume audio_title audio_category_title audio_category_id direct_url tts_endpoint headers_json""".split())


class TTSConfigurationError(ValueError):
    """Malformed local TTS operation input."""


def parse_provider_params(value: str | Path | Mapping[str, Any] | None) -> dict[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return dict(value)
    raw = str(value)
    if raw.startswith("@"):
        try:
            raw = Path(raw[1:]).read_text(encoding="utf-8-sig")
        except OSError as exc:
            raise TTSConfigurationError("provider JSON file cannot be read") from exc
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TTSConfigurationError("provider JSON is invalid") from exc
    if not isinstance(parsed, dict):
        raise TTSConfigurationError("provider JSON must be an object")
    return parsed


def build_tts_action(*, text: str, seg_id: str, speaker: str | None = None,
                     provider_params_json: str | Path | Mapping[str, Any] | None = None,
                     extension_json: str | Path | Mapping[str, Any] | None = None,
                     **options: Any) -> dict[str, Any]:
    """Build the observed local draft algo TTS action envelope."""
    if not isinstance(text, str) or not text.strip():
        raise TTSConfigurationError("text must be non-empty")
    if not isinstance(seg_id, str) or not seg_id.strip():
        raise TTSConfigurationError("seg_id must be non-empty")
    unknown = {
        key for key in options
        if key not in TTS_OPTIONAL_FIELDS
        and not (isinstance(key, str) and (
            key.startswith("tone_") or key.startswith("sami_") or key.startswith("moyin_")
        ))
    }
    if unknown:
        raise TTSConfigurationError("unknown TTS option(s): " + ", ".join(sorted(unknown)))
    params: dict[str, Any] = {"text": text, "seg_id": seg_id}
    if speaker is not None:
        if not isinstance(speaker, str) or not speaker.strip():
            raise TTSConfigurationError("speaker must be a service ID")
        params["tts_speaker"] = speaker
    params.update({key: value for key, value in options.items() if value is not None})
    provider = parse_provider_params(provider_params_json)
    extension = parse_provider_params(extension_json)
    if provider is not None:
        params["provider_params"] = provider
    if extension is not None:
        params["extra"] = extension
    params["segment_id"] = params.pop("seg_id")
    params["text_segment_id"] = params["segment_id"]
    return {"action_name": "TTS_ACTION", "params": {"tts": {"params": params}},
            "segment_ids": [seg_id]}
