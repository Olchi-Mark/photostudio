# -*- coding: utf-8 -*-
#─────────────────────────────────────────────
#  App/components/step_bar.py — 스텝바(전역 토큰/팔레트 적용)
#  - 전역 하드값 제거: THEME_COLORS/TYPO_TOKENS 런타임 참조
#  - 높이/마진은 BasePage의 chrome 토큰으로만 제어
#  - 폰트 px 고정 (FHD 24/18 | QHD 32/24 | UHD 48/36)
#─────────────────────────────────────────────
from __future__ import annotations

from typing import List
from PySide6.QtCore import Qt, QRectF, Signal
from PySide6.QtGui import QPainter, QColor, QFont, QPainterPath, QPen
from PySide6.QtWidgets import QWidget, QApplication

#─────────────────────────────────────────────
#  내부 유틸 — 티어/폰트/토큰
#─────────────────────────────────────────────
# 기능 시작: 현재 티어 이름(FHD/QHD/UHD) 반환
def _tier_name() -> str:
    app = QApplication.instance()
    t = app.property("DISPLAY_TIER") if app else None
    return t if t in ("FHD", "QHD", "UHD") else "FHD"

# 기능 시작: 티어별 활성/비활성 픽셀 폰트 크기
_DEF_FONT_PX: dict[str, tuple[int, int]] = {
    "FHD": (27, 21),
    "QHD": (36, 28),
    "UHD": (54, 42),
}

def _font_px_for_tier() -> tuple[int, int]:
    return _DEF_FONT_PX[_tier_name()]

# 기능 시작: hairline 너비(1:1:2)
def _hairline_width_from_tokens() -> int:
    app = QApplication.instance()
    try:
        TOK = (app.property("TYPO_TOKENS") or {}) if app else {}
        B = TOK.get("borders", {}) if isinstance(TOK, dict) else {}
        hw = int(B.get("hairline", 1))
        return 1 if hw <= 1 else 2  # UHD에서 2px 가능
    except Exception:
        return 2 if _tier_name() == "UHD" else 1

# 기능 시작: 색 팔레트 로드(폴백 포함)
def _palette() -> dict:
    app = QApplication.instance()
    C = (app.property("THEME_COLORS") or {}) if app else {}
    return {
        "primary": C.get("primary", "#FFA9A9"),
        "card":    C.get("card",    "#FFFFFF"),
    }

#─────────────────────────────────────────────
#  클래스 StepBar
#─────────────────────────────────────────────
class StepBar(QWidget):
    """스텝 바(분홍 바 + 선택 하이라이트)
    - 높이/마진: BasePage의 chrome 토큰(stepbar_h 등)에서만 제어
    - 폰트: 활성/비활성 픽셀 고정 (FHD 24/18, QHD 32/24, UHD 48/36)
    - 보더: hairline(1/1/2)
    """

    #─────────────────────────────────────
    #  초기화
    #─────────────────────────────────────
    def __init__(self, steps: List[str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.steps = steps[:]
        self.active_index = 0
        pal = _palette()
        self._COLOR_PRIMARY = QColor(pal["primary"])     # 바/활성 텍스트
        self._COLOR_CARD    = QColor(pal["card"])        # 하이라이트/비활성 텍스트
        self._HAIRLINE_W    = _hairline_width_from_tokens()

        # 설정 변경 브로드캐스트가 있으면 연결(선택)
        try:
            from app.pages.setting import settings_bus  # 지연 임포트
            settings_bus.changed.connect(self._on_settings_changed)
        except Exception:
            pass

    # 설정 변경 시 토큰/팔레트 재적용
    def _on_settings_changed(self, *_):
        pal = _palette()
        self._COLOR_PRIMARY = QColor(pal["primary"])     # 바/활성 텍스트
        self._COLOR_CARD    = QColor(pal["card"])        # 하이라이트/비활성 텍스트
        self._HAIRLINE_W    = _hairline_width_from_tokens()
        self.update()

    # 활성 스텝 인덱스 설정
    def setActive(self, index: int) -> None:
        """범위 내로 클램프하고 리렌더링."""
        self.active_index = max(0, min(index, len(self.steps) - 1))
        self.update()

    #─────────────────────────────────────
    #  렌더: 규격 폰트/보더 사용(자동 축소/포인트 단위 금지)
    #─────────────────────────────────────
    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        W, H = self.width(), self.height()
        n = len(self.steps)
        if n == 0:
            p.fillRect(self.rect(), self._COLOR_CARD)
            p.end(); return

        seg_w = W / n

        # (1) 전체 바 + 아웃라인
        p.fillRect(self.rect(), self._COLOR_PRIMARY)
        pen = QPen(self._COLOR_PRIMARY)
        pen.setWidth(self._HAIRLINE_W)
        p.setPen(pen)
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

        # (2) 선택 구간 하이라이트(양쪽 팁)
        i = self.active_index
        x0, x1 = i * seg_w, (i + 1) * seg_w
        tip = seg_w * 0.07  # 팁 길이(비율)

        path = QPainterPath()
        path.moveTo(x0, 0)
        path.lineTo(x1, 0)
        if i < n - 1:
            path.lineTo(x1 + tip, H / 2)   # 오른쪽 돌출
        path.lineTo(x1, H)
        path.lineTo(x0, H)
        if i > 0:
            path.lineTo(x0 + tip, H / 2)   # 왼쪽 오목
        path.closeSubpath()
        p.fillPath(path, self._COLOR_CARD)

        # (3) 글자: 활성/비활성 고정 px (가로폭에 맞춘 축소 없음)
        active_px, inactive_px = _font_px_for_tier()
        font_active = QFont(); font_active.setBold(True);  font_active.setPixelSize(active_px)
        font_inact  = QFont(); font_inact.setBold(False); font_inact.setPixelSize(inactive_px)

        # (4) 텍스트 그리기: 활성=primary 볼드, 비활성=card 보통
        for k, label in enumerate(self.steps):
            rect = QRectF(k * seg_w, 0, seg_w, H)
            if k == i:
                p.setFont(font_active)
                p.setPen(self._COLOR_PRIMARY)
            else:
                p.setFont(font_inact)
                p.setPen(self._COLOR_CARD)
            p.drawText(rect, Qt.AlignCenter, str(label))

        p.end()

#─────────────────────────────────────────────
#  수정 로그
#─────────────────────────────────────────────
# 2025-09-14 v2.0: 토큰/팔레트 런타임 참조, settings_bus.changed 연결, 하드코딩 색 제거.
# 2025-09-12 v1.0: 초기 도입(티어별 폰트 px 고정, 1:1:2 hairline).
