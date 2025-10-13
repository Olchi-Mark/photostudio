#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
?ъ쭊 ?꾩껜 ?뚯쟾(v2) + ?닿묠 ?섑룊 蹂댁젙 + ?뺤닔由??깅걹 鍮④컙???쒖떆瑜??섑뻾?쒕떎.
???뚯씪? 湲곗〈 ?명꽣?섏씠??process_file ??瑜??좎??쒕떎.
"""

from __future__ import annotations
import os, math, logging
from typing import Tuple
import cv2
import numpy as np

logger = logging.getLogger(__name__)

# ?섍꼍 ?ㅼ쐞移??쒕떇媛?(湲곕낯媛??좎? 媛??
_MAX_ROLL_DEG = float(os.environ.get("AI_MAX_ROLL_DEG", "2.0") or 2.0)   # ?쇨뎬 ?뚯쟾 理쒕? 媛곷룄(?덈?媛?
_CROWN_ALPHA  = float(os.environ.get("AI_CROWN_ALPHA", "0.42") or 0.42)  # p10 湲곕컲 ?뺤닔由??ㅽ봽??鍮꾩쑉
_ROLL_FLIP    = str(os.environ.get("AI_ROLL_FLIP", "0")).strip().lower() in ("1","true","yes")


# -----------------------
# ?대? ?좏떥
# -----------------------
def _load_image(path: str) -> np.ndarray | None:
    """?대?吏瑜?BGR(np.uint8)濡?濡쒕뱶?쒕떎."""
    if not path:
        return None
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    return img


def save_jpg_bgr(bgr: np.ndarray, path: str, quality: int = 100) -> bool:
    """BGR ?대?吏瑜?JPEG濡???ν븳??"""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        return bool(cv2.imwrite(path, bgr, [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]))
    except Exception as e:
        logger.error("[save] ????ㅽ뙣: %s", e)
        return False


# -----------------------
# Face/pose 異붿젙 (mediapipe 媛꾩씠 ?ъ슜)
# -----------------------
def _mp_face_mesh(bgr: np.ndarray):
    """(?깃났) landmark list 諛섑솚, ?ㅽ뙣 ??None.
    10(?대쭏 ?곷?), 152(?깅걹), 33/263(?덇?) ?ъ슜.
    """
    try:
        import mediapipe as mp
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        with mp.solutions.face_mesh.FaceMesh(static_image_mode=True, max_num_faces=1, refine_landmarks=True) as fm:
            res = fm.process(rgb)
        if res.multi_face_landmarks:
            return res.multi_face_landmarks[0].landmark
    except Exception:
        return None
    return None


def _mp_pose(bgr: np.ndarray):
    try:
        import mediapipe as mp
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        with mp.solutions.pose.Pose(static_image_mode=True) as pose:
            res = pose.process(rgb)
        if res.pose_landmarks:
            return res.pose_landmarks.landmark
    except Exception:
        return None
    return None


# -----------------------
# Crown/Chin 異붿젙
# -----------------------
def _head_profile_for_ratio(ratio: object | None) -> Tuple[float, float]:
    """紐낆꽭 鍮꾩쑉???곕Ⅸ Head% 踰붿쐞瑜?諛섑솚?쒕떎."""
    try:
        if isinstance(ratio, (tuple, list)) and len(ratio) == 2:
            rw, rh = int(ratio[0]), int(ratio[1])
            key = '3040' if (rw, rh) == (3, 4) else '3545' if (rw, rh) == (7, 9) else '3545'
        else:
            s = str(ratio).strip().lower() if ratio else ''
            key = '3040' if ('3040' in s or '3x4' in s) else '3545'
    except Exception:
        key = '3545'
    if key == '3040':
        return (0.52, 0.58)
    return (0.73, 0.78)


def _edge_penalty(bgr: np.ndarray, x_center: int, y_cand: int) -> float:
    """?곷떒 ?ㅽ듃?쇱씠???먯? ?鍮꾨줈 ?꾨낫 ?믪씠???⑤꼸?곕? 怨꾩궛?쒕떎."""
    H, W = bgr.shape[:2]
    x0 = max(0, x_center - int(0.04 * W)); x1 = min(W, x_center + int(0.04 * W))
    if x1 <= x0:
        return 0.0
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY).astype('float32')
    stripe = gray[:, x0:x1]
    top_band = max(2, int(0.06 * H))
    bg = float(stripe[:top_band].mean())
    diff = np.abs(stripe - bg).max(axis=1)
    g = cv2.Sobel(stripe, cv2.CV_32F, 0, 1, ksize=3)
    g_abs = np.abs(g).max(axis=1)
    thr_d = max(8.0, float(diff[:top_band*2].mean() + 2*diff[:top_band*2].std()))
    thr_g = max(8.0, float(g_abs[:top_band*2].mean() + 2*g_abs[:top_band*2].std()))
    ys = (diff > thr_d) | (g_abs > thr_g)
    idxs = np.nonzero(ys)[0]
    if idxs.size == 0:
        return 0.0
    y_edge = int(idxs[0])
    if y_cand < y_edge - 2:
        return float((y_edge - y_cand) * 2.0)
    if y_cand > y_edge + 20:
        return float((y_cand - (y_edge + 20)) * 0.2)
    return 0.0


def _estimate_crown_chin(bgr: np.ndarray, *, ratio: object | None = None) -> Tuple[int, int, int]:
    """(?곸쓳?? ?뺤닔由??깅걹/?덉쨷?숈쓣 異붿젙?쒕떎."""
    H, W = bgr.shape[:2]
    lms = _mp_face_mesh(bgr)
    if lms:
        p10 = lms[10]; p152 = lms[152]; pL = lms[33]; pR = lms[263]
        x_eye = int(np.clip(0.5 * (pL.x + pR.x) * W, 0, W - 1))
        y_chin = int(np.clip(p152.y * H, 0, H - 1))

        head_lo, head_hi = _head_profile_for_ratio(ratio)
        head_mid = 0.5 * (head_lo + head_hi)

        # ?꾨낫 alpha 洹몃━??媛쒖씤蹂??곸쓳)
        alphas = [0.16, 0.20, 0.24, 0.28, 0.32, 0.36, float(_CROWN_ALPHA)]
        best = None; best_score = 1e9
        for a in alphas:
            y_c = int(np.clip((p10.y + a * (p10.y - p152.y)) * H, 0, H - 1))
            head_pct = (y_chin - y_c) / max(1.0, float(H))
            spec_cost = abs(head_pct - head_mid) * 100.0
            edge_cost = _edge_penalty(bgr, x_eye, y_c)
            score = spec_cost + edge_cost
            if score < best_score:
                best_score = score; best = (y_c, a)
        y_crown, a_sel = best if best else (int(0.1*H), float(_CROWN_ALPHA))
        logger.info("[crown] alpha_sel=%.3f score=%.2f y_crown=%d y_chin=%d x_eye_mid=%d", a_sel, best_score, y_crown, y_chin, x_eye)
        return y_crown, y_chin, x_eye

    # ?ъ쫰 湲곕컲 ??듭튂
    pl = _mp_pose(bgr)
    if pl:
        nose = pl[0]; le = pl[7]; re = pl[8]
        x_eye = int(np.clip(0.5 * (le.x + re.x) * W, 0, W - 1))
        y_crown = int(np.clip((nose.y - 0.18) * H, 0, H - 1))
        y_chin = int(np.clip((nose.y + 0.22) * H, 0, H - 1))
        logger.info("[crown] pose-only y_crown=%d y_chin=%d x_eye_mid=%d", y_crown, y_chin, x_eye)
        return y_crown, y_chin, x_eye
    # ?ㅽ뙣 ??以묒븰媛?    yc, yn, xe = int(0.1 * H), int(0.8 * H), int(0.5 * W)
    logger.info("[crown] fallback y_crown=%d y_chin=%d x_eye_mid=%d", yc, yn, xe)
    return yc, yn, xe


# -----------------------
# ?뚯쟾(?꾩뿭) + ?닿묠 ?섑룊
# -----------------------
def _eye_roll_angle_deg(bgr: np.ndarray) -> float:
    """醫?????湲곗슱湲?deg, ?쒓퀎?묒닔). ?ㅽ뙣 ??0."""
    lms = _mp_face_mesh(bgr)
    if not lms:
        logger.info("[roll] eyes not found -> 0.0 deg")
        return 0.0
    L, R = lms[33], lms[263]
    dx = (R.x - L.x); dy = (R.y - L.y)
    logger.info("[roll] dx=%.5f dy=%.5f", dx, dy)
    if abs(dx) < 1e-6:
        logger.info("[roll] dx?? -> 0.0 deg")
        return 0.0
    ang_raw = -math.degrees(math.atan2(dy, dx))
    ang = max(-_MAX_ROLL_DEG, min(_MAX_ROLL_DEG, ang_raw))
    if _ROLL_FLIP:
        ang = -ang
        logger.info("[roll] flip enabled -> sign inverted")
    logger.info("[roll] eyes angle raw=%.2f deg, clamp=%.2f deg", ang_raw, ang)
    return ang


def _face_center(bgr: np.ndarray) -> Tuple[int, int]:
    """?쇨뎬 以묒떖(cx, cy)??諛섑솚?쒕떎. ?ㅽ뙣 ???대?吏 以묒떖."""
    H, W = bgr.shape[:2]
    lms = _mp_face_mesh(bgr)
    if lms:
        idxs = [10, 152, 33, 263]
        xs = [lms[i].x for i in idxs]
        ys = [lms[i].y for i in idxs]
        cx = int(np.clip(sum(xs) / len(xs) * W, 0, W - 1))
        cy = int(np.clip(sum(ys) / len(ys) * H, 0, H - 1))
        return cx, cy
    return int(W * 0.5), int(H * 0.5)


# -----------------------
# v1 ?ㅽ????뚯쟾(??以묒떖, ?묒? 媛곷룄 ?ㅽ궢, ?깅걹 x ?뺣젹)
# -----------------------
def _face_bbox_from_mesh(bgr: np.ndarray) -> Tuple[int,int,int,int] | None:
    """
    ?쇨뎬 ?쒕뱶留덊겕 ?꾩껜??諛붿슫??諛뺤뒪瑜??쎌? ?⑥쐞濡?諛섑솚?쒕떎.
    ?ㅽ뙣 ??None.
    """
    H, W = bgr.shape[:2]
    lms = _mp_face_mesh(bgr)
    if not lms:
        return None
    xs = [int(p.x * W) for p in lms]
    ys = [int(p.y * H) for p in lms]
    x1, x2 = max(0, min(xs)), min(W - 1, max(xs))
    y1, y2 = max(0, min(ys)), min(H - 1, max(ys))
    return (x1, y1, max(1, x2 - x1), max(1, y2 - y1))


def _rotate_v1(bgr: np.ndarray) -> np.ndarray:
    """
    v1 洹쒖튃?쇰줈 ?뚯쟾?쒕떎.
    - ??以묒떖???뚯쟾 異뺤쑝濡??ъ슜?쒕떎.
    - 媛곷룄??짹15째濡??쒗븳?섍퀬, 0.8째 誘몃쭔?대㈃ ?ㅽ궢?쒕떎.
    - ?뚯쟾 ???깅걹??x媛 ?쇨뎬 bbox 以묒떖 x???ㅻ룄濡??섑룊 ?대룞 蹂댁젙?쒕떎.
    """
    H, W = bgr.shape[:2]
    lms = _mp_face_mesh(bgr)
    if not lms:
        logger.info("[v1] face landmarks none -> rotate skip")
        return bgr
    L, R = lms[33], lms[263]
    dx, dy = (R.x - L.x), (R.y - L.y)
    if abs(dx) < 1e-6:
        logger.info("[v1] dx?? -> ?ㅽ궢")
        return bgr
    ang_raw = -math.degrees(math.atan2(dy, dx))
    ang = max(-15.0, min(15.0, ang_raw))
    if abs(ang) < 0.8:
        logger.info("[v1] |angle|<0.8° -> skip")
        return bgr

    # ?뚯쟾 以묒떖: ???덉쓽 以묒젏
    cx = int(0.5 * (L.x + R.x) * W)
    cy = int(0.5 * (L.y + R.y) * H)

    # ?쇨뎬 bbox 諛??깅걹 ?꾩튂
    fb = _face_bbox_from_mesh(bgr) or (0, 0, W, H)
    fx, fy, fw, fh = fb
    chin = lms[152]
    chin_x, chin_y = float(chin.x * W), float(chin.y * H)

    # ?뚯쟾 + ?섑룊 蹂댁젙(trans_dx)
    # ?붿껌: ?뚯쟾 遺?몃? 諛섎?濡??곸슜
    M = cv2.getRotationMatrix2D((float(cx), float(cy)), float(-ang), 1.0)
    x_rot = float(M[0,0]*chin_x + M[0,1]*chin_y + M[0,2])
    desired_cx = float(fx + fw * 0.5)
    trans_dx = float(desired_cx - x_rot)
    M[0,2] = float(M[0,2] + trans_dx)

    rot = cv2.warpAffine(bgr, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    logger.info("[v1] rotate(sign-flip) %.2f° center=(%d,%d) trans_dx=%.1f bbox_cx=%.1f", -ang, cx, cy, trans_dx, desired_cx)
    return rot


def _rotate_global(bgr: np.ndarray, angle_deg: float, center: Tuple[int, int]) -> np.ndarray:
    H, W = bgr.shape[:2]
    M = cv2.getRotationMatrix2D(center, angle_deg, 1.0)
    rot = cv2.warpAffine(bgr, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    return rot


def _level_shoulders(bgr: np.ndarray) -> np.ndarray:
    """?닿묠 ?섑룊(媛꾩씠): Pose 11-12 湲곗슱湲곕쭔???꾨떒(shear), ???꾨옒留??곸슜."""
    H, W = bgr.shape[:2]
    pl = _mp_pose(bgr)
    if not pl:
        logger.info("[shoulder] pose none -> skip")
        return bgr
    L, R = pl[11], pl[12]
    xL, yL = L.x * W, L.y * H
    xR, yR = R.x * W, R.y * H
    # 湲곗슱湲??묒닔=?ㅻⅨ履??닿묠媛 ?꾨옒)
    slope_deg = math.degrees(math.atan2((yR - yL), (xR - xL + 1e-6)))
    if abs(slope_deg) < 1.0:
        logger.info("[shoulder] 寃쎌궗 ?묒쓬 -> skip")
        return bgr
    m = -math.tan(math.radians(slope_deg))
    m = float(max(-0.14, min(0.14, m)))  # ?덉쟾 罹?    # ?깆꽑 洹쇱쿂瑜?寃쎄퀎濡??꾨옒留??꾨떒
    y_crown, y_chin, _ = _estimate_crown_chin(bgr)
    y_seam = int(min(H - 1, max(y_chin + int(H * 0.01), int(max(yL, yR) + H * 0.02))))
    M = np.array([[1.0, m, -m * y_seam], [0.0, 1.0, 0.0]], np.float32)
    sh = cv2.warpAffine(bgr, M, (W, H), flags=cv2.INTER_LINEAR, borderMode=cv2.BORDER_REFLECT)
    # 寃쎄퀎 留덉뒪????0~??1)
    band = max(12, int(H * 0.05))
    y0 = max(0, y_seam - band)
    mask = np.zeros((H, 1), np.float32)
    if y0 < y_seam:
        ramp = np.linspace(0.0, 1.0, y_seam - y0, dtype=np.float32)
        mask[y0:y_seam, 0] = ramp
    mask[y_seam:, 0] = 1.0
    mask = np.repeat(mask, W, axis=1)
    out = (sh * mask[..., None] + bgr * (1.0 - mask[..., None])).astype("uint8")
    logger.info("[shoulder] slope_deg=%.2f m=%.4f y_seam=%d band=%d", slope_deg, m, y_seam, band)
    return out


def _draw_red_dots(bgr: np.ndarray, crown_y: int, chin_y: int, cx: int, r: int = 12) -> np.ndarray:
    out = bgr.copy()
    cv2.circle(out, (int(cx), int(crown_y)), int(r), (0, 0, 255), -1, cv2.LINE_AA)
    cv2.circle(out, (int(cx), int(chin_y)), int(r), (0, 0, 255), -1, cv2.LINE_AA)
    return out


# -----------------------
# ???ш린 議곗젅(?묒? ?덈쭔 ?뺣?)
# -----------------------
def _eyes_from_facemesh(bgr: np.ndarray):
    lms = _mp_face_mesh(bgr)
    if not lms:
        return None
    H, W = bgr.shape[:2]
    LIDX = [33, 133, 159, 145]
    RIDX = [263, 362, 386, 374]
    def box(idxs):
        xs = [lms[i].x for i in idxs]; ys = [lms[i].y for i in idxs]
        x1, x2 = max(0.0, min(xs)), min(1.0, max(xs))
        y1, y2 = max(0.0, min(ys)), min(1.0, max(ys))
        cx = (x1 + x2) * 0.5; cy = (y1 + y2) * 0.5; w = (x2 - x1); h = (y2 - y1)
        return (cx, cy, w, h)
    L = box(LIDX); R = box(RIDX)
    # ?뺣젹: L????긽 ?쇱そ
    if L[0] > R[0]:
        L, R = R, L
    return L, R, (W, H)


def _adjust_eyes(bgr: np.ndarray, *, strength: float = 0.45, enable: bool = True) -> np.ndarray:
    if not enable:
        return bgr
    res = _eyes_from_facemesh(bgr)
    if not res:
        return bgr
    (cxL, cyL, wL, hL), (cxR, cyR, wR, hR), (W, H) = res
    # 硫댁쟻 湲곗? ?묒? ?덈쭔 ?뺣?, 理쒕? +20%
    areaL, areaR = wL * hL, wR * hR
    if areaL <= 1e-6 or areaR <= 1e-6:
        return bgr
    grow = 1.0
    # ?뚯뒪??紐⑤뱶: ?묒? 履쎌쓣 臾댁“嫄?+50% ?뺣?
    if areaL < areaR:
        gap = (areaR / areaL) - 1.0
        grow = 1.0 + min(0.05, max(0.0, strength * gap))
        target = ('L', cxL, cyL, wL, hL)
    else:
        gap = (areaL / areaR) - 1.0
        grow = 1.0 + min(0.05, max(0.0, strength * gap))
        target = ('R', cxR, cyR, wR, hR)
    if abs(grow - 1.0) < 1e-3:
        return bgr
    tag, cx, cy, w, h = target
    cx_px, cy_px = int(cx * W), int(cy * H)
    rx, ry = int(max(8, w * W * 1.45)), int(max(8, h * H * 1.45))
    # ?뺣? ?됰젹(以묒떖 湲곗?)
    M = np.array([[grow, 0.0, (1 - grow) * cx_px], [0.0, grow, (1 - grow) * cy_px]], np.float32)
    layer = cv2.warpAffine(bgr, M, (W, H), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REFLECT)
    m = np.zeros((H, W), np.uint8)
    # ???留덉뒪?щ줈 釉붾젋??    m = np.zeros((H, W), np.uint8)
    cv2.ellipse(m, (cx_px, cy_px), (rx, ry), 0, 0, 360, 255, -1, cv2.LINE_AA)
    m = cv2.GaussianBlur(m, (0, 0), max(2.0, min(rx, ry) * 0.30)).astype('float32') / 255.0
    out = (layer * m[..., None] + bgr * (1.0 - m[..., None])).astype('uint8')
    logger.info("[eyes] target=%s grow=%.3f center=(%d,%d) rx=%d ry=%d", tag, grow, cx_px, cy_px, rx, ry)
    return out


# -----------------------
# 鍮꾩쑉 ?щ∼(紐낆꽭: 3040, 3545)
# -----------------------
def _profile_spec(ratio: object | None) -> Tuple[float, float, float, float, float]:
    """(head_lo, head_hi, top_lo, top_hi, aspect) 諛섑솚."""
    key = '3545'
    try:
        if isinstance(ratio, (tuple, list)) and len(ratio) == 2:
            rw, rh = int(ratio[0]), int(ratio[1])
            if (rw, rh) == (3, 4):
                key = '3040'
            elif (rw, rh) == (7, 9):
                key = '3545'
            else:
                key = '3040' if abs(rw / max(1.0, float(rh)) - 0.75) < abs(rw / max(1.0, float(rh)) - 7/9) else '3545'
        else:
            s = str(ratio).strip().lower() if ratio else ''
            if '3040' in s or '3x4' in s:
                key = '3040'
            else:
                key = '3545'
    except Exception:
        key = '3545'
    if key == '3040':
        return (0.52, 0.58, 0.06, 0.10, 3/4)
    return (0.73, 0.78, 0.06, 0.08, 7/9)


def _spec_crop(bgr: np.ndarray, *, ratio: object | None = '3545') -> np.ndarray:
    H, W = bgr.shape[:2]
    head_lo, head_hi, top_lo, top_hi, aspect = _profile_spec(ratio)
    yc, yn, xeye = _estimate_crown_chin(bgr, ratio=ratio)
    head_span = max(1, int(yn - yc))
    head_target = 0.5 * (head_lo + head_hi)
    crop_h = int(round(head_span / max(1e-6, head_target)))
    crop_w = int(round(crop_h * aspect))
    # top target 湲곗??쇰줈 y ?곗젙, x???덉쨷??湲곗? 以묒븰 諛곗튂
    top_target = 0.5 * (top_lo + top_hi)
    x_tgt = int(round(xeye - crop_w * 0.5))
    y_tgt = int(round(yc - top_target * crop_h))
    # ?⑤뵫(?곗깋) ?꾩슂 ??異붽?
    pad_top    = max(0, -y_tgt)
    pad_bottom = max(0, (y_tgt + crop_h) - H)
    pad_left   = max(0, -x_tgt)
    pad_right  = max(0, (x_tgt + crop_w) - W)
    if pad_top or pad_bottom or pad_left or pad_right:
        bgr = cv2.copyMakeBorder(bgr, pad_top, pad_bottom, pad_left, pad_right, borderType=cv2.BORDER_CONSTANT, value=(255,255,255))
        H += pad_top + pad_bottom; W += pad_left + pad_right
        yc += pad_top; yn += pad_top; xeye += pad_left
        x_tgt += pad_left; y_tgt += pad_top
        logger.info("[crop] padded t/b/l/r = %d,%d,%d,%d", pad_top, pad_bottom, pad_left, pad_right)
    x = max(0, min(W - crop_w, x_tgt))
    y = max(0, min(H - crop_h, y_tgt))
    crop = np.ascontiguousarray(bgr[y:y+crop_h, x:x+crop_w])
    act_head = head_span / float(crop_h)
    act_top  = (yc - y) / float(crop_h)
    logger.info("[crop] ratio=%s rect=(%d,%d,%d,%d) Head%%=%.3f target[%.2f,%.2f] Top%%=%.3f target[%.2f,%.2f]",
                str(ratio), x, y, crop_w, crop_h, act_head, head_lo, head_hi, act_top, top_lo, top_hi)
    return crop


# -----------------------
# Public API
# -----------------------
def process_file(
    in_path: str,
    out_path: str,
    *,
    ratio: object | None = None,               # ?명솚???좎?(?뺤닔由??곸쓳 ?ㅼ퐫?댁뿉 ?ъ슜)
    face_align_mode: str = "global",
    shoulder_strength: float = 1.0,            # ?명솚???좎????꾩옱 誘몄꽭 ?곹뼢 ?놁쓬)
    eye_balance: bool = False,                 # ?명솚???좎???誘몄궗??
    **kwargs,
) -> bool:
    """?ъ쭊 ?꾩껜 ?뚯쟾(??湲곗슱湲? 짹2째) ???닿묠 ?섑룊 蹂댁젙. ?뺤닔由??깅걹 鍮④컙???쒖떆.

    - ratio, eye_balance ??異붽? ?ㅼ썙?쒕뒗 怨쇨굅 ?명꽣?섏씠???명솚???꾪빐 諛쏄퀬 臾댁떆?쒕떎.
    """
    try:
        bgr = _load_image(in_path)
        if bgr is None:
            logger.error("[retouch] 로드 실패: %s", in_path)
            return False
        H, W = bgr.shape[:2]
        # v1 ?ㅽ????뚯쟾?쇰줈 蹂寃???以묒떖, 짹15째, 0.8째 ?ㅽ궢, ?깅걹 x ?뺣젹)
        rot = _rotate_v1(bgr)
        out = _level_shoulders(rot)
        # ???ш린 洹좏삎(?묒? ?덈쭔 ?뺣?)
        out = _adjust_eyes(out, strength=0.45, enable=True)
        # 鍮꾩쑉 ?щ∼
        out = _spec_crop(out, ratio=ratio)
        # ?щ∼???대?吏?먯꽌 ?뺤닔由????ъ텛???????쒖떆
        # 정수리/턱 점 오버레이 제거(표시 안 함)
        # yc, yn, xeye = _estimate_crown_chin(out, ratio=ratio)
        # out = _draw_red_dots(out, yc, yn, xeye, r=12)
        ok = save_jpg_bgr(out, out_path, 100)
        return bool(ok)
    except Exception as e:
        logger.error("[retouch] 예외 발생: %s", e)
        return False


