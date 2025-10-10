# -*- coding: utf-8 -*-
# app/pages/intro.py — 인트로 화면(이미지 → 텍스트 전환, 토큰화 + 3:4:6 스냅)
from __future__ import annotations

#─────────────────────────────────────────────
#  인트로(텍스트)
#  - 타이틀 3줄 + 점선 + 서브타이틀 + CTA(깜빡임)
#  - 모든 px 토큰은 FHD 기준 → 티어별 3:4:6 스냅으로 변환
#  - 자간/비율 성격의 값은 고정(스케일 적용 안 함)
#  - 분홍 더블 보더는 기존 정책 유지(각진 모서리)
#─────────────────────────────────────────────

from typing import Optional
from PySide6.QtCore import Qt, Signal, QTimer, QRectF, QPropertyAnimation, QEasingCurve
from PySide6.QtGui import QPainter, QPen, QColor, QFont, QFontMetrics
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QVBoxLayout, QHBoxLayout, QSizePolicy, QGraphicsOpacityEffect,
    QSpacerItem
)

from app.ui.scale import scale_px_by_tier
from app.pages.setting import open_settings  # F10 설정

#─────────────────────────────────────────────
#  페이지 토큰(FHD 기준) — 스케일 적용 대상 / 비적용 대상 분리
#─────────────────────────────────────────────

# 스케일 대상(FHD 기준 px) — 3의 배수로 설계
_P_FHD = {
    "TITLE_FS": 120,        # 타이틀 세 줄 폰트 크기
    "TITLE_TOP_GAP": 240,   # 상단에서 첫 줄까지
    "TITLE_LINE_GAP": 0,    # 타이틀 줄 간격(리치텍스트로 줄내 조절)
    "TITLE_RULE_GAP": 12,   # 타이틀↔점선 간격
    "RULE_SUB_GAP": 12,     # 점선↔서브타이틀 간격
    "RULE_SIDE_MARGIN": 90, # 점선 좌우 인셋
    "DOT_RULE_H": 2,        # 점선 높이
    "SUBTITLE_FS": 51,      # "PHOTO STUDIO" 폰트 크기
    "SUBTITLE_BIG_KICK": 9, # P/S만 살짝 크게(절대 px)
    "CTA_FS": 69,           # "TAP TO START" 폰트 크기(더 큼)
    "CTA_BOTTOM_GAP": 450,  # 하단 여백(CTA 기준)
}

# 스케일 비적용(고정 px) — 자간 등 비율성 값은 고정
_P_FIXED = {
    "TITLE_LS": 0.8,        # 타이틀 자간(px) — 티어 무관 고정
    "TITLE_LH": 0.75,       # 타이틀 line-height 배수(82%) — 리치텍스트 내부 적용
    "SUBTITLE_LS": 6,     # 서브타이틀 자간(px) — 고정
    "CTA_BLINK_MS": 1100,   # 페이드 주기(ms)
    "DOT_GAP_FACTOR": 3.0,  # 점선 간격 = 높이*계수 (기존 3→2로 더 촘촘)
    "DOT_LEN_FACTOR": 5.0,  # 점 길이 = 높이*계수 (점 대신 짧은 대시)
}

# 보더(기존 유지) — 3의 배수
OUTER_MARGIN = 12
INNER_MARGIN = 27
OUTER_THICK  = 12
INNER_THICK  = 6

# 색상: 테마 우선, 폴백 PINK
_DEF_PINK = "#FFA9A9"


def _spx(base_px: int) -> int:
    """FHD 기준 px → 티어 스케일. 예외(1px/2px)는 scale_px_by_tier 내부 규칙 사용."""
    app = QApplication.instance()
    tier = app.property("DISPLAY_TIER") if app else None
    try:
        return int(scale_px_by_tier(int(base_px), tier))
    except Exception:
        return int(base_px)


