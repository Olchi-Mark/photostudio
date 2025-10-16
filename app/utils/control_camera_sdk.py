# -*- coding: utf-8 -*-
from __future__ import annotations
import os, ctypes as C, logging
from ctypes import wintypes as W
from ctypes import create_unicode_buffer
from typing import Optional

# DLL load
_DLL_PATH = os.environ.get("CRSDK_DLL", "crsdk_pybridge.dll")
_d = C.CDLL(_DLL_PATH)
# 로거: CODING.md의 로깅 규칙을 따른다.
_log = logging.getLogger("CRSDK")

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

# --- 안전 폴백 래퍼 ---
def _safe_one_shot_af(h: C.c_void_p) -> int:
    """AF 1회 실행(심볼 부재 시 -1 반환)."""
    if not '_HAS_AF' in globals() or not _HAS_AF:
        return -1
    try:
        return int(_d.crsdk_one_shot_af(h))
    except Exception:
        return -1

def _safe_one_shot_awb(h: C.c_void_p) -> int:
    """AWB 1회 실행(심볼 부재 시 -1 반환)."""
    if not '_HAS_AWB' in globals() or not _HAS_AWB:
        return -1
    try:
        return int(_d.crsdk_one_shot_awb(h))
    except Exception:
        return -1

def _safe_set_download_dir(path: str) -> int:
    """다운로드 경로 설정(심볼 부재 시 -1 반환)."""
    if not '_HAS_SAVE_DIR' in globals() or not _HAS_SAVE_DIR:
        return -1
    try:
        return int(_d.crsdk_set_download_dir(path.encode("utf-8")))
    except Exception:
        return -1

def _safe_get_last_saved_jpeg(h: C.c_void_p, out: C.c_wchar_p, cap: int) -> int:
    """최근 저장 JPEG 경로 조회(심볼 부재 시 -1 반환)."""
    if not '_HAS_LAST_SAVED' in globals() or not _HAS_LAST_SAVED:
        return -1
    try:
        return int(_d.crsdk_get_last_saved_jpeg(h, out, cap))
    except Exception:
        return -1


