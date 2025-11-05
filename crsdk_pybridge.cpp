// crsdk_pybridge.cpp — Sony Camera Remote SDK v2.0 bridge (DLL)
// Build: x64, C++17, /MD, Unicode
// Include: <SDK>\app\CRSDK   Link: Cr_Core.lib

// 보안/매크로 충돌 방지 매크로를 가장 먼저 선언한다.
// - _CRT_SECURE_NO_WARNINGS: MSVC의 getenv 보안 경고(C4996) 무시
// - NOMINMAX: <windows.h>에서 정의하는 min/max 매크로로 인한 std::min/max 충돌 방지
#ifndef _CRT_SECURE_NO_WARNINGS
#define _CRT_SECURE_NO_WARNINGS 1
#endif
#ifndef NOMINMAX
#define NOMINMAX 1
#endif

#include <windows.h>
#include <cstdint>
#include <cwchar>
#include <cstdarg>
#include <string>
#include <atomic>
#include <new>
#include <cstring>
#include <algorithm>   // std::max
#include <cctype>      // std::tolower / ::tolower
#include <cwctype>     // std::towlower
#include <vector>
#include <cstdio>
#include <io.h>
#include <filesystem>   // [ADD] 저장 폴더 생성 지원
#include <mutex>        // [ADD] 다운로드 경로 동시성 보호

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
// 다운로드 기준 폴더와 마지막 저장 파일 경로
static std::wstring g_download_dir = L"C\\:\\PhotoBox\\raw"; // 기본값
static std::wstring g_last_saved;
static std::mutex   g_dl_mu;

// ===== LiveView JPEG 가드: SOI~EOI 추출 + (옵션) DHT 삽입 =====
static inline long long _env_i64(const char* k, long long d) {
    if (const char* v = std::getenv(k)) { try { return std::stoll(v); } catch (...) {} }
    return d;
}
static inline bool _env_on(const char* k, bool d=false) {
    if (const char* v = std::getenv(k)) {
        std::string s(v); for (auto& c: s) c = (char)tolower((unsigned char)c);
        return (s=="1"||s=="true"||s=="on");
    }
    return d;
}

// 간단 기본 DHT 테이블(예시). 필요시 실제 표준 DHT로 교체 가능.
static const unsigned char kDefaultDHT_[] = {
    0xFF,0xC4,0x00,0x1F, 0x00,0x00,0x01,0x05,0x01,0x01,0x01,0x01,0x01,0x01,
    0x00,0x00,0x00,0x00,0x00,0x00,0x00
};
static bool _has_DHT(const unsigned char* p, size_t n) {
    for (size_t i=0;i+1<n;++i) if (p[i]==0xFF && p[i+1]==0xC4) return true; return false;
}
// SOI~EOI 구간만 추출. 필요 시 SOI 뒤에 기본 DHT 삽입.
static bool _extract_jpeg_guarded(const unsigned char* in, size_t inlen,
                                  std::vector<unsigned char>& out) {
    if (!in || inlen < 4) return false;
    size_t soi=(size_t)-1; for (size_t i=0;i+1<inlen;++i){ if(in[i]==0xFF && in[i+1]==0xD8){ soi=i; break; } }
    if (soi==(size_t)-1) return false;
    size_t eoi=(size_t)-1; for (size_t j=soi+2;j+1<inlen;++j){ if(in[j]==0xFF && in[j+1]==0xD9){ eoi=j+2; break; } }
    if (eoi==(size_t)-1 || eoi<=soi) return false;
    size_t seg = eoi - soi; if (seg < 2048) return false;
    out.assign(in+soi, in+eoi);
    if (_env_on("CAP_INJECT_DHT", true) && !_has_DHT(out.data(), out.size())) {
        if (out.size()>2 && out[0]==0xFF && out[1]==0xD8) {
            out.insert(out.begin()+2, std::begin(kDefaultDHT_), std::end(kDefaultDHT_));
        }
    }
    return true;
}


// ===== helpers =====
static std::wstring widen_from_acp(const char* s) {
    if (!s) return {};
    int n = MultiByteToWideChar(CP_ACP, 0, s, -1, nullptr, 0);
    if (n <= 1) return {};
    std::wstring w; w.resize(n - 1);
    MultiByteToWideChar(CP_ACP, 0, s, -1, w.data(), n);
    return w;
}

