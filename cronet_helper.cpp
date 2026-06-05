// cronet_helper.cpp — Uses CapCut's libsscronet with CFRunLoop for proper async request processing
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <string>
#include <dlfcn.h>
#include <unistd.h>
#include <sys/stat.h>
#include <CoreFoundation/CoreFoundation.h>
#include <CommonCrypto/CommonDigest.h>

static std::string get_md5(const std::string& str) {
    unsigned char digest[CC_MD5_DIGEST_LENGTH];
    CC_MD5(str.data(), (CC_LONG)str.size(), digest);
    char hex[33];
    for (int i = 0; i < 16; ++i) {
        sprintf(hex + i * 2, "%02x", digest[i]);
    }
    return std::string(hex, 32);
}

typedef void* CPtr;
static void* lib = nullptr;

template<typename T> T sym(const char* name) {
    void* addr = dlsym(lib, name);
    if (!addr) {
        fprintf(stderr, "[-] dlsym failed for: %s\n", name);
        fflush(stderr);
    }
    return (T)addr;
}

struct UploadCtx { const char* data; size_t len; size_t pos; };

static std::string g_body;
static int g_status = 0;

static void executor_execute(CPtr self, CPtr runnable) {
    dispatch_async(dispatch_get_main_queue(), ^{
        auto run_fn = (void(*)(CPtr))dlsym(lib, "Cronet_Runnable_Run");
        auto destroy_fn = (void(*)(CPtr))dlsym(lib, "Cronet_Runnable_Destroy");
        if (run_fn) run_fn(runnable);
        if (destroy_fn) destroy_fn(runnable);
    });
}

static void on_redirect(CPtr self, CPtr req, CPtr info, const char* url) {
    fprintf(stderr, "[*] Redirect: %s\n", url);
    sym<void(*)(CPtr)>("Cronet_UrlRequest_FollowRedirect")(req);
}

static void on_response(CPtr self, CPtr req, CPtr info) {
    g_status = sym<int(*)(CPtr)>("Cronet_UrlResponseInfo_http_status_code_get")(info);
    fprintf(stderr, "[*] HTTP Status: %d\n", g_status);
    
    auto buf = sym<CPtr(*)()>("Cronet_Buffer_Create")();
    sym<void(*)(CPtr, uint64_t)>("Cronet_Buffer_InitWithAlloc")(buf, 65536);
    sym<void(*)(CPtr, CPtr)>("Cronet_UrlRequest_Read")(req, buf);
}

static void on_read(CPtr self, CPtr req, CPtr info, CPtr buffer, uint64_t bytes) {
    if (bytes > 0)
        g_body.append(sym<char*(*)(CPtr)>("Cronet_Buffer_GetData")(buffer), bytes);
    sym<void(*)(CPtr, uint64_t)>("Cronet_Buffer_InitWithAlloc")(buffer, 65536);
    sym<void(*)(CPtr, CPtr)>("Cronet_UrlRequest_Read")(req, buffer);
}

static void on_success(CPtr self, CPtr req, CPtr info) {
    printf("%s\n", g_body.c_str());
    CFRunLoopStop(CFRunLoopGetMain());
}

static void on_fail(CPtr self, CPtr req, CPtr info, CPtr err) {
    auto msg = sym<const char*(*)(CPtr)>("Cronet_Error_message_get")(err);
    fprintf(stderr, "[-] Request Failed: %s\n", msg ? msg : "unknown");
    printf("{\"error\":\"%s\"}\n", msg ? msg : "unknown");
    CFRunLoopStop(CFRunLoopGetMain());
}

static void on_cancel(CPtr self, CPtr req, CPtr info) {
    fprintf(stderr, "[-] Request Canceled\n");
    printf("{\"error\":\"canceled\"}\n");
    CFRunLoopStop(CFRunLoopGetMain());
}

static int64_t upload_length(CPtr self) {
    auto ctx = (UploadCtx*)sym<void*(*)(CPtr)>("Cronet_UploadDataProvider_GetClientContext")(self);
    return ctx ? (int64_t)ctx->len : 0;
}

