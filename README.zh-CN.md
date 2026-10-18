<p align="center"><a href="README.md">English</a> · <a href="README.vi.md">Tiếng Việt</a> · <strong>简体中文</strong></p>

<h1 align="center">CapCut TTS &amp; STT API</h1>
<p align="center"><strong>用于 CapCut 语音任务的 Python SDK</strong></p>
<p align="center">文字转语音 · 语音识别 · 翻译 · SRT · 语音目录</p>

---

## 功能

`capcut-tts-api` 为模块中已有的语音流程提供 Python client：

- 创建并查询 TTS 任务，然后下载服务返回的音频 artifact；
- 上传本地音频或视频，提交 STT，并解析句子和单词时间轴；
- 在 STT 中请求翻译，把返回的翻译文本写入 SRT；
- 读取 SRT，为每个字幕块生成音频，或生成一个合并音频；
- 读取 `capcut_tts_api` 内置的语音和语言数据。

下面的示例直接调用 Python API，不依赖命令行解析器。

## 安装

需要 Python 3.9 或更高版本：

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e .
```

## Python 用法

### 1. 创建 client 并查看语音

```python
from capcut_tts_api import CapCutClient

client = CapCutClient(timeout=60)

# VoiceInfo 从 capcut_tts_api/Voice.json 读取。
for voice in client.list_voices(lang="vi-VN")[:5]:
    print(voice.voice_type, voice.display_name, voice.resource_id)

# 可以传入 voice_type、显示名称或 resource ID。
voice_type, resource_id = client.resolve_voice("BV421_vivn_streaming")
print(voice_type, resource_id)
```

`list_voices()` 只读取本地目录，不发送请求。目录可能过期，最终可用性仍由服务和账号决定。

### 2. 生成语音并保存 artifact

```python
from capcut_tts_api import CapCutClient

client = CapCutClient(timeout=60)
result = client.generate_speech(
    "来自 Python API 的问候。",
    voice="BV421_vivn_streaming",
    timeout=180,
)
audio_path = client.download_tts_audio(result, "hello.mp3")
print(f"已保存 {audio_path}")
```

`generate_speech()` 默认等待任务完成。使用 `wait=False` 可自行查询：

```python
created = client.generate_speech("排队中的任务", voice="BV421_vivn_streaming", wait=False)
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
        raise RuntimeError(f"TTS 任务失败：{completed}")
    time.sleep(1)
else:
    raise TimeoutError("TTS 任务未能在期限内完成")

audio_path = client.download_tts_audio(completed, "queued-task.mp3")
print(status, audio_path)
```

实际程序应重复查询直到任务成功。`download_tts_audio()` 接受已完成的 response，并写入服务返回的 artifact URL。

### 3. 转写文件并写入源语言 SRT

```python
from capcut_tts_api import CapCutClient

client = CapCutClient(timeout=60)
stt = client.transcribe_file("recording.mp3", language="vi-VN", timeout=180)
subtitles = client.extract_subtitles(stt)
subtitles.write_srt("recording.vi.srt")
print(subtitles.full_text)
```

`transcribe_file()` 会上传媒体、创建 STT 任务、查询完成并返回 response。传入 `wait=False` 可以只返回创建结果。

### 4. 请求翻译并写入翻译 SRT

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

翻译文本来自完成 response 的 `translation_text`。服务没有返回该字段时，SDK 不会自行生成翻译。

### 5. 从 SRT 生成语音

```python
# 每个非空字幕块下载一个 artifact。
parts = client.generate_speech_from_srt(
    "captions.srt",
    voice="BV421_vivn_streaming",
    output_dir="voice-parts",
    part=True,
)
print(parts["cues"])

