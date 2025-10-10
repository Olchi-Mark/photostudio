# app/pages/enhance_select.py
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
ENHANCE 페이지 (이메일 후 추가 옵션 처리)
- 고객 이메일 전송 이후, 사용자가 추가로 체크한 옵션에 따라
  1) 인화(출력팀) 안내 메일 전송 + PDF 생성/인쇄
  2) 보정팀 안내 메일 전송 + 원본 JPG 복사
- settings.json의 email 섹션에 들어있는 print_manager / retouch_manager 설정을 최대한 존중하여
  subject/body/to 를 사용하고, 없을 경우 안전한 기본값으로 폴백
"""

import os, re, shutil, datetime as dt, logging
from typing import Optional, List, Tuple, Dict
from logging.handlers import RotatingFileHandler

from PySide6.QtCore import Qt, QMarginsF, QSizeF, QRectF
from PySide6.QtGui import QImage, QPageSize, QPageLayout, QPainter
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QCheckBox, QPushButton,
    QSizePolicy, QProgressDialog, QApplication
)

from app.ui.base_page import BasePage
from app.pages.setting import SETTINGS
from app.utils import storage, emailer
from app.components.footer_bar import TriButton

# ────────────────────────────────────────────────────────────────────────────────
# 상수/경로
# ────────────────────────────────────────────────────────────────────────────────
TEXT_DARK = "#333333"
ROOT_DIR = r"C:\\PhotoBox"
EDITED_JPG = os.path.join(ROOT_DIR, "edited_photo.jpg")   # 인화 소스 고정(edited)
ORIGIN_JPG = os.path.join(ROOT_DIR, "origin_photo.jpg")   # 보정 소스 고정(origin)

# ────────────────────────────────────────────────────────────────────────────────
# 로깅
# ────────────────────────────────────────────────────────────────────────────────
LOG_DIR = os.path.join(ROOT_DIR, "logs")
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "enhance_select.log")
logger = logging.getLogger("enhance_select")
if not logger.handlers:
    logger.setLevel(logging.INFO)
    _h = RotatingFileHandler(LOG_FILE, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    _h.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logger.addHandler(_h)

def _log(msg: str):
    try:
        logger.info(str(msg))
    except Exception:
        pass

# ────────────────────────────────────────────────────────────────────────────────
# 유틸/토큰
# ────────────────────────────────────────────────────────────────────────────────
def _snap3(v: int) -> int:
    vi = int(v); return (vi // 3) * 3

def _load_scale() -> float:
    app = QApplication.instance()
    TOK = (app.property("TYPO_TOKENS") or {}) if app else {}
    try:
        return float(TOK.get("scale", 1.0) or 1.0)
    except Exception:
        return 1.0

_P_FHD = {
    "FS_TITLE": 36, "FS_TAB": 21, "FS_CHECK": 21, "FS_NOTE": 18, "FS_FINISH": 21,
    "TITLE_TOP_GAP": 390, "GAP_V": 24, "HEAD_GAP": 12, "ROW_GAP": 12,
    "PAGE_M_L": 36, "PAGE_M_T": 24, "PAGE_M_R": 36, "PAGE_M_B": 24,
    "CARD_PAD": 18, "CARD_RADIUS": 9, "CARD_BORDER": 3,
    "TAB_PAD_H": 12, "TAB_PAD_V": 6, "TAB_RADIUS": 9,
    "IND_SIZE": 18, "IND_RADIUS": 3, "IND_BORDER": 3,
    "BTN_RADIUS": 15, "BTN_PAD_H": 18,
    "BADGE_PAD_H": 6, "BADGE_PAD_V": 3, "BADGE_RADIUS": 9,
}

def _build_page_tokens() -> dict:
    s = _load_scale(); P = {}
    for k, v in _P_FHD.items():
        try: P[k] = _snap3(int(v * s))
        except Exception: P[k] = v
    return P

def _theme_primary() -> str:
    app = QApplication.instance()
    cols = (app.property("THEME_COLORS") or {}) if app else {}
    return cols.get("primary", "#FFA9A9")

def _rgba_from_hex(hex_str: str, a: float) -> str:
    try:
        s = hex_str.lstrip('#')
        if len(s) == 3:
            r, g, b = (int(s[i]*2, 16) for i in range(3))
        elif len(s) >= 6:
            r, g, b = int(s[0:2],16), int(s[2:4],16), int(s[4:6],16)
        else:
            r, g, b = 255, 169, 169
        return f"rgba({r},{g},{b},{float(a)})"
    except Exception:
        return "rgba(255,169,169,0.10)"

# ────────────────────────────────────────────────────────────────────────────────
# 파일/이름/토큰 유틸
# ────────────────────────────────────────────────────────────────────────────────
def _today() -> str:
    return dt.datetime.now().strftime("%y%m%d")

def _now_stamp() -> str:
    return dt.datetime.now().strftime("%y%m%d-%H%M")

def _sanitize_filename(s: str) -> str:
    s = re.sub(r"[^\w가-힣]+", "_", s, flags=re.UNICODE)
    return s.strip("_") or "noname"

def _target_basename(session: dict, ext: str) -> str:
    name  = (session.get("name") or "noname").strip()
    phone = re.sub(r"[^0-9]+", "", (session.get("phone") or "0000"))
    return f"{_today()}_{_sanitize_filename(name)}_{phone}.{ext.lower().lstrip('.')}"

def _target_origin_basename(session: dict) -> str:
    name  = (session.get("name") or "noname").strip()
    phone = re.sub(r"[^0-9]+", "", (session.get("phone") or "0000"))
    return f"origin_{_today()}_{_sanitize_filename(name)}_{phone}.jpg"

def _ensure_dir(p: str) -> str:
    try: os.makedirs(p, exist_ok=True)
    except Exception: pass
    return p

# ────────────────────────────────────────────────────────────────────────────────
# 설정/수신자 읽기
# ────────────────────────────────────────────────────────────────────────────────
def _load_settings() -> dict:
    try:
        return getattr(SETTINGS, "data", {}) or {}
    except Exception:
        return {}

def _list_from_maybe_str(x) -> List[str]:
    if not x: return []
    if isinstance(x, str):
        return [t.strip() for t in re.split(r"[,\n;]+", x) if t.strip()]
    if isinstance(x, (list, tuple)):
        return [str(t).strip() for t in x if str(t).strip()]
    return []

def _recips_printer(cfg: dict) -> List[str]:
    to_new = (((cfg.get("email") or {}).get("print_manager") or {}).get("to"))
    rec = _list_from_maybe_str(to_new)
    return rec or _list_from_maybe_str((((cfg.get("email") or {}).get("staff") or {}).get("printer")))

def _recips_retouch(cfg: dict) -> List[str]:
    to_new = (((cfg.get("email") or {}).get("retouch_manager") or {}).get("to"))
    rec = _list_from_maybe_str(to_new)
    return rec or _list_from_maybe_str((((cfg.get("email") or {}).get("staff") or {}).get("retoucher")))

# ────────────────────────────────────────────────────────────────────────────────
# 인쇄 관련
# ────────────────────────────────────────────────────────────────────────────────
def _sumatra_candidates() -> List[str]:
    return [
        r"C:\\Program Files\\SumatraPDF\\SumatraPDF.exe",
        r"C:\\Program Files (x86)\\SumatraPDF\\SumatraPDF.exe",
        r"C:\\Portable\\SumatraPDF\\SumatraPDF.exe",
        r"C:\\Tools\\SumatraPDF\\SumatraPDF.exe",
    ]

def _print_with_sumatra(pdf_path: str, printer_name: str) -> bool:
    import subprocess, shutil
    _log(f"Print:Sumatra start printer='{printer_name}' pdf='{pdf_path}'")
    exe = next((p for p in _sumatra_candidates() if os.path.isfile(p)), None)
    if not exe:
        exe = shutil.which("SumatraPDF.exe") or shutil.which("sumatrapdf.exe")
    if not exe:
        _log("Print:Sumatra exe not found")
        return False
    args = [
        exe, "-silent",
        "-print-to", printer_name,
        "-print-settings", "paper=4x6in,noscale",
        "-exit-on-print",
        pdf_path,
    ]
    try:
        _log(f"Print:Sumatra cmd={' '.join(args)}")
        ret = subprocess.run(args, capture_output=True, text=True)
        _log(f"Print:Sumatra rc={ret.returncode} stdout={ret.stdout!r} stderr={ret.stderr!r}")
        return ret.returncode == 0
    except Exception as e:
        _log(f"Print:Sumatra exception err={e}")
        return False

def _print_with_qt(pdf_path: str, printer_name: str) -> bool:
    try:
        from PySide6.QtPdf import QPdfDocument
    except Exception as e:
        _log(f"Print:Qt no QPdfDocument err={e}")
        return False
    try:
        _log(f"Print:Qt start printer='{printer_name}' pdf='{pdf_path}'")
        printer = QPrinter(QPrinter.PrinterResolution)
        printer.setPrinterName(printer_name)
        printer.setResolution(300)

        sz = QPageSize(QSizeF(101.6, 152.4), QPageSize.Millimeter)
        layout = QPageLayout(sz, QPageLayout.Portrait, QMarginsF(0, 0, 0, 0))
        printer.setPageLayout(layout)
        printer.setFullPage(True)

        doc = QPdfDocument()
        if doc.load(pdf_path) != QPdfDocument.NoError:
            _log("Print:Qt doc load error")
            return False

        painter = QPainter()
        if not painter.begin(printer):
            _log("Print:Qt painter.begin failed")
            return False
        try:
            page_count = doc.pageCount()
            _log(f"Print:Qt page_count={page_count}")
            for i in range(page_count):
                if i > 0:
                    printer.newPage()
                img = doc.render(i, QSizeF(1800, 1200))  # 300dpi 대략 4x6
                painter.drawImage(QRectF(0, 0, printer.pageRect().width(), printer.pageRect().height()), img)
        finally:
            painter.end()
        _log("Print:Qt success")
        return True
    except Exception as e:
        _log(f"Print:Qt exception err={e}")
        return False

def _try_print_to_named_printer(pdf_path: str, printer_name: str) -> bool:
    _log(f"Print:try printer='{printer_name}' pdf='{pdf_path}'")
    if _print_with_sumatra(pdf_path, printer_name):
        _log("Print:done via Sumatra")
        return True
    if _print_with_qt(pdf_path, printer_name):
        _log("Print:done via Qt")
        return True
    _log("Print:all methods failed")
    return False

# ────────────────────────────────────────────────────────────────────────────────
# 메일 렌더링 (설정 우선 → 폴백)
# ────────────────────────────────────────────────────────────────────────────────
def _render_printer_mail_default(session: dict, pdf_path: str) -> Tuple[str, str]:
    name  = (session.get("name") or "noname").strip()
    phone = re.sub(r"[^0-9]+", "", (session.get("phone") or "0000"))
    subject = f"[인화요청]{_today()}_{name}_{phone}"
    body = "\n".join([
        f"{name} 고객 인화 요청입니다.",
        f"- 규격: {session.get('size_key') or 'ID_30x40'}",
        f"- 첨부: {os.path.basename(pdf_path)}",
        f"- 생성시각: {_now_stamp()}",
    ])
    return subject, body

def _render_retouch_mail_default(session: dict, jpg_path: str) -> Tuple[str, str]:
    name  = (session.get("name") or "noname").strip()
    phone = re.sub(r"[^0-9]+", "", (session.get("phone") or "0000"))
    subject = f"[보정요청]{_today()}_{name}_{phone}"
    body = "\n".join([
        f"{name} 고객 보정 요청입니다.",
        f"- 규격: {session.get('size_key') or 'ID_30x40'}",
        f"- 첨부: {os.path.basename(jpg_path)}",
        f"- 생성시각: {_now_stamp()}",
    ])
    return subject, body

def _render_with_settings(section: Dict, tokens: Dict, fallback: Tuple[str, str]) -> Tuple[str, str]:
    """email.print_manager / email.retouch_manager 섹션의 subject/body를 우선 사용."""
    subj_tpl = (section or {}).get("subject")
    body_tpl = (section or {}).get("body")
    if not isinstance(subj_tpl, str) and not isinstance(body_tpl, str):
        return fallback
    def _fmt(tpl: Optional[str]) -> str:
        if not isinstance(tpl, str):  # 템플릿이 없으면 빈 문자열 반환 → 아래에서 폴백
            return ""
        try:
            return tpl.format(**tokens)
        except Exception:
            # 키 에러 등은 원문 그대로 사용(운영 안전성 우선)
            return tpl
    subj = _fmt(subj_tpl) or fallback[0]
    body = _fmt(body_tpl) or fallback[1]
    return subj, body

# ────────────────────────────────────────────────────────────────────────────────
# 산출물 준비
# ────────────────────────────────────────────────────────────────────────────────
def _finalize_pdf_to_photobox(pdf_tmp_path: str, session: dict) -> str:
    base = _target_basename(session, "pdf")
    pdf_dir = _ensure_dir(os.path.join(ROOT_DIR, "PDF"))
    dst = os.path.join(pdf_dir, base)
    try:
        _log(f"FinalizePDF:start tmp={pdf_tmp_path} -> dst={dst}")
        if os.path.abspath(pdf_tmp_path) == os.path.abspath(dst):
            _log("FinalizePDF:already at destination")
            return dst
        try:
            os.replace(pdf_tmp_path, dst)
            _log("FinalizePDF:os.replace success")
        except Exception as e:
            _log(f"FinalizePDF:replace failed -> copy err={e}")
            shutil.copyfile(pdf_tmp_path, dst)
            try:
                os.remove(pdf_tmp_path)
            except Exception as e2:
                _log(f"FinalizePDF:remove tmp failed err={e2}")
        return dst
    except Exception as e:
        _log(f"FinalizePDF:exception fallback -> {pdf_tmp_path} err={e}")
        return pdf_tmp_path

def _prepare_origin_copy_to_photobox(session: dict) -> Optional[str]:
    if not os.path.isfile(ORIGIN_JPG):
        _log("OriginCopy:missing origin_photo.jpg")
        return None
    jpg_dir = _ensure_dir(os.path.join(ROOT_DIR, "JPG"))
    dst = os.path.join(jpg_dir, _target_origin_basename(session))
    try:
        shutil.copyfile(ORIGIN_JPG, dst)
        _log(f"OriginCopy:copied to {dst}")
        return dst
    except Exception as e:
        _log(f"OriginCopy:failed err={e}")
        return None

# ────────────────────────────────────────────────────────────────────────────────
# UI 페이지
# ────────────────────────────────────────────────────────────────────────────────
class EnhanceSelectPage(BasePage):
    def __init__(self, theme, session: dict, parent=None):
        try:
            _flow = (getattr(SETTINGS, "data", {}) or {}).get("flow", {}) or {}
            _steps = list(_flow.get("steps") or [])
        except Exception:
            _steps = []
        if not _steps:
            _steps = ["INPUT","SIZE","CAPTURE","PICK","PREVIEW","EMAIL","ENHANCE"]
        super().__init__(theme, steps=_steps, active_index=(len(_steps)-1 if _steps else 0), parent=parent)
        self.session = session

        root = QWidget(self)
        self.P = _build_page_tokens()

        self.setCentralWidget(
            root,
            margin=(self.P["PAGE_M_L"], self.P["PAGE_M_T"], self.P["PAGE_M_R"], self.P["PAGE_M_B"]),
            spacing=self.P["GAP_V"],
            center=False,
        )

        v = QVBoxLayout(root); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(self.P["GAP_V"])
        primary = _theme_primary()
        v.addSpacing(self.P["TITLE_TOP_GAP"])

        head = QHBoxLayout(); head.setSpacing(self.P["HEAD_GAP"])
        title = QLabel("이메일 전송이 완료되었습니다"); title.setStyleSheet(f"color:{TEXT_DARK};")
        title.setFont(self.theme.heading_font(self.P["FS_TITLE"]))
        head.addWidget(title, 0, Qt.AlignVCenter); head.addStretch(1)
        v.addLayout(head)

        card = QFrame(root); card.setObjectName("Card")
        card.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        card.setStyleSheet(
            f"""QFrame#Card{{
                border:{self.P['CARD_BORDER']}px solid {primary};
                border-radius:{self.P['CARD_RADIUS']}px;
                background:#FFFFFF;
            }}"""
        )
        cv = QVBoxLayout(card)
        pad = int(self.P.get("CARD_PAD", 18))
        cv.setContentsMargins(pad, pad, pad, pad); cv.setSpacing(self.P["ROW_GAP"])

        tab = QLabel("추가 옵션 선택", card)
        tab.setStyleSheet(
            f"""background:{primary}; color:#000;
                padding:{self.P['TAB_PAD_V']}px {self.P['TAB_PAD_H']}px;
                border-radius:{self.P['TAB_RADIUS']}px; font-weight:700;"""
        )
        tab.setFont(self.theme.body_font(self.P["FS_TAB"]))
        cv.addWidget(tab, 0, Qt.AlignLeft)

        IND = int(self.P.get("IND_SIZE", 18)); IND_RAD = int(self.P.get("IND_RADIUS", 3))
        chk_css = (
            "QCheckBox{color:" + TEXT_DARK + "; spacing:8px;}"
            f"QCheckBox::indicator{{width:{IND}px; height:{IND}px; border:{self.P['IND_BORDER']}px solid {primary}; "
            f"border-radius:{IND_RAD}px; background:transparent;}}"
            f"QCheckBox::indicator:checked{{background:{primary};}}"
        )

        row1 = QHBoxLayout(); row1.setSpacing(self.P["ROW_GAP"])
        self.chk_print = QCheckBox("사진 인화 (1장 6컷 인쇄)")
        self.chk_print.setStyleSheet(chk_css)
        self.chk_print.setFont(self.theme.body_font(self.P["FS_CHECK"]))
        row1.addWidget(self.chk_print, 0, Qt.AlignVCenter)
        price = QLabel("<span style='color:#777'>인화 1장 2,000원</span>")
        price.setFont(self.theme.body_font(self.P["FS_NOTE"]))
        row1.addWidget(price, 0, Qt.AlignVCenter)
        row1.addStretch(1)
        cv.addLayout(row1)

        row2 = QHBoxLayout(); row2.setSpacing(self.P["ROW_GAP"])
        self.chk_pro = QCheckBox("전문가 보정 요청")
        self.chk_pro.setStyleSheet(chk_css)
        self.chk_pro.setFont(self.theme.body_font(self.P["FS_CHECK"]))
        row2.addWidget(self.chk_pro, 0, Qt.AlignVCenter)
        note2 = QLabel("<span style='color:#777'>1주일 내 방문 시 적용</span>")
        note2.setFont(self.theme.body_font(self.P["FS_NOTE"]))
        row2.addWidget(note2, 0, Qt.AlignVCenter)
        row2.addStretch(1)
        cv.addLayout(row2)
        v.addWidget(card)

        self.btn_finish = QPushButton("FINISH")
        hover_rgba = _rgba_from_hex(primary, 0.10)
        self.btn_finish.setStyleSheet(
            f"""QPushButton{{
                    background:transparent; border:2px solid {primary};
                    color:{TEXT_DARK}; padding:9px {self.P['BTN_PAD_H']}px;
                    border-radius:{self.P['BTN_RADIUS']}px; font-weight:700;
               }}
               QPushButton:hover{{background:{hover_rgba};}}"""
        )
        self.btn_finish.setFont(self.theme.body_font(self.P["FS_FINISH"]))
        self.btn_finish.clicked.connect(self._on_finish)
        v.addWidget(self.btn_finish, 0, Qt.AlignHCenter)

        v.addStretch(1)
        self.set_next_enabled(False)

        try:
            self.footer.set_prev_mode(TriButton.MODE_HIDDEN)
            self.footer.set_next_mode(TriButton.MODE_HIDDEN)
        except Exception:
            pass

        self.chk_print.setChecked(bool(self.session.get("opt_print")))
        self.chk_pro.setChecked(bool(self.session.get("opt_pro_retouch")))

    def showEvent(self, e):
        super().showEvent(e)
        try:
            self.footer.set_prev_mode(TriButton.MODE_HIDDEN)
            self.footer.set_next_mode(TriButton.MODE_HIDDEN)
        except Exception:
            pass

    # ────────────────────────────────────────────────────────────────────────
    # 진행 다이얼로그
    # ────────────────────────────────────────────────────────────────────────
    def _run_with_progress(self, work_fn):
        dlg = QProgressDialog("", None, 0, 100, self)
        dlg.setWindowModality(Qt.ApplicationModal)
        dlg.setAutoClose(True); dlg.setAutoReset(True)
        dlg.setCancelButton(None); dlg.setMinimumDuration(0)
        dlg.setValue(0); dlg.setLabelText("준비 중…")

        def update(text=None, pct=None):
            if text is not None: dlg.setLabelText(text)
            if pct is not None: dlg.setValue(max(0, min(100, int(pct))))
            QApplication.processEvents()

        t0 = dt.datetime.now()
        try:
            ok, msg = work_fn(update)
        except Exception as e:
            ok, msg = False, str(e)

        while (dt.datetime.now() - t0).total_seconds() < 1.0:
            QApplication.processEvents()

        dlg.setValue(100); dlg.setLabelText("완료")
        return ok, msg

    # ────────────────────────────────────────────────────────────────────────
    # FINISH
    # ────────────────────────────────────────────────────────────────────────
    def _on_finish(self):
        self.session["opt_print"] = self.chk_print.isChecked()
        self.session["opt_pro_retouch"] = self.chk_pro.isChecked()

        if not self.chk_print.isChecked() and not self.chk_pro.isChecked():
            return self._go_outro()

        def work(update):
            cfg_all = _load_settings()
            email_cfg = emailer.load_email_config()  # emailer가 스키마를 정규화해서 반환 :contentReference[oaicite:5]{index=5}

            # 공통 토큰
            name  = (self.session.get("name") or "noname").strip()
            size_key = self.session.get("size_key") or "ID_30x40"
            tokens_base = {
                "name": name,
                "size_key": size_key,
                "date": _today(),
                "timestamp": _now_stamp(),
            }

            # 1) 인화(출력담당)
            if self.chk_print.isChecked():
                update("인화: 소스 이미지 여는 중…", 5)
                if not os.path.isfile(EDITED_JPG):
                    _log("LoadImage:edited_photo.jpg not found")
                    update("edited_photo.jpg 없음. 인화 작업 생략.", 25)
                else:
                    img = QImage(EDITED_JPG)
                    _log(f"LoadImage path={EDITED_JPG} isNull={img.isNull()}")
                    if img.isNull():
                        update("이미지 로드 실패. 인화 작업 생략.", 25)
                    else:
                        update("타일 PDF 생성 중…", 35)
                        photo_mm = tuple(self.session.get("photo_mm") or storage.SIZES_MM.get(size_key, (30, 40)))
                        _log(f"BuildPDF call size_key={size_key} photo_mm={photo_mm}")
                        tmp_pdf = storage.build_tiled_pdf(
                            image=img,
                            session=self.session,
                            size_key=size_key,
                            photo_mm=photo_mm,
                        )
                        final_pdf_path = _finalize_pdf_to_photobox(tmp_pdf, self.session)
                        self.session["pdf_path"] = final_pdf_path
                        _log(f"BuildPDF done tmp={tmp_pdf} -> final={final_pdf_path}")
                        update("PDF 저장 완료", 55)

                        # 인쇄(선택)
                        cfg_name = (((cfg_all.get("printer") or {}).get("photo") or {}).get("name")) \
                                   or ((cfg_all.get("photo_printer") or {}).get("name")) or ""
                        printer_name = "Canon G500 series"
                        if cfg_name and ("canon" in cfg_name.lower()) and ("g500" in cfg_name.lower()):
                            printer_name = cfg_name
                        _log(f"Print:using printer='{printer_name}' (cfg='{cfg_name}')")
                        update("인쇄 중…", 70)
                        ok_print = _try_print_to_named_printer(final_pdf_path, printer_name)
                        _log(f"Print:result ok={ok_print}")
                        update("인쇄 완료", 75)

                        # 출력담당 메일
                        rec_p = _recips_printer(cfg_all)  # settings.email.print_manager.to 읽기 :contentReference[oaicite:6]{index=6}
                        if rec_p:
                            update("출력담당 메일 발송 중…", 85)
                            # 설정 템플릿 우선
                            pm_cfg = ((cfg_all.get("email") or {}).get("print_manager") or {})
                            tokens = dict(tokens_base)
                            tokens["filename"] = os.path.basename(final_pdf_path)

                            subj_fallback, body_fallback = _render_printer_mail_default(self.session, final_pdf_path)
                            subj_p, body_p = _render_with_settings(pm_cfg, tokens, (subj_fallback, body_fallback))

                            _log(f"Email:printer recipients={rec_p} subj={subj_p!r}")
                            for to in rec_p:
                                try:
                                    try:
                                        res = emailer.send_email_checked(
                                            to_email=to,
                                            subject=subj_p,
                                            body=body_p,
                                            attachments=[final_pdf_path],
                                            cfg=email_cfg,
                                        )
                                    except AttributeError:
                                        res = emailer.send_email(
                                            to_email=to,
                                            subject=subj_p,
                                            body=body_p,
                                            attachments=[final_pdf_path],
                                            cfg=email_cfg,
                                        )
                                    _log(f"Email:printer to={to} result={res}")
                                except Exception as e:
                                    _log(f"Email:printer to={to} exception err={e}")
                        update("인화 작업 완료", 90)

            # 2) 전문가 보정(보정담당)
            if self.chk_pro.isChecked():
                update("보정: 원본 준비 중…", 92)
                jpg_path = _prepare_origin_copy_to_photobox(self.session)
                if jpg_path:
                    rec_r = _recips_retouch(cfg_all)  # settings.email.retouch_manager.to 읽기 :contentReference[oaicite:7]{index=7}
                    if rec_r:
                        update("보정담당 메일 발송 중…", 95)
                        # 설정 템플릿 우선
                        rm_cfg = ((cfg_all.get("email") or {}).get("retouch_manager") or {})
                        tokens = dict(tokens_base)
                        tokens["filename"] = os.path.basename(jpg_path)

                        subj_fallback, body_fallback = _render_retouch_mail_default(self.session, jpg_path)
                        subj_r, body_r = _render_with_settings(rm_cfg, tokens, (subj_fallback, body_fallback))

                        _log(f"Email:retouch recipients={rec_r} subj={subj_r!r}")
                        for to in rec_r:
                            try:
                                try:
                                    res = emailer.send_email_checked(
                                        to_email=to,
                                        subject=subj_r,
                                        body=body_r,
                                        attachments=[jpg_path],
                                        cfg=email_cfg,
                                    )
                                except AttributeError:
                                    res = emailer.send_email(
                                        to_email=to,
                                        subject=subj_r,
                                        body=body_r,
                                        attachments=[jpg_path],
                                        cfg=email_cfg,
                                    )
                                _log(f"Email:retouch to={to} result={res}")
                            except Exception as e:
                                _log(f"Email:retouch to={to} exception err={e}")
                        update("보정 작업 완료", 98)

            update("정리 중…", 100)
            return True, "OK"

        self._run_with_progress(work)
        return self._go_outro()

    # ────────────────────────────────────────────────────────────────────────
    # Outro 이동
    # ────────────────────────────────────────────────────────────────────────
    def _go_outro(self):
        try:
            from app.ui.router import find_router
            r = find_router(self)
        except Exception:
            r = None

        for method in ("goto", "go", "push", "show"):
            if r and hasattr(r, method) and callable(getattr(r, method)):
                try:
                    getattr(r, method)("outro"); return
                except Exception:
                    pass

        mw = self.window()
        for method in ("goto", "go", "push", "show"):
            if hasattr(mw, method) and callable(getattr(mw, method)):
                try:
                    getattr(mw, method)("outro"); return
                except Exception:
                    pass

        try:
            self.go_next.emit()
        except Exception:
            pass

__all__ = ["EnhanceSelectPage"]
