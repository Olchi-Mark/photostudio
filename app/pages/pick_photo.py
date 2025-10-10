# -*- coding: utf-8 -*-
from __future__ import annotations

"""
PickPhotoPage — 썸네일 이미지 미리보기 + 선택 → origin 저장 + 세션 정리
- 경로 일원화: C:\PhotoBox
- 세션['captures']에 thumb_01~thumb_04.jpg가 온다고 가정. session['captures_dir']가 있으면 우선.
- 썸네일은 실제 이미지를 로드하여 2×2 그리드에 표시.
- 선택 시 Next 활성화, 원본(raw)에서 C:\PhotoBox\origin_photo.jpg로 복사.
- Next 후에도 captures/raw_captures는 비우지 않는다.
"""

from typing import Optional, List
import os, shutil

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QGridLayout, QFrame, QSizePolicy
)

from app.ui.base_page import BasePage
from app.pages.setting import SETTINGS

# ───────────── 토큰 상수(FHD 기준)
TITLE_FS_BASE = 30
THUMB_H_BASE = 504
THUMB_W_3040_BASE = 378
THUMB_W_3545_BASE = 392
BORDER_W_BASE = 2
GRID_GAP_BASE = 30
HINT_GAP_TOP_BASE = 39
HINT_GAP_BOTTOM_BASE = 60
HINT_FS_BASE = 45

PHOTOBOX_ROOT = r"C:\PhotoBox"


