"""
app/ui/ai_overlay.py

Role: Standalone overlay widget that renders AI guides on top of the live camera preview.
Status: Overlay + hole-binding complete.

Change Log:
- 2025-09-18: Converted to independent QWidget (removed BasePage hooks).
- 2025-09-18: Added hole-binding API and odd-even path masking.
"""


# stdlib
from typing import Optional, Tuple

# Qt
from PySide6.QtCore import Qt, QRectF, QPointF, Slot, QObject, QPoint, Signal
from PySide6.QtGui import QPainter, QPen, QBrush, QPainterPath
from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QApplication, QPushButton, QFileDialog, QFrame

# === Overlay Canvas ==========================================================
class OverlayCanvas(QWidget):
    """Paint-only widget that draws guides on top of camera preview.

    Responsibilities:
    - Maintain target aspect ratio (e.g., 3:4 or 35:45)
    - Draw safe-areas and helper lines without owning camera frames
    - React to runtime token changes (colors, stroke, scale)
    - Support a fixed "hole" rectangle to leave transparent (preview box exact bounds)
    """

    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self._ratio: Tuple[int, int] = (3, 4)
        self._hole_rect: Optional[QRectF] = None
        self._TOK = {
            "guide_color": (255, 255, 255, 180),
            "mask_color": (238, 238, 238, 255),  # 90% transparent white
            "stroke": 3,
            "round": 0,
            "grid_alpha": 120,
            "scale": 1.0,
            # landmark tokens
            "pt_core": (46, 125, 50, 230),
            "pt_pro": (255, 255, 255, 90),      # faint white
            "pro_mode": False,      # green
            "pt_chin": (76, 175, 80, 230),      # light green
            "pt_eye": (3, 169, 244, 230),       # cyan
            "pt_nose": (67, 160, 71, 230),      # greenish
            "pt_shoulder": (255, 215, 64, 230),  # amber for shoulders
            "pt_pro": (255, 255, 255, 90),      # faint white
            "pt_radius": 0,
            # dash options
            "dash_guide": True,
            "dash_shoulder": True,
            "dash_chin": True,
            "dash_color": (204, 204, 204, 255),  # light gray for dashed lines
            "dash_width": 1,
            "show_guide": False,
        }

    # --- Tokens & Debug ------------------------------------------------------
    def refresh_tokens(self, TOK: dict) -> None:
        """Apply token bag and trigger repaint."""
        self._TOK.update(TOK or {})
        self.update()

    # Debug flag for crosshair
    def set_debug_cross(self, enable: bool) -> None:
        self._dbg_cross = bool(enable)
        self.update()

    # Back-compat helper for old callers
    def set_mask_color(self, rgb: Tuple[int, int, int] = (255, 255, 255), alpha: int = 26) -> None:
        r, g, b = rgb
        a = int(max(0, min(255, alpha)))
        self._TOK["mask_color"] = (int(r), int(g), int(b), a)
        self.update()

    # --- Landmarks API -------------------------------------------------------
    def clear_landmarks(self) -> None:
        self._lm_payload = None
        self._lm_normalized = False
        self.update()

    def set_landmarks(self, payload: dict, normalized: bool = False) -> None:
        """payload keys (optional):
        - core: {name: (x,y), ...}
        - chin_ring: [(x,y), ...]
        - eye_support: {"left": [(x,y)*4], "right": [(x,y)*4]}
        - nose_support: [(x,y)*2]
        - pro_mesh: [(x,y), ...]  # many points
        If `normalized` True, (x,y) are in 0..1 of preview frame.
        Coordinates are mapped into overlay coords using the current hole rect.
        """
        self._lm_payload = payload or None
        self._lm_normalized = bool(normalized)
        self.update()

    # --- Ratio / Hole --------------------------------------------------------
    def set_ratio(self, w: int, h: int) -> None:
        if w <= 0 or h <= 0:
            return
        self._ratio = (int(w), int(h))
        self.update()

    def set_hole_rect(self, rect: Optional[QRectF]) -> None:
        self._hole_rect = rect
        self.update()

    # --- Utils ---------------------------------------------------------------
    def _rgba(self, tup: Tuple[int, int, int, int]):
        from PySide6.QtGui import QColor
        r, g, b, a = tup
        return QColor(int(r), int(g), int(b), int(a))

    def _map_pt(self, p: Tuple[float, float], hole: QRectF, normalized: bool) -> QPointF:
        x, y = float(p[0]), float(p[1])
        if normalized:
            return QPointF(hole.left() + x * hole.width(), hole.top() + y * hole.height())
        return QPointF(hole.left() + x, hole.top() + y)

    def _paint_landmarks(self, painter: QPainter, hole: QRectF) -> None:
        norm = getattr(self, "_lm_normalized", False)
        payload = getattr(self, "_lm_payload", None) or {}
        r = float(self._TOK.get("pt_radius", 3))

        def draw_pts(pts, color):
            if not pts:
                return
            # tiny-dot mode: diameter 3px (no outline)
            if r <= 0:
                qcolor = self._rgba(color)
                painter.setPen(Qt.NoPen)
                painter.setBrush(qcolor)
                for p in pts:
                    qpt = self._map_pt(p, hole, norm)
                    painter.drawEllipse(qpt, 1.5, 1.5)
                return
            # outer ring for contrast
            oc = self._rgba((0, 0, 0, 255))
            pen_o = QPen(oc); pen_o.setWidth(2)
            painter.setPen(pen_o); painter.setBrush(Qt.NoBrush)
            for p in pts:
                qpt = self._map_pt(p, hole, norm)
                painter.drawEllipse(qpt, r+1.5, r+1.5)
            # inner fill
            qcolor = self._rgba(color)
            pen_i = QPen(qcolor); pen_i.setWidth(1)
            painter.setPen(pen_i); painter.setBrush(qcolor)
            for p in pts:
                qpt = self._map_pt(p, hole, norm)
                painter.drawEllipse(qpt, r, r)

        def draw_poly(pts, color, width=2, dashed=False):
            if not pts or len(pts) < 2:
                return
            qpts = [self._map_pt(p, hole, norm) for p in pts]
            if dashed:
                color = self._TOK.get("dash_color", (204, 204, 204, 255))
                width = int(self._TOK.get("dash_width", 1))
            pen = QPen(self._rgba(color)); pen.setWidth(width)
            if dashed:
                pen.setStyle(Qt.DashLine)
                try:
                    pen.setDashPattern([6, 4])
                except Exception:
                    pass
            painter.setPen(pen); painter.setBrush(Qt.NoBrush)
            from PySide6.QtGui import QPainterPath
            path = QPainterPath(qpts[0])
            for q in qpts[1:]:
                path.lineTo(q)
            painter.drawPath(path)

        # pro mesh first (faint)
        if bool(self._TOK.get("pro_mode", False)):
            draw_pts(payload.get("pro_mesh"), self._TOK.get("pt_pro"))
        # chin ring as points + optional dashed poly
        chin = payload.get("chin_ring")
        draw_pts(chin, self._TOK.get("pt_chin"))
        draw_poly(chin, self._TOK.get("pt_chin"), width=1, dashed=bool(self._TOK.get("dash_chin", True)))
        eye = payload.get("eye_support") or {}
        draw_pts(eye.get("left"), self._TOK.get("pt_eye"))
        draw_pts(eye.get("right"), self._TOK.get("pt_eye"))
        draw_pts(payload.get("nose_support"), self._TOK.get("pt_nose"))
        spts = payload.get("shoulder_support")
        draw_pts(spts, self._TOK.get("pt_shoulder"))
        draw_poly(spts, self._TOK.get("pt_shoulder"), width=1, dashed=bool(self._TOK.get("dash_shoulder", True)))
        core = payload.get("core") or {}
        draw_pts(core.values() if isinstance(core, dict) else core, self._TOK.get("pt_core"))

    # --- Paint ---------------------------------------------------------------
    def paintEvent(self, ev) -> None:  # noqa: N802(Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        try:
            W, H = self.width(), self.height()

            # 구멍 영역 계산
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

            # 1) 마스크 채우기(구멍 없으면 전체 채움)
            mc = self._TOK.get("mask_color", (238, 238, 238, 255))
            hole = self._hole_rect
            if hole is None or hole.width() <= 0 or hole.height() <= 0:
                painter.fillRect(0, 0, W, H, self._rgba(mc))
                # 디버그: 마스크가 안 보일 때 크기 확인
                # print(f"[OverlayCanvas] mask-only W={W} H={H} mc={mc}")
                return
            outer = QPainterPath(); outer.addRect(0, 0, float(W), float(H))
            radius = float(self._TOK.get("round", 0))
            hole_path = QPainterPath()
            if radius > 0:
                hole_path.addRoundedRect(hole, radius, radius)
            else:
                hole_path.addRect(hole)
            outer.addPath(hole_path)
            outer.setFillRule(Qt.OddEvenFill)
            painter.fillPath(outer, self._rgba(mc))

            guide_rect = QRectF(hole)

            # 2) 가이드 프레임 (옵션)
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
                painter.setPen(pen)
                painter.setBrush(Qt.NoBrush)
                radius = float(self._TOK.get("round", 0))
                if radius > 0:
                    painter.drawRoundedRect(guide_rect, radius, radius)
                else:
                    painter.drawRect(guide_rect)

            # 2.5) debug crosshair if enabled
            if getattr(self, "_dbg_cross", False):
                center = guide_rect.center()
                pen = QPen(self._rgba((255, 0, 0, 255)))
                pen.setWidth(2)
                painter.setPen(pen)
                painter.drawLine(center.x()-24, center.y(), center.x()+24, center.y())
                painter.drawLine(center.x(), center.y()-24, center.x(), center.y()+24)

            # 3) 랜드마크 점 렌더
            payload = getattr(self, "_lm_payload", None)
            if payload:
                self._paint_landmarks(painter, guide_rect)
        finally:
            painter.end()
