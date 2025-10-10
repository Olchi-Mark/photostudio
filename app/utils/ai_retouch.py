# -*- coding: utf-8 -*-
# app/utils/ai_retouch.py — ID/Resume photo AI retouch pipeline (Tasks)
# Spec: (3,4)=30×40 → Head 52–58%H, Top 6–10%H
#       (7,9)=35×45 → Head 73–78%H, Top 6–8%H
# Pipeline: 1) Face roll align(head-only) → 2) Shoulder level(below chin)
#           3) Eye-size balance(small-only) → 4) Crown&Chin estimate → 5) Spec crop → 6) Save

from __future__ import annotations
from typing import Union, Tuple
import os, math, cv2, threading, atexit
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, Optional, Tuple, Union

# ─────────────────────────────────────────────
# Debug
# ─────────────────────────────────────────────

#Debug_mod: bool = True
Debug_mod: bool = False
DEBUG_POINTS_ONLY: bool = False   # 점만 찍기 모드
#DEBUG_POINTS_ONLY: bool = True
DOT_R: int = 4                   # 일반 포인트 반지름(픽셀)  ← 2 → 4 로 키움
DOT_R_CROWN: int = 7             # crown/chin 강조 점 크기

from typing import Dict, Tuple, Any
import json, os

SETTINGS_PATH = r"C:\PhotoBox\settings.json"

DEFAULT_PROFILES: Dict[str, Dict[str, Tuple[float, float]]] = {
    # 가이드 디폴트(단위: 비율 0~1)
    "3545": {"head_pct_range": (0.73, 0.78), "top_pct_range": (0.06, 0.08)},
    "3040": {"head_pct_range": (0.52, 0.58), "top_pct_range": (0.06, 0.10)},
}

def _to_range01(v: Any) -> Tuple[float, float]:
    """
    입력 형식 허용:
      - [0.73, 0.78]  또는 [73, 78]
      - {"min": 73, "max": 78}  또는 {"min":0.73,"max":0.78}
    반환: (min01, max01)
    """
    if isinstance(v, dict):
        a, b = v.get("min"), v.get("max")
    elif isinstance(v, (list, tuple)) and len(v) == 2:
        a, b = v[0], v[1]
    else:
        raise ValueError("invalid range")
    a = float(a); b = float(b)
    if a > 1.0 or b > 1.0:  # 퍼센트 → 비율
        a /= 100.0; b /= 100.0
    if a > b:
        a, b = b, a
    a = max(0.0, min(1.0, a))
    b = max(0.0, min(1.0, b))
    return (a, b)

def _load_profiles_from_file(path: str) -> Dict[str, Dict[str, Tuple[float, float]]]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    prof = data.get("profiles", {})
    out: Dict[str, Dict[str, Tuple[float, float]]] = {}
    for key in ("3040", "3545"):
        if key in prof:
            item = prof[key] or {}
            head_src = item.get("head_pct", item.get("head_pct_range"))
            top_src  = item.get("top_pct",  item.get("top_pct_range"))
            if head_src is None or top_src is None:
                continue
            head_r = _to_range01(head_src)
            top_r  = _to_range01(top_src)
            out[key] = {"head_pct_range": head_r, "top_pct_range": top_r}
    return out

def _ratio_key_from_param(ratio: Any) -> str:
    try:
        if isinstance(ratio, dict) and 'ratio' in ratio:
            ratio = ratio['ratio']
        elif hasattr(ratio, 'ratio'):
            ratio = getattr(ratio, 'ratio')
    except Exception:
        pass
    if isinstance(ratio, (list, tuple)) and len(ratio) == 2:
        try:
            rw, rh = int(ratio[0]), int(ratio[1])
            if (rw, rh) == (3, 4):
                return '3040'
            if (rw, rh) == (7, 9):
                return '3545'
            aspect = (rw / float(rh)) if rh else 0.0
            return '3040' if abs(aspect - 0.75) < abs(aspect - 7/9) else '3545'
        except Exception:
            return '3545'
    s = str(ratio).strip().lower()
    if s in ('3040', '3545'):
        return s
    if '3x4' in s or '30x40' in s or '3*4' in s:
        return '3040'
    if '7x9' in s or '35x45' in s or '7*9' in s or '3.5x4.5' in s:
        return '3545'
    return '3545'

def get_profile_spec(ratio: Any) -> Dict[str, float]:
    """
    ratio: 3040 또는 3545(문자/숫자 모두 허용)
    반환:
      head_pct_min, head_pct_max, top_pct_min, top_pct_max, head_target, top_target
    """
    key = _ratio_key_from_param(ratio)
    profiles = DEFAULT_PROFILES.copy()
    try:
        if os.path.isfile(SETTINGS_PATH):
            profiles.update(_load_profiles_from_file(SETTINGS_PATH))
        else:
            print(f"[settings] not found → defaults: {SETTINGS_PATH}")
    except Exception as e:
        print(f"[settings] load error → defaults: {e}")

    if key not in profiles:
        print(f"[settings] unknown ratio={key} → fallback 3545")
        key = "3545"

    head_min, head_max = profiles[key]["head_pct_range"]
    top_min,  top_max  = profiles[key]["top_pct_range"]
    head_target = (head_min + head_max) * 0.5
    top_target  = (top_min  + top_max)  * 0.5
    return {
        "head_pct_min": head_min, "head_pct_max": head_max,
        "top_pct_min": top_min,   "top_pct_max": top_max,
        "head_target": head_target, "top_target": top_target,
    }

