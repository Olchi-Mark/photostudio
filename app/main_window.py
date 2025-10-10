# app/main_window.py
# -*- coding: utf-8 -*-
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout
from PySide6.QtCore import Qt, QRect, QEvent, QPoint, QTimer
from PySide6.QtGui import QShortcut, QKeySequence

from app.ui.router import PageRouter
from app.pages.intro import IntroPage
from app.pages.input import InputPage
from app.pages.size_select import SizeSelectPage
from app.pages.capture import CapturePage
from app.pages.pick_photo import PickPhotoPage
from app.pages.print_view import PrintViewPage
from app.pages.email_send import EmailSendPage
from app.pages.enhance_select import EnhanceSelectPage
from app.pages.outro import OutroPage

from app.pages.setting import open_settings, settings_bus, SETTINGS
from app.ui.keyboard_sheet import KeyboardSheet
from app.utils.storage import get_retention_days
from ctypes import windll, wintypes
# 스케일링 유틸 (tier 기반)
from app.ui.scale import scale_px_by_tier

# 개발 플래그(없어도 동작) — 빠른진입 지원
try:
    from app.config import dev_flags as DEV  # type: ignore
except Exception:
    DEV = None

# 빠른진입 대상 페이지(F7)



#F7_ENTRY_PAGE = "outro"

#F7_ENTRY_PAGE = "size_select"
##F7_ENTRY_PAGE = "capture"
F7_ENTRY_PAGE = "pick_photo"
#F7_ENTRY_PAGE = "print_view"
#F7_ENTRY_PAGE = "email_send"
#F7_ENTRY_PAGE = "enhance_select"

def _factory(cls):
    def f(theme, session):
        try:
            return cls(theme, session)
        except TypeError:
            return cls(theme)
    return f


