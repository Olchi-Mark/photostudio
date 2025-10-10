# app/utils/storage.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, re, json, shutil, datetime as dt
from typing import Dict, Tuple, Optional, List

from PySide6.QtCore import Qt, QTimer, QObject
from PySide6.QtGui import QImage, QImageWriter, QPainter, QPdfWriter, QPageSize, QPageLayout
from PySide6.QtCore import QSizeF, QMarginsF

# ─────────────────────────────────────────────────────────────
# 기본 경로/상수
# ─────────────────────────────────────────────────────────────
APP_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(APP_ROOT, "data")  # (구) app/data

PHOTOBOX_ROOT = r"C:\PhotoBox"
PDF_ROOT = os.path.join(PHOTOBOX_ROOT, "PDF")
JPG_ROOT = os.path.join(PHOTOBOX_ROOT, "JPG")

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
    return re.sub(r"[^\w가-힣\.\-]+", "_", (name or "").strip())

def today_dir(root: str) -> str:
    ymd = dt.datetime.now().strftime("%y%m%d")
    path = os.path.join(root, ymd)
    os.makedirs(path, exist_ok=True)
    return path

def unique_path(base_path: str) -> str:
    """같은 파일명이 있으면 _001, _002 식으로 붙여서 중복 회피"""
    if not os.path.exists(base_path):
        return base_path
    root, ext = os.path.splitext(base_path)
    i = 1
    while True:
        cand = f"{root}_{i:03d}{ext}"
        if not os.path.exists(cand):
            return cand
        i += 1


# ── origin 저장 (Pick → NEXT 순간)
def save_origin_photo(img: QImage) -> str:
    _ensure_dir(PHOTOBOX_ROOT)
    path = os.path.join(PHOTOBOX_ROOT, "origin_photo.jpg")
    QImage(img).save(path, "JPG", quality=95)
    return path

# ── PDF 일자 폴더: C:\PhotoBox\PDF\YYMMDD
def save_selected_origin(session: dict) -> str:
    """선택된 원본을 C:\PhotoBox\origin_photo.jpg로 복사해 저장한다.
    우선순위: session['selected_raw_name'] → session['selected_index'] → session['selected_capture'](번호 유추).
    원본 소스 디렉터리: session['raw_dir']가 있으면 사용, 없으면 C:\PhotoBox.
    반환: 목적지 경로 문자열.
    """
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
        try:
            raw_name = os.path.basename(raws[idx])
        except Exception:
            raw_name = "1.jpg"

    raw_dir = session.get("raw_dir") or PHOTOBOX_ROOT
    src = os.path.join(raw_dir, raw_name)
    dst = os.path.join(PHOTOBOX_ROOT, "origin_photo.jpg")
    _ensure_dir(PHOTOBOX_ROOT)
    shutil.copyfile(src, dst)
    return dst

# ── 날짜 폴더 도우미
def pdf_date_dir(create: bool = True) -> str:
    """C:\PhotoBox\PDF\YYMMDD 반환. create=True면 폴더 생성."""
    path = today_dir(PDF_ROOT) if create else today_dir(PDF_ROOT)
    return path

def jpg_date_dir(create: bool = True) -> str:
    """C:\PhotoBox\JPG 반환. 날짜 하위폴더 생성 안 함."""
    path = JPG_ROOT
    if create: os.makedirs(path, exist_ok=True)
    return path


# ── PDF 파일명: {이름_뒷4}_{size_key}_{YYMMDD-HHMM}.pdf
def make_pdf_filename(session: dict, size_key: str, when: Optional[dt.datetime] = None) -> str:
    # 정책: {name_number}.pdf 형식, size_key/타임스탬프 미포함
    name = str(session.get("name", "noname"))
    number = str(session.get("number", "0000"))
    return f"{name}_{number}.pdf"

