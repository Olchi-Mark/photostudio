# app/pages/setting.py
# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from copy import deepcopy
from typing import Dict, Any, Optional

from PySide6.QtCore import Qt, QRect, QPoint, Signal, QObject
from PySide6.QtWidgets import (
    QWidget, QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QGridLayout,
    QListWidget, QListWidgetItem, QStackedWidget, QLabel, QLineEdit, QTextEdit,
    QSpinBox, QCheckBox, QPushButton, QFileDialog, QGroupBox,
    QAbstractSpinBox, QScrollArea, QFrame, QMessageBox, QColorDialog, QSizePolicy
)
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QColor

# ── 설정 로더/브로드캐스트 유틸 ──
from app.config.loader import (
    config_load_defaults,
    config_ensure_settings_file,
    config_deep_merge,
    config_save_settings_atomic,
    config_apply_and_broadcast,
)

# ── 브로드캐스트 버스 + 프록시 ──
class _SettingsBus(QObject):
    changed = Signal(dict)
settings_bus = _SettingsBus()

class _SettingsProxy:
    def __init__(self) -> None:
        self.data: Dict[str, Any] = {}
    def load(self, effective: Dict[str, Any]) -> None:
        self.data = effective or {}
SETTINGS = _SettingsProxy()
settings_bus.changed.connect(SETTINGS.load)

# 최초 로드
try:
    _defaults = config_load_defaults()
    _settings = config_ensure_settings_file(_defaults)
    _effective = config_deep_merge(_defaults, _settings)
    config_apply_and_broadcast(_effective)
except Exception:
    pass

# ── UI 기본값(FHD 기준, 3의 배수 스냅) ──
DEFAULT_UI = {
    "nav_width": 162,
    "nav_font_px": 21,
    "label_font_px": 18,
    "input_font_px": 18,
    "group_font_px": 24,
    "panel_radius": 3,
    "item_radius": 6,
    "control_radius": 6,
    "button_radius": 6,
    "control_h": 54,
    "panel_height_ratio": 0.55,
}

def _tokens_colors():
    app = QApplication.instance()
    TOK = (app.property("TYPO_TOKENS") or {}) if app else {}
    COL = (app.property("THEME_COLORS") or {}) if app else {}
    return TOK, COL

