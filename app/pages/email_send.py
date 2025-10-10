# app/pages/email_send.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, re, shutil, logging
from datetime import datetime
from typing import List, Tuple, Optional

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QProgressBar, QLabel, QPushButton,
    QSizePolicy, QApplication, QMessageBox
)
from PySide6.QtCore import Qt, QTimer

from app.ui.base_page import BasePage
from app.pages.setting import SETTINGS
from app.utils import emailer  # settings.json의 [email] 사용

try:
    from app.components.footer_bar import TriButton  # type: ignore
except Exception:
    TriButton = None  # type: ignore

PHOTOBOX_DIR = r"C:\PhotoBox"
EDITED_JPG   = os.path.join(PHOTOBOX_DIR, "edited_photo.jpg")
JPG_DIR      = os.path.join(PHOTOBOX_DIR, "JPG")

BASE_FHD = {
    "fs_h1": 36, "fs_h2": 21, "fs_body": 21, "fs_label": 30, "fs_small": 9,
    "btn_h": 45, "btn_pad_v": 9, "btn_pad_h": 6, "btn_radius": 6,
    "sec_gap": 12, "pb_h": 30, "pb_radius": 0, "border_thin": 3,
    "pb_w_min": 720, "pad_area_t": 0, "pad_area_r": 0, "pad_area_b": 0, "pad_area_l": 0,
    "gap_header_btn": 9, "gap_btn_prog": 12,
}
TEXT_BASE = {
    "title": "이메일 보내기", "recipient1": "수신자 1", "recipient2": "수신자 2",
    "recipient_none": "(없음)", "btn_send": "이메일 보내기",
}

# ───────────────────────── helpers
def _recipients(session) -> List[str]:
    cand: List[str] = []
    for key in ("email1", "email2"):
        v = session.get(key)
        if not v:
            continue
        if isinstance(v, (list, tuple)):
            cand += [str(x).strip() for x in v]
        elif isinstance(v, str):
            cand += [p.strip() for p in re.split(r"[,\n]+", v)]
    out, seen = [], set()
    for e in [x for x in cand if x]:
        if e not in seen:
            out.append(e); seen.add(e)
    return out[:2]

def _today_yymmdd() -> str:
    return datetime.now().strftime("%y%m%d")

def _sanitize_filename(s: str) -> str:
    return re.sub(r"[^\w가-힣]+", "_", str(s)).strip("_") or "noname"

def _target_basename(session: dict, ext: str) -> str:
    name  = _sanitize_filename(session.get("name") or "noname")
    phone = re.sub(r"\D+", "", (session.get("phone") or "0000"))
    ratio = _sanitize_filename((session.get("ratio") or "3040"))
    return f"{_today_yymmdd()}_{name}_{phone}_{ratio}.{ext.lower().lstrip('.')}"

def _ensure_dir(p: str) -> str:
    try: os.makedirs(p, exist_ok=True)
    except Exception: pass
    return p

def _unique_path(dir_path: str, base_name: str) -> str:
    root, ext = os.path.splitext(base_name)
    cand = os.path.join(dir_path, base_name)
    i = 2
    while os.path.exists(cand):
        cand = os.path.join(dir_path, f"{root}_{i}{ext}")
        i += 1
    return cand

def _prepare_named_copy_to_jpg_dir(session: dict) -> Optional[str]:
    src_path = EDITED_JPG
    if not os.path.isfile(src_path):
        return None
    _ensure_dir(JPG_DIR)
    base = _target_basename(session, "jpg")
    dst = _unique_path(JPG_DIR, base)
    try:
        shutil.copyfile(src_path, dst)
        return dst
    except Exception:
        return None

def _load_email_config() -> dict:
    return emailer.load_email_config()