class SDKCamera:
    """CRSDK 제어(라이브뷰/촬영/다운로드)를 제공한다."""
    def __init__(self, dll_debug: bool=False):
        """DLL 디버그 모드 설정과 핸들을 초기화한다."""
        self.h = C.c_void_p()
        try: _d.crsdk_set_debug(1 if dll_debug else 0)
        except Exception: pass

    # --- open/close ---
    def open(self, serial: Optional[str]=None) -> None:
        """카메라 연결을 연다(시리얼 지정 또는 첫 장치)."""
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
        """카메라 연결을 닫고 SDK를 해제한다."""
        try:
            if self.h.value:
                _d.crsdk_disconnect(self.h)
        finally:
            self.h = C.c_void_p()
        try: _d.crsdk_release()
        except Exception: pass

    # convenience: bool-returning connect wrapper
    def connect_first(self, serial: Optional[str]=None) -> bool:
        try:
            self.open(serial=serial)
            return True
        except Exception:
            return False

    # --- liveview ---
    def start_lv(self) -> None:
        """라이브뷰를 활성화한다."""
        if not self.h.value: return
        _d.crsdk_enable_liveview(self.h, 1)

    def stop_lv(self) -> None:
        """라이브뷰를 비활성화한다."""
        if not self.h.value: return
        _d.crsdk_enable_liveview(self.h, 0)

    def read_frame(self, timeout_sec: float=1.0) -> bytes | None:
        """라이브뷰 프레임을 읽어 바이트로 반환한다."""
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
        """AF를 1회 수행한다(성공 시 True)."""
        rc = -1
        try:
            if getattr(self, "h", None):
                rc = _safe_one_shot_af(self.h)
        except Exception:
            rc = -1
        print(f"[SDK] AF rc={rc}")
        return rc == 0

    def one_shot_awb(self) -> bool:
        """AWB를 1회 수행한다(성공 시 True)."""
        rc = -1
        try:
            if getattr(self, "h", None):
                rc = _safe_one_shot_awb(self.h)
        except Exception:
            rc = -1
        print(f"[SDK] AWB rc={rc}")
        return rc == 0

    def shoot_one(self) -> bool:
        """정지 이미지를 1회 촬영한다."""
        if not self.h.value: return False
        return _d.crsdk_shoot_one(self.h, 0) == 0

    # --- Save/Download ---
    def set_save_and_proxy(self, save_to_card: bool=True, proxy_to_pc: bool=True) -> bool:
        """카드 저장/PC 프록시 옵션을 설정한다(선택 심볼)."""
        fn = getattr(_d, "crsdk_set_save_and_proxy", None)
        if not fn or not self.h.value: return False
        return fn(self.h, 1 if save_to_card else 0, 1 if proxy_to_pc else 0) == 0

    def set_download_dir(self, path: str) -> bool:
        """다운로드 저장 경로를 설정한다(심볼 부재 시 False)."""
        rc = -1
        try:
            rc = _safe_set_download_dir(path)
        except Exception:
            rc = -1
        print(f"[SDK] set_download_dir rc={rc} path={path}")
        return rc == 0

    def download_latest(self) -> Optional[str]:
        """최근 저장된 JPEG 경로를 반환한다(없거나 실패 시 None)."""
        return self.get_last_saved_jpeg()

    # Convenience wrappers
    def focus_once(self) -> tuple[bool, int]:
        """AF 1회 결과를 (성공, 코드)로 반환한다."""
        ok = self.one_shot_af()
        return ok, (0 if ok else -1)

    def awb_once(self) -> tuple[bool, int]:
        """AWB 1회 결과를 (성공, 코드)로 반환한다."""
        ok = self.one_shot_awb()
        return ok, (0 if ok else -1)

    def set_save_dir(self, path: str) -> bool:
        """다운로드 저장 경로 설정에 대한 별칭."""
        return self.set_download_dir(path)

    def get_last_saved_path(self) -> Optional[str]:
        """최근 저장된 JPEG 경로를 반환한다."""
        return self.download_latest()

    def get_last_saved_jpeg(self) -> Optional[str]:
        """최근 저장된 JPEG 경로를 반환한다(호환 목적)."""
        rc = -1
        path: Optional[str] = None
        try:
            if getattr(self, "h", None):
                out = create_unicode_buffer(512)
                rc = _safe_get_last_saved_jpeg(self.h, out, 512)
                path = out.value if rc == 0 and out.value else None
        except Exception:
            rc = -1
            path = None
        print(f"[SDK] last_saved rc={rc} val=\"{path}\"")
        return path


# 모듈 수준 간단 래퍼(호환성): enable_liveview/get_lv_info/get_lv_image
def enable_liveview(h: C.c_void_p, on: bool) -> int:
    """라이브뷰 On/Off(성공 0, 실패 -1)."""
    try:
        return int(_d.crsdk_enable_liveview(h, 1 if on else 0))
    except Exception:
        return -1

def get_lv_info(h: C.c_void_p) -> int:
    """라이브뷰 필요 바이트 수(실패 0)."""
    try:
        need = C.c_uint(0)
        rc = int(_d.crsdk_get_lv_info(h, C.byref(need)))
        return int(need.value) if rc == 0 else 0
    except Exception:
        return 0

def get_lv_image(h: C.c_void_p) -> bytes:
    """라이브뷰 프레임 바이트(실패 빈 바이트)."""
    try:
        need = C.c_uint(0)
        if _d.crsdk_get_lv_info(h, C.byref(need)) != 0 or need.value == 0:
            return b""
        buf = (C.c_ubyte * int(need.value))()
        used = C.c_uint(0)
        rc = int(_d.crsdk_get_lv_image(h, C.cast(buf, C.c_void_p), C.c_uint(len(buf)), C.byref(used)))
        if rc == 0 and used.value:
            return bytes(memoryview(buf)[: used.value])
    except Exception:
        return b""
    return b""

__all__ = list(globals().get('__all__', [])) + ['CRSDKBridge']
class CRSDKBridge(SDKCamera):  # noqa: N801
    """호환성을 위한 SDKCamera의 별칭 클래스이다."""
    pass

__all__ = list(globals().get('__all__', []))

class ControlCameraSDK(SDKCamera):
    """호환성을 위한 SDKCamera 별칭(식별자 유지)."""
    pass

__all__ += ['CRSDKBridge', 'ControlCameraSDK']
