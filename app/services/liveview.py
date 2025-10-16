                       
from __future__ import annotations
"""LiveViewService: Sony CRSDK ??繹먮끏???怨쀫뮛??QImage) ??⑥レ툓????筌먐삳４??"""

import os
import time
import threading
import ctypes as C
import logging
from typing import Optional, Callable

from PySide6.QtCore import QObject, Signal, Qt, QThread
from PySide6.QtGui import QImage

_PROJ_DLL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                         "crsdk_pybridge.dll")
_DLL_PATH = os.environ.get("CRSDK_DLL",
                           _PROJ_DLL if os.path.exists(_PROJ_DLL) else "crsdk_pybridge.dll")

_d = C.CDLL(_DLL_PATH)

try:
    _d.crsdk_set_debug.argtypes = [C.c_int]; _d.crsdk_set_debug.restype = None
except Exception:
    pass
_d.crsdk_init.restype = C.c_int
_d.crsdk_release.restype = None
_d.crsdk_connect_first.argtypes  = [C.POINTER(C.c_void_p)]
_d.crsdk_connect_first.restype   = C.c_int
_d.crsdk_disconnect.argtypes = [C.c_void_p]; _d.crsdk_disconnect.restype = None
_d.crsdk_enable_liveview.argtypes = [C.c_void_p, C.c_int]
_d.crsdk_enable_liveview.restype  = C.c_int
_d.crsdk_get_lv_info.argtypes     = [C.c_void_p, C.POINTER(C.c_uint)]
_d.crsdk_get_lv_info.restype      = C.c_int
_d.crsdk_get_lv_image.argtypes    = [C.c_void_p, C.c_void_p, C.c_uint, C.POINTER(C.c_uint)]
_d.crsdk_get_lv_image.restype     = C.c_int
try:
    _d.crsdk_shoot_one.argtypes = [C.c_void_p, C.c_int]
    _d.crsdk_shoot_one.restype  = C.c_int
except Exception:
    pass
try:
    _d.crsdk_connect_usb_serial.argtypes = [C.c_char_p, C.POINTER(C.c_void_p)]
    _d.crsdk_connect_usb_serial.restype  = C.c_int
except Exception:
    pass

WARMUP_MS      = 150
KEEPALIVE_SEC  = 2.0

_log = logging.getLogger("LV")


class _LiveViewThread(QThread):
    frameReady    = Signal(QImage)
    statusChanged = Signal(str)

    def __init__(self, ms_sdk: int, dll_debug: bool):
        super().__init__()
        self.ms_sdk = ms_sdk
        self._dll_debug = dll_debug
        self._stop = threading.Event()
        self._h = C.c_void_p()
        self._last_w = 0
        self._last_h = 0

    def stop_async(self) -> None:
        self._stop.set()
        try:
            self.requestInterruption()
        except Exception:
            pass

    def run(self):
        try:
            try:
                _d.crsdk_set_debug(1 if self._dll_debug else 0)
            except Exception:
                pass

            if _d.crsdk_init() != 0:
                _log.info("[LV] init failed"); return

            h = C.c_void_p()
            rc = -999
            # 연결 경로 선택: FORCE_ENUM(강제 열거) 또는 USB-Serial 우선 후 열거 폴백
            try:
                force_enum = str(os.environ.get("CRSDK_FORCE_ENUM", "")).strip().lower() in ("1","true","on")
            except Exception:
                force_enum = False
            try:
                serial = (os.environ.get("CRSDK_USB_SERIAL") or "").strip()
            except Exception:
                serial = ""

            if force_enum:
                # 강제 열거 모드: USB-Serial 경로를 건너뛰고 열거 연결만 시도
                try:
                    rc = int(_d.crsdk_connect_first(C.byref(h)))
                    _log.info("[LV] path=enum rc=%s handle=0x%X", rc, (h.value or 0))
                except Exception:
                    rc = -997
            else:
                # 기본: USB-Serial이 유효하면 우선 시도, 실패/미설정 시 열거 폴백
                if serial and len(serial) == 12 and getattr(_d, 'crsdk_connect_usb_serial', None):
                    try:
                        rc = int(_d.crsdk_connect_usb_serial(serial.encode('ascii','ignore'), C.byref(h)))
                        _log.info("[LV] path=usb-serial rc=%s serial=%s handle=0x%X", rc, serial, (h.value or 0))
                    except Exception:
                        rc = -998
                if (rc != 0) or (not h.value):
                    try:
                        rc = int(_d.crsdk_connect_first(C.byref(h)))
                        _log.info("[LV] path=fallback-enum rc=%s handle=0x%X", rc, (h.value or 0))
                    except Exception:
                        rc = -997

            _log.info("[LV] dll=%s", _DLL_PATH)
            _log.info("[LV] connect rc=%s handle=0x%X", rc, (h.value or 0))
            if rc != 0 or not h.value:
                try:
                    self.statusChanged.emit("off")
                except Exception:
                    pass
                _d.crsdk_release(); return
            self._h = h

            rc_en = _d.crsdk_enable_liveview(self._h, 1)
            _log.info("[LV] enable rc=%s", rc_en)
            time.sleep(WARMUP_MS / 1000.0)
            self.statusChanged.emit("sdk")

            need = C.c_uint(0)
            buf = None
            last_kick = 0.0
            gap = max(16, int(self.ms_sdk)) / 1000.0

            while not self._stop.is_set():
                if buf is None:
                    if _d.crsdk_get_lv_info(self._h, C.byref(need)) == 0 and need.value > 0:
                        buf = (C.c_ubyte * int(need.value))()
                        _log.info("[LV] lv_info need=%s", need.value)
                    else:
                        now = time.time()
                        if now - last_kick > KEEPALIVE_SEC:
                            try: _d.crsdk_enable_liveview(self._h, 1)
                            except Exception: pass
                            last_kick = now
                        time.sleep(0.08)
                        continue

                used = C.c_uint(0)
                rc = _d.crsdk_get_lv_image(self._h, C.cast(buf, C.c_void_p), C.c_uint(len(buf)), C.byref(used))
                if rc == 0 and used.value:
                    data = bytes(memoryview(buf)[:used.value])
                    img = QImage.fromData(data, "JPG")
                    if img.isNull():
                        try:
                            import numpy as np, cv2
                            arr = np.frombuffer(data, dtype=np.uint8)
                            bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                            if bgr is not None:
                                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                                h_, w_, _ = rgb.shape
                                img = QImage(rgb.data, w_, h_, 3*w_, QImage.Format_RGB888).copy()
                        except Exception:
                            img = QImage()
                    if not img.isNull():
                        try:
                            self._last_w, self._last_h = img.width(), img.height()
                        except Exception:
                            pass
                        self.frameReady.emit(img)

                now = time.time()
                if now - last_kick > KEEPALIVE_SEC:
                    try: _d.crsdk_enable_liveview(self._h, 1)
                    except Exception: pass
                    last_kick = now
                time.sleep(gap)
        finally:
            try:
                if self._h.value:
                    try: _d.crsdk_enable_liveview(self._h, 0)
                    except Exception: pass
                    try: _d.crsdk_disconnect(self._h)
                    except Exception: pass
            finally:
                try: _d.crsdk_release()
                except Exception: pass
                self._h = C.c_void_p()
            self.statusChanged.emit("off")


