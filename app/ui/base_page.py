# -*- coding: utf-8 -*-
from typing import List, Optional, Dict
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QFrame, QSizePolicy, QVBoxLayout as _QVBoxLayout, QApplication
)

from app.components.step_bar import StepBar
from app.components.footer_bar import FooterBar

#─────────────────────────────────────────────
#  공통 페이지 프레임: StepBar / Content / FooterBar
#  - 해상도별 규칙 고정: 3:4:6 배율 + 3의 배수 내림 스냅
#  - 예외: 보더 1px=1:1:2, 2px=2:3:4 (※ 보더 두께 자체는 하위 위젯 토큰에서 적용)
#  - 모든 페이지의 자체 좌우 마진/폭 확장 금지 → BasePage가 일괄 적용
#  - 페이지는 오직 수직 spacing(상하 간격)만 사용
#─────────────────────────────────────────────
class BasePage(QWidget):
    """
    - 역할: 상단 스텝바/중앙 컨텐츠/하단 푸터바의 높이·마진을 전역 규칙으로 강제한다.
    - 규칙: FHD/QHD/UHD = 3:4:6, 스냅=3의 배수 내림. 페이지단 수평 마진 제거.
    """
    go_prev = Signal()
    go_next = Signal()

    # 기능 시작: FHD 기준 하드 토큰(외부 json/settings 비참조)
    _CHROME_FHD = {
        "stepbar_h": 66,   # 스텝바 높이
        "footer_h": 96,   # 푸터바 높이
        "gap_top": 84,    # 컨텐츠 상단 여백
        "gap_bottom": 84, # 컨텐츠 하단 여백(기본은 gap_top과 동일)
        "side_l": 135,     # 좌측 마진
        "side_r": 135,     # 우측 마진
    }

    #── 내부 스케일/스냅 유틸 ─────────────────────────────────────────────
    @staticmethod
    def _tier_factor() -> float:
        """
        - 역할: DISPLAY_TIER(FHD/QHD/UHD)에 따른 배율(1, 4/3, 2) 반환.
        - 보강: TYPO_TOKENS.scale 존재 시 그 값으로 분기.
        """
        app = QApplication.instance()
        # 토큰 우선
        try:
            TOK = (app.property("TYPO_TOKENS") or {}) if app else {}
            scl = float(TOK.get("scale", 1.0)) if TOK else 1.0
            if scl >= 1.9:
                return 2.0
            if scl >= 1.3:
                return 4.0/3.0
        except Exception:
            pass
        tier = app.property("DISPLAY_TIER") if app else None
        if tier == "QHD":
            return 4.0/3.0
        if tier == "UHD":
            return 2.0
        return 1.0  # FHD 기본

    @staticmethod
    def _snap3(x: float) -> int:
        """
        - 역할: 3의 배수 내림 스냅. 예: 28→27, 16→15, 14→12, 20→18
        """
        xi = int(x)
        return (xi // 3) * 3

    @classmethod
    def _chrome_from_tokens(cls) -> Optional[Dict[str, int]]:
        """
        - 역할: (비활성) 외부 json/settings 무시. 항상 None을 반환해 하드토큰 사용.
        """
        return None

    @classmethod
    def _chrome_dims(cls) -> Dict[str, int]:
        """
        - 역할: 전역 크롬 규격 결정(하드토큰만 사용).
        - 계산: FHD 기준 `_CHROME_FHD` × 배율(1/4⁄3/2) → 3의 배수 내림 스냅.
        """
        f = cls._tier_factor()
        base = cls._CHROME_FHD
        step_h = cls._snap3(base["stepbar_h"] * f)
        foot_h = cls._snap3(base["footer_h"] * f)
        gap_t  = cls._snap3(base["gap_top"]   * f)
        gap_b  = cls._snap3(base.get("gap_bottom", base["gap_top"]) * f)
        side_l = cls._snap3(base["side_l"]    * f)
        side_r = cls._snap3(base["side_r"]    * f)
        return {
            "stepbar_h": step_h,
            "footer_h": foot_h,
            "gap_top": gap_t,
            "gap_bottom": gap_b,
            "side_l": side_l,
            "side_r": side_r,
            "side_margin": min(side_l, side_r),
        }

    def __init__(
        self,
        theme,
        steps: List[str],
        active_index: int,
        footer_assets: Optional[Dict[str, str]] = None,
        parent: Optional[QWidget] = None,
    ):
        super().__init__(parent)
        self.theme = theme
        self._steps = steps[:]
        self._active_index = max(0, min(active_index, len(self._steps) - 1))
        dims = self._chrome_dims()

        # 루트 프레임 레이아웃
        self._root_v = QVBoxLayout(self)
        self._root_v.setContentsMargins(0, 0, 0, 0)
        self._root_v.setSpacing(0)

        # StepBar (고정 높이)
        self.stepbar = StepBar(self._steps, parent=self)
        self.stepbar.setActive(self._active_index)
        self.stepbar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.stepbar.setMinimumHeight(dims["stepbar_h"])  # 크기 규격 적용
        self.stepbar.setMaximumHeight(dims["stepbar_h"])  # 고정
        self._root_v.addWidget(self.stepbar)

        # Content (중앙, 좌우 마진은 BasePage가 관리)
        self.content = QFrame(self)
        self.content.setObjectName("ContentArea")
        self.content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._root_v.addWidget(self.content)

        # FooterBar (고정 높이)
        footer_kwargs: Dict[str, Optional[str]] = {}
        if footer_assets:
            footer_kwargs = dict(
                brand_path=footer_assets.get("brand"),
                prev_path=footer_assets.get("prev"),
                next_path=footer_assets.get("next"),
            )
        self.footer = FooterBar(**footer_kwargs, parent=self)
        self.footer.go_prev.connect(self.go_prev.emit)
        self.footer.go_next.connect(self.go_next.emit)
        self.footer.setMinimumHeight(dims["footer_h"])  # 크기 규격 적용
        self.footer.setMaximumHeight(dims["footer_h"])  # 고정
        self._root_v.addWidget(self.footer)

        self._root_v.setStretch(0, 0)
        self._root_v.setStretch(1, 1)
        self._root_v.setStretch(2, 0)

        # ← / → 네비게이션만 유지 (F9 제거)
        QShortcut(QKeySequence(Qt.Key_Left),  self, activated=self.go_prev.emit)
        QShortcut(QKeySequence(Qt.Key_Right), self, activated=self.go_next.emit)

        self._sync_footer_enabled()
        self._top_compact = False  # 페이지 상단 컴팩트 모드 플래그

        # 설정 변경 시 크롬 재적용
        try:
            from app.pages.setting import settings_bus
            settings_bus.changed.connect(lambda *_: self.refresh_chrome())
        except Exception:
            pass

    #─────────────────────────────────────────────
    #  중앙 컨텐츠 배치 — 좌우 마진 고정, 상하 스페이싱만 허용
    #─────────────────────────────────────────────
    def setCentralWidget(
        self,
        widget: QWidget,
        *,
        margin=(0, 0, 0, 0),  # ← 무시됨: BasePage가 chrome_dims로 강제 적용
        spacing: int = 12,
        max_width: Optional[int] = None,   # 폭 제한 금지 권장(None)
        center: bool = True,
    ):
        """
        - 역할: 페이지의 중앙 컨텐츠를 배치. 좌우 마진은 전역 side_margin만 적용.
        - 규칙: 페이지 자체 마진 정책 금지. 수직 spacing만 허용.
        """
        dims = self._chrome_dims()
        widget.setParent(self.content)

        # 기존 레이아웃이 있으면 재사용(덮어쓰기 대신 안전 재설정)
        root = self.content.layout()
        if root is None:
            root = _QVBoxLayout(self.content)
        # 좌우 마진=side_margin, 상단/하단=gap_top/gap_bottom
        root.setContentsMargins(dims["side_l"], dims["gap_top"], dims["side_r"], dims["gap_bottom"])
        root.setSpacing(spacing)  # 수직 간격만 사용

        if center:
            # 단일 컬럼 래퍼 재사용/생성
            column = None
            if root.count() > 0:
                item = root.itemAt(0)
                if item and item.widget() and isinstance(item.widget(), QWidget):
                    column = item.widget()
            if column is None:
                column = QWidget(self.content)
                column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                root.addWidget(column, 1, Qt.AlignHCenter)

            if max_width is None:
                column.setMaximumWidth(16777215)
                column.setMinimumWidth(0)
            else:
                column.setMaximumWidth(int(max_width))
                column.setMinimumWidth(min(int(max_width), 320))

            colv = column.layout()
            if colv is None:
                colv = _QVBoxLayout(column)
                colv.setContentsMargins(0, 0, 0, 0)
                colv.setSpacing(spacing)
                colv.addWidget(widget, 1)
            else:
                # 기존 위젯 교체
                while colv.count():
                    it = colv.takeAt(0)
                    w = it.widget()
                    if w:
                        w.setParent(None)
                colv.setSpacing(spacing)
                colv.addWidget(widget, 1)
        else:
            # center=False: 루트에 바로 부착(재배치 시 교체)
            while root.count():
                it = root.takeAt(0)
                w = it.widget()
                if w:
                    w.setParent(None)
            root.addWidget(widget, 1)

        # 컴팩트 모드면 상단 여백만 최소화(규격 내)
        if getattr(self, "_top_compact", False):
            m = root.contentsMargins()
            root.setContentsMargins(m.left(), min(m.top(), self._snap3(6)), m.right(), m.bottom())

    #─────────────────────────────────────────────
    #  크롬 규격 재적용(설정 변경 대응)
    #─────────────────────────────────────────────
    def refresh_chrome(self):
        try:
            dims = self._chrome_dims()
            self.stepbar.setMinimumHeight(dims["stepbar_h"])
            self.stepbar.setMaximumHeight(dims["stepbar_h"])
            self.footer.setMinimumHeight(dims["footer_h"])
            self.footer.setMaximumHeight(dims["footer_h"])
            lay = self.content.layout()
            if lay:
                lay.setContentsMargins(dims["side_l"], dims["gap_top"], dims["side_r"], dims["gap_bottom"])
        except Exception:
            pass

    #─────────────────────────────────────────────
    #  스텝 활성/네비게이션 상태
    #─────────────────────────────────────────────
    def set_active_step(self, index: int):
        self._active_index = max(0, min(index, len(self._steps) - 1))
        self.stepbar.setActive(self._active_index)
        self._sync_footer_enabled()

    def set_prev_enabled(self, enabled: bool): self.footer.prevBtn.setEnabled(enabled)
    def set_next_enabled(self, enabled: bool): self.footer.nextBtn.setEnabled(enabled)

    def _sync_footer_enabled(self):
        is_first = (self._active_index <= 0)
        is_last  = (self._active_index >= len(self._steps) - 1)
        self.footer.prevBtn.setEnabled(not is_first)
        self.footer.nextBtn.setEnabled(not is_last)

    # 네비게이션 모드 및 페이지 훅
    @staticmethod
    def _mode_to_int(mode) -> int:
        """FooterBar의 정수 모드로 정규화. 문자열/정수 모두 허용.
        disabled=0, enabled=1, lit=2, hidden=3 (TriButton 기준)
        """
        try:
            from app.components.footer_bar import TriButton
            mapping = {
                "disabled": getattr(TriButton, "MODE_DISABLED", 0),
                "enabled": getattr(TriButton, "MODE_ENABLED", 1),
                "lit": getattr(TriButton, "MODE_LIT", 2),
                "hidden": getattr(TriButton, "MODE_HIDDEN", 3),
            }
            if isinstance(mode, int):
                return int(mode)
            if isinstance(mode, str):
                return mapping.get(mode.lower(), mapping["enabled"])
        except Exception:
            if isinstance(mode, int):
                return int(mode)
            if isinstance(mode, str):
                return {"disabled":0, "enabled":1, "lit":2, "hidden":3}.get(mode.lower(), 1)
        return 1

    def _apply_mode_fallback(self, target: str, mode) -> None:
        """FooterBar가 문자열 모드를 지원하지 않을 때의 폴백 처리."""
        m = self._mode_to_int(mode)
        enabled = (m in (1, 2))
        visible = (m != 3)
        if target == "prev":
            self.set_prev_visible(visible)
            self.set_prev_enabled(enabled)
        else:
            self.set_next_visible(visible)
            self.set_next_enabled(enabled)
    def on_before_prev(self, session: Optional[Dict] = None):
        """이전으로 이동하기 직전 호출. False를 반환하면 이동을 취소."""
        return True

    def on_before_next(self, session: Optional[Dict] = None):
        """다음으로 이동하기 직전 호출. False를 반환하면 이동을 취소."""
        return True

    def set_prev_mode(self, mode):
        f = getattr(self.footer, "set_prev_mode", None)
        if callable(f):
            f(self._mode_to_int(mode))
        else:
            self._apply_mode_fallback("prev", mode)

    def set_next_mode(self, mode):
        f = getattr(self.footer, "set_next_mode", None)
        if callable(f):
            f(self._mode_to_int(mode))
        else:
            self._apply_mode_fallback("next", mode)

    def set_prev_visible(self, on: bool):
        f = getattr(self.footer, "set_prev_visible", None)
        if callable(f):
            f(on)
        else:
            self.footer.prevBtn.setVisible(bool(on))

    def set_next_visible(self, on: bool):
        f = getattr(self.footer, "set_next_visible", None)
        if callable(f):
            f(on)
        else:
            self.footer.nextBtn.setVisible(bool(on))

    #─────────────────────────────────────────────
    #  안전 하단 인셋(키보드 등)
    #─────────────────────────────────────────────
    def set_bottom_safe_inset(self, inset: int):
        """
        - 역할: 가상키보드 등으로 가려지는 경우 하단 여백을 최소 inset까지 늘린다.
        - 주의: 좌우 마진은 변경하지 않는다.
        """
        lay = self.content.layout()
        if not lay:
            return
        m = lay.contentsMargins()
        lay.setContentsMargins(m.left(), m.top(), m.right(), max(m.bottom(), inset))

    #─────────────────────────────────────────────
    #  상단 컴팩트 모드: 스텝바/컨텐츠 사이 여백 최소화
    #─────────────────────────────────────────────
    def set_top_compact(self, on: bool = True):
        """
        - 역할: 상단 여백을 규격 범위에서 최소화. (페이지 단위로 선택적 적용)
        - 규칙: 내부 spacing/마진을 직접 건드리지 않고 BasePage 규격만 조정.
        """
        self._top_compact = bool(on)
        try:
            dims = self._chrome_dims()
            # 스텝바 높이는 규격 유지, 컨텐츠 top만 살짝 줄임
            lay = self.content.layout()
            if lay:
                m = lay.contentsMargins()
                lay.setContentsMargins(m.left(), min(m.top(), self._snap3(6)), m.right(), m.bottom())
        except Exception:
            pass

#─────────────────────────────────────────────
#  수정 로그 (최신 항목 위)
#─────────────────────────────────────────────
# 2025-09-14: 하드 토큰화(BasePage 내부 `_CHROME_FHD`), 외부 json/settings 완전 무시.
#             좌우 분리(side_l/side_r) 유지, 3:4:6×스냅 계산은 동일.
# 2025-09-11: 해상도별 3:4:6 규격 반영(step=66/87/132, footer=96/128/192, gap_top=30/40/60, side=90/120/180)
#             BasePage에서 좌우 마진/상단하단 간격 일괄 적용, 페이지 자체 마진 정책 금지
#             고정 높이(스텝/푸터)와 수직 spacing만 허용
# 2025-09-11: F9 네비 제거, 기본 프레임 구성 유지