# 一次请求并下载一个包含全部字幕文本的 artifact。
combined = client.generate_speech_from_srt(
    "captions.srt",
    voice="BV421_vivn_streaming",
    audio_path="captions.mp3",
    part=False,
)
print(combined["audio_path"])
```

字幕块的起止时间会保存在返回 metadata 中；method 不会修改原始 SRT 的时间轴。

### 6. 生成语音后转写同一个文件

```python
result = client.generate_speech_and_transcribe(
    "来自 CapCut 的问候。",
    voice="BV421_vivn_streaming",
    audio_path="roundtrip.mp3",
    srt_path="roundtrip.srt",
    language="zh-CN",
)
print(result["audio_path"], result["srt_path"])
```

### 异常处理

```python
from capcut_tts_api import CapCutAPIError, CapCutError, CapCutTaskError

try:
    client.generate_speech("test", voice="BV421_vivn_streaming", timeout=180)
except CapCutTaskError as exc:
    print(f"任务失败或超时：{exc}")
except CapCutAPIError as exc:
    print(f"服务错误：{exc}")
except CapCutError as exc:
    print(f"客户端错误：{exc}")
```

## API 参考与任务查询

高级方法适合大多数程序。需要保存任务 ID 并稍后查询时，可使用下面的底层调用。

```python
from capcut_tts_api import CapCutClient

client = CapCutClient(timeout=60)

# 创建 TTS 任务，并由调用方管理查询。
created = client.create_tts_task(
    ["第一段", "第二段"],
    voice="BV421_vivn_streaming",
)
task = created["data"]["tasks"][0]

# 稍后调用；任务排队或运行时重复调用。
tts_result = client.query_tts_task(
    task_id=task["id"],
    token=task["token"],
    bind_id=task.get("bind_id", ""),
)
print(tts_result)

# 下载前先读取 artifact 元数据。
for artifact in client.extract_tts_artifacts(tts_result):
    print(artifact)
```

STT worker 可以分开上传和查询：

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

需要在发送前查看或记录请求时，可以使用 request builder：

```python
url, headers, body = client.build_tts_new_request(
    "仅预览", voice="BV421_vivn_streaming"
)
print(url, headers, body)

