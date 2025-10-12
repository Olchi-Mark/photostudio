"""
app/ui/ai_overlay.py — 안정화 버전(페인터 정규화)
역할: 라이브뷰 위에 가이드/마스크/랜드마크를 그리는 오버레이 위젯

규칙
- paintEvent 내부에서는 QPainter 변수 `qp`만 사용한다.
- paintEvent 중 geometry/show/update 호출 금지(깜빡임·재진입 방지).
- 보조 그리기 함수는 새 QPainter를 만들지 않고 전달받은 `qp`만 사용한다.
"""

from __future__ import annotations

from typing import Optional, Tuple, Dict, Any, Iterable

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QPainterPath, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout


class OverlayCanvas(QWidget):
    """카메라 프리뷰 위에 가이드를 그리는 페인트 전용 위젯."""
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._ratio: Tuple[int, int] = (3, 4)
        self._hole_rect: Optional[QRectF] = None
        self._TOK: Dict[str, Any] = {
            "mask_color": (238, 238, 238, 255),
            "guide_color": (255, 255, 255, 180),
            "stroke": 3,
            "round": 0,
            "dash_guide": True,
            "dash_color": (204, 204, 204, 255),
            "dash_width": 1,
            "show_guide": False,
            # 랜드마크 색상
            "pt_core": (46, 125, 50, 230),
            "pt_chin": (76, 175, 80, 230),
            "pt_eye": (3, 169, 244, 230),
            "pt_nose": (67, 160, 71, 230),
            "pt_shoulder": (255, 215, 64, 230),
            "pt_pro": (255, 255, 255, 90),
        }
        self._lm_payload: Optional[Dict[str, Any]] = None
        self._lm_normalized: bool = False
        self._dbg_cross: bool = False
        self._badge_text: str = ""

    # 설정/토큰 ----------------------------------------------------------------
    def refresh_tokens(self, TOK: dict) -> None:
        """토큰 값 적용 후 리페인트 요청."""
        self._TOK.update(TOK or {})
        self.update()

    def set_debug_cross(self, enable: bool) -> None:
        """디버그 십자선 표시 토글."""
        self._dbg_cross = bool(enable)
        self.update()

    def set_mask_color(self, rgb=(255, 255, 255), alpha: int = 26) -> None:
        """마스크 색상을 설정한다(QColor 또는 (r,g,b))."""
        if isinstance(rgb, QColor):
            c = rgb
            self._TOK["mask_color"] = (c.red(), c.green(), c.blue(), c.alpha())
        else:
            r, g, b = rgb
            a = int(max(0, min(255, alpha)))
            self._TOK["mask_color"] = (int(r), int(g), int(b), a)
        self.update()

    def set_badge(self, text: str) -> None:
        """오버레이 상단 배지 문구 설정."""
        self._badge_text = str(text or "")
        self.update()

    # 랜드마크 -----------------------------------------------------------------
    def clear_landmarks(self) -> None:
        """랜드마크/정규화 플래그 초기화."""
        self._lm_payload = None
        self._lm_normalized = False
        self.update()

    def set_landmarks(self, payload: dict, normalized: bool = False) -> None:
        """랜드마크/정규화 플래그 설정."""
        self._lm_payload = payload or None
        self._lm_normalized = bool(normalized)
        self.update()

    # 비율/홀 ------------------------------------------------------------------
    def set_ratio(self, w: int, h: int) -> None:
        """가이드 비율을 설정한다."""
        if w > 0 and h > 0:
            self._ratio = (int(w), int(h))
            self.update()

    def set_hole_rect(self, rect: Optional[QRectF]) -> None:
        """프리뷰 영역(hole) 사각형을 설정한다."""
        self._hole_rect = rect
        self.update()

    # 유틸 ---------------------------------------------------------------------
    def _rgba(self, tup: Tuple[int, int, int, int]) -> QColor:
        r, g, b, a = tup
        return QColor(int(r), int(g), int(b), int(a))

    def _map_pt(self, p: Tuple[float, float], hole: QRectF, normalized: bool) -> QPointF:
        x, y = float(p[0]), float(p[1])
        if normalized:
            return QPointF(hole.left() + x * hole.width(), hole.top() + y * hole.height())
        return QPointF(hole.left() + x, hole.top() + y)

    def _paint_landmarks(self, qp: QPainter, hole: QRectF) -> None:
        """랜드마크를 qp로 그린다(새 페인터 생성 금지)."""
        payload = self._lm_payload or {}
        normalized = self._lm_normalized

        def draw_pts(pts: Optional[Iterable[Tuple[float, float]]], color_rgba, w: int = 3):
            if not pts:
                return
            pen = QPen(self._rgba(color_rgba))
            pen.setWidth(w)
            qp.setPen(pen)
            qp.setBrush(Qt.NoBrush)
            for p in pts:
                pt = self._map_pt(p, hole, normalized)
                qp.drawPoint(pt)

        if payload.get("pro_mesh"):
            draw_pts(payload.get("pro_mesh"), self._TOK.get("pt_pro"), 1)
        chin = payload.get("chin_ring")
        draw_pts(chin, self._TOK.get("pt_chin"), 2)
        eye = payload.get("eye_support") or {}
        draw_pts(eye.get("left"), self._TOK.get("pt_eye"), 2)
        draw_pts(eye.get("right"), self._TOK.get("pt_eye"), 2)
        draw_pts(payload.get("nose_support"), self._TOK.get("pt_nose"), 2)
        spts = payload.get("shoulder_support")
        draw_pts(spts, self._TOK.get("pt_shoulder"), 2)
        core = payload.get("core") or {}
        if isinstance(core, dict):
            draw_pts(core.values(), self._TOK.get("pt_core"), 3)
        else:
            draw_pts(core, self._TOK.get("pt_core"), 3)

    # 페인트 -------------------------------------------------------------------
    def paintEvent(self, ev) -> None:  # noqa
        """qp 하나만 사용. paint 중 geometry/show/update 호출 금지."""
        qp = QPainter()
        if not qp.begin(self):
            return
        try:
            try:
                qp.setRenderHint(QPainter.Antialiasing, True)
            except Exception:
                pass

            # 필요 시 hole만 갱신(geometry 변경은 paint에서 금지)
            try:
                if hasattr(self, "_recalc_hole_from_widget"):
                    self._recalc_hole_from_widget()
            except Exception:
                pass

            W, H = self.width(), self.height()
            if self._hole_rect is not None:
                guide_rect = QRectF(self._hole_rect)
            else:
                rw, rh = self._ratio
                target_h = H
                target_w = int(target_h * rw / rh)
                if target_w > W:
                    target_w = W
                    target_h = int(target_w * rh / rw)
                x = (W - target_w) // 2
                y = (H - target_h) // 2
                guide_rect = QRectF(x, y, target_w, target_h)

            # 마스크 채우기(가이드 제외)
            mc = self._TOK.get("mask_color", (238, 238, 238, 255))
            hole = self._hole_rect
            # 구멍(hole)이 유효하지 않으면 아무 것도 그리지 않는다(기본 투명)
            if hole is None or hole.width() <= 0 or hole.height() <= 0:
                return
            outer = QPainterPath()
            outer.addRect(0, 0, float(W), float(H))
            radius = float(self._TOK.get("round", 0))
            hole_path = QPainterPath()
            if radius > 0:
                hole_path.addRoundedRect(hole, radius, radius)
            else:
                hole_path.addRect(hole)
            outer.addPath(hole_path)
            outer.setFillRule(Qt.OddEvenFill)
            qp.fillPath(outer, self._rgba(mc))

            # 가이드 사각형(옵션)
            if bool(self._TOK.get("show_guide", False)):
                gc = self._TOK.get("guide_color", (255, 255, 255, 180))
                dashed = bool(self._TOK.get("dash_guide", False))
                color = self._TOK.get("dash_color", (204, 204, 204, 255)) if dashed else gc
                width = int(self._TOK.get("dash_width", 1)) if dashed else int(self._TOK.get("stroke", 3))
                pen = QPen(self._rgba(color))
                pen.setWidth(width)
                if dashed:
                    pen.setStyle(Qt.DashLine)
                    try:
                        pen.setDashPattern([6, 4])
                    except Exception:
                        pass
                qp.setPen(pen)
                qp.setBrush(Qt.NoBrush)
                if radius > 0:
                    qp.drawRoundedRect(guide_rect, radius, radius)
                else:
                    qp.drawRect(guide_rect)

            # 디버그 십자선(옵션)
            if self._dbg_cross:
                center = guide_rect.center()
                pen = QPen(self._rgba((255, 0, 0, 255)))
                pen.setWidth(2)
                qp.setPen(pen)
                qp.drawLine(center.x() - 24, center.y(), center.x() + 24, center.y())
                qp.drawLine(center.x(), center.y() - 24, center.x(), center.y() + 24)

            # 랜드마크
            if self._lm_payload:
                self._paint_landmarks(qp, guide_rect)

            # 배지 텍스트
            if self._badge_text:
                pen = QPen(QColor(255, 255, 255, 230))
                pen.setWidth(1)
                qp.setPen(pen)
                qp.drawText(guide_rect.adjusted(8, 8, -8, -8), Qt.AlignLeft | Qt.AlignTop, self._badge_text)
        except Exception as ex:
            print("[OV] paint error:", ex)
        finally:
            if qp.isActive():
                qp.end()


