"""
cronet_client.py — Python ctypes wrapper for cronet_helper.dll

Usage (as library):
    from cronet_client import CronetClient
    client = CronetClient(
        dll_path=r"C:\...\sscronet.dll",
        app_id="359289",
        device_id="7531371909913576977",
        app_version="8.7.0",
        channel="capcutpc_0",
        device_platform="windows",
        device_type="pc",
    )
    result = client.run_request("https://...", {"key": "value"}, sign="abc")

Usage (legacy adapter — uses module-level defaults):
    from cronet_client import run_request
    result = run_request("https://...", {"key": "value"})
"""

import ctypes
import json
import os
import subprocess
import sys
import time
import hashlib
from config import (
    SSCRONET_DLL, APP_ID, DEVICE_ID, APP_VR,
    APP_CHANNEL, DEVICE_PLATFORM, DEVICE_TYPE,
)

# ─────────────────────────────────────────────────────────────────────────────
# Paths
# ─────────────────────────────────────────────────────────────────────────────
DIR       = os.path.dirname(os.path.abspath(__file__))
DLL_PATH  = os.path.join(DIR, "cronet_helper.dll")
BUILD_BAT = os.path.join(DIR, "build.bat")


def _ensure_built():
    """Auto-compile cronet_helper.dll if missing."""
    if os.path.exists(DLL_PATH):
        return
    print("[*] cronet_helper.dll not found — building...", flush=True)
    if not os.path.exists(BUILD_BAT):
        raise FileNotFoundError(f"build.bat not found: {BUILD_BAT}")
    result = subprocess.run(["cmd", "/c", BUILD_BAT], cwd=DIR,
                            capture_output=True, text=True)
    sys.stderr.write(result.stdout)
    sys.stderr.write(result.stderr)
    if result.returncode != 0:
        raise RuntimeError(f"Build failed:\n{result.stderr}")
    if not os.path.exists(DLL_PATH):
        raise FileNotFoundError(f"DLL still missing after build: {DLL_PATH}")
    print("[+] Build OK", flush=True)


def _load_raw_dll() -> ctypes.CDLL:
    """Load the DLL and declare function signatures."""
    _ensure_built()
    dll = ctypes.CDLL(DLL_PATH)

    # int init_engine(dll_path, app_id, device_id, app_version,
    #                 channel, device_platform, device_type)
    dll.init_engine.restype  = ctypes.c_int
    dll.init_engine.argtypes = [
        ctypes.c_char_p,  # dll_path
        ctypes.c_char_p,  # app_id
        ctypes.c_char_p,  # device_id
        ctypes.c_char_p,  # app_version
        ctypes.c_char_p,  # channel
        ctypes.c_char_p,  # device_platform
        ctypes.c_char_p,  # device_type
    ]

    # int run_request(url, body_json, sign_header, device_time,
    #                 out_buf, out_buf_size)
    dll.run_request.restype  = ctypes.c_int
    dll.run_request.argtypes = [
        ctypes.c_char_p,  # url
        ctypes.c_char_p,  # body_json
        ctypes.c_char_p,  # sign_header
        ctypes.c_int64,   # device_time
        ctypes.c_char_p,  # out_buf
        ctypes.c_int,     # out_buf_size
    ]
    return dll


# ─────────────────────────────────────────────────────────────────────────────
# CronetClient
# ─────────────────────────────────────────────────────────────────────────────

