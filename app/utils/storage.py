# app/utils/storage.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, re, json, shutil, datetime as dt
from typing import Dict, Tuple, Optional, List

from PySide6.QtCore import Qt, QTimer, QObject, QSizeF, QMarginsF, QRectF, QPointF
from PySide6.QtGui import (
    QImage, QImageWriter, QPainter, QPdfWriter, QPageSize, QPageLayout,
    QTransform, QPen
)

# ─────────────────────────────────────────────────────────────
# 기본 경로/상수
# ─────────────────────────────────────────────────────────────
APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(APP_ROOT, "data")  # (구) app/data

PHOTOBOX_ROOT = r"C:\PhotoBox"
PDF_ROOT = os.path.join(PHOTOBOX_ROOT, "PDF")
JPG_ROOT = os.path.join(PHOTOBOX_ROOT, "JPG")

# 편집 완료 이미지(최종 보정본) 고정 경로
EDITED_PHOTO_PATH = r"C:\PhotoBox\edited_photo.jpg"  # 300ppi 가정

PRINT_PPI = 300
SIZES_MM: Dict[str, Tuple[int, int]] = {
    "ID_30x40": (30, 40),
    "ID_35x45": (35, 45),
}
EMAIL_LONG_PX = 1600
THUMB_LONG_PX = 480

# ─────────────────────────────────────────────────────────────
# 내부 유틸
# ─────────────────────────────────────────────────────────────
def _ensure_dir(p: str) -> str:
    os.makedirs(p, exist_ok=True); return p

def _sanitize_name(name: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣_]+", "", name or "noname")

def _last4(phone_or_last4: str) -> str:
    d = re.sub(r"\D+", "", phone_or_last4 or "")
    return d[-4:] if len(d) >= 4 else (d or "0000")

def _today_yymmdd() -> str:
    return dt.datetime.now().strftime("%y%m%d")

def _unique_dir(root: str, stem: str) -> str:
    path = os.path.join(root, stem)
    if not os.path.exists(path):
        return path
    i = 2
    while True:
        cand = f"{path}-{i}"
        if not os.path.exists(cand):
            return cand
        i += 1

# ── origin 저장
def save_origin_photo(img: QImage) -> str:
    _ensure_dir(PHOTOBOX_ROOT)
    path = os.path.join(PHOTOBOX_ROOT, "origin_photo.jpg")
    QImage(img).save(path, "JPG", quality=95)
    return path

def save_selected_origin(session: dict) -> str:
    raws = session.get("raw_captures") or []
    idx = session.get("selected_index")
    raw_name = session.get("selected_raw_name")
    if raw_name is None:
        if idx is None:
            sel_cap = session.get("selected_capture")
            try:
                idx = int(os.path.splitext(os.path.basename(sel_cap))[0]) - 1 if sel_cap else 0
            except Exception:
                idx = 0
        if raws and isinstance(idx, int) and 0 <= idx < len(raws):
            raw_name = raws[idx]
    if not raw_name:
        raw_name = "origin_photo.jpg"

    src_dir = session.get("raw_dir") or PHOTOBOX_ROOT
    src = os.path.join(src_dir, raw_name)
    dst_dir = PHOTOBOX_ROOT
    dst = os.path.join(dst_dir, "origin_photo.jpg")
    os.makedirs(dst_dir, exist_ok=True)
    if os.path.exists(src):
        try:
            shutil.copyfile(src, dst)
        except Exception:
            pass
    session["selected_origin_path"] = dst
    session["selected_raw_name"] = raw_name
    return dst

def pdf_date_dir(create: bool = True) -> str:
    path = PDF_ROOT
    if create: os.makedirs(path, exist_ok=True)
    return path

def jpg_date_dir(create: bool = True) -> str:
    path = JPG_ROOT
    if create: os.makedirs(path, exist_ok=True)
    return path

