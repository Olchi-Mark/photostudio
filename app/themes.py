# app/themes.py
# -*- coding: utf-8 -*-
#─────────────────────────────────────────────
#  Theme 클래스 (팔레트/토큰 기반 QSS/폰트)
#  - 색상: qApp.property("THEME_COLORS") 역할 기반 팔레트만 사용
#  - 토큰: qApp.property("TYPO_TOKENS")의 borders/spacing/radii/scale/grid 사용
#  - 별칭(PINK/TEXT 등) 전면 제거
#─────────────────────────────────────────────
from __future__ import annotations
from typing import Dict, Any
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

#─────────────────────────────────────────────
#  Theme
#─────────────────────────────────────────────
# 역할: settings → 팔레트/타이포 토큰을 읽어 전역 QSS/폰트를 생성
# 변경로그:
# - v1.0: 역할 팔레트(THEME_COLORS) 도입, 색상 별칭 제거, QSS 전면 치환
class Theme:
    #─────────────────────────────────────────────
    #  생성자: 폰트 패밀리만 인자로 받고, 색/토큰은 qApp 프로퍼티에서 읽는다.
    #─────────────────────────────────────────────
    def __init__(self, font_info: Dict[str, Any]):
        # 폰트 패밀리(정책: 기본은 전부 S-Core Dream)
        self.body_family    = font_info.get("body_family") or "S-Core Dream"
        self.heading_family = font_info.get("heading_family") or self.body_family

        # 역할 팔레트 로드(필수)
        app = QApplication.instance()
        colors = (app.property("THEME_COLORS") or {}) if app else {}
        # 필수 키 검사(내부 디폴트 없음)
        required = (
            "bg", "card", "border",
            "text", "subtext",
            "primary", "primary_hover", "primary_active",
        )
        missing = [k for k in required if k not in colors]
        if missing:
            raise RuntimeError(f"THEME_COLORS missing keys: {missing}. Ensure defaults/settings are loaded before Theme().")
        self.colors: Dict[str, str] = colors

    #─────────────────────────────────────────────
    #  헤딩/본문 폰트 생성 (픽셀 단위 고정)
    #─────────────────────────────────────────────
    # 헤딩 폰트 생성
    def heading_font(self, size_px: int) -> QFont:
        f = QFont(self.heading_family)
        try:
            f.setFamilies([self.heading_family, "Noto Sans KR", "Malgun Gothic", "Segoe UI", "Arial"])
        except Exception:
            pass
        f.setKerning(True)
        f.setPixelSize(max(8, int(size_px)))
        f.setBold(True)
        f.setLetterSpacing(QFont.PercentageSpacing, 102)
        f.setHintingPreference(QFont.PreferFullHinting)
        f.setStyleStrategy(QFont.PreferAntialias | QFont.PreferQuality)
        return f

    # 본문 폰트 생성
    def body_font(self, size_px: int) -> QFont:
        f = QFont(self.body_family)
        try:
            f.setFamilies([self.body_family, "Noto Sans KR", "Malgun Gothic", "Segoe UI", "Arial"])
        except Exception:
            pass
        f.setKerning(True)
        f.setPixelSize(max(10, int(size_px)))
        f.setHintingPreference(QFont.PreferFullHinting)
        f.setStyleStrategy(QFont.PreferAntialias)
        return f

    #─────────────────────────────────────────────
    #  QSS 문자열 생성 (역할 팔레트 + 토큰)
    #─────────────────────────────────────────────
    def qss(self) -> str:
        app = QApplication.instance()
        tokens = (app.property("TYPO_TOKENS") or {}) if app else {}
        borders = tokens.get("borders", {})
        scale   = tokens.get("scale", 1.0)
        grid    = tokens.get("grid", 3)
        c       = self.colors

        # 스냅 유틸: grid 배수로 내림
        def _snap(v: float) -> int:
            if grid <= 1:
                return int(v)
            q = v / grid
            return int(q) * grid

        # 라운드/패딩 기본값(FHD 기준 → 스케일 후 내림 스냅)
        radius_px    = _snap(3 * scale)    # 고정: 3
        card_radius  = _snap(3 * scale)
        pad_v_px     = _snap(6 * scale)
        pad_h_px     = _snap(6 * scale)
        pad_btn_px   = _snap(6 * scale)
        cb_wh_px     = _snap(15 * scale)   # 체크박스 크기 15
        btn_radius   = _snap(6 * scale)    # 버튼 라운드 6

        # 보더 폭 토큰(예외 규칙은 스케일러에서 처리됨)
        b_hair = borders.get("hairline", 1)
        b_thin = borders.get("thin", 2)
        b_norm = borders.get("normal", 3)

        body_family_qss = ",".join([
            f"'{self.body_family}'",
            "'Noto Sans KR'",
            "'Malgun Gothic'",
            "'Segoe UI'",
            "'Arial'",
            "sans-serif",
        ])

        return f"""
        QWidget {{
            background:{c['bg']};
            color:{c['text']};
            font-family:{body_family_qss};
        }}

        /* 카드 */
        .card {{
            background:{c['card']};
            border:{b_hair}px solid {c['border']};
            border-radius:{card_radius}px;
        }}

        /* 캡션/서브텍스트 */
        QLabel[role="caption"] {{
            color:{c['subtext']};
        }}

        /* 폼 공통 */
        QLineEdit, QTextEdit {{
            background:#FFFFFF;
            border:{b_thin}px solid {c['primary']};
            border-radius:{radius_px}px;
            padding:{pad_v_px}px {pad_h_px}px;
            selection-background-color:{c['primary']};
            selection-color:#FFFFFF;
        }}
        QLineEdit:focus, QTextEdit:focus {{
            border-color:{c['primary_active']};
        }}
        QCheckBox::indicator {{
            width:{cb_wh_px}px; height:{cb_wh_px}px;
        }}

        /* 버튼 프라이머리 */
        QPushButton[variant="primary"] {{
            background:{c['primary']};
            color:#FFFFFF;
            border:none;
            border-radius:{btn_radius}px;
            padding:{pad_btn_px}px {pad_btn_px}px;
        }}
        QPushButton[variant="primary"]:hover  {{ background:{c['primary_hover']};  }}
        QPushButton[variant="primary"]:pressed{{ background:{c['primary_active']}; }}
        QPushButton[variant="primary"]:disabled{{ background:#F2F2F2; color:#BDBDBD; }}

        /* 버튼 고스트 */
        QPushButton[variant="ghost"] {{
            background:transparent;
            color:{c['text']};
            border:{b_hair}px solid {c['border']};
            border-radius:{btn_radius}px;
            padding:{pad_v_px}px {pad_h_px}px;
        }}
        QPushButton[variant="ghost"]:hover {{ background:rgba(0,0,0,0.02); }}
        """

#─────────────────────────────────────────────
#  수정 로그 (최신 항목 위)
#─────────────────────────────────────────────
# 2025-09-11 v1.0: 역할 팔레트(THEME_COLORS)로 전환, 색상 별칭 제거, QSS 전면 치환