# -----------------------
# Fixed I/O via settings.json
# -----------------------
def _json_load(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _resolve_fixed_paths() -> Tuple[str, str]:
    """Return (origin_path, ai_out_path) based on settings; fallback to defaults.
    Defaults:
      C:\\PhotoBox\\origin_photo.jpg -> C:\\PhotoBox\\ai_origin_photo.jpg
    """
    s = _json_load(SETTINGS_PATH)
    paths = s.get("paths", {}) if isinstance(s, dict) else {}
    origin = paths.get("origin", r"C:\\PhotoBox\\origin_photo.jpg")
    ai_out = paths.get("ai_out", r"C:\\PhotoBox\\ai_origin_photo.jpg")
    return origin, ai_out

def _select_ratio_from_settings(default: str = "3545") -> Union[str, Tuple[int, int]]:
    """Pick ratio key from settings.overlay.preset or fallback to default.
    Returns "3040" or "3545". If ambiguous, return default.
    """
    s = _json_load(SETTINGS_PATH)
    preset = ((s.get("overlay") or {}).get("preset") or "") if isinstance(s, dict) else ""
    p = str(preset).lower()
    if "35x45" in p or "3545" in p or "7x9" in p:
        return "3545"
    if "30x40" in p or "3040" in p or "3x4" in p:
        return "3040"
    return default
def _collect_debug_points(rgb):
    """얼굴 478포인트(가능시) + 포즈 주요포인트 일부(코, 귀, 어깨) 픽셀 좌표 수집"""
    H, W = rgb.shape[:2]
    pts = []

    # 1) MediaPipe Tasks Face Landmarker
    mp_face = _mp_face_landmarks(rgb)
    if mp_face:
        lms, _ = mp_face
        pts.extend([(p.x * W, p.y * H) for p in lms])

    # 2) Legacy FaceMesh fallback
    if not pts:
        try:
            import mediapipe as mp
            with mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, refine_landmarks=True) as fm:
                res = fm.process(rgb)
            if res.multi_face_landmarks:
                lm = res.multi_face_landmarks[0].landmark
                pts.extend([(p.x * W, p.y * H) for p in lm])
        except Exception:
            pass

    # 3) Pose(어깨/코/귀) 일부
    plms = _mp_pose_landmarks(rgb)
    if plms:
        for i in [0, 7, 8, 11, 12]:  # nose, L/R ear, L/R shoulder
            try:
                pts.append((plms[i].x * W, plms[i].y * H))
            except Exception:
                pass

    # 4) 최후: 얼굴 Haar bbox 모서리 4점
    if not pts:
        try:
            face_cascade = EyeDetector._load_cascade('haarcascade_frontalface_default.xml')
            import cv2
            gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
            faces = face_cascade.detectMultiScale(gray, 1.2, 3) if face_cascade and not face_cascade.empty() else []
            if len(faces) > 0:
                x, y, w, h = max(faces, key=lambda r: r[2]*r[3])
                pts += [(x, y), (x+w, y), (x, y+h), (x+w, y+h)]
        except Exception:
            pass

    return pts


