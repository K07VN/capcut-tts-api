// cronet_helper_dll.cpp — Windows DLL, callable from Python via ctypes
//
// Exports:
//   int init_engine(dll_path, app_id, device_id, app_version,
//                   channel, device_platform, device_type)
//   int run_request(url, body_json, sign_header, device_time,
//                   out_buf, out_buf_size)
//
// Build (MSVC Developer Command Prompt):
//   cl /O2 /std:c++17 /EHsc /MD /LD cronet_helper_dll.cpp /Fe:cronet_helper.dll
//      /link Advapi32.lib /INCREMENTAL:NO

#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <wincrypt.h>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <ctime>
#include <string>
#include <stdint.h>
#pragma comment(lib, "Advapi32.lib")

// ─────────────────────────────────────────────────────────────────────────────
// Runtime config — filled by init_engine(), used by run_request()
// ─────────────────────────────────────────────────────────────────────────────
static std::string g_dll_path;        // path to sscronet.dll
static std::string g_app_id;
static std::string g_device_id;
static std::string g_app_version;
static std::string g_channel;
static std::string g_device_platform;
static std::string g_device_type;

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────
typedef void* CPtr;
static HMODULE g_lib = nullptr;

template<typename T>
static T sym(const char* name) {
    FARPROC addr = GetProcAddress(g_lib, name);
    if (!addr) {
        fprintf(stderr, "[-] GetProcAddress failed: %s (err %lu)\n",
                name, GetLastError());
        fflush(stderr);
    }
    return (T)(void*)addr;
}

// MD5 via Windows CryptAPI (no external deps)
static std::string win_md5(const std::string& s) {
    HCRYPTPROV hProv = 0;
    HCRYPTHASH hHash = 0;
    CryptAcquireContext(&hProv, nullptr, nullptr, PROV_RSA_FULL,
                        CRYPT_VERIFYCONTEXT);
    CryptCreateHash(hProv, CALG_MD5, 0, 0, &hHash);
    CryptHashData(hHash, (const BYTE*)s.data(), (DWORD)s.size(), 0);
    BYTE digest[16];
    DWORD len = 16;
    CryptGetHashParam(hHash, HP_HASHVAL, digest, &len, 0);
    CryptDestroyHash(hHash);
    CryptReleaseContext(hProv, 0);
    char hex[33];
    for (int i = 0; i < 16; ++i) sprintf_s(hex + i * 2, 3, "%02x", digest[i]);
    return std::string(hex, 32);
}

// ─────────────────────────────────────────────────────────────────────────────
// Request state
// ─────────────────────────────────────────────────────────────────────────────
struct RequestState {
    std::string body;
    int         status = 0;
    bool        done   = false;
    HANDLE      hEvent = nullptr;
};

struct UploadCtx {
    const char* data;
    size_t      len;
    size_t      pos;
};

// ─────────────────────────────────────────────────────────────────────────────
// Cronet callbacks
// ─────────────────────────────────────────────────────────────────────────────
static void cb_redirect(CPtr self, CPtr req, CPtr info, const char* url) {
    fprintf(stderr, "[*] Redirect: %s\n", url);
    sym<void(*)(CPtr)>("Cronet_UrlRequest_FollowRedirect")(req);
}

static void cb_response(CPtr self, CPtr req, CPtr info) {
    auto* st = (RequestState*)sym<void*(*)(CPtr)>(
        "Cronet_UrlRequestCallback_GetClientContext")(self);
    if (st)
        st->status = sym<int(*)(CPtr)>(
            "Cronet_UrlResponseInfo_http_status_code_get")(info);
    fprintf(stderr, "[*] HTTP %d\n", st ? st->status : -1);
    auto buf = sym<CPtr(*)()>("Cronet_Buffer_Create")();
    sym<void(*)(CPtr, uint64_t)>("Cronet_Buffer_InitWithAlloc")(buf, 65536);
    sym<void(*)(CPtr, CPtr)>("Cronet_UrlRequest_Read")(req, buf);
}

