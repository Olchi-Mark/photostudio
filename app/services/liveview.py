# -*- coding: utf-8 -*-
# LiveViewService: Sony CRSDK live‑view → QImage (emit via Qt signal)
from __future__ import annotations

import os, ctypes as C, threading, time, logging
from typing import Optional, Callable

from PySide6.QtCore import QObject, Signal, Qt, QThread
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
# optional: shoot-one api (if dll supports)
try:
    _d.crsdk_shoot_one.argtypes = [C.c_void_p, C.c_int]
    _d.crsdk_shoot_one.restype  = C.c_int
except Exception:
    pass
# optional: smoke helper to kick LV
try:
    _d.crsdk_lv_smoke.argtypes = [C.c_void_p, C.c_wchar_p, C.POINTER(C.c_uint)]
    _d.crsdk_lv_smoke.restype  = C.c_int
except Exception:
    pass

# ---- timing constants --------------------------------------------------------
# 워밍업/폴링 타이밍 보강(느린 초기 카메라 대응)
WARMUP_MS      = 150   # enable 이후 초기 대기
POLL_MS        = 60    # info 폴링 간격
POLL_TOTAL_MS  = 8000  # 단계별 최대 대기 시간

# 로거: CODING.md 규칙에 따라 logging을 사용한다.
_logger = logging.getLogger("LV")

def _log(msg: str) -> None:
    """과거 호출 호환을 위한 단순 로그 래퍼."""
    try:
        _logger.info("[LV] %s", msg)
    except Exception:
        pass

def _log_info(msg: str) -> None:
    """정보 수준 로그를 기록한다."""
    try:
        _logger.info("[LV] %s", msg)
    except Exception:
        pass

def _logf_info(fmt: str, *args) -> None:
    """서식 문자열로 정보 로그를 기록한다."""
    try:
        _logger.info("[LV] " + fmt, *args)
    except Exception:
        pass

def _logf_debug(fmt: str, *args) -> None:
    """서식 문자열로 디버그 로그를 기록한다."""
    try:
        _logger.debug("[LV] " + fmt, *args)
    except Exception:
        pass