class _DebugPointsRenderer:
    def render(self, image: QImageLike) -> "QImage":
        qi = _to_qimage(image)
        if qi is None:
            raise ValueError("DebugPointsRenderer: invalid image")

        q = qi.convertToFormat(getattr(qi, "Format").Format_RGB888)
        rgb = _rgb_from_qimage(q)

        # 기본 포인트(얼굴 478 + 포즈 일부 등)
        pts = _collect_debug_points(rgb)

        # crown/chin/eye_cx 도출해서 ‘굵은 점’으로 별도 표시
        crown_pt = chin_pt = eye_pt = None
        try:
            crown, chin, eye_cx, W, H, _ = CrownChinEstimator().estimate(qi, return_dbg=True)
            crown_pt = (eye_cx, crown)
            chin_pt  = (eye_cx, chin)
            eye_pt   = (eye_cx, (crown+chin)//2)
        except Exception:
            pass

        out = _draw_small_white_points(rgb, pts, radius=DOT_R)
        # Ensure C-contiguous buffer before OpenCV drawing
        try:
            import numpy as np
            out = out.copy(order="C") if hasattr(out, "copy") else out
            out = np.ascontiguousarray(out)
        except Exception:
            pass

        import cv2
        for p in [crown_pt, chin_pt, eye_pt]:
            if p is not None:
                cv2.circle(out, (int(p[0]), int(p[1])), DOT_R_CROWN, (255, 255, 255), -1, cv2.LINE_AA)

        n = len(pts) + (1 if crown_pt else 0) + (1 if chin_pt else 0) + (1 if eye_pt else 0)
        print(f"[debug] points_only plotted: {n} pts (face/pose + crown/chin)")
        return _qi_from_rgb_np(out)
# -----------------------
# Qt stubs (typing only)
# -----------------------
if TYPE_CHECKING:
    from PySide6.QtGui import QImage, QPixmap  # typing only
else:
    class QImage:  # runtime stubs
        pass
    class QPixmap:
        def toImage(self):
            return QImage()

QImageLike = Union["QImage", "QPixmap", str]

# -----------------------
# Model paths (Tasks)
# -----------------------
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_MODEL_DIR = os.path.join(_THIS_DIR, "models")
MODEL_FACE = os.path.join(_MODEL_DIR, "face_landmarker.task")
MODEL_POSE = os.path.join(_MODEL_DIR, "pose_landmarker_full.task")

# ---------------------------------------------------------------------------
# Mediapipe Tasks singletons (stability: avoid repeated create/destroy)
# ---------------------------------------------------------------------------
_TASKS_DISABLE = bool(int(os.environ.get("AI_RETOUCH_DISABLE_TASKS", "0") or 0))
_FACE_LOCK = threading.Lock()
_POSE_LOCK = threading.Lock()
_FACE_LM = None   # type: ignore[var-annotated]
_POSE_LM = None   # type: ignore[var-annotated]

def _close_tasks_singletons():
    global _FACE_LM, _POSE_LM
    try:
        if _FACE_LM is not None and hasattr(_FACE_LM, "close"):
            try: _FACE_LM.close()
            except Exception: pass
    finally:
        _FACE_LM = None
    try:
        if _POSE_LM is not None and hasattr(_POSE_LM, "close"):
            try: _POSE_LM.close()
            except Exception: pass
    finally:
        _POSE_LM = None

atexit.register(_close_tasks_singletons)

# -----------------------
# Spec ranges by ratio
# -----------------------
@dataclass
class SpecRanges:
    ratio: Tuple[int, int]                  # (W, H)
    head_pct: Tuple[float, float]           # (chin - crown) / H
    top_pct: Tuple[float, float]            # (crown - top) / H

RATIO_PRESETS: Dict[Tuple[int, int], SpecRanges] = {
    (3, 4): SpecRanges((3, 4), (0.52, 0.58), (0.06, 0.10)),  # 30×40
    (7, 9): SpecRanges((7, 9), (0.73, 0.78), (0.06, 0.08)),  # 35×45
}

# -----------------------
# QImage helpers
# -----------------------
def _qi_rgb888_format(_QImage):
    try:
        return _QImage.Format.Format_RGB888
    except Exception:
        return getattr(_QImage, "Format_RGB888")

def _rgb_from_qimage(q: "QImage"):
    # QImage → writable C-contig RGB ndarray (HxWx3, uint8)
    from PySide6.QtGui import QImage as _QImage
    import numpy as np
    q2 = q.convertToFormat(_qi_rgb888_format(_QImage))
    w, h = q2.width(), q2.height()
    bpl = q2.bytesPerLine()
    ptr = q2.bits()
    nbytes = h * bpl
    try:
        if hasattr(ptr, "setsize"):
            ptr.setsize(nbytes); buf = bytes(ptr)
        elif hasattr(ptr, "asstring"):
            buf = ptr.asstring(nbytes)
        else:
            buf = ptr.tobytes()
    except Exception:
        buf = bytes(ptr)
    arr = np.frombuffer(buf, dtype="uint8").reshape((h, bpl))[:, : w * 3]
    rgb = arr.reshape(h, w, 3).copy()  # copy → writeable
    return rgb

def _qi_from_rgb_np(arr: Any) -> "QImage":
    import numpy as np
    a = np.asarray(arr, dtype="uint8").copy(order="C")
    h, w = a.shape[:2]
    from PySide6.QtGui import QImage as _QImage
    q = _QImage(a.data, w, h, 3 * w, _qi_rgb888_format(_QImage))
    return q.copy()

def _to_qimage(img: QImageLike) -> Optional["QImage"]:
    try:
        from PySide6.QtGui import QImage as _QImage, QPixmap as _QPixmap
    except Exception:
        _QImage = _QPixmap = None  # type: ignore
    if _QImage is not None and isinstance(img, _QImage):
        return img
    if _QPixmap is not None and isinstance(img, _QPixmap):
        return img.toImage()
    if isinstance(img, str) and img:
        # Try Qt -> OpenCV fallback
        try:
            from PySide6.QtGui import QPixmap as _PM
            pm = _PM(img)
            if hasattr(pm, "isNull") and not pm.isNull():
                return pm.toImage()
        except Exception:
            pass
        try:
            bgr = cv2.imread(img, cv2.IMREAD_COLOR)
            if bgr is None:
                return None
            rgb = bgr[:, :, ::-1]
            return _qi_from_rgb_np(rgb)
        except Exception:
            return None
    return None

def save_jpg(img: "QImage", path: str, quality: int = 100) -> bool:
    import os, cv2
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    try:
        # OpenCV로 저장하면 EXIF 메타(회전)가 제거되어 90° 틀어짐 방지
        bgr = _rgb_from_qimage(img)[:, :, ::-1].copy()
        return bool(cv2.imwrite(path, bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]))
    except Exception:
        try:
            return img.save(path, "JPG", int(quality))
        except Exception:
            return False


# -----------------------
# MediaPipe Tasks helpers
# -----------------------
def _mp_face_landmarks(rgb):
    """return (lms(list[478]), bbox(x,y,w,h)) in pixels; None if fail"""
    if _TASKS_DISABLE:
        return None
    try:
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.core.base_options import BaseOptions
        H, W = rgb.shape[:2]
        global _FACE_LM
        if _FACE_LM is None:
            with _FACE_LOCK:
                if _FACE_LM is None:
                    if not os.path.isfile(MODEL_FACE):
                        return None
                    opts = vision.FaceLandmarkerOptions(
                        base_options=BaseOptions(model_asset_path=MODEL_FACE),
                        running_mode=vision.RunningMode.IMAGE,
                        num_faces=1,
                        output_face_blendshapes=False,
                        output_facial_transformation_matrixes=False,
                    )
                    _FACE_LM = vision.FaceLandmarker.create_from_options(opts)
        if _FACE_LM is None:
            return None
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        # Tasks objects are not documented as thread-safe; guard with lock
        with _FACE_LOCK:
            res = _FACE_LM.detect(mp_img)
        if not res or not res.face_landmarks:
            return None
        lms = res.face_landmarks[0]
        xs = [int(p.x * W) for p in lms]; ys = [int(p.y * H) for p in lms]
        x1, x2 = max(0, min(xs)), min(W - 1, max(xs))
        y1, y2 = max(0, min(ys)), min(H - 1, max(ys))
        return lms, (x1, y1, max(1, x2 - x1), max(1, y2 - y1))
    except Exception:
        return None

def _mp_pose_landmarks(rgb):
    """return list pose landmarks (33) or None"""
    if _TASKS_DISABLE:
        return None
    try:
        import mediapipe as mp
        from mediapipe.tasks.python import vision
        from mediapipe.tasks.python.core.base_options import BaseOptions
        global _POSE_LM
        if _POSE_LM is None:
            with _POSE_LOCK:
                if _POSE_LM is None:
                    if not os.path.isfile(MODEL_POSE):
                        return None
                    opts = vision.PoseLandmarkerOptions(
                        base_options=BaseOptions(model_asset_path=MODEL_POSE),
                        running_mode=vision.RunningMode.IMAGE,
                        num_poses=1,
                        min_pose_detection_confidence=0.35,
                        min_pose_presence_confidence=0.35,
                    )
                    _POSE_LM = vision.PoseLandmarker.create_from_options(opts)
        if _POSE_LM is None:
            return None
        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        with _POSE_LOCK:
            res = _POSE_LM.detect(mp_img)
        return res.pose_landmarks[0] if res and res.pose_landmarks else None
    except Exception:
        return None