static void cb_read(CPtr self, CPtr req, CPtr info, CPtr buffer, uint64_t bytes) {
    auto* st = (RequestState*)sym<void*(*)(CPtr)>(
        "Cronet_UrlRequestCallback_GetClientContext")(self);
    if (st && bytes > 0)
        st->body.append(sym<char*(*)(CPtr)>("Cronet_Buffer_GetData")(buffer), bytes);
    sym<void(*)(CPtr, uint64_t)>("Cronet_Buffer_InitWithAlloc")(buffer, 65536);
    sym<void(*)(CPtr, CPtr)>("Cronet_UrlRequest_Read")(req, buffer);
}

static void signal_done(RequestState* st) {
    if (st) { st->done = true; SetEvent(st->hEvent); }
}

static void cb_success(CPtr self, CPtr req, CPtr info) {
    auto* st = (RequestState*)sym<void*(*)(CPtr)>(
        "Cronet_UrlRequestCallback_GetClientContext")(self);
    fprintf(stderr, "[*] Request success\n");
    signal_done(st);
}

static void cb_fail(CPtr self, CPtr req, CPtr info, CPtr err) {
    auto* st = (RequestState*)sym<void*(*)(CPtr)>(
        "Cronet_UrlRequestCallback_GetClientContext")(self);
    auto msg = sym<const char*(*)(CPtr)>("Cronet_Error_message_get")(err);
    fprintf(stderr, "[-] Request failed: %s\n", msg ? msg : "unknown");
    if (st) st->body = std::string("{\"error\":\"") +
                       (msg ? msg : "unknown") + "\"}";
    signal_done(st);
}

static void cb_cancel(CPtr self, CPtr req, CPtr info) {
    auto* st = (RequestState*)sym<void*(*)(CPtr)>(
        "Cronet_UrlRequestCallback_GetClientContext")(self);
    fprintf(stderr, "[-] Request canceled\n");
    if (st) st->body = "{\"error\":\"canceled\"}";
    signal_done(st);
}

// ─────────────────────────────────────────────────────────────────────────────
// Upload callbacks
// ─────────────────────────────────────────────────────────────────────────────
static int64_t up_length(CPtr self) {
    auto* ctx = (UploadCtx*)sym<void*(*)(CPtr)>(
        "Cronet_UploadDataProvider_GetClientContext")(self);
    return ctx ? (int64_t)ctx->len : 0;
}

static void up_read(CPtr self, CPtr sink, CPtr buffer) {
    auto* ctx = (UploadCtx*)sym<void*(*)(CPtr)>(
        "Cronet_UploadDataProvider_GetClientContext")(self);
    auto buf_data = sym<char*(*)(CPtr)>("Cronet_Buffer_GetData")(buffer);
    auto buf_size = sym<uint64_t(*)(CPtr)>("Cronet_Buffer_GetSize")(buffer);
    size_t to_copy = ctx->len - ctx->pos;
    if (to_copy > buf_size) to_copy = (size_t)buf_size;
    if (to_copy > 0) memcpy(buf_data, ctx->data + ctx->pos, to_copy);
    ctx->pos += to_copy;
    sym<void(*)(CPtr, uint64_t, bool)>("Cronet_UploadDataSink_OnReadSucceeded")(
        sink, to_copy, false);
}

static void up_rewind(CPtr self, CPtr sink) {
    auto* ctx = (UploadCtx*)sym<void*(*)(CPtr)>(
        "Cronet_UploadDataProvider_GetClientContext")(self);
    if (ctx) ctx->pos = 0;
    sym<void(*)(CPtr)>("Cronet_UploadDataSink_OnRewindSucceeded")(sink);
}

static void up_close(CPtr self) {}

// ─────────────────────────────────────────────────────────────────────────────
// Executor — each runnable runs on its own Windows thread
// ─────────────────────────────────────────────────────────────────────────────
struct RunnableWork { CPtr runnable; };