# ── 파일명 규칙
def make_pdf_filename(session: dict, size_key: str, when: Optional[dt.datetime] = None) -> str:
    name = str(session.get("name", "noname"))
    number = str(session.get("number", "0000"))
    return f"{name}_{number}.pdf"

# ── mm↔px 유틸
def mm_to_px(mm_pair: tuple[int, int], ppi: int) -> tuple[int, int]:
    w_mm, h_mm = mm_pair
    to_px = lambda mm: int(round(mm * ppi / 25.4))
    return to_px(w_mm), to_px(h_mm)

def set_ppi_meta(img: QImage, ppi: int = PRINT_PPI) -> None:
    dpm = int(round(ppi / 0.0254))
    img.setDotsPerMeterX(dpm); img.setDotsPerMeterY(dpm)

def qimage_save(img: QImage, path: str, fmt: str = "PNG", quality: int = -1) -> bool:
    _ensure_dir(os.path.dirname(path))
    w = QImageWriter(path, bytes(fmt, "ascii"))
    if quality >= 0: w.setQuality(quality)
    return w.write(img)

def cover_crop_rect(iw: int, ih: int, tw: int, th: int):
    src_ar = iw / float(ih); dst_ar = tw / float(th)
    if src_ar > dst_ar:
        want_w = int(dst_ar * ih); x = (iw - want_w) // 2
        return x, 0, want_w, ih
    else:
        want_h = int(iw / dst_ar); y = (ih - want_h) // 2
        return 0, y, iw, want_h

