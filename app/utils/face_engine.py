# app/utils/face_engine.py
# -*- coding: utf-8 -*-
"""
FaceEngine: MediaPipe Face Landmarker wrapper
- 입력: QImage 또는 ndarray, (w,h), timestamp(ms)
- 출력: resultReady(payload: dict, size: tuple[int,int], normalized: bool)
  payload 예시(normalized=True):
  {
    "core": {
      "top_head": (x,y), "chin": (x,y),
      "eye_L": (x,y), "eye_R": (x,y),
      "nose_tip": (x,y)
    },
    "eye_support": {"left": [...4], "right": [...4]},
    "nose_support": [(x,y),(x,y)],
    "chin_ring": [(x,y)*21],
    "pro_mesh": [(x,y)*N]
  }

주의: 이 모듈은 UI 의존성 없음. PySide6는 QImage 타입 체크에만 사용.
"""
from __future__ import annotations
from typing import Optional, Tuple, Dict, Any, List

from PySide6.QtCore import QObject, Signal


class FaceEngine(QObject):
    resultReady = Signal(dict, tuple, bool)  # (payload, (w,h), normalized)

    def __init__(self, model_path: Optional[str] = None, *, running_mode: str = "VIDEO", parent: Optional[QObject] = None):
        super().__init__(parent)
        self._model_path = model_path or "app/utils/models/face_landmarker.task"
        self._running = False
        self._mp = None
        self._vision = None
        self._landmarker = None
        self._running_mode = running_mode.upper()
        self._target_height = 1008  # 세로 고정 높이(px). 항상 적용.

    # --- Lifecycle ---------------------------------------------------------
    def start(self) -> None:
        self._running = True
        if self._landmarker is None:
            self._init_mp()

    def stop(self) -> None:
        self._running = False

    def set_model_path(self, path: str) -> None:
        self._model_path = path
        self._release()
        print(f"[FaceEngine] model path set to: {path}")

    # --- Inference ---------------------------------------------------------
    def process_frame(self, frame: object, size: Tuple[int, int], ts_ms: Optional[int] = None) -> Dict[str, Any]:
        if not self._running or self._landmarker is None:
            return {}
        w, h = size
        payload: Dict[str, Any] = {}
        normalized = True
        mp_image = self._to_mp_image(frame)
        try:
            if mp_image is None:
                return {}
            if self._running_mode == "VIDEO" and ts_ms is not None:
                res = self._landmarker.detect_for_video(mp_image, ts_ms)
            else:
                res = self._landmarker.detect(mp_image)
            if not res or not getattr(res, "face_landmarks", None):
                return {}
            lm = res.face_landmarks[0]  # 첫 얼굴
            payload = self._build_payload_from_landmarks(lm)
            return payload
        except Exception as e:
            print(f"[FaceEngine] detect failed: {e}")
            return {}
        finally:
            try:
                self.resultReady.emit(payload, (w, h), normalized)
            except Exception:
                pass

    # --- Internals ---------------------------------------------------------
    def _to_mp_image(self, frame: object):
        try:
            import mediapipe as mp
            import numpy as np
            from PySide6.QtGui import QImage
        except Exception as e:
            print(f"[FaceEngine] helper import failed: {e}")
            return None
        # QImage → SRGB np.array
        try:
            if isinstance(frame, QImage):
                img = frame.convertToFormat(QImage.Format.Format_RGB888)
                w, h = img.width(), img.height()
                tH = getattr(self, "_target_height", 0)
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
            print(f"[FaceEngine] QImage→np failed: {e}")
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

    # --- Payload mapping ----------------------------------------------------
    def _build_payload_from_landmarks(self, lm) -> Dict[str, Any]:
        # MediaPipe FaceLandmarker는 468개(또는 478개) 정점. 눈/코/턱 등 인덱스는 BlazeFace/FaceMesh 규칙.
        # 필수 포인트 추출 인덱스(대략적인 FaceMesh 기준):
        idx = {
            "chin": 152,
            "top_head": 10,  # hairline 근사치(정수리 보정은 상위 단계에서)
            "eye_L": 33,
            "eye_R": 263,
            "nose_tip": 1,
        }
        core = {
            k: (lm[v].x, lm[v].y)
            for k, v in idx.items()
            if v < len(lm)
        }
        # 눈 박스 보조점(상/하/좌/우)
        eye_support = {
            "left": [
                (lm[159].x, lm[159].y),  # top
                (lm[145].x, lm[145].y),  # bottom
                (lm[133].x, lm[133].y),  # left
                (lm[33].x,  lm[33].y),   # right
            ],
            "right": [
                (lm[386].x, lm[386].y),  # top
                (lm[374].x, lm[374].y),  # bottom
                (lm[263].x, lm[263].y),  # left
                (lm[362].x, lm[362].y),  # right
            ],
        }
        # 콧볼
        nose_support = [(lm[94].x, lm[94].y), (lm[331].x, lm[331].y)]
        # 턱 링(21점 근사: jawline 0..16 + 중간 샘플)
        chin_ring: List[Tuple[float, float]] = []
        jaw_idxs = [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16]
        for i in jaw_idxs:
            chin_ring.append((lm[i].x, lm[i].y))
        # pro_mesh: 전체 포인트 희미하게
        pro_mesh = [(pt.x, pt.y) for pt in lm]
        return {
            "core": core,
            "eye_support": eye_support,
            "nose_support": nose_support,
            "chin_ring": chin_ring,
            "pro_mesh": pro_mesh,
        }


# ============================================================================
# 사용 가이드 ("보이는 대로 안내" 적용)
# ----------------------------------------------------------------------------
# 1) 프리뷰 라벨에서 보이는 그대로의 QImage를 엔진에 넣는다.
#    - 예) qimg = self.preview_label.pixmap().toImage()
#    - 이렇게 하면 라벨의 스케일/레터박스/회전/미러링 상태가 그대로 반영된다.
#
# 2) 오버레이 구멍은 프리뷰 라벨에 바인딩한다.
#    - self.overlay.bind_hole_widget(self.preview_label, shrink_px=3)
#    - OverlayCanvas는 hole(rect)을 기준으로 정규화 좌표(0..1)를 화면 좌표로 변환한다.
#
# 3) 프레임마다 엔진 호출 (VIDEO 모드 권장)
#    - ts = int(time.time()*1000)
#    - w, h = qimg.width(), qimg.height()
#    - self.face.process_frame(qimg, (w,h), ts)
#    - self.pose.process_frame(qimg, (w,h), ts)   # PoseEngine를 쓰는 경우
#
# 4) 콜백에서 결과 병합 후 오버레이에 전달
#    - base = dict(face_payload)
#    - pose_payload의 shoulder_support, shoulder_L/R를 base에 병합
#    - self.overlay.update_landmarks(base, normalized=True)
#
# 5) 크기 정책
#    - _target_height=1008: 세로 길이를 1008px로 고정(종횡비 유지). 항상 적용.
#
# 6) 왜 이렇게 하나?
#    - 목표가 "보이는 대로 안내"이기 때문. 라벨에 보이는 픽셀 좌표계가 곧 사용자 경험의 기준이다.
#    - 엔진은 0..1 정규화 좌표를 내고, 오버레이가 라벨 구멍 rect로 정확히 매핑한다.
#    - 카메라 원본 해상도나 회전/미러 상태와 무관하게 화면에 보이는 방향으로 지시가 나온다.
# ============================================================================