static DWORD WINAPI runnable_thread(LPVOID param) {
    auto* w = (RunnableWork*)param;
    auto run_fn     = sym<void(*)(CPtr)>("Cronet_Runnable_Run");
    auto destroy_fn = sym<void(*)(CPtr)>("Cronet_Runnable_Destroy");
    if (run_fn)     run_fn(w->runnable);
    if (destroy_fn) destroy_fn(w->runnable);
    delete w;
    return 0;
}

static void executor_execute(CPtr self, CPtr runnable) {
    auto* w = new RunnableWork{runnable};
    HANDLE h = CreateThread(nullptr, 0, runnable_thread, w, 0, nullptr);
    if (h) CloseHandle(h);
    else   delete w;
}

// ─────────────────────────────────────────────────────────────────────────────
// Engine singleton
// ─────────────────────────────────────────────────────────────────────────────
static CPtr g_engine   = nullptr;
static CPtr g_executor = nullptr;
static CRITICAL_SECTION g_init_cs;
static bool g_cs_inited = false;

// Called internally after init_engine() has set the config globals
static bool start_engine() {
    EnterCriticalSection(&g_init_cs);
    if (g_engine) { LeaveCriticalSection(&g_init_cs); return true; }

    fprintf(stderr, "[*] Loading %s\n", g_dll_path.c_str()); fflush(stderr);
    g_lib = LoadLibraryA(g_dll_path.c_str());
    if (!g_lib) {
        fprintf(stderr, "[-] LoadLibrary failed: err %lu\n", GetLastError());
        LeaveCriticalSection(&g_init_cs);
        return false;
    }
    fprintf(stderr, "[*] DLL loaded\n"); fflush(stderr);

    // ── TTNetParams ───────────────────────────────────────────────────────────
    auto ttparams = sym<CPtr(*)()>("Cronet_TTNetParams_Create")();
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_app_id_set")          (ttparams, g_app_id.c_str());
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_app_name_set")        (ttparams, "CapCut");
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_device_id_set")       (ttparams, g_device_id.c_str());
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_device_platform_set") (ttparams, g_device_platform.c_str());
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_device_type_set")     (ttparams, g_device_type.c_str());
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_channel_set")         (ttparams, g_channel.c_str());
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_version_code_set")    (ttparams, g_app_version.c_str());
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_update_version_code_set")(ttparams, g_app_version.c_str());
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_domain_httpdns_set")  (ttparams, "dig.bdurl.net");
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_tnc_host_first_set")  (ttparams, "tnc-sg.capcut.com");
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_tnc_host_second_set") (ttparams, "tnc-sg.capcut.com");
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_tnc_host_third_set")  (ttparams, "tnc-sg.capcut.com");
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_domain_boe_set")      (ttparams, "boe.bytedance.net");
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_uuid_set")            (ttparams, g_device_id.c_str());
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_domain_netlog_set")   (ttparams, "log-sg.capcut.com");
    sym<void(*)(CPtr,const char*)>("Cronet_TTNetParams_is_main_process_set") (ttparams, "true");

    // ── EngineParams ──────────────────────────────────────────────────────────
    auto eparams = sym<CPtr(*)()>("Cronet_EngineParams_Create")();

    char tmp_dir[MAX_PATH];
    GetTempPathA(MAX_PATH, tmp_dir);
    std::string cache_dir = std::string(tmp_dir) + "cronet_cache";
    CreateDirectoryA(cache_dir.c_str(), nullptr);

    sym<void(*)(CPtr,const char*)>("Cronet_EngineParams_storage_path_set")(eparams, cache_dir.c_str());
    sym<void(*)(CPtr,const char*)>("Cronet_EngineParams_user_agent_set")(eparams,
        "Cronet/TTNetVersion:1d7cc3b1 2025-07-16 QuicVersion:52c2b40d 2025-04-03");
    sym<void(*)(CPtr,bool)>("Cronet_EngineParams_enable_check_result_set")(eparams, false);
    sym<void(*)(CPtr,bool)>("Cronet_EngineParams_enable_quic_set")        (eparams, false);
    sym<void(*)(CPtr,bool)>("Cronet_EngineParams_enable_http2_set")       (eparams, true);
    sym<void(*)(CPtr,CPtr)>("Cronet_EngineParams_ttnet_params_set")       (eparams, ttparams);

    auto engine = sym<CPtr(*)()>("Cronet_Engine_Create")();
    int ret = sym<int(*)(CPtr,CPtr)>("Cronet_Engine_StartWithParams")(engine, eparams);
    if (ret != 0) {
        fprintf(stderr, "[-] Engine start failed: %d\n", ret);
        LeaveCriticalSection(&g_init_cs);
        return false;
    }

    g_engine   = engine;
    g_executor = sym<CPtr(*)(void*)>("Cronet_Executor_CreateWith")(
        (void*)executor_execute);

    fprintf(stderr, "[*] Cronet engine ready\n"); fflush(stderr);
    LeaveCriticalSection(&g_init_cs);
    return true;
}