class _LiveViewThread(QThread):
    """백그라운드에서 CRSDK 라이브뷰를 처리한다."""
    frameReady    = Signal(QImage)
    statusChanged = Signal(str)

    def __init__(self, ms_sdk: int, dll_debug: bool):
        """폴링 주기와 디버그 옵션으로 스레드를 초기화한다."""
        super().__init__()
        self.ms_sdk = ms_sdk
        self._stop = threading.Event()
        self._h = C.c_void_p()
        self._dll_debug = dll_debug
        self._last_w = 0
        self._last_h = 0

    def stop_async(self) -> None:
        """중단 플래그를 설정하고 안전하게 인터럽트를 건다."""
        self._stop.set()
        try:
            self.requestInterruption()
        except Exception:
            pass

    def run(self):
        """CRSDK 연결→웨이크→활성화→폴링/프레임 송신을 수행한다."""
        try:
            try: _d.crsdk_set_debug(1 if self._dll_debug else 0)
            except Exception: pass

            if _d.crsdk_init() != 0:
                _log_info("init failed"); return

            h = C.c_void_p()
            rc = _d.crsdk_connect_first(C.byref(h))
            _logf_info("dll=%s", _DLL_PATH)
            _logf_info("connect rc=%s handle=0x%X", rc, (h.value or 0))
            if rc != 0 or not h.value:
                _d.crsdk_release(); return
            self._h = h

            # 연결 직후 웨이크(원샷 AF) 시도
            try:
                fn_af = getattr(_d, "crsdk_one_shot_af", None)
                if callable(fn_af):
                    try:
                        rc_af = int(fn_af(self._h))
                    except Exception:
                        rc_af = -1
                    _logf_info("wake rc=%s", rc_af)
            except Exception:
                pass

            t_enable = time.time()
            rc_en = _d.crsdk_enable_liveview(self._h, 1)
            _logf_info("enable rc=%s", rc_en)
            try:
                time.sleep(WARMUP_MS / 1000.0)
            except Exception:
                pass
            # Allow buffers to warm up before pulling info
            time.sleep(WARMUP_MS / 1000.0)
            self.statusChanged.emit("sdk")

            need = C.c_uint(0)
            buf = None
            last_kick = 0.0
            last_frame_ts = time.time()
            gap = self.ms_sdk / 1000.0

            # Phase 1: get_lv_info 폴링 (최대 3000ms, 50ms 간격)
            t0 = time.time()
            last_info_log = 0.0
            while buf is None and not self._stop.is_set() and ((time.time() - t0) * 1000.0) < POLL_TOTAL_MS:
                if _d.crsdk_get_lv_info(self._h, C.byref(need)) == 0:
                    t_ms = int((time.time() - t_enable) * 1000.0)
                    # info 단계: w/h는 마지막 알려진 값으로 기록 (디버그는 매틱, info는 초당 1회)
                    now = time.time()
                    if now - last_info_log >= 1.0:
                        _logf_info("info t=%s need=%s w=%s h=%s", t_ms, need.value, self._last_w, self._last_h)
                        last_info_log = now
                    else:
                        _logf_debug("info t=%s need=%s w=%s h=%s", t_ms, need.value, self._last_w, self._last_h)
                    if need.value > 0:
                        # prime read: need>0 이고 (w==0 or h==0)이면 1회 읽고 info 재조회
                        if self._last_w == 0 or self._last_h == 0:
                            pbuf = (C.c_ubyte * int(need.value))()
                            used_p = C.c_uint(0)
                            try:
                                rc_prime = _d.crsdk_get_lv_image(self._h, C.cast(pbuf, C.c_void_p), C.c_uint(int(need.value)), C.byref(used_p))
                            except Exception:
                                rc_prime = -1
                            _logf_info("prime rc=%s", rc_prime)
                            # 가능한 경우 크기 업데이트
                            if rc_prime == 0 and used_p.value:
                                try:
                                    data_p = bytes(memoryview(pbuf)[:used_p.value])
                                    img_p = QImage.fromData(data_p, "JPG")
                                    if not img_p.isNull():
                                        self._last_w, self._last_h = img_p.width(), img_p.height()
                                except Exception:
                                    pass
                            time.sleep(POLL_MS / 1000.0)
                            continue
                        buf = (C.c_ubyte * int(need.value))()
                        _logf_info("lv_info need=%s", need.value)
                        break
                time.sleep(POLL_MS / 1000.0)

            # Phase 2: 여전히 need==0이면 smoke 1회(+재시도) 후 재폴링
            if buf is None and not self._stop.is_set():
                # Guard: skip smoke if symbol missing
                if getattr(_d, "crsdk_lv_smoke", None) is None:
                    _log_info("smoke skip (symbol missing)")
                else:
                    try:
                        nbytes = C.c_uint(0)
                        rc_smoke = _d.crsdk_lv_smoke(self._h, None, C.byref(nbytes))
                        _logf_info("smoke rc=%s", rc_smoke)
                        if rc_smoke != 0:
                            time.sleep(0.12)
                            try:
                                nbytes2 = C.c_uint(0)
                                rc_smoke2 = _d.crsdk_lv_smoke(self._h, None, C.byref(nbytes2))
                                _logf_info("smoke2 rc=%s", rc_smoke2)
                            except Exception:
                                _log_info("smoke2 rc=ERR")
                    except Exception:
                        _log_info("smoke rc=ERR")
                t1 = time.time()
                last_info_log = 0.0
                while buf is None and not self._stop.is_set() and ((time.time() - t1) * 1000.0) < POLL_TOTAL_MS:
                    if _d.crsdk_get_lv_info(self._h, C.byref(need)) == 0:
                        t_ms = int((time.time() - t_enable) * 1000.0)
                        now = time.time()
                        if now - last_info_log >= 1.0:
                            _logf_info("info t=%s need=%s w=%s h=%s", t_ms, need.value, self._last_w, self._last_h)
                            last_info_log = now
                        else:
                            _logf_debug("info t=%s need=%s w=%s h=%s", t_ms, need.value, self._last_w, self._last_h)
                        if need.value > 0:
                            if self._last_w == 0 or self._last_h == 0:
                                pbuf = (C.c_ubyte * int(need.value))()
                                used_p = C.c_uint(0)
                                try:
                                    rc_prime = _d.crsdk_get_lv_image(self._h, C.cast(pbuf, C.c_void_p), C.c_uint(int(need.value)), C.byref(used_p))
                                except Exception:
                                    rc_prime = -1
                                _logf_info("prime rc=%s", rc_prime)
                                if rc_prime == 0 and used_p.value:
                                    try:
                                        data_p = bytes(memoryview(pbuf)[:used_p.value])
                                        img_p = QImage.fromData(data_p, "JPG")
                                        if not img_p.isNull():
                                            self._last_w, self._last_h = img_p.width(), img_p.height()
                                    except Exception:
                                        pass
                                time.sleep(POLL_MS / 1000.0)
                                continue
                            buf = (C.c_ubyte * int(need.value))()
                            _logf_info("lv_info need=%s", need.value)
                            break
                    time.sleep(POLL_MS / 1000.0)

            # Phase 3: 그래도 실패 시 재시작 시퀀스(0→1) 후 마지막 재폴링
            if buf is None and not self._stop.is_set():
                try:
                    _d.crsdk_enable_liveview(self._h, 0)
                except Exception:
                    pass
                time.sleep(0.120)
                try:
                    _d.crsdk_enable_liveview(self._h, 1)
                except Exception:
                    pass
                time.sleep(0.090)
                _log_info("restart 0→1")
                t2 = time.time()
                last_info_log = 0.0
                while buf is None and not self._stop.is_set() and ((time.time() - t2) * 1000.0) < POLL_TOTAL_MS:
                    if _d.crsdk_get_lv_info(self._h, C.byref(need)) == 0:
                        t_ms = int((time.time() - t_enable) * 1000.0)
                        now = time.time()
                        if now - last_info_log >= 1.0:
                            _logf_info("info t=%s need=%s w=%s h=%s", t_ms, need.value, self._last_w, self._last_h)
                            last_info_log = now
                        else:
                            _logf_debug("info t=%s need=%s w=%s h=%s", t_ms, need.value, self._last_w, self._last_h)
                        if need.value > 0:
                            if self._last_w == 0 or self._last_h == 0:
                                pbuf = (C.c_ubyte * int(need.value))()
                                used_p = C.c_uint(0)
                                try:
                                    rc_prime = _d.crsdk_get_lv_image(self._h, C.cast(pbuf, C.c_void_p), C.c_uint(int(need.value)), C.byref(used_p))
                                except Exception:
                                    rc_prime = -1
                                _logf_info("prime rc=%s", rc_prime)
                                if rc_prime == 0 and used_p.value:
                                    try:
                                        data_p = bytes(memoryview(pbuf)[:used_p.value])
                                        img_p = QImage.fromData(data_p, "JPG")
                                        if not img_p.isNull():
                                            self._last_w, self._last_h = img_p.width(), img_p.height()
                                    except Exception:
                                        pass
                                time.sleep(POLL_MS / 1000.0)
                                continue
                            buf = (C.c_ubyte * int(need.value))()
                            _logf_info("lv_info need=%s", need.value)
                            break
                    time.sleep(POLL_MS / 1000.0)

            while not self._stop.is_set():
                # keepalive: 마지막 프레임 이후 ≥1000ms 시 info 재조회로 1회 복구
                _now_ts = time.time()
                if (_now_ts - last_frame_ts) >= 1.0:
                    _need_k = C.c_uint(0)
                    try:
                        if _d.crsdk_get_lv_info(self._h, C.byref(_need_k)) == 0:
                            _log_info("keepalive recover")
                            if buf is None and _need_k.value > 0:
                                buf = (C.c_ubyte * int(_need_k.value))()
                                _logf_info("lv_info need=%s", _need_k.value)
                    except Exception:
                        pass
                    # 1회 복구 후 타이머 리셋
                    last_frame_ts = last_frame_ts
                if buf is None:
                    if _d.crsdk_get_lv_info(self._h, C.byref(need)) == 0 and need.value > 0:
                        buf = (C.c_ubyte * int(need.value))()
                        _logf_info("lv_info need=%s", need.value)
                    else:
                        # need==0 recovery: nudge LV periodically and wait a short while
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
                        # 마지막 알려진 w/h 갱신
                        try:
                            self._last_w, self._last_h = img.width(), img.height()
                        except Exception:
                            pass
                        # 마지막 프레임 시각 갱신
                        last_frame_ts = time.time()
                        if not hasattr(self, "_started_logged"):
                            t_started_ms = int((time.time() - t_enable) * 1000.0)
                            _logf_info("started in %s", t_started_ms)
                            self._started_logged = True
                        self.frameReady.emit(img)
                # 주기적 keepalive: 비차단으로 주기적으로 1을 재설정
                now = time.time()
                if now - last_kick > 2.0:
                    try:
                        _d.crsdk_enable_liveview(self._h, 1)
                    except Exception:
                        pass
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

