# app/utils/pose_engine.py
# -*- coding: utf-8 -*-
"""
PoseEngine: MediaPipe Pose Landmarker wrapper
- 입력: QImage 또는 ndarray, (w,h), timestamp(ms)
- 출력: resultReady(payload: dict, size: tuple[int,int], normalized: bool)
  payload(normalized=True):
  {
    "shoulder_L": (x,y), "shoulder_R": (x,y),
    "shoulder_support": [(x,y)*9]
  }
"""
from __future__ import annotations
from typing import Optional, Tuple, Dict, Any
from PySide6.QtCore import QObject, Signal


class PoseEngine(QObject):
    resultReady = Signal(dict, tuple, bool)

    def __init__(self, model_path: Optional[str] = None, *, running_mode: str = "VIDEO", parent: Optional[QObject] = None):
        super().__init__(parent)
        self._model_path = model_path or "app/utils/models/pose_landmarker_full.task"
        self._running = False
        self._mp = None
        self._vision = None
        self._landmarker = None
        self._running_mode = running_mode.upper()
        self._target_height = 1008  # 세로 고정 높이(px). 항상 적용.
        self._busy = False  # 처리 중이면 프레임 드롭.
  # 처리 중이면 프레임 드롭.

    def start(self) -> None:
        self._running = True
        if self._landmarker is None:
            self._init_mp()

    def stop(self) -> None:
        self._running = False

    def set_model_path(self, path: str) -> None:
        self._model_path = path
        self._release()
        print(f"[PoseEngine] model path set to: {path}")

    def process_frame(self, frame: object, size: Tuple[int, int], ts_ms: Optional[int] = None) -> Dict[str, Any]:
        if not self._running or self._landmarker is None:
            return {}
        if self._busy:
            return {}
        self._busy = True
        w, h = size
        payload: Dict[str, Any] = {}
        normalized = True
        mp_image = self._to_mp_image(frame)
        try:
            if mp_image is None:
                return {}
            if ts_ms is None:
                import time; ts_ms = int(time.time() * 1000)
            res = (self._landmarker.detect_for_video(mp_image, ts_ms)
                   if self._running_mode == "VIDEO" else
                   self._landmarker.detect(mp_image))
            if not res or not getattr(res, "pose_landmarks", None):
                return {}
            lms = res.pose_landmarks[0]
            L = (lms[11].x, lms[11].y); R = (lms[12].x, lms[12].y)
            spts = [(L[0]*(1-t)+R[0]*t, L[1]*(1-t)+R[1]*t) for t in [k/8 for k in range(9)]]
            payload = {"shoulder_L": L, "shoulder_R": R, "shoulder_support": spts}
            return payload
        except Exception as e:
            print(f"[PoseEngine] detect failed: {e}")
            return {}
        finally:
            self._busy = False
            try:
                self.resultReady.emit(payload, (w, h), normalized)
            except Exception:
                pass

    def _to_mp_image(self, frame: object):
        try:
            import mediapipe as mp
            import numpy as np
            from PySide6.QtGui import QImage
        except Exception as e:
            print(f"[PoseEngine] helper import failed: {e}")
            return None
        # QImage → SRGB np.array
        try:
            if isinstance(frame, QImage):
                img = frame.convertToFormat(QImage.Format.Format_RGB888)
                w, h = img.width(), img.height()
                tH = getattr(self, "_target_height", 1008)
                if tH and h != tH:
                    from PySide6.QtCore import Qt
                    scale = tH / float(h)
                    nw = int(round(w * scale))
                    img = img.scaled(nw, tH, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    w, h = img.width(), img.height()
                ptr = img.constBits(); stride = img.bytesPerLine()
                arr = np.frombuffer(ptr, dtype=np.uint8, count=stride*h).reshape((h, stride))
                arr = arr[:, : w*3].reshape((h, w, 3))
                return mp.Image(image_format=mp.ImageFormat.SRGB, data=arr)
        except Exception as e:
            print(f"[PoseEngine] QImage→np failed: {e}")
        # ndarray path
        try:
            arr = np.asarray(frame)
            if arr.ndim == 3 and arr.shape[2] == 3:
                return mp.Image(image_format=mp.ImageFormat.SRGB, data=arr)
            if arr.ndim == 3 and arr.shape[2] == 4:
                return mp.Image(image_format=mp.ImageFormat.SRGB, data=arr[..., :3])
        except Exception:
            pass
        return None


    def _release(self) -> None:
        self._landmarker = None

    @staticmethod
    def _abs(p: str) -> str:
        try:
            import os
            return os.path.abspath(p)
        except Exception:
            return p

    @staticmethod
    def _to_mp_image(frame: object):
        try:
            import mediapipe as mp
            import numpy as np
            from PySide6.QtGui import QImage
        except Exception as e:
            print(f"[PoseEngine] helper import failed: {e}")
            return None
        # QImage → SRGB np.array
        try:
            if isinstance(frame, QImage):  # type: ignore[name-defined]
                img = frame.convertToFormat(QImage.Format.Format_RGB888)
                w, h = img.width(), img.height()
                # 크기 규칙: 세로 길이 고정(tH=1008), 종횡비 유지
                tH = getattr(self, "_target_height", 1008)
                if tH and h != tH:
                    from PySide6.QtCore import Qt
                    scale = tH / float(h)
                    nw = int(round(w * scale))
                    img = img.scaled(nw, tH, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    w, h = img.width(), img.height()
                ptr = img.constBits(); stride = img.bytesPerLine()
                arr = np.frombuffer(ptr, dtype=np.uint8, count=stride*h).reshape((h, stride))
                arr = arr[:, : w*3].reshape((h, w, 3))
                return mp.Image(image_format=mp.ImageFormat.SRGB, data=arr)
        except Exception as e:
            print(f"[PoseEngine] QImage→np failed: {e}")
        # ndarray path
        try:
            arr = np.asarray(frame)
            if arr.ndim == 3 and arr.shape[2] == 3:
                return mp.Image(image_format=mp.ImageFormat.SRGB, data=arr)
            if arr.ndim == 3 and arr.shape[2] == 4:
                return mp.Image(image_format=mp.ImageFormat.SRGB, data=arr[..., :3])
        except Exception:
            pass
        return None
        
        # ndarray path
        try:
            arr = np.asarray(frame)
            if arr.ndim == 3 and arr.shape[2] == 3:
                return mp.Image(image_format=mp.ImageFormat.SRGB, data=arr)
            if arr.ndim == 3 and arr.shape[2] == 4:
                return mp.Image(image_format=mp.ImageFormat.SRGB, data=arr[..., :3])
        except Exception:
            pass
        return None


# ============================================================================
# 사용 가이드 ("보이는 대로 안내" · PoseEngine)
# ----------------------------------------------------------------------------
# 1) 프리뷰 라벨에서 보이는 QImage 사용
#    qimg = self.preview_label.pixmap().toImage()
# 2) 프레임마다 호출 (VIDEO 모드)
#    ts = int(time.time()*1000)
#    self.pose.process_frame(qimg, (qimg.width(), qimg.height()), ts)
# 3) 결과 연결
#    def _on_pose(payload, size, norm):
#        # payload: shoulder_L/R, shoulder_support(9점)
#        merge 후 overlay.update_landmarks(...)
# 4) 크기 정책
#    - _target_height=1008: 세로 길이를 1008px로 고정(종횡비 유지). 항상 적용.
# 5) 성능
#    - backpressure(_busy): 처리 중 프레임 드롭해 30fps UI 유지.
# ============================================================================


