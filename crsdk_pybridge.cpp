// crsdk_pybridge.cpp — Sony Camera Remote SDK v2.0 bridge (DLL)
// Build: x64, C++17, /MD, Unicode
// Include: <SDK>\app\CRSDK   Link: Cr_Core.lib

#include <windows.h>
#include <cstdint>
#include <cwchar>
#include <cstdarg>
#include <string>
#include <atomic>
#include <new>
#include <cstring>
#include <vector>
#include <cstdio>
#include <io.h>

#include "CrTypes.h"
#include "CrError.h"
#include "CrDefines.h"
#include "CrCommandData.h"
#include "ICrCameraObjectInfo.h"
#include "IDeviceCallback.h"
#include "CrImageDataBlock.h"
#include "CameraRemote_SDK.h"

#define WIDEN2(x) L##x
#define WIDEN(x)  WIDEN2(x)
static const wchar_t* BUILD_STAMP = WIDEN(__DATE__) L" " WIDEN(__TIME__);

// ---- helpers (RC 분류: SDK v2 명칭 기준) ----
static inline bool is_timeout(SCRSDK::CrError e) {
    return e == SCRSDK::CrError_Connect_TimeOut ||
        e == SCRSDK::CrError_Reconnect_TimeOut;
}
static inline bool is_disconnected(SCRSDK::CrError e) {
    return e == SCRSDK::CrError_Connect_Disconnected;
}
static std::wstring g_download_dir;
static std::wstring g_last_saved;


// ===== helpers =====
static std::wstring widen_from_acp(const char* s) {
    if (!s) return {};
    int n = MultiByteToWideChar(CP_ACP, 0, s, -1, nullptr, 0);
    if (n <= 1) return {};
    std::wstring w; w.resize(n - 1);
    MultiByteToWideChar(CP_ACP, 0, s, -1, w.data(), n);
    return w;
}


// ---- debug ----
static int g_debug = 1;
static void dlog(const wchar_t* fmt, ...) {
    if (!g_debug) return;
    wchar_t buf[1024];
    va_list ap; va_start(ap, fmt);
    _vsnwprintf_s(buf, _countof(buf), _TRUNCATE, fmt, ap);
    va_end(ap);
    OutputDebugStringW(L"[crsdk_pybridge] ");
    OutputDebugStringW(buf);
    OutputDebugStringW(L"\r\n");
}
static void log_loaded_mod(const wchar_t* name) {
    HMODULE h = GetModuleHandleW(name);
    if (!h) { dlog(L"mod %s -> not loaded", name); return; }
    wchar_t path[MAX_PATH]{};
    GetModuleFileNameW(h, path, _countof(path));
    dlog(L"mod %s -> %s", name, path);
}

// ---- ensure runtime DLL search dir & preload ----
static void pin_sdk_dir_and_preload() {
    wchar_t mod[MAX_PATH]{};
    HMODULE hSelf = nullptr;
    GetModuleHandleExW(
        GET_MODULE_HANDLE_EX_FLAG_FROM_ADDRESS |
        GET_MODULE_HANDLE_EX_FLAG_UNCHANGED_REFCOUNT,
        reinterpret_cast<LPCWSTR>(&pin_sdk_dir_and_preload), &hSelf);
    GetModuleFileNameW(hSelf, mod, _countof(mod));
    if (wchar_t* p = wcsrchr(mod, L'\\')) *p = 0;

    if (HMODULE k32 = GetModuleHandleW(L"kernel32.dll")) {
        auto pSetDef = reinterpret_cast<BOOL(WINAPI*)(DWORD)>(
            GetProcAddress(k32, "SetDefaultDllDirectories"));
        using AddDirFn = PVOID(WINAPI*)(PCWSTR);
        auto pAddDir = reinterpret_cast<AddDirFn>(
            GetProcAddress(k32, "AddDllDirectory"));
        if (pSetDef && pAddDir) {
            pSetDef(LOAD_LIBRARY_SEARCH_DEFAULT_DIRS | LOAD_LIBRARY_SEARCH_USER_DIRS);
            pAddDir(mod);
        }
        else {
            SetDllDirectoryW(mod);
        }
    }
    else {
        SetDllDirectoryW(mod);
    }

    std::wstring dir(mod);
    LoadLibraryW((dir + L"\\Cr_Core.dll").c_str());
    LoadLibraryW((dir + L"\\Cr_PTP_USB.dll").c_str());
    LoadLibraryW((dir + L"\\libusb-1.0.dll").c_str());
    LoadLibraryW((dir + L"\\Cr_PTP_IP.dll").c_str());
    LoadLibraryW((dir + L"\\libssh2.dll").c_str());

    SetCurrentDirectoryW(mod);
}

