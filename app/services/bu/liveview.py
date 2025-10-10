# -*- coding: utf-8 -*-
# app/services/liveview.py
# 1줄 요약: SDK 우선으로 프레임을 공급하고 1초 정지 시 파일 폴백으로 전환.
"""
[수정 로그]
- 2025-09-22 v2: SDK→파일 폴백 전환, 상태 시그널, QImage 변환 안정화.
- 2025-09-22 v1: 최소 동작 버전.
"""
from __future__ import annotations
import os, time, glob
from pathlib import Path
from typing import Optional, Tuple

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QImage

# 호환 import 경로
from app.utils.control_camera import CRSDKBridge

class LiveViewService(QObject):
    """3~5줄 요약
    - SDK 프레임을 주기적으로 가져와 QImage로 내보낸다.
    - SDK가 1초 이상 정지하면 LiveView*.JPG 파일 폴백으로 전환한다.
    - mode: 'sdk'|'file'|'off' 로 LED에 전달한다.
    - start(on_qimage=...)로 콜백을 연결할 수 있다.
    """
    frameReady = Signal(QImage)
    statusChanged = Signal(str)

    def __init__(self, page_obj: object, settings: Optional[dict] = None) -> None:
        super().__init__(parent=page_obj)          # ✅ 올바른 parent
        self._page = page_obj

        # 선택: 간단 디버그 헬퍼
        self._dbg = bool(os.environ.get("PHOTOSTUDIO_DEBUG"))
        def d(msg): 
            if self._dbg: print(f"[LVS] {msg}")
        self._d = d
        self._d("ctor")
        self._cb = None
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.mode = 'off'
        self._last_img: Optional[QImage] = None  # PATCH: cache

        # 설정
        self._settings = settings or getattr(page_obj, "settings", {}) or {}
        paths = (self._settings.get("paths") or {})
        self._lv_dir = str(paths.get("liveview_dir") or r"C:\PhotoBox\lv")
        Path(self._lv_dir).mkdir(parents=True, exist_ok=True)
        os.environ["CRSDK_LV_DIR"] = self._lv_dir

        lvset = (self._settings.get("liveview") or {})
        ms = lvset.get("ms") or {}
        self._ms_sdk = int(ms.get("sdk", 33))
        self._ms_file = int(ms.get("file", 48))
        self._fallback_ms = int(lvset.get("fallback_ms", 1000))

        # 런타임
        self._sdk: Optional[CRSDKBridge] = None
        self.cam: Optional[CRSDKBridge] = None  # 외부 노출 별칭
        self._last_sdk_ms = 0
        self._last_file_sig: Tuple[str, float] = ("", 0.0)

    # 1줄 역할: 동작 파라미터 갱신
    def configure(self, lv_dir: Optional[str] = None, ms_sdk: Optional[int] = None, ms_file: Optional[int] = None, *, fallback_ms: Optional[int] = None) -> None:
        """[수정 로그] 2025-09-22 최초 추가."""
        if lv_dir:
            self._lv_dir = str(lv_dir)
            Path(self._lv_dir).mkdir(parents=True, exist_ok=True)
            os.environ["CRSDK_LV_DIR"] = self._lv_dir
        if ms_sdk: self._ms_sdk = int(ms_sdk)
        if ms_file: self._ms_file = int(ms_file)
        if fallback_ms: self._fallback_ms = int(fallback_ms)

    # 1줄 역할: 시작
    def start(self, on_qimage=None, *, sdk_dir: Optional[str] = None, ms_sdk: Optional[int] = None, ms_file: Optional[int] = None) -> bool:
        self._cb = on_qimage
        self.configure(sdk_dir, ms_sdk, ms_file)
        self._sdk = CRSDKBridge(lv_dir=self._lv_dir, debug=False)
        self.cam = self._sdk
        ok = bool(self._sdk and self._sdk.connect())
        if ok:
            self._sdk.enable_liveview(True)
            self.mode = 'sdk'
            self.statusChanged.emit(self.mode)
            self._last_sdk_ms = int(time.time() * 1000)
            self._timer.start(self._ms_sdk)
            return True
        else:
            self.mode = 'file'
            self.statusChanged.emit(self.mode)
            self._timer.start(self._ms_file)
            self._emit_file_once()  # ▶ 폴백 진입 즉시 한 프레임
            return False


    # 1줄 역할: 중지
    def stop(self) -> None:
        """[수정 로그] 2025-09-22 타이머 정지 및 연결 해제."""
        try:
            self._timer.stop()
        except Exception:
            pass
        try:
            if self._sdk:
                self._sdk.enable_liveview(False)
                self._sdk.disconnect()
        except Exception:
            pass
        self.mode = 'off'
        self.statusChanged.emit(self.mode)

    # 내부: SDK 프레임 시도
    def _try_sdk(self) -> Optional[QImage]:
        if not self._sdk:
            return None
        ok, data = self._sdk.get_frame()
        if not ok or not data:
            return None
        img = QImage.fromData(data, "JPG")
        if img.isNull():
            return None
        self._last_sdk_ms = int(time.time() * 1000)
        return img

    # 내부: 파일 폴백 프레임 시도
    def _try_file(self) -> Optional[QImage]:
        p = Path(self._lv_dir) / "Disconnected.jpg"
        if not p.exists():
            return None
        try:
            mt = p.stat().st_mtime
            sig = (str(p), mt)
            if sig == self._last_file_sig:
                return None  # 동일 파일이면 스킵
            self._last_file_sig = sig
            data = p.read_bytes()
            img = QImage.fromData(data, "JPG")
            return img if not img.isNull() else None
        except Exception:
            return None


    # 타이머 틱
    def _tick(self) -> None:
        now_ms = int(time.time() * 1000)
        if self.mode == 'sdk':
            img = self._try_sdk()
            if img is not None:
                self._emit(img); return
            if now_ms - self._last_sdk_ms >= max(500, self._fallback_ms):
                self.mode = 'file'
                self.statusChanged.emit(self.mode)
                self._timer.start(self._ms_file)
                self._emit_file_once()  # ▶ 전환 즉시 1회
                return
        elif self.mode == 'file':
            img = self._try_file()
            if img is not None:
                self._emit(img)
            s = self._try_sdk()
            if s is not None:
                self.mode = 'sdk'
                self.statusChanged.emit(self.mode)
                self._timer.start(self._ms_sdk)
                self._emit(s)

    def _load_image(self, path: str) -> Optional[QImage]:
        try:
            data = Path(path).read_bytes()
            img = QImage.fromData(data, "JPG")
            return img if not img.isNull() else None
        except Exception:
            return None

    def _emit_file_once(self) -> None:
        # Disconnected.jpg 우선, 없으면 _try_file 시도
        img = self._load_image(str(Path(self._lv_dir) / "Disconnected.jpg")) or self._try_file()
        if img is not None:
            # 최초 1회는 중복 검사 없이 강제 표시되도록 서명 리셋
            self._last_file_sig = ("", 0.0)
            self._emit(img)

    # 내부: 프레임 내보내기
    def _emit(self, img: QImage) -> None:
        self.frameReady.emit(img)
        if callable(self._cb):
            try:
                self._cb(img)
            except Exception:
                pass