# === Public Overlay Widget ===================================================

class AiOverlay(QWidget):
    """Standalone overlay host used by capture.py.
    - Owns an OverlayCanvas and exposes a small API expected by capture.
    - Mesh/Pose engines are optional; if not wired, methods no-op safely.
    """
    def __init__(self, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.setObjectName("AiOverlay")
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self._overlay = OverlayCanvas(self)
        lay.addWidget(self._overlay, 1)
        # anchors
        self._anchor = None  # QWidget to bind the hole

    # --- Public API expected by capture.py ---------------------------------
    def refresh_tokens(self, tok: dict) -> None:
        self._overlay.refresh_tokens(tok or {})

    def set_mask_color(self, rgb: Tuple[int, int, int] = (238, 238, 238), alpha: int = 255) -> None:
        self._overlay.set_mask_color(rgb, alpha)

    def set_ratio(self, w: int, h: int) -> None:
        self._overlay.set_ratio(w, h)

    def set_ratio_from_session(self, ratio: str) -> None:
        if str(ratio) == "3545":
            self.set_ratio(35, 45)
        else:
            self.set_ratio(3, 4)

    def bind_hole_widget(self, widget: QWidget, shrink_px: int = 3) -> None:
        """Bind transparent hole to a target widget on the same window."""
        if widget is None:
            self._overlay.set_hole_rect(None)
            self._anchor = None
            return
        self._anchor = widget
        self._update_hole_from_anchor(shrink_px)

    def clear_hole(self) -> None:
        self._overlay.set_hole_rect(None)

    def update_landmarks(self, payload: dict, normalized: bool = True) -> None:
        self._overlay.set_landmarks(payload or {}, normalized=normalized)

    def clear_landmarks(self) -> None:
        self._overlay.clear_landmarks()

    # Stubs for compatibility (mesh/pose engines can be integrated later)
    def set_model_path(self, path: str) -> None:
        print(f"[AiOverlay] set_model_path ignored in stub: {path}")

    def set_pose_model_path(self, path: str) -> None:
        print(f"[AiOverlay] set_pose_model_path ignored in stub: {path}")

    def start_mesh(self, backend: str = "mediapipe") -> None:
        print(f"[AiOverlay] start_mesh stub: backend={backend}")

    def stop_mesh(self) -> None:
        print("[AiOverlay] stop_mesh stub")

    def ingest_frame(self, frame: object, size: Tuple[int, int]) -> None:
        # No-op in stub. Engines can hook here later.
        pass

    # --- Internal helpers ---------------------------------------------------
    def _update_hole_from_anchor(self, shrink_px: int = 3) -> None:
        if not self._anchor or not self._anchor.isVisible():
            return
        # map anchor rect to this overlay's coordinates
        top_left = self.mapFromGlobal(self._anchor.mapToGlobal(QPoint(0, 0)))
        w = self._anchor.width(); h = self._anchor.height()
        x = max(0, top_left.x() + shrink_px)
        y = max(0, top_left.y() + shrink_px)
        rw = max(0, w - 2 * shrink_px)
        rh = max(0, h - 2 * shrink_px)
        self._overlay.set_hole_rect(QRectF(float(x), float(y), float(rw), float(rh)))

    def resizeEvent(self, ev):  # noqa: N802(Qt)
        super().resizeEvent(ev)
        self._update_hole_from_anchor()

# (Engines removed from this module.)


# --- Pro mesh toggle API ---
def set_pro_mode(self, on: bool) -> None:
    try:
        self._overlay._TOK["pro_mode"] = bool(on)
        self._overlay.update()
    except Exception:
        pass
