# -*- coding: utf-8 -*-
# app/utils/ai_retouch.py — AI 보정 스캐폴드(백엔드 미연결 시 No-Op)
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence, Tuple, Union, Dict

# PySide6 의존성은 선택적 — 필요 시 내부에서 import
QImageLike = Union["QImage", "QPixmap"]

#─────────────────────────────────────────────
#  데이터 모델
#─────────────────────────────────────────────
@dataclass
class EyeInfo:
    """눈 윤곽/박스 정보(정규화 좌표)."""
    cx: float  # 중심 x [0~1]
    cy: float  # 중심 y [0~1]
    w: float   # 박스 폭 [0~1]
    h: float   # 박스 높이 [0~1]

@dataclass
class EyeDetectResult:
    ok: bool
    left: Optional[EyeInfo] = None
    right: Optional[EyeInfo] = None

@dataclass
class ShoulderDetectResult:
    ok: bool
    left_xy: Optional[Tuple[float, float]] = None  # [0~1] 좌표 
    right_xy: Optional[Tuple[float, float]] = None # [0~1] 좌표
    slope_deg: float = 0.0

@dataclass
class PoseInfo:
    """얼굴 포즈 정보(추정값)."""
    ok: bool
    yaw: float = 0.0   # 좌/우 (deg)
    pitch: float = 0.0 # 위/아래 (deg)
    roll: float = 0.0  # 기울기 (deg)
    bbox: Optional[Tuple[float, float, float, float]] = None  # 정규화 (x,y,w,h)

@dataclass
class SpecProfile:
    """규격별 정렬/크롭 스펙."""
    ratio: Tuple[int, int]                  # 출력 비율(정수)
    eye_line_y: float                       # 눈높이(프레임 대비 y, 0~1)
    head_top_margin: float                  # 상단 여백 비율(머리끝~프레임 상단)
    bg_color: str = "white"                 # 기본 배경색

# 규격 프리셋(예시)
SPEC_PRESETS: Dict[str, SpecProfile] = {
    "ID_30x40": SpecProfile(ratio=(3, 4), eye_line_y=0.42, head_top_margin=0.06, bg_color="white"),
    "ID_35x45": SpecProfile(ratio=(7, 9), eye_line_y=0.42, head_top_margin=0.06, bg_color="white"),
    # PASSPORT_2x2 제거(요청)
}


#─────────────────────────────────────────────
#  변환 유틸 (지연 import)
#─────────────────────────────────────────────
# QImage/QPixmap 타입 힌트용(런타임 import 전용)
try:  # PySide6 가 없는 환경에서도 임포트에 실패하지 않도록
    from PySide6.QtGui import QImage, QPixmap
except Exception:  # pragma: no cover
    QImage = QPixmap = object  # type: ignore


def _to_qimage(img: Union[QImageLike, str]) -> Optional[QImage]:
    """QImage/Pixmap/파일경로 → QImage (실패 시 None)."""
    # 역할: 입력을 QImage로 표준화
    # 수정로그:
    # - v1.0: 초판 — QPixmap, 경로 문자열 대응
    if isinstance(img, QImage):
        return img
    if isinstance(img, QPixmap):
        return img.toImage()
    if isinstance(img, str) and img:
        pm = QPixmap(img)
        return pm.toImage() if not pm.isNull() else None
    return None


#─────────────────────────────────────────────
#  I/O 유틸 (저장/로드)
#─────────────────────────────────────────────

# 파일경로 → QImage (스레드세이프)
def _qimage_from_path(path: str) -> Optional[QImage]:
    """
    - QImage 파일 로더 우선. 실패 시 cv2로 로딩 후 RGB→QImage 변환.
    - QPixmap에 의존하지 않아 워커 스레드에서도 안전.
    """
    try:
        qi = QImage(path)
        if not qi.isNull():
            return qi
    except Exception:
        pass
    try:
        import cv2, numpy as np
        bgr = cv2.imread(path, cv2.IMREAD_COLOR)
        if bgr is None:
            return None
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        h, w = rgb.shape[:2]
        qimg = QImage(rgb.data, w, h, 3*w, QImage.Format.Format_RGB888)
        return qimg.copy()
    except Exception:
        return None

