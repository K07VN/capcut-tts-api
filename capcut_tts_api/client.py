"""
High-level Python API Client for CapCut Text-to-Speech (TTS) and Speech-to-Text (STT) tasks.
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union
from urllib.parse import urlencode

try:
    import requests
except ImportError:
    requests = None

from capcut_tts_api.config import BASE_URL
from capcut_tts_api.exceptions import CapCutAPIError, CapCutError, CapCutTaskError
from capcut_tts_api.models import DeviceConfig, SubtitleResult, UploadResult, VoiceInfo
from capcut_tts_api.signer import (
    base_headers,
    compact_json,
    common_query,
    escape_xml,
    make_sign_header,
    make_tts_payload_sign,
)
from capcut_tts_api.uploader import VODUploader


def _checked_json_response(resp: Any, label: str) -> Dict[str, Any]:
    try:
        data = resp.json()
    except Exception as exc:
        raise CapCutAPIError(
            f"{label} returned non-JSON HTTP {resp.status_code}: {resp.text[:500]}",
            status_code=resp.status_code,
        ) from exc
    if resp.status_code >= 400:
        raise CapCutAPIError(
            f"{label} HTTP {resp.status_code}: {data}",
            status_code=resp.status_code,
            response_data=data,
        )
    # The service can return HTTP 200 for an application-level failure.
    # Treat a non-zero `ret` as an error instead of trying to poll a task that
    # was never created (for example ret=1014/system busy).
    ret = data.get("ret") if isinstance(data, dict) else None
    if ret not in (None, 0, "0", ""):
        raise CapCutAPIError(
            f"{label} API error ret={ret!r}: {data.get('errmsg', '')}",
            status_code=resp.status_code,
            response_data=data,
        )
    return data


def _task_status_succeeded(status: Any) -> bool:
    return str(status or "").lower() in {"success", "succeed", "succeeded", "completed", "done"}


class CapCutClient:
    """
    Main CapCut API client for generating TTS and transcribing STT audio/video files.
    """

    def __init__(
        self,
        device: Optional[Union[DeviceConfig, Dict[str, Any], str, Path]] = None,
        session: Optional[Any] = None,
        base_url: Optional[str] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: float = 60.0,
    ):
        """
        Initialize CapCutClient.

        :param device: Device configuration instance, dictionary, or path to device.json file.
        :param session: Optional requests.Session instance for connection pooling.
        """
        if isinstance(device, DeviceConfig):
            self.device = device
        elif isinstance(device, (str, Path)):
            self.device = DeviceConfig.from_json_file(device)
        elif isinstance(device, dict):
            self.device = DeviceConfig.from_dict(device)
        else:
            self.device = DeviceConfig()

        self.session = session or (requests.Session() if requests else None)
        self.base_url = (base_url or os.environ.get("CAPCUT_BASE_URL") or BASE_URL).rstrip("/")
        if not self.base_url.startswith(("http://", "https://")):
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if timeout <= 0:
            raise ValueError("timeout must be positive")
        self.timeout = float(timeout)
        self.extra_headers: Dict[str, str] = {str(k): str(v) for k, v in (headers or {}).items()}
        # Only explicit caller-provided credentials are read. No browser or
        # CapCut cookie database is accessed.
        cookie = os.environ.get("CAPCUT_COOKIE") or os.environ.get("LYRA_TTS_COOKIE")
        bearer = os.environ.get("CAPCUT_BEARER") or os.environ.get("LYRA_TTS_BEARER")
        if cookie and "Cookie" not in self.extra_headers:
            self.extra_headers["Cookie"] = cookie
        if bearer and "Authorization" not in self.extra_headers:
            self.extra_headers["Authorization"] = bearer if bearer.lower().startswith("bearer ") else f"Bearer {bearer}"
        raw_headers = os.environ.get("CAPCUT_HEADERS_JSON") or os.environ.get("LYRA_TTS_HEADERS_JSON")
        if raw_headers:
            try:
                parsed = json.loads(raw_headers)
            except json.JSONDecodeError as exc:
                raise ValueError("CAPCUT_HEADERS_JSON must contain a JSON object") from exc
            if not isinstance(parsed, dict):
                raise ValueError("CAPCUT_HEADERS_JSON must contain a JSON object")
            for key, value in parsed.items():
                self.extra_headers.setdefault(str(key), str(value))

    def _headers(self, generated: Dict[str, str]) -> Dict[str, str]:
        merged = dict(generated)
        merged.update(self.extra_headers)
        return merged

    def _post_json(self, url: str, headers: Dict[str, str], body: str, label: str) -> Dict[str, Any]:
        """Send a JSON POST and apply the same HTTP/API error handling everywhere."""
        if self.session is None:
            raise CapCutError("The 'requests' package is required. Run 'pip install requests'.")
        response = self.session.post(
            url,
            headers=headers,
            data=body.encode("utf-8"),
            timeout=self.timeout,
            allow_redirects=False,
        )
        return _checked_json_response(response, label)

    # -------------------------------------------------------------------------
    # Voice Resolution Helper
    # -------------------------------------------------------------------------

    def resolve_voice(
        self,
        voice: Optional[str] = None,
        resource_id: Optional[str] = None,
        catalog_path: Optional[Union[str, Path]] = None,
    ) -> Tuple[str, str]:
        """
        Resolve voice_type and resource_id from Voice.json catalog or explicit inputs.

        :param voice: Voice type string (e.g. 'BV421_vivn_streaming', 'BV074_streaming') or display name
        :param resource_id: Optional explicit voice resource ID string
        :return: Tuple of (voice_type, resource_id)
        """
        default_voice = "BV074_streaming"
        default_resource_id = "7102355709945188865"

        target_voice = voice or default_voice
        target_res = resource_id

        # Try lookup in Voice.json catalog
        all_voices = self.list_voices(catalog_path=catalog_path)
        target_lower = target_voice.lower().strip() if target_voice else ""

        # 1. Primary match: voice_type
        for v in all_voices:
            if v.voice_type.lower() == target_lower:
                return v.voice_type, target_res or v.resource_id

        # 2. Secondary match: display_name or resource_id
        for v in all_voices:
            if v.display_name.lower() == target_lower or (target_res and v.resource_id == target_res):
                return v.voice_type, target_res or v.resource_id

        # Fallback to provided values or defaults
        resolved_voice = target_voice
        resolved_res = target_res or default_resource_id
        return resolved_voice, resolved_res

    # -------------------------------------------------------------------------
    # Request Payload Builders (Dry-run capable)
    # -------------------------------------------------------------------------

    def build_tts_new_request(
        self,
        texts: Union[str, List[str]],
        voice: Optional[str] = "BV074_streaming",
        resource_id: Optional[str] = None,
        payload_sign: Optional[str] = None,
    ) -> Tuple[str, Dict[str, str], str]:
        """
        Build URL, headers, and body string for creating a new TTS task.
        Automatically resolves resource_id for voice character if omitted.
        """
        if isinstance(texts, str):
            text_list = [texts]
        else:
            text_list = list(texts)

        if not text_list or any(not isinstance(text, str) or not text.strip() for text in text_list):
            raise ValueError("texts must contain non-empty strings")
        voice_type, final_resource_id = self.resolve_voice(voice=voice, resource_id=resource_id)

        device_dict = self.device.to_dict()
        babi = {
            "feature_entrance": "editor",
            "feature_entrance_detail": "editor-feature-text_to_speech",
            "feature_key": "text_to_speech",
            "scenario": "video_editor",
        }
        voice_blocks = []
        for text in text_list:
            voice_blocks.append(
                f'    <voice name="{escape_xml(voice_type)}" mock_tone_info="" platform="sami" '
                f'resource_id="{escape_xml(final_resource_id)}" emotion="" emotion_scale="0" style="" role="" '
                f'moyin_emotion="" is_clone_tone="false" need_subtitle_timestamp="false">\n'
                f'        <prosody rate="1.0">{escape_xml(text)}</prosody>\n'
                f'    </voice>'
            )
        ssml = (
            '<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">\n'
            + "\n".join(voice_blocks)
            + "\n</speak>"
        )
        extra_info = compact_json({"benefit_info": {}})
        payload = {
            "audio_format": "mp3",
            "babi_param": compact_json(babi),
            "credit_disable": False,
            "extra_info": extra_info,
            "need_merge_voice": False,
            "need_subtitle_timestamp": False,
            "scene": "text_to_speech",
            "ssml": ssml,
        }
        # Confirmed against the successful common-task response supplied by
        # the user (ret=0, task queueing). An explicit signature can override.
        payload["sign"] = payload_sign or make_tts_payload_sign(
            ssml, extra_info, device_dict["device_id"], device_dict["aid"]
        )
        body = {
            "bind_id": str(uuid.uuid4()),
            "can_queue": True,
            "enter_from": "text_to_speech",
            "tasks": [
                {
                    "context": str(uuid.uuid4()),
                    "payload": compact_json(payload),
                    "req_key": "sami_text_to_speech",
                    "task_version": "v3",
                }
            ],
        }

        body_text = compact_json(body)
        path = "/lv/v1/common_task/new"
        query = common_query(device_dict, babi, include_region=True)
        url = self.base_url + path + "?" + urlencode(query)
        headers = base_headers(device_dict, body_text, appid=True)
        lower_headers = {k.lower(): v for k, v in headers.items()}
        headers["sign"] = self.extra_headers.get("sign") or make_sign_header(
            url, device_dict["appvr"], lower_headers["device-time"], device_dict["tdid"]
        )
        return url, self._headers(headers), body_text

    def build_stt_new_request(
        self,
        audio_vid: str,
        audio_md5: str,
        duration_ms: int = 10000,
        language: str = "zh-CN",
        translation_language: str = "vi-VN",
        use_translation: bool = False,
    ) -> Tuple[str, Dict[str, str], str]:
        """
        Build URL, headers, and body string for creating a new STT task.
        """
        device_dict = self.device.to_dict()
        babi = {
            "feature_entrance": "editor",
            "feature_entrance_detail": "editor-elements-captions-subtitle_recognition",
            "feature_key": "subtitle_recognition",
            "scenario": "video_editor",
        }
        cap_json = {
            "adjust_endtime": 200,
            "audio": audio_vid,
            "audio_type": "vid",
            "caption_type": 0,
            "client_request_id": str(uuid.uuid4()),
            "duration": int(duration_ms),
            "enable_cache": True,
            "enter_from": "asr",
            "language": language,
            "max_lines": 1,
            "md5": audio_md5,
            "pack_options": {"need_attribute": True},
            "songs_info": [
                {"end_time": float(duration_ms) - 10.334, "id": "", "start_time": 0}
            ],
            "translation_language": translation_language,
            "use_translation": bool(use_translation),
            "words_per_line": 15,
        }
        body = {
            "bind_id": str(uuid.uuid4()).upper(),
            "can_queue": True,
            "enter_from": "asr",
            "tasks": [
                {
                    "context": str(uuid.uuid4()),
                    "payload": compact_json({"cap_json": cap_json}),
                    "req_key": "cc_audio_subtitle_asr",
                    "task_version": "v3",
                }
            ],
        }

        body_text = compact_json(body)
        path = "/lv/v1/common_task/new"
        query = common_query(device_dict, babi, include_region=True)
        url = self.base_url + path + "?" + urlencode(query)
        headers = base_headers(device_dict, body_text, appid=False)
        lower_headers = {k.lower(): v for k, v in headers.items()}
        headers["sign"] = self.extra_headers.get("sign") or make_sign_header(
            url, device_dict["appvr"], lower_headers["device-time"], device_dict["tdid"]
        )
        return url, self._headers(headers), body_text

    def build_query_request(
        self,
        task_id: str,
        token: str,
        mode: str = "tts",
        bind_id: str = "",
    ) -> Tuple[str, Dict[str, str], str]:
        """
        Build URL, headers, and body string for querying a task.
        :param mode: "tts" or "stt"
        """
        req_key = (
            "sami_text_to_speech"
            if mode in ("tts", "tts-query")
            else "cc_audio_subtitle_asr"
        )
        device_dict = self.device.to_dict()
        body = {
            "tasks": [
                {
                    "bind_id": bind_id,
                    "id": task_id,
                    "req_key": req_key,
                    "task_version": "v3",
                    "token": token,
                }
            ]
        }
        body_text = compact_json(body)
        path = "/lv/v1/common_task/query"
        query = common_query(device_dict, None, include_region=False)
        url = self.base_url + path + "?" + urlencode(query)
        headers = base_headers(
            device_dict, body_text, appid=(mode in ("tts", "tts-query"))
        )
        lower_headers = {k.lower(): v for k, v in headers.items()}
        headers["sign"] = self.extra_headers.get("sign") or make_sign_header(
            url, device_dict["appvr"], lower_headers["device-time"], device_dict["tdid"]
        )
        return url, self._headers(headers), body_text

    # -------------------------------------------------------------------------
    # Core API Execution Methods
    # -------------------------------------------------------------------------

    def create_tts_task(
        self,
        texts: Union[str, List[str]],
        voice: Optional[str] = "BV074_streaming",
        resource_id: Optional[str] = None,
        payload_sign: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Submit a new Text-to-Speech task to CapCut API.
        """
        url, headers, body_text = self.build_tts_new_request(
            texts, voice, resource_id, payload_sign
        )
        return self._post_json(url, headers, body_text, "create_tts_task")

    def query_tts_task(
        self, task_id: str, token: str, bind_id: str = ""
    ) -> Dict[str, Any]:
        """
        Query TTS task status by task_id and token.
        """
        url, headers, body_text = self.build_query_request(
            task_id, token, mode="tts", bind_id=bind_id
        )
        return self._post_json(url, headers, body_text, "query_tts_task")

    def generate_speech(
        self,
        texts: Union[str, List[str]],
        voice: Optional[str] = "BV074_streaming",
        resource_id: Optional[str] = None,
        wait: bool = True,
        poll_interval: float = 1.0,
        timeout: float = 60.0,
        payload_sign: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Convenience method: Submits TTS task and polls until completed.
        """
        create_res = self.create_tts_task(
            texts, voice, resource_id, payload_sign
        )
        if not wait:
            return create_res

        tasks = (create_res.get("data") or {}).get("tasks") or []
        if not tasks:
            raise CapCutTaskError(f"No task returned from API: {create_res}")

        task_id = tasks[0]["id"]
        token = tasks[0]["token"]
        bind_id = tasks[0].get("bind_id") or (create_res.get("data") or {}).get("bind_id") or ""

        start_time = time.time()
        while time.time() - start_time < timeout:
            query_res = self.query_tts_task(task_id, token, bind_id=bind_id)
            query_tasks = (query_res.get("data") or {}).get("tasks") or []
            if query_tasks:
                status = query_tasks[0].get("status")
                if _task_status_succeeded(status):
                    return query_res
                elif status == "failed":
                    raise CapCutTaskError(f"TTS Task failed: {query_res}")
            time.sleep(poll_interval)

        raise CapCutTaskError(f"TTS Task timed out after {timeout} seconds")

    def upload_audio(self, file_path: Union[str, Path]) -> UploadResult:
        """
        Upload audio or video file to VOD space.
        """
        uploader = VODUploader(self.device, session=self.session)
        return uploader.upload_file(file_path)

    def create_stt_task(
        self,
        audio_vid: str,
        audio_md5: str,
        duration_ms: int = 10000,
        language: str = "zh-CN",
        translation_language: str = "vi-VN",
        use_translation: bool = False,
    ) -> Dict[str, Any]:
        """
        Submit Speech-to-Text task using pre-uploaded media vid and md5.
        """
        url, headers, body_text = self.build_stt_new_request(
            audio_vid, audio_md5, duration_ms, language, translation_language, use_translation
        )
        return self._post_json(url, headers, body_text, "create_stt_task")

    def query_stt_task(
        self, task_id: str, token: str, bind_id: str = ""
    ) -> Dict[str, Any]:
        """
        Query STT task status by task_id and token.
        """
        url, headers, body_text = self.build_query_request(
            task_id, token, mode="stt", bind_id=bind_id
        )
        return self._post_json(url, headers, body_text, "query_stt_task")

    def transcribe_file(
        self,
        file_path: Union[str, Path],
        language: str = "zh-CN",
        translation_language: str = "vi-VN",
        use_translation: bool = False,
        wait: bool = True,
        poll_interval: float = 2.0,
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        """
        Upload media file, create STT task, and optionally poll for completion.
        """
        upload_res = self.upload_audio(file_path)
        duration_ms = upload_res.duration_ms or 10000

        stt_res = self.create_stt_task(
            audio_vid=upload_res.vid,
            audio_md5=upload_res.md5,
            duration_ms=duration_ms,
            language=language,
            translation_language=translation_language,
            use_translation=use_translation,
        )

        if not wait:
            return stt_res

        tasks = (stt_res.get("data") or {}).get("tasks") or []
        if not tasks:
            raise CapCutTaskError(f"No STT task returned from API: {stt_res}")

        task_id = tasks[0]["id"]
        token = tasks[0]["token"]

        start_time = time.time()
        while time.time() - start_time < timeout:
            bind_id = tasks[0].get("bind_id") or (stt_res.get("data") or {}).get("bind_id") or ""
            query_res = self.query_stt_task(task_id, token, bind_id=bind_id)
            query_tasks = (query_res.get("data") or {}).get("tasks") or []
            if query_tasks:
                status = query_tasks[0].get("status")
                if _task_status_succeeded(status):
                    return query_res
                elif status == "failed":
                    raise CapCutTaskError(f"STT Task failed: {query_res}")
            time.sleep(poll_interval)

        raise CapCutTaskError(f"STT Task timed out after {timeout} seconds")

    def extract_subtitles(self, query_response: Dict[str, Any]) -> SubtitleResult:
        """
        Extract and parse subtitles from an STT query response payload.
        """
        try:
            tasks = (query_response.get("data") or {}).get("tasks") or []
            if not tasks:
                return SubtitleResult()
            raw_payload = tasks[0].get("payload", "{}")
            if isinstance(raw_payload, str):
                payload_dict = json.loads(raw_payload)
            else:
                payload_dict = raw_payload
            return SubtitleResult.from_payload(payload_dict)
        except Exception as exc:
            raise CapCutError(f"Failed to parse subtitle payload: {exc}") from exc

    def write_srt(
        self,
        query_response: Dict[str, Any],
        path: Union[str, Path],
        use_translation: bool = False,
    ) -> Path:
        """Extract completed STT utterances and write source or translated SRT."""
        return self.extract_subtitles(query_response).write_srt(
            path, use_translation=use_translation
        )

    def extract_tts_artifacts(self, query_response: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract speech URLs/VIDs from a completed common-task response."""
        artifacts: List[Dict[str, Any]] = []
        for task in ((query_response.get("data") or {}).get("tasks") or []):
            raw = task.get("payload", {})
            try:
                payload = json.loads(raw) if isinstance(raw, str) else raw
            except json.JSONDecodeError as exc:
                raise CapCutError(f"Invalid TTS task payload: {exc}") from exc
            for item in (payload or {}).get("audio_subtitles") or []:
                if isinstance(item, dict):
                    artifacts.append(dict(item))
        return artifacts

    def download_tts_audio(
        self,
        query_response: Dict[str, Any],
        output_path: Union[str, Path],
        artifact_index: int = 0,
    ) -> Path:
        """Download a completed common-task TTS artifact to a local file.

        The URL fields are limited to response fields observed in the native
        response/download handling: ``speech_url``, ``audio_url`` and ``url``.
        A response containing only a VID cannot be downloaded without the
        separate VOD resolver, so it fails explicitly instead of guessing one.
        """
        if self.session is None:
            raise CapCutError("The 'requests' package is required. Run 'pip install requests'.")
        artifacts = self.extract_tts_artifacts(query_response)
        if artifact_index < 0 or artifact_index >= len(artifacts):
            raise CapCutError(f"TTS response has {len(artifacts)} downloadable artifact(s)")
        artifact = artifacts[artifact_index]
        url = next((artifact.get(key) for key in ("speech_url", "audio_url", "url")
                    if isinstance(artifact.get(key), str) and artifact.get(key)), None)
        if not url:
            raise CapCutError("TTS artifact has no observed download URL (speech_url/audio_url/url)")
        response = self.session.get(url, timeout=self.timeout, allow_redirects=True)
        if response.status_code >= 400:
            raise CapCutAPIError(
                f"download_tts_audio HTTP {response.status_code}: {response.text[:500]}",
                status_code=response.status_code,
            )
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(response.content)
        if not output.stat().st_size:
            raise CapCutError("TTS download returned an empty file")
        return output

    def generate_speech_and_transcribe(
        self,
        texts: Union[str, List[str]],
        audio_path: Union[str, Path] = "tts-output.mp3",
        srt_path: Optional[Union[str, Path]] = None,
        voice: Optional[str] = "BV074_streaming",
        resource_id: Optional[str] = None,
        language: str = "zh-CN",
        translation_language: str = "vi-VN",
        use_translation: bool = False,
        timeout: float = 120.0,
    ) -> Dict[str, Any]:
        """Generate TTS, save its artifact, then run STT on that same file."""
        tts_response = self.generate_speech(
            texts, voice=voice, resource_id=resource_id,
            timeout=timeout,
        )
        audio_file = self.download_tts_audio(tts_response, audio_path)
        stt_response = self.transcribe_file(
            audio_file, language=language,
            translation_language=translation_language,
            use_translation=use_translation,
            timeout=timeout,
        )
        if srt_path is not None:
            self.write_srt(stt_response, srt_path, use_translation=use_translation)
        return {"tts": tts_response, "audio_path": str(audio_file), "stt": stt_response,
                **({"srt_path": str(srt_path)} if srt_path is not None else {})}

    def generate_speech_from_srt(
        self,
        srt_path: Union[str, Path],
        output_dir: Union[str, Path] = "tts-srt-output",
        voice: Optional[str] = "BV074_streaming",
        resource_id: Optional[str] = None,
        timeout: float = 120.0,
        part: bool = True,
        audio_path: Union[str, Path] = "tts-output.mp3",
    ) -> Dict[str, Any]:
        """Generate TTS from SRT cues, either as separate parts or one MP3.

        Cue timings are retained in the returned ``cues`` metadata. CapCut's
        common-task response determines whether one or multiple artifacts are
        returned; each observed artifact is downloaded separately.
        """
        from capcut_tts_api.models import SubtitleResult

        subtitles = SubtitleResult.from_srt(srt_path)
        if not subtitles.utterances:
            raise CapCutError("SRT contains no non-empty subtitle cues")
        if not part:
            combined_text = " ".join(item.text.replace("\n", " ").strip()
                                      for item in subtitles.utterances)
            response = self.generate_speech(
                combined_text,
                voice=voice,
                resource_id=resource_id,
                timeout=timeout,
            )
            artifacts = self.extract_tts_artifacts(response)
            if len(artifacts) != 1:
                raise CapCutError(
                    f"No-part TTS expected one audio artifact, received {len(artifacts)}"
                )
            output_file = self.download_tts_audio(response, audio_path, artifact_index=0)
            return {
                "tts": response,
                "srt_path": str(srt_path),
                "part": False,
                "audio_path": str(output_file),
                "text": combined_text,
                "cues": [{
                    "index": 1,
                    "start_time": subtitles.utterances[0].start_time,
                    "end_time": subtitles.utterances[-1].end_time,
                    "audio_path": str(output_file),
                }],
            }
        response = self.generate_speech(
            [item.text for item in subtitles.utterances],
            voice=voice,
            resource_id=resource_id,
            timeout=timeout,
        )
        artifacts = self.extract_tts_artifacts(response)
        if len(artifacts) < len(subtitles.utterances):
            raise CapCutError(
                f"TTS returned {len(artifacts)} artifact(s) for {len(subtitles.utterances)} SRT cue(s)"
            )
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        files = []
        for index, cue in enumerate(subtitles.utterances):
            path = output / f"{index + 1:03d}.mp3"
            self.download_tts_audio(response, path, artifact_index=index)
            files.append({
                "index": index + 1,
                "text": cue.text,
                "start_time": cue.start_time,
                "end_time": cue.end_time,
                "audio_path": str(path),
            })
        return {"tts": response, "srt_path": str(srt_path), "part": True,
                "output_dir": str(output), "cues": files}

    def list_voices(
        self, lang: Optional[str] = None, catalog_path: Optional[Union[str, Path]] = None
    ) -> List[VoiceInfo]:
        """
        List available CapCut TTS voices from catalog file.
        """
        path = catalog_path or Path(__file__).parent / "Voice.json"
        voices = [
            v for v in VoiceInfo.load_catalog(path)
            if v.catalog_kind != "digital_human_voice"
        ]
        if lang:
            return [v for v in voices if v.lang.lower() == lang.lower() or v.lan.lower() == lang.lower()]
        return voices

    def list_local_digital_human_voice_metadata(
        self, catalog_path: Optional[Union[str, Path]] = None
    ) -> List[Dict[str, Any]]:
        """Return local digital-human asset metadata from Voice.json.

        These records came from cached ResourceSDK responses and are not
        asserted to be usable TTS service speaker IDs.
        """
        path = Path(catalog_path or Path(__file__).parent / "Voice.json")
        if not path.exists():
            return []
        with path.open("r", encoding="utf-8") as fp:
            records = json.load(fp)
        return [
            item for item in records
            if isinstance(item, dict) and item.get("catalog_kind") == "digital_human_voice"
        ]