# 라이브뷰를 비동기로 제공하는 서비스이다.
class LiveViewService(QObject):
    frameReady    = Signal(QImage)   # 프레임(QImage)
    statusChanged = Signal(str)      # 'sdk' | 'off'

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

    # 외부 설정
    # 라이브뷰 폴링 주기 등 설정을 적용한다.
    def configure(self, _lv_dir: str, ms_sdk: int, _ms_file: int, _fallback_ms: int = 3000) -> None:
        try: self.ms_sdk = max(16, int(ms_sdk))
        except Exception: self.ms_sdk = 33

    # 비동기 시작 (즉시 반환)
    # 라이브뷰를 시작하고 QImage 콜백을 연결한다.
    def start(self, on_qimage: Callable[[QImage], None],
              serial: Optional[str] = None, dll_debug: bool = False) -> bool:
        self.stop()
        try: self.frameReady.disconnect()
        except Exception: pass
        self._cb = on_qimage
        self._sig_cb_connected = False
        if on_qimage:
            try:
                self.frameReady.connect(on_qimage, Qt.ConnectionType.QueuedConnection)
            except Exception:
                self.frameReady.connect(on_qimage)
            self._sig_cb_connected = True

        # Start background QThread to handle SDK work without blocking UI
        self._stop.clear()
        self._th = _LiveViewThread(self.ms_sdk, dll_debug)
        # Enforce queued delivery from worker -> service
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
        self._th.start()
        return True

    # ---- capture helpers ---------------------------------------------------
    def shoot_one(self) -> int:
        """카메라 셔터를 1회 동작시킨다. 0=성공, 그 외 실패.
        - 워커 쓰레드의 CRSDK 핸들(_th._h)이 있으면 그 핸들로 호출한다.
        - 없다면 서비스 보유 핸들(_h) 시도.
        예외는 1줄 로그 후 -1 반환.
        """
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
                _log("shoot_one: no handle")
                return -1
            try:
                rc = int(_d.crsdk_shoot_one(h, 0))
            except Exception:
                rc = -1
            _logf_info("shoot rc=%s", rc)
            return 0 if rc == 0 else -1
        except Exception as ex:
            _logf_info("shoot err=%s", ex)
            return -1

    # 라이브뷰를 중단하고 연결된 신호를 해제한다.
    def stop(self) -> None:
        # Request stop but never block the UI thread waiting
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
        # Worker will cleanup SDK and emit statusChanged("off") on exit
        
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

    def _on_worker_status(self, m: str):
        # Keep internal mode in sync and re-emit
        self._set_mode(m)

    def _on_worker_frame(self, img: QImage):
        # Re-emit on the service signal; downstream callbacks are also queued
        self.frameReady.emit(img)