# ── 4×6 / 300dpi / margin=3 / gap=4 / 2×3(6컷) 우선 PDF 타일 생성
def build_tiled_pdf(
    image: QImage,
    session: dict,
    *,
    size_key: str,
    photo_mm: tuple,                   # (30,40) or (35,45)
    paper_mm: tuple = (102.0, 152.0),  # 4×6 inch = 102×152 mm
    dpi: int = 300,
    margin_mm: float = 3.0,
    gap_mm: float = 4.0,
    force_cols_rows: tuple = (2, 3),   # 6컷 고정 우선, 불가 시 최대 적재 폴백
) -> str:
    """이미지 타일을 4×6 PDF로 저장한다.
    - 종이 크기, 여백, 간격은 mm 단위 입력. 내부에서 dpi로 px 변환.
    - force_cols_rows가 들어맞지 않으면 최대 적재 수로 폴백하며 회전 여부도 탐색.
    """
    name = _sanitize_name(str(session.get("name", "noname")))
    number = str(session.get("number", "0000"))
    size_w_mm, size_h_mm = photo_mm

    # 1) 캔버스 계산
    ppi = dpi
    def mm_to_px_pair(w_mm: float, h_mm: float):
        to_px = lambda mm: int(round(mm * ppi / 25.4))
        return to_px(w_mm), to_px(h_mm)

    paper_w_px, paper_h_px = mm_to_px_pair(*paper_mm)
    margin_px = int(round(margin_mm * ppi / 25.4))
    gap_px    = int(round(gap_mm * ppi / 25.4))
    tile_w_px, tile_h_px = mm_to_px_pair(size_w_mm, size_h_mm)

    # 2) 배치 그리드 결정 (force 우선, 안되면 폴백)
    def can_place(cols, rows):
        total_w = cols * tile_w_px + (cols - 1) * gap_px + 2 * margin_px
        total_h = rows * tile_h_px + (rows - 1) * gap_px + 2 * margin_px
        return total_w <= paper_w_px and total_h <= paper_h_px

    cols, rows = force_cols_rows
    if not can_place(cols, rows):
        # 6컷을 못 넣으면 가능한 최대 적재를 탐색
        best = (0, 0, 0)  # (cnt, cols, rows)
        for c in range(1, 10):
            for r in range(1, 10):
                if can_place(c, r):
                    cnt = c * r
                    if cnt > best[0]:
                        best = (cnt, c, r)
        if best[0] == 0:
            # 회전도 시도
            paper_w_px, paper_h_px = paper_h_px, paper_w_px
            if not can_place(cols, rows):
                best = (0, 0, 0)
                for c in range(1, 10):
                    for r in range(1, 10):
                        if can_place(c, r):
                            cnt = c * r
                            if cnt > best[0]:
                                best = (cnt, c, r)
            if best[0] == 0:
                raise RuntimeError("용지에 배치 불가")
        cols, rows = best[1], best[2]

    # 3) PDF Writer
    out_dir = pdf_date_dir(True)
    out_name = make_pdf_filename(session, size_key)
    out_path = unique_path(os.path.join(out_dir, out_name))
    writer = QPdfWriter(out_path)
    writer.setResolution(ppi)
    writer.setPageSize(QPageSize(QSizeF(paper_mm[0], paper_mm[1]), QPageSize.Millimeter))
    layout = QPageLayout(QPageSize(QSizeF(paper_mm[0], paper_mm[1]), QPageSize.Millimeter),
                         QPageLayout.Portrait, QMarginsF(0, 0, 0, 0))
    writer.setPageLayout(layout)

    painter = QPainter(writer)
    try:
        # 4) 타일 그리기
        canvas_w = writer.width()
        canvas_h = writer.height()
        # 중앙 정렬 시작점
        total_w = cols * tile_w_px + (cols - 1) * gap_px + 2 * margin_px
        total_h = rows * tile_h_px + (rows - 1) * gap_px + 2 * margin_px
        start_x = (canvas_w - total_w) // 2 + margin_px
        start_y = (canvas_h - total_h) // 2 + margin_px

        # 원본 맞추기(cover)
        def cover_crop_rect(iw: int, ih: int, tw: int, th: int):
            src_ar = iw / float(ih); dst_ar = tw / float(th)
            if src_ar > dst_ar:
                want_w = int(dst_ar * ih); x = (iw - want_w) // 2
                return x, 0, want_w, ih
            else:
                want_h = int(iw / dst_ar); y = (ih - want_h) // 2
                return 0, y, iw, want_h

        iw, ih = image.width(), image.height()
        cx, cy, cw, ch = cover_crop_rect(iw, ih, tile_w_px, tile_h_px)
        cropped = image.copy(cx, cy, cw, ch)
        tile = cropped.scaled(tile_w_px, tile_h_px, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)

        # 격자 배치
        for r in range(rows):
            for c in range(cols):
                x = start_x + c * (tile_w_px + gap_px)
                y = start_y + r * (tile_h_px + gap_px)
                painter.drawImage(x, y, tile)

    finally:
        painter.end()

    return out_path