# ── retention_days 헬퍼
def get_retention_days(default: int = 7) -> int:
    try:
        app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        cfg_path = os.path.join(app_dir, "config", "email.json")
        if os.path.exists(cfg_path):
            import json
            with open(cfg_path, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            v = cfg.get("retention_days", default)
            return int(v)
    except Exception:
        pass
    return int(default)

# ─────────────────────────────────────────────────────────────
# PDF 타일 생성 (개선: 실사이즈 유지 + 컷마크/구분)
# ─────────────────────────────────────────────────────────────
def build_tiled_pdf(
    image: QImage,
    session: dict,
    *,
    size_key: str,
    photo_mm: tuple,                    # (30,40) or (35,45)
    # ⬇️ 기본 종이 크기는 4×6 inch의 '세로'(101.6 × 152.4 mm)로 정의하고,
    #    QPageLayout에서 Landscape로 회전시켜 최종 가로 4×6이 되도록 강제합니다.
    paper_mm: tuple = (101.6, 152.4),
    orientation: QPageLayout.Orientation = QPageLayout.Landscape,
    dpi: int = 300,
    margin_mm: float = 0.0,             # 페이지 마진(프린터 축소 유발 방지) → 0 유지
    gap_mm: float = 3.0,                # 사진 사이 구분 공간(콘텐츠 여백)
    outer_gutter_mm: float = 2.0,       # 페이지 테두리와 첫 타일 사이 외곽 여백(콘텐츠 여백)
    draw_crop_marks: bool = False,      # 컷마크 사용 안 함(요청사항)
    draw_separators: bool = False,      # 사진 테두리 얇은 선(옅게)
    bleed_mm: float = 0.0,              # 사진마다 블리드(+양쪽)
    # ⬇️ 2×3(2행 × 3열, 가로 우선) 고정
    force_cols_rows: tuple = (3, 2),
    strict_cols_rows: bool = True,     # True면 2×3 고정(폴백으로 행/열 변경 금지)
) -> str:
    
    """
    이미지 타일을 **가로 4×6(최종 152.4×101.6mm)** PDF로 저장합니다.
    - session["ratio"]가 '3040'이면 30×40mm, '3545'이면 35×45mm로 자동 선택
    - 소스 이미지는 C:\PhotoBox\edited_photo.jpg(300ppi) 고정 사용
    - 페이지 마진 0, `FullPageMode`, 그리드 **2×3(2행×3열, 가로)**
    - 컷마크는 사용하지 않음
    """
    # 출력 경로
    pdf_dir = pdf_date_dir(True)
    pdf_name = make_pdf_filename(session, size_key)
    save_path = os.path.join(pdf_dir, pdf_name)

    # 1) 사진 규격: session["ratio"] 기반 자동 선택
    ratio = str(session.get("ratio", "")).strip()
    if ratio == "3040":
        photo_mm = (30, 40)
    elif ratio == "3545":
        photo_mm = (35, 45)
    # else: 호출 인자 photo_mm 그대로 사용(폴백)

    # 2) 소스 이미지: 편집본 고정 경로 우선 사용
    src_img = QImage(EDITED_PHOTO_PATH)
    if src_img.isNull() and isinstance(image, QImage):
        # 편집본이 없으면 전달받은 이미지 사용(폴백)
        src_img = image


    # 페이지 레이아웃(mm 단위) — Orientation 적용 + FullPage
    #   - paper_mm는 (세로 기준) 4×6inch = (101.6, 152.4)
    #   - orientation=Landscape로 실제 출력은 152.4×101.6이 됨
    base_w_mm, base_h_mm = paper_mm
    page_size = QPageSize(QSizeF(base_w_mm, base_h_mm), QPageSize.Millimeter)
    page_layout = QPageLayout(page_size, orientation, QMarginsF(margin_mm, margin_mm, margin_mm, margin_mm))
    page_layout.setMode(QPageLayout.FullPageMode)

    # PDF 라이터
    writer = QPdfWriter(save_path)
    writer.setResolution(dpi)
    writer.setPageLayout(page_layout)

    # px 스케일 계산 (orientation 반영)
    #   Landscape면 가로/세로를 스왑하여 실제 페이지 픽셀 계산
    if orientation == QPageLayout.Landscape:
        page_w_mm, page_h_mm = base_h_mm, base_w_mm  # 152.4, 101.6
    else:
        page_w_mm, page_h_mm = base_w_mm, base_h_mm

    pw_px, ph_px = mm_to_px((page_w_mm, page_h_mm), dpi)
    outer_px   = int(round(outer_gutter_mm * dpi / 25.4))
    gap_px     = int(round(gap_mm * dpi / 25.4))
    bleed_px   = int(round(bleed_mm * dpi / 25.4))
    tw_px, th_px = mm_to_px((photo_mm[0], photo_mm[1]), dpi)

    # 실제 배치 가능한 콘텐츠 영역
    usable_w = pw_px - outer_px * 2
    usable_h = ph_px - outer_px * 2

    # 배치 가능성 검사
    def fits(cols: int, rows: int, tile_w: int, tile_h: int) -> bool:
        need_w = cols * tile_w + (cols - 1) * gap_px
        need_h = rows * tile_h + (rows - 1) * gap_px
        return (need_w <= usable_w) and (need_h <= usable_h)

    cols, rows = force_cols_rows  # cols=3, rows=2 → 2행×3열
    use_rot = False
    tile_w, tile_h = tw_px, th_px

    # 2×3 고정 배치 → 필요 시 사진만 회전 후 재검 (행/열은 고정)
    if not fits(cols, rows, tile_w, tile_h):
        use_rot = True
        tile_w, tile_h = th_px, tw_px
        # strict_cols_rows=True 이면 행/열을 바꾸지 않음
        if strict_cols_rows and not fits(cols, rows, tile_w, tile_h):
            # 그래도 안 들어가면 그대로 진행(겹침/클립 위험 알림은 상위 UI에서 처리)
            pass
        elif not strict_cols_rows and not fits(cols, rows, tile_w, tile_h):
            # 폴백: 최대 적재 수 계산(회전/비회전 비교)
            use_rot = False
            tile_w, tile_h = tw_px, th_px

            def max_fit(w: int, h: int):
                c = max(0, (usable_w + gap_px) // (w + gap_px))
                r = max(0, (usable_h + gap_px) // (h + gap_px))
                return int(c), int(r), int(c * r)

            c1, r1, n1 = max_fit(tw_px, th_px)
            c2, r2, n2 = max_fit(th_px, tw_px)
            if n2 > n1:
                use_rot, (cols, rows), (tile_w, tile_h) = True, (c2, r2), (th_px, tw_px)
            else:
                use_rot, (cols, rows), (tile_w, tile_h) = False, (c1, r1), (tw_px, th_px)

    # 타일 배치 시작 좌표(콘텐츠 기준 중앙 정렬)
    used_w = cols * tile_w + (cols - 1) * gap_px
    used_h = rows * tile_h + (rows - 1) * gap_px
    sx = outer_px + (usable_w - used_w) // 2
    sy = outer_px + (usable_h - used_h) // 2

    painter = QPainter(writer)
    try:
        # 소스 이미지(필요 시 90도 회전)
        src = src_img.transformed(QTransform().rotate(90)) if use_rot else src_img

        for r in range(rows):
            for c in range(cols):
                x = sx + c * (tile_w + gap_px)
                y = sy + r * (tile_h + gap_px)

                # 사진을 타일 크기에 '꽉' 채우되 비율 커버(중앙 크롭)
                crop_x, crop_y, crop_w, crop_h = cover_crop_rect(src.width(), src.height(), tile_w, tile_h)
                tile = src.copy(crop_x, crop_y, crop_w, crop_h).scaled(
                    tile_w + bleed_px * 2, tile_h + bleed_px * 2,
                    Qt.IgnoreAspectRatio, Qt.SmoothTransformation
                )
                # 블리드가 있다면 바깥으로 밀어 그리기
                painter.drawImage(x - bleed_px, y - bleed_px, tile)

                # (선택) 구분선 — 기본 False(요청 시만 True)
                if draw_separators:
                    pen = QPen(); pen.setWidth(1); painter.setPen(pen)
                    painter.drawRect(x, y, tile_w, tile_h)
                # 컷마크 비활성화 (아무것도 그리지 않음)
    finally:
        painter.end()

    return save_path

# ─────────────────────────────────────────────────────────────
# Job 경로/번들/메일 기록 (기존 그대로)
# ─────────────────────────────────────────────────────────────
class JobPaths:
    def __init__(self, root: str):
        self.root = root
        self.raw = os.path.join(root, "raw_selected.png")
        self.preview = os.path.join(root, "preview_small.jpg")
        self.email = os.path.join(root, "enhanced_email.jpg")
        self.print = None
        self.meta = os.path.join(root, "metadata.json")
        self.email_req = os.path.join(root, "email_request.json")
        self.email_res = os.path.join(root, "email_result.json")

def open_job(session: dict) -> "JobPaths":
    day_dir = _ensure_dir(os.path.join(PHOTOBOX_ROOT, "_work", _today_yymmdd()))
    stem = f"{session.get('name', 'noname')}_{session.get('number', '0000')}"
    job_dir = _unique_dir(day_dir, stem)
    _ensure_dir(job_dir)
    return JobPaths(job_dir)

def make_jpg_filename(session: dict) -> str:
    name = str(session.get("name", "noname"))
    number = str(session.get("number", "0000"))
    return f"{name}_{number}.jpg"

def save_bundle(
    job: JobPaths,
    base_img: QImage,
    enhanced_img: QImage,
    size_key: str,
    preset_token: str,
    user_params: Dict,
    session_info: Optional[Dict] = None,
    email_long_px: int = EMAIL_LONG_PX,
    thumb_long_px: int = THUMB_LONG_PX,
) -> Dict[str, str]:
    now = dt.datetime.now()
    hhmmss = now.strftime("%H%M%S")

    qimage_save(base_img, job.raw, "PNG")

    if base_img.width() >= base_img.height():
        nh = int(round(base_img.height() * (thumb_long_px / base_img.width())))
        thumb = base_img.scaled(thumb_long_px, nh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    else:
        nw = int(round(base_img.width() * (thumb_long_px / base_img.height())))
        thumb = base_img.scaled(nw, thumb_long_px, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    qimage_save(thumb, job.preview, "JPG", 88)

    eimg = enhanced_img
    ew, eh = eimg.width(), eimg.height()
    if max(ew, eh) > email_long_px:
        if ew >= eh:
            nh = int(round(eh * (email_long_px / ew)))
            eimg = eimg.scaled(email_long_px, nh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            nw = int(round(ew * (email_long_px / eh)))
            eimg = eimg.scaled(nw, email_long_px, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    qimage_save(eimg, job.email, "JPG", 92)

    tw, th = mm_to_px(SIZES_MM[size_key], PRINT_PPI)
    x, y, cw, ch = cover_crop_rect(enhanced_img.width(), enhanced_img.height(), tw, th)
    cropped = enhanced_img.copy(x, y, cw, ch)
    out_print = cropped.scaled(tw, th, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    set_ppi_meta(out_print, PRINT_PPI)
    print_path = os.path.join(job.root, f"print_{size_key}_{PRINT_PPI}ppi.jpg")
    qimage_save(out_print, print_path, "JPG", 95)
    job.print = print_path

    try:
        jpg_dir = jpg_date_dir(True)
        jpg_name = make_jpg_filename(session_info or {})
        jpg_out = os.path.join(jpg_dir, jpg_name)
        shutil.copyfile(print_path, jpg_out)
    except Exception:
        jpg_out = None

    meta = {
        "created_at": now.isoformat(timespec="seconds"),
        "size_key": size_key,
        "ratio": (session_info or {}).get("ratio"),
        "preset_token": preset_token,
        "user_params": user_params,
        "name": (session_info or {}).get("name"),
        "number": (session_info or {}).get("number"),
        "email1": (session_info or {}).get("email1"),
        "email2": (session_info or {}).get("email2"),
        "files": {
            "raw": os.path.relpath(job.raw, job.root),
            "preview": os.path.relpath(job.preview, job.root),
            "email": os.path.relpath(job.email, job.root),
            "print": os.path.relpath(print_path, job.root),
            "final_jpg": (os.path.relpath(jpg_out, jpg_dir) if jpg_out else None),
        },
        "dpi": PRINT_PPI,
        "app_version": "photostudio-1.0",
    }
    with open(job.meta, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return {
        "dir": job.root,
        "raw": job.raw,
        "preview": job.preview,
        "email": job.email,
        "print": print_path,
        "meta": job.meta,
        "final_jpg": (os.path.join(jpg_dir, make_jpg_filename(session_info or {})) if jpg_out else None),
    }

# ── 이메일 기록
def save_email_request(job: JobPaths, to: str, subject: str, body: str, attachments: List[str]) -> str:
    rec = {
        "to": to,
        "subject": subject,
        "body": body,
        "attachments": [os.path.relpath(p, job.root) for p in attachments],
        "requested_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    with open(job.email_req, "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=2)
    return job.email_req

def save_email_result(job: JobPaths, ok: bool, provider_id: Optional[str] = None, error: Optional[str] = None) -> str:
    res = {
        "ok": ok,
        "provider_id": provider_id,
        "error": error,
        "finished_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    with open(job.email_res, "w", encoding="utf-8") as f:
        json.dump(res, f, ensure_ascii=False, indent=2)
    return job.email_res

# ── 정리/청소 더미
def start_pdf_cleanup_timer(*_, **__): return None
def start_jpg_cleanup_timer(*_, **__): return None
def start_cleanup_timer(*_, **__): return None
def cleanup_pdf(*_, **__): return 0
def cleanup_jpg(*_, **__): return 0
def cleanup_jobs(*_, **__): return 0