// UTF-8(또는 ACP 폴백) → UTF-16 변환을 수행한다.
static std::wstring to_wide(const char* s) {
    if (!s || !*s) return L"";
    int n = MultiByteToWideChar(CP_UTF8, 0, s, -1, nullptr, 0);
    if (n <= 0) n = MultiByteToWideChar(CP_ACP, 0, s, -1, nullptr, 0);
    std::wstring w; w.resize((size_t)std::max(0, n - 1));
    if (n > 0) {
        int m = MultiByteToWideChar((n > 0 ? CP_UTF8 : CP_ACP), 0, s, -1, &w[0], n);
        if (m > 0) w.resize((size_t)m - 1);
    }
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

    // 원샷 AF: TrackingOnAndAFOn Down→Up
    __declspec(dllexport) int crsdk_one_shot_af(void* handle) {
        CamCtx* ctx = reinterpret_cast<CamCtx*>(handle);
        if (!ctx || !ctx->dev) return -2;
        using namespace SCRSDK;
        CrError e1 = SendCommand(ctx->dev, (CrInt32u)CrCommandId_TrackingOnAndAFOn, CrCommandParam_Down);
        Sleep(180);
        CrError e2 = SendCommand(ctx->dev, (CrInt32u)CrCommandId_TrackingOnAndAFOn, CrCommandParam_Up);
        if (e1 != CrError_None) return (int)e1;
        if (e2 != CrError_None) return (int)e2;
        return 0;
    }

    // 원샷 AWB: SDK에직접명령부재→미지원고정
    __declspec(dllexport) int crsdk_one_shot_awb(void* /*handle*/) {
        // 안전 스텁: 헤더에 직접 명령 부재 시 미지원(-24)
        return -24; // not supported in this build
    }

    // 다운로드 기준 폴더만 별도 지정(호스트 스캔 기준)
    __declspec(dllexport) int crsdk_set_download_dir(const char* dir) {
        std::scoped_lock lk(g_dl_mu);
        g_download_dir = to_wide(dir);
        if (!g_download_dir.empty() && g_download_dir.back() == L'\\') g_download_dir.pop_back();
        dlog(L"set_download_dir: %ls", g_download_dir.c_str());
        return g_download_dir.empty() ? -2 : 0;
    }

    // 마지막 저장된 JPG 1개 반환(handle 미사용). 성공시 0, 경로 out_path(NUL 포함).
    __declspec(dllexport) int crsdk_get_last_saved_jpeg(void* /*handle*/, wchar_t* out_path, unsigned cch) {
        if (!out_path || cch == 0) return -2;
        std::wstring base;
        { std::scoped_lock lk(g_dl_mu); base = g_download_dir; }
        if (base.empty()) { out_path[0] = 0; return -3; }

        namespace fs = std::filesystem;
        std::error_code ec;
        fs::path best_p;
        fs::file_time_type best_t{};

        for (auto it = fs::directory_iterator(base, ec); !ec && it != fs::end(it); it.increment(ec)) {
            const fs::directory_entry& de = *it;
            if (ec) break;
            if (!de.is_regular_file(ec)) continue;
            auto ext = de.path().extension().wstring();
            for (auto& ch : ext) ch = (wchar_t)std::towlower(ch);
            if (ext != L".jpg" && ext != L".jpeg") continue;
            auto t = de.last_write_time(ec); if (ec) continue;
            if (best_p.empty() || t > best_t) { best_p = de.path(); best_t = t; }
        }

        if (best_p.empty()) { out_path[0] = 0; return 1; }
        wcsncpy_s(out_path, cch, best_p.c_str(), _TRUNCATE);
        { std::scoped_lock lk(g_dl_mu); g_last_saved = best_p.wstring(); }
        return 0;
    }

    // 편의 래퍼: 카메라 저장 모드를 호스트(SAVE_MODE_HOST=2 가정)로 설정하고,
    // 호스트 저장 폴더와 다운로드 기준 폴더를 동시에 지정한다.
    __declspec(dllexport) int crsdk_preset_host_save_dir(void* handle, const char* host_dir_utf8) {
        CamCtx* ctx = reinterpret_cast<CamCtx*>(handle);
        if (!ctx || !ctx->dev) return -2;
        const int SAVE_MODE_HOST = 2; // SDK의 Host 저장 모드 값 가정
        // SetSaveInfo: host_dir만 지정, 파일명은 자동
        SCRSDK::CrError er = call_SetSaveInfo(ctx->dev, host_dir_utf8, nullptr, (CrInt32)SAVE_MODE_HOST);
        // 다운로드 기준 폴더 동기화
        {
            std::lock_guard<std::mutex> lk(g_dl_mu);
            g_download_dir = to_wide(host_dir_utf8);
            if (!g_download_dir.empty() && g_download_dir.back() == L'\\') g_download_dir.pop_back();
        }
        try { if (!g_download_dir.empty()) std::filesystem::create_directories(g_download_dir); } catch (...) {}
        return (int)er;
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
        // 라이브뷰 초기에 SDK가 매우 작은 크기를 보고하는 경우가 있어 최소값을 강제한다.
        // - CRSDK_LV_MIN_BUF 환경변수로 오버라이드 가능(기본 256KB)
        // - 프레임가드(DHT) 활성 시 64바이트 여유
        unsigned need = (unsigned)info.GetBufferSize();
        unsigned min_need = (unsigned)_env_i64("CRSDK_LV_MIN_BUF", 256u * 1024u);
        if (need < min_need) need = min_need;
        if (_env_on("CRSDK_LV_GUARD", true) && _env_on("CAP_INJECT_DHT", true)) { need += 64u; }
        *out_nbytes = need;
        dlog(L"GetLVInfo bytes=%u(min=%u)", (unsigned)info.GetBufferSize(), need);
        return 0;
    }

    // 컨테이너에서 실제 JPEG만 복사해 주는 버전
    __declspec(dllexport) int crsdk_get_lv_image(void* handle, void* out_buf, unsigned buf_size, unsigned* out_used) {
        CamCtx* ctx = reinterpret_cast<CamCtx*>(handle);
        if (!ctx || !ctx->dev || !out_buf || !out_used) return -2;

        // SDK 요구 버퍼 크기 확인 후 내부 스크래치 버퍼를 충분히 확보한다.
        SCRSDK::CrImageInfo info{}; (void)SCRSDK::GetLiveViewImageInfo(ctx->dev, &info);
        unsigned need_sdk = (unsigned)info.GetBufferSize();
        unsigned min_scratch = (unsigned)_env_i64("CRSDK_LV_SCRATCH", 512u*1024u); // 기본 512KB
        unsigned scratch_sz = (std::max)((std::max)(buf_size, need_sdk), min_scratch);

        std::vector<CrInt8u> tmp(scratch_sz);
        SCRSDK::CrImageDataBlock blk;
        blk.SetData(tmp.data());
        blk.SetSize((CrInt32u)scratch_sz);

        // 라이브뷰 프레임은 시점에 따라 일시적으로 실패할 수 있으므로 짧게 재시도한다.
        SCRSDK::CrError er = (SCRSDK::CrError)0;
        int max_try = (int)_env_i64("CRSDK_LV_TRIES", 20);
        DWORD slp = (DWORD)_env_i64("CRSDK_LV_SLEEP_MS", 30);
        for (int t = 0; t < max_try; ++t) {
            er = SCRSDK::GetLiveViewImage(ctx->dev, &blk);
            if (er == SCRSDK::CrError_None) break;
            if (is_disconnected(er)) { *out_used = 0; dlog(L"GetLVImage disconnected er=%d", (int)er); return (int)er; }
            // 짧게 대기 후 재시도(초기 프레임/버퍼 전환 등 대비)
            Sleep(slp);
        }
        if (er != SCRSDK::CrError_None) {
            *out_used = 0;
            dlog(L"GetLVImage er=%d after %d tries", (int)er, max_try);
            return (int)er;
        }

        const CrInt8u* jpeg_ptr = blk.GetImageData();   // 실제 JPEG 시작 주소
        CrInt32u jpeg_size = blk.GetImageSize();        // JPEG 바이트 수
        if (!jpeg_ptr || jpeg_size <= 0) { *out_used = 0; return 0; }

        // 프레임가드: SOI~EOI 추출 + (옵션) DHT 삽입 적용 시도
        if (_env_on("CRSDK_LV_GUARD", true)) {
            std::vector<unsigned char> guarded;
            if (_extract_jpeg_guarded(reinterpret_cast<const unsigned char*>(jpeg_ptr), (size_t)jpeg_size, guarded)) {
                if (guarded.size() <= buf_size) {
                    std::memcpy(out_buf, guarded.data(), guarded.size());
                    *out_used = (unsigned)guarded.size();
                    dlog(L"LV guard OK: in=%u out=%u", (unsigned)jpeg_size, (unsigned)guarded.size());
                    return 0;
                }
                dlog(L"LV guard overflow: need=%u buf=%u -> fallback raw", (unsigned)guarded.size(), buf_size);
            }
            else {
                dlog(L"LV guard failed to extract JPEG (in=%u)", (unsigned)jpeg_size);
            }
        }

        unsigned to_copy = (unsigned)jpeg_size;
        if (to_copy > buf_size) { dlog(L"LV raw truncate: in=%u buf=%u", to_copy, buf_size); to_copy = buf_size; }
        if (to_copy) std::memcpy(out_buf, jpeg_ptr, (size_t)to_copy);
        *out_used = to_copy;
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

    // 저장 폴더를 설정하고 호스트 저장 모드로 전환한다.
    // - path: UTF-8 경로 문자열
    // - 효과: SetSaveInfo(SAVE_MODE_HOST) 호출 + 다운로드 기준 폴더 동기화
    __declspec(dllexport) int crsdk_set_save_dir(void* handle, const char* path) {
        CamCtx* ctx = reinterpret_cast<CamCtx*>(handle);
        if (!ctx || !ctx->dev) return -2;
        int save_mode_host = 2; // 프로젝트규약값사용
        int rc = (int)call_SetSaveInfo(ctx->dev, path, nullptr, (CrInt32)save_mode_host);
        {
            std::scoped_lock lk(g_dl_mu);
            g_download_dir = to_wide(path);
            if (!g_download_dir.empty() && g_download_dir.back() == L'\\') g_download_dir.pop_back();
        }
        dlog(L"set_save_dir: mode=%d path=%ls rc=%d", save_mode_host, g_download_dir.c_str(), rc);
        return rc;
    }

} // extern "C"
