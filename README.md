<p align="center"><strong>English</strong> · <a href="README.vi.md">Tiếng Việt</a> · <a href="README.zh-CN.md">简体中文</a></p>

<h1 align="center">CapCut TTS &amp; STT API</h1>
<p align="center"><strong>Python SDK for CapCut speech tasks</strong></p>
<p align="center">Text to speech · Speech recognition · Translation · SRT · Voice catalog</p>

---

## Features

`capcut-tts-api` exposes a Python client for the speech workflows implemented by the package:

- create and poll a TTS task, then download the audio artifact returned by the service;
- upload a local audio or video file, submit STT, and parse utterance and word timings;
- request translation during STT and write the returned translated text to SRT;
- read an SRT file and create one audio file per cue or one combined audio file;
- inspect the voice and language data shipped inside `capcut_tts_api`.

The examples below call the package directly. They do not depend on the command-line parser.

## Install

Python 3.9 or newer is required.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Python quick start

### 1. Create a client and inspect voices

```python
from capcut_tts_api import CapCutClient

client = CapCutClient(timeout=60)

# VoiceInfo objects are loaded from capcut_tts_api/Voice.json.
for item in client.list_voices(lang="vi-VN")[:5]:
    print(item.voice_type, item.display_name, item.resource_id)

# A voice_type, display name, or explicit resource ID can be resolved.
voice_type, resource_id = client.resolve_voice("BV421_vivn_streaming")
print(voice_type, resource_id)
```

`list_voices()` reads the local catalog and does not contact the service. The catalog can be stale; the service still decides whether an account may use a voice.

### 2. Generate speech and save the returned artifact

```python
from capcut_tts_api import CapCutClient

client = CapCutClient(timeout=60)
result = client.generate_speech(
    "Hello from the Python API.",
    voice="BV421_vivn_streaming",
    timeout=180,
)
audio_path = client.download_tts_audio(result, "hello.mp3")
print(f"saved {audio_path}")
```

`generate_speech()` waits for a completed task by default. Set `wait=False` when the caller wants to manage polling:

```python
created = client.generate_speech("A queued task", voice="BV421_vivn_streaming", wait=False)
task = created["data"]["tasks"][0]

import time
deadline = time.monotonic() + 180
while time.monotonic() < deadline:
    completed = client.query_tts_task(
        task["id"], task["token"], task.get("bind_id", "")
    )
    status = (completed.get("data", {}).get("tasks") or [{}])[0].get("status", "")
    if status.lower() in {"success", "succeed", "succeeded", "completed", "done"}:
        break
    if status.lower() in {"failed", "failure", "error"}:
        raise RuntimeError(f"TTS task failed: {completed}")
    time.sleep(1)
else:
    raise TimeoutError("TTS task did not complete before the deadline")

audio_path = client.download_tts_audio(completed, "queued-task.mp3")
print(status, audio_path)
```

The query call above is normally repeated until the task status is successful. `download_tts_audio()` accepts the completed response and writes the URL found in the response artifact.

### 3. Transcribe a file and write source-language SRT

```python
from capcut_tts_api import CapCutClient

client = CapCutClient(timeout=60)
stt = client.transcribe_file(
    "recording.mp3",
    language="vi-VN",
    timeout=180,
)
subtitles = client.extract_subtitles(stt)
subtitles.write_srt("recording.vi.srt")
print(subtitles.full_text)
```

`transcribe_file()` uploads the media, creates the STT task, polls it, and returns the completed response. Use `wait=False` to receive the creation response instead.

### 4. Request translation and write translated SRT

```python
translated = client.transcribe_file(
    "recording.mp3",
    language="vi-VN",
    translation_language="en-US",
    use_translation=True,
    timeout=180,
)
client.write_srt(translated, "recording.en.srt", use_translation=True)
```

Translation text is taken from the completed response. If the service returns no `translation_text` values, the SDK cannot invent a translation.

### 5. Create speech from an SRT file