# -----------------------
# Eyes: detect + optional balance
# -----------------------
@dataclass
class EyeBox:
    cx: float; cy: float; w: float; h: float  # normalized

@dataclass
class Eyes:
    ok: bool
    left: Optional[EyeBox] = None
    right: Optional[EyeBox] = None

class EyeDetector:
    LIDX = [33, 133, 159, 145]   # left eye contour
    RIDX = [263, 362, 386, 374]  # right eye

    @staticmethod
    def _load_cascade(name: str):
        try:
            cands = []
            if hasattr(cv2, "data") and getattr(cv2.data, "haarcascades", None):
                cands.append(cv2.data.haarcascades + name)
            cands.append(os.path.join(os.path.dirname(cv2.__file__), "data", name))
            cands.append(name)
            for p in cands:
                if os.path.exists(p):
                    c = cv2.CascadeClassifier(p)
                    if not c.empty():
                        return c
        except Exception:
            return None
        return None

    def detect(self, image: QImageLike) -> Eyes:
        qi = _to_qimage(image)
        if qi is None:
            return Eyes(False)
        q = qi.convertToFormat(getattr(qi, "Format").Format_RGB888)
        rgb = _rgb_from_qimage(q)
        H, W = rgb.shape[:2]

        # Tasks 우선
        mp_res = _mp_face_landmarks(rgb)
        if mp_res is not None:
            lms, _ = mp_res
            def box(idxs):
                xs = [lms[i].x for i in idxs]; ys = [lms[i].y for i in idxs]
                x1, x2 = max(0.0, min(xs)), min(1.0, max(xs))
                y1, y2 = max(0.0, min(ys)), min(1.0, max(ys))
                return EyeBox(cx=(x1 + x2) / 2, cy=(y1 + y2) / 2, w=(x2 - x1), h=(y2 - y1))
            L, R = box(self.LIDX), box(self.RIDX)
            if L.cx > R.cx: L, R = R, L
            return Eyes(True, L, R)

        # Legacy FaceMesh
        try:
            import mediapipe as mp
            with mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, refine_landmarks=True) as fm:
                res = fm.process(rgb)
            if res.multi_face_landmarks:
                lm = res.multi_face_landmarks[0].landmark
                def box2(idxs):
                    xs = [lm[i].x for i in idxs]; ys = [lm[i].y for i in idxs]
                    x1, x2 = max(0.0, min(xs)), min(1.0, max(xs))
                    y1, y2 = max(0.0, min(ys)), min(1.0, max(ys))
                    return EyeBox(cx=(x1+x2)/2, cy=(y1+y2)/2, w=(x2-x1), h=(y2-y1))
                L, R = box2(self.LIDX), box2(self.RIDX)
                if L.cx > R.cx: L, R = R, L
                return Eyes(True, L, R)
        except Exception:
            pass

        # Haar 폴백
        face_cascade = self._load_cascade('haarcascade_frontalface_default.xml')
        eye_cascade  = self._load_cascade('haarcascade_eye_tree_eyeglasses.xml')
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
        faces = []
        if face_cascade is not None and not face_cascade.empty():
            try: faces = face_cascade.detectMultiScale(gray, 1.2, 3)
            except Exception: faces = []
        if len(faces) > 0:
            fx, fy, fw, fh = max(faces, key=lambda r: r[2]*r[3])
        else:
            fx = fy = 0; fw = W; fh = H
        roi = gray[fy:fy+fh, fx:fx+fw]
        eyes = []
        if eye_cascade is not None and not eye_cascade.empty():
            try: eyes = eye_cascade.detectMultiScale(roi, 1.2, 3)
            except Exception: eyes = []
        if len(eyes) < 1: return Eyes(False)
        eyes = sorted(eyes, key=lambda r: (r[1], -r[2]))[:2]
        infos = []
        for (ex, ey, ew, eh) in eyes:
            ex += fx; ey += fy
            infos.append(EyeBox(cx=(ex+ew/2)/W, cy=(ey+eh/2)/H, w=ew/W, h=eh/H))
        infos.sort(key=lambda e: e.cx)
        if len(infos) == 1: return Eyes(True, infos[0], None)
        return Eyes(True, infos[0], infos[-1])

class EyeBalancer:
    """작은 쪽만 확장(축소 금지), 최대 +20%"""
    def adjust(self, image: QImageLike, strength: float = 0.45, *, enable: bool = True) -> "QImage":
        qi = _to_qimage(image)
        if qi is None or not enable:
            return qi if isinstance(image, QImage) else image  # type: ignore
        import numpy as np
        det = EyeDetector().detect(qi)
        if not det.ok or det.left is None or det.right is None:
            return qi

        L, R = det.left, det.right
        q = qi.convertToFormat(getattr(qi, "Format").Format_RGB888)
        H, W = q.height(), q.width()
        rgb = _rgb_from_qimage(q)

        print(f"[eyes] before  L(w{L.w:.3f},h{L.h:.3f})  R(w{R.w:.3f},h{R.h:.3f})")

        def grow_only(s, b):
            if s <= 1e-8 or b <= 1e-8: return 1.0
            gap = (b / s) - 1.0
            g = 1.0 + max(0.0, min(0.20, strength * gap))
            return float(min(1.20, max(1.0, g)))

        if (L.w * L.h) <= (R.w * R.h):
            sxL, syL, sxR, syR = grow_only(L.w, R.w), grow_only(L.h, R.h), 1.0, 1.0
            smaller = "L"
        else:
            sxL, syL, sxR, syR = 1.0, 1.0, grow_only(R.w, L.w), grow_only(R.h, L.h)
            smaller = "R"

        def warp_eye(p: EyeBox, sx: float, sy: float, img):
            if abs(sx - 1.0) < 1e-3 and abs(sy - 1.0) < 1e-3: return img
            cx, cy = int(p.cx * W), int(p.cy * H)
            rx, ry = int(max(8, p.w * W * 1.45)), int(max(8, p.h * H * 1.45))
            M = np.array([[sx, 0, (1 - sx) * cx], [0, sy, (1 - sy) * cy]], np.float32)
            layer = cv2.warpAffine(img, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
            m = np.zeros((H, W), np.uint8)
            cv2.ellipse(m, (cx, cy), (rx, ry), 0, 0, 360, 255, -1, cv2.LINE_AA)
            m = cv2.GaussianBlur(m, (0, 0), max(2.0, min(rx, ry) * 0.30)).astype("float32") / 255.0
            return (layer * m[..., None] + img * (1 - m[..., None])).astype("uint8")

        out = rgb.copy()
        out = warp_eye(L, sxL, syL, out)
        out = warp_eye(R, sxR, syR, out)
        print(f"[eyes] scales  smaller={smaller}  L→(sx{sxL:.3f},sy{syL:.3f})  R→(sx{sxR:.3f},sy{syR:.3f})")
        return _qi_from_rgb_np(out)

# -----------------------
# Face roll align (head-only)
# -----------------------
class FaceRollAligner:
    def align(self, image: QImageLike, *, mode: str = "local") -> "QImage":
        qi = _to_qimage(image)
        if qi is None:
            raise ValueError("FaceRollAligner.align: invalid image")
        import numpy as np
        q = qi.convertToFormat(getattr(qi, "Format").Format_RGB888)
        rgb = _rgb_from_qimage(q)
        H, W = rgb.shape[:2]

        # eyes slope → angle (부호: 오른쪽 눈이 낮으면 +dy → -θ)
        ed = EyeDetector().detect(qi)
        angle = 0.0
        if ed.ok and ed.left and ed.right:
            dx = ed.right.cx - ed.left.cx
            dy = ed.right.cy - ed.left.cy
            if abs(dx) > 1e-6:
                angle = -math.degrees(math.atan2(dy, dx))
        # 과도 회전 보호
        max_rot = 15.0
        angle = max(-max_rot, min(max_rot, angle))
        if abs(angle) < 0.8:
            print(f"[pose] roll_face≈0 → skip")
            return qi

        # crown/chin
        crown, chin, _, _, _ = CrownChinEstimator().estimate(qi)

        # 회전 중심: 얼굴 bbox 없을 때는 crown~chin 기반 추정
        fb = None
        mp = _mp_face_landmarks(rgb)
        if mp is not None:
            _, fb = mp
        if fb is None:
            fx, fy, fw, fh = 0, int(max(0, crown - (chin - crown)*1.1)), W, int((chin - crown)*2.0)
        else:
            fx, fy, fw, fh = fb
        cx = int(fx + fw * 0.5); cy = int(fy + fh * 0.45)

        # 회전 레이어
        M = cv2.getRotationMatrix2D((float(cx), float(cy)), float(angle), 1.0)
        rot = cv2.warpAffine(rgb, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        # 얼굴 타원 마스크 + 턱 힌지(턱-4px~턱+22px: 1→0 감쇠)
        rx = int(fw * 0.60); ry = int(fh * 0.75)
        m = np.zeros((H, W), np.float32)
        cv2.ellipse(m, (cx, cy), (max(8, rx), max(8, ry)), 0, 0, 360, 1.0, -1, cv2.LINE_AA)
        y0 = int(max(0, chin - 4)); y1 = int(min(H - 1, chin + 22))
        if y1 > y0:
            ramp = np.linspace(1.0, 0.0, y1 - y0, dtype=np.float32)
            m[y0:y1, :] *= ramp[:, None]
        if y1 < H:
            m[y1:, :] = 0.0
        m = cv2.GaussianBlur(m, (0, 0), 9)

        out = (rot * m[..., None] + rgb * (1.0 - m[..., None])).astype("uint8")
        print(f"[pose] local rotate {angle:+.2f}° (chin={chin} hinge=[{y0},{y1}))")
        return _qi_from_rgb_np(out)

# -----------------------
# Crown & chin estimation
# -----------------------
class CrownChinEstimator:
    def estimate(self, image: QImageLike, *, return_dbg: bool = False):
        """Return (crown_y, chin_y, eye_cx, W, H)  [Debug_mod/return_dbg=True이면 + dbg_pts]"""
        qi = _to_qimage(image)
        if qi is None:
            raise ValueError("CrownChinEstimator.estimate: invalid image")
        import numpy as np
        q = qi.convertToFormat(getattr(qi, "Format").Format_RGB888)
        rgb = _rgb_from_qimage(q)
        H, W = rgb.shape[:2]

        dbg_pts = []

        y_crown = None; y_chin = None; x_eye_mid = W//2
        # 1) Legacy FaceMesh — landmark id 이용(정밀)
        try:
            import mediapipe as mp
            with mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, refine_landmarks=True) as fm:
                res = fm.process(rgb)
            if res.multi_face_landmarks:
                lm = res.multi_face_landmarks[0].landmark
                def px(i): return (lm[i].x * W, lm[i].y * H)
                for i in [10, 152, 33, 263]:
                    x, y = px(i)
                    if 0 <= x < W and 0 <= y < H: dbg_pts.append((x, y))
                p10  = np.array(px(10), dtype=float)
                p152 = np.array(px(152), dtype=float)
                eyeL = np.array(px(33), dtype=float)
                eyeR = np.array(px(263), dtype=float)
                x_eye_mid = int(np.clip(0.5*(eyeL[0]+eyeR[0]), 0, W-1))
                v_up = p10 - p152
                alpha = 0.24
                est = p10 + alpha * v_up
                y_crown = float(np.clip(est[1], 0, H-1))
                y_chin  = float(np.clip(p152[1], 0, H-1))
        except Exception:
            y_crown = None

        # 2) Pose 폴백
        if y_crown is None or y_chin is None:
            lms = _mp_pose_landmarks(rgb)
            if lms:
                def P(i): return (lms[i].x*W, lms[i].y*H)
                nose = np.array(P(0)); le = np.array(P(7)); re = np.array(P(8))
                ls   = np.array(P(11)); rs = np.array(P(12))
                for p in (nose, le, re, ls, rs):
                    x, y = p
                    if 0 <= x < W and 0 <= y < H: dbg_pts.append((x, y))
                m  = 0.5*(le+re); s = 0.5*(ls+rs)
                u  = m - s; nu = np.linalg.norm(u) or 1.0; u /= nu
                d1 = np.linalg.norm(m - nose); d2 = np.linalg.norm(le - re)
                scale = 0.8*d1 + 0.5*d2
                c = m + 1.0*scale*u
                y_crown = float(np.clip(c[1], 0, H-1))
                y_chin  = float(np.clip((nose + 1.6*(nose-s))[1], 0, H-1))
                x_eye_mid = int(np.clip(m[0], 0, W-1))

        # 3) 상단 엣지 미세 보정(흰 배경 가정)
        try:
            lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB)
            L = lab[...,0].astype("float32")
            half = max(1, int(0.05 * W))
            x0, x1 = max(0, x_eye_mid - half), min(W, x_eye_mid + half)
            stripe = L[:, x0:x1]
            top_band_h = max(1, int(0.06 * H))
            bg = stripe[:top_band_h].mean()
            diff = abs(stripe - bg).max(axis=1)
            g = cv2.Sobel(stripe, cv2.CV_32F, 0, 1, ksize=3)
            g_abs = abs(g).max(axis=1)
            thr_d = max(8.0, diff[:top_band_h*2].mean() + 2*diff[:top_band_h*2].std())
            thr_g = max(8.0, g_abs[:top_band_h*2].mean() + 2*g_abs[:top_band_h*2].std())
            ys = (diff > thr_d) | (g_abs > thr_g)
            idxs = ys.nonzero()[0]
            if idxs.size:
                y_edge = int(idxs[0])
                if y_crown is None or y_edge < y_crown + 6:
                    y_crown = float(y_edge)
        except Exception:
            pass

        # 4) Haar 최후 폴백
        if y_crown is None or y_chin is None:
            try:
                face_cascade = EyeDetector._load_cascade('haarcascade_frontalface_default.xml')
                gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
                faces = []
                if face_cascade is not None and not face_cascade.empty():
                    try: faces = face_cascade.detectMultiScale(gray, 1.2, 3)
                    except Exception: faces = []
                if faces:
                    fx, fy, fw, fh = max(faces, key=lambda r: r[2]*r[3])
                    dbg_pts += [(fx,fy),(fx+fw,fy),(fx,fy+fh),(fx+fw,fy+fh)]
                    y_crown = float(max(0, int(fy - fh * 0.18)))
                    y_chin  = float(min(H-1, int(fy + fh * 0.92)))
            except Exception:
                pass

        # Finalize with NaN-safe fallback and clamp
        try:
            yc = float(y_crown) if y_crown is not None else 0.0
        except Exception:
            yc = 0.0
        try:
            yn = float(y_chin) if y_chin is not None else (0.65 * H)
        except Exception:
            yn = 0.65 * H
        if not (isinstance(yc, float) and math.isfinite(yc)):
            yc = 0.0
        if not (isinstance(yn, float) and math.isfinite(yn)):
            yn = 0.65 * H
        y_crown = int(max(0, min(H-1, int(yc))))
        y_chin  = int(max(0, min(H-1, int(yn))))
        print(f"[crown] y_crown={y_crown} y_chin={y_chin} x_eye_mid={x_eye_mid}")

        if return_dbg and Debug_mod:
            return y_crown, y_chin, int(x_eye_mid), W, H, dbg_pts
        return y_crown, y_chin, int(x_eye_mid), W, H

