# -*- coding: utf-8 -*-
from __future__ import annotations
import os, ctypes as C
from ctypes import wintypes as W
from typing import Optional

# DLL 로드
_DLL_PATH = os.environ.get("CRSDK_DLL", "crsdk_pybridge.dll")
_d = C.CDLL(_DLL_PATH)

# ---- prototypes ----
_d.crsdk_set_debug.argtypes = [C.c_int]; _d.crsdk_set_debug.restype = None
_d.crsdk_init.restype = C.c_int
_d.crsdk_release.restype = None

_d.crsdk_connect_first.argtypes  = [C.POINTER(C.c_void_p)]
_d.crsdk_connect_first.restype   = C.c_int
_d.crsdk_connect_usb_serial.argtypes = [C.c_char_p, C.POINTER(C.c_void_p)]
_d.crsdk_connect_usb_serial.restype  = C.c_int
_d.crsdk_disconnect.argtypes = [C.c_void_p]; _d.crsdk_disconnect.restype = None

_d.crsdk_enable_liveview.argtypes = [C.c_void_p, C.c_int]
_d.crsdk_enable_liveview.restype  = C.c_int
_d.crsdk_get_lv_info.argtypes     = [C.c_void_p, C.POINTER(C.c_uint)]
_d.crsdk_get_lv_info.restype      = C.c_int
_d.crsdk_get_lv_image.argtypes    = [C.c_void_p, C.c_void_p, C.c_uint, C.POINTER(C.c_uint)]
_d.crsdk_get_lv_image.restype     = C.c_int

_d.crsdk_shoot_one.argtypes = [C.c_void_p, C.c_int]
_d.crsdk_shoot_one.restype  = C.c_int

# (있으면 사용) AF/AWB
try:
    _d.crsdk_one_shot_af.argtypes = [C.c_void_p]; _d.crsdk_one_shot_af.restype = C.c_int
except Exception:
    _d.crsdk_one_shot_af = None
try:
    _d.crsdk_one_shot_awb.argtypes = [C.c_void_p]; _d.crsdk_one_shot_awb.restype = C.c_int
except Exception:
    _d.crsdk_one_shot_awb = None

# (이번에 추가한) 저장/다운로드 관련
try:
    _d.crsdk_set_save_and_proxy.argtypes = [C.c_void_p, C.c_int, C.c_int]
    _d.crsdk_set_save_and_proxy.restype  = C.c_int
    _d.crsdk_set_download_dir.argtypes   = [W.LPCWSTR]
    _d.crsdk_set_download_dir.restype    = C.c_int
    _d.crsdk_get_last_saved_jpeg.argtypes = [C.c_void_p, W.LPWSTR, C.c_uint]
    _d.crsdk_get_last_saved_jpeg.restype  = C.c_int
except Exception:
    _d.crsdk_set_save_and_proxy = None
    _d.crsdk_set_download_dir   = None
    _d.crsdk_get_last_saved_jpeg = None


class SDKCamera:
    """CRSDK 제어 래퍼 (라이브뷰+촬영+다운로드)"""
    def __init__(self, dll_debug: bool=False):
        self.h = C.c_void_p()
        try: _d.crsdk_set_debug(1 if dll_debug else 0)
        except Exception: pass

    # --- 연결/해제 ---
    def open(self, serial: Optional[str]=None) -> None:
        if _d.crsdk_init() != 0:
            raise RuntimeError("crsdk_init failed")
        rc = 0
        if serial:
            rc = _d.crsdk_connect_usb_serial(serial.encode("ascii"), C.byref(self.h))
        else:
            rc = _d.crsdk_connect_first(C.byref(self.h))
        if rc != 0 or not self.h.value:
            _d.crsdk_release()
            raise RuntimeError(f"connect failed rc={rc}")

    def close(self) -> None:
        try:
            if self.h.value:
                _d.crsdk_disconnect(self.h)
        finally:
            self.h = C.c_void_p()
            try: _d.crsdk_release()
            except Exception: pass

    # --- 라이브뷰 ---
    def start_lv(self) -> None:
        if not self.h.value: return
        _d.crsdk_enable_liveview(self.h, 1)

    def stop_lv(self) -> None:
        if not self.h.value: return
        _d.crsdk_enable_liveview(self.h, 0)

    def read_frame(self, timeout_sec: float=1.0) -> bytes | None:
        """JPEG 바이트 반환 (없으면 None)"""
        if not self.h.value: return None
        need = C.c_uint(0)
        if _d.crsdk_get_lv_info(self.h, C.byref(need)) != 0 or need.value == 0:
            return None
        buf = (C.c_ubyte * need.value)()
        used = C.c_uint(0)
        rc = _d.crsdk_get_lv_image(self.h, C.cast(buf, C.c_void_p), need.value, C.byref(used))
        if rc == 0 and used.value:
            return bytes(memoryview(buf)[:used.value])
        return None

    # --- AF / AWB / 촬영 ---
    def one_shot_af(self) -> bool:
        if getattr(_d, "crsdk_one_shot_af", None):
            return _d.crsdk_one_shot_af(self.h) == 0
        return False

    def one_shot_awb(self) -> bool:
        if getattr(_d, "crsdk_one_shot_awb", None):
            return _d.crsdk_one_shot_awb(self.h) == 0
        return False

    def shoot_one(self) -> bool:
        if not self.h.value: return False
        return _d.crsdk_shoot_one(self.h, 0) == 0

    # --- 저장/다운로드 설정 ---
    def set_save_and_proxy(self, save_to_card: bool=True, proxy_to_pc: bool=True) -> bool:
        fn = getattr(_d, "crsdk_set_save_and_proxy", None)
        if not fn or not self.h.value: return False
        return fn(self.h, 1 if save_to_card else 0, 1 if proxy_to_pc else 0) == 0

    def set_download_dir(self, path: str) -> bool:
        fn = getattr(_d, "crsdk_set_download_dir", None)
        if not fn: return False
        return fn(path) == 0

    def download_latest(self) -> Optional[str]:
        fn = getattr(_d, "crsdk_get_last_saved_jpeg", None)
        if not fn or not self.h.value: return None
        out = C.create_unicode_buffer(1024)
        rc = fn(self.h, out, 1024)
        return out.value if rc == 0 and out.value else None

    # --- backward compat alias ----------------------------------------------------
# 예전 코드가 `CRSDKBridge`를 import 하더라도 동작하도록 얇은 래퍼를 둡니다.
__all__ = list(globals().get('__all__', [])) + ['CRSDKBridge']

class CRSDKBridge(SDKCamera):  # noqa: N801 (옛 이름 유지)
    """Backward‑compat alias for SDKCamera."""
    pass

