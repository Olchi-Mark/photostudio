// probe_crsdk.cpp  —  CRSDK DLL 연결 점검용 콘솔
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <cstdio>    // std::wprintf
#include <cwchar>    // wide I/O

extern "C" {
    __declspec(dllimport) unsigned crsdk_diag_runtime(wchar_t*, unsigned);
    __declspec(dllimport) int      crsdk_init(void);
    __declspec(dllimport) int      crsdk_enum_count(void);
    __declspec(dllimport) int      crsdk_connect_first(void**);
    __declspec(dllimport) int      crsdk_connect_usb_serial(const char*, void**);
    __declspec(dllimport) unsigned crsdk_status(void*);
    __declspec(dllimport) void     crsdk_release(void);
}

int wmain(int argc, wchar_t** argv)
{
    wchar_t msg[256]{};
    unsigned mask = crsdk_diag_runtime(msg, 256);
    std::wprintf(L"[runtime] mask=0x%02X %ls\n", mask, msg);

    std::wprintf(L"init=%d\n", crsdk_init());
    std::wprintf(L"enum=%d\n", crsdk_enum_count());

    void* h = nullptr;
    int rc = 0;

    if (argc > 1) {
        char s[13] = {};                   // 12자리 USB 시리얼
        for (int i = 0; i < 12 && argv[1][i]; ++i) s[i] = (char)argv[1][i];
        rc = crsdk_connect_usb_serial(s, &h);
    }
    else {
        rc = crsdk_connect_first(&h);
    }

    std::wprintf(L"connect=%d handle=0x%p\n", rc, h);
    std::wprintf(L"status=0b%03u\n", crsdk_status(h));

    crsdk_release();
    return 0;
}