class CronetClient:
    """
    Manages a single Cronet engine instance inside cronet_helper.dll.

    Parameters
    ----------
    sscronet_dll  : Full path to sscronet.dll (CapCut's Cronet library).
    app_id        : CapCut app ID, e.g. "359289".
    device_id     : Numeric device ID string.
    app_version   : App version string, e.g. "8.7.0".
    channel       : Distribution channel, e.g. "capcutpc_0".
    device_platform : "windows" / "mac" / "android" / "ios".
    device_type   : "pc" / "MacBookPro17,1" / etc.
    """

    def __init__(
        self,
        sscronet_dll: str,
        app_id: str       = "359289",
        device_id: str    = "",
        app_version: str  = "8.7.0",
        channel: str      = "capcutpc_0",
        device_platform: str = "windows",
        device_type: str  = "pc",
    ):
        self.app_id          = app_id
        self.device_id       = device_id
        self.app_version     = app_version
        self.channel         = channel
        self.device_platform = device_platform
        self.device_type     = device_type

        # Add sscronet.dll directory to PATH so Windows can find it
        dll_dir = os.path.dirname(os.path.abspath(sscronet_dll))
        if dll_dir not in os.environ.get("PATH", ""):
            os.environ["PATH"] = dll_dir + os.pathsep + os.environ.get("PATH", "")

        self._dll = _load_raw_dll()

        ret = self._dll.init_engine(
            sscronet_dll.encode(),
            app_id.encode(),
            device_id.encode(),
            app_version.encode(),
            channel.encode(),
            device_platform.encode(),
            device_type.encode(),
        )
        if ret != 0:
            raise RuntimeError(f"init_engine() failed with code {ret}")

    # ── signing ───────────────────────────────────────────────────────────────

    def make_sign_header(self, url: str, device_time: int) -> str:
        path        = url.split("?")[0]
        path_suffix = path[-7:]
        sign_str    = f"9e2c|{path_suffix}|3|{self.app_version}|{device_time}|{self.device_id}|11ac"
        return hashlib.md5(sign_str.encode()).hexdigest()

    # ── request ───────────────────────────────────────────────────────────────

    def run_request(
        self,
        url: str,
        body,
        sign: str  = "",
        device_time: int = 0,
        buf_size: int    = 4 * 1024 * 1024,
    ) -> dict:
        """
        Send a POST request through CapCut's Cronet engine.

        Parameters
        ----------
        url         : Full URL with query string.
        body        : dict (JSON-serialised) or raw str.
        sign        : Sign header value. Auto-computed if empty.
        device_time : Unix timestamp. 0 = current time.
        buf_size    : Response buffer size (default 4 MB).

        Returns parsed JSON dict.
        """
        if device_time <= 0:
            device_time = int(time.time())

        body_str = json.dumps(body, separators=(",", ":")) \
                   if isinstance(body, dict) else str(body)

        if not sign:
            sign = self.make_sign_header(url, device_time)

        out_buf = ctypes.create_string_buffer(buf_size)

        status = self._dll.run_request(
            url.encode("utf-8"),
            body_str.encode("utf-8"),
            sign.encode("utf-8"),
            ctypes.c_int64(device_time),
            out_buf,
            ctypes.c_int(buf_size),
        )

        raw = out_buf.value.decode("utf-8", errors="replace").strip()

        if status < 0:
            raise RuntimeError(
                f"run_request error code {status}. Body: {raw[:300]}"
            )
        if not raw:
            raise RuntimeError(f"HTTP {status} but empty body")

        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            raise RuntimeError(
                f"Invalid JSON (HTTP {status}): {raw[:300]}"
            ) from e


# ─────────────────────────────────────────────────────────────────────────────
# Module-level default client (legacy compatibility)
# capcut_tts_ctypes.py imports: from cronet_client import run_request
# ─────────────────────────────────────────────────────────────────────────────

# Default config — override by calling init_default() before first use
_DEFAULT_CONFIG = {
    "sscronet_dll":    SSCRONET_DLL,
    "app_id":          APP_ID,
    "device_id":       DEVICE_ID,
    "app_version":     APP_VR,
    "channel":         APP_CHANNEL,
    "device_platform": DEVICE_PLATFORM,
    "device_type":     DEVICE_TYPE,
}

_default_client: "CronetClient | None" = None


def init_default(**kwargs):
    """Override default config and (re)initialize the default client."""
    global _default_client
    _DEFAULT_CONFIG.update(kwargs)
    _default_client = None  # force re-init on next use


def _get_default_client() -> CronetClient:
    global _default_client
    if _default_client is None:
        _default_client = CronetClient(**_DEFAULT_CONFIG)
    return _default_client


def make_sign_header(url: str, device_time: int) -> str:
    return _get_default_client().make_sign_header(url, device_time)


def run_request(
    url: str,
    body,
    sign: str  = "",
    device_time: int = 0,
    buf_size: int    = 4 * 1024 * 1024,
) -> dict:
    """Module-level convenience wrapper using the default client."""
    return _get_default_client().run_request(
        url, body, sign=sign, device_time=device_time, buf_size=buf_size
    )


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(f"Usage: python {sys.argv[0]} <url> <body_json> [sign]")
        sys.exit(1)

    _url  = sys.argv[1]
    _body = sys.argv[2]
    _sign = sys.argv[3] if len(sys.argv) > 3 else ""

    result = run_request(_url, _body, sign=_sign)
    print(json.dumps(result, ensure_ascii=False, indent=2))
