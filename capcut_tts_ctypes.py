import subprocess
import json
import time
import os
import sys
import hashlib
import base64
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding
from config import (
    APP_ID, APP_VR, APP_CHANNEL, DEVICE_ID, IID,
    OS_VERSION, DEVICE_TYPE, DEVICE_PLATFORM,
    VOICE_NAME, VOICE_RESOURCE_ID, VOICE_PLATFORM, VOICE_RATE,
)

DIR = os.path.dirname(os.path.abspath(__file__))
HELPER_BIN = os.path.join(DIR, "cronet_helper")

def check_and_compile():
    HELPER_SRC = os.path.join(DIR, "cronet_helper.cpp")
    if not os.path.exists(HELPER_BIN) or os.path.getmtime(HELPER_SRC) > os.path.getmtime(HELPER_BIN):
        print("[*] Compiling native TTNet bridge...", flush=True)
        cmd = ["clang++", "-O3", "-std=c++17", "-framework", "CoreFoundation", "-framework", "Foundation", HELPER_SRC, "-o", HELPER_BIN]
        subprocess.run(cmd)

def run_request(url, body, sign_hdr, device_time):
    check_and_compile()
    body_str = json.dumps(body)
    cmd = [HELPER_BIN, url, body_str, sign_hdr]
    
    env = os.environ.copy()
    env["DEVICE_TIME"] = str(device_time)
    
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, env=env)
    stdout, stderr = process.communicate()
    if process.returncode != 0:
        return {"error": f"helper returned {process.returncode}", "raw": stdout, "stderr": stderr}
    try:
        return json.loads(stdout.strip())
    except Exception as e:
        return {"error": str(e), "raw": stdout, "stderr": stderr}

# Load the public key
PUB_KEY_PEM = """-----BEGIN PUBLIC KEY-----
MIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAmTd34Lw4b7IuldSXh/zY
CMla+ITdGG5TeWz6ad+OySd4r+IrY45AoqrYUxhQ2dl+7z+i7r/5vEa8rr39BYfB
8AGMQLmZA8HmgpWBsqrn/V6daUALkKnkLb70Fn32CJigIuGXAYqxUdGuI340aC+0
v5Es3puJsHyzf01/AelE4Cdc6bZhQrASJLBh8R3BQToYClmDVSDUQk28o8sl/guA
Z4n303Vj+6Siv1HayPCdV6kpVVnMBAG4+umUbwGmn132N3fgpzLarFF3XyWmS1zh
D/J07iM/rP8GDO9IskHNHd2phrO0G6KzrcFAnTBHjVv+hCBEfzN/no3FNA9AuC36
mwIDAQAB
-----END PUBLIC KEY-----"""

def make_sign(ssml, extra_info=None, device_id=None):
    if device_id is None:
        device_id = DEVICE_ID
    ssml_md5 = hashlib.md5(ssml.encode("utf-8")).hexdigest()
    if extra_info is not None:
        sign_input = f"appid:{APP_ID}&did:{device_id}&creditDisable:false&ssml:{ssml_md5}&extraInfo:{extra_info}"
    else:
        sign_input = f"appid:{APP_ID}&did:{device_id}&creditDisable:false&ssml:{ssml_md5}"
        
    public_key = serialization.load_pem_public_key(PUB_KEY_PEM.encode())
    encrypted = public_key.encrypt(
        sign_input.encode("utf-8"),
        padding.PKCS1v15()
    )
    return base64.b64encode(encrypted).decode("utf-8")

def make_sign_header(url, appvr, device_time, tdid):
    path = url.split("?")[0]
    path_suffix = path[-7:]
    sign_str = f"9e2c|{path_suffix}|3|{appvr}|{device_time}|{tdid}|11ac"
    return hashlib.md5(sign_str.encode()).hexdigest()

COMMON_PARAMS = (
    f"app_name=CapCut&device_type={DEVICE_TYPE}&os_version={OS_VERSION}"
    f"&channel={APP_CHANNEL}&version_name={APP_VR}&device_brand={DEVICE_TYPE}"
    f"&babi_param=%7B%22feature_entrance%22%3A%22editor%22%2C%22feature_entrance_detail%22%3A%22editor-feature-text_to_speech%22%2C%22feature_key%22%3A%22text_to_speech%22%2C%22scenario%22%3A%22video_editor%22%7D"
    f"&device_id={DEVICE_ID}&iid={IID}&region=VN&version_code={APP_VR}"
    f"&device_platform={DEVICE_PLATFORM}&aid={APP_ID}"
)
NEW_URL = f"https://editor-api-sg.capcutapi.com/lv/v1/common_task/new?{COMMON_PARAMS}"
QUERY_URL = f"https://editor-api-sg.capcutapi.com/lv/v1/common_task/query?{COMMON_PARAMS}"

