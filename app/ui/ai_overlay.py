"""
app/ui/ai_overlay.py ???덉젙??踰꾩쟾(?섏씤???뺢퇋??
??븷: ?쇱씠釉뚮럭 ?꾩뿉 媛?대뱶/留덉뒪???쒕뱶留덊겕瑜?洹몃━???ㅻ쾭?덉씠 ?꾩젽

洹쒖튃
- paintEvent ?대??먯꽌??QPainter 蹂??`qp`留??ъ슜?쒕떎.
- paintEvent 以?geometry/show/update ?몄텧 湲덉?(源쒕묀?꽷룹옱吏꾩엯 諛⑹?).
- 蹂댁“ 洹몃━湲??⑥닔????QPainter瑜?留뚮뱾吏 ?딄퀬 ?꾨떖諛쏆? `qp`留??ъ슜?쒕떎.
"""

from __future__ import annotations

from typing import Optional, Tuple, Dict, Any, Iterable

from PySide6.QtCore import Qt, QRectF, QPointF
from PySide6.QtGui import QPainter, QPen, QPainterPath, QColor
from PySide6.QtWidgets import QWidget, QVBoxLayout


class OverlayCanvas(QWidget):
    """移대찓???꾨━酉??꾩뿉 媛?대뱶瑜?洹몃━???섏씤???꾩슜 ?꾩젽."""
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
            # ?쒕뱶留덊겕 ?됱긽
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

    # ?ㅼ젙/?좏겙 ----------------------------------------------------------------
    def refresh_tokens(self, TOK: dict) -> None:
        """?좏겙 媛??곸슜 ??由ы럹?명듃 ?붿껌."""
        self._TOK.update(TOK or {})
        self.update()

    def set_debug_cross(self, enable: bool) -> None:
        """?붾쾭洹???옄???쒖떆 ?좉?."""
        self._dbg_cross = bool(enable)
        self.update()

    def set_mask_color(self, rgb=(255, 255, 255), alpha: int = 26) -> None:
        """留덉뒪???됱긽???ㅼ젙?쒕떎(QColor ?먮뒗 (r,g,b))."""
        if isinstance(rgb, QColor):
            c = rgb
            self._TOK["mask_color"] = (c.red(), c.green(), c.blue(), c.alpha())
        else:
            r, g, b = rgb
            a = int(max(0, min(255, alpha)))
            self._TOK["mask_color"] = (int(r), int(g), int(b), a)
        self.update()

    def set_badge(self, text: str) -> None:
        """?ㅻ쾭?덉씠 ?곷떒 諛곗? 臾멸뎄 ?ㅼ젙."""
        self._badge_text = str(text or "")
        self.update()

    # ?쒕뱶留덊겕 -----------------------------------------------------------------
    def clear_landmarks(self) -> None:
        """?쒕뱶留덊겕/?뺢퇋???뚮옒洹?珥덇린??"""
        self._lm_payload = None
        self._lm_normalized = False
        self.update()

    def set_landmarks(self, payload: dict, normalized: bool = False) -> None:
        """?쒕뱶留덊겕/?뺢퇋???뚮옒洹??ㅼ젙."""
        self._lm_payload = payload or None
        self._lm_normalized = bool(normalized)
        self.update()

    # 鍮꾩쑉/? ------------------------------------------------------------------
    def set_ratio(self, w: int, h: int) -> None:
        """媛?대뱶 鍮꾩쑉???ㅼ젙?쒕떎."""
        if w > 0 and h > 0:
            self._ratio = (int(w), int(h))
            self.update()

    def set_hole_rect(self, rect: Optional[QRectF]) -> None:
        """?꾨━酉??곸뿭(hole) ?ш컖?뺤쓣 ?ㅼ젙?쒕떎."""
        self._hole_rect = rect
        self.update()

    # ?좏떥 ---------------------------------------------------------------------
    def _rgba(self, tup: Tuple[int, int, int, int]) -> QColor:
        r, g, b, a = tup
        return QColor(int(r), int(g), int(b), int(a))

    def _map_pt(self, p: Tuple[float, float], hole: QRectF, normalized: bool) -> QPointF:
        x, y = float(p[0]), float(p[1])
        if normalized:
            return QPointF(hole.left() + x * hole.width(), hole.top() + y * hole.height())
        return QPointF(hole.left() + x, hole.top() + y)

    def _paint_landmarks(self, qp: QPainter, hole: QRectF) -> None:
        """?쒕뱶留덊겕瑜?qp濡?洹몃┛?????섏씤???앹꽦 湲덉?)."""
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

        def draw_poly(points: Optional[Iterable[Tuple[float, float]]], color_rgba, w: int = 2, closed: bool = True, fill: Optional[Tuple[int, int, int, int]] = None):
            if not points:
                return
            pen = QPen(self._rgba(color_rgba))
            pen.setWidth(int(w))
            qp.setPen(pen)
            qp.setBrush(Qt.NoBrush if not fill else self._rgba(fill))
            pts = [self._map_pt(p, hole, normalized) for p in points]
            if len(pts) < 2:
                for pt in pts:
                    qp.drawPoint(pt)
                return
            path = QPainterPath()
            path.moveTo(pts[0])
            for pt in pts[1:]:
                path.lineTo(pt)
            if closed:
                path.closeSubpath()
            if fill:
                qp.fillPath(path, self._rgba(fill))
            qp.drawPath(path)

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

        # polygons / polylines / bbox / labels (optional payload keys)
        polys = payload.get("polygons") or []
        for poly in polys:
            draw_poly(poly, self._TOK.get("pt_core"), w=int(self._TOK.get("stroke", 3)), closed=True)
        lines = payload.get("polylines") or []
        for ln in lines:
            draw_poly(ln, self._TOK.get("pt_eye"), w=2, closed=False)
        bbox = payload.get("bbox")
        if bbox and isinstance(bbox, (list, tuple)) and len(bbox) == 4:
            x, y, w, h = [float(v) for v in bbox]
            p0 = self._map_pt((x, y), hole, normalized)
            p1 = self._map_pt((x + w, y + h), hole, normalized)
            pen = QPen(self._rgba(self._TOK.get("pt_core")))
            pen.setWidth(int(self._TOK.get("stroke", 3)))
            qp.setPen(pen)
            qp.setBrush(Qt.NoBrush)
            qp.drawRect(QRectF(p0, p1))
        labels = payload.get("labels") or []
        try:
            for item in labels:
                txt = str(item.get("text", ""))
                pos = item.get("pos", (0.0, 0.0))
                pt = self._map_pt(pos, hole, normalized)
                pen = QPen(QColor(255, 255, 255, 230))
                pen.setWidth(1)
                qp.setPen(pen)
                qp.drawText(pt, txt)
        except Exception:
            pass

    # ?섏씤??-------------------------------------------------------------------
    def paintEvent(self, ev) -> None:  # noqa
        """qp ?섎굹留??ъ슜. paint 以?geometry/show/update ?몄텧 湲덉?."""
        qp = QPainter()
        if not qp.begin(self):
            return
        try:
            try:
                qp.setRenderHint(QPainter.Antialiasing, True)
            except Exception:
                pass

            # ?꾩슂 ??hole留?媛깆떊(geometry 蹂寃쎌? paint?먯꽌 湲덉?)
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

            # 留덉뒪??梨꾩슦湲?媛?대뱶 ?쒖쇅)
            mc = self._TOK.get("mask_color", (238, 238, 238, 255))
            hole = self._hole_rect
            # 援щ찉(hole)???좏슚?섏? ?딆쑝硫??꾨Т 寃껊룄 洹몃━吏 ?딅뒗??湲곕낯 ?щ챸)
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

            # 媛?대뱶 ?ш컖???듭뀡)
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

            # ?붾쾭洹???옄???듭뀡)
            if self._dbg_cross:
                center = guide_rect.center()
                pen = QPen(self._rgba((255, 0, 0, 255)))
                pen.setWidth(2)
                qp.setPen(pen)
                qp.drawLine(center.x() - 24, center.y(), center.x() + 24, center.y())
                qp.drawLine(center.x(), center.y() - 24, center.x(), center.y() + 24)

            # ?쒕뱶留덊겕
            if self._lm_payload:
                self._paint_landmarks(qp, guide_rect)

            # 諛곗? ?띿뒪??            if self._badge_text:
                pen = QPen(QColor(255, 255, 255, 230))
                pen.setWidth(1)
                qp.setPen(pen)
                align = Qt.AlignCenter if bool(self._TOK.get("badge_center", False)) else (Qt.AlignLeft | Qt.AlignTop)
                # 배지를 정확히 중앙에 두기 위해 패딩을 제거한다.
                qp.drawText((QRectF(self._hole_rect) if (self._hole_rect is not None and self._hole_rect.width() > 0 and self._hole_rect.height() > 0) else guide_rect).adjusted(0, 0, 0, 0), align, self._badge_text)
        except Exception as ex:
            print("[OV] paint error:", ex)
        finally:
            if qp.isActive():
                qp.end()