# -----------------------
# Shoulder leveling (horizontal shear, below chin)
# -----------------------
class ShoulderLeveler:
    def level(self, image: QImageLike, *, strength: float = 1.0, max_deg: float = 8.0) -> "QImage":
        qi = _to_qimage(image)
        if qi is None:
            raise ValueError("ShoulderLeveler.level: invalid image")
        import cv2, numpy as np, math
        q = qi.convertToFormat(getattr(qi, "Format").Format_RGB888)
        rgb = _rgb_from_qimage(q)
        H, W = rgb.shape[:2]

        lms = _mp_pose_landmarks(rgb)
        if not lms:
            print("[shoulder] no pose → skip")
            return qi

        def P(i): return (lms[i].x * W, lms[i].y * H)
        xL, yL = P(11); xR, yR = P(12)
        if xL > xR: xL, xR, yL, yR = xR, xL, yR, yL

        slope = float(math.degrees(math.atan2((yR - yL), (xR - xL))))
        if abs(slope) < 1.2:
            print("[shoulder] slope≈0 → skip")
            return qi

        crown, chin, _, _, _ = CrownChinEstimator().estimate(qi)
        y_seam = int(min(H-1, max(chin + int(H * 0.01), max(int(yL), int(yR)) + int(H * 0.02))))

        m_req = -math.tan(math.radians(slope))
        m = float(max(-math.tan(math.radians(max_deg)), min(math.tan(math.radians(max_deg)), m_req*max(0.0, min(1.0, strength)))))
        # Limit over-correction with a shear cap (safety)
        SHEAR_CAP = 0.14  # approx tan(8°)
        if m > SHEAR_CAP:
            m = SHEAR_CAP
        elif m < -SHEAR_CAP:
            m = -SHEAR_CAP

        # x' = x + m*(y - y0)  → y0=y_seam을 정확히 사용
        M = np.array([[1.0, m, -m * y_seam], [0.0, 1.0, 0.0]], np.float32)
        sheared = cv2.warpAffine(rgb, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)

        band = max(12, int(H * 0.05)); y0 = max(0, y_seam - band)
        mask = np.zeros((H, 1), np.float32)
        if y0 < y_seam:
            ramp = np.linspace(0.0, 1.0, y_seam - y0, dtype=np.float32)
            mask[y0:y_seam, 0] = ramp
        mask[y_seam:, 0] = 1.0
        mask = np.repeat(mask, W, axis=1)
        out = (sheared * mask[..., None] + rgb * (1.0 - mask[..., None])).astype("uint8")
        print(f"[shoulder] slope={slope:+.2f}° seam_y={y_seam} m={m:+.5f}")
        return _qi_from_rgb_np(out)