def process_tts(text):
    print("[*] Preparing TTS synthesis payload...", flush=True)
    
    # Format SSML using voice parameters from config.py
    ssml = f'''<speak version="1.0" xmlns="http://www.w3.org/2001/10/synthesis" xml:lang="en-US">
    <voice name="{VOICE_NAME}" mock_tone_info="" platform="{VOICE_PLATFORM}" resource_id="{VOICE_RESOURCE_ID}" emotion="" emotion_scale="0" style="" role="" moyin_emotion="" is_clone_tone="false" need_subtitle_timestamp="true">
        <prosody rate="{VOICE_RATE}">{text}</prosody>
    </voice>
</speak>'''
    
    extra_info = '{"benefit_info":{}}'
    signature = make_sign(ssml, extra_info)
    
    payload_data = {
        "audio_format": "mp3",
        "babi_param": "{\"feature_entrance\":\"editor\",\"feature_entrance_detail\":\"editor-feature-text_to_speech\",\"feature_key\":\"text_to_speech\",\"scenario\":\"video_editor\"}",
        "credit_disable": False,
        "extra_info": extra_info,
        "need_merge_voice": False,
        "need_subtitle_timestamp": True,
        "scene": "text_to_speech",
        "ssml": ssml,
        "sign": signature
    }
    
    body = {
        "bind_id": "a222ac24-65f5-493f-bb03-c020a822cd9c",
        "can_queue": True,
        "enter_from": "text_to_speech",
        "tasks": [{
            "context": "f63d5b45-a60a-461f-b853-30e0ee0a34d0",
            "payload": json.dumps(payload_data, separators=(',', ':')),
            "req_key": "sami_text_to_speech",
            "task_version": "v3"
        }]
    }
    
    print("[*] Creating CapCut TTS task...", flush=True)
    device_time = int(time.time())
    sign_hdr = make_sign_header(NEW_URL, APP_VR, device_time, DEVICE_ID)
    
    res = run_request(NEW_URL, body, sign_hdr, device_time)
    
    if not res or "data" not in res or not res["data"].get("tasks"):
        print("[-] Create task failed:", res, flush=True)
        return
        
    task_id = res["data"]["tasks"][0]["id"]
    print(f"[+] Task created successfully: {task_id}", flush=True)
    
    for i in range(20):
        print(f"[*] Polling task status (attempt {i+1}/20)...", flush=True)
        time.sleep(2)
        q_body = {
            "tasks": [{
                "bind_id": "",
                "id": task_id,
                "req_key": "sami_text_to_speech",
                "task_version": "v3",
                "token": res["data"]["tasks"][0]["token"]
            }]
        }
        
        q_device_time = int(time.time())
        q_sign_hdr = make_sign_header(QUERY_URL, APP_VR, q_device_time, DEVICE_ID)
        
        q_res = run_request(QUERY_URL, q_body, q_sign_hdr, q_device_time)
        
        if not q_res or "data" not in q_res or not q_res["data"].get("tasks"):
            print("  [-] Empty or failed query response:", q_res, flush=True)
            continue
            
        task = q_res["data"]["tasks"][0]
        status = task.get("status")
        print(f"  [*] Status: {status}", flush=True)
        
        if status in ["success", "succeed"]:
            payload_str = task.get("payload", "{}")
            payload = json.loads(payload_str) if isinstance(payload_str, str) else payload_str
            subtitles = payload.get("audio_subtitles", [])
            
            print("\n" + "="*50)
            print("[+] GENERATION SUCCESSFUL!")
            print("="*50)
            if subtitles:
                audio_url = subtitles[0].get("speech_url")
                print("Audio URL:", audio_url)
                
                # Check for subtitles/utterances
                utterances = subtitles[0].get("utterances")
                if utterances:
                    print("\nSubtitles:")
                    for sub in utterances:
                        print(f"  [{sub.get('start_time', 0)}ms -> {sub.get('end_time', 0)}ms] {sub.get('word', '')}")
            else:
                print("No audio subtitles found in payload.")
            print("="*50)
            return
        elif status in ["failed", "error"]:
            print(f"[-] Task failed in engine: {task}", flush=True)
            return
            
    print("[-] Polling timed out.", flush=True)

if __name__ == "__main__":
    if len(sys.argv) > 1:
        text = " ".join(sys.argv[1:])
    else:
        text = "Hello world from pure Python signing script."
    process_tts(text)
