# -*- coding: utf-8 -*-
from __future__ import annotations
import os, ctypes as C
from ctypes import wintypes as W
from ctypes import create_unicode_buffer
from typing import Optional

# DLL load
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

# --- new bindings ---
try:
    _d.crsdk_one_shot_af.argtypes = [C.c_void_p]
    _d.crsdk_one_shot_af.restype  = C.c_int
    _HAS_AF = True
except AttributeError:
    _HAS_AF = False

try:
    _d.crsdk_one_shot_awb.argtypes = [C.c_void_p]
    _d.crsdk_one_shot_awb.restype  = C.c_int
    _HAS_AWB = True
except AttributeError:
    _HAS_AWB = False

try:
    _d.crsdk_set_download_dir.argtypes = [C.c_char_p]
    _d.crsdk_set_download_dir.restype  = C.c_int
    _HAS_SAVE_DIR = True
except AttributeError:
    _HAS_SAVE_DIR = False

try:
    _d.crsdk_get_last_saved_jpeg.argtypes = [C.c_void_p, C.c_wchar_p, C.c_uint]
    _d.crsdk_get_last_saved_jpeg.restype  = C.c_int
    _HAS_LAST_SAVED = True
except AttributeError:
    _HAS_LAST_SAVED = False

# optional capture/proxy
try:
    _d.crsdk_set_save_and_proxy.argtypes = [C.c_void_p, C.c_int, C.c_int]
    _d.crsdk_set_save_and_proxy.restype  = C.c_int
except Exception:
    _d.crsdk_set_save_and_proxy = None


class SDKCamera:
    """CRSDK control (liveview + shoot + download)"""
    def __init__(self, dll_debug: bool=False):
        self.h = C.c_void_p()
        try: _d.crsdk_set_debug(1 if dll_debug else 0)
        except Exception: pass

    # --- open/close ---
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

    # --- liveview ---
    def start_lv(self) -> None:
        if not self.h.value: return
        _d.crsdk_enable_liveview(self.h, 1)

    def stop_lv(self) -> None:
        if not self.h.value: return
        _d.crsdk_enable_liveview(self.h, 0)

    def read_frame(self, timeout_sec: float=1.0) -> bytes | None:
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

    # --- AF / AWB / Shoot ---
    def one_shot_af(self) -> bool:
        if not getattr(self, "h", None) or not _HAS_AF:
            print("[SDK] af_once rc=-1")
            return False
        try:
            rc = int(_d.crsdk_one_shot_af(self.h))
        except Exception:
            rc = -1
        print(f"[SDK] af_once rc={rc}")
        return rc == 0

    def one_shot_awb(self) -> bool:
        if not getattr(self, "h", None) or not _HAS_AWB:
            print("[SDK] awb_once rc=-1")
            return False
        try:
            rc = int(_d.crsdk_one_shot_awb(self.h))
        except Exception:
            rc = -1
        print(f"[SDK] awb_once rc={rc}")
        return rc == 0

    def shoot_one(self) -> bool:
        if not self.h.value: return False
        return _d.crsdk_shoot_one(self.h, 0) == 0

    # --- Save/Download ---
    def set_save_and_proxy(self, save_to_card: bool=True, proxy_to_pc: bool=True) -> bool:
        fn = getattr(_d, "crsdk_set_save_and_proxy", None)
        if not fn or not self.h.value: return False
        return fn(self.h, 1 if save_to_card else 0, 1 if proxy_to_pc else 0) == 0

    def set_download_dir(self, path: str) -> bool:
        if not _HAS_SAVE_DIR:
            print(f"[SDK] save_dir={path} ok=False")
            return False
        ok = False
        try:
            ok = (_d.crsdk_set_download_dir(path.encode("utf-8")) == 0)
        except Exception:
            ok = False
        print(f"[SDK] save_dir={path} ok={ok}")
        return bool(ok)

    def download_latest(self) -> Optional[str]:
        if not getattr(self, "h", None) or not _HAS_LAST_SAVED:
            return None
        try:
            out = create_unicode_buffer(512)
            rc = _d.crsdk_get_last_saved_jpeg(self.h, out, 512)
            path = out.value if rc == 0 and out.value else None
            if path:
                print(f"[SDK] saved path={path}")
            return path
        except Exception:
            return None

    # Convenience wrappers
    def focus_once(self) -> tuple[bool, int]:
        ok = self.one_shot_af()
        return ok, (0 if ok else -1)

    def awb_once(self) -> tuple[bool, int]:
        ok = self.one_shot_awb()
        return ok, (0 if ok else -1)

    def set_save_dir(self, path: str) -> bool:
        return self.set_download_dir(path)

    def get_last_saved_path(self) -> Optional[str]:
        return self.download_latest()

    def get_last_saved_jpeg(self) -> Optional[str]:
        return self.download_latest()


__all__ = list(globals().get('__all__', [])) + ['CRSDKBridge']
class CRSDKBridge(SDKCamera):  # noqa: N801
    """Backward-compat alias for SDKCamera."""
    pass