class PickPhotoPage(BasePage):
    def __init__(self, theme, session: dict, parent: Optional[QWidget] = None):
        try:
            _flow = (getattr(SETTINGS, "data", {}) or {}).get("flow", {}) or {}
            _steps = list(_flow.get("steps") or [])
        except Exception:
            _steps = []
        if not _steps:
            _steps = ["INPUT","SIZE","CAPTURE","PICK","PREVIEW","EMAIL","ENHANCE"]
        super().__init__(theme, _steps, active_index=3, parent=parent)
        self.session = session or {}
        self.selected_idx: int | None = None

        # ── 토큰 계산
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        _tok = (app.property("TYPO_TOKENS") or {}) if app else {}
        try:
            scale = float(_tok.get("scale", getattr(self.theme, "scale", 1.0) or 1.0))
        except Exception:
            scale = getattr(self.theme, "scale", 1.0) or 1.0

        def snap3(px: int) -> int:
            return px if px in (1, 2) else px - (px % 3)

        primary = None
        try:
            c = (getattr(self.theme, "colors", {}) or {}).get("primary")
            primary = c if isinstance(c, QColor) else QColor(c) if isinstance(c, str) else None
        except Exception:
            primary = None
        if primary is None:
            pal = (app.property("THEME_COLORS") or {}) if app else {}
            v = pal.get("primary")
            primary = v if isinstance(v, QColor) else QColor(v) if isinstance(v, str) else QColor("#0B3D91")

        self.TOK = {
            "scale": scale,
            "gap": snap3(int(GRID_GAP_BASE * scale)),
            "pad": snap3(int(18 * scale)),
            "thumb_h": snap3(int(THUMB_H_BASE * scale)),
            "thumb_w_3040": snap3(int(THUMB_W_3040_BASE * scale)),
            "thumb_w_3545": snap3(int(THUMB_W_3545_BASE * scale)),
            "radius": 0,
            "hint_fs": snap3(int(HINT_FS_BASE * scale)),
            "title_fs": snap3(int(TITLE_FS_BASE * scale)),
            "hint_gap_top": snap3(int(HINT_GAP_TOP_BASE * scale)),
            "hint_gap_bottom": snap3(int(HINT_GAP_BOTTOM_BASE * scale)),
            "border": max(1, int(round(BORDER_W_BASE * scale))),
        }
        self.COL = {"primary": primary, "primary_str": primary.name()}

        # ── UI
        root = QWidget(self)
        self.setCentralWidget(
            root,
            margin=(self.TOK["pad"], self.TOK["pad"], self.TOK["pad"], self.TOK["pad"]),
            spacing=self.TOK["gap"],
            max_width=int(900 * self.TOK["scale"])
        )
        v = QVBoxLayout(root); v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        self._hint_spacer_top = QWidget(root); v.addWidget(self._hint_spacer_top, 0)
        self.hint = QLabel("원하시는 사진 한 장을 선택해 주세요", root)
        self.hint.setObjectName("hint"); self.hint.setAlignment(Qt.AlignCenter)
        self.hint.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        v.addWidget(self.hint, 0)
        self._hint_spacer_bottom = QWidget(root); v.addWidget(self._hint_spacer_bottom, 0)

        grid = QGridLayout(); grid.setContentsMargins(0,0,0,0)
        grid.setHorizontalSpacing(self.TOK["gap"]); grid.setVerticalSpacing(self.TOK["gap"])
        grid.setAlignment(Qt.AlignHCenter | Qt.AlignTop)
        v.addLayout(grid)

        # 썸네일 4개
        self.thumbs: List[QFrame] = []
        self.thumb_labels: List[QLabel] = []
        for i in range(4):
            f = QFrame(root); f.setObjectName("thumb"); f.setCursor(Qt.PointingHandCursor)
            fl = QVBoxLayout(f); fl.setContentsMargins(0,0,0,0); fl.setSpacing(0)
            img = QLabel(f); img.setObjectName("thumbImg"); img.setAlignment(Qt.AlignCenter)
            fl.addWidget(img)
            # 클릭
            def _mk_press(idx: int):
                def _on_press(event): self._on_thumb_clicked(idx)
                return _on_press
            f.mousePressEvent = _mk_press(i)  # type: ignore
            grid.addWidget(f, i // 2, i % 2)
            self.thumbs.append(f); self.thumb_labels.append(img)

        self._rebuild_qss(); self._apply_runtime_tokens()
        self._apply_thumb_sizes()

        self.set_prev_enabled(True)
        self.set_next_enabled(False)
        self.set_next_mode(1)

        # 초기 썸네일 로드
        self._reload_captures()

    # ── 스타일
    def _rebuild_qss(self) -> None:
        c = self.COL["primary_str"]; sel = max(1, int(self.TOK['border']) * 2)
        self._qss = f"""
        QLabel#hint {{
            color: {c}; font-size: {self.TOK['hint_fs']}px; font-weight: 700;
        }}
        QFrame#thumb {{
            background: rgba(0,0,0,0);
            border: {self.TOK['border']}px solid {c};
            border-radius: {self.TOK['radius']}px;
        }}
        QFrame#thumb[selected="true"] {{
            border-width: {sel}px;
        }}
        QLabel#thumbImg {{
            background: #F0F0F0;
        }}
        """

    def _apply_runtime_tokens(self) -> None:
        self.content.setStyleSheet(self._qss)
        self.hint.setFont(self.theme.heading_font(self.TOK['hint_fs']))
        self._hint_spacer_top.setFixedHeight(self.TOK['hint_gap_top'])
        self._hint_spacer_bottom.setFixedHeight(self.TOK['hint_gap_bottom'])

    def _apply_thumb_sizes(self) -> None:
        w = self.TOK['thumb_w_3040'] if str(self.session.get("ratio","3040")) == "3040" else self.TOK['thumb_w_3545']
        h = self.TOK['thumb_h']
        for f in self.thumbs:
            f.setFixedSize(w, h)

    # ── 데이터 로드
    def _reload_captures(self) -> None:
        caps = self.session.get("captures")
        self.captures: List[str] = list(caps) if isinstance(caps, list) else []
        while len(self.captures) < 4:
            self.captures.append(f"thumb_{len(self.captures)+1:02d}.jpg")
        raws = self.session.get("raw_captures")
        self.raw_names: List[str] = list(raws) if isinstance(raws, list) and raws else [f"raw_{i:02d}.jpg" for i in range(1,5)]

        cap_dir = self.session.get("captures_dir") or os.path.join(PHOTOBOX_ROOT, "cap")
        for i, (f, lab) in enumerate(zip(self.thumbs, self.thumb_labels)):
            path = self._resolve_path(cap_dir, self.captures[i])
            self._set_thumb_pix(lab, path)

    @staticmethod
    def _resolve_path(base: str, name_or_path: str) -> str:
        p = str(name_or_path or "").strip()
        return p if os.path.isabs(p) else os.path.join(base, p)

    def _set_thumb_pix(self, label: QLabel, path: str) -> None:
        pm = QPixmap(path) if os.path.isfile(path) else QPixmap()
        if not pm.isNull():
            # 라벨 크기에 맞춰 보존 비율 스케일
            sz = label.size() if label.size().width() and label.size().height() else QSize(200, 200)
            pix = pm.scaled(sz, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            label.setPixmap(pix)
        else:
            label.setPixmap(QPixmap())  # 회색 배경 + 빈 이미지

    # ── 상호작용
    def _on_thumb_clicked(self, idx: int) -> None:
        self.selected_idx = idx
        for i, f in enumerate(self.thumbs):
            f.setProperty("selected", "true" if i == idx else "false")
            f.style().unpolish(f); f.style().polish(f)
        self.set_next_enabled(True); self.set_next_mode(2)

        # 선택 메타 저장
        try:
            raws = self.raw_names if isinstance(self.raw_names, list) else [f"raw_{i:02d}.jpg" for i in range(1,5)]
            self.session["selected_index"] = idx
            self.session["selected_capture"] = self.captures[idx]
            self.session["selected_raw_name"] = raws[idx] if idx < len(raws) else raws[0]
            self.session["selected_origin_path"] = os.path.join(PHOTOBOX_ROOT, "origin_photo.jpg")
        except Exception:
            pass

    def reset_selection(self) -> None:
        self.selected_idx = None
        for f in self.thumbs:
            f.setProperty("selected", "false")
            f.style().unpolish(f); f.style().polish(f)
        self.set_next_enabled(False); self.set_next_mode(1)

    # ── 네비 훅
    def before_enter(self, session: dict) -> bool:
        self.session = session or {}
        self.reset_selection()
        self._apply_thumb_sizes()
        self._reload_captures()
        return True

    def before_leave(self, session: dict) -> bool:
        return True

    # Next 직전: 선택 원본을 origin_photo.jpg로 복사하고 임시 리스트 정리
    def on_before_next(self, session: dict) -> bool:
        if self.selected_idx is None:
            return False
        try:
            raw_name = session.get("selected_raw_name") or (
                (session.get("raw_captures") or [f"raw_{i:02d}.jpg" for i in range(1,5)])[self.selected_idx]
            )
            raw_dir = session.get("raw_dir") or os.path.join(PHOTOBOX_ROOT, "raw")
            src = os.path.join(raw_dir, raw_name)
            dst_dir = PHOTOBOX_ROOT
            os.makedirs(dst_dir, exist_ok=True)
            dst = os.path.join(dst_dir, "origin_photo.jpg")
            if os.path.exists(src):
                shutil.copyfile(src, dst)
            session["selected_origin_path"] = dst
            session["selected_raw_name"] = raw_name
            # 임시 리스트 정리
            # keep captures
            # keep raw_captures
            return True
        except Exception:
            return False

    # 리사이즈 시 썸네일 재스케일
    def resizeEvent(self, e):
        super().resizeEvent(e)
        for lab, cap in zip(self.thumb_labels, self.captures):
            base = self.session.get("captures_dir") or os.path.join(PHOTOBOX_ROOT, "cap")
            self._set_thumb_pix(lab, self._resolve_path(base, cap))

    def sizeHint(self) -> QSize:
        s = float(self.TOK.get("scale", 1.0)) if self.TOK else 1.0
        return QSize(int(900 * s), int(1200 * s))
