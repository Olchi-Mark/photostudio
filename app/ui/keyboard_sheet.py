# -*- coding: utf-8 -*-
# app/ui/keyboard_sheet.py — 타깃 바로 아래에 붙는 바텀시트 (고정 사이즈, 반응형 재배치 제거)
from __future__ import annotations
from typing import Optional

from PySide6.QtCore import Qt, QRect, QEasingCurve, QPropertyAnimation, QPoint
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QWidget, QFrame, QVBoxLayout, QGraphicsDropShadowEffect, QSizePolicy

from app.ui.virtual_keyboard import VirtualKeyboard, KeyboardMode  # noqa: F401 (KeyboardMode 참조 용)

#─────────────────────────────────────────────
#  키보드 바텀시트 오버레이
#─────────────────────────────────────────────
class KeyboardSheet(QWidget):
    """
    전체 창 위에 떠있는 오버레이 바텀시트.
    - 레이아웃에 넣지 않음(본문이 밀리지 않음)
    - 포커스된 입력칸 바로 아래에 붙여 표시(가리지 않음)
    - '완료' 또는 패널 밖 클릭(스크림)으로 닫힘
    - ★ 반응형 재배치 제거: 열릴 때 1회 배치만 수행, 이후 창 리사이즈에도 위치 고정
    - ★ 보더/라운드/간격/색상은 전부 토큰/팔레트 기반(3:4:6 + 예외 규칙)
    """

    # 내부 유틸 — 3의 배수로 내림 스냅
    @staticmethod
    def _snap3(v: int) -> int:
        try:
            v = int(v)
        except Exception:
            return 0
        return (v // 3) * 3

    # 초기 구성: 팔레트/토큰을 읽어 QSS 적용
    def __init__(self, theme, parent: Optional[QWidget] = None) -> None:
        """
        - 역할: 스크림/패널/가상키보드 초기화 + 토큰/팔레트 기반 QSS 적용
        - 수정로그:
          - v2.0: 반응형 재배치 제거, theme.BORDER 등 별칭 제거 → theme.colors & TYPO_TOKENS로 치환
          - v1.x: 최초 구현(슬라이드 인/아웃 애니메이션)
        """
        super().__init__(parent)
        self.theme = theme
        # 패널 좌/우 여백(상위 컨테이너와 충돌 방지용, 토큰 기반으로 '살짝')
        self._edge_inset = 0  # open() 시점에 토큰으로 계산됨
        self.setWindowFlags(Qt.Widget | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.hide()

        self._is_open = False
        self._target: Optional[QWidget] = None

        # 토큰/팔레트 로드(초기 상태) — 열릴 때마다 최신으로 다시 읽음
        app = QApplication.instance()
        TOK = (app.property("TYPO_TOKENS") or {}) if app else {}
        COL = (app.property("THEME_COLORS") or {}) if app else {}
        B = TOK.get("borders", {})
        R = TOK.get("radii", {})
        S = TOK.get("spacing", {})
        hair = int(B.get("hairline", 1))           # 1:1:2 규칙
        gap  = int(S.get("gap", 12))               # 3:4:6 스냅된 값
        rbtn = int(R.get("button", 6))             # 버튼/시트 라운드

        # 스크림
        self.scrim = QFrame(self)
        scrim_bg = COL.get("overlay_12", "rgba(0,0,0,0.12)")  # 오버레이 컬러
        self.scrim.setStyleSheet(f"background:{scrim_bg};")
        self.scrim.hide()

        # 패널
        self.panel = QFrame(self)
        self.panel.setObjectName("KeyboardPanel")
        border_color = COL.get("border", "#E0E0E0")
        card_bg = COL.get("card", "#FFFFFF")
        self.panel.setStyleSheet(
            f"""
            QFrame#KeyboardPanel {{
                background:{card_bg};
                border-top:{hair}px solid {border_color};
                border-top-left-radius:{rbtn}px; border-top-right-radius:{rbtn}px;
            }}
            """
        )
        # 그림자(선택) — 규칙 영향 없음
        # eff = QGraphicsDropShadowEffect(); eff.setBlurRadius(24); eff.setColor(QColor(0,0,0,70)); eff.setOffset(0,8); self.panel.setGraphicsEffect(eff)
        self.panel.hide()

        # 레이아웃(내부 패딩/간격은 키보드 위젯이 관리)
        lay = QVBoxLayout(self.panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # 가상 키보드
        self.vkb = VirtualKeyboard(self.theme, self.panel)
        self.vkb.done.connect(self.close)  # 완료→닫기
        lay.addWidget(self.vkb)

        # 애니메이션
        self._anim = QPropertyAnimation(self.panel, b"geometry", self)

    # 오버레이 영역 1회 설정
    def _apply_overlay_geometry(self) -> None:
        """
        - 역할: 부모창 기준으로 오버레이/스크림 전체 영역을 1회 설정
        - 수정로그: 반응형 재배치 제거에 따라 단발성 호출만 유지
        """
        # 크기 제약 해제
        if not self.parent():
            return
        self.setGeometry(self.parent().rect())         # 오버레이 = 부모 전체
        self.scrim.setGeometry(self.rect())             # 스크림 = 오버레이 전체

        # 패널 좌우 인셋 계산(부모 컨테이너와의 시각적 충돌 방지)
        app = QApplication.instance()
        TOK = (app.property("TYPO_TOKENS") or {}) if app else {}
        CH = TOK.get("chrome", {}) if isinstance(TOK, dict) else {}
        sm = int(CH.get("side_margin", 0) or 0)
        # 너무 넓지 않게 15%만 취한 뒤 3의 배수로 스냅(FHD: 90→13→12 / QHD:120→18 / UHD:180→27)
        inset = self._snap3(int(sm * 0.15)) if sm > 0 else 0
        self._edge_inset = inset
        # 오버레이 자체 마진은 유지하되, 패널 배치 시 x/width로 반영된다.

    # 패널을 화면 아래쪽(offscreen) 시작 위치로 변환
    def _panel_offscreen(self, end_rect: QRect) -> QRect:
        """
        - 역할: 패널 슬라이드 인 시작 지점 계산(아래에서 시작)
        """
        return QRect(end_rect.x(), self.height(), end_rect.width(), end_rect.height())

    # 타깃 하단 y & 남은 높이 계산(토큰 gap 활용)
    def _top_and_free_below(self, target: QWidget, gap: Optional[int] = None) -> tuple[int, int]:
        """
        - 역할: 타깃 하단 기준으로 패널이 올라올 y와 그 아래 남은 높이를 계산
        - 수정로그: 고정 gap→토큰 spacing.gap 사용
        """
        app = QApplication.instance()
        TOK = (app.property("TYPO_TOKENS") or {}) if app else {}
        S = TOK.get("spacing", {})
        gap_px = int(S.get("gap", 12)) if gap is None else int(gap)
        try:
            bottom_y = target.mapTo(self, QPoint(0, target.height())).y()
        except Exception:
            bottom_y = int(self.height() * 0.5)
        top_y = max(0, min(self.height(), bottom_y + gap_px))
        free_h = max(0, self.height() - top_y)
        return top_y, free_h

    # 키보드 열기(고정 높이, 1회 배치)
    # - 수정로그: 반응형 재배치 호출 제거, 팔레트/토큰 기반 QSS 유지
    def open(self, mode: str, target: QWidget) -> None:
        """
        - 역할: 포커스 타깃 아래로 키보드를 슬라이드 인(고정 높이)
        - 수정로그: _reposition_overlay_impl 제거 → _apply_overlay_geometry 1회 호출로 대체
        """
        self._target = target
        self._apply_overlay_geometry()                  # 오버레이 1회 배치

        # 키보드 빌드/부착 (공개 API 분리: attach + set_mode)
        if target is not None:
            self.vkb.attach(target)
        self.vkb.set_mode(mode)
        self.vkb.show()

        # 타깃 아래 남은 공간 계산(토큰 gap)
        top_y, free_h = self._top_and_free_below(target)

        # 고정 높이(모드별 preferred) 사용. 화면을 넘지 않도록만 클램프(확대/축소 없음)
        pref_h  = self.vkb.preferred_height()
        final_h = pref_h if pref_h > 0 else max(360, min(520, free_h))  # 안전값
        # 남는 공간이 더 크면, 시트를 '아래로 붙여' 보이게 상단 y를 조정
        max_top = max(0, self.height() - final_h)
        top_y = min(top_y, max_top)
        # 좌우 인셋 반영(부모 레이아웃과 겹침 방지)
        x = self._edge_inset
        w = max(0, self.width() - (self._edge_inset * 2))
        end_geom = QRect(x, top_y, w, min(final_h, free_h))

        # ★ 패널만 고정, 내부 vkb는 Preferred 정책으로 그리드가 스스로 배치되게 둔다
        sp = self.panel.sizePolicy(); sp.setVerticalPolicy(QSizePolicy.Fixed); self.panel.setSizePolicy(sp)
        self.panel.setMinimumHeight(end_geom.height())
        self.panel.setMaximumHeight(end_geom.height())

        vsp = self.vkb.sizePolicy(); vsp.setVerticalPolicy(QSizePolicy.Preferred); self.vkb.setSizePolicy(vsp)
        # vkb는 최소 높이만 보장(내부 그리드가 자체 배치되게)
        self.vkb.setMinimumHeight(end_geom.height())
        self.vkb.setMaximumHeight(16777215)

        # 레이어링 & 표시
        self.show(); self.raise_()
        self.scrim.show(); self.scrim.raise_()
        if not self._is_open:
            self.panel.setGeometry(self._panel_offscreen(end_geom))  # 아래에서 시작
            self.panel.show()
            self._is_open = True
        self.panel.raise_()

        # 애니메이션
        self._anim.stop()
        self._anim.setStartValue(self.panel.geometry())
        self._anim.setEndValue(end_geom)
        self._anim.setDuration(420)
        self._anim.setEasingCurve(QEasingCurve.OutBack)
        self._anim.start()

    # 모드 전환(열려 있으면 동일 로직 사용)
    def switch(self, mode: str, target: QWidget) -> None:
        """
        - 역할: 열려 있는 상태에서 모드만 변경
        """
        self.open(mode, target)

    # 슬라이드 다운 후 완전히 숨김
    def close(self) -> None:  # noqa: A003
        """
        - 역할: 애니메이션으로 닫고 상태 초기화
        """
        if not self._is_open:
            return
        end = self._panel_offscreen(self.panel.geometry())
        self._anim.stop()
        self._anim.setStartValue(self.panel.geometry())
        self._anim.setEndValue(end)
        self._anim.setDuration(260)
        self._anim.setEasingCurve(QEasingCurve.InCubic)
        self._anim.finished.connect(self._after_closed)
        self._anim.start()

    # 닫힘 후 정리
    def _after_closed(self) -> None:
        """
        - 역할: 애니메이션 종료 후 시그널 연결 해제 및 위젯 숨김
        - 수정로그: 닫힘 시 고정 높이/정책 원복
        """
        try:
            self._anim.finished.disconnect(self._after_closed)
        except Exception:
            pass
        self.scrim.hide()
        self.panel.hide()
        self.hide()
        self._is_open = False
        self._target = None

        # ★ 고정 높이 해제(원복)
        for w in (self.panel, self.vkb):
            try:
                sp = w.sizePolicy(); sp.setVerticalPolicy(QSizePolicy.Preferred); w.setSizePolicy(sp)
                w.setMinimumHeight(0); w.setMaximumHeight(16777215)
            except Exception:
                pass

    # 패널 밖 클릭(스크림) → 닫기
    def mousePressEvent(self, e):
        """
        - 역할: 패널 외부 클릭 시 닫기 동작
        """
        if self._is_open and not self.panel.geometry().contains(e.position().toPoint()):
            self.close()
            return
        super().mousePressEvent(e)

#─────────────────────────────────────────────
#  수정 로그
#  - v2.0: 반응형 재배치 제거, 토큰/팔레트 기반 QSS, theme 별칭 제거
#  - v1.x: 최초 구현(슬라이드 인/아웃)
#─────────────────────────────────────────────
