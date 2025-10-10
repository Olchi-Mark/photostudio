# app/ui/router.py
# -*- coding: utf-8 -*-
from __future__ import annotations
from collections import OrderedDict
from typing import Callable, Dict, List, Tuple, Optional

from PySide6.QtCore import Slot
from PySide6.QtWidgets import QWidget, QStackedWidget, QVBoxLayout

PageFactory = Callable[[object, dict], QWidget]  # (theme, session) -> Page

class PageRouter(QWidget):
    """
    중앙 라우터. QStackedWidget 내부에서 next/prev/go(<name>) 전환을 담당.
    """
    def __init__(
        self,
        theme,
        session: dict,
        routes: List[Tuple[str, PageFactory | type]],
        on_index_changed=None,
        parent: QWidget | None = None,
    ):
        super().__init__(parent)
        self._theme = theme
        self._session = session
        self._on_index_changed = on_index_changed

        # name -> factory 매핑
        self._routes = OrderedDict()
        for name, factory in routes:
            if isinstance(factory, type):
                # 클래스가 넘어오면 (theme, session) 시그니처로 감싼다
                self._routes[name] = lambda t, s, _f=factory: _f(t, s)  # type: ignore
            else:
                self._routes[name] = factory

        self._names: List[str] = list(self._routes.keys())
        self._pages: Dict[str, QWidget] = {}
        self._idx = 0

        self.stack = QStackedWidget(self)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.stack)

        # 페이지에서 라우터를 역참조할 수 있게 표시자 제공
        self._router_marker = True

        # 디버그 출력 대상 키(기본): next/prev 시 콘솔에 스냅샷 출력
        self._debug_keys: List[str] = ["name", "phone", "email1", "email2", "ratio"]
    # ---------- Debug helpers ----------
    def set_debug_keys(self, keys: List[str]):
        """세션 디버그 출력 대상 키를 설정한다."""
        self._debug_keys = list(keys)

    def debug_snapshot(self, keys: Optional[List[str]] = None) -> Dict[str, object]:
        """세션에서 선택 키만 추려 dict로 반환. 콘솔 외 UI 디버그 패널에서도 재사용 가능."""
        use = list(keys) if keys is not None else list(getattr(self, "_debug_keys", []))
        snap: Dict[str, object] = {}
        for k in use:
            try:
                snap[k] = self._session.get(k, None)
            except Exception:
                snap[k] = None
        return snap

    def _debug_session(self, keys: Optional[List[str]] = None) -> None:
        try:
            snap = self.debug_snapshot(keys)
            print("[SESSION]", snap)
        except Exception:
            pass

    # ---------- Public API ----------
    def go(self, name: str):
        if name not in self._routes:
            return
        idx = self._names.index(name)
        self._ensure_page(name)
        self._switch_to(idx)

    @Slot()
    def next(self):
        if self._idx + 1 >= len(self._names):
            return
        # 디버그 스냅샷 출력
        self._debug_session()
        # 현재 페이지 훅 호출(필요 시 초기화 등)
        cur = self.stack.currentWidget()
        hook = getattr(cur, "on_before_next", None)
        if callable(hook) and hook(self._session) is False:
            return
        name = self._names[self._idx + 1]
        self._ensure_page(name)
        self._switch_to(self._idx + 1)

    @Slot()
    def prev(self):
        if self._idx - 1 < 0:
            return
        # 디버그 스냅샷 출력
        self._debug_session()
        # 현재 페이지 훅 호출(이전으로 가기 전 초기화 등)
        cur = self.stack.currentWidget()
        hook = getattr(cur, "on_before_prev", None)
        if callable(hook) and hook(self._session) is False:
            return
        name = self._names[self._idx - 1]
        self._ensure_page(name)
        self._switch_to(self._idx - 1)

    def current_name(self) -> str:
        return self._names[self._idx]

    # ---------- Internals ----------
    def _ensure_page(self, name: str):
        if name in self._pages:
            return
        page = self._routes[name](self._theme, self._session)
        setattr(page, "_router", self)  # 역참조 제공
        # 각 페이지의 표준 신호(go_prev/go_next)가 있으면 라우터에 연결
        for sig_name, slot in (("go_prev", self.prev), ("go_next", self.next)):
            sig = getattr(page, sig_name, None)
            if sig is not None:
                try:
                    sig.connect(slot)  # type: ignore
                except Exception:
                    pass
        self.stack.addWidget(page)
        self._pages[name] = page

    def _switch_to(self, idx: int):
        old = self.stack.currentWidget()
        new = self._pages[self._names[idx]]

        if old:
            hook = getattr(old, "before_leave", None)
            if callable(hook) and hook(self._session) is False:
                return

        hook = getattr(new, "before_enter", None)
        if callable(hook) and hook(self._session) is False:
            return

        self.stack.setCurrentWidget(new)
        self._idx = idx
        if callable(self._on_index_changed):
            self._on_index_changed(idx)

# --- 유틸: 아무 위젯에서든 라우터 획득 ---
def find_router(w: QWidget) -> Optional[PageRouter]:
    p = w
    while p is not None:
        if isinstance(p, PageRouter):
            return p
        if getattr(p, "_router_marker", False):
            return getattr(p, "_router", None)
        p = p.parent()
    return None