static void upload_read(CPtr self, CPtr sink, CPtr buffer) {
    auto ctx = (UploadCtx*)sym<void*(*)(CPtr)>("Cronet_UploadDataProvider_GetClientContext")(self);
    auto buf_data = sym<char*(*)(CPtr)>("Cronet_Buffer_GetData")(buffer);
    auto buf_size = sym<uint64_t(*)(CPtr)>("Cronet_Buffer_GetSize")(buffer);
    size_t to_copy = ctx->len - ctx->pos;
    if (to_copy > buf_size) to_copy = buf_size;
    fprintf(stderr, "[*] upload_read: buf_data=%p, buf_size=%llu, pos=%zu, to_copy=%zu\n", buf_data, buf_size, ctx->pos, to_copy);
    if (to_copy > 0) {
        fprintf(stderr, "[*] Data at src: %.*s\n", (int)to_copy, ctx->data + ctx->pos);
        memcpy(buf_data, ctx->data + ctx->pos, to_copy);
        fprintf(stderr, "[*] Data at dst: %.*s\n", (int)to_copy, buf_data);
    }
    ctx->pos += to_copy;
    sym<void(*)(CPtr, uint64_t, bool)>("Cronet_UploadDataSink_OnReadSucceeded")(sink, to_copy, false);
}

static void upload_rewind(CPtr self, CPtr sink) {
    auto ctx = (UploadCtx*)sym<void*(*)(CPtr)>("Cronet_UploadDataProvider_GetClientContext")(self);
    if (ctx) ctx->pos = 0;
    sym<void(*)(CPtr)>("Cronet_UploadDataSink_OnRewindSucceeded")(sink);
}

static void upload_close(CPtr self) {}