def _format_subject_body(cfg: dict, session: dict, ts: str) -> Tuple[str, str]:
    subj = (cfg.get("customer", {}) or {}).get("subject") or "증명사진 전송"
    body = (cfg.get("customer", {}) or {}).get("body") or "사진을 첨부합니다."
    name  = (session.get("name") or "noname").strip()
    phone = re.sub(r"\D+", "", (session.get("phone") or "0000").strip())
    ratio = (session.get("ratio") or "3040").strip()
    tokens = {"name": name, "phone": phone, "date": ts, "ratio": ratio, "size_key": ratio}
    try: subj = subj.format(**tokens)
    except Exception: pass
    try: body = body.format(**tokens)
    except Exception: pass
    return subj, body

# ───────────────────────── page
class EmailSendPage(BasePage):
    def _resolve_primary_hex(self) -> str:
        try:
            return (getattr(self.theme, 'colors', {}) or {}).get('primary', '#2F74FF')
        except Exception:
            return '#2F74FF'

    def _get_scale_grid(self):
        app = QApplication.instance()
        tt = (app.property("TYPO_TOKENS") or {}) if app else {}
        return float(tt.get("scale", 1.0)), int(tt.get("grid", 3)), (tt.get("borders", {}) or {})

    @staticmethod
    def _snap(v: int, grid: int) -> int:
        return max(1, (int(v) // max(1, grid)) * max(1, grid))

    def _refresh_tokens(self) -> None:
        s, g, borders = self._get_scale_grid()
        snapv = lambda x: self._snap(int(round(x * s)), g)
        self.BORDERS = borders
        self.TOK = {k: snapv(v) for k, v in BASE_FHD.items()}

    def _apply_tokens(self) -> None:
        try:
            lay = self.email_area.layout(); lay.setSpacing(int(self.TOK.get('sec_gap', 12)))
            self.btn_email.setFixedHeight(int(self.TOK.get('btn_h', 45)))
            self.btn_email.setFont(self.theme.body_font(int(self.TOK.get('fs_body', 15))))
            self.btn_email.setStyleSheet(self._btn_css())
            self.pb_email.setFixedHeight(int(self.TOK.get('pb_h', 12)))
            self.pb_email.setMinimumWidth(int(self.TOK.get('pb_w_min', 480)))
            self.header_lbl.setFont(self.theme.body_font(int(self.TOK.get('fs_body', 15))))
            self.msg_email.setFont(self.theme.body_font(int(self.TOK.get('fs_body', 15))))
        except Exception:
            pass

    def __init__(self, theme, session: dict, parent=None):
        try:
            _flow = (getattr(SETTINGS, "data", {}) or {}).get("flow", {}) or {}
            _steps = list(_flow.get("steps") or [])
        except Exception:
            _steps = []
        if not _steps:
            _steps = ["INPUT","SIZE","CAPTURE","PICK","PREVIEW","EMAIL","ENHANCE"]
        super().__init__(theme, steps=_steps, active_index=5, parent=parent)
        self.session = session
        self._primary = self._resolve_primary_hex()

        self._refresh_tokens()
        self.TEXT = TEXT_BASE.copy()

        root = QWidget(self)
        s, g, _ = self._get_scale_grid()
        snapv = lambda x: self._snap(int(round(x * s)), g)
        self.setCentralWidget(root, margin=(snapv(72), snapv(18), snapv(72), snapv(18)), spacing=0, center=False)
        v = QVBoxLayout(root); v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        v.addStretch(2)
        self.email_area = self._make_email_area(root)
        self.email_area.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        v.addWidget(self.email_area, 0, Qt.AlignLeft)
        v.addStretch(5)

        self._apply_tokens()

        try:
            if TriButton:
                self.footer.set_prev_mode(TriButton.MODE_HIDDEN)
        except Exception:
            pass
        self.set_next_enabled(True)

        self._sync_recips()

    def showEvent(self, e):
        super().showEvent(e)
        try:
            if TriButton:
                self.footer.set_prev_mode(TriButton.MODE_HIDDEN)
        except Exception:
            pass

    def resizeEvent(self, e):
        super().resizeEvent(e)

    # ───────────── UI
    def _make_email_area(self, parent) -> QWidget:
        w = QWidget(parent)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(
            int(self.TOK.get('pad_area_l', 0)),
            int(self.TOK.get('pad_area_t', 0)),
            int(self.TOK.get('pad_area_r', 0)),
            int(self.TOK.get('pad_area_b', 0)),
        )
        lay.setSpacing(int(self.TOK.get('sec_gap', 12)))

        self.header_lbl = QLabel(); self.header_lbl.setTextFormat(Qt.RichText); self.header_lbl.setStyleSheet("color:#444;")
        lay.addWidget(self.header_lbl)
        lay.addSpacing(int(self.TOK.get('gap_header_btn', 9)))

        self.btn_email = QPushButton(self.TEXT.get("btn_send", "이메일 보내기"))
        self.btn_email.setStyleSheet(self._btn_css())
        self.btn_email.clicked.connect(self._on_send_email)
        lay.addWidget(self.btn_email, 0, Qt.AlignLeft)

        lay.addSpacing(int(self.TOK.get('gap_btn_prog', 12)))
        self.pb_email = QProgressBar(); self._style_progress(self.pb_email); lay.addWidget(self.pb_email)

        self.msg_email = QLabel(""); self.msg_email.setStyleSheet("color:#333;")
        lay.addWidget(self.msg_email)

        return w

    # ───────────── style
    def _btn_css(self) -> str:
        p = getattr(self, "_primary", "#2F74FF")
        r = int(self.TOK.get("btn_radius", 12))
        pv = int(self.TOK.get("btn_pad_v", 9))
        ph = int(self.TOK.get("btn_pad_h", 18))
        return f"""
QPushButton{{background:transparent; border:{int(self.TOK.get('border_thin', 3))}px solid {p}; color:{p}; padding:{pv}px {ph}px; border-radius:{r}px;}}
QPushButton:hover{{background:{p}; color:#FFFFFF;}}
QPushButton:disabled{{opacity:.5}}
"""

    def _style_progress(self, pb: QProgressBar):
        pb.setRange(0, 100); pb.setTextVisible(False)
        pb.setFixedHeight(int(self.TOK.get("pb_h", 12)))
        r = int(self.TOK.get("pb_radius", 6)); p = getattr(self, "_primary", "#2F74FF")
        pb.setStyleSheet(f"""
QProgressBar{{background:transparent; border:{int(self.TOK.get('border_thin', 3))}px solid {p}; border-radius:{r}px;}}
QProgressBar::chunk{{background:{p}; border-radius:{r}px;}}
""")

    # ───────────── data → header
    def _sync_recips(self):
        fs1 = int(self.TOK.get('fs_h1', 24)); fsb = int(self.TOK.get('fs_body', 15))
        email1 = (self.session.get("email1") or "").strip()
        email2 = (self.session.get("email2") or "").strip()
        none = self.TEXT.get("recipient_none", "(없음)")
        e1 = email1 if email1 else none; e2 = email2 if email2 else none
        title = self.TEXT.get("title", "이메일 보내기")
        lab1 = self.TEXT.get("recipient1", "수신자 1"); lab2 = self.TEXT.get("recipient2", "수신자 2")
        html = (f"<div style='line-height:1.25'>"
                f"<div style='font-weight:700; font-size:{fs1}px;'>{title}</div>"
                f"<div style='font-size:{fsb}px; color:#666;'>{lab1}: {e1}<br>{lab2}: {e2}</div>"
                f"</div>")
        self.header_lbl.setText(html)

    # ───────────── robust navigation
    def _navigate_enhance(self):
        """가능한 모든 경로로 다음 화면으로 이동."""
        logging.info("[EmailSend] navigating to enhance_select")
        # 1) Router가 있으면 사용
        try:
            from app.ui import router as _router  # type: ignore
        except Exception:
            _router = None

        def _try_call(obj, names, *args):
            for n in names:
                fn = getattr(obj, n, None)
                if callable(fn):
                    try:
                        fn(*args)
                        return True
                    except Exception:
                        continue
            return False

        route_names = ("enhance_select", "EnhanceSelect", "enhance", "ENHANCE")
        if _router:
            r = None
            try:
                r = getattr(_router, "find_router", None)
                r = r(self) if callable(r) else None
            except Exception:
                r = None
            if r:
                if _try_call(r, ("goto","go","push","show","switch","navigate"), "enhance_select"): return
                for rn in route_names:
                    if _try_call(r, ("goto","go","push","show","switch","navigate"), rn): return
                if _try_call(r, ("goto_enhance","go_enhance","open_enhance")): return
            # 전역 라우터 함수도 시도
            if _try_call(_router, ("goto","go","push","show","switch","navigate"), "enhance_select"): return
            for rn in route_names:
                if _try_call(_router, ("goto","go","push","show","switch","navigate"), rn): return

        # 2) Footer의 Next 시뮬레이션
        try:
            self.set_next_enabled(True)
        except Exception:
            pass
        f = getattr(self, "footer", None)
        if f:
            for attr in ("btn_next","btnNext","next_btn","buttonNext","nextButton","next"):
                b = getattr(f, attr, None)
                if b is not None and hasattr(b, "click"):
                    try:
                        b.click(); return
                    except Exception:
                        pass
            if _try_call(f, ("click_next","go_next","do_next","on_next","press_next","emit_next")): return

        # 3) 신호 직접 발행 시도
        for sig_name in ("go_next","next","proceedNext","proceed_next"):
            sig = getattr(self, sig_name, None)
            try:
                sig.emit()
                return
            except Exception:
                pass

        logging.warning("[EmailSend] navigation fallback exhausted")

    # ───────────── email send
    def _on_send_email(self):
        """첨부를 C:\\PhotoBox\\JPG에 저장 후 발송. 성공 시 자동 이동."""
        def ui_update(text=None, pct=None):
            if text is not None:
                self.msg_email.setText(str(text))
            if pct is not None:
                self.pb_email.setValue(max(0, min(100, int(pct))))
            QApplication.processEvents()

        # 시작 UI
        self.btn_email.setEnabled(False)
        self.set_next_enabled(False)
        self.pb_email.setValue(0)
        self.pb_email.show()
        ui_update("첨부 준비 중…", 10)

        # 첨부 준비
        attach_path = _prepare_named_copy_to_jpg_dir(self.session)
        if not attach_path:
            self.btn_email.setEnabled(True)
            self.set_next_enabled(True)
            self.msg_email.setText(r"C:\PhotoBox\edited_photo.jpg 없음 또는 복사 실패")
            return
        self.session["customer_jpg_path"] = attach_path
        attach_label = os.path.basename(attach_path)

        # 수신자
        ui_update("수신자 확인 중…", 30)
        recips = _recipients(self.session)
        if not recips:
            self.btn_email.setEnabled(True)
            self.set_next_enabled(True)
            self.msg_email.setText(f"수신자 없음. 파일만 저장됨: {attach_label}")
            return

        # 메일 구성
        cfg = _load_email_config()
        subj, body = _format_subject_body(cfg, self.session, _today_yymmdd())

        # 발송
        ok_all, first_err = True, None
        n = len(recips)
        for i, to in enumerate(recips, 1):
            ui_update(f"메일 발송 중… ({i}/{n})", 40 + int(55 * i / n))
            try:
                # emailer.send_email(to=…, subject=…, body=…, attachments=[…], config=…)
                emailer.send_email(
                    to=to,
                    subject=subj,
                    body=body,
                    attachments=[attach_path],
                    config=cfg,
                )
            except Exception as e:
                ok_all = False
                if first_err is None:
                    first_err = str(e)

        # 결과 및 내비게이션
        if ok_all:
            ui_update(f"성공: {attach_label} 발송 완료", 100)
            # 이벤트 루프 한 틱 후 내비게이션
            QTimer.singleShot(120, self._navigate_enhance)
        else:
            self.btn_email.setEnabled(True)
            self.set_next_enabled(True)
            ui_update(f"실패: {first_err}", 100)

__all__ = ["EmailSendPage"]