```python
# One downloaded artifact for every non-empty cue.
parts = client.generate_speech_from_srt(
    "captions.srt",
    voice="BV421_vivn_streaming",
    output_dir="voice-parts",
    part=True,
)
print(parts["cues"])

# One request and one downloaded artifact containing all cue text.
combined = client.generate_speech_from_srt(
    "captions.srt",
    voice="BV421_vivn_streaming",
    audio_path="captions.mp3",
    part=False,
)
print(combined["audio_path"])
```

Cue start/end times are retained in the returned metadata. The method does not alter the source SRT or fabricate timing information.

### 6. Generate speech, then transcribe the same file

```python
result = client.generate_speech_and_transcribe(
    "Xin chào từ CapCut.",
    voice="BV421_vivn_streaming",
    audio_path="roundtrip.mp3",
    srt_path="roundtrip.srt",
    language="vi-VN",
)
print(result["audio_path"], result["srt_path"])
```

### Error handling

```python
from capcut_tts_api import CapCutAPIError, CapCutError, CapCutTaskError

try:
    client.generate_speech("test", voice="BV421_vivn_streaming", timeout=180)
except CapCutTaskError as exc:
    print(f"task failed or timed out: {exc}")
except CapCutAPIError as exc:
    print(f"service error: {exc}")
except CapCutError as exc:
    print(f"client error: {exc}")
```

## API reference and task commands

The high-level methods cover most programs. These lower-level calls are useful when a worker stores task IDs and polls them later.

```python
from capcut_tts_api import CapCutClient

client = CapCutClient(timeout=60)

# Submit TTS without the convenience polling loop.
created = client.create_tts_task(
    ["First segment", "Second segment"],
    voice="BV421_vivn_streaming",
)
task = created["data"]["tasks"][0]

# Call this later (and repeat while the task is queued/running).
tts_result = client.query_tts_task(
    task_id=task["id"],
    token=task["token"],
    bind_id=task.get("bind_id", ""),
)
print(tts_result)

# Read artifact metadata before downloading a selected artifact.
for artifact in client.extract_tts_artifacts(tts_result):
    print(artifact)
```

For an STT worker, upload and query explicitly:

```python
upload = client.upload_audio("recording.mp3")
created = client.create_stt_task(
    audio_vid=upload.vid,
    audio_md5=upload.md5,
    duration_ms=upload.duration_ms,
    language="vi-VN",
    translation_language="en-US",
    use_translation=True,
)
task = created["data"]["tasks"][0]
stt_result = client.query_stt_task(task["id"], task["token"], task.get("bind_id", ""))
subtitles = client.extract_subtitles(stt_result)
subtitles.write_srt("recording.en.srt", use_translation=True)
```

Request builders are available when an application needs to inspect or log a request before sending it:

```python
url, headers, body = client.build_tts_new_request(
    "Preview only", voice="BV421_vivn_streaming"
)
print(url, headers, body)

stt_url, stt_headers, stt_body = client.build_stt_new_request(
    audio_vid="uploaded-vid",
    audio_md5="uploaded-md5",
    duration_ms=10_000,
    language="vi-VN",
)
```

`create_tts_task()` and `create_stt_task()` send requests; `build_*` methods only return request data. `upload_audio()` sends the media upload and returns an `UploadResult` containing `vid`, `md5`, duration, size, and format.

## Optional command-line use

The same client is available as `capcut-tts-api` or `python -m capcut_tts_api.cli`. Use `--help` for the installed version's modes and arguments. Typical calls are:

```powershell
python -m capcut_tts_api.cli list-voices --language vi-VN
python -m capcut_tts_api.cli tts-new --text "Hello" --voice BV421_vivn_streaming
python -m capcut_tts_api.cli tts-srt --srt-file captions.srt --voice BV421_vivn_streaming --part --output-dir voice-parts
python -m capcut_tts_api.cli tts-srt --srt-file captions.srt --voice BV421_vivn_streaming --no-part --audio-out captions.mp3
python -m capcut_tts_api.cli stt-file --audio-file recording.mp3 --language vi-VN --srt-out recording.srt
python -m capcut_tts_api.cli translate --audio-file recording.mp3 --language vi-VN --translation-language en-US --srt-out recording.en.srt
python -m capcut_tts_api.cli tts-query --task-id TASK_ID --token TASK_TOKEN
python -m capcut_tts_api.cli stt-query --task-id TASK_ID --token TASK_TOKEN
python -m capcut_tts_api.cli upload-audio --audio-file recording.mp3
python -m capcut_tts_api.cli stt-new --audio-vid VOD_ID --audio-md5 MD5 --duration-ms 10000 --language vi-VN
```