class _DottedRule(QWidget):
    """
    가로 점선 라인 위젯.
    - 높이: P[DOT_RULE_H]
    - 색: 테마 primary
    - 가운데 정렬로 점들을 배치
    """
    def __init__(self, color: QColor, h: int, gap_factor: float = 2.0, len_factor: float = 3.0, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self._c = color
        self._h = max(1, h)
        self._g = max(0.5, float(gap_factor))  # 간격 배수(도트 높이 * g)
        self._lf = max(1.0, float(len_factor))  # 길이 배수(도트 높이 * lf)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(self._h)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        pen = QPen(self._c, self._h)
        pen.setCapStyle(Qt.SquareCap)
        p.setPen(pen)
        w = max(0, self.width())
        d = max(1, self._h)
        gap = max(1, int(round(d * self._g)))
        dash = max(d, int(round(d * self._lf)))
        step = dash + gap
        n = 0 if step <= 0 else (w + gap) // step
        used = 0 if n == 0 else (n * dash + (n - 1) * gap)
        offset = (w - used) // 2
        y = self.height() // 2
        x = offset
        for _ in range(int(n)):
            p.drawLine(x, y, x + dash - 1, y)
            x += step
        p.end()


class IntroPage(QWidget):
    """인트로 화면 — 이미지 제거, 텍스트 기반 레이아웃.
    - Spectral/S-CoreDream 폰트 사용(시스템에 등록되어 있다는 가정)
    - 클릭 시 다음 단계로 진행
    """
    go_next = Signal()

    def __init__(self, theme):
        super().__init__()
        self.theme = theme
        self._build_tokens()
        self._build_ui()

    # 토큰 빌드: FHD 기준 → 티어 스케일/고정 결합
    def _build_tokens(self) -> None:
        P = {}
        for k, v in _P_FHD.items():
            P[k] = _spx(v)
        P.update(_P_FIXED)
        self.P = P

    def _color(self, key: str, default_hex: str) -> QColor:
        app = QApplication.instance()
        pal = (app.property("THEME_COLORS") or {}) if app else {}
        return QColor(pal.get(key, default_hex))

    def _build_ui(self) -> None:
        C_PRIMARY = self._color("primary", _DEF_PINK)
        self.setObjectName("IntroPage")

        # 라벨 공통 생성기
        def make_label(text: str, fs: int, ls: float, bold: bool = True) -> QLabel:
            lab = QLabel(text, self)
            f = QFont("Spectral")
            f.setPixelSize(fs)
            f.setWeight(QFont.Bold if bold else QFont.Medium)
            f.setLetterSpacing(QFont.AbsoluteSpacing, float(ls))  # 자간은 고정(px)
            lab.setFont(f)
            lab.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            lab.setStyleSheet(f"color: {C_PRIMARY.name()}; background:transparent; font-family:'Spectral';")
            lab.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
            return lab

        # 타이틀(리치텍스트 한 라벨) — 내부 line-height로 줄간 조절
        self.title = QLabel(self)
        fs_t = self.P["TITLE_FS"]; ls_t = self.P["TITLE_LS"]; lh = self.P.get("TITLE_LH", 0.82)
        ft = QFont("Spectral"); ft.setPixelSize(fs_t); ft.setWeight(QFont.Bold); ft.setLetterSpacing(QFont.AbsoluteSpacing, float(ls_t))
        self.title.setFont(ft)
        self.title.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.title.setStyleSheet(f"color: {C_PRIMARY.name()}; background:transparent; font-family:'Spectral'; margin:0; padding:0;")
        self.title.setTextFormat(Qt.RichText)
        self.title.setText(
            f"<div style='margin:0;padding:0;line-height:{int(lh*100)}%'>MY<br/>SWEET<br/>INTERVIEW</div>"
        )
        self.title.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # 점선
        self.rule = _DottedRule(
            self._color("primary", _DEF_PINK),
            self.P["DOT_RULE_H"],
            self.P.get("DOT_GAP_FACTOR", 2.0),
            self.P.get("DOT_LEN_FACTOR", 3.0),
            self
        )
        # 점선 좌우 인셋 컨테이너
        rule_row = QWidget(self)
        hl = QHBoxLayout(rule_row)
        hl.setContentsMargins(self.P["RULE_SIDE_MARGIN"], 0, self.P["RULE_SIDE_MARGIN"], 0)
        hl.setSpacing(0)
        hl.addWidget(self.rule)

        # 서브타이틀 (P/S만 살짝 크게, 전부 대문자)
        self.subtitle = QLabel(self)
        fs = self.P["SUBTITLE_FS"]; ls = self.P["SUBTITLE_LS"]; kick = self.P.get("SUBTITLE_BIG_KICK", 0)
        f = QFont("Spectral"); f.setPixelSize(fs); f.setWeight(QFont.Medium); f.setLetterSpacing(QFont.AbsoluteSpacing, float(ls))
        self.subtitle.setFont(f)
        self.subtitle.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.subtitle.setStyleSheet(f"color: {C_PRIMARY.name()}; background:transparent;")
        self.subtitle.setTextFormat(Qt.RichText)
        fs_big = fs + int(kick)
        # 모든 조각에 font-family:'Spectral' 강제
        self.subtitle.setText(
            f"<span style=\"font-family:'Spectral'; font-size:{fs_big}px\">P</span>"
            f"<span style=\"font-family:'Spectral'; font-size:{fs}px\">HOTO </span>"
            f"<span style=\"font-family:'Spectral'; font-size:{fs_big}px\">S</span>"
            f"<span style=\"font-family:'Spectral'; font-size:{fs}px\">TUDIO</span>"
        )
        self.subtitle.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)

        # CTA(페이드)
        fs_cta = self.P["CTA_FS"]
        self.cta = QLabel(self)
        fcta = QFont("Spectral"); fcta.setPixelSize(fs_cta); fcta.setWeight(QFont.Medium)
        self.cta.setFont(fcta)
        self.cta.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
        self.cta.setStyleSheet(f"color: {C_PRIMARY.name()}; background:transparent; font-family:'Spectral';")
        self.cta.setTextFormat(Qt.RichText)
        # T/T/S만 살짝 크게(절대 px +6)
        big = fs_cta + 6
        self.cta.setText(
            f"<span style=\"font-family:'Spectral'; font-size:{big}px\">T</span>"
            f"<span style=\"font-family:'Spectral'; font-size:{fs_cta}px\">AP </span>"
            f"<span style=\"font-family:'Spectral'; font-size:{big}px\">T</span>"
            f"<span style=\"font-family:'Spectral'; font-size:{fs_cta}px\">O </span>"
            f"<span style=\"font-family:'Spectral'; font-size:{big}px\">S</span>"
            f"<span style=\"font-family:'Spectral'; font-size:{fs_cta}px\">TART</span>"
        )
        self._cta_op = QGraphicsOpacityEffect(self.cta)
        self._cta_op.setOpacity(1.0)
        self.cta.setGraphicsEffect(self._cta_op)
        # 페이드 애니메이션 (InOutSine, 왕복)
        self._fade = QPropertyAnimation(self._cta_op, b"opacity", self)
        self._fade.setDuration(int(self.P["CTA_BLINK_MS"]))
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.InOutSine)
        self._fade.finished.connect(self._on_fade_finished)
        self._fade.start()
        # 초기 표시 직전에 한 번 더 팔레트 재적용(부트 순서 차이 보호)
        self._reapply_colors()

        # 레이아웃(세로)
        v = QVBoxLayout(self)
        v.setContentsMargins(INNER_MARGIN + OUTER_THICK, INNER_MARGIN + OUTER_THICK,
                             INNER_MARGIN + OUTER_THICK, INNER_MARGIN + OUTER_THICK)
        v.setSpacing(0)  # 기본 줄 간격 기반
        v.addSpacerItem(QSpacerItem(0, self.P["TITLE_TOP_GAP"]))
        v.addWidget(self.title)
        v.addSpacing(self.P["TITLE_RULE_GAP"])
        v.addWidget(rule_row)
        v.addSpacing(self.P["RULE_SUB_GAP"])
        v.addWidget(self.subtitle)
        v.addStretch(1)
        v.addWidget(self.cta, 0, Qt.AlignHCenter)
        v.addSpacerItem(QSpacerItem(0, self.P["CTA_BOTTOM_GAP"]))

    def _on_fade_finished(self) -> None:
        # 애니메이션 방향을 왕복시켜 지속 페이드
        if self._fade.direction() == QPropertyAnimation.Forward:
            self._fade.setDirection(QPropertyAnimation.Backward)
        else:
            self._fade.setDirection(QPropertyAnimation.Forward)
        self._fade.start()

    def _reapply_colors(self) -> None:
        c = self._color("primary", _DEF_PINK)
        name = c.name()
        # 라벨 3종
        self.title.setStyleSheet(f"color:{name}; background:transparent; font-family:'Spectral'; margin:0; padding:0;")
        self.subtitle.setStyleSheet(f"color:{name}; background:transparent;")
        self.cta.setStyleSheet(f"color:{name}; background:transparent; font-family:'Spectral';")
        # 점선 색
        if hasattr(self, "rule"):
            self.rule._c = c
            self.rule.update()

    def showEvent(self, e):
        super().showEvent(e)
        # 표시 시점에도 최신 팔레트 보장
        self._reapply_colors()

    # 어디 클릭해도 시작
    def mousePressEvent(self, e):
        self.go_next.emit()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_F10:
            open_settings(self, theme=self.theme)
            return
        super().keyPressEvent(e)

    # 더블 보더(각)
    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        pink = self._color("primary", _DEF_PINK)

        def draw_rect(margin, thickness):
            pen = QPen(pink, thickness)
            pen.setJoinStyle(Qt.MiterJoin)
            pen.setCapStyle(Qt.SquareCap)
            p.setPen(pen)
            r = QRectF(self.rect()).adjusted(margin, margin, -margin, -margin)
            if thickness % 2 == 1:
                r = r.adjusted(0.5, 0.5, -0.5, -0.5)
            p.drawRect(r)

        draw_rect(OUTER_MARGIN, OUTER_THICK)
        draw_rect(INNER_MARGIN, INNER_THICK)
        p.end()

