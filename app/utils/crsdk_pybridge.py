# -*- coding: utf-8 -*-
"""
ctypes 래퍼: crsdk_pybridge.dll
규약: 0=성공, 그 외 실패. DLL 경로: env CRSDK_DLL 또는 C:\dev\photostudio\crsdk_pybridge.dll
"""
import os, threading, time
import ctypes as C
from ctypes import c_int, c_uint, c_void_p, c_char_p, c_wchar_p, POINTER

# ----- 로드 -----
_DLL_PATH = os.environ.get("CRSDK_DLL", r"C:\dev\photostudio\crsdk_pybridge.dll")
_d = C.CDLL(_DLL_PATH)

def _sym(name):
    return getattr(_d, name, None)

def _b(s: str | None) -> bytes | None:
    if s is None: return None
    # DLL은 CP_ACP 기준. Windows에선 'mbcs'가 안전.
    return s.encode("mbcs", errors="ignore")

def error_name(rc: int) -> str:
    f = _sym("crsdk_error_name")
    if not f:
        return f"rc={rc}"
    f.argtypes = [c_int]; f.restype = c_char_p
    p = f(int(rc))
    try:
        return p.decode("utf-8") if p else f"rc={rc}"
    except Exception:
        return str(p or b"").decode(errors="ignore") or f"rc={rc}"

# ----- 시그니처 바인딩 -----
if _sym("crsdk_init"):               _d.crsdk_init.restype = c_int
if _sym("crsdk_release"):            _d.crsdk_release.restype = None
if _sym("crsdk_connect_first"):      _d.crsdk_connect_first.argtypes = [POINTER(c_void_p)]; _d.crsdk_connect_first.restype = c_int
if _sym("crsdk_disconnect"):         _d.crsdk_disconnect.argtypes = [c_void_p]; _d.crsdk_disconnect.restype = None

if _sym("crsdk_set_download_dir"):   _d.crsdk_set_download_dir.argtypes = [c_char_p]; _d.crsdk_set_download_dir.restype = c_int
if _sym("crsdk_set_save_info"):      _d.crsdk_set_save_info.argtypes = [c_void_p, c_int, c_char_p, c_char_p]; _d.crsdk_set_save_info.restype = c_int

if _sym("crsdk_enable_liveview"):    _d.crsdk_enable_liveview.argtypes = [c_void_p, c_int]; _d.crsdk_enable_liveview.restype = c_int
if _sym("crsdk_get_lv_info"):        _d.crsdk_get_lv_info.argtypes = [c_void_p, POINTER(c_uint)]; _d.crsdk_get_lv_info.restype = c_int
if _sym("crsdk_get_lv_image"):       _d.crsdk_get_lv_image.argtypes = [c_void_p, c_void_p, c_uint, POINTER(c_uint)]; _d.crsdk_get_lv_image.restype = c_int

if _sym("crsdk_shoot_one"):          _d.crsdk_shoot_one.argtypes = [c_void_p, c_int]; _d.crsdk_shoot_one.restype = c_int
if _sym("crsdk_one_shot_af"):        _d.crsdk_one_shot_af.argtypes = [c_void_p]; _d.crsdk_one_shot_af.restype = c_int
if _sym("crsdk_one_shot_awb"):       _d.crsdk_one_shot_awb.argtypes = [c_void_p]; _d.crsdk_one_shot_awb.restype = c_int

if _sym("crsdk_get_last_saved_jpeg"):
    _d.crsdk_get_last_saved_jpeg.argtypes = [c_void_p, c_wchar_p, c_uint]  # handle 미사용이면 None 전달 가능
    _d.crsdk_get_last_saved_jpeg.restype  = c_int

# 선택 진단
if _sym("crsdk_diag_runtime"):       _d.crsdk_diag_runtime.argtypes = [c_wchar_p, c_uint]; _d.crsdk_diag_runtime.restype = c_int
if _sym("crsdk_status"):             _d.crsdk_status.argtypes = [c_void_p]; _d.crsdk_status.restype = c_uint
if _sym("crsdk_last_cb_error"):      _d.crsdk_last_cb_error.argtypes = [c_void_p]; _d.crsdk_last_cb_error.restype = c_int

# ----- 상수 -----
SAVE_MODE_HOST = 2  # SDK 값에 맞춰 조정 필요 시 여기만 변경

# ----- 수명주기 -----
def init() -> int:
    f = _sym("crsdk_init")
    return int(f()) if f else -1

def release() -> None:
    f = _sym("crsdk_release")
    if f: f()