# -----------------------
# Spec crop using crown & chin
# -----------------------
# -----------------------
# Spec crop using crown & chin  (PATCHED)
# -----------------------
class SpecCropper:
    def crop(self, image: QImageLike, *, ratio: Union[Tuple[int,int], str]=(3,4)) -> "QImage":
        qi = _to_qimage(image)
        if qi is None:
            raise ValueError("SpecCropper.crop: invalid image")
        q = qi.convertToFormat(getattr(qi, "Format").Format_RGB888)
        rgb = _rgb_from_qimage(q)

        est = CrownChinEstimator().estimate(qi, return_dbg=Debug_mod)
        if Debug_mod:
            crown, chin, eye_cx, W, H, dbg_pts = est
            rgb = _draw_small_white_points(rgb, dbg_pts)
            print(f"[debug] mesh points plotted: {len(dbg_pts)}")
        else:
            crown, chin, eye_cx, W, H = est

        # ----- ratio 키/종횡비 결정 -----
        ratio_key: str
        if isinstance(ratio, str):
            ratio_key = ratio
            aspect = 3/4 if ratio_key == "3040" else 7/9 if ratio_key == "3545" else 7/9
        else:
            rw, rh = ratio
            aspect = rw / float(rh)
            if (rw, rh) == (3, 4):
                ratio_key = "3040"
            elif (rw, rh) == (7, 9):
                ratio_key = "3545"
            else:
                # 종횡비로 추정
                ratio_key = "3040" if abs(aspect - 0.75) < abs(aspect - 7/9) else "3545"

        # ----- settings.json 적용(실패 시 디폴트) -----
        prof = get_profile_spec(ratio_key)
        head_lo, head_hi = prof["head_pct_min"], prof["head_pct_max"]
        top_lo,  top_hi  = prof["top_pct_min"],  prof["top_pct_max"]

        import numpy as np, cv2
        head_span = max(1, chin - crown)

        # 1) crop_h 결정(Head% 기준)
        Hmin  = head_span / float(head_hi)
        Hmax  = head_span / float(head_lo)
        Hgeom = min(H, int(W / aspect))
        crop_h = int(round(min(max(0.5 * (Hmin + min(Hmax, Hgeom)), 1.0), max(Hgeom, 1))))
        crop_w = int(round(crop_h * aspect))

        # 2) Top% 중앙값으로 배치
        t_target = 0.5 * (top_lo + top_hi)
        x_tgt = int(round(eye_cx - crop_w * 0.5))
        y_tgt = int(round(crown - t_target * crop_h))

        # 3) 패딩(흰색)
        pad_top    = max(0, -y_tgt)
        pad_bottom = max(0, (y_tgt + crop_h) - H)
        pad_left   = max(0, -x_tgt)
        pad_right  = max(0, (x_tgt + crop_w) - W)
        if pad_top or pad_bottom or pad_left or pad_right:
            rgb = cv2.copyMakeBorder(rgb, pad_top, pad_bottom, pad_left, pad_right,
                                     borderType=cv2.BORDER_CONSTANT, value=(255, 255, 255))
            H += pad_top + pad_bottom; W += pad_left + pad_right
            crown += pad_top; chin += pad_top; eye_cx += pad_left
            x_tgt += pad_left; y_tgt += pad_top
            print(f"[crop] padded t/b/l/r = {pad_top},{pad_bottom},{pad_left},{pad_right}")

        # 4) 최종 크롭
        x = max(0, min(W - crop_w, x_tgt))
        y = max(0, min(H - crop_h, y_tgt))
        crop = np.ascontiguousarray(rgb[y:y+crop_h, x:x+crop_w])

        act_head = head_span / float(crop_h)
        act_top  = (crown - y) / float(crop_h)
        print(f"[crop] ratio_key={ratio_key} rect=({x},{y},{crop_w},{crop_h}) "
              f"Head%={act_head:.3f} target[{head_lo:.2f},{head_hi:.2f}] "
              f"Top%={act_top:.3f} target[{top_lo:.2f},{top_hi:.2f}]")
        return _qi_from_rgb_np(crop)


# -----------------------
# Pipeline
# -----------------------
class RetouchPipeline:
    def __init__(self) -> None:
        self.face = FaceRollAligner()
        self.shoulder = ShoulderLeveler()
        self.eyes = EyeBalancer()
        self.cropper = SpecCropper()

    def apply(
        self,
        img: QImageLike,
        *,
        ratio: Union[Tuple[int,int], str] = (7,9),
        face_align_mode: str = "local",
        shoulder_strength: float = 1.0,
        eye_balance: bool = True,
    ) -> "QImage":
        qi = _to_qimage(img)
        if qi is None:
            raise ValueError("RetouchPipeline.apply: invalid image")

        # ★ 점만 찍기 모드: 나머지 단계 전부 스킵하고 바로 종료
        if DEBUG_POINTS_ONLY:
            print("[debug] DEBUG_POINTS_ONLY=True → skip face/shoulder/eyes/crop")
            return _DebugPointsRenderer().render(qi)

        # (아래는 정상 파이프라인, 현재 모드에선 실행되지 않음)
        q1 = self.face.align(qi, mode=face_align_mode)
        q2 = self.shoulder.level(q1, strength=shoulder_strength)
        q3 = self.eyes.adjust(q2, strength=0.4, enable=eye_balance)
        q4 = self.cropper.crop(q3, ratio=ratio)
        return q4

