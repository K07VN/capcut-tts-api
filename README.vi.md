<p align="center"><a href="README.md">English</a> · <strong>Tiếng Việt</strong> · <a href="README.zh-CN.md">简体中文</a></p>

<h1 align="center">CapCut TTS &amp; STT API</h1>
<p align="center"><strong>SDK Python cho các tác vụ giọng nói CapCut</strong></p>
<p align="center">Text to speech · Nhận dạng tiếng nói · Dịch · SRT · Catalog voice</p>

---

## Chức năng

`capcut-tts-api` cung cấp client Python cho các luồng có trong module:

- tạo và theo dõi task TTS, sau đó tải artifact audio mà dịch vụ trả về;
- upload audio/video, gửi STT và parse timing của câu và từ;
- bật dịch trong STT rồi ghi phần dịch trả về thành SRT;
- đọc SRT để tạo một file audio cho mỗi cue hoặc một file gộp;
- đọc catalog voice và ngôn ngữ nằm trong `capcut_tts_api`.

Ví dụ bên dưới gọi trực tiếp Python API, không phụ thuộc parser dòng lệnh.

## Cài đặt

Yêu cầu Python 3.9 trở lên:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Sử dụng bằng Python

### 1. Tạo client và xem voice

```python
from capcut_tts_api import CapCutClient

client = CapCutClient(timeout=60)

# VoiceInfo được đọc từ capcut_tts_api/Voice.json.
for voice in client.list_voices(lang="vi-VN")[:5]:
    print(voice.voice_type, voice.display_name, voice.resource_id)

# Có thể truyền voice_type, tên hiển thị hoặc resource ID.
voice_type, resource_id = client.resolve_voice("BV421_vivn_streaming")
print(voice_type, resource_id)
```

`list_voices()` chỉ đọc catalog cục bộ. Catalog có thể cũ; quyền dùng voice vẫn do dịch vụ và tài khoản quyết định.

### 2. Tạo giọng nói và lưu artifact

```python
from capcut_tts_api import CapCutClient

client = CapCutClient(timeout=60)
result = client.generate_speech(
    "Xin chào từ Python API.",
    voice="BV421_vivn_streaming",
    timeout=180,
)
audio_path = client.download_tts_audio(result, "hello.mp3")
print(f"đã lưu {audio_path}")
```

Mặc định `generate_speech()` chờ task hoàn tất. Dùng `wait=False` nếu muốn tự theo dõi:

```python
created = client.generate_speech("Task đang chờ", voice="BV421_vivn_streaming", wait=False)
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
        raise RuntimeError(f"TTS task lỗi: {completed}")
    time.sleep(1)
else:
    raise TimeoutError("TTS task chưa hoàn thành trong thời hạn")

audio_path = client.download_tts_audio(completed, "queued-task.mp3")
print(status, audio_path)
```

Thực tế cần gọi query lặp lại cho tới khi task thành công. `download_tts_audio()` nhận response đã hoàn tất và ghi URL artifact do dịch vụ trả về.

### 3. Nhận dạng file và ghi SRT ngôn ngữ gốc

```python
from capcut_tts_api import CapCutClient

client = CapCutClient(timeout=60)
stt = client.transcribe_file("recording.mp3", language="vi-VN", timeout=180)
subtitles = client.extract_subtitles(stt)
subtitles.write_srt("recording.vi.srt")
print(subtitles.full_text)
```

`transcribe_file()` upload file, tạo task STT, poll và trả response hoàn tất. Có thể truyền `wait=False` để nhận response tạo task.

### 4. Dịch và ghi SRT đã dịch

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

Phần dịch được lấy từ `translation_text` trong response. Nếu dịch vụ không trả trường này, SDK không tự tạo bản dịch.

### 5. Tạo voice từ file SRT

```python
# Một artifact cho từng cue không rỗng.
parts = client.generate_speech_from_srt(
    "captions.srt",
    voice="BV421_vivn_streaming",
    output_dir="voice-parts",
    part=True,
)
print(parts["cues"])

# Một request và một artifact chứa toàn bộ text.
combined = client.generate_speech_from_srt(
    "captions.srt",
    voice="BV421_vivn_streaming",
    audio_path="captions.mp3",
    part=False,
)
print(combined["audio_path"])
```

