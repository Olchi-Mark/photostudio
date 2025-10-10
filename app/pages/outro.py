# app/pages/outro.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os, re, shutil, time, datetime as dt
from typing import Optional

from PySide6.QtCore import Qt, QSize, QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QApplication

from app.constants import IMAGES_DIR
try:
    from app.utils.storage import photobox_job_dir, PHOTOBOX_ROOT
except Exception:
    photobox_job_dir = None  # type: ignore
    PHOTOBOX_ROOT = r"C:\PhotoBox"  # 폴백 고정

# FooterBar(선택)
try:
    from app.components.footer_bar import FooterBar, TriButton  # type: ignore
except Exception:
    FooterBar = None  # type: ignore
    TriButton = None  # type: ignore

# ── helpers ─────────────────────────────────────────────────────
def _snap3(v: int) -> int:
    return (int(v) // 3) * 3

def _theme_primary(theme) -> str:
    try:
        return (getattr(theme, "colors", {}) or {}).get("primary", "#2F74FF")
    except Exception:
        return "#2F74FF"

def _rgba_from_hex(hex_str: str, a: float) -> str:
    s = hex_str.lstrip('#')
    try:
        if len(s) == 3:
            r, g, b = (int(s[i]*2, 16) for i in range(3))
        else:
            r, g, b = int(s[0:2],16), int(s[2:4],16), int(s[4:6],16)
    except Exception:
        r, g, b = 47, 116, 255
    return f"rgba({r},{g},{b},{float(a)})"

def _retry(n: int, wait: float, fn, *args, **kwargs):
    last = None
    for _ in range(max(1, int(n))):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last = e
            time.sleep(max(0.0, float(wait)))
    if last:
        raise last

def _safe_unlink(path: str) -> None:
    try:
        if path and os.path.isfile(path):
            _retry(2, 0.2, os.remove, path)
    except Exception:
        pass

def _safe_rmtree(path: str) -> None:
    if path and os.path.isdir(path):
        root = os.path.normcase(os.path.abspath(PHOTOBOX_ROOT))
        cand = os.path.normcase(os.path.abspath(path))
        if not cand.startswith(root + os.sep):
            return
        try:
            _retry(3, 0.5, shutil.rmtree, path)
        except Exception:
            pass

def _sanitize_name(name: Optional[str]) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣_]+", "", name or "noname")

def _guess_job_dir_from_session(session: dict) -> str:
    today = dt.datetime.now().strftime("%y%m%d")
    phone = re.sub("[^0-9]+", "", session.get("phone") or "")
    last4 = phone[-4:] or "0000"
    stem = f"{_sanitize_name(session.get('name'))}_{last4}"
    return os.path.join(PHOTOBOX_ROOT, today, stem)

