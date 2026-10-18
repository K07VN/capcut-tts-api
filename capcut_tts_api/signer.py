"""Pure-Python hashing and VOD signing helpers.

The TTS payload signature algorithm is not implemented here because the
reverse-engineering evidence does not establish its key material or details.
"""

import base64
import binascii
import datetime as dt
import hashlib
import hmac
import json
import secrets
import time
import uuid
from typing import Any, Dict, Optional, Tuple, Union
from urllib.parse import parse_qsl, quote, urlsplit

from capcut_tts_api.config import TTS_SIGN_PUBLIC_KEY_PEM, VOD_REGION, VOD_SERVICE
from capcut_tts_api.exceptions import CapCutSignError


def compact_json(obj: Any) -> str:
    """Format python object into compact JSON string (no whitespace between separators)."""
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def make_x_ss_stub(body_text: str) -> str:
    """Generate x-ss-stub header value (MD5 of request body)."""
    return hashlib.md5(body_text.encode("utf-8")).hexdigest()


def make_trace_id() -> str:
    """Generate unique W3C trace parent header ID."""
    seed = uuid.uuid4().hex[:32]
    return f"00-{seed}-{seed[:16]}-01"


def escape_xml(text: str) -> str:
    """Escape special XML characters for SSML generation."""
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _der_len(data: bytes, pos: int) -> Tuple[int, int]:
    first = data[pos]
    pos += 1
    if first < 0x80:
        return first, pos
    nbytes = first & 0x7F
    return int.from_bytes(data[pos : pos + nbytes], "big"), pos + nbytes


def _der_value(data: bytes, pos: int, tag: int) -> Tuple[bytes, int]:
    if data[pos] != tag:
        raise CapCutSignError(f"Bad DER tag: expected 0x{tag:02x}, got 0x{data[pos]:02x}")
    length, pos = _der_len(data, pos + 1)
    return data[pos : pos + length], pos + length


def _der_int(data: bytes, pos: int) -> Tuple[int, int]:
    raw, pos = _der_value(data, pos, 0x02)
    return int.from_bytes(raw.lstrip(b"\x00"), "big"), pos


def rsa_public_numbers_from_pem(pem: str) -> Tuple[int, int]:
    """Parse RSA modulus and exponent numbers from PEM formatted public key."""
    try:
        b64 = "".join(line for line in pem.splitlines() if not line.startswith("-----"))
        der = base64.b64decode(b64)
        outer, pos = _der_value(der, 0, 0x30)
        if pos != len(der):
            raise CapCutSignError("Trailing data in public key")
        _, pos = _der_value(outer, 0, 0x30)  # AlgorithmIdentifier
        bit_string, pos = _der_value(outer, pos, 0x03)
        if pos != len(outer) or not bit_string or bit_string[0] != 0:
            raise CapCutSignError("Bad subjectPublicKeyInfo")
        rsa_seq, pos = _der_value(bit_string[1:], 0, 0x30)
        if pos != len(bit_string[1:]):
            raise CapCutSignError("Trailing data in RSA public key")
        modulus, pos = _der_int(rsa_seq, 0)
        exponent, pos = _der_int(rsa_seq, pos)
        if pos != len(rsa_seq):
            raise CapCutSignError("Trailing integer data in RSA public key")
        return modulus, exponent
    except Exception as exc:
        if isinstance(exc, CapCutSignError):
            raise
        raise CapCutSignError(f"Failed to parse RSA PEM public key: {exc}") from exc


def rsa_encrypt_pkcs1v15(message: Union[str, bytes], pem: str) -> str:
    """
    Encrypt message using RSA PKCS#1 v1.5 with standard library cryptography logic.
    Returns Base64 encoded ciphertext. RSA public-key encryption is not a
    digital signature and this generic helper is not used for TTS signing.
    """
    modulus, exponent = rsa_public_numbers_from_pem(pem)
    key_len = (modulus.bit_length() + 7) // 8
    msg = message.encode("utf-8") if isinstance(message, str) else bytes(message)
    if len(msg) > key_len - 11:
        raise CapCutSignError("Message too long for RSA PKCS#1 v1.5 padding")
    ps_len = key_len - len(msg) - 3
    ps = bytearray()
    while len(ps) < ps_len:
        chunk = secrets.token_bytes(ps_len - len(ps))
        ps.extend(b for b in chunk if b != 0)
    encoded = b"\x00\x02" + bytes(ps[:ps_len]) + b"\x00" + msg
    encrypted = pow(int.from_bytes(encoded, "big"), exponent, modulus).to_bytes(key_len, "big")
    return base64.b64encode(encrypted).decode("ascii")


def make_tts_payload_sign(
    ssml: str,
    extra_info: Optional[str],
    device_id: str,
    app_id: str,
    *,
    pem: str = TTS_SIGN_PUBLIC_KEY_PEM,
) -> str:
    """Build the legacy RSA payload value used by older package versions.

    Retained for compatibility and explicit opt-in. The recovered 9.6 native
    code calls a build_sign stage and uses fields such as did,
    creditDisable, ssml and extraInfo, but current evidence does not prove RSA
    PKCS#1 v1.5 (or this public key) is the production algorithm. The client
    never calls this helper automatically.
    """
    ssml_md5 = hashlib.md5(ssml.encode("utf-8")).hexdigest()
    sign_input = f"appid:{app_id}&did:{device_id}&creditDisable:false&ssml:{ssml_md5}"
    if extra_info is not None:
        sign_input += f"&extraInfo:{extra_info}"
    return rsa_encrypt_pkcs1v15(sign_input, pem=pem)