// ---- context & callback ----
struct CamCtx {
    SCRSDK::CrDeviceHandle dev{ 0 };
    std::atomic<int> connected{ 0 };
    std::atomic<int> last_cb_err{ 0 };
    bool lv_on{ false };
    HANDLE hConnEvt{ CreateEventW(nullptr, TRUE, FALSE, nullptr) };

    struct DevCb final : SCRSDK::IDeviceCallback {
        explicit DevCb(CamCtx* o) : owner(o) {}
        void OnConnected(SCRSDK::DeviceConnectionVersioin) override {
            if (owner) {
                owner->connected.store(1, std::memory_order_relaxed);
                SetEvent(owner->hConnEvt);
            }
            dlog(L"OnConnected()");
        }
        void OnDisconnected(CrInt32u err) override {
            if (owner) {
                owner->connected.store(0, std::memory_order_relaxed);
                owner->last_cb_err.store((int)err, std::memory_order_relaxed);
                ResetEvent(owner->hConnEvt);
            }
            dlog(L"OnDisconnected err=%u", err);
        }
        void OnWarning(CrInt32u w) override { dlog(L"OnWarning code=%u", w); }
        void OnError(CrInt32u err) override {
            if (owner) owner->last_cb_err.store((int)err, std::memory_order_relaxed);
            dlog(L"OnError err=%u", err);
        }
        CamCtx* owner{ nullptr };
    } cb;

    CamCtx() : cb(this) {}
    ~CamCtx() { if (hConnEvt) CloseHandle(hConnEvt); }
};

static int to_ret(SCRSDK::CrError er) { return (er == SCRSDK::CrError_None) ? 0 : (int)er; }

static HMODULE try_load(const wchar_t* name, DWORD* perr) {
    HMODULE h = GetModuleHandleW(name);
    if (!h) {
        h = LoadLibraryW(name);
        if (!h && perr) *perr = GetLastError();
    }
    return h;
}

#if defined(UNICODE) || defined(_UNICODE)
static inline const wchar_t* W(const CrChar* s) {
    return reinterpret_cast<const wchar_t*>(s ? s : L"");
}
#else
static inline const wchar_t* W(const CrChar* s) {
    static thread_local wchar_t tmp[512];
    if (!s) { tmp[0] = 0; return tmp; }
    MultiByteToWideChar(CP_ACP, 0, s, -1, tmp, (int)_countof(tmp));
    return tmp;
}
#endif

static int wait_connected(CamCtx* ctx, DWORD ms) {
    if (!ctx || !ctx->hConnEvt) return -2;
    DWORD w = WaitForSingleObject(ctx->hConnEvt, ms);
    if (w == WAIT_OBJECT_0 && ctx->connected.load()) return 0;
    dlog(L"wait_connected timeout (ms=%u)", (unsigned)ms);
    return -3;
}

// ---- mutable-string helper for SetSaveInfo (expects CrChar*) ----
static inline SCRSDK::CrError call_SetSaveInfo(
    SCRSDK::CrDeviceHandle dev,
    const char* host_dir,         // nullable
    const char* file_name,        // nullable
    CrInt32 save_mode             // SDK save mode enum value
) {
    CrChar* p_dir = nullptr;
    CrChar* p_name = nullptr;
    std::vector<CrChar> dirbuf;
    std::vector<CrChar> namebuf;

    if (host_dir && host_dir[0]) {
        dirbuf.assign(host_dir, host_dir + std::strlen(host_dir) + 1); // include NUL
        p_dir = dirbuf.data();
    }
    if (file_name && file_name[0]) {
        namebuf.assign(file_name, file_name + std::strlen(file_name) + 1);
        p_name = namebuf.data();
    }
    return SCRSDK::SetSaveInfo(dev, p_dir, p_name, save_mode);
}