class AiOverlay(QWidget):
    """罹≪쿂 ?섏씠吏?먯꽌 ?ъ슜?섎뒗 ?ㅻ쾭?덉씠 ?섑띁 ?꾩젽(?덉젙??."""
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

    # capture.py?먯꽌 湲곕??섎뒗 API ------------------------------------------------
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

    def set_debug_cross(self, enable: bool) -> None:
        """중앙 십자 디버그 표시를 켠다/끈다."""
        self._overlay.set_debug_cross(enable)

    def set_badge_center(self, on: bool = True) -> None:
        """배지 텍스트를 중앙 정렬로 표시한다."""
        self._overlay.refresh_tokens({"badge_center": bool(on)})

    # ?대? ?좏떥 ------------------------------------------------------------------
    # 바인딩된 위젯의 좌표를 오버레이 좌표로 변환하여 홀 사각형을 갱신한다.
    def _recalc_hole_from_widget(self) -> None:
        try:
            if self._hole_widget is not None:
                w = self._hole_widget
                r = w.geometry()
                # ?꾩뿭 醫뚰몴濡?蹂???? ?ㅻ쾭?덉씠 醫뚰몴濡??????                g_tl = w.mapToGlobal(r.topLeft())
                g_br = w.mapToGlobal(r.bottomRight())
                tl = self.mapFromGlobal(g_tl)
                br = self.mapFromGlobal(g_br)
                from PySide6.QtCore import QRect
                rect = QRect(tl, br)
                s = int(self._hole_shrink or 0)
                if s > 0:
                                    rect.adjust(s, s, -s, -s)
                # 오프셋 보정: 기본 -2px, 환경변수 PS_HOLE_OFF로 오버라이드
                try:
                    import os as _os
                    _off = int(str(_os.getenv("PS_HOLE_OFF", "-2")).strip())
                except Exception:
                    _off = -2
                rect.adjust(_off, _off, 0, 0)
                self._overlay.set_hole_rect(rect)
                # z-순서 최상단 유지 시도
                try:
                    self.raise_()
                except Exception:
                    pass
        except Exception:
            pass

    def resizeEvent(self, ev) -> None:  # noqa: N802
        super().resizeEvent(ev)
        self._recalc_hole_from_widget()