Thời gian bắt đầu/kết thúc của cue được giữ trong metadata trả về; method không tự sửa timing SRT.

### 6. Tạo voice rồi nhận dạng lại file đó

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

### Bắt lỗi

```python
from capcut_tts_api import CapCutAPIError, CapCutError, CapCutTaskError

try:
    client.generate_speech("test", voice="BV421_vivn_streaming", timeout=180)
except CapCutTaskError as exc:
    print(f"task lỗi hoặc hết thời gian: {exc}")
except CapCutAPIError as exc:
    print(f"dịch vụ trả lỗi: {exc}")
except CapCutError as exc:
    print(f"lỗi client: {exc}")
```

## Tra cứu API và task

Các hàm cấp cao phù hợp với hầu hết chương trình. Dùng các hàm dưới đây khi muốn lưu task ID rồi poll ở một thời điểm khác.

```python
from capcut_tts_api import CapCutClient

client = CapCutClient(timeout=60)

# Tạo task TTS và tự quản lý việc poll.
created = client.create_tts_task(
    ["Câu thứ nhất", "Câu thứ hai"],
    voice="BV421_vivn_streaming",
)
task = created["data"]["tasks"][0]

# Gọi sau đó và lặp lại khi task còn đang chờ/chạy.
tts_result = client.query_tts_task(
    task_id=task["id"],
    token=task["token"],
    bind_id=task.get("bind_id", ""),
)
print(tts_result)

# Xem metadata artifact trước khi tải artifact cần dùng.
for artifact in client.extract_tts_artifacts(tts_result):
    print(artifact)
```

Với worker STT, có thể upload và truy vấn riêng:

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

Request builder giúp xem hoặc ghi log request trước khi gửi:

```python
url, headers, body = client.build_tts_new_request(
    "Chỉ xem trước", voice="BV421_vivn_streaming"
)
print(url, headers, body)

stt_url, stt_headers, stt_body = client.build_stt_new_request(
    audio_vid="uploaded-vid",
    audio_md5="uploaded-md5",
    duration_ms=10_000,
    language="vi-VN",
)
```

`create_tts_task()` và `create_stt_task()` gửi request; `build_*` chỉ trả dữ liệu request. `upload_audio()` tải media lên và trả `UploadResult` gồm `vid`, `md5`, thời lượng, dung lượng và định dạng.

## CLI tùy chọn

CLI có sẵn qua `capcut-tts-api` hoặc `python -m capcut_tts_api.cli`. Chạy `--help` để xem mode của phiên bản đã cài:

```powershell
python -m capcut_tts_api.cli list-voices --language vi-VN
python -m capcut_tts_api.cli tts-new --text "Xin chào" --voice BV421_vivn_streaming
python -m capcut_tts_api.cli tts-srt --srt-file captions.srt --voice BV421_vivn_streaming --part --output-dir voice-parts
python -m capcut_tts_api.cli tts-srt --srt-file captions.srt --voice BV421_vivn_streaming --no-part --audio-out captions.mp3
python -m capcut_tts_api.cli stt-file --audio-file recording.mp3 --language vi-VN --srt-out recording.srt
python -m capcut_tts_api.cli translate --audio-file recording.mp3 --language vi-VN --translation-language en-US --srt-out recording.en.srt
python -m capcut_tts_api.cli tts-query --task-id TASK_ID --token TASK_TOKEN
python -m capcut_tts_api.cli stt-query --task-id TASK_ID --token TASK_TOKEN
python -m capcut_tts_api.cli upload-audio --audio-file recording.mp3
python -m capcut_tts_api.cli stt-new --audio-vid VOD_ID --audio-md5 MD5 --duration-ms 10000 --language vi-VN
```