// ---- exports ----
extern "C" {

    // 원샷 AF: AF-ON Down→Up
    __declspec(dllexport) int crsdk_one_shot_af(void* handle) {
        CamCtx* ctx = reinterpret_cast<CamCtx*>(handle);
        if (!ctx || !ctx->dev) return -2;
        auto e = SCRSDK::SendCommand(ctx->dev,
            SCRSDK::CrCommandId_TrackingOnAndAFOn,
            SCRSDK::CrCommandParam_Down);
        if (e != SCRSDK::CrError_None) return (int)e;
        Sleep(150);
        e = SCRSDK::SendCommand(ctx->dev,
            SCRSDK::CrCommandId_TrackingOnAndAFOn,
            SCRSDK::CrCommandParam_Up);
        return (int)e;
    }

    // 원샷 AWB(보수적): 기종/헤더에 따라 미지원일 수 있음.
    // → 미지원이면 음수 반환해서 상위(Python) 폴백 사용.
    __declspec(dllexport) int crsdk_one_shot_awb(void* /*handle*/) {
        // 안전 스텁: 현재 배포 헤더에 "Custom WB Capture" 계열 명령이 노출되지 않으면 미지원
        // 실제 구현은 모델이 지원할 때 CrCommandId_CustomWBCapture* 또는
        // WhiteBalance 관련 DP를 사용해 교정 트리거를 보내도록 확장.
        return -24; // not supported in this build
    }

    // 다운로드 대상 폴더 지정 (예: "C:\\PhotoBox\\captures")
    __declspec(dllexport) int crsdk_set_download_dir(const char* dir) {
        g_download_dir = widen_from_acp(dir);
        // 끝의 백슬래시 제거
        if (!g_download_dir.empty() && g_download_dir.back() == L'\\')
            g_download_dir.pop_back();
        return 0;
    }

    // 지정 폴더에서 "가장 최근 .jpg" 경로 반환
    __declspec(dllexport) int crsdk_get_last_saved_jpeg(void* /*handle*/, wchar_t* out_path, unsigned cch) {
        if (!out_path || cch == 0) return -1;
        out_path[0] = 0;
        if (g_download_dir.empty()) return -2;

        WIN32_FIND_DATAW fd{};
        std::wstring pattern = g_download_dir + L"\\*.jpg";
        HANDLE h = FindFirstFileW(pattern.c_str(), &fd);
        if (h == INVALID_HANDLE_VALUE) return 1; // none

        ULONGLONG best = 0;
        std::wstring bestPath;
        do {
            if (!(fd.dwFileAttributes & FILE_ATTRIBUTE_DIRECTORY)) {
                ULARGE_INTEGER t{};
                t.HighPart = fd.ftLastWriteTime.dwHighDateTime;
                t.LowPart = fd.ftLastWriteTime.dwLowDateTime;
                if (t.QuadPart > best) {
                    best = t.QuadPart;
                    bestPath = g_download_dir + L"\\" + fd.cFileName;
                }
            }
        } while (FindNextFileW(h, &fd));
        FindClose(h);

        if (bestPath.empty()) return 1;
        wcsncpy_s(out_path, cch, bestPath.c_str(), _TRUNCATE);
        g_last_saved = bestPath;
        return 0;
    }

    __declspec(dllexport) void crsdk_set_debug(int on) { g_debug = on ? 1 : 0; }

    __declspec(dllexport) int crsdk_init() {
        pin_sdk_dir_and_preload();
        log_loaded_mod(L"Cr_Core.dll");
        log_loaded_mod(L"Cr_PTP_USB.dll");
        log_loaded_mod(L"libusb-1.0.dll");
        log_loaded_mod(L"Cr_PTP_IP.dll");
        log_loaded_mod(L"libssh2.dll");
        bool ok = SCRSDK::Init(0);
        dlog(L"Init -> %d", ok ? 1 : 0);
        return ok ? 0 : -1;
    }

    __declspec(dllexport) void crsdk_release(void) {
        SCRSDK::Release();
        dlog(L"Release");
    }

    // dependency check
    __declspec(dllexport) unsigned crsdk_diag_runtime(wchar_t* buf, unsigned buf_cch) {
        struct Item { const wchar_t* name; DWORD err; bool ok; } items[] = {
            {L"Cr_Core.dll",0,false},{L"Cr_PTP_USB.dll",0,false},{L"Cr_PTP_IP.dll",0,false},
            {L"libusb-1.0.dll",0,false},{L"libssh2.dll",0,false},
        };
        unsigned mask = 0;
        for (unsigned i = 0; i < _countof(items); ++i) {
            DWORD e = 0; HMODULE h = try_load(items[i].name, &e);
            items[i].ok = (h != nullptr); items[i].err = items[i].ok ? 0 : e;
            if (!items[i].ok) mask |= (1u << i);
        }
        if (buf && buf_cch) {
            std::wstring s = L"missing=";
            for (auto& it : items) if (!it.ok) {
                wchar_t t[96];
                _snwprintf_s(t, _countof(t), _TRUNCATE, L"%s(0x%08X) ", it.name, it.err); s += t;
            }
            if (s.size() == 8) s += L"none";
            wcsncpy_s(buf, buf_cch, s.c_str(), _TRUNCATE);
        }
        dlog(L"diag_runtime mask=0x%X", mask);
        return mask;
    }

    __declspec(dllexport) const wchar_t* crsdk_strerror(int rc) {
        static thread_local wchar_t buf[64];
        if (rc == 0) return L"OK";
        _snwprintf_s(buf, _countof(buf), _TRUNCATE, L"CrError=%d", rc);
        return buf;
    }

    __declspec(dllexport) int crsdk_get_build_info(wchar_t* buf, unsigned buf_cch) {
        if (!buf || !buf_cch) return -1;
        std::wstring s = L"crsdk_pybridge " + std::wstring(BUILD_STAMP);
        wcsncpy_s(buf, buf_cch, s.c_str(), _TRUNCATE);
        return 0;
    }

    __declspec(dllexport) int crsdk_enum_count(void) {
        SCRSDK::ICrEnumCameraObjectInfo* en = nullptr;
        dlog(L"EnumCameraObjects(timeout=%u)", 10u);
        SCRSDK::CrError er = SCRSDK::EnumCameraObjects(&en, (CrInt8u)10u);
        if (er != SCRSDK::CrError_None || !en) { dlog(L"EnumCameraObjects er=%d", (int)er); return er ? -((int)er) : -10; }
        CrInt32u cnt = en->GetCount(); dlog(L"EnumCameraObjects ok, count=%u", (unsigned)cnt);
        en->Release(); return (int)cnt;
    }

    __declspec(dllexport) int crsdk_enum_dump(wchar_t* buf, unsigned cch) {
        if (!buf || !cch) return -1; buf[0] = 0;
        SCRSDK::ICrEnumCameraObjectInfo* en = nullptr; dlog(L"EnumCameraObjects(timeout=%u) for dump", 10u);
        SCRSDK::CrError er = SCRSDK::EnumCameraObjects(&en, (CrInt8u)10u);
        if (er != SCRSDK::CrError_None || !en) {
            wchar_t t[64]; _snwprintf_s(t, _countof(t), _TRUNCATE, L"Enum er=%d", (int)er);
            wcsncpy_s(buf, cch, t, _TRUNCATE); dlog(L"Enum dump er=%d", (int)er); return (int)er ? (int)er : -10;
        }
        const CrInt32u n = en->GetCount();
        for (CrInt32u i = 0; i < n; ++i) {
            const SCRSDK::ICrCameraObjectInfo* info = en->GetCameraObjectInfo(i); if (!info) continue;
            const CrChar* name = info->GetName(); const CrChar* guid = info->GetGuid(); wchar_t line[512];
            _snwprintf_s(line, _countof(line), _TRUNCATE, L"[%u] name=%ls guid=%ls\r\n", i, W(name), W(guid)); wcsncat_s(buf, cch, line, _TRUNCATE);
        }
        en->Release(); return (int)n;
    }

    __declspec(dllexport) unsigned crsdk_status(void* handle) {
        CamCtx* ctx = reinterpret_cast<CamCtx*>(handle);
        if (!ctx) return 0;
        unsigned m = 0;
        if (ctx->dev) m |= 1u << 0;
        if (ctx->connected.load()) m |= 1u << 1;
        if (ctx->lv_on) m |= 1u << 2;
        return m;
    }
    __declspec(dllexport) int crsdk_last_cb_error(void* handle) {
        CamCtx* ctx = reinterpret_cast<CamCtx*>(handle);
        if (!ctx) return 0;
        return ctx->last_cb_err.load(std::memory_order_relaxed);
    }

    // --- connect (normal) ---
    __declspec(dllexport) int crsdk_connect_first(void** out_handle) {
        if (!out_handle) return -2; *out_handle = nullptr;

        SCRSDK::ICrEnumCameraObjectInfo* enumInfo = nullptr;
        dlog(L"EnumCameraObjects(timeout=%u) for connect", 10u);
        SCRSDK::CrError er = SCRSDK::EnumCameraObjects(&enumInfo, (CrInt8u)10u);
        if (er != SCRSDK::CrError_None || !enumInfo) { dlog(L"EnumCameraObjects er=%d", (int)er); return (int)er ? (int)er : -10; }

        CrInt32u count = enumInfo->GetCount(); dlog(L"Enum count=%u", (unsigned)count);
        if (count == 0) { enumInfo->Release(); dlog(L"No cameras"); return 1; }
        const SCRSDK::ICrCameraObjectInfo* info = enumInfo->GetCameraObjectInfo(0);
        if (!info) { enumInfo->Release(); dlog(L"GetCameraObjectInfo(0)=nullptr"); return 1; }

        CamCtx* ctx = new(std::nothrow) CamCtx();
        if (!ctx) { enumInfo->Release(); return -100; }

        SCRSDK::CrDeviceHandle dev = 0;
        er = SCRSDK::Connect(const_cast<SCRSDK::ICrCameraObjectInfo*>(info),
            &ctx->cb, &dev,
            SCRSDK::CrSdkControlMode_Remote,
            SCRSDK::CrReconnecting_ON,
            nullptr, nullptr, nullptr, 0);
        enumInfo->Release();

        if (er != SCRSDK::CrError_None) { delete ctx; dlog(L"Connect er=%d", (int)er); return (int)er; }
        ctx->dev = dev;

        if (wait_connected(ctx, 7000) != 0) {
            dlog(L"Connect but not ready (no OnConnected)");
            SCRSDK::Disconnect(ctx->dev);
            SCRSDK::ReleaseDevice(ctx->dev);
            delete ctx;
            return -3; // wait timeout
        }

        (void)SCRSDK::SetDeviceSetting(ctx->dev, (CrInt32u)SCRSDK::Setting_Key_EnableLiveView, 1u);
        dlog(L"Connected handle=%llu", (unsigned long long)ctx->dev);
        *out_handle = ctx;
        return 0;
    }

    // --- connect (diagnostic) ---
    __declspec(dllexport) int crsdk_connect_first_dbg(
        void** out_handle, int* out_enum_rc, unsigned* out_enum_cnt,
        int* out_connect_rc, unsigned* out_wait_ms, unsigned* out_status_bits, int* out_last_cb_err)
    {
        if (out_handle) *out_handle = nullptr;
        if (out_enum_rc) *out_enum_rc = 0;
        if (out_enum_cnt) *out_enum_cnt = 0;
        if (out_connect_rc) *out_connect_rc = 0;
        if (out_wait_ms) *out_wait_ms = 0;
        if (out_status_bits) *out_status_bits = 0;
        if (out_last_cb_err) *out_last_cb_err = 0;

        SCRSDK::ICrEnumCameraObjectInfo* enumInfo = nullptr;
        SCRSDK::CrError er_enum = SCRSDK::EnumCameraObjects(&enumInfo, (CrInt8u)10u);
        if (out_enum_rc) *out_enum_rc = (int)er_enum;
        if (er_enum != SCRSDK::CrError_None || !enumInfo) return (int)er_enum ? (int)er_enum : -10;

        CrInt32u count = enumInfo->GetCount();
        if (out_enum_cnt) *out_enum_cnt = (unsigned)count;
        if (count == 0) { enumInfo->Release(); return 1; }

        const SCRSDK::ICrCameraObjectInfo* info = enumInfo->GetCameraObjectInfo(0);
        if (!info) { enumInfo->Release(); return 1; }

        CamCtx* ctx = new(std::nothrow) CamCtx();
        if (!ctx) { enumInfo->Release(); return -100; }

        SCRSDK::CrDeviceHandle dev = 0;
        SCRSDK::CrError er_conn = SCRSDK::Connect(const_cast<SCRSDK::ICrCameraObjectInfo*>(info),
            &ctx->cb, &dev, SCRSDK::CrSdkControlMode_Remote, SCRSDK::CrReconnecting_ON,
            nullptr, nullptr, nullptr, 0);
        enumInfo->Release();
        if (out_connect_rc) *out_connect_rc = (int)er_conn;

        if (er_conn != SCRSDK::CrError_None) { delete ctx; return (int)er_conn; }
        ctx->dev = dev;

        DWORD waited = 7000;
        int wrc = wait_connected(ctx, waited);
        if (out_wait_ms) *out_wait_ms = waited;
        if (wrc != 0) {
            if (out_last_cb_err) *out_last_cb_err = ctx->last_cb_err.load();
            SCRSDK::Disconnect(ctx->dev); SCRSDK::ReleaseDevice(ctx->dev); delete ctx;
            return -3;
        }

        (void)SCRSDK::SetDeviceSetting(ctx->dev, (CrInt32u)SCRSDK::Setting_Key_EnableLiveView, 1u);
        if (out_status_bits) *out_status_bits = 0b011u;
        if (out_handle) *out_handle = ctx;
        return 0;
    }

    __declspec(dllexport) void crsdk_disconnect(void* handle) {
        CamCtx* ctx = reinterpret_cast<CamCtx*>(handle);
        if (!ctx) return;
        if (ctx->dev) { SCRSDK::Disconnect(ctx->dev); SCRSDK::ReleaseDevice(ctx->dev); ctx->dev = 0; }
        delete ctx; dlog(L"Disconnected");
    }

    __declspec(dllexport) int crsdk_enable_liveview(void* handle, int enable) {
        CamCtx* ctx = reinterpret_cast<CamCtx*>(handle);
        if (!ctx || !ctx->dev) return -2;
        SCRSDK::CrError er = SCRSDK::SetDeviceSetting(ctx->dev, (CrInt32u)SCRSDK::Setting_Key_EnableLiveView, enable ? 1u : 0u);
        if (er == SCRSDK::CrError_None) ctx->lv_on = (enable != 0);
        dlog(L"Enable LV=%d -> %d", enable, (int)er);
        return to_ret(er);
    }

    __declspec(dllexport) int crsdk_get_lv_info(void* handle, unsigned* out_nbytes) {
        CamCtx* ctx = reinterpret_cast<CamCtx*>(handle);
        if (!ctx || !ctx->dev || !out_nbytes) return -2;
        SCRSDK::CrImageInfo info{};
        SCRSDK::CrError er = SCRSDK::GetLiveViewImageInfo(ctx->dev, &info);
        if (er != SCRSDK::CrError_None) { *out_nbytes = 0; dlog(L"GetLVInfo er=%d", (int)er); return (int)er; }
        *out_nbytes = (unsigned)info.GetBufferSize(); return 0;
    }

    // 컨테이너에서 실제 JPEG만 복사해 주는 버전
    __declspec(dllexport) int crsdk_get_lv_image(void* handle, void* out_buf, unsigned buf_size, unsigned* out_used) {
        CamCtx* ctx = reinterpret_cast<CamCtx*>(handle);
        if (!ctx || !ctx->dev || !out_buf || !out_used) return -2;

        std::vector<CrInt8u> tmp(buf_size);
        SCRSDK::CrImageDataBlock blk;
        blk.SetData(tmp.data());
        blk.SetSize((CrInt32u)buf_size);

        SCRSDK::CrError er = SCRSDK::GetLiveViewImage(ctx->dev, &blk);
        if (er != SCRSDK::CrError_None) {
            *out_used = 0;
            dlog(L"GetLVImage er=%d", (int)er);
            return (int)er;
        }

        const CrInt8u* jpeg_ptr = blk.GetImageData();   // 실제 JPEG 시작 주소
        CrInt32u jpeg_size = blk.GetImageSize();        // JPEG 바이트 수
        if (!jpeg_ptr || jpeg_size <= 0) { *out_used = 0; return 0; }

        if ((unsigned)jpeg_size > buf_size) jpeg_size = (CrInt32u)buf_size;
        std::memcpy(out_buf, jpeg_ptr, (size_t)jpeg_size);
        *out_used = (unsigned)jpeg_size;
        return 0;
    }

    __declspec(dllexport) int crsdk_shoot_one(void* handle, int /*save_to_host*/) {
        CamCtx* ctx = reinterpret_cast<CamCtx*>(handle);
        if (!ctx || !ctx->dev) return -2;
        SCRSDK::CrError e1 = SCRSDK::SendCommand(ctx->dev, (CrInt32u)SCRSDK::CrCommandId_Release, SCRSDK::CrCommandParam_Down);
        Sleep(120);
        SCRSDK::CrError e2 = SCRSDK::SendCommand(ctx->dev, (CrInt32u)SCRSDK::CrCommandId_Release, SCRSDK::CrCommandParam_Up);
        if (e1 != SCRSDK::CrError_None) return (int)e1;
        if (e2 != SCRSDK::CrError_None) return (int)e2;
        return 0;
    }

    // ------ NEW: 저장 모드/폴더/파일명 설정 (mutable buffer로 전달) ------
    __declspec(dllexport) int crsdk_set_save_info(void* handle, int save_mode, const char* host_dir, const char* file_name) {
        CamCtx* ctx = reinterpret_cast<CamCtx*>(handle);
        if (!ctx || !ctx->dev) return -2;
        SCRSDK::CrError er = call_SetSaveInfo(ctx->dev, host_dir, file_name, (CrInt32)save_mode);
        dlog(L"SetSaveInfo(mode=%d) -> %d", (int)save_mode, (int)er);
        return (int)er;
    }

    // error name helper
    __declspec(dllexport) int crsdk_error_name(int rc, wchar_t* buf, unsigned cch) {
        if (!buf || !cch) return -1;
        const wchar_t* s = L"";
        if (rc == (int)SCRSDK::CrError_None)                       s = L"CrError_None";
        else if (rc == (int)SCRSDK::CrError_Connect_TimeOut)       s = L"CrError_Connect_TimeOut";
        else if (rc == (int)SCRSDK::CrError_Reconnect_TimeOut)     s = L"CrError_Reconnect_TimeOut";
        else if (rc == (int)SCRSDK::CrError_Connect_Disconnected)  s = L"CrError_Connect_Disconnected";
        else { static thread_local wchar_t tmp[64]; _snwprintf_s(tmp, _countof(tmp), _TRUNCATE, L"CrError=%d", rc); s = tmp; }
        wcsncpy_s(buf, cch, s, _TRUNCATE); return 0;
    }

    // connect by USB serial (12 chars) — 실패 시 Enum 경로로 폴백
    __declspec(dllexport) int crsdk_connect_usb_serial(const char* ascii12, void** out_handle) {
        if (!out_handle) return -2; *out_handle = nullptr; if (!ascii12) return -2;
        CrInt8u serial12[SCRSDK::USB_SERIAL_LENGTH]{}; size_t i = 0; for (; i < SCRSDK::USB_SERIAL_LENGTH && ascii12[i]; ++i) serial12[i] = (CrInt8u)ascii12[i];
        if (i != SCRSDK::USB_SERIAL_LENGTH) return -2;

        SCRSDK::ICrCameraObjectInfo* info = nullptr;
        SCRSDK::CrError er = SCRSDK::CreateCameraObjectInfoUSBConnection(&info, SCRSDK::CrCameraDeviceModel_ILCE_7C, serial12);
        if (er != SCRSDK::CrError_None || !info) return (int)er ? (int)er : -20;

        CamCtx* ctx = new(std::nothrow) CamCtx(); if (!ctx) { info->Release(); return -100; }
        SCRSDK::CrDeviceHandle dev = 0;
        er = SCRSDK::Connect(info, &ctx->cb, &dev, SCRSDK::CrSdkControlMode_Remote, SCRSDK::CrReconnecting_ON, nullptr, nullptr, nullptr, 0);
        info->Release();
        if (er != SCRSDK::CrError_None) { delete ctx; return (int)er; }

        ctx->dev = dev;
        if (wait_connected(ctx, 7000) != 0) {
            SCRSDK::Disconnect(ctx->dev);
            SCRSDK::ReleaseDevice(ctx->dev);
            delete ctx;
            // 폴백: 일반 Enum 방식
            return crsdk_connect_first(out_handle);
        }
        (void)SCRSDK::SetDeviceSetting(ctx->dev, (CrInt32u)SCRSDK::Setting_Key_EnableLiveView, 1u);
        *out_handle = ctx;
        return 0;
    }

    // LiveView smoke (save optional)
    __declspec(dllexport) int crsdk_lv_smoke(void* handle, const wchar_t* save_path, unsigned* out_bytes) {
        if (out_bytes) *out_bytes = 0;
        CamCtx* ctx = reinterpret_cast<CamCtx*>(handle);
        if (!ctx || !ctx->dev) return -2;

        SCRSDK::CrError er = SCRSDK::SetDeviceSetting(ctx->dev, (CrInt32u)SCRSDK::Setting_Key_EnableLiveView, 1u);
        if (er != SCRSDK::CrError_None) return (int)er;
        ctx->lv_on = true;
        Sleep(200);

        SCRSDK::CrImageInfo info{}; SCRSDK::CrError er_info = (SCRSDK::CrError)0, er_img = (SCRSDK::CrError)0;
        for (int t = 0; t < 80; ++t) {
            er_info = SCRSDK::GetLiveViewImageInfo(ctx->dev, &info);
            if (is_disconnected(er_info)) return (int)er_info;
            if (is_timeout(er_info)) { Sleep(80); continue; }

            if (er_info == SCRSDK::CrError_None && info.GetBufferSize() > 0) {
                std::vector<CrInt8u> buf((size_t)info.GetBufferSize());
                SCRSDK::CrImageDataBlock blk; blk.SetData(buf.data()); blk.SetSize(info.GetBufferSize());

                er_img = SCRSDK::GetLiveViewImage(ctx->dev, &blk);
                if (is_disconnected(er_img)) return (int)er_img;
                if (is_timeout(er_img)) { Sleep(80); continue; }

                const CrInt32u used = blk.GetImageSize();
                const void* p = blk.GetImageData();

                if (er_img == SCRSDK::CrError_None && p && used > 0) {
                    if (out_bytes) *out_bytes = (unsigned)used;
                    if (save_path && save_path[0]) {
                        FILE* fp = nullptr; _wfopen_s(&fp, save_path, L"wb");
                        if (fp) {
                            fwrite(p, 1, (size_t)used, fp);
                            fflush(fp);
                            HANDLE hf = (HANDLE)_get_osfhandle(_fileno(fp));
                            if (hf != INVALID_HANDLE_VALUE) FlushFileBuffers(hf);
                            fclose(fp);
                        }
                    }
                    return 0;
                }
            }
            Sleep(80);
        }
        return (int)(er_img ? er_img : (er_info ? er_info : -3));
    }

    // LiveView smoke (debug numbers)
    __declspec(dllexport) int crsdk_lv_smoke_dbg(void* handle, unsigned* out_rc_info, unsigned* out_rc_img, unsigned* out_bytes) {
        if (out_rc_info) *out_rc_info = 0;
        if (out_rc_img)  *out_rc_img = 0;
        if (out_bytes)   *out_bytes = 0;

        CamCtx* ctx = reinterpret_cast<CamCtx*>(handle);
        if (!ctx || !ctx->dev) return -2;

        SCRSDK::CrError er = SCRSDK::SetDeviceSetting(ctx->dev, (CrInt32u)SCRSDK::Setting_Key_EnableLiveView, 1u);
        if (er != SCRSDK::CrError_None) return (int)er;
        ctx->lv_on = true; Sleep(200);

        SCRSDK::CrImageInfo info{}; SCRSDK::CrError er_info = (SCRSDK::CrError)0, er_img = (SCRSDK::CrError)0;
        for (int t = 0; t < 80; ++t) {
            er_info = SCRSDK::GetLiveViewImageInfo(ctx->dev, &info);
            if (is_disconnected(er_info)) { if (out_rc_info) *out_rc_info = (unsigned)er_info; return (int)er_info; }
            if (is_timeout(er_info)) { Sleep(80); continue; }

            if (er_info == SCRSDK::CrError_None && info.GetBufferSize() > 0) {
                std::vector<CrInt8u> buf((size_t)info.GetBufferSize());
                SCRSDK::CrImageDataBlock blk; blk.SetData(buf.data()); blk.SetSize(info.GetBufferSize());
                er_img = SCRSDK::GetLiveViewImage(ctx->dev, &blk);

                if (is_disconnected(er_img)) { if (out_rc_img) *out_rc_img = (unsigned)er_img; return (int)er_img; }
                if (is_timeout(er_img)) { Sleep(80); continue; }

                if (er_img == SCRSDK::CrError_None && blk.GetImageSize() > 0) {
                    if (out_bytes) *out_bytes = (unsigned)blk.GetImageSize();
                    if (out_rc_info) *out_rc_info = 0;
                    if (out_rc_img)  *out_rc_img = 0;
                    return 0;
                }
            }
            Sleep(80);
        }
        if (out_rc_info) *out_rc_info = (unsigned)er_info;
        if (out_rc_img)  *out_rc_img = (unsigned)er_img;
        return (int)(er_img ? er_img : (er_info ? er_info : -3));
    }

} // extern "C"