Common service modes are `list-voices`, `tts-new`, `tts-query`, `tts-srt`, `upload-audio`, `stt-new`, `stt-query`, `stt-file`, and `translate`. `stt-new` needs a previously uploaded `--audio-vid` and `--audio-md5`; `upload-audio` prints those values. Run `python -m capcut_tts_api.cli --help` for the complete mode list and `python -m capcut_tts_api.cli MODE --help` for that mode's arguments. For reusable programs, prefer the Python methods above: they return dictionaries and model objects instead of requiring output parsing.

## Package data and implementation

All package references in this section are inside [`capcut_tts_api/`](capcut_tts_api):

| File | Purpose |
|---|---|
| [`Voice.json`](capcut_tts_api/Voice.json) | Local voice records, display names, service IDs, resource IDs, and language fields. |
| [`language.json`](capcut_tts_api/language.json) | Language records available to the package's catalog helpers. |
| [`client.py`](capcut_tts_api/client.py) | Client construction, TTS/STT requests, polling, downloads, and SRT workflows. |
| [`models.py`](capcut_tts_api/models.py) | `DeviceConfig`, `VoiceInfo`, subtitle, utterance, and word models. |
| [`config.py`](capcut_tts_api/config.py) | Default request origin and device profile. |
| [`signer.py`](capcut_tts_api/signer.py) | Request signing and header helpers used internally by the client. |
| [`uploader.py`](capcut_tts_api/uploader.py) | Media upload flow used before STT. |
| [`exceptions.py`](capcut_tts_api/exceptions.py) | Public exception classes. |
| [`__init__.py`](capcut_tts_api/__init__.py) | Public imports and package version. |

Useful public methods are `list_voices`, `resolve_voice`, `build_tts_new_request`, `create_tts_task`, `generate_speech`, `query_tts_task`, `extract_tts_artifacts`, `download_tts_audio`, `upload_audio`, `build_stt_new_request`, `create_stt_task`, `query_stt_task`, `transcribe_file`, `extract_subtitles`, `write_srt`, `generate_speech_from_srt`, and `generate_speech_and_transcribe`.

<h2 align="center">🔧 TNKRE developer tools</h2>

<div align="center">
  <a href="https://tnkre.dev/"><strong>tnkre.dev</strong></a><br>
  <sub>TNKRE developer tools and resources</sub>
  <br><br>
  <a href="https://decompile.tnkre.dev/"><strong>decompile.tnkre.dev</strong></a><br>
  <sub>Python <code>.pyc</code> decompilation and PyArmor analysis</sub>
</div>

These are external reference services, not package dependencies. Do not upload private source, credentials, or user media without authorization.

## Troubleshooting

- A non-zero API return value is raised as `CapCutAPIError`; inspect its `response_data`.
- If no artifact URL is present, inspect the completed response passed to `extract_tts_artifacts()`; the downloader only uses URL fields returned by the service.
- If a voice is rejected, verify the service ID and account/region availability. `Voice.json` is a local reference.
- If a translated SRT is empty, confirm `use_translation=True` and inspect whether the response contains `translation_text`.

<h2 align="center">📣 Help spread the word</h2>

If you build a tool, tutorial, or project with this package, please consider sharing it with others and mentioning the repository. A star, recommendation, or bit of feedback helps more developers discover the project and supports its continued development.

<p align="center"><a href="https://github.com/K07VN/capcut-tts-api"><strong>Share the repository</strong></a></p>

<h2 align="center">⭐ Star History</h2>

<a href="https://www.star-history.com/?repos=k07vn%2Fcapcut-tts-api&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=k07vn/capcut-tts-api&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=k07vn/capcut-tts-api&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=k07vn/capcut-tts-api&type=date&legend=top-left" />
 </picture>
</a>