# ─────────────────────────────────────────────────────────────
# JPG/EMAIL 산출물(요약) — 일부 외부 모듈에서 호출
# ─────────────────────────────────────────────────────────────
class JobPaths:
    def __init__(self, root: str):
        self.root = _ensure_dir(root)
        self.email_req = os.path.join(root, "email_request.json")
        self.email_res = os.path.join(root, "email_result.json")
        self.email = os.path.join(root, "email.jpg")
        self.thumb = os.path.join(root, "thumb.jpg")
        self.print = os.path.join(root, "print.jpg")
        self.meta = os.path.join(root, "meta.json")

def mm_to_px(size_mm: Tuple[int, int], ppi: int = PRINT_PPI) -> Tuple[int, int]:
    w_mm, h_mm = size_mm
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

# ── email.json에서 retention_days 읽어오는 안전 헬퍼(없으면 7)
def get_retention_days(default: int = 7) -> int:
    """
    app/config/email.json의 retention_days를 읽어 정수로 반환.
    값이 없거나 비정상이면 default(7)를 사용.
    """
    try:
        app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        cfg_path = os.path.join(app_dir, "config", "email.json")
        with open(cfg_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        rd = int(data.get("retention_days", default))
        return rd if 1 <= rd <= 90 else default
    except Exception:
        return default

# ── 출력/이메일/썸네일 일괄 산출
def export_all_outputs(image: QImage, session_info: Optional[dict], size_key: str) -> JobPaths:
    """
    - email.jpg: 긴변 1600px
    - thumb.jpg: 긴변 480px
    - print.jpg: 규격 픽셀(@300ppi)
    - meta.json: 메타데이터
    """
    job_root = today_dir(os.path.join(PHOTOBOX_ROOT, "jobs"))
    job = JobPaths(job_root)

    # 1) 향상 이미지(별도 단계에서 만들어져 들어온다고 가정)
    enhanced_img = image

    # 2) 썸네일/이메일
    eimg = QImage(enhanced_img)
    email_long_px = EMAIL_LONG_PX
    ew, eh = eimg.width(), eimg.height()
    if max(ew, eh) > email_long_px:
        if ew >= eh:
            nh = int(round(eh * (email_long_px / ew)))
            eimg = eimg.scaled(email_long_px, nh, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        else:
            nw = int(round(ew * (email_long_px / eh)))
            eimg = eimg.scaled(nw, email_long_px, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    qimage_save(eimg, job.email, "JPG", 92)

    # 4) 출력용 (규격 픽셀 @ 300ppi)
    tw, th = mm_to_px(SIZES_MM[size_key], PRINT_PPI)
    x, y, cw, ch = cover_crop_rect(enhanced_img.width(), enhanced_img.height(), tw, th)
    cropped = enhanced_img.copy(x, y, cw, ch)
    out_print = cropped.scaled(tw, th, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    set_ppi_meta(out_print, PRINT_PPI)
    print_path = os.path.join(job.root, f"print_{size_key}_{PRINT_PPI}ppi.jpg")
    qimage_save(out_print, print_path, "JPG", 95)
    job.print = print_path

    # 4-1) 최종 출력본을 JPG 저장 규칙에 따라 복사: C:\PhotoBox\JPG\YYMMDD\{name_number}.jpg
    try:
        jpg_dir = jpg_date_dir(True)
        jpg_name = make_jpg_filename(session_info or {})
        jpg_out = os.path.join(jpg_dir, jpg_name)
        shutil.copyfile(print_path, jpg_out)
    except Exception:
        jpg_out = None

    # 5) 메타데이터 (이메일/이름 등 포함)
    meta = {
        "size_key": size_key,
        "ppi": PRINT_PPI,
        "jpg_copy": jpg_out,
        "session": {
            "name": (session_info or {}).get("name"),
            "number": (session_info or {}).get("number"),
            "email": (session_info or {}).get("email1"),
        },
    }
    with open(job.meta, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)

    return job

def make_jpg_filename(session: dict) -> str:
    name = _sanitize_name(str(session.get("name", "noname")))
    number = str(session.get("number", "0000"))
    return f"{name}_{number}.jpg"

# 이메일 요청/결과 JSON 저장 (외부 모듈이 사용)
def save_email_request(job: JobPaths, session: dict, pdf_path: Optional[str]) -> str:
    req = {
        "name": session.get("name"),
        "number": session.get("number"),
        "email": session.get("email1") or session.get("email"),
        "pdf_path": pdf_path,
        "requested_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    with open(job.email_req, "w", encoding="utf-8") as f:
        json.dump(req, f, ensure_ascii=False, indent=2)
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


# 정리/청소 정책 제거 — 운영 정책에 따라 외부에서 관리함.
def start_cleanup_timer(*_, **__):
    return None

def cleanup_pdf(*_, **__):
    return 0

def cleanup_jpg(*_, **__):
    return 0

def cleanup_jobs(*_, **__):
    return 0


# ─────────────────────────────────────────────────────────────
# ratio(3040/3545) 기반 ID 사진 타일 PDF 생성
# ─────────────────────────────────────────────────────────────
def create_id_pdf_from_ratio(session: dict) -> str:
    """
    session["ratio"] 값을 읽어 3040→(30,40)mm, 3545→(35,45)mm 로 판단하고
    C:\\PhotoBox\\edited_photo.jpg 를 소스로 4×6인치(101.6×152.0mm) 용지에
    3×2(가로) 타일 PDF를 생성한다.

    반환값: 생성된 PDF의 절대경로 (build_tiled_pdf 반환과 동일)
    """
    ratio = str(session.get("ratio") or "").strip()
    ratio_map = {"3040": ("ID_30x40", (30, 40)), "3545": ("ID_35x45", (35, 45))}
    if ratio not in ratio_map:
        print(f"[PDF] session['ratio']='{ratio}' → 잘못되었거나 없음. 기본 3040 적용.")
        ratio = "3040"
    size_key, photo_mm = ratio_map[ratio]

    # 소스 이미지 경로
    src_path = r"C:\PhotoBox\edited_photo.jpg"
    img = QImage(src_path)
    if img.isNull():
        raise RuntimeError(f"[PDF] 소스 이미지 로드 실패: {src_path}")

    # name/number 기본값 보정 (파일명 규칙용)
    session.setdefault("name", "noname")
    session.setdefault("number", "0000")

    # 3×2(가로) 우선 PDF 생성
    pdf_path = build_tiled_pdf(
        image=img,
        session=session,
        size_key=size_key,
        photo_mm=photo_mm,
        paper_mm=(102.0, 152.0),   # 4×6inch
        dpi=PRINT_PPI,             # 300dpi
        margin_mm=3.0,
        gap_mm=4.0,
        force_cols_rows=(3, 2),    # 3x2 고정 우선
    )
    print(f"[PDF] OK: {pdf_path}  ({photo_mm[0]}×{photo_mm[1]}mm, key={size_key})")
    return pdf_path