# ── page ────────────────────────────────────────────────────────
class OutroPage(QWidget):
    """감사 화면 → 지정 시간 후 Intro 복귀. 복귀 직전 작업폴더 정리 + 세션 초기화."""
    def __init__(self, theme, session):
        super().__init__()
        self.theme = theme
        self.session = session

        # tokens
        app = QApplication.instance()
        TOK_BASE = (app.property("TYPO_TOKENS") or {}) if app else {}
        TOK_OUTRO = (app.property("OUTRO_TOKENS") or {}) if app else {}
        TOK = {**TOK_BASE, **TOK_OUTRO}
        try:
            scale = float(TOK.get("scale", 1.0) or 1.0)
        except Exception:
            scale = 1.0
        snapv = lambda v: _snap3(int(v * scale))

        self._fs_h1    = snapv(int(TOK.get("outro_fs_h1", 99)))
        self._fs_body  = snapv(int(TOK.get("outro_fs_body", 36)))
        self._fs_brand = snapv(int(TOK.get("outro_fs_brand", 30)))
        self._pad = (
            snapv(int(TOK.get("outro_pad_l", 36))),
            snapv(int(TOK.get("outro_pad_t", 24))),
            snapv(int(TOK.get("outro_pad_r", 36))),
            snapv(int(TOK.get("outro_pad_b", 24))),
        )
        self._primary = _theme_primary(self.theme)
        self._auto_ms = int(TOK.get("outro_ms", 5000) or 5000)

        # 브랜드 로고 스케일 기본값
        self._brand_ratio = 0.18
        self._brand_min   = snapv(150)

        root = QVBoxLayout(self)
        root.setContentsMargins(*self._pad)
        root.setSpacing(0)

        root.addStretch(3)

        self.guide = QLabel("출력된 사진은 카운터에서 결제 후 수령하시면 됩니다\n이용해주셔서 감사합니다", self)
        self.guide.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.guide.setFont(self.theme.body_font(self._fs_body))
        self.guide.setStyleSheet(f"color: {_rgba_from_hex(self._primary, 0.85)};")
        root.addWidget(self.guide, 0, Qt.AlignHCenter)

        self.thanks = QLabel("THANK  YOU", self)
        self.thanks.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.thanks.setFont(self.theme.heading_font(self._fs_h1))
        self.thanks.setStyleSheet(f"color:{self._primary}; font-weight:900;")
        root.addWidget(self.thanks, 0, Qt.AlignHCenter)

        root.addStretch(8)

        brand_path = os.path.join(IMAGES_DIR, "brand_logo.jpg")
        self._brand_pm: Optional[QPixmap] = QPixmap(brand_path) if os.path.exists(brand_path) else None
        self.brand = QLabel(self); self.brand.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        if self._brand_pm:
            self._apply_brand_scaled()
        else:
            self.brand.setText("")
            self.brand.setFont(self.theme.heading_font(self._fs_brand))
            self.brand.setStyleSheet(f"color: {_rgba_from_hex(self._primary, 0.9)}; letter-spacing: 1px;")
        root.addWidget(self.brand, 0, Qt.AlignHCenter)
        root.addStretch(1)

        try:
            if FooterBar:
                self.footer = FooterBar(self)
                if TriButton:
                    self.footer.set_prev_mode(TriButton.MODE_HIDDEN)
                    self.footer.set_next_mode(TriButton.MODE_HIDDEN)
                root.addWidget(self.footer, 0)
        except Exception:
            pass

        self._auto_timer = QTimer(self)
        self._auto_timer.setSingleShot(True)
        self._auto_timer.timeout.connect(self._go_intro)

    def before_enter(self, session=None):
        try:
            self._auto_timer.start(self._auto_ms)
        except Exception:
            pass
        return True

    def before_leave(self, session=None):
        try:
            self._auto_timer.stop()
        except Exception:
            pass
        return True

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_brand_scaled()

    def _apply_brand_scaled(self):
        if not self._brand_pm:
            return
        target_w = max(self._brand_min, min(int(self.width()*self._brand_ratio), self._brand_pm.width()))
        scaled = self._brand_pm.scaled(QSize(target_w, target_w), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.brand.setPixmap(scaled)

    # ── photobox 정리 ─────────────────────────────────────────────
    def _cleanup_photobox(self):
        job_dir = None
        try:
            if callable(photobox_job_dir):  # type: ignore
                job_dir = photobox_job_dir(self.session, create=False)
        except Exception:
            job_dir = None
        if not job_dir:
            job_dir = _guess_job_dir_from_session(self.session)
        try:
            base, stem = os.path.dirname(job_dir), os.path.basename(job_dir)
            if os.path.isdir(base):
                cands = [d for d in os.listdir(base) if d == stem or d.startswith(stem + "-")]
                if cands:
                    job_dir = max((os.path.join(base, d) for d in cands), key=lambda p: os.path.getmtime(p))
        except Exception:
            pass
        _safe_rmtree(job_dir)
        _safe_unlink(os.path.join(PHOTOBOX_ROOT, "origin_photo.jpg"))
        _safe_unlink(os.path.join(PHOTOBOX_ROOT, "edited_photo.jpg"))

    def _reset_session_safely(self):
        s = self.session
        if not isinstance(s, dict):
            return
        try:
            from app.ui.router import find_router  # ← 지연 import로 순환 차단
            r = find_router(self)
        except Exception:
            r = None
        for obj in (r, self.window()):
            for attr in ("reset_session", "restart_session", "reset", "restart"):
                if obj and hasattr(obj, attr) and callable(getattr(obj, attr)):
                    try:
                        getattr(obj, attr)()
                        return
                    except Exception:
                        pass
        try:
            s.clear()
        except Exception:
            for k in list(s.keys()):
                try:
                    s.pop(k, None)
                except Exception:
                    pass

    def _go_intro(self):
        self._cleanup_photobox()
        self._reset_session_safely()
        try:
            from app.ui.router import find_router  # ← 지연 import
            r = find_router(self)
        except Exception:
            r = None
        if r:
            try:
                r.go("intro"); return
            except Exception:
                pass

__all__ = ["OutroPage"]