int main(int argc, char* argv[]) {
    fprintf(stderr, "[*] cronet_helper started\n");
    fflush(stderr);
    if (argc < 3) {
        fprintf(stderr, "Usage: %s <url> <body>\n", argv[0]);
        return 1;
    }
    
    fprintf(stderr, "[*] dlopening libsscronet...\n"); fflush(stderr);
    lib = dlopen("/Applications/CapCut.app/Contents/Frameworks/libsscronet.dylib", RTLD_LAZY);
    if (!lib) {
        fprintf(stderr, "[-] dlopen failed: %s\n", dlerror());
        return 1;
    }
    fprintf(stderr, "[*] libsscronet loaded\n"); fflush(stderr);
    
    fprintf(stderr, "[*] Creating TTNetParams...\n"); fflush(stderr);
    auto ttparams = sym<CPtr(*)()>("Cronet_TTNetParams_Create")();
    fprintf(stderr, "[*] TTNetParams created: %p\n", ttparams); fflush(stderr);
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_app_id_set")(ttparams, "359289");
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_app_name_set")(ttparams, "CapCut");
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_device_id_set")(ttparams, "7647183892936328721");
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_device_platform_set")(ttparams, "mac");
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_device_type_set")(ttparams, "MacBookPro17,1");
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_channel_set")(ttparams, "App Store");
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_version_code_set")(ttparams, "8.6.0");
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_update_version_code_set")(ttparams, "8.6.0");
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_domain_httpdns_set")(ttparams, "dig.bdurl.net");
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_tnc_host_first_set")(ttparams, "tnc-sg.capcut.com");
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_tnc_host_second_set")(ttparams, "tnc-sg.capcut.com");
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_tnc_host_third_set")(ttparams, "tnc-sg.capcut.com");
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_domain_boe_set")(ttparams, "boe.bytedance.net");
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_uuid_set")(ttparams, "7647183892936328721");
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_domain_netlog_set")(ttparams, "log-sg.capcut.com");
    sym<void(*)(CPtr, const char*)>("Cronet_TTNetParams_is_main_process_set")(ttparams, "true");
    
    auto eparams = sym<CPtr(*)()>("Cronet_EngineParams_Create")();
    mkdir("/tmp/cronet_cache", 0755);
    sym<void(*)(CPtr, const char*)>("Cronet_EngineParams_storage_path_set")(eparams, "/tmp/cronet_cache");
    sym<void(*)(CPtr, const char*)>("Cronet_EngineParams_user_agent_set")(eparams, "Cronet/TTNetVersion:1d7cc3b1 2025-07-16 QuicVersion:52c2b40d 2025-04-03");
    sym<void(*)(CPtr, bool)>("Cronet_EngineParams_enable_check_result_set")(eparams, false);
    sym<void(*)(CPtr, bool)>("Cronet_EngineParams_enable_quic_set")(eparams, false);
    sym<void(*)(CPtr, bool)>("Cronet_EngineParams_enable_http2_set")(eparams, true);
    sym<void(*)(CPtr, CPtr)>("Cronet_EngineParams_ttnet_params_set")(eparams, ttparams);
    
    auto engine = sym<CPtr(*)()>("Cronet_Engine_Create")();
    int ret = sym<int(*)(CPtr, CPtr)>("Cronet_Engine_StartWithParams")(engine, eparams);
    if (ret != 0) {
        fprintf(stderr, "[-] Failed to start Cronet engine: %d\n", ret);
        return 1;
    }
    
    const char* url = argv[1];
    const char* body_str = argv[2];
    
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 500 * NSEC_PER_MSEC), dispatch_get_main_queue(), ^{
        auto executor = sym<CPtr(*)(void*)>("Cronet_Executor_CreateWith")((void*)executor_execute);
        auto callback = sym<CPtr(*)(void*,void*,void*,void*,void*,void*)>("Cronet_UrlRequestCallback_CreateWith")(
            (void*)on_redirect, (void*)on_response, (void*)on_read,
            (void*)on_success, (void*)on_fail, (void*)on_cancel);
        
        auto rparams = sym<CPtr(*)()>("Cronet_UrlRequestParams_Create")();
        sym<void(*)(CPtr, const char*)>("Cronet_UrlRequestParams_http_method_set")(rparams, "POST");
        
        auto add_hdr = [&](const char* n, const char* v) {
            auto h = sym<CPtr(*)()>("Cronet_HttpHeader_Create")();
            sym<void(*)(CPtr, const char*)>("Cronet_HttpHeader_name_set")(h, n);
            sym<void(*)(CPtr, const char*)>("Cronet_HttpHeader_value_set")(h, v);
            sym<void(*)(CPtr, CPtr)>("Cronet_UrlRequestParams_request_headers_add")(rparams, h);
        };
// Inside main function, where headers are added:
        add_hdr("content-type", "application/json");
        add_hdr("appid", "359289");
        add_hdr("appvr", "8.6.0");
        add_hdr("ch", "App Store");
        add_hdr("pf", "3");
        add_hdr("tdid", "7647183892936328721");
        add_hdr("app-sdk-version", "8.6.0");
        add_hdr("lan", "en");
        add_hdr("loc", "VN");
        add_hdr("sign-ver", "1");
        add_hdr("x-ss-dp", "359289");
        if (argc > 3) {
            add_hdr("sign", argv[3]);
        }
        
        std::string stub = get_md5(body_str);
        add_hdr("x-ss-stub", stub.c_str());
        
        char khronos_buf[32];
        const char* env_ts = getenv("DEVICE_TIME");
        if (env_ts) {
            snprintf(khronos_buf, sizeof(khronos_buf), "%s", env_ts);
        } else {
            snprintf(khronos_buf, sizeof(khronos_buf), "%ld", time(nullptr));
        }
        add_hdr("device-time", khronos_buf);
        add_hdr("x-khronos", khronos_buf);
        
        static UploadCtx uctx;
        uctx = {body_str, strlen(body_str), 0};
        auto upload = sym<CPtr(*)(void*,void*,void*,void*)>("Cronet_UploadDataProvider_CreateWith")(
            (void*)upload_length, (void*)upload_read, (void*)upload_rewind, (void*)upload_close);
        sym<void(*)(CPtr, void*)>("Cronet_UploadDataProvider_SetClientContext")(upload, &uctx);
        sym<void(*)(CPtr, CPtr)>("Cronet_UrlRequestParams_upload_data_provider_set")(rparams, upload);
        sym<void(*)(CPtr, CPtr)>("Cronet_UrlRequestParams_upload_data_provider_executor_set")(rparams, executor);
        
        auto request = sym<CPtr(*)()>("Cronet_UrlRequest_Create")();
        int r = sym<int(*)(CPtr, CPtr, const char*, CPtr, CPtr, CPtr)>("Cronet_UrlRequest_InitWithParams")(
            request, engine, url, rparams, callback, executor);
        if (r == 0) {
            sym<int(*)(CPtr)>("Cronet_UrlRequest_Start")(request);
        } else {
            fprintf(stderr, "[-] UrlRequest Init failed: %d\n", r);
            CFRunLoopStop(CFRunLoopGetMain());
        }
    });
    
    // Timeout fallback (30s)
    dispatch_after(dispatch_time(DISPATCH_TIME_NOW, 30 * NSEC_PER_SEC), dispatch_get_main_queue(), ^{
        fprintf(stderr, "[-] Request Timeout\n");
        printf("{\"error\":\"timeout\"}\n");
        CFRunLoopStop(CFRunLoopGetMain());
    });
    
    CFRunLoopRun();
    return 0;
}
