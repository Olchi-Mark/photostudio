# sdk_probe.py — CRSDK DLL 연결/라이브뷰 스모크 테스트(+enum_dump/직결/에러명)
from __future__ import annotations
import os, ctypes as C, argparse, time
from pathlib import Path

DLL_NAME = "crsdk_pybridge.dll"
DEFAULT_LV_DIR = r"C:\PhotoBox\lv"

def _candidate_dirs() -> list[Path]:
    cand = []
    cwd = Path.cwd(); script = Path(__file__).resolve().parent
    env_dir = os.getenv("CRSDK_DLL_DIR") or ""
    fixed = r"C:\CrSDK_v2.00.00_20250805a_Win64\build\Release"
    cand += [cwd, script];  env_dir and cand.append(Path(env_dir));  cand.append(Path(fixed))
    out, seen = [], set()
    for p in cand:
        s = str(p).lower()
        if s not in seen: out.append(p); seen.add(s)
    return out

def _load_dll(verbose=False):
    dll = None; dll_path = None
    for base in _candidate_dirs():
        p = base / DLL_NAME
        if p.exists():
            try:
                verbose and print(f"[dll] trying: {p}")
                dll = C.CDLL(str(p)); dll_path = str(p); break
            except OSError as e: last = e
    if dll is None:
        try:
            verbose and print("[dll] trying from PATH")
            dll = C.CDLL(DLL_NAME); dll_path = "<PATH>"
        except OSError as e:
            verbose and print(f"[dll] load failed: {e}")
            return None, None

    # 필수
    dll.crsdk_init.restype = C.c_int
    dll.crsdk_set_debug.argtypes=[C.c_int]; dll.crsdk_set_debug.restype=None
    dll.crsdk_connect_first.argtypes=[C.POINTER(C.c_void_p)]; dll.crsdk_connect_first.restype=C.c_int
    dll.crsdk_disconnect.argtypes=[C.c_void_p]; dll.crsdk_disconnect.restype=None
    dll.crsdk_enable_liveview.argtypes=[C.c_void_p, C.c_int]; dll.crsdk_enable_liveview.restype=C.c_int
    dll.crsdk_get_lv_info.argtypes=[C.c_void_p, C.POINTER(C.c_uint)]; dll.crsdk_get_lv_info.restype=C.c_int
    dll.crsdk_get_lv_image.argtypes=[C.c_void_p, C.c_void_p, C.c_uint, C.POINTER(C.c_uint)]; dll.crsdk_get_lv_image.restype=C.c_int

    # 진단(있으면 사용)
    try:
        dll.crsdk_release.restype=None
        dll.crsdk_enum_count.restype=C.c_int
        dll.crsdk_status.argtypes=[C.c_void_p]; dll.crsdk_status.restype=C.c_uint
        dll.crsdk_last_cb_error.argtypes=[C.c_void_p]; dll.crsdk_last_cb_error.restype=C.c_int
        dll.crsdk_diag_runtime.argtypes=[C.c_wchar_p, C.c_uint]; dll.crsdk_diag_runtime.restype=C.c_uint
        dll.crsdk_strerror.argtypes=[C.c_int]; dll.crsdk_strerror.restype=C.c_wchar_p
        dll.crsdk_enum_dump.argtypes=[C.c_wchar_p, C.c_uint]; dll.crsdk_enum_dump.restype=C.c_int
        dll.crsdk_error_name.argtypes=[C.c_int, C.c_wchar_p, C.c_uint]; dll.crsdk_error_name.restype=C.c_int
        dll.crsdk_connect_usb_serial.argtypes=[C.c_char_p, C.POINTER(C.c_void_p)]; dll.crsdk_connect_usb_serial.restype=C.c_int
    except AttributeError:
        pass
    return dll, dll_path