#─────────────────────────────────────────────
#  메인 윈도우
#─────────────────────────────────────────────
class MainWindow(QMainWindow):
    def __init__(self, theme, display=None):
        super().__init__()
        self.theme = theme
        self.display = display  # WindowModeInfo 주입: tier/req_h 기준 스케일링용
        self.setStyleSheet(self.theme.qss())
        self.setWindowTitle("photostudio")

        # 전역 세션 (captures=썸네일용, raw_captures=원본용)
        self.session = {
            "name": "", "phone": "", "email1": "", "email2": "",
            "ratio": "3040", "captures": [], "raw_captures": []
        }

        # 라우터
        self.router = PageRouter(
            theme=self.theme,
            session=self.session,
            routes=[
                ("intro",          _factory(IntroPage)),
                ("input",          _factory(InputPage)),
                ("size_select",    _factory(SizeSelectPage)),
                ("capture",        _factory(CapturePage)),
                ("pick_photo",     _factory(PickPhotoPage)),
                ("print_view",     _factory(PrintViewPage)),
                ("email_send",     _factory(EmailSendPage)),
                ("enhance_select", _factory(EnhanceSelectPage)),
                ("outro",          _factory(OutroPage)),
            ],
            parent=self,
        )

        #─────────────────────────────────────────────
        #  풀스크린 흰 배경 + 9:16 스테이지(레터박스) 컨테이너
        #─────────────────────────────────────────────
        self._root = QWidget(self)
        self._root.setObjectName("Root")
        root_v = QVBoxLayout(self._root)
        root_v.setContentsMargins(0, 0, 0, 0)
        root_v.setSpacing(0)
        self._root.setStyleSheet("background:#FFFFFF;")

        self.stage = QWidget(self._root)
        self.stage.setObjectName("Stage")
        stage_v = QVBoxLayout(self.stage)
        stage_v.setContentsMargins(0, 0, 0, 0)
        stage_v.setSpacing(0)
        stage_v.addWidget(self.router)
        root_v.addWidget(self.stage, 0, Qt.AlignCenter)

        self.setCentralWidget(self._root)
        self.router.go("intro")

        # 전역 가상키보드
        self.kbd_sheet = KeyboardSheet(self.theme, parent=self)
        self.kbd_sheet.hide()

        # F10 설정
        sc = QShortcut(QKeySequence("F10"), self)
        sc.setContext(Qt.ApplicationShortcut)
        sc.activated.connect(lambda: open_settings(self, theme=self.theme))

        # ESC로 닫기
        QShortcut(QKeySequence("Esc"), self, activated=self.close)

        # F12: 디버그 외곽선 토글
        self._debug_outline = False
        sc_f12 = QShortcut(QKeySequence("F12"), self)
        sc_f12.setContext(Qt.ApplicationShortcut)
        sc_f12.activated.connect(self._toggle_debug_outline)

        # F7: 테스트 페이지 빠른진입
        sc_f7 = QShortcut(QKeySequence("F7"), self)
        sc_f7.setContext(Qt.ApplicationShortcut)
        sc_f7.activated.connect(self._dev_jump_print_view)

        # 드래그 금지 상태
        self._drag_active = False
        self._drag_offset = QPoint(0, 0)

        # ✅ 시작: 작업표시줄 무시 + 9:16 세로 꽉참 + 항상 위 + 드래그 금지
        self.start_kiosk_916_topmost()

    def start_kiosk_916_topmost(self, screen_index: int | None = None):
        self.setMinimumSize(0, 0)
        self.setMaximumSize(16777215, 16777215)
        self.setWindowFlag(Qt.FramelessWindowHint, True)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setAttribute(Qt.WA_TranslucentBackground, False)
        self.showFullScreen()
        self._apply_916_fill_height()

    def _apply_916_fill_height(self):
        sc = self.screen()
        if not sc:
            return
        g = sc.geometry()
        sw, sh = g.width(), g.height()
        stage_h = sh
        stage_w = int(round(stage_h * 9 / 16))
        if stage_w > sw:
            stage_w = sw
            stage_h = int(round(stage_w * 16 / 9))
        if hasattr(self, 'stage') and self.stage:
            self.stage.setFixedSize(stage_w, stage_h)
            bw = self._scaled_debug_border() if getattr(self, "_debug_outline", False) else 0
            border_css = f"border: {bw}px solid #0B3D91;" if bw else "border: none;"
            self.stage.setStyleSheet(f"background:#FFFFFF; {border_css}")
        if getattr(self, 'kbd_sheet', None) and self.kbd_sheet.isVisible():
            self.kbd_sheet._reposition_overlay()
            self.kbd_sheet.raise_()

    def _scaled_debug_border(self) -> int:
        """
        - 2px 보더를 티어 기준으로 스케일
        - FHD:2px, QHD:3px, UHD:4px
        """
        try:
            tier = self.display.tier if self.display else "FHD"
            return max(1, scale_px_by_tier(2, tier))
        except Exception:
            return 2

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_916_fill_height()

    def _toggle_debug_outline(self):
        self._debug_outline = not getattr(self, "_debug_outline", False)
        if hasattr(self, 'stage') and self.stage:
            if self._debug_outline:
                bw = self._scaled_debug_border()
                border_css = f"border: {bw}px solid #0B3D91;"
            else:
                border_css = "border: none;"
            self.stage.setStyleSheet(f"background:#FFFFFF; {border_css}")

    def _toggle_dev_flag(self):
        self._dev_enabled = not getattr(self, "_dev_enabled", False)
        self.setWindowTitle("photostudio [DEV]" if self._dev_enabled else "photostudio")
        if self._dev_enabled:
            self._dev_quickstart(force=True)

    def _dev_jump_print_view(self):
        try:
            self.session.setdefault("name", "TEST")
            self.session.setdefault("phone", "")
            self.session.setdefault("email1", "")
            self.session.setdefault("email2", "")
            self.session.setdefault("ratio", "3040")
            self.router.go(F7_ENTRY_PAGE)
        except Exception as e:
            import traceback
            print("[F7 jump error]", e)
            traceback.print_exc()

    #───────────────────────────────
    #  TopMost 제어 (Neural 확인 등에서 사용)
    #───────────────────────────────
   # app/main_window.py

    

    def set_topmost(self, enabled: bool, *, no_activate: bool = True):
        """항상 위 토글 (창 활성화/포커스 훔치지 않음)."""
        try:
            hwnd = int(self.winId())
        except Exception:
            return

        user32 = windll.user32
        HWND_TOPMOST     = wintypes.HWND(-1)
        HWND_NOTOPMOST   = wintypes.HWND(-2)
        SWP_NOSIZE       = 0x0001
        SWP_NOMOVE       = 0x0002
        SWP_NOZORDER     = 0x0004
        SWP_NOACTIVATE   = 0x0010
        SWP_NOREPOSITION = 0x0200  # 일부 환경에서 깜빡임 감소

        flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOREPOSITION
        if no_activate:
            flags |= SWP_NOACTIVATE

        # Qt 플래그는 내부 상태만 맞춰두고, 실제 토글은 WinAPI로 (show() 금지)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)

        user32.SetWindowPos(
            hwnd,
            HWND_TOPMOST if enabled else HWND_NOTOPMOST,
            0, 0, 0, 0,
            flags
        )