class LiveViewService(QObject):
    frameReady    = Signal(QImage)
    statusChanged = Signal(str)

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.mode = "off"
        self.ms_sdk = 33
        self._stop = threading.Event()
        self._th: Optional[_LiveViewThread] = None
        self._h = C.c_void_p()
        self._cb: Optional[Callable[[QImage], None]] = None
        self._sig_cb_connected = False
        self._sig_worker_connected = False

    def configure(self, _lv_dir: str, ms_sdk: int, _ms_file: int, _fallback_ms: int = 3000) -> None:
        try:
            self.ms_sdk = max(16, int(ms_sdk))
        except Exception:
            self.ms_sdk = 33

    def start(self, on_qimage: Optional[Callable[[QImage], None]] = None, dll_debug: bool = False) -> bool:
        self.stop()
        self._cb = on_qimage
        self._sig_cb_connected = False
        if on_qimage:
            try:
                self.frameReady.connect(on_qimage, Qt.ConnectionType.QueuedConnection)
            except Exception:
                self.frameReady.connect(on_qimage)
            self._sig_cb_connected = True

        self._stop.clear()
        self._th = _LiveViewThread(self.ms_sdk, dll_debug)
        try:
            self._th.frameReady.connect(self._on_worker_frame, Qt.ConnectionType.QueuedConnection)
        except Exception:
            self._th.frameReady.connect(self._on_worker_frame)
        try:
            self._th.statusChanged.connect(self._on_worker_status, Qt.ConnectionType.QueuedConnection)
        except Exception:
            self._th.statusChanged.connect(self._on_worker_status)
        self._sig_worker_connected = True
        try:
            self._th.finished.connect(lambda: setattr(self, "_th", None))
        except Exception:
            pass
        try:
            self._th.start()
            return True
        except Exception:
            return False

    def shoot_one(self) -> int:
        try:
            h = None
            try:
                if getattr(self, "_th", None) is not None:
                    h = getattr(self._th, "_h", None)
            except Exception:
                h = None
            if not h or not getattr(h, 'value', None):
                h = getattr(self, "_h", None)
            if not h or not getattr(h, 'value', None):
                _log.info("[LV] shoot_one: no handle")
                return -1
            try:
                rc = int(_d.crsdk_shoot_one(h, 0))
            except Exception:
                rc = -1
            _log.info("[LV] shoot rc=%s", rc)
            return 0 if rc == 0 else -1
        except Exception as ex:
            _log.info("[LV] shoot err=%s", ex)
            return -1

    def stop(self) -> None:
        self._stop.set()
        if self._th:
            try: self._th.stop_async()
            except Exception: pass
            if self._sig_worker_connected:
                try: self._th.frameReady.disconnect(self._on_worker_frame)
                except Exception: pass
                try: self._th.statusChanged.disconnect(self._on_worker_status)
                except Exception: pass
                self._sig_worker_connected = False
        if self._sig_cb_connected and self._cb is not None:
            try: self.frameReady.disconnect(self._cb)
            except Exception: pass
            self._sig_cb_connected = False
        self._cb = None

    def _set_mode(self, m: str):
        m = m if m in ("sdk", "off") else "off"
        if self.mode != m:
            self.mode = m
            self.statusChanged.emit(m)

    def _on_worker_status(self, m: str):
        self._set_mode(m)

    def _on_worker_frame(self, img: QImage):
        self.frameReady.emit(img)