Các mode dịch vụ gồm `list-voices`, `tts-new`, `tts-query`, `tts-srt`, `upload-audio`, `stt-new`, `stt-query`, `stt-file` và `translate`. `stt-new` cần `--audio-vid` và `--audio-md5` từ lần upload trước; `upload-audio` in ra hai giá trị này. Chạy `python -m capcut_tts_api.cli --help` để xem toàn bộ mode và `python -m capcut_tts_api.cli MODE --help` để xem tham số từng mode. Chương trình cần tái sử dụng nên gọi Python API để nhận dictionary và model trực tiếp.

## Dữ liệu và mã nguồn trong module

Tất cả đường dẫn trong mục này đều nằm trong [`capcut_tts_api/`](capcut_tts_api):

| File | Nội dung |
|---|---|
| [`Voice.json`](capcut_tts_api/Voice.json) | Voice, tên hiển thị, service ID, resource ID và mã ngôn ngữ. |
| [`language.json`](capcut_tts_api/language.json) | Bản ghi ngôn ngữ được đóng gói. |
| [`client.py`](capcut_tts_api/client.py) | Tạo request TTS/STT, poll, tải artifact và xử lý SRT. |
| [`models.py`](capcut_tts_api/models.py) | `DeviceConfig`, `VoiceInfo`, subtitle, utterance và word. |
| [`config.py`](capcut_tts_api/config.py) | Origin mặc định và profile thiết bị. |
| [`signer.py`](capcut_tts_api/signer.py) | Helper ký request và tạo header nội bộ. |
| [`uploader.py`](capcut_tts_api/uploader.py) | Luồng upload media trước STT. |
| [`exceptions.py`](capcut_tts_api/exceptions.py) | Các exception công khai. |
| [`__init__.py`](capcut_tts_api/__init__.py) | Import công khai và version package. |

Method chính: `list_voices`, `resolve_voice`, `build_tts_new_request`, `create_tts_task`, `generate_speech`, `query_tts_task`, `extract_tts_artifacts`, `download_tts_audio`, `upload_audio`, `build_stt_new_request`, `create_stt_task`, `query_stt_task`, `transcribe_file`, `extract_subtitles`, `write_srt`, `generate_speech_from_srt`, `generate_speech_and_transcribe`.

<h2 align="center">🔧 Công cụ phát triển TNKRE</h2>

<div align="center">
  <a href="https://tnkre.dev/"><strong>tnkre.dev</strong></a><br>
  <sub>Công cụ và tài nguyên phát triển của TNKRE</sub>
  <br><br>
  <a href="https://decompile.tnkre.dev/"><strong>decompile.tnkre.dev</strong></a><br>
  <sub>Decompile Python <code>.pyc</code> và phân tích PyArmor</sub>
</div>

Đây là các dịch vụ tham khảo bên ngoài, không phải dependency của package. Không tải source riêng tư, credential hoặc media người dùng lên nếu chưa được phép.

## Xử lý lỗi

- API trả mã lỗi khác không sẽ raise `CapCutAPIError`; xem `response_data`.
- Nếu thiếu URL artifact, kiểm tra response hoàn tất đưa vào `extract_tts_artifacts()`.
- Nếu voice bị từ chối, kiểm tra service ID và quyền tài khoản/khu vực; `Voice.json` chỉ là catalog cục bộ.
- Nếu SRT dịch rỗng, kiểm tra `use_translation=True` và trường `translation_text` trong response.

<h2 align="center">📣 Cùng chia sẻ dự án</h2>

Nếu bạn dùng package này để làm tool, viết hướng dẫn hoặc xây dựng dự án, hãy giới thiệu repo cho mọi người nếu thấy hữu ích. Một lượt star, lời giới thiệu hoặc góp ý của bạn sẽ giúp thêm nhiều developer biết đến dự án và góp phần duy trì package.

<p align="center"><a href="https://github.com/K07VN/capcut-tts-api"><strong>Chia sẻ repository</strong></a></p>

<h2 align="center">⭐ Star History</h2>

<a href="https://www.star-history.com/?repos=k07vn%2Fcapcut-tts-api&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=k07vn/capcut-tts-api&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=k07vn/capcut-tts-api&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=k07vn/capcut-tts-api&type=date&legend=top-left" />
 </picture>
</a>