// ─────────────────────────────────────────────────────────────────────────────
// EXPORT 1: init_engine
//
//  dll_path        : full path to sscronet.dll
//  app_id          : e.g. "359289"
//  device_id       : numeric device ID string
//  app_version     : e.g. "8.7.0"
//  channel         : e.g. "capcutpc_0"
//  device_platform : e.g. "windows"
//  device_type     : e.g. "pc"
//
//  Returns 0 on success, non-zero on failure.
//  Must be called once before the first run_request().
// ─────────────────────────────────────────────────────────────────────────────
extern "C" __declspec(dllexport)
int init_engine(const char* dll_path,
                const char* app_id,
                const char* device_id,
                const char* app_version,
                const char* channel,
                const char* device_platform,
                const char* device_type)
{
    if (!g_cs_inited) {
        InitializeCriticalSection(&g_init_cs);
        g_cs_inited = true;
    }

    // Store config globals
    g_dll_path        = dll_path        ? dll_path        : "";
    g_app_id          = app_id          ? app_id          : "359289";
    g_device_id       = device_id       ? device_id       : "";
    g_app_version     = app_version     ? app_version     : "8.7.0";
    g_channel         = channel         ? channel         : "capcutpc_0";
    g_device_platform = device_platform ? device_platform : "windows";
    g_device_type     = device_type     ? device_type     : "pc";

    return start_engine() ? 0 : 1;
}