class AiOverlay(QWidget):
    """캡처 페이지에서 사용하는 오버레이 래퍼 위젯(안정화)."""
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("AiOverlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._overlay = OverlayCanvas(self)
        lay.addWidget(self._overlay, 1)
        self._hole_widget = None
        self._hole_shrink = 0
        self._hole_rect: Optional[QRectF] = None

    # capture.py에서 기대하는 API ------------------------------------------------
    def refresh_tokens(self, tok: dict) -> None:
        self._overlay.refresh_tokens(tok or {})

    def set_mask_color(self, rgb=(238, 238, 238), alpha: int = 255) -> None:
        self._overlay.set_mask_color(rgb, alpha)

    def set_ratio(self, w: int, h: int) -> None:
        self._overlay.set_ratio(w, h)

    def set_ratio_from_session(self, ratio: str) -> None:
        if str(ratio) == "3545":
            self.set_ratio(35, 45)
        else:
            self.set_ratio(3, 4)

    def bind_hole_widget(self, widget, shrink_px: int = 0) -> None:
        self._hole_widget = widget
        self._hole_shrink = int(shrink_px)
        self._hole_rect = None
        self.update()

    def update_badges(self, text: str, _metrics: dict) -> None:
        self._overlay.set_badge(text or "")

    def update_landmarks(self, payload: dict, normalized: bool = False) -> None:
        self._overlay.set_landmarks(payload, normalized)

    # 내부 유틸 ------------------------------------------------------------------
    def _recalc_hole_from_widget(self) -> None:
        try:
            if self._hole_widget is not None:
                w = self._hole_widget
                r = w.geometry()
                # 전역 좌표로 변환 후, 오버레이 좌표로 역변환
                g_tl = w.mapToGlobal(r.topLeft())
                g_br = w.mapToGlobal(r.bottomRight())
                tl = self.mapFromGlobal(g_tl)
                br = self.mapFromGlobal(g_br)
                from PySide6.QtCore import QRect
                rect = QRect(tl, br)
                s = int(self._hole_shrink or 0)
                if s > 0:
                    rect.adjust(s, s, -s, -s)
                self._overlay.set_hole_rect(rect)
        except Exception:
            pass

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self._recalc_hole_from_widget()