#─────────────────────────────────────────────
#  수정 로그
#  - v1.6 (2025-09-14): 점 길이 토큰 DOT_LEN_FACTOR 추가(기본 3.0). 점 → 짧은 대시 렌더.
#  - v1.5 (2025-09-14): 점선 간격 토큰 DOT_GAP_FACTOR 추가(기본 2.0) → 더 촘촘하게. 중앙 정렬 계산 개선.
#  - v1.4 (2025-09-14): 타이틀을 RichText 한 라벨로 통합(line-height 82%). RULE_GAP 12px, CTA_BOTTOM 300px.
#  - v1.3 (2025-09-14): 타이틀 줄간격 6, 서브타이틀 45px/자간 3.5px, CTA 69px.
#  - v1.2 (2025-09-14): 타이틀 줄간격 축소, 점선 좌우 마진 추가, 서브타이틀 +6px/자간 확대, CTA 크기 확대 및 페이드 0.0↔1.0, 주기 1200ms.
#  - v1.1 (2025-09-14): 서브타이틀/CTA에 font-family:'Spectral'을 RichText로 강제. CTA 첫글자(T/T/S) 강조.
#  - v1.0 (2025-09-14): 이미지 제거, 텍스트 레이아웃 전환. FHD 하드토큰 → 티어 스냅.
#                        자간/비율 값은 고정(px) 처리. 보더 정책 유지.
#─────────────────────────────────────────────