// ─────────────────────────────────────────────────────────────────────────────
// EXPORT 2: run_request
//
//  url         : full URL with query string
//  body_json   : UTF-8 JSON POST body
//  sign_header : value for "sign" header (may be "")
//  device_time : unix timestamp; 0 = current time
//  out_buf     : caller buffer to receive response JSON
//  out_buf_size: size of out_buf in bytes
//
//  Returns HTTP status code, or negative on error:
//    -1  engine not initialized / load failed
//    -2  UrlRequest_InitWithParams failed
//    -3  timeout (30 s)
// ─────────────────────────────────────────────────────────────────────────────
extern "C" __declspec(dllexport)
int run_request(const char* url,
                const char* body_json,
                const char* sign_header,
                int64_t     device_time,
                char*       out_buf,
                int         out_buf_size)
{
    if (!g_engine) {
        fprintf(stderr, "[-] Engine not initialized. Call init_engine() first.\n");
        return -1;
    }

    if (device_time <= 0) device_time = (int64_t)time(nullptr);

    std::string stub = win_md5(body_json ? body_json : "");
    char ts_str[32];
    sprintf_s(ts_str, "%lld", (long long)device_time);

    // ── Request state & event ─────────────────────────────────────────────────
    RequestState st;
    st.hEvent = CreateEventA(nullptr, TRUE, FALSE, nullptr);

    auto callback = sym<CPtr(*)(void*,void*,void*,void*,void*,void*)>(
        "Cronet_UrlRequestCallback_CreateWith")(
        (void*)cb_redirect, (void*)cb_response, (void*)cb_read,
        (void*)cb_success,  (void*)cb_fail,     (void*)cb_cancel);

    auto set_ctx = (void(*)(CPtr,void*))GetProcAddress(g_lib,
        "Cronet_UrlRequestCallback_SetClientContext");
    if (set_ctx) set_ctx(callback, &st);

    // ── HTTP headers (all from config / caller) ───────────────────────────────
    auto rparams = sym<CPtr(*)()>("Cronet_UrlRequestParams_Create")();
    sym<void(*)(CPtr,const char*)>("Cronet_UrlRequestParams_http_method_set")(rparams, "POST");

    auto add_hdr = [&](const char* n, const char* v) {
        auto h = sym<CPtr(*)()>("Cronet_HttpHeader_Create")();
        sym<void(*)(CPtr,const char*)>("Cronet_HttpHeader_name_set")(h, n);
        sym<void(*)(CPtr,const char*)>("Cronet_HttpHeader_value_set")(h, v);
        sym<void(*)(CPtr,CPtr)>("Cronet_UrlRequestParams_request_headers_add")(rparams, h);
    };

    add_hdr("content-type",    "application/json");
    add_hdr("appid",           g_app_id.c_str());
    add_hdr("appvr",           g_app_version.c_str());
    add_hdr("ch",              g_channel.c_str());
    add_hdr("pf",              "3");
    add_hdr("tdid",            g_device_id.c_str());
    add_hdr("app-sdk-version", g_app_version.c_str());
    add_hdr("lan",             "en");
    add_hdr("loc",             "VN");
    add_hdr("sign-ver",        "1");
    add_hdr("x-ss-dp",         g_app_id.c_str());
    add_hdr("x-ss-stub",       stub.c_str());
    add_hdr("device-time",     ts_str);
    add_hdr("x-khronos",       ts_str);
    if (sign_header && sign_header[0])
        add_hdr("sign", sign_header);

    // ── Upload body ───────────────────────────────────────────────────────────
    static thread_local UploadCtx uctx;
    uctx = { body_json, body_json ? strlen(body_json) : 0, 0 };

    auto upload = sym<CPtr(*)(void*,void*,void*,void*)>(
        "Cronet_UploadDataProvider_CreateWith")(
        (void*)up_length, (void*)up_read, (void*)up_rewind, (void*)up_close);
    sym<void(*)(CPtr,void*)>("Cronet_UploadDataProvider_SetClientContext")(upload, &uctx);
    sym<void(*)(CPtr,CPtr)>("Cronet_UrlRequestParams_upload_data_provider_set")(rparams, upload);
    sym<void(*)(CPtr,CPtr)>("Cronet_UrlRequestParams_upload_data_provider_executor_set")(rparams, g_executor);

    // ── Start request & wait ──────────────────────────────────────────────────
    auto request = sym<CPtr(*)()>("Cronet_UrlRequest_Create")();
    int r = sym<int(*)(CPtr,CPtr,const char*,CPtr,CPtr,CPtr)>(
        "Cronet_UrlRequest_InitWithParams")(
        request, g_engine, url, rparams, callback, g_executor);

    if (r != 0) {
        fprintf(stderr, "[-] InitWithParams failed: %d\n", r);
        CloseHandle(st.hEvent);
        return -2;
    }
    sym<int(*)(CPtr)>("Cronet_UrlRequest_Start")(request);

    DWORD wait = WaitForSingleObject(st.hEvent, 30000);
    CloseHandle(st.hEvent);

    if (wait == WAIT_TIMEOUT) {
        fprintf(stderr, "[-] Request timeout\n");
        if (out_buf && out_buf_size > 0)
            strncpy_s(out_buf, out_buf_size, "{\"error\":\"timeout\"}", _TRUNCATE);
        return -3;
    }

    if (out_buf && out_buf_size > 0)
        strncpy_s(out_buf, out_buf_size, st.body.c_str(), _TRUNCATE);

    return st.status;
}

// ─────────────────────────────────────────────────────────────────────────────
// DllMain
// ─────────────────────────────────────────────────────────────────────────────
BOOL WINAPI DllMain(HINSTANCE, DWORD reason, LPVOID) {
    if (reason == DLL_PROCESS_DETACH && g_lib)
        FreeLibrary(g_lib);
    return TRUE;
}