# ----- 연결 -----
def connect_first() -> c_void_p | None:
    f = _sym("crsdk_connect_first")
    if not f: return None
    out = c_void_p()
    rc = int(f(C.byref(out)))
    return out if rc == 0 and out.value else None

def disconnect(h: c_void_p | None) -> None:
    f = _sym("crsdk_disconnect")
    if f and h: f(h)

# ----- 저장/경로 -----
def set_download_dir(path: str) -> int:
    f = _sym("crsdk_set_download_dir")
    return int(f(_b(path))) if f else -1

def set_save_info(h: c_void_p, save_mode: int, host_dir: str | None, file_name: str | None) -> int:
    f = _sym("crsdk_set_save_info")
    return int(f(h, int(save_mode), _b(host_dir), _b(file_name))) if (f and h) else -1

def set_save_dir(h: c_void_p, path: str) -> int:
    rc1 = set_save_info(h, SAVE_MODE_HOST, path, None)
    rc2 = set_download_dir(path)
    return 0 if (rc1 == 0 and rc2 == 0) else (rc1 if rc1 != 0 else rc2)

# ----- 라이브뷰 -----
def enable_liveview(h: c_void_p, on: bool) -> int:
    f = _sym("crsdk_enable_liveview")
    return int(f(h, 1 if on else 0)) if (f and h) else -1

def get_lv_info(h: c_void_p) -> int:
    f = _sym("crsdk_get_lv_info")
    if not (f and h): return 0
    need = c_uint(0)
    rc = int(f(h, C.byref(need)))
    return int(need.value) if rc == 0 else 0

def get_lv_image(h: c_void_p) -> bytes:
    f = _sym("crsdk_get_lv_image")
    if not (f and h): return b""
    need = get_lv_info(h)
    if need <= 0: return b""
    buf = C.create_string_buffer(max(need, 4096))
    used = c_uint(0)
    rc = int(f(h, C.byref(buf), c_uint(len(buf)), C.byref(used)))
    if rc != 0 or used.value == 0: return b""
    return bytes(buf.raw[:used.value])

# ----- 촬영/AF/AWB -----
def one_shot_af(h: c_void_p) -> int:
    f = _sym("crsdk_one_shot_af")
    return int(f(h)) if (f and h) else -1

def one_shot_awb(h: c_void_p) -> int:
    f = _sym("crsdk_one_shot_awb")
    return int(f(h)) if (f and h) else -24  # 미지원 기본

def shoot_one(h: c_void_p) -> int:
    f = _sym("crsdk_shoot_one")
    return int(f(h, 0)) if (f and h) else -1

def get_last_saved_jpeg(out_dir: str) -> str | None:
    # 탐색 기준 폴더 지정
    set_download_dir(out_dir)
    f = _sym("crsdk_get_last_saved_jpeg")
    if not f: return None
    buf = C.create_unicode_buffer(520)
    rc = int(f(None, buf, c_uint(len(buf))))
    return buf.value if rc == 0 and buf.value else None

# ----- 선택 진단 -----
def diag_runtime() -> tuple[int, str]:
    f = _sym("crsdk_diag_runtime")
    if not f: return (-1, "")
    buf = C.create_unicode_buffer(512)
    rc = int(f(buf, c_uint(len(buf))))
    return (rc, buf.value or "")

def status_bits(h: c_void_p) -> int:
    f = _sym("crsdk_status")
    return int(f(h)) if (f and h) else 0

def last_cb_error(h: c_void_p) -> int:
    f = _sym("crsdk_last_cb_error")
    return int(f(h)) if (f and h) else 0

# ----- 선택: 풀러 스레드 -----
class _LVThread(threading.Thread):
    def __init__(self, h: c_void_p, cb, fps: int = 15):
        super().__init__(daemon=True)
        self.h, self.cb = h, cb
        self._run = True
        self._dt = 1.0 / max(1, fps)
    def stop(self): self._run = False
    def run(self):
        nxt = time.perf_counter()
        while self._run:
            b = get_lv_image(self.h)
            if b and callable(self.cb):
                try: self.cb(b)
                except Exception: pass
            nxt += self._dt
            time.sleep(max(0, nxt - time.perf_counter()))

_lv_thread: _LVThread | None = None

def start(h: c_void_p, on_frame, fps: int = 15) -> None:
    global _lv_thread
    stop()
    _lv_thread = _LVThread(h, on_frame, fps=fps)
    _lv_thread.start()

def stop() -> None:
    global _lv_thread
    t = _lv_thread
    _lv_thread = None
    if t: 
        try: t.stop()
        except Exception: pass