def _scale_snap3(v_fhd: int, scale: float) -> int:
    val = int(v_fhd * scale)
    return (val // 3) * 3

# ─────────────────────────────────────────────
#  설정 오버레이
# ─────────────────────────────────────────────
class SettingDialog(QDialog):
    def __init__(self, parent: Optional[QWidget] = None, theme=None, ui_cfg: Optional[Dict[str, Any]] = None):
        super().__init__(parent)
        self.setObjectName("SettingsOverlay")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.Dialog)
        self.setModal(True)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

        TOK, COL = _tokens_colors()
        borders = TOK.get("borders", {})
        spacing = TOK.get("spacing", {})
        scale   = float(TOK.get("scale", 1.0) or 1.0)

        # UI 파라미터
        self.ui = {**DEFAULT_UI, **(ui_cfg or {})}
        nav_w     = _scale_snap3(self.ui["nav_width"],      scale)
        nav_px    = _scale_snap3(self.ui["nav_font_px"],    scale)
        label_px  = _scale_snap3(self.ui["label_font_px"],  scale)
        input_px  = _scale_snap3(self.ui["input_font_px"],  scale)
        group_px  = _scale_snap3(self.ui["group_font_px"],  scale)
        ctrl_h    = _scale_snap3(self.ui["control_h"],      scale)
        panel_r   = _scale_snap3(self.ui["panel_radius"],   scale)
        item_r    = _scale_snap3(self.ui["item_radius"],    scale)
        ctrl_r    = _scale_snap3(self.ui["control_radius"], scale)
        btn_r     = _scale_snap3(self.ui["button_radius"],  scale)

        gap   = int(spacing.get("gap", 12))
        pad_v = int(spacing.get("pad_v", 12))
        pad_h = int(spacing.get("pad_h", 12))
        hair  = int(borders.get("hairline", 1))
        thin  = int(borders.get("thin", 2))

        # 루트 레이아웃
        root = QVBoxLayout(self); root.setContentsMargins(0, 0, 0, 0); root.setSpacing(0)
        self.scrim = QWidget(self); self.scrim.setObjectName("Scrim")
        self.scrim.setStyleSheet("#Scrim{background:rgba(0,0,0,0.36);}")
        root.addWidget(self.scrim)

        self.panel = QWidget(self); self.panel.setObjectName("Panel")
        css = f"""
            #Panel{{background:{COL.get('card','#FFFFFF')}; border:{hair}px solid {COL.get('border','#E0E0E0')}; border-radius:{panel_r}px;}}
            QListWidget{{border:0; background:{COL.get('bg','#FFFFFF')}; padding:{pad_v}px; min-width:{nav_w}px;}}
            QListWidget::item{{padding:{pad_v}px {pad_h}px; margin:{int(gap/2)}px; border-radius:{item_r}px; font-size:{nav_px}px; color:{COL.get('text','#1A1A1A')};}}
            QListWidget::item:selected{{background:{COL.get('primary','#FFA9A9')}; color:#FFF;}}
            QLineEdit, QTextEdit, QSpinBox{{background:#FFF; color:{COL.get('text','#1A1A1A')};
                border:{thin}px solid {COL.get('primary','#FFA9A9')}; border-radius:{ctrl_r}px; padding:{pad_v}px {pad_h}px; font-size:{input_px}px;}}
            #Panel QLabel{{ font-size:{label_px}px; padding:3px 0; min-height:{max(ctrl_h, int(label_px*1.5))}px; color:{COL.get('text','#1A1A1A')}; }}
            #Panel QGroupBox{{ font-weight:600; border:{hair}px solid {COL.get('border','#E0E0E0')}; border-radius:3px; margin-top:18px; padding-top:6px; }}
            #Panel QGroupBox::title{{ font-size:{group_px}px; subcontrol-origin: margin; subcontrol-position: top left; left:9px; top:0px; padding:0 6px; background:{COL.get('card','#FFFFFF')}; }}
            QPushButton{{ border:{thin}px solid {COL.get('primary','#FFA9A9')}; border-radius:{btn_r}px; padding:12px 18px; font-size:{input_px}px; color:{COL.get('text','#1A1A1A')}; background:transparent; }}
            QPushButton[variant="primary"]{{ background:{COL.get('primary','#FFA9A9')}; color:#FFFFFF; }}
        """
        self.panel.setStyleSheet(css)

        pv = QVBoxLayout(self.panel); pv.setContentsMargins(18,18,18,18); pv.setSpacing(12)
        body = QHBoxLayout(); body.setSpacing(12)

        # 좌측 내비
        self.nav = QListWidget(self.panel)
        for name in ("프로그램 정보", "경로 & 저장", "색 / 테마", "정보 입력", "포토샵 보정", "이메일 설정"):
            QListWidgetItem(name, self.nav)
        self.nav.setCurrentRow(0)
        self.nav.setFixedWidth(nav_w)
        self.nav.setFocusPolicy(Qt.NoFocus)

        # 우측 스택
        self.stack = QStackedWidget(self.panel)
        self._build_pages()
        self.nav.currentRowChanged.connect(self.stack.setCurrentIndex)

        body.addWidget(self.nav, 0)
        body.addWidget(self.stack, 1)
        pv.addLayout(body, 1)

        # 푸터
        footer = QHBoxLayout(); footer.setSpacing(12); footer.addStretch(1)
        self.btnReset = QPushButton("초기화")
        self.btnSave  = QPushButton("저장"); self.btnSave.setProperty("variant", "primary")
        self.btnClose = QPushButton("닫기")
        footer.addWidget(self.btnReset); footer.addWidget(self.btnSave); footer.addWidget(self.btnClose)
        pv.addLayout(footer)

        self.btnReset.clicked.connect(self._on_reset)
        self.btnSave.clicked.connect(self._on_save)
        self.btnClose.clicked.connect(self.reject)

        self._apply_geometry()

    # ── 탭 빌드 ──
    def _build_pages(self):
        self.stack.addWidget(self._page_program_info())           # 0
        self.stack.addWidget(self._page_paths())                   # 1
        self.stack.addWidget(self._page_theme())                   # 2
        self.stack.addWidget(self._page_input())                   # 3
        self.stack.addWidget(self._wrap_scroll(self._page_ps_retouch()))  # 4
        self.stack.addWidget(self._wrap_scroll(self._page_email()))       # 5

    # ── 포토샵 보정(= AI 라벨 + 포토샵 설정 통합) ──
    def _page_ps_retouch(self) -> QWidget:
        ai = SETTINGS.data.get("ai", {})
        rows = ai.get("rows", [])
        ps  = SETTINGS.data.get("photoshop", {})

        w = QWidget()
        v = QVBoxLayout(w); v.setContentsMargins(12,12,18,18); v.setSpacing(18)
        ctrl_h = DEFAULT_UI["control_h"]

        # AI 라벨
        g_ai = QGroupBox("AI 라벨"); grid = QGridLayout(g_ai)
        grid.setHorizontalSpacing(12); grid.setVerticalSpacing(12)
        grid.addWidget(QLabel("행 이름"), 0, 0)
        grid.addWidget(QLabel("버튼1"),   0, 1)
        grid.addWidget(QLabel("버튼2"),   0, 2)
        grid.addWidget(QLabel("버튼3"),   0, 3)
        self.ai_rows = []
        for r in range(4):
            name  = rows[r]["name"] if r < len(rows) else f"Row {r+1}"
            comps = rows[r]["components"] if r < len(rows) else ["","",""]
            e_name = QLineEdit(name); e_name.setMinimumHeight(ctrl_h)
            c1 = QLineEdit(comps[0]); c1.setMinimumHeight(ctrl_h)
            c2 = QLineEdit(comps[1]); c2.setMinimumHeight(ctrl_h)
            c3 = QLineEdit(comps[2]); c3.setMinimumHeight(ctrl_h)
            grid.addWidget(e_name, r+1, 0); grid.addWidget(c1, r+1, 1)
            grid.addWidget(c2, r+1, 2);     grid.addWidget(c3, r+1, 3)
            self.ai_rows.append((e_name, c1, c2, c3))
        v.addWidget(g_ai)

        # 포토샵 보정
        g_ps = QGroupBox("포토샵 보정"); g = QGridLayout(g_ps)
        g.setHorizontalSpacing(12); g.setVerticalSpacing(12)
        for col in range(1, 5): g.setColumnStretch(col, 1)

        # Ratio [set] [action_3040] [action_3545]
        rt = ps.get("ratio", {})
        self.e_ratio_set  = QLineEdit(rt.get("set",""));          self.e_ratio_set.setMinimumHeight(ctrl_h)
        self.e_ratio_3040 = QLineEdit(rt.get("action_3040",""));  self.e_ratio_3040.setMinimumHeight(ctrl_h)
        self.e_ratio_3545 = QLineEdit(rt.get("action_3545",""));  self.e_ratio_3545.setMinimumHeight(ctrl_h)
        g.addWidget(QLabel("Ratio"), 0, 0, alignment=Qt.AlignRight)
        g.addWidget(self.e_ratio_set,  0, 1)
        g.addWidget(self.e_ratio_3040, 0, 2)
        g.addWidget(self.e_ratio_3545, 0, 3)

        # Liquify [set] [action_liquify]
        lq = ps.get("liquify", {})
        self.e_liq_set    = QLineEdit(lq.get("set",""));    self.e_liq_set.setMinimumHeight(ctrl_h)
        self.e_liq_action = QLineEdit(lq.get("action","")); self.e_liq_action.setMinimumHeight(ctrl_h)
        g.addWidget(QLabel("Liquify"), 1, 0, alignment=Qt.AlignRight)
        g.addWidget(self.e_liq_set,    1, 1)
        g.addWidget(self.e_liq_action, 1, 2, 1, 2)

        # Neural [set] [action_mode1] [action_mode2]
        nn = ps.get("neural", {})
        m1 = nn.get("mode1", {}); m2 = nn.get("mode2", {})
        self.e_nn_set        = QLineEdit(nn.get("set",""));       self.e_nn_set.setMinimumHeight(ctrl_h)
        self.e_nn_m1_action  = QLineEdit(m1.get("action",""));    self.e_nn_m1_action.setMinimumHeight(ctrl_h)
        self.e_nn_m2_action  = QLineEdit(m2.get("action",""));    self.e_nn_m2_action.setMinimumHeight(ctrl_h)
        g.addWidget(QLabel("Neural"), 2, 0, alignment=Qt.AlignRight)
        g.addWidget(self.e_nn_set,       2, 1)
        g.addWidget(self.e_nn_m1_action, 2, 2)
        g.addWidget(self.e_nn_m2_action, 2, 3)

        # Background [set] [action_bg1] [action_bg2] [action_bg3]
        bg   = ps.get("background", {})
        acts = (list(bg.get("actions", [])) + ["", "", ""])[:3]
        self.e_bg_set = QLineEdit(bg.get("set","")); self.e_bg_set.setMinimumHeight(ctrl_h)
        self.e_bg_a1  = QLineEdit(acts[0]);          self.e_bg_a1.setMinimumHeight(ctrl_h)
        self.e_bg_a2  = QLineEdit(acts[1]);          self.e_bg_a2.setMinimumHeight(ctrl_h)
        self.e_bg_a3  = QLineEdit(acts[2]);          self.e_bg_a3.setMinimumHeight(ctrl_h)
        g.addWidget(QLabel("Background"), 3, 0, alignment=Qt.AlignRight)
        g.addWidget(self.e_bg_set, 3, 1)
        g.addWidget(self.e_bg_a1, 3, 2)
        g.addWidget(self.e_bg_a2, 3, 3)
        g.addWidget(self.e_bg_a3, 3, 4)

        v.addWidget(g_ps)

        # 시간 설정
        pr = nn.get("progress", {})
        g_time = QGroupBox("시간 설정"); ft = QFormLayout(g_time)
        ft.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.s_nn_first_delay = QSpinBox(); self.s_nn_first_delay.setRange(0, 600000); self.s_nn_first_delay.setButtonSymbols(QAbstractSpinBox.NoButtons); self.s_nn_first_delay.setMinimumHeight(ctrl_h); self.s_nn_first_delay.setValue(int(pr.get("first_delay_ms", 7000)))
        self.s_nn_period      = QSpinBox(); self.s_nn_period.setRange(0, 600000);      self.s_nn_period.setButtonSymbols(QAbstractSpinBox.NoButtons);      self.s_nn_period.setMinimumHeight(ctrl_h);      self.s_nn_period.setValue(int(pr.get("period_ms", 1500)))
        self.s_nn_timeout     = QSpinBox(); self.s_nn_timeout.setRange(0, 3600000);    self.s_nn_timeout.setButtonSymbols(QAbstractSpinBox.NoButtons);     self.s_nn_timeout.setMinimumHeight(ctrl_h);     self.s_nn_timeout.setValue(int(pr.get("timeout_ms", 60000)))
        self.s_ps_pipe_delay  = QSpinBox(); self.s_ps_pipe_delay.setRange(0, 600000);  self.s_ps_pipe_delay.setButtonSymbols(QAbstractSpinBox.NoButtons);  self.s_ps_pipe_delay.setMinimumHeight(ctrl_h);  self.s_ps_pipe_delay.setValue(int(ps.get("pipeline_delay_ms", 2000)))
        ft.addRow("Neural 최초 지연(ms)", self.s_nn_first_delay)
        ft.addRow("Neural 주기(ms)",      self.s_nn_period)
        ft.addRow("Neural 타임아웃(ms)",  self.s_nn_timeout)
        ft.addRow("파이프라인 지연(ms)",  self.s_ps_pipe_delay)
        v.addWidget(g_time)

        v.addStretch(1)
        return w

    # ── 레이아웃 유틸 ──
    def _apply_geometry(self):
        TOK, _ = _tokens_colors()
        parent = self.parent()
        if parent:
            self.setGeometry(parent.geometry())
        else:
            self.setGeometry(QRect(0, 0, 1200, 800))

        # 스테이지 중앙 배치
        stage = None
        if parent is not None:
            stage = getattr(parent, "stage", None) or parent.findChild(QWidget, "Stage") or (parent.centralWidget() if hasattr(parent, "centralWidget") else None)
        canvas = QRect(self.rect()) if not stage else QRect(self.mapFromGlobal(stage.mapToGlobal(QPoint(0, 0))), stage.size())

        ratio = DEFAULT_UI["panel_height_ratio"]
        pw = (int(canvas.width() * 0.90) // 3) * 3
        base_h = int(TOK.get("req_h", 0) or canvas.height())
        ph = (int(min(base_h, canvas.height()) * ratio) // 3) * 3
        px = canvas.x() + (canvas.width() - pw)//2
        py = canvas.y() + (canvas.height() - ph)//2
        self.panel.setGeometry(QRect(px, py, pw, ph))
        self.panel.raise_()
        self.update()

    def _can_write_dir(self, path: str) -> bool:
        try:
            if not path: return False
            os.makedirs(path, exist_ok=True)
            probe = os.path.join(path, "~ps_wtest.tmp")
            with open(probe, "w", encoding="utf-8") as f: f.write("ok")
            os.remove(probe)
            return True
        except Exception:
            return False

    def _pick_root(self):
        base = (getattr(self, "e_root", None).text().strip() if getattr(self, "e_root", None) else "C:\\")
        path = QFileDialog.getExistingDirectory(self, "작업/산출물 루트 선택", base)
        if not path: return
        path = os.path.normpath(path)
        if not self._can_write_dir(path):
            QMessageBox.warning(self, "쓰기 권한 오류", f"선택한 폴더에 쓰기 권한이 없습니다.\n{path}")
            return
        self.e_root.setText(path)

    def _wrap_scroll(self, w: QWidget) -> QScrollArea:
        sa = QScrollArea(self.panel); sa.setWidgetResizable(True); sa.setFrameShape(QFrame.NoFrame); sa.setWidget(w); return sa

    def resizeEvent(self, e):
        super().resizeEvent(e); self._apply_geometry()

    # ── 색/테마: 경로&저장과 동일한 HBox 정책 적용 ──
    def _page_theme(self) -> QWidget:
        ui = SETTINGS.data.get("ui", {}); colors = dict(ui.get("colors", {}))
        primary0 = colors.get("primary", "#FFA9A9")

        w = QWidget(); f = QFormLayout(w)
        f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        f.setContentsMargins(12,12,12,12); f.setVerticalSpacing(12)

        ctrl_h = DEFAULT_UI["control_h"]

        container = QWidget()
        row = QHBoxLayout(container); row.setContentsMargins(0,0,0,0); row.setSpacing(12); row.setAlignment(Qt.AlignVCenter)

        self.e_primary = QLineEdit(self._norm_hex(primary0, "#FFA9A9")); self.e_primary.setMinimumHeight(ctrl_h); self.e_primary.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.btn_pick = QPushButton("색 선택…"); self.btn_pick.setMinimumHeight(ctrl_h)
        self.preview_sw = QLabel(); self.preview_sw.setFixedSize(ctrl_h, ctrl_h); self.preview_sw.setAlignment(Qt.AlignCenter)
        self._set_preview_color(self.e_primary.text())

        row.addWidget(self.e_primary, 1); row.addWidget(self.btn_pick, 0); row.addWidget(self.preview_sw, 0)
        f.addRow("Primary", container)

        self.btn_color_reset = QPushButton("색 설정 초기화"); self.btn_color_reset.setMinimumHeight(ctrl_h)
        f.addRow("", self.btn_color_reset)

        self.e_primary.textChanged.connect(lambda _: self._set_preview_color(self._norm_hex(self.e_primary.text(), "#FFA9A9")))
        def _pick():
            init = QColor(self._norm_hex(self.e_primary.text(), "#FFA9A9"))
            c = QColorDialog.getColor(init, self, "Primary 색 선택")
            if c.isValid(): self.e_primary.setText(c.name(QColor.HexRgb).upper())
        self.btn_pick.clicked.connect(_pick)
        self.btn_color_reset.clicked.connect(self._on_color_reset)
        return w

    # 색상 유틸
    def _norm_hex(self, s: str, fallback: str) -> str:
        s = (s or "").strip()
        if not s: return fallback
        if not s.startswith("#"): s = "#" + s
        if len(s) == 4: s = "#" + "".join(ch*2 for ch in s[1:])
        return s.upper() if len(s) == 7 else fallback

    def _derive_hover_active(self, primary_hex: str) -> tuple[str, str]:
        c = QColor(primary_hex); return c.lighter(105).name(QColor.HexRgb).upper(), c.darker(107).name(QColor.HexRgb).upper()

    def _set_preview_color(self, hexstr: str):
        self.preview_sw.setStyleSheet(f"background:{hexstr}; border:1px solid #E0E0E0; border-radius:6px;")

    def _on_color_reset(self):
        try:
            defaults = config_load_defaults()
            cols = dict(defaults.get("ui", {}).get("colors", {}))
            self.e_primary.setText(self._norm_hex(cols.get("primary", "#FFA9A9"), "#FFA9A9"))
        except Exception as e:
            QMessageBox.critical(self, "초기화 실패", f"색 설정을 초기화하지 못했습니다.\n{e}")

    # 프로그램 정보
    def _page_program_info(self) -> QWidget:
        d = SETTINGS.data.get("program_info", {})
        w = QWidget(); v = QVBoxLayout(w); v.setContentsMargins(12,12,12,12)
        title = QLabel(f"<h2>{d.get('name','')} <small style='color:#666'>v{d.get('version','')}</small></h2>")
        brand = QLabel(f"브랜드: {d.get('brand','')}")
        v.addWidget(title); v.addWidget(brand)
        v.addSpacing(12)
        v.addWidget(QLabel("업데이트 내역:"))
        log = QTextEdit(); log.setReadOnly(True)
        lines = []
        for item in d.get("changelog", []):
            lines.append(f"- {item.get('version','')} ({item.get('date','')})")
            for n in item.get("notes", []): lines.append(f"  · {n}")
        log.setPlainText("\n".join(lines))
        v.addWidget(log, 1)
        return w

    # 경로 & 저장
    def _page_paths(self) -> QWidget:
        d = SETTINGS.data
        w = QWidget(); f = QFormLayout(w); f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.e_root = QLineEdit(d.get("paths", {}).get("root", r"C:\PhotoBox")); self.e_root.setReadOnly(True)
        container = QWidget(); row = QHBoxLayout(container); row.setContentsMargins(0,0,0,0); row.setSpacing(12); row.addWidget(self.e_root, 1)
        f.addRow("작업/산출물 루트", container)

        self.s_retention = QSpinBox(); self.s_retention.setRange(1, 365)
        self.s_retention.setValue(int(d.get("retention", {}).get("days", 7)))
        self.s_retention.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.s_retention.setMinimumHeight(DEFAULT_UI["control_h"])
        f.addRow("보관 기간(일)", self.s_retention)
        return w

    # 정보 입력
    def _page_input(self) -> QWidget:
        d = SETTINGS.data.get("input", {})
        w = QWidget(); f = QFormLayout(w); f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter); f.setContentsMargins(12,12,12,12); f.setVerticalSpacing(12)
        def _lbl(text: str, top: bool = False) -> QLabel:
            lb = QLabel(text); lb.setAlignment(Qt.AlignRight | (Qt.AlignTop if top else Qt.AlignVCenter)); return lb
        self.t_top = QTextEdit(d.get("top_guide", "")); self.t_top.setMinimumHeight(108); self.t_top.document().setDocumentMargin(6)
        self.t_bottom = QTextEdit(d.get("bottom_guide", "")); self.t_bottom.setMinimumHeight(90); self.t_bottom.document().setDocumentMargin(6)
        f.addRow(_lbl("상단 안내문", top=True), self.t_top)
        f.addRow(_lbl("하단 안내문", top=True), self.t_bottom)
        return w

    # 이메일 설정
    def _page_email(self) -> QWidget:
        d = SETTINGS.data.get("email", {})
        w = QWidget(); w.setObjectName("EmailRoot"); v = QVBoxLayout(w); v.setContentsMargins(12,12,18,18); v.setSpacing(18)

        g_sender = QGroupBox("발신 공통") ; gf = QFormLayout(g_sender)
        gf.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter); gf.setContentsMargins(12,18,12,18); gf.setVerticalSpacing(12)
        self.e_from_name = QLineEdit(d.get("from_name", "")); self.e_from_addr = QLineEdit(d.get("from_address", ""))
        self.e_smtp_host = QLineEdit(d.get("smtp", {}).get("host", "")); self.s_smtp_port = QSpinBox(); self.s_smtp_port.setRange(1,65535); self.s_smtp_port.setValue(int(d.get("smtp", {}).get("port", 587)))
        self.chk_tls = QCheckBox("TLS 사용"); self.chk_tls.setChecked(bool(d.get("smtp", {}).get("tls", True)))
        self.e_user = QLineEdit(d.get("auth", {}).get("user", "")); self.e_pass = QLineEdit(d.get("auth", {}).get("pass", "")); self.e_pass.setEchoMode(QLineEdit.Password)
        for _w in (self.e_from_name, self.e_from_addr, self.e_smtp_host, self.s_smtp_port, self.e_user, self.e_pass): _w.setMinimumHeight(DEFAULT_UI["control_h"])
        self.s_smtp_port.setButtonSymbols(QAbstractSpinBox.NoButtons)
        gf.addRow("발신자 이름", self.e_from_name); gf.addRow("발신자 주소", self.e_from_addr)
        gf.addRow("SMTP 호스트", self.e_smtp_host); gf.addRow("SMTP 포트", self.s_smtp_port); gf.addRow("", self.chk_tls)
        gf.addRow("SMTP 계정", self.e_user); gf.addRow("SMTP 비번", self.e_pass)

        def role_box(title: str, role_key: str):
            box = QGroupBox(title); f = QFormLayout(box); f.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
            role = d.get(role_key, {}); e_to = QLineEdit(role.get("to", "")) if role_key != "customer" else None
            e_sub = QLineEdit(role.get("subject", "")); t_body = QTextEdit(role.get("body", "")); t_body.setMinimumHeight(108); t_body.document().setDocumentMargin(6)
            for _w in (e_to, e_sub):
                if _w is not None: _w.setMinimumHeight(DEFAULT_UI["control_h"])
            if e_to: f.addRow("수신자", e_to)
            f.addRow("제목", e_sub); f.addRow("본문", t_body)
            return box, (e_to, e_sub, t_body)

        self.role_widgets: Dict[str, tuple] = {}
        box_c, w_c = role_box("고객", "customer");         self.role_widgets["customer"] = w_c
        box_p, w_p = role_box("출력 담당자", "print_manager"); self.role_widgets["print_manager"] = w_p
        box_r, w_r = role_box("보정 담당자", "retouch_manager"); self.role_widgets["retouch_manager"] = w_r

        v.addWidget(g_sender); v.addWidget(box_c); v.addWidget(box_p); v.addWidget(box_r); v.addStretch(1)
        return w

    # 저장
    def _on_save(self):
        d = deepcopy(SETTINGS.data)

        # 경로/보관
        new_root = os.path.normpath(d.get("paths", {}).get("root", r"C:\PhotoBox"))
        if not self._can_write_dir(new_root):
            QMessageBox.warning(self, "쓰기 권한 오류", f"선택한 루트에 쓰기 권한이 없습니다.\n{new_root}")
            return
        d.setdefault("paths", {})["root"] = new_root
        d.setdefault("retention", {})["days"] = int(self.s_retention.value())

        # 안내
        d.setdefault("input", {})["top_guide"]    = self.t_top.toPlainText().strip()
        d.setdefault("input", {})["bottom_guide"] = self.t_bottom.toPlainText().strip()

        # AI 라벨
        d.setdefault("ai", {}).setdefault("rows", [])
        for idx, (n,c1,c2,c3) in enumerate(self.ai_rows):
            while len(d["ai"]["rows"]) <= idx:
                d["ai"]["rows"].append({"name":"","components":["","",""]})
            d["ai"]["rows"][idx]["name"] = n.text().strip() or d["ai"]["rows"][idx]["name"]
            d["ai"]["rows"][idx]["components"] = [c1.text().strip(), c2.text().strip(), c3.text().strip()]

        # 이메일
        d.setdefault("email", {})
        d["email"]["from_name"]    = self.e_from_name.text().strip()
        d["email"]["from_address"] = self.e_from_addr.text().strip()
        d.setdefault("email", {}).setdefault("smtp", {})
        d["email"]["smtp"]["host"] = self.e_smtp_host.text().strip()
        d["email"]["smtp"]["port"] = int(self.s_smtp_port.value())
        d["email"]["smtp"]["tls"]  = bool(self.chk_tls.isChecked())
        d.setdefault("email", {}).setdefault("auth", {})
        d["email"]["auth"]["user"] = self.e_user.text().strip()
        d["email"]["auth"]["pass"] = self.e_pass.text()
        for key, widgets in self.role_widgets.items():
            e_to, e_sub, t_body = widgets
            role = d.setdefault("email", {}).setdefault(key, {})
            if e_to is not None: role["to"] = e_to.text().strip()
            role["subject"] = e_sub.text().strip()
            role["body"]    = t_body.toPlainText()

        # 색상 저장(+hover/active 파생)
        d.setdefault("ui", {}).setdefault("colors", {})
        p_hex = self._norm_hex(getattr(self, "e_primary", QLineEdit("#FFA9A9")).text(), d["ui"]["colors"].get("primary", "#FFA9A9"))
        hov, act = self._derive_hover_active(p_hex)
        d["ui"]["colors"]["primary"] = p_hex
        d["ui"]["colors"]["primary_hover"]  = hov
        d["ui"]["colors"]["primary_active"] = act

        # Photoshop
        ps = d.setdefault("photoshop", {})
        ps.setdefault("ratio", {})["set"]          = self.e_ratio_set.text().strip()
        ps["ratio"]["action_3040"]                 = self.e_ratio_3040.text().strip()
        ps["ratio"]["action_3545"]                 = self.e_ratio_3545.text().strip()

        ps.setdefault("liquify", {})["set"]        = self.e_liq_set.text().strip()
        ps["liquify"]["action"]                    = self.e_liq_action.text().strip()

        ps.setdefault("neural", {})
        if self.e_nn_set.text().strip(): ps["neural"]["set"] = self.e_nn_set.text().strip()
        ps["neural"].setdefault("mode1", {})["action"] = self.e_nn_m1_action.text().strip()
        ps["neural"].setdefault("mode2", {})["action"] = self.e_nn_m2_action.text().strip()
        ps["neural"].setdefault("progress", {})
        ps["neural"]["progress"]["first_delay_ms"] = int(self.s_nn_first_delay.value())
        ps["neural"]["progress"]["period_ms"]      = int(self.s_nn_period.value())
        ps["neural"]["progress"]["timeout_ms"]     = int(self.s_nn_timeout.value())

        ps.setdefault("background", {})["set"]     = self.e_bg_set.text().strip()
        ps["background"]["actions"] = [a for a in (self.e_bg_a1.text().strip(), self.e_bg_a2.text().strip(), self.e_bg_a3.text().strip()) if a]
        ps["pipeline_delay_ms"] = int(self.s_ps_pipe_delay.value())

        try:
            config_save_settings_atomic(d)
            defaults = config_load_defaults()
            effective = config_deep_merge(defaults, d)
            config_apply_and_broadcast(effective)
            QMessageBox.information(self, "저장됨", "프로그램을 다시 시작해주세요")
            app = QApplication.instance()
            if app: app.quit()
        except Exception as e:
            QMessageBox.critical(self, "저장 실패", f"설정을 저장하지 못했습니다.\n{e}")

    # 초기화
    def _on_reset(self):
        try:
            defaults = config_load_defaults()
            config_save_settings_atomic(defaults)
            QMessageBox.information(self, "초기화 완료", "프로그램을 다시 시작해주세요")
            app = QApplication.instance()
            if app: app.quit()
        except Exception as e:
            QMessageBox.critical(self, "초기화 실패", f"초기화에 실패했습니다.\n{e}")

# ── Public API ──
def open_settings(parent: Optional[QWidget] = None, theme=None, ui_cfg: Optional[Dict[str, Any]] = None):
    old_parent_flag = None
    try:
        if parent is not None:
            old_parent_flag = parent.windowFlags()
            parent.setWindowFlag(Qt.WindowStaysOnTopHint, False)
            parent.show()
    except Exception:
        pass

    try:
        dlg = SettingDialog(parent=parent, theme=theme, ui_cfg=ui_cfg)
        dlg.exec()
    finally:
        if parent is not None and old_parent_flag is not None:
            try:
                parent.setWindowFlags(old_parent_flag)
                parent.show()
            except Exception:
                pass
