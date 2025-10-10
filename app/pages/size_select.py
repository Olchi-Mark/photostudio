# app/pages/size_select.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from typing import Optional, List, Tuple
import os
from math import gcd

from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QFrame, QSizePolicy, QHBoxLayout, QSpacerItem
)
from PySide6.QtGui import QColor, QPixmap

from app.ui.base_page import BasePage
from app.pages.setting import SETTINGS

# ── Font size tokens (3-multiple) ─────────────────────────────
# FHD 기준값을 상단에 하드코딩하고, qApp TYPO_TOKENS.scale 반영 후 3의 배수로 스냅한다.
def _snap3(v: int) -> int:
    return (int(round(v)) // 3) * 3

_F_FHD = {
    "TITLE_FS": 36,  # 타이틀 글자 크기. 사용처: self.title.setFont(theme.heading_font(...))
    "BADGE_FS": 21,  # 배지 글자 크기. 사용처: self.card_*.badge.setFont(theme.body_font(...))
    "DESC_FS": 21,   # 설명 글자 크기. 사용처: self.card_*.desc.setFont(theme.body_font(...))
}

def _font_tokens() -> dict:
    app = QApplication.instance()
    TOK = (app.property("TYPO_TOKENS") or {}) if app else {}
    scale = float(TOK.get("scale", 1.0)) if isinstance(TOK, dict) else 1.0
    return {k: _snap3(int(round(v * scale))) for k, v in _F_FHD.items()}

# ── Spacing tokens (3-grid) ─────────────────────────
_S_FHD = {
    "PAD_H": 39,      # 좌우 바깥 여백. 사용처: self.cv.setContentsMargins(PAD_H, PAD_V, PAD_H, PAD_V)
    "PAD_V": 24,      # 위아래 바깥 여백. 사용처: self.cv.setContentsMargins(...)
    "ROW_GAP": 90,    # 두 카드 사이 간격. 사용처: self.row.setSpacing(...)
    "CARD_PAD": 12,   # 카드 내부 패딩/간격. 사용처: SizeCard.v.setContentsMargins / setSpacing
    "EXTRA_EACH": 24, # 레이아웃 폭 계산 보정치. 사용처: _relayout_all()의 max_for_photos 계산
    "BADGE_PAD_V": 9, # 배지 상하 패딩. 사용처: QLabel[role='badge'] padding
    "BADGE_PAD_H": 15,# 배지 좌우 패딩. 사용처: QLabel[role='badge'] padding
    "TOAST_PAD_V": 9, # 토스트 상하 패딩. 현재 미사용(토스트 제거)
    "TOAST_PAD_H": 15,# 토스트 좌우 패딩. 현재 미사용(토스트 제거)
}

# ── Border/Radius tokens ─────────────────────────
_B_FHD = {
    "FRAME_BORDER": 3, # 사진 프레임 테두리 두께. 사용처: QFrame#PhotoBox border
    "FRAME_RADIUS": 6, # 사진 프레임 모서리 라운드. 사용처: QFrame#PhotoBox border-radius
    "CARD_RADIUS": 9,  # 카드 모서리 라운드. 사용처: QWidget#SizeCard border-radius
    "BADGE_RADIUS": 15,# 배지 라운드. 사용처: QLabel[role='badge'] border-radius
    "TOAST_RADIUS": 12,# 토스트 라운드. 현재 미사용(토스트 제거)
}

def _scale_val(v: int) -> int:
    app = QApplication.instance()
    TOK = (app.property("TYPO_TOKENS") or {}) if app else {}
    scale = float(TOK.get("scale", 1.0)) if isinstance(TOK, dict) else 1.0
    return _snap3(int(round(v * scale)))

def _tier() -> str:
    app = QApplication.instance()
    t = app.property("DISPLAY_TIER") if app else "FHD"
    return t if t in ("FHD", "QHD", "UHD") else "FHD"

def _scale_border_px(v: int) -> int:
    t = _tier()
    if v == 1:
        return 2 if t == "UHD" else 1
    if v == 2:
        return 4 if t == "UHD" else (3 if t == "QHD" else 2)
    return _scale_val(v)

def _space_tokens() -> dict:
    return {k: _scale_val(v) for k, v in _S_FHD.items()}

def _border_tokens() -> dict:
    out = {}
    for k, v in _B_FHD.items():
        out[k] = _scale_border_px(v) if "BORDER" in k else _scale_val(v)
    return out

# ── Layout tokens (user‑editable) ─────────────────────────
# - PHOTO_W_MODE: 'fixed' → 아래 PHOTO_W_* 픽셀값 사용 / 'auto' → 가용 폭에 맞춰 자동 배치
# - PHOTO_W_34 / PHOTO_W_3545: 각 카드의 "사진 프레임" 폭(px). 카드 전체 폭은 내부 패딩을 더한 값.
# - TITLE_Y_PC: 타이틀 상단이 위치할 목표 (창 높이 대비 비율 0~1)
# - BADGE_CY_PC: 두 카드의 배지 중심을 맞출 세로 위치 (창 높이 대비 비율 0~1)
_LAYOUT_FHD = {
    "PHOTO_W_MODE": "fixed", # 사진 폭 모드. 사용처: _relayout_all()의 mode 분기('fixed'|'auto')
    "PHOTO_W_34": 252,        # 3×4 사진 프레임 폭(px). 사용처: _relayout_all() w_34
    "PHOTO_W_3545": 294,      # 3.5×4.5 사진 프레임 폭(px). 사용처: _relayout_all() w_3545
    "TITLE_Y_PC": 0.15,       # 타이틀 상단 기준선(화면 비율 0~1). 사용처: _relayout_all() y_title_top_target
    "BADGE_CY_PC": 0.50,      # 배지 중심선(화면 비율 0~1). 사용처: _relayout_all() y_badge_center_tgt
}

def _layout_tokens() -> dict:
    """스케일(3:4:6) 반영된 레이아웃 토큰 반환. 픽셀 토큰은 3의 배수로 스냅."""
    app = QApplication.instance()
    TOK = (app.property("TYPO_TOKENS") or {}) if app else {}
    scale = float(TOK.get("scale", 1.0)) if isinstance(TOK, dict) else 1.0
    out = dict(_LAYOUT_FHD)
    # 픽셀 토큰: 스케일×스냅
    out["PHOTO_W_34"]   = _scale_val(int(out.get("PHOTO_W_34", 168)))
    out["PHOTO_W_3545"] = _scale_val(int(out.get("PHOTO_W_3545", 198)))
    return out

# ── Palette helpers (themes.py policy) ─────────────────────────
def _palette() -> dict:
    app = QApplication.instance()
    return (app.property("THEME_COLORS") or {}) if app else {}

def _primary_qcolor() -> QColor:
    col = _palette().get("primary", "#FFA9A9")
    return QColor(col)

def _primary_hex() -> str:
    return _primary_qcolor().name()

def _primary_rgba(a: float) -> str:
    c = _primary_qcolor()
    return f"rgba({c.red()},{c.green()},{c.blue()},{a})"


def _normalize_ratio(w: float, h: float) -> Tuple[int, int, float]:
    """3.5:4.5 → 7:9 처럼 정수 기약비 + float aspect 반환"""
    iw = int(round(w * 2))  # .5 대응(예: 3.5→7)
    ih = int(round(h * 2))
    g = gcd(iw, ih) or 1
    iw //= g; ih //= g
    return iw, ih, iw / ih


class RatioFrame(QFrame):
    def __init__(self, ratio_w: float, ratio_h: float, theme, parent: QWidget | None = None):
        super().__init__(parent)
        self.rw, self.rh = float(ratio_w), float(ratio_h)
        self.setObjectName("PhotoBox")
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self._fixed_w = 160
        self.setStyleSheet(
            f"""
            QFrame#PhotoBox {{
               background: {_primary_rgba(0.06)};
                border: {_border_tokens().get("FRAME_BORDER", 3)}px solid {_primary_hex()};
                border-radius: {_border_tokens().get("FRAME_RADIUS", 6)}px;
            }}
            """
        )
        self._apply_size()
        # 이미지 표시용 라벨(프레임 전체 채움)
        self._img = QLabel(self)
        self._img.setScaledContents(True)
        self._img.setAlignment(Qt.AlignCenter)
        self._img.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._img.setStyleSheet("background: transparent;")
        self._layout_image()

    def set_image_path(self, path: str):
        try:
            if path and os.path.exists(path):
                self._img.setPixmap(QPixmap(path))
        except Exception:
            pass

    def setFixedContentWidth(self, w: int):
        self._fixed_w = max(60, int(w))
        self._apply_size()

    def _apply_size(self):
        h = int(self._fixed_w * (self.rh / self.rw))
        self.setFixedSize(self._fixed_w, h)
        self._layout_image()

    # 프레임 테두리를 가리지 않게 이미지 영역을 안쪽으로 인셋
    def _layout_image(self) -> None:
        try:
            b = int(_border_tokens().get("FRAME_BORDER", 3))
            inset = max(0, b)
            self._img.setGeometry(inset, inset, max(0, self.width() - 2*inset), max(0, self.height() - 2*inset))
        except Exception:
            pass


class SizeCard(QWidget):
    def __init__(
        self,
        key: str,
        ratio_w: float,
        ratio_h: float,
        badge_text: str,
        desc_lines: List[str],
        theme,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self.key = key
        self.theme = theme
        self.rw, self.rh = ratio_w, ratio_h
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setObjectName("SizeCard")
        self.setStyleSheet(
            f"""
            QWidget#SizeCard {{ background: transparent; border: none; border-radius: {_border_tokens().get("CARD_RADIUS", 9)}px; }}
            QWidget#SizeCard[active="true"] {{ background: {_primary_rgba(0.18)}; }}
            QLabel[role="badge"] {{
                background: {_primary_hex()}; color: #FFFFFF;
                border-radius: {_border_tokens().get("BADGE_RADIUS", 15)}px; padding: {_space_tokens().get("BADGE_PAD_V", 9)}px {_space_tokens().get("BADGE_PAD_H", 15)}px; font-weight: 700;
            }}
            QLabel[role="desc"] {{ color: {_primary_hex()}; background: transparent; }}
            """
        )

        self.v = QVBoxLayout(self)
        pad = _space_tokens().get("CARD_PAD", 12)
        self.v.setContentsMargins(pad, pad, pad, pad)
        self.v.setSpacing(_space_tokens().get("CARD_PAD", 12))

        self.spacer_top = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.v.addItem(self.spacer_top)

        self.photo = RatioFrame(ratio_w, ratio_h, theme, self)
        self.v.addWidget(self.photo, 0, Qt.AlignHCenter)

        # 아이콘 로드: app/assets/icons/3040.png, 3545.png
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../app
            icons_dir = os.path.join(base_dir, "assets", "icons")
            fname = "3040" if key == "ID_30x40" else "3545"
            candidates = [f"{fname}.png", f"{fname}png"]
            img_path = None
            for c in candidates:
                p = os.path.join(icons_dir, c)
                if os.path.exists(p):
                    img_path = p; break
            if img_path:
                self.photo.set_image_path(img_path)
        except Exception:
            pass

        self.badge = QLabel(badge_text, self)
        self.badge.setProperty("role", "badge")
        self.badge.setAlignment(Qt.AlignCenter)
        self.badge.setFont(theme.body_font(_font_tokens().get("BADGE_FS", 15)))
        self.v.addWidget(self.badge, 0, Qt.AlignHCenter)

        self.desc = QLabel("\n".join(desc_lines), self)
        self.desc.setProperty("role", "desc")
        self.desc.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        self.desc.setFont(theme.body_font(_font_tokens().get("DESC_FS", 15)))
        self.v.addWidget(self.desc)

        self.v.addStretch(1)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Preferred)

    def set_photo_width(self, px: int):
        self.photo.setFixedContentWidth(px)
        self.setFixedWidth(px + self.v.contentsMargins().left() + self.v.contentsMargins().right())

    def set_active(self, on: bool):
        self.setProperty("active", "true" if on else "false")
        self.style().unpolish(self); self.style().polish(self); self.update()

    def set_top_space(self, h: int):
        self.spacer_top.changeSize(0, max(0, int(h)), QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.layout().invalidate(); self.layout().activate()

    def mousePressEvent(self, e):
        p = self.parent()
        while p and not hasattr(p, "on_card_clicked"):
            p = p.parent()
        if p:
            p.on_card_clicked(self.key)
        super().mousePressEvent(e)


class SizeSelectPage(BasePage):
    """3단계: 사이즈 선택 — **선택값을 session에 일관 저장**(photo_mm/ratio/aspect/size_key/ratio_rev)."""
    def __init__(self, theme, session: dict, parent: Optional[QWidget] = None) -> None:
        try:
            _flow = (getattr(SETTINGS, "data", {}) or {}).get("flow", {}) or {}
            _steps = list(_flow.get("steps") or [])
        except Exception:
            _steps = []
        if not _steps:
            _steps = ["INPUT","SIZE","CAPTURE","PICK","PREVIEW","EMAIL","ENHANCE"]
        super().__init__(theme, steps=_steps, active_index=1, parent=parent)
        self.session = session
        self.selected_key: Optional[str] = None

        self.center = QWidget(self)
        self.cv = QVBoxLayout(self.center)
        self.cv.setContentsMargins(_space_tokens().get("PAD_H", 39), _space_tokens().get("PAD_V", 24), _space_tokens().get("PAD_H", 39), _space_tokens().get("PAD_V", 24))
        self.cv.setSpacing(0)

        self.title = QLabel("원하시는 사이즈를 선택해주세요", self.center)
        self.title.setAlignment(Qt.AlignHCenter)
        self.title.setFont(theme.heading_font(_font_tokens().get("TITLE_FS", 21)))
        self.title.setStyleSheet(f"color:{_primary_hex()};")

        self.sp_top = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.sp_mid = QSpacerItem(0, 0, QSizePolicy.Minimum, QSizePolicy.Fixed)

        self.row = QHBoxLayout()
        self.row.setSpacing(_space_tokens().get("ROW_GAP", 72))
        self.row.addStretch(1)

        self.card_34 = SizeCard("ID_30x40", 3, 4, "3 × 4 cm",
                                ["반명함판", "이력서", "자격증"], theme, self.center)
        self.card_3545 = SizeCard("ID_35x45", 3.5, 4.5, "3.5 × 4.5 cm",
                                  ["주민등록증", "여권", "운전면허"], theme, self.center)

        self.row.addWidget(self.card_34)
        self.row.addWidget(self.card_3545)
        self.row.addStretch(1)

        self.cv.addItem(self.sp_top)
        self.cv.addWidget(self.title)
        self.cv.addItem(self.sp_mid)
        self.cv.addLayout(self.row)
        self.cv.addStretch(1)

        self.setCentralWidget(self.center)
        self.set_next_enabled(False)

        QTimer.singleShot(0, self._relayout_all)

    def showEvent(self, e):
        super().showEvent(e)
        # 초기 상태: Prev 활성, Next 비활성, 선택 해제
        self.selected_key = None
        self.card_34.set_active(False)
        self.card_3545.set_active(False)
        self.set_prev_mode("enabled")
        self.set_next_mode("disabled")
        self.set_next_enabled(False)

    # ---- 핵심: 세션에 값 저장(일관 키)
    def _commit_selection(self, ratio_str: str):
        """세션에는 오직 ratio(str)만 저장: '3040' | '3545'"""
        self.session["ratio"] = ratio_str

    # 카드 클릭: 세션 저장 + NEXT 활성
    def on_card_clicked(self, key: str):
        self.selected_key = key
        self.card_34.set_active(key == "ID_30x40")
        self.card_3545.set_active(key == "ID_35x45")

        if key == "ID_30x40":
            self._commit_selection("3040")
        else:
            self._commit_selection("3545")

        self.set_next_enabled(True)
        self.set_next_mode("lit")

    def selected_size_key(self) -> Optional[str]:
        return self.selected_key

    # 진입 시 이전 선택 복구(있다면)
    def _restore_from_session(self):
        r = str(self.session.get("ratio", "")).strip()
        if r == "3040":
            self.selected_key = "ID_30x40"
            self.card_34.set_active(True); self.card_3545.set_active(False)
            # 정책상 진입 시 자동 활성화는 하지 않음
        elif r == "3545":
            self.selected_key = "ID_35x45"
            self.card_34.set_active(False); self.card_3545.set_active(True)
            # 정책상 진입 시 자동 활성화는 하지 않음
        else:
            self.selected_key = None
            self.card_34.set_active(False); self.card_3545.set_active(False)
        # Next는 showEvent에서 비활성 처리

    def on_before_prev(self, session):
        """이전으로 갈 때: UI 리셋 + ratio 기본값 복원."""
        self.selected_key = None
        self.card_34.set_active(False)
        self.card_3545.set_active(False)
        self.set_next_enabled(False)
        self.set_next_mode("disabled")
        try:
            session["ratio"] = "3040"
        except Exception:
            pass
        return True

    def on_before_next(self, session):
        """다음으로 갈 때: 선택된 ratio를 전역 세션에 커밋. 미선택이면 취소(False)."""
        if self.selected_key == "ID_30x40":
            session["ratio"] = "3040"; return True
        if self.selected_key == "ID_35x45":
            session["ratio"] = "3545"; return True
        return False

    def _relayout_all(self):
        W = self.center.width()
        H = self.center.height()
        lt = _layout_tokens()

        # (1) 타이틀 위치 기준선 — 상단 여백 스페이서로 맞춤
        title_h = self.title.sizeHint().height()
        y_title_top_target = int(H * float(lt.get("TITLE_Y_PC", 0.20)))
        self.sp_top.changeSize(0, max(0, y_title_top_target - title_h // 2), QSizePolicy.Minimum, QSizePolicy.Fixed)

        # (2) 카드 사진 폭 — 고정/자동 모드
        mode = str(lt.get("PHOTO_W_MODE", "fixed")).lower()
        if mode == "fixed":
            w_34   = int(lt.get("PHOTO_W_34", 168))
            w_3545 = int(lt.get("PHOTO_W_3545", 198))
        else:
            spacing = self.row.spacing()
            extra_each = _space_tokens().get("EXTRA_EACH", 24)
            side_pad = _space_tokens().get("PAD_H", 39)
            units_total = 3.0 + 3.5
            max_for_photos = max(120, W - spacing - side_pad - extra_each * 2)
            px_per_unit = max(30.0, max_for_photos / units_total)
            w_34   = int(round(3.0 * px_per_unit))
            w_3545 = int(round(3.5 * px_per_unit))

        self.card_34.set_photo_width(w_34)
        self.card_3545.set_photo_width(w_3545)

        # (3) 배지 중심선 기준 정렬 — 각 카드 상단 스페이서로 미세 조정
        y_badge_center_tgt = int(H * float(lt.get("BADGE_CY_PC", 0.60)))
        self.cv.invalidate(); self.cv.activate()

        b1_top = self.card_34.badge.mapTo(self.center, QPoint(0, 0)).y()
        b2_top = self.card_3545.badge.mapTo(self.center, QPoint(0, 0)).y()
        b1_cy  = b1_top + self.card_34.badge.height() // 2
        b2_cy  = b2_top + self.card_3545.badge.height() // 2

        self.card_34.set_top_space(self.card_34.spacer_top.geometry().height() + (y_badge_center_tgt - b1_cy))
        self.card_3545.set_top_space(self.card_3545.spacer_top.geometry().height() + (y_badge_center_tgt - b2_cy))

        self.cv.invalidate(); self.cv.activate()

        b1_top = self.card_34.badge.mapTo(self.center, QPoint(0, 0)).y()
        b2_top = self.card_3545.badge.mapTo(self.center, QPoint(0, 0)).y()
        b1_cy  = b1_top + self.card_34.badge.height() // 2
        b2_cy  = b2_top + self.card_3545.badge.height() // 2

        self.card_34.set_top_space(self.card_34.spacer_top.geometry().height() + (y_badge_center_tgt - b1_cy))
        self.card_3545.set_top_space(self.card_3545.spacer_top.geometry().height() + (y_badge_center_tgt - b2_cy))

        self.cv.invalidate(); self.cv.activate()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        QTimer.singleShot(0, self._relayout_all)