def main():
    ap = argparse.ArgumentParser(add_help=False)
    ap.add_argument("-s","--save", default="probe_lv.jpg")
    ap.add_argument("-v","--verbose", action="store_true")
    args,_ = ap.parse_known_args()

    os.environ.setdefault("CRSDK_LV_DIR", DEFAULT_LV_DIR)

    dll, path = _load_dll(args.verbose)
    if dll is None:
        print("connected=False"); print("frame_ok=False bytes=0"); return
    args.verbose and print(f"[dll] loaded: {path}")

    try: dll.crsdk_set_debug(1)
    except Exception: pass

    msg = C.create_unicode_buffer(256)
    mask = dll.crsdk_diag_runtime(msg, 256)
    args.verbose and print(f"[runtime] mask=0x{mask:02X} {msg.value}")

    dll.crsdk_init()

    # 1) 열거 텍스트 덤프
    if hasattr(dll, "crsdk_enum_dump"):
        buf = C.create_unicode_buffer(2048)
        rc_dump = dll.crsdk_enum_dump(buf, 2048)
        if args.verbose: print(f"[enum_dump_rc] {rc_dump}"); print(buf.value)

    # 2) 열거 개수
    enum_cnt = dll.crsdk_enum_count() if hasattr(dll,"crsdk_enum_count") else None
    args.verbose and print(f"[enum_count] {enum_cnt} (note: negative = CrError)")

    # 3) 직결 우선(환경변수 CRSDK_USB_SERIAL 또는 기본 하드코드)
    h = C.c_void_p(); rc_conn = None
    if hasattr(dll, "crsdk_connect_usb_serial"):
        ser = os.getenv("CRSDK_USB_SERIAL","D005D075D6AA").encode("ascii")
        rc_conn = dll.crsdk_connect_usb_serial(ser, C.byref(h))
        args.verbose and print(f"[connect_usb_rc] {rc_conn} handle=0x{(h.value or 0):016X}")

    # 4) 실패 시 일반 연결
    if not h.value:
        rc_conn = dll.crsdk_connect_first(C.byref(h))
        args.verbose and print(f"[connect_rc] {rc_conn} {dll.crsdk_strerror(rc_conn) if hasattr(dll,'crsdk_strerror') else ''} handle=0x{(h.value or 0):016X}")

    st = dll.crsdk_status(h) if hasattr(dll,"crsdk_status") else 0
    ok_conn = bool(h.value) or bool(st & (1<<1))
    args.verbose and print(f"[status_bits] 0b{st:03b}")
    print(f"connected={str(ok_conn)}")

    if not ok_conn:
        print("frame_ok=False bytes=0")
        try: dll.crsdk_disconnect(h)
        finally:
            try: dll.crsdk_release()
            except Exception: pass
        return

    # LiveView
    dll.crsdk_enable_liveview(h, 1)
    need = C.c_uint(0); rc_info = -1
    for _ in range(80):
        rc_info = dll.crsdk_get_lv_info(h, C.byref(need))
        if rc_info == 0 and need.value > 0: break
        time.sleep(0.05)
    args.verbose and print(f"[lv_info_rc] {rc_info} bytes={need.value}")

    if rc_info != 0 or need.value == 0:
        print("frame_ok=False bytes=0")
        try: dll.crsdk_enable_liveview(h, 0)
        finally:
            try: dll.crsdk_disconnect(h)
            finally:
                try: dll.crsdk_release()
                except Exception: pass
        return

    buf = (C.c_ubyte * need.value)()
    used = C.c_uint(0)
    rc_img = dll.crsdk_get_lv_image(h, C.cast(buf, C.c_void_p), C.c_uint(need.value), C.byref(used))
    print(f"frame_ok={str(rc_img == 0 and used.value > 0)} bytes={used.value}")

    try: dll.crsdk_enable_liveview(h, 0)
    finally:
        try: dll.crsdk_disconnect(h)
        finally:
            try: dll.crsdk_release()
            except Exception: pass

if __name__ == "__main__":
    main()