# -----------------------
# File entry (호출부와 호환 유지)
# -----------------------
def process_file(
    in_path: str,
    out_path: str,
    *,
    ratio: Union[Tuple[int,int], str] = (3,4),   # "3040" / "3545" 또는 (3,4)/(7,9)
    face_align_mode: str = "local",
    shoulder_strength: float = 1.0,
    eye_balance: bool = False,
) -> bool:
    try:
        print(f"[retouch] start: {in_path} → {out_path}")
        qi = _to_qimage(in_path)
        if qi is None:
            print("[retouch] load fail")
            return False
        q = RetouchPipeline().apply(
            qi,
            ratio=ratio,
            face_align_mode=face_align_mode,
            shoulder_strength=shoulder_strength,
            eye_balance=eye_balance,
        )
        ok = save_jpg(q, out_path, 100)
        print(f"[retouch] done ok={ok}")
        return bool(ok)
    except Exception as e:
        print(f"[retouch] error: {e}")
        return False


def process_fixed_paths(*, ratio_default: str = "3545",
                        face_align_mode: str = "local",
                        shoulder_strength: float = 1.0,
                        eye_balance: bool = False) -> bool:
    """Process using fixed input/output from settings.json.
    - Input:  paths.origin (fallback C:\\PhotoBox\\origin_photo.jpg)
    - Output: paths.ai_out (fallback C:\\PhotoBox\\ai_origin_photo.jpg)
    - Ratio:  overlay.preset heuristic → "3040"|"3545"; fallback ratio_default
    Safe fallback: on failure, copies input to output when possible.
    """
    in_path, out_path = _resolve_fixed_paths()
    ratio = _select_ratio_from_settings(ratio_default)
    try:
        print(f"[retouch] fixed start: {in_path} -> {out_path} ratio={ratio}")
        qi = _to_qimage(in_path)
        if qi is None:
            print("[retouch] load fail (fixed)")
            # still attempt fallback copy if input exists
            if os.path.isfile(in_path):
                try:
                    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
                    import shutil
                    shutil.copy2(in_path, out_path)
                    print("[retouch] fallback copy (fixed)")
                    return True
                except Exception:
                    pass
            return False
        q = RetouchPipeline().apply(
            qi,
            ratio=ratio,
            face_align_mode=face_align_mode,
            shoulder_strength=shoulder_strength,
            eye_balance=eye_balance,
        )
        ok = save_jpg(q, out_path, 100)
        if not ok and os.path.isfile(in_path):
            try:
                os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
                import shutil
                shutil.copy2(in_path, out_path)
                print("[retouch] fallback copy (save fail)")
                return True
            except Exception:
                pass
        print(f"[retouch] fixed done ok={ok}")
        return bool(ok)
    except Exception as e:
        print(f"[retouch] fixed error: {e}")
        # fallback copy on error
        try:
            if os.path.isfile(in_path):
                os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
                import shutil
                shutil.copy2(in_path, out_path)
                print("[retouch] fallback copy (exception)")
                return True
        except Exception:
            pass
        return False


def process_fixed_paths_session(ratio_code: Optional[str] = None,
                                *,
                                face_align_mode: str = "local",
                                shoulder_strength: float = 1.0,
                                eye_balance: bool = False) -> bool:
    """Process fixed I/O with explicit session ratio string.
    - Input:  C:\\PhotoBox\\origin_photo.jpg (or settings.paths.origin)
    - Output: C:\\PhotoBox\\ai_origin_photo.jpg (or settings.paths.ai_out)
    - Ratio:  ratio_code in {"3040","3545"}; default to "3545" if missing/invalid.
    Safe fallback: on any failure, copy input to output if possible.
    """
    in_path, out_path = _resolve_fixed_paths()
    ratio_key = str(ratio_code).strip() if ratio_code else "3545"
    if ratio_key not in ("3040", "3545"):
        ratio_key = "3545"
    try:
        print(f"[retouch] fixed(session) start: {in_path} -> {out_path} ratio={ratio_key}")
        qi = _to_qimage(in_path)
        if qi is None:
            print("[retouch] load fail (fixed/session)")
            if os.path.isfile(in_path):
                try:
                    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
                    import shutil
                    shutil.copy2(in_path, out_path)
                    print("[retouch] fallback copy (fixed/session)")
                    return True
                except Exception:
                    pass
            return False
        q = RetouchPipeline().apply(
            qi,
            ratio=ratio_key,
            face_align_mode=face_align_mode,
            shoulder_strength=shoulder_strength,
            eye_balance=eye_balance,
        )
        ok = save_jpg(q, out_path, 100)
        if not ok and os.path.isfile(in_path):
            try:
                os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
                import shutil
                shutil.copy2(in_path, out_path)
                print("[retouch] fallback copy (save fail, fixed/session)")
                return True
            except Exception:
                pass
        print(f"[retouch] fixed(session) done ok={ok}")
        return bool(ok)
    except Exception as e:
        print(f"[retouch] fixed(session) error: {e}")
        try:
            if os.path.isfile(in_path):
                os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
                import shutil
                shutil.copy2(in_path, out_path)
                print("[retouch] fallback copy (exception, fixed/session)")
                return True
        except Exception:
            pass
        return False

def process_photobox_session(session_ratio: str = "3545") -> bool:
    in_p  = r"C:\PhotoBox\origin_photo.jpg"
    out_p = r"C:\PhotoBox\ai_origin_photo.jpg"
    return process_file(in_p, out_p, ratio=session_ratio)