stt_url, stt_headers, stt_body = client.build_stt_new_request(
    audio_vid="uploaded-vid",
    audio_md5="uploaded-md5",
    duration_ms=10_000,
    language="vi-VN",
)
```

`create_tts_task()` 和 `create_stt_task()` 会发送请求；`build_*` 只返回请求数据。`upload_audio()` 上传媒体并返回包含 `vid`、`md5`、时长、大小和格式的 `UploadResult`。

## 可选命令行用法

也可以通过 `capcut-tts-api` 或 `python -m capcut_tts_api.cli` 使用 CLI。运行 `--help` 查看当前安装版本的模式和参数：

```powershell
python -m capcut_tts_api.cli list-voices --language vi-VN
python -m capcut_tts_api.cli tts-new --text "你好" --voice BV421_vivn_streaming
python -m capcut_tts_api.cli tts-srt --srt-file captions.srt --voice BV421_vivn_streaming --part --output-dir voice-parts
python -m capcut_tts_api.cli tts-srt --srt-file captions.srt --voice BV421_vivn_streaming --no-part --audio-out captions.mp3
python -m capcut_tts_api.cli stt-file --audio-file recording.mp3 --language vi-VN --srt-out recording.srt
python -m capcut_tts_api.cli translate --audio-file recording.mp3 --language vi-VN --translation-language en-US --srt-out recording.en.srt
python -m capcut_tts_api.cli tts-query --task-id TASK_ID --token TASK_TOKEN
python -m capcut_tts_api.cli stt-query --task-id TASK_ID --token TASK_TOKEN
python -m capcut_tts_api.cli upload-audio --audio-file recording.mp3
python -m capcut_tts_api.cli stt-new --audio-vid VOD_ID --audio-md5 MD5 --duration-ms 10000 --language vi-VN
```

常见服务模式有 `list-voices`、`tts-new`、`tts-query`、`tts-srt`、`upload-audio`、`stt-new`、`stt-query`、`stt-file` 和 `translate`。`stt-new` 需要之前上传得到的 `--audio-vid` 和 `--audio-md5`；`upload-audio` 会打印这两个值。运行 `python -m capcut_tts_api.cli --help` 查看完整模式列表，运行 `python -m capcut_tts_api.cli MODE --help` 查看对应参数。编写可复用程序时，建议直接调用 Python API，以获得 dictionary 和 model 对象。

## 模块中的数据和实现

本节所有路径都在 [`capcut_tts_api/`](capcut_tts_api) 内：

| 文件 | 内容 |
|---|---|
| [`Voice.json`](capcut_tts_api/Voice.json) | 语音记录、显示名称、service ID、resource ID 和语言字段。 |
| [`language.json`](capcut_tts_api/language.json) | 打包的语言记录。 |
| [`client.py`](capcut_tts_api/client.py) | TTS/STT 请求、查询、下载和 SRT 流程。 |
| [`models.py`](capcut_tts_api/models.py) | `DeviceConfig`、`VoiceInfo`、subtitle、utterance、word。 |
| [`config.py`](capcut_tts_api/config.py) | 默认请求 origin 和设备配置。 |
| [`signer.py`](capcut_tts_api/signer.py) | 内部请求签名和 header helper。 |
| [`uploader.py`](capcut_tts_api/uploader.py) | STT 前使用的媒体上传流程。 |
| [`exceptions.py`](capcut_tts_api/exceptions.py) | 公共异常类。 |
| [`__init__.py`](capcut_tts_api/__init__.py) | 公共导入和 package 版本。 |

主要方法包括 `list_voices`、`resolve_voice`、`build_tts_new_request`、`create_tts_task`、`generate_speech`、`query_tts_task`、`extract_tts_artifacts`、`download_tts_audio`、`upload_audio`、`build_stt_new_request`、`create_stt_task`、`query_stt_task`、`transcribe_file`、`extract_subtitles`、`write_srt`、`generate_speech_from_srt` 和 `generate_speech_and_transcribe`。

<h2 align="center">🔧 TNKRE 开发工具</h2>

<div align="center">
  <a href="https://tnkre.dev/"><strong>tnkre.dev</strong></a><br>
  <sub>TNKRE 开发工具与资源</sub>
  <br><br>
  <a href="https://decompile.tnkre.dev/"><strong>decompile.tnkre.dev</strong></a><br>
  <sub>Python <code>.pyc</code> 反编译与 PyArmor 分析</sub>
</div>

这些是外部参考服务，不是 package 依赖。未经授权不要上传私有源码、凭据或用户媒体。

## 故障排查

- 非零 API 返回值会抛出 `CapCutAPIError`，可查看 `response_data`。
- 没有 artifact URL 时，检查传给 `extract_tts_artifacts()` 的完成 response。
- 语音被拒绝时，检查 service ID 及账号/地区权限；`Voice.json` 只是本地目录。
- 翻译 SRT 为空时，确认 `use_translation=True` 并检查 response 是否含 `translation_text`。

<h2 align="center">📣 帮助分享项目</h2>

如果你用这个 package 制作了工具、教程或其他项目，欢迎在觉得有帮助时分享给更多人并推荐本仓库。点个 star、分享推荐或留下反馈，都能让更多开发者发现这个项目，并支持它持续改进。

<p align="center"><a href="https://github.com/K07VN/capcut-tts-api"><strong>分享仓库</strong></a></p>

<h2 align="center">⭐ Star History</h2>

<a href="https://www.star-history.com/?repos=k07vn%2Fcapcut-tts-api&type=date&legend=top-left">
 <picture>
   <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/chart?repos=k07vn/capcut-tts-api&type=date&theme=dark&legend=top-left" />
   <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/chart?repos=k07vn/capcut-tts-api&type=date&legend=top-left" />
   <img alt="Star History Chart" src="https://api.star-history.com/chart?repos=k07vn/capcut-tts-api&type=date&legend=top-left" />
 </picture>
</a>