def make_sign_header(url: str, appvr: str, device_time: str, tdid: str) -> str:
    """Return a candidate HTTP sign header used by this client implementation.

    This formula is confirmed for the working common-task compatibility route.
    """
    path = url.split("?", 1)[0]
    sign_str = f"9e2c|{path[-7:]}|3|{appvr}|{device_time}|{tdid}|11ac"
    return hashlib.md5(sign_str.encode("utf-8")).hexdigest()


def sha256_hex(data: Union[str, bytes]) -> str:
    """SHA-256 hex digest helper."""
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def hmac_sha256(key: Union[str, bytes], msg: Union[str, bytes]) -> bytes:
    """HMAC-SHA256 digest helper."""
    if isinstance(key, str):
        key = key.encode("utf-8")
    if isinstance(msg, str):
        msg = msg.encode("utf-8")
    return hmac.new(key, msg, hashlib.sha256).digest()


def aws4_signing_key(
    secret_access_key: str, date_stamp: str, region: str = VOD_REGION, service: str = VOD_SERVICE
) -> bytes:
    """Derive AWS SigV4 signing key."""
    k_date = hmac_sha256("AWS4" + secret_access_key, date_stamp)
    k_region = hmac_sha256(k_date, region)
    k_service = hmac_sha256(k_region, service)
    return hmac_sha256(k_service, "aws4_request")


def canonical_query(url: str) -> str:
    """Build canonical query string for AWS SigV4."""
    pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True)
    return "&".join(
        quote(str(k), safe="-_.~") + "=" + quote(str(v), safe="-_.~") for k, v in sorted(pairs)
    )


def aws4_authorization(
    method: str,
    url: str,
    body: bytes,
    access_key_id: str,
    secret_access_key: str,
    session_token: str,
    amz_date: str,
) -> str:
    """Build AWS SigV4 Authorization header string for VOD services."""
    date_stamp = amz_date[:8]
    scope = f"{date_stamp}/{VOD_REGION}/{VOD_SERVICE}/aws4_request"
    signed_headers = "x-amz-date;x-amz-security-token"
    canonical_headers = f"x-amz-date:{amz_date}\nx-amz-security-token:{session_token}\n"
    canonical_request = "\n".join(
        [method, urlsplit(url).path, canonical_query(url), canonical_headers, signed_headers, sha256_hex(body)]
    )
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, sha256_hex(canonical_request)]
    )
    signature = hmac.new(
        aws4_signing_key(secret_access_key, date_stamp), string_to_sign.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return f"AWS4-HMAC-SHA256 Credential={access_key_id}/{scope}, SignedHeaders={signed_headers}, Signature={signature}"


def utc_now_for_vod() -> Tuple[str, str]:
    """Return formatted ISO ISO8601 basic string and HTTP GMT date string for VOD headers."""
    now = dt.datetime.now(dt.timezone.utc)
    return now.strftime("%Y%m%dT%H%M%SZ"), now.strftime("%a, %d %b %Y %H:%M:%S GMT")


def file_md5(path: str) -> str:
    """Calculate MD5 checksum of local file."""
    h = hashlib.md5()
    with open(path, "rb") as fp:
        for chunk in iter(lambda: fp.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def crc32_hex(data: bytes) -> str:
    """Calculate CRC32 checksum formatted as 8-character hex string."""
    return f"{binascii.crc32(data) & 0xFFFFFFFF:08x}"


def common_query(device: Dict[str, Any], babi_param: Any = None, include_region: bool = True) -> Dict[str, str]:
    """Build standard query parameter dict for CapCut API calls."""
    q = {
        "app_name": device["app_name"],
        "device_type": device["device_type"],
        "os_version": device["os_version"],
        "channel": device["channel"],
        "version_name": device["version_name"],
        "device_brand": device["device_brand"],
        "device_id": device["device_id"],
        "iid": device["iid"],
        "version_code": device["version_code"],
        "device_platform": device["device_platform"],
        "aid": device["aid"],
    }
    if include_region:
        q["region"] = device["region"]
    if babi_param is not None:
        q["babi_param"] = compact_json(babi_param)
    return q


def base_headers(device: Dict[str, Any], body_text: str, appid: bool = False) -> Dict[str, str]:
    """Build base HTTP headers required by CapCut API endpoints."""
    now = str(int(time.time()))
    headers = {
        "content-type": "application/json",
        "appvr": device["appvr"],
        "ch": device["channel"],
        "device-time": now,
        "lan": device["lan"],
        "loc": device["loc"],
        "pf": device["pf"],
        "sign-ver": "1",
        "tdid": device["tdid"],
        "x-ss-stub": make_x_ss_stub(body_text),
        "x-ss-dp": device["aid"],
        "x-khronos": now,
        "x-tt-trace-id": make_trace_id(),
        "user-agent": "Cronet/TTNetVersion:1d7cc3b1 2025-07-16 QuicVersion:52c2b40d 2025-04-03",
        "accept-encoding": "gzip, deflate",
        "store-country-code": device["loc"].lower(),
        "store-country-code-src": "did",
        "is-dispatch-us-ttp": "0",
        "is-app-region-us-ttp": "0",
    }
    if appid:
        headers["app-sdk-version"] = device["appvr"]
        headers["appid"] = device["aid"]
    return headers