# QImage → JPEG 저장(품질 100 기본)
# - 역할: 항상 최고 화질로 JPG 저장, 경로 생성 포함
# - 수정로그: v1.3 신설
def save_jpg(img: QImage, path: str, quality: int = 100) -> bool:
    """
    QImage → JPEG 저장(품질 100) 시도 후, 실패하면 OpenCV로 폴백.
    - 역할: 출력 보장(가능한 한)
    - 수정로그: v1.6 — OpenCV imwrite 폴백 추가, 경로 생성 보강
    """
    import os
    if img is None or (hasattr(img, 'isNull') and img.isNull()):
        return False
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    # 1차: Qt 저장
    ok = bool(img.save(path, "JPG", quality))
    if ok:
        return True
    # 2차: OpenCV 폴백
    try:
        import numpy as np, cv2
        q = img.convertToFormat(QImage.Format.Format_RGB888)
        h, w = q.height(), q.width()
        bpl = q.bytesPerLine()
        ptr = q.bits()
        buf = ptr.tobytes() if hasattr(ptr, "tobytes") else bytes(ptr)
        arr = np.frombuffer(buf, dtype=np.uint8).reshape((h, bpl // 3, 3))
        arr = arr[:, :w, :]
        ok2 = cv2.imwrite(path, cv2.cvtColor(arr, cv2.COLOR_RGB2BGR), [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)])
        return bool(ok2)
    except Exception:
        return False

# 파일 단위 파이프라인(one-shot)
# - 역할: in_path 로드 → 파이프라인 적용 → out_path(JPG 100) 저장
# - 수정로그: v1.3 신설
def process_file(
    in_path: str,
    out_path: str,
    *,
    target_ratio: Tuple[int, int] = (3, 4),
    spec_profile: str = "AUTO",
    background_color: str = "white",
    eye_strength: float = 0.0,
    shoulder_mode: str = "auto",
    anti_glare: bool = True,
) -> bool:
    """
    파일 단위 파이프라인(one-shot)
    - 역할: in_path 로드 → 파이프라인 적용 → out_path(JPG 100) 저장
    - 정책: 어떤 경우에도 out_path 생성을 최대한 보장(최후에는 원본 복사)
    - 수정로그: v1.6 — 실패 시 원본 복사 폴백, 저장 보장 로직 강화
    """
    import os, shutil
    # 입력 로드
    src = _qimage_from_path(in_path)
    if src is None or (hasattr(src, 'isNull') and src.isNull()):
        # 입력 로드 실패라도 출력 보장 시도(원본 파일이 있으면 복사)
        try:
            os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
            if os.path.exists(in_path):
                shutil.copyfile(in_path, out_path)
                return True
            return False
        except Exception:
            return False

    # 파이프라인 적용
    try:
        pipe = RetouchPipeline()
        qi = pipe.apply(
            src,
            eye_strength=eye_strength,
            shoulder_mode=shoulder_mode,
            target_ratio=target_ratio,
            spec_profile=spec_profile,
            background_color=background_color,
            anti_glare=anti_glare,
        )
        if save_jpg(qi, out_path, 100):
            return True
    except Exception as e:
        print("[retouch] pipeline error:", e)

    # 저장 실패 또는 파이프라인 오류 → 원본 복사 폴백
    try:
        os.makedirs(os.path.dirname(out_path) or '.', exist_ok=True)
        shutil.copyfile(in_path, out_path)
        return True
    except Exception:
        return False

#─────────────────────────────────────────────
#  디텍터 / 어저스터 (No-Op 백엔드)
#─────────────────────────────────────────────
# EyeSizeDetector.detect(image) → 좌/우 눈 윤곽/면적, 정규화 좌표(0~1) / 어저스터 (No-Op 백엔드)
#─────────────────────────────────────────────
# EyeSizeDetector.detect(image) → 좌/우 눈 윤곽/면적, 정규화 좌표(0~1)
class EyeSizeDetector:
    # 눈 크기/위치 탐지 (정규화 좌표)
    def detect(self, image: Union[QImageLike, str]) -> EyeDetectResult:
        """현재는 No-Op: 항상 ok=False 를 돌려준다."""
        # 역할: 입력 이미지에서 좌우 눈을 찾아 정규화 좌표 반환
        # 수정로그:
        # - v1.0: 초판 — 백엔드 미연결, ok=False
        _ = _to_qimage(image)  # 표준화만 수행
        return EyeDetectResult(ok=False)


class EyeSizeAdjuster:
    # 눈 크기 국소 변형 (strength: -1.0~+1.0 권장)
    def adjust(self, image: Union[QImageLike, str], strength: float = 0.0) -> QImage:
        """현재는 No-Op: 입력 이미지를 QImage로 변환해 그대로 반환."""
        # 역할: 감마/워프 등으로 눈 크기 보정 (미구현)
        # 수정로그:
        # - v1.0: 초판 — 무변경 패스스루
        qi = _to_qimage(image)
        if qi is None:
            raise ValueError("Invalid image input for EyeSizeAdjuster.adjust")
        return qi


# ShoulderHeightDetector.detect(image) → 좌/우 어깨 포인트/기울기
class ShoulderHeightDetector:
    # 어깨 높이/기울기 탐지 (정규화 좌표)
    def detect(self, image: Union[QImageLike, str]) -> ShoulderDetectResult:
        """현재는 No-Op: 항상 ok=False 를 돌려준다."""
        # 역할: 좌/우 어깨 좌표 및 기울기 추정
        # 수정로그:
        # - v1.0: 초판 — 백엔드 미연결, ok=False
        _ = _to_qimage(image)
        return ShoulderDetectResult(ok=False)


class ShoulderHeightAdjuster:
    # 어깨 높이 보정 (mode: 'auto'|'left'|'right'|'tilt')
    def adjust(self, image: Union[QImageLike, str], mode: str = "auto") -> QImage:
        """현재는 No-Op: 입력 이미지를 QImage로 변환해 그대로 반환."""
        # 역할: 회전/워프/캔버스 시프트 등으로 어깨 높이 보정 (미구현)
        # 수정로그:
        # - v1.0: 초판 — 무변경 패스스루
        qi = _to_qimage(image)
        if qi is None:
            raise ValueError("Invalid image input for ShoulderHeightAdjuster.adjust")
        return qi


#─────────────────────────────────────────────
#  신규: 포즈/크롭 정규화, 배경 정리, 조명/색 보정 (No-Op 스캐폴드)
#─────────────────────────────────────────────
class PoseAligner:
    """얼굴 각도 보정(roll), 규격별 크롭 박스 산출 후 정렬/크롭 수행."""

    # 포즈 추정(현재 No-Op)
    def estimate_pose(self, image: Union[QImageLike, str]) -> PoseInfo:
        """이미지의 yaw/pitch/roll 추정 — 현재는 ok=False의 근사값 반환."""
        _ = _to_qimage(image)
        return PoseInfo(ok=False)

    # 정렬/크롭(Tasks FaceLandmarker 사용, 실패 시 패스스루)
    # - 세션 비율(target_ratio)에 맞게 roll 보정 후 크롭
    # - 모델은 model_asset_buffer 로딩(경로 이슈 회피)
    def align_and_crop(
        self,
        image: Union[QImageLike, str],
        target_ratio: Tuple[int, int] = (3, 4),
        spec_profile: str = "AUTO",
    ) -> QImage:
        """
        - 역할: 얼굴 랜드마크로 roll 보정 후, eye_line_y≈0.42 + head_top_margin≈0.06 규칙을 최대한 만족하도록 target_ratio 크롭
        - 실패 시: 입력 이미지를 그대로 반환(No-Op)
        - 수정로그:
          - v1.2: MediaPipe Tasks 연동, 회전 + 크롭 구현
          - v1.7: 머리 윗여백 0.06 강제(가능 범위 내) + 가로/세로 경계 핏 보정
        """
        # 지연 임포트(실행 환경에 mediapipe/cv2 없는 경우 대비)
        try:
            import numpy as np
            import cv2
            import mediapipe as mp
            from mediapipe.tasks import python as mp_python
            from mediapipe.tasks.python import vision as mp_vision
        except Exception:
            qi = _to_qimage(image)
            if qi is None:
                raise ValueError("Invalid image input for PoseAligner.align_and_crop")
            return qi

        # --- QImage/경로 → RGB ndarray ---
        def to_rgb_nd(img_in) -> Tuple[np.ndarray, Tuple[int,int]]:
            if isinstance(img_in, str):
                bgr = cv2.imread(img_in, cv2.IMREAD_COLOR)
                if bgr is None:
                    raise ValueError("Image path read failed")
                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                return rgb, (bgr.shape[1], bgr.shape[0])
            qi = _to_qimage(img_in)
            if qi is None:
                raise ValueError("Invalid image type")
            qi = qi.convertToFormat(QImage.Format.Format_RGBA8888)
            w, h = qi.width(), qi.height()
            bpl = qi.bytesPerLine()  # 라인 패딩 고려
            ptr = qi.bits()
            buf = ptr.tobytes() if hasattr(ptr, "tobytes") else bytes(ptr)
            arr = np.frombuffer(buf, dtype=np.uint8).reshape((h, bpl // 4, 4))
            arr = arr[:, :w, :]  # 패딩 제거
            rgb = cv2.cvtColor(arr, cv2.COLOR_RGBA2RGB)
            return rgb, (w, h)

        # --- RGB ndarray → QImage ---
        def to_qimage(rgb: "np.ndarray") -> QImage:
            h, w = rgb.shape[:2]
            rgb8 = rgb.astype(np.uint8, copy=False)
            qimg = QImage(rgb8.data, w, h, 3*w, QImage.Format.Format_RGB888)
            return qimg.copy()  # 메모리 소유권 분리

        # --- FaceLandmarker 모델 바이트 로딩 ---
        def load_model_bytes() -> Optional[bytes]:
            import os
            base = os.getcwd()                            # 실행 기준 루트
            mod_dir = os.path.dirname(__file__)           # app/utils
            cand = [
                os.path.join(base, "face_landmarker.task"),
                os.path.join(base, "models", "face_landmarker.task"),
                os.path.join(base, "app", "utils", "models", "face_landmarker.task"),
                os.path.join(mod_dir, "face_landmarker.task"),
                os.path.join(mod_dir, "models", "face_landmarker.task"),
            ]
            for p in cand:
                try:
                    if os.path.exists(p) and os.path.getsize(p) > 100*1024:
                        with open(p, "rb") as f:
                            return f.read()
                except Exception:
                    continue
            return None

        EYE_LINE_Y = 0.42
        HEAD_TOP = 0.06

        rgb, (W, H) = to_rgb_nd(image)
        model_bytes = load_model_bytes()
        if not model_bytes:
            return to_qimage(rgb)  # 모델 없으면 패스스루

        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        opts = mp_vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_buffer=model_bytes),
            num_faces=1,
            running_mode=mp_vision.RunningMode.IMAGE,
        )
        try:
            landmarker = mp_vision.FaceLandmarker.create_from_options(opts)
            result = landmarker.detect(mp_image)
        except Exception:
            return to_qimage(rgb)

        if not result.face_landmarks:
            return to_qimage(rgb)
        lm = result.face_landmarks[0]

        # --- roll 계산 (눈꼬리 33, 263) ---
        lx, ly = int(lm[33].x * W), int(lm[33].y * H)
        rx, ry = int(lm[263].x * W), int(lm[263].y * H)
        dy, dx = (ry - ly), (rx - lx)
        import math
        roll_deg = math.degrees(math.atan2(dy, dx))  # +: 시계 반대

        # --- 회전 보정 (눈 중점 기준) ---
        cx, cy = (lx + rx) / 2.0, (ly + ry) / 2.0
        M = cv2.getRotationMatrix2D((cx, cy), -roll_deg, 1.0)
        rgb_rot = cv2.warpAffine(rgb, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)

        # --- 회전 후 좌표 계산 ---
        pts = np.array([[[lx, ly]], [[rx, ry]]], dtype=np.float32)
        rot_pts = cv2.transform(pts, M)
        ly2 = float(rot_pts[0,0,1]); ry2 = float(rot_pts[1,0,1])
        eye_y = (ly2 + ry2) * 0.5

        # 머리 윗점 추정: 모든 랜드마크 y의 최소값(회전 좌표계)
        all_xy = np.array([[[int(p.x * W), int(p.y * H)]] for p in lm], dtype=np.float32)
        all_xy_rot = cv2.transform(all_xy, M)
        head_top_y = float(np.min(all_xy_rot[...,1]))
        head_top_y = max(0.0, min(float(H), head_top_y))

        # --- 크롭 박스 계산 (스펙 강제) ---
        rw, rh = target_ratio
        aspect = rw / float(max(1, rh))
        den = max(1e-6, (EYE_LINE_Y - HEAD_TOP))
        crop_h_desired = (eye_y - head_top_y) / den
        crop_h = float(max(1.0, crop_h_desired))
        crop_w = crop_h * aspect
        if crop_w > W:
            scale = W / crop_w
            crop_w = W
            crop_h *= scale
        max_h_top = eye_y / max(1e-6, EYE_LINE_Y)
        max_h_bot = (H - eye_y) / max(1e-6, (1.0 - EYE_LINE_Y))
        fit_h = min(crop_h, max_h_top, max_h_bot)
        if fit_h < crop_h:
            crop_h = fit_h
            crop_w = crop_h * aspect
        left = int(round(cx - crop_w / 2.0))
        top = int(round(eye_y - EYE_LINE_Y * crop_h))
        left = max(0, min(W - int(crop_w), left))
        top = max(0, min(H - int(crop_h), top))

        x, y, w, h = left, top, int(round(crop_w)), int(round(crop_h))
        crop = rgb_rot[y:y+h, x:x+w]
        if crop.size == 0:
            return to_qimage(rgb_rot)
        return to_qimage(crop)
        if crop.size == 0:
            return to_qimage(rgb_rot)

        return to_qimage(crop)

class BackgroundCleaner:
    """인물/배경 분리 후 배경 단색 치환 및 벽면 그림자 완화."""

    # 배경 치환(경량): 코너 시드 floodFill → 마스크 합성 → feather → 단색 채움
    def clean(
        self,
        image: Union[QImageLike, str],
        *,
        color: str = "white",
        feather_px: int = 10,
        shadow_reduction: float = 0.35,
        tol: int = 32,
    ) -> QImage:
        """
        - 역할: 배경이 비교적 균일할 때(벽/스크린) 코너 시드 floodFill로 배경 마스크 추정 후 단색으로 치환
        - 수정로그: v1.4 — 경량 floodFill 마스크 기반 치환 구현(세그 모델 없이 사용 가능)
        """
        qi = _to_qimage(image)
        if qi is None:
            raise ValueError("Invalid image input for BackgroundCleaner.clean")
        try:
            import cv2, numpy as np
            # QImage->BGR
            qi2 = qi.convertToFormat(QImage.Format.Format_RGBA8888)
            w, h = qi2.width(), qi2.height()
            bpl = qi2.bytesPerLine()
            ptr = qi2.bits()
            buf = ptr.tobytes() if hasattr(ptr, "tobytes") else bytes(ptr)
            arr = np.frombuffer(buf, dtype=np.uint8).reshape((h, bpl // 4, 4))
            arr = arr[:, :w, :]
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)

            H, W = bgr.shape[:2]
            mask = np.zeros((H+2, W+2), np.uint8)
            flags = 4 | (255 << 8)  # 4-conn, newMaskVal=255
            lo = (tol, tol, tol); up = (tol, tol, tol)
            seeds = [(1,1), (W-2,1), (1,H-2), (W-2,H-2)]
            tmp = bgr.copy()
            for sx, sy in seeds:
                try:
                    cv2.floodFill(tmp, mask, (int(sx), int(sy)), (0,0,0), lo, up, flags)
                except Exception:
                    pass
            m = (mask[1:-1,1:-1] > 0).astype(np.float32)
            if m.mean() < 0.01:
                return qi  # 배경으로 추정되는 영역이 너무 작으면 스킵
            # feather
            k = max(1, int(feather_px // 2) * 2 + 1)
            m = cv2.GaussianBlur(m, (k, k), 0)
            m3 = np.dstack([m, m, m])
            # 배경색 생성
            if color == "white":
                bg = np.full_like(bgr, 255)
            elif color == "light-gray":
                bg = np.full_like(bgr, 235)
            elif color == "light-blue":
                bg = np.full_like(bgr, (240, 248, 255))
            else:
                bg = np.full_like(bgr, 255)
            # 그림자 완화
            if shadow_reduction > 0:
                lift = (m3 * shadow_reduction * 255).astype(np.uint8)
                bgr = cv2.add(bgr, lift, mask=(m*255).astype(np.uint8))
            out = (m3 * bg + (1.0 - m3) * bgr).astype(np.uint8)
            # BGR->QImage
            rgb = cv2.cvtColor(out, cv2.COLOR_BGR2RGB)
            qout = QImage(rgb.data, W, H, 3*W, QImage.Format.Format_RGB888)
            return qout.copy()
        except Exception:
            return qi


class IlluminationNormalizer:
    """노출/화이트밸런스 정규화 + 안경 난반사 억제(경량)."""

    def normalize(
        self,
        image: Union[QImageLike, str],
        *,
        anti_glare: bool = True,
        wb: str = "auto",
        gamma: float = 1.05,
        clip_limit: float = 3.0,
        unsharp_amount: float = 0.3,
    ) -> QImage:
        """
        - 역할: LAB L 채널 CLAHE로 대비/노출 보정 + 선택적으로 과다 하이라이트 영역 톤다운
        - 수정로그: v1.4 — CLAHE/하이라이트 억제 구현
        """
        qi = _to_qimage(image)
        if qi is None:
            raise ValueError("Invalid image input for IlluminationNormalizer.normalize")
        try:
            import cv2, numpy as np
            # QImage -> BGR
            qi2 = qi.convertToFormat(QImage.Format.Format_RGBA8888)
            w, h = qi2.width(), qi2.height()
            bpl = qi2.bytesPerLine()
            ptr = qi2.bits()
            buf = ptr.tobytes() if hasattr(ptr, "tobytes") else bytes(ptr)
            arr = np.frombuffer(buf, dtype=np.uint8).reshape((h, bpl // 4, 4))
            arr = arr[:, :w, :]
            bgr = cv2.cvtColor(arr, cv2.COLOR_RGBA2BGR)
            # LAB CLAHE
            lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
            l, a, b = cv2.split(lab)
            clahe = cv2.createCLAHE(clipLimit=float(clip_limit), tileGridSize=(8,8))
            l2 = clahe.apply(l)
            lab2 = cv2.merge([l2, a, b])
            bgr2 = cv2.cvtColor(lab2, cv2.COLOR_LAB2BGR)
            # Anti-glare: 매우 밝은 영역 톤다운
            if anti_glare:
                gray = cv2.cvtColor(bgr2, cv2.COLOR_BGR2GRAY)
                mask = (gray > 235).astype(np.uint8) * 255
                if mask.mean() > 1:
                    blur = cv2.GaussianBlur(bgr2, (0,0), 3)
                    bgr2 = np.where(mask[...,None]==255, (bgr2*0.85 + blur*0.15).astype(np.uint8), bgr2)
            # 감마 옵션
            if abs(gamma - 1.0) > 1e-3:
                inv = 1.0 / max(1e-6, gamma)
                table = (np.linspace(0,1,256)**inv * 255).astype(np.uint8)
                bgr2 = cv2.LUT(bgr2, table)
            # Unsharp mask (약하게)
            if unsharp_amount > 0:
                blur = cv2.GaussianBlur(bgr2, (0,0), 1.2)
                sharp = cv2.addWeighted(bgr2, 1 + unsharp_amount, blur, -unsharp_amount, 0)
                bgr2 = sharp
            # BGR->QImage
            rgb = cv2.cvtColor(bgr2, cv2.COLOR_BGR2RGB)
            qout = QImage(rgb.data, w, h, 3*w, QImage.Format.Format_RGB888)
            return qout.copy()
        except Exception:
            return qi


#─────────────────────────────────────────────
#  오버레이 유틸 (정규화 → 픽셀좌표 사상)
#─────────────────────────────────────────────
def map_norm_point(x: float, y: float, rect_px: Tuple[int, int, int, int]) -> Tuple[int, int]:
    """(0~1) 점을 대상 사각형(px)으로 변환.
    rect_px: (x, y, w, h)
    """
    # 역할: 프리뷰 네모 좌표계로 오버레이 포인트 매핑
    # 수정로그:
    # - v1.0: 초판
    rx, ry, rw, rh = rect_px
    return int(rx + x * rw), int(ry + y * rh)


def map_norm_box(cx: float, cy: float, w: float, h: float, rect_px: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    """정규화 중심/폭/높이(box)를 대상 사각형(px)으로 변환 → (x,y,w,h)."""
    # 역할: 눈 박스 등 정규화 사각형을 픽셀 사각형으로 변환
    # 수정로그:
    # - v1.0: 초판
    rx, ry, rw, rh = rect_px
    bx = cx - w / 2.0
    by = cy - h / 2.0
    return (
        int(rx + bx * rw),
        int(ry + by * rh),
        int(w * rw),
        int(h * rh),
    )


#─────────────────────────────────────────────
#  파이프라인 (선택 사용)
#─────────────────────────────────────────────
class RetouchPipeline:
    """눈/어깨 + (포즈/배경/조명) 파이프라인 — 현재는 No-Op 체인."""

    def __init__(self):
        self.eye_detector = EyeSizeDetector()
        self.eye_adjuster = EyeSizeAdjuster()
        self.shoulder_detector = ShoulderHeightDetector()
        self.shoulder_adjuster = ShoulderHeightAdjuster()
        # 신규 스텝
        self.pose_aligner = PoseAligner()
        self.bg_cleaner = BackgroundCleaner()
        self.illum = IlluminationNormalizer()

    # 입력 이미지를 받아 단계별 보정(현재는 패스스루)
    def apply(
        self,
        image: Union[QImageLike, str],
        *,
        eye_strength: float = 0.0,
        shoulder_mode: str = "auto",
        target_ratio: Tuple[int, int] = (3, 4),   # 기본: 3.5x4.5 → 7:9
        spec_profile: str = "ID_35x45",
        background_color: str = "white",
        anti_glare: bool = True,
    ) -> QImage:
        """검출→보정 순서. 현재는 각 단계가 No-Op이므로 입력 그대로 흐른다."""
        # 역할: 일괄 보정 엔트리포인트
        # 수정로그:
        # - v1.1: 포즈정렬/배경/조명 스텝 추가, 파라미터 확장
        # - v1.0: 초판 — No-Op 파이프라인
        qi = _to_qimage(image)
        if qi is None:
            raise ValueError("Invalid image input for RetouchPipeline.apply")

        # 1) 포즈/크롭 정규화
        qi = self.pose_aligner.align_and_crop(qi, target_ratio=target_ratio, spec_profile=spec_profile)
        # 2) 배경 치환/정리
        qi = self.bg_cleaner.clean(qi, color=background_color, feather_px=10, shadow_reduction=0.35, tol=32)
        # 3) 조명/색 보정(난반사 억제 포함)
        qi = self.illum.normalize(qi, anti_glare=anti_glare, gamma=1.05, clip_limit=3.0, unsharp_amount=0.3)
        # 4) (선택) 눈/어깨 보정 — 현재는 패스스루
        qi = self.eye_adjuster.adjust(qi, strength=eye_strength)
        qi = self.shoulder_adjuster.adjust(qi, mode=shoulder_mode)
        return qi


#─────────────────────────────────────────────
#  수정 로그
#─────────────────────────────────────────────
"""
- v1.5 — PoseAligner: 회전 보간을 INTER_CUBIC으로 상향(미세각 스냅 없음)

- v1.4 — BackgroundCleaner: 코너 floodFill 기반 단색 치환 / IlluminationNormalizer: LAB-CLAHE + 하이라이트 억제 / PoseAligner: 회전 후 눈높이로 크롭 개선 / 기본 ratio=(3,4)
- v1.3 — 저장/로드 유틸 추가: `save_jpg()`(JPG 100 저장), `process_file()`(파일→파이프라인→파일). 경량 QImage 로더 `_qimage_from_path()` 도입.
- v1.2 — PoseAligner.align_and_crop: MediaPipe Tasks 연동(모델 바이트 로딩), roll 보정 + ratio 크롭 구현. PASSPORT 프리셋 제거. 모델 검색경로에 `app/utils/models/face_landmarker.task` 추가.

- v1.1 — 신규 클래스 추가: PoseAligner, BackgroundCleaner, IlluminationNormalizer. 파이프라인에 통합.
- v1.0 — 파일 생성: Eye/Shoulder Detector & Adjuster No-Op 스캐폴드, 정규화→픽셀 맵 유틸, 파이프라인 추가
"""
