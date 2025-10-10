# -*- coding: utf-8 -*-
# LiveViewService: Sony CRSDK live‑view → QImage (emit via Qt signal)
from __future__ import annotations

import os, ctypes as C, threading, time
from typing import Optional, Callable

from PySide6.QtCore import QObject, Signal, Qt
from PySide6.QtGui import QImage

# ---- DLL load ---------------------------------------------------------------
_PROJ_DLL = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
                         "crsdk_pybridge.dll")
_DLL_PATH = os.environ.get("CRSDK_DLL",
                           _PROJ_DLL if os.path.exists(_PROJ_DLL) else "crsdk_pybridge.dll")
_d = C.CDLL(_DLL_PATH)

# ---- signatures --------------------------------------------------------------
_d.crsdk_set_debug.argtypes = [C.c_int]; _d.crsdk_set_debug.restype = None
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

def _log(s: str) -> None: print(f"[LV] {s}")

class LiveViewService(QObject):
    frameReady    = Signal(QImage)   # 프레임(QImage)
    statusChanged = Signal(str)      # 'sdk' | 'off'

    def __init__(self, parent: Optional[QObject] = None):
        super().__init__(parent)
        self.mode = "off"
        self.ms_sdk = 33
        self._stop = threading.Event()
        self._th: Optional[threading.Thread] = None
        self._h = C.c_void_p()
        self._cb: Optional[Callable[[QImage], None]] = None

    # 외부 설정
    def configure(self, _lv_dir: str, ms_sdk: int, _ms_file: int, _fallback_ms: int = 3000) -> None:
        try: self.ms_sdk = max(16, int(ms_sdk))
        except Exception: self.ms_sdk = 33

    # 비동기 시작 (즉시 반환)
    def start(self, on_qimage: Callable[[QImage], None],
              serial: Optional[str] = None, dll_debug: bool = False) -> bool:
        self.stop()
        try: self.frameReady.disconnect()
        except Exception: pass
        self._cb = on_qimage
        if on_qimage:
            try: self.frameReady.connect(on_qimage, Qt.ConnectionType.QueuedConnection)
            except Exception: self.frameReady.connect(on_qimage)

        self._stop.clear()
        self._th = threading.Thread(target=self._worker, args=(dll_debug,), daemon=True)
        self._th.start()
        return True

    def stop(self) -> None:
        self._stop.set()
        if self._th:
            self._th.join(timeout=1.0)
            self._th = None
        try: self.frameReady.disconnect()
        except Exception: pass
        self._cb = None
        self._cleanup()
        self._set_mode("off")

    # ---- worker (백그라운드) -----------------------------------------------
    def _worker(self, dll_debug: bool):
        try:
            try: _d.crsdk_set_debug(1 if dll_debug else 0)
            except Exception: pass

            if _d.crsdk_init() != 0:
                _log("init failed"); return

            h = C.c_void_p()
            rc = _d.crsdk_connect_first(C.byref(h))
            _log(f"dll={_DLL_PATH}")
            _log(f"connect rc={rc} handle=0x{h.value or 0:X}")
            if rc != 0 or not h.value:
                _d.crsdk_release(); return
            self._h = h

            _d.crsdk_enable_liveview(self._h, 1)
            self._set_mode("sdk")  # LED 초록불 먼저

            # 웜업 & 프레임 루프(전부 백그라운드)
            need = C.c_uint(0)
            buf = None
            last_kick = 0.0
            gap = self.ms_sdk / 1000.0

            while not self._stop.is_set():
                if buf is None:
                    if _d.crsdk_get_lv_info(self._h, C.byref(need)) == 0 and need.value > 0:
                        buf = (C.c_ubyte * int(need.value))()
                        _log(f"lv_info need={need.value}")
                    else:
                        # 간헐적 0일 때 재가동 킥(1초 주기)
                        now = time.time()
                        if now - last_kick > 1.0:
                            try: _d.crsdk_enable_liveview(self._h, 1)
                            except Exception: pass
                            last_kick = now
                        time.sleep(0.08)
                        continue

                used = C.c_uint(0)
                rc = _d.crsdk_get_lv_image(self._h, C.cast(buf, C.c_void_p),
                                           C.c_uint(len(buf)), C.byref(used))
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
                        self.frameReady.emit(img)
                time.sleep(gap)
        finally:
            self._cleanup()
            self._set_mode("off")

    # ---- helpers ------------------------------------------------------------
    def _cleanup(self):
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

    def _set_mode(self, m: str):
        m = m if m in ("sdk","off") else "off"
        if self.mode != m:
            self.mode = m
            self.statusChanged.emit(m)
