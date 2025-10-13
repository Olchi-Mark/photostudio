# -*- coding: utf-8 -*-
from __future__ import annotations
import os, time, threading, logging
from pathlib import Path
from typing import Optional, Dict

from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QApplication,
    QPushButton, QButtonGroup, QLabel
)
from PySide6.QtGui import QPixmap, QImage, QFont, QPainter, QPen, QColor

from app.ui.base_page import BasePage
from app.constants import STEPS
from app.ui.ai_overlay import AiOverlay
from app.utils.image_ops import render_transformed, render_placeholder
from app.ai.guidance import Guidance

# DLL 寃쎈줈(?꾩슂 ??
os.add_dll_directory(r"C:\dev\photostudio")
os.environ.setdefault("CRSDK_DLL", r"C:\dev\photostudio\crsdk_pybridge.dll")

# 濡쒓굅: 罹≪쿂 ?섏씠吏??濡쒓굅
_log = logging.getLogger("CAP")

# CameraControl 사용(가능 시), 실패 시 None 처리
try:
    from app.utils.control_camera import CameraControl
except Exception:
    CameraControl = None  # noqa: N816

# ?? LiveViewService ?곗꽑, ?놁쑝硫??대갚 援ы쁽 ?ъ슜 ?????????????????????????????
try:
    from app.services.liveview import LiveViewService  # 沅뚯옣 寃쎈줈(?대??먯꽌 on_qimage 肄쒕갚 ?몄텧)
except Exception:
    LiveViewService = None  # type: ignore
    # ?대갚: CRSDK DLL??吏곸젒 ?밴꺼??QImage 肄쒕갚??二쇰뒗 媛꾨떒 ?쒕씪?대쾭
    import ctypes as C, numpy as np, cv2
    _DLL = os.environ.get("CRSDK_DLL", r"C:\dev\photostudio\crsdk_pybridge.dll")
    _d = C.CDLL(_DLL)
    _d.crsdk_init.restype = C.c_int
    _d.crsdk_release.restype = None
    _d.crsdk_connect_first.argtypes  = [C.POINTER(C.c_void_p)]
    _d.crsdk_connect_first.restype   = C.c_int
    _d.crsdk_disconnect.argtypes = [C.c_void_p]; _d.crsdk_disconnect.restype = None
    _d.crsdk_enable_liveview.argtypes = [C.c_void_p, C.c_int]; _d.crsdk_enable_liveview.restype  = C.c_int
    _d.crsdk_get_lv_info.argtypes     = [C.c_void_p, C.POINTER(C.c_uint)]; _d.crsdk_get_lv_info.restype = C.c_int
    _d.crsdk_get_lv_image.argtypes    = [C.c_void_p, C.c_void_p, C.c_uint, C.POINTER(C.c_uint)]; _d.crsdk_get_lv_image.restype = C.c_int

    class _InlineLiveView:
        """LiveViewService媛 ?놁쓣 ?뚮쭔 ?ъ슜?섎뒗 理쒖냼 ?대갚."""
        def __init__(self, owner):
            self.owner = owner
            self.mode = 'off'
            self.cam = None
            self._ms_sdk = 33
            self._stop = threading.Event()
            self._th: Optional[threading.Thread] = None
            self._h = C.c_void_p()

        def configure(self, _lv_dir: str, ms_sdk: int, _ms_file: int, *_):
            try: self._ms_sdk = max(16, int(ms_sdk))
            except Exception: self._ms_sdk = 33

        def start(self, on_qimage) -> bool:
            if _d.crsdk_init() != 0: return False
            h = C.c_void_p()
            rc = _d.crsdk_connect_first(C.byref(h))
            if rc != 0 or not h.value:
                _d.crsdk_release(); return False
            self._h = h
            _d.crsdk_enable_liveview(self._h, 1)
            self.mode = 'sdk'
            self._stop.clear()
            def _run():
                need = C.c_uint(0)
                while not self._stop.is_set():
                    try:
                        if _d.crsdk_get_lv_info(self._h, C.byref(need)) != 0 or need.value == 0:
                            time.sleep(self._ms_sdk/1000.0); continue
                        buf = (C.c_ubyte * need.value)()
                        used = C.c_uint(0)
                        rc = _d.crsdk_get_lv_image(self._h, C.cast(buf, C.c_void_p), need.value, C.byref(used))
                        if rc == 0 and used.value:
                            arr = np.frombuffer(buf, dtype=np.uint8, count=used.value)
                            bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
                            if bgr is not None:
                                rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
                                h_, w_, _ = rgb.shape
                                qi = QImage(rgb.data, w_, h_, 3*w_, QImage.Format_RGB888).copy()
                                on_qimage(qi)
                    except Exception: pass
                    time.sleep(self._ms_sdk/1000.0)
            self._th = threading.Thread(target=_run, daemon=True); self._th.start()
            return True

        def stop(self):
            self._stop.set()
            if self._th: self._th.join(timeout=1.0)
            try:
                if self._h.value:
                    try: _d.crsdk_enable_liveview(self._h, 0)
                    except Exception: pass
                    try: _d.crsdk_disconnect(self._h)
                    except Exception: pass
            finally:
                _d.crsdk_release()
                self._h = C.c_void_p()
                self.mode = 'off'


# ?? 湲곕낯 ?좏겙 ???????????????????????????????????????????????????????????????
LV_DEFAULT_DIR = r"C:\PhotoBox\lv"
LV_DEFAULT_MS_SDK  = 33
LV_DEFAULT_MS_FILE = 48
PLACEHOLDER_DEFAULT = r"app\assets\placeholder.png"

CAP_DIR = Path(r"C:\PhotoBox\captures")
CAP_SEQ = ["01.jpg","02.jpg","03.jpg","04.jpg"]

TH_COUNT = 4; TH_GAP = 36; TH_H = 216; TH_W_3040 = 162; TH_W_3545 = 168
P_GAP = 36; PREV_H = 1008; PREV_W_3040 = 756; PREV_W_3545 = 784
P2_GAP = 30; CTRL_H = 45; BTN_R = 12; LED_D = 12; CTRL_GAP = 21


# ?? 媛꾨떒 Busy/Toast ?ㅻ쾭?덉씠 ????????????????????????????????????????????????
class BusyOverlay(QWidget):
    """바쁜 상태를 반투명 배경과 스피너/문구로 표시한다."""
    def __init__(self, parent: QWidget, text: str = "카메라 연결중"):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setStyleSheet("background: rgba(0,0,0,128);")
        self.msg = QLabel("", self)
        self.msg.setStyleSheet("color:white;")
        f = QFont(); f.setPointSize(16); f.setBold(True)
        self.msg.setFont(f)
        self.msg.setAlignment(Qt.AlignCenter)
        self.setText(text)
        self._dots = 0
        self._angle = 0
        self._spinner_radius = 24
        self._spinner_thickness = 4
        self._timer = QTimer(self); self._timer.setInterval(100); self._timer.timeout.connect(self._spin)

    def showEvent(self, _):
        self.resize(self.parentWidget().size()); self.msg.setGeometry(0,0,self.width(),self.height())
        self._dots = 0; self._timer.start()

    def hideEvent(self, _):
        self._timer.stop()

    def setText(self, t: str):
        """문구의 말줄임표/공백을 정리하고 기본 문구로 표시한다."""
        base = str(t or "").rstrip(" .")
        self.msg.setText(base)

    def _tick(self):
        """점(.) 애니메이션으로 진행 상황을 표시한다."""
        self._dots = (self._dots + 1) % 4
        base = self.msg.text().rstrip(" .")
        self.msg.setText(base + "." * self._dots)

    def _spin(self):
        self._angle = (self._angle + 20) % 360
        self.update()

    def paintEvent(self, ev):
        try:
            qp = QPainter(self)
            qp.setRenderHint(QPainter.Antialiasing, True)
            w, h = self.width(), self.height()
            cx, cy = w//2, max(40, h//2 - 80)
            r = self._spinner_radius
            pen = QPen(QColor(255, 255, 255))
            pen.setWidth(self._spinner_thickness)
            pen.setCapStyle(Qt.RoundCap)
            qp.setPen(pen); qp.setBrush(Qt.NoBrush)
            start_angle = int(self._angle * 16)
            span_angle = int(120 * 16)
            qp.drawArc(cx - r, cy - r, 2*r, 2*r, start_angle, span_angle)
            qp.end()
        except Exception:
            pass
class Toast(QWidget):
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: rgba(0,0,0,160); border-radius:10px;")
        self.lbl = QLabel("", self); self.lbl.setStyleSheet("color:white; padding:10px;")
        self.lbl.setAlignment(Qt.AlignCenter)
        self._timer = QTimer(self); self._timer.setInterval(1400); self._timer.timeout.connect(self.hide)
        self.hide()
    def popup(self, text:str):
        self.lbl.setText(text)
        w = max(200, self.parentWidget().width()//3); h = 50
        self.setGeometry((self.parentWidget().width()-w)//2, 40, w, h)
        self.lbl.setGeometry(0,0,w,h)
        self.show(); self.raise_(); self._timer.start()


# ?? CapturePage ?????????????????????????????????????????????????????????????
class CapturePage(BasePage):
    """珥ъ쁺 ?섏씠吏(?몃꽕???ㅽ듃由?+ ?쇱씠釉뚮럭 + 而⑦듃濡?諛?."""
    def __init__(self, theme, session: dict, parent=None):
        super().__init__(theme, steps=STEPS, active_index=2, parent=parent)
        self.session = session; self.session.setdefault("guide_skip", True)

        center = QWidget(self)
        layout = QVBoxLayout(center); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)

        # ?? ?몃꽕???ㅽ듃由???
        self.strip = QWidget(self)
        row = QHBoxLayout(self.strip); row.setContentsMargins(0,0,0,0); row.setSpacing(0); row.setAlignment(Qt.AlignHCenter)
        self._thumbs: list[QFrame] = []; self._thumb_imgs: list[QLabel] = []
        for i in range(TH_COUNT):
            f = QFrame(self.strip); f.setObjectName(f"Thumb{i+1}")
            f.setStyleSheet(f"QFrame#Thumb{i+1} {{ background: transparent; border: {self._thin_px()}px solid {self._primary_hex()}; border-radius: 0px; }}")
            f.setFixedSize(*self._tile_size())
            lbl = QLabel(f); lbl.setGeometry(0,0,*self._tile_size()); lbl.setAlignment(Qt.AlignCenter)
            lbl.setStyleSheet("background: transparent; border:none; padding:0; margin:0;"); lbl.setScaledContents(False)
            self._thumbs.append(f); self._thumb_imgs.append(lbl); row.addWidget(f, 0)
        layout.addWidget(self.strip, 0, Qt.AlignHCenter)

        # 媛꾧꺽
        self._gap36 = QWidget(self); self._gap36.setFixedHeight(0); layout.addWidget(self._gap36, 0)

        # ?? ?꾨━酉???
        self.preview_box = QFrame(self); self.preview_box.setObjectName("PreviewBox")
        self.preview_box.setStyleSheet(f"QFrame#PreviewBox {{ background: transparent; border: {self._normal_px()}px solid {self._primary_hex()}; border-radius: 0px; }}")
        layout.addWidget(self.preview_box, 0, Qt.AlignHCenter)
        self.preview_label = QLabel(self.preview_box)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setAttribute(Qt.WA_TranslucentBackground, False)
        self.preview_label.setStyleSheet("background: #808080; padding:0; margin:0; border:none;")

        self._gap36b = QWidget(self); self._gap36b.setFixedHeight(0); layout.addWidget(self._gap36b, 0)

        # Controls (delay buttons / capture / retake)
        self.ctrl = QWidget(self)
        hb = QHBoxLayout(self.ctrl); hb.setContentsMargins(0,0,0,0); hb.setSpacing(0); hb.setAlignment(Qt.AlignHCenter)
        self.cam_led = QLabel(self.ctrl); self.cam_led.setObjectName("CamLED"); hb.addWidget(self.cam_led, 0)
        self.delay3 = QPushButton("3s", self.ctrl); self.delay3.setObjectName("Delay3"); self.delay3.setCheckable(True)
        self.delay5 = QPushButton("5s", self.ctrl); self.delay5.setObjectName("Delay5"); self.delay5.setCheckable(True)
        self.delay7 = QPushButton("7s", self.ctrl); self.delay7.setObjectName("Delay7"); self.delay7.setCheckable(True)
        self.delay_group = QButtonGroup(self)
        for i, b in ((3,self.delay3),(5,self.delay5),(7,self.delay7)): self.delay_group.addButton(b, i); hb.addWidget(b, 0)
        self.delay_group.setExclusive(True); self.delay3.setChecked(True)
        try: self.delay_group.idClicked.disconnect(self._on_delay_changed)
        except Exception: pass
        for b in (self.delay3, self.delay5, self.delay7):
            try: b.setEnabled(False); b.setVisible(False)
            except Exception: pass
        self.btn_capture = QPushButton("Capture", self.ctrl); self.btn_capture.setObjectName("BtnCapture")
        self.btn_retake  = QPushButton("Retake", self.ctrl); self.btn_retake.setObjectName("BtnRetake")
        self.btn_capture.clicked.connect(self._on_capture_clicked)
        self.btn_retake.clicked.connect(self._on_retake_clicked)
        hb.addWidget(self.btn_capture, 0); hb.addWidget(self.btn_retake, 0)
        layout.addWidget(self.ctrl, 0, Qt.AlignHCenter)
        layout.addStretch(1)

        # ?고????곹깭
        self._cam: CameraControl | None = None
        self._settings_cache = {}; self._refresh_settings_tokens()
        self._count_timer = QTimer(self); self._count_timer.setInterval(1000)
        self._count_timer.timeout.connect(self._tick_countdown)
        self._count_left = 0; self._capturing = False
        # 踰꾪듉 珥ъ쁺?먯꽌留??ㅻ쾭?덉씠瑜??쒖떆?섍린 ?꾪븳 ?뚮옒洹?        self._overlay_from_button = False
        # 媛?대뜕???깃났 ?湲곕? ?꾪븳 臾댁옣 ?곹깭
        self._armed_for_auto = False
        # ?먮룞 ?곗궗 ?쒖뼱 ?곹깭
        self._seq_running = False
        self._seq_index = -1
        self._ready_since = None
        self._seq_timer = QTimer(self); self._seq_timer.setInterval(1000)
        self._seq_timer.timeout.connect(self._tick_seq_countdown)
        # ?꾨젅??濡쒓퉭 二쇨린 ?쒖뼱(1珥??⑥쐞)
        self._last_qimage_log_ms = 0
        self._seq_count_left = 0

        self._lv_status_hooked = False   # statusChanged ?곌껐 ?뚮옒洹?        self._connecting = False         # ?곌껐 吏꾪뻾 以??뚮옒洹?
        self._rebuild_layout_tokens(); self._apply_layout_tokens()

        # ?ㅼ젙 踰꾩뒪
        try:
            bus = QApplication.instance().property("settings_bus")
            if hasattr(bus, "changed"): bus.changed.connect(self._on_settings_changed)
        except Exception: pass
        # ?쇱씠釉뚮럭 start ?몄텧(吏꾩엯 濡쒓렇)
        try: _log.info("[CONN] start 以鍮?)
        except Exception: pass

        self.setCentralWidget(center, margin=(0,0,0,0), spacing=0, center=False, max_width=None)
        self.set_prev_mode("enabled"); self.set_next_mode("disabled"); self.set_next_enabled(False)

        self._read_ratio()

        # ?ㅻ쾭?덉씠??        self.overlay = AiOverlay(self)
        try: self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        except Exception: pass
        try:
            if hasattr(self.overlay, "bind_session"): self.overlay.bind_session(self.session)
        except Exception: pass
        self.overlay.setGeometry(self.rect()); self.overlay.hide(); self.overlay.lower()

        self.busy = BusyOverlay(self, "移대찓???곌껐以?)
        try:
            self.busy.setText("移대찓???곌껐以?)
        except Exception:
            pass
        self.busy.hide()

        self.toast = Toast(self)

        self._lv_mode = 'off'
        try:
            from app.utils.face_engine import FaceEngine  # type: ignore
            self.face = FaceEngine()
        except Exception: self.face = None
        try:
            from app.utils.pose_engine import PoseEngine  # type: ignore
            self.pose = PoseEngine()
        except Exception: self.pose = None

        self._ai_rate_ms = 500; self._ai_last_ms = 0; self._ema: Dict[str, float] = {}
        self.guide = Guidance(rate_ms=500)

        # LiveViewService ?몄뒪?댁뒪(?놁쑝硫??대갚)
        self.lv = LiveViewService(self) if LiveViewService else _InlineLiveView(self)  # type: ignore[name-defined]
        self._first_frame_seen = False
        self._conn_timer = QTimer(self); self._conn_timer.setInterval(400)
        self._conn_timer.timeout.connect(self._conn_tick)


    # ??????????????????????????????????????????????????????????
    def showEvent(self, e):
        super().showEvent(e)
        self.set_prev_mode("enabled"); self.set_next_mode("disabled"); self.set_next_enabled(False)
        self._read_ratio()
        self._rebuild_layout_tokens(); self._apply_layout_tokens(); self._apply_ctrl_styles()
        self._show_placeholder()
        # 鍮꾨룞湲??곌껐 ?쒖옉(UI 癒쇱? ?쒖떆)
        QTimer.singleShot(0, self._connect_camera_async)

        try:
            if self.face: self.face.start()
        except Exception: pass
        try:
            if self.pose: self.pose.start()
        except Exception: pass

        self._first_frame_seen = False
        self._conn_phase = 0               # 0: ?곌껐以? 1: 吏?곗쨷
        self._conn_started = time.time()
        self._show_connect_overlay("移대찓???곌껐以?)
        self._conn_timer.start()


        try:
            self.overlay.setGeometry(self.rect())
            self.overlay.hide(); self.overlay.lower()
            self.preview_box.raise_(); self.preview_label.raise_()
        except Exception: pass

    def resizeEvent(self, ev):
        """由ъ궗?댁쫰 ???ㅻ쾭?덉씠/?좎뒪???꾩튂瑜?媛깆떊?쒕떎."""
        super().resizeEvent(ev)
        try:
            if hasattr(self, "overlay"):
                self.overlay.setGeometry(self.rect())
                self._overlay_update_hole()
                if (getattr(self, "_capturing", False) or getattr(self, "_armed_for_auto", False)) and getattr(self, "_overlay_from_button", False):
                    self.overlay.show(); self.overlay.raise_()
                else:
                    self.overlay.hide(); self.overlay.lower()
        except Exception: pass
        try:
            self.busy.resize(self.size())
            if self.toast.isVisible(): self.toast.popup(self.toast.lbl.text())
        except Exception: pass
        try: self._sync_preview_label_geom()
        except Exception: pass

    def keyPressEvent(self, e):
        k = e.key()
        if k == Qt.Key_Left:
            self.go_prev.emit(); return
        if k == Qt.Key_Right and self.footer.nextBtn.isEnabled():
            self.go_next.emit(); return
        # 珥ъ쁺 ?⑥텞??        if k == Qt.Key_F1:  # AF
            self._cmd_one_shot_af(); return
        if k == Qt.Key_F2:  # AWB
            self._cmd_one_shot_awb(); return
        if k == Qt.Key_F3:  # SHOT
            self._cmd_shoot_one(); return
        super().keyPressEvent(e)

    # ?? ratio helpers ?????????????????????????????????????????
    def _read_ratio(self):
        r = str(self.session.get("ratio", "3040")).strip()
        if r not in ("3040","3545"): r = "3040"
        self._ratio = r

    def get_ratio(self) -> str: return getattr(self, "_ratio", "3040")
    def ratio_tuple(self) -> tuple[int, int]: return (3,4) if self.get_ratio()=="3040" else (7,9)

    # ?? helpers: theme/size ???????????????????????????????????
    def _primary_hex(self) -> str:
        app = QApplication.instance()
        cols = (app.property("THEME_COLORS") or {}) if app else {}
        return cols.get("primary", "#FF4081")

    def _thin_px(self) -> int:
        app = QApplication.instance(); val = None
        if app:
            for key in ("BORDER_TOKENS","THEME_BORDERS","BORDERS","THEME_SIZES","SIZES"):
                d = app.property(key)
                if isinstance(d, dict):
                    if "thin" in d: val = d.get("thin"); break
                    for k in ("border_thin","thin_px","line_thin"):
                        if k in d: val = d.get(k); break
                if val is not None: break
        try: v = int(float(val)) if val is not None else 3
        except Exception: v = 3
        return max(1, v)

    def _normal_px(self) -> int:
        app = QApplication.instance(); val = None
        if app:
            for key in ("BORDER_TOKENS","THEME_BORDERS","BORDERS","THEME_SIZES","SIZES"):
                d = app.property(key)
                if isinstance(d, dict):
                    if "normal" in d: val = d.get("normal"); break
                    for k in ("border","normal_px","line_normal"):
                        if k in d: val = d.get(k); break
                if val is not None: break
        try: v = int(float(val)) if val is not None else 3
        except Exception: v = 3
        return max(1, v)

    def _tile_size(self) -> tuple[int, int]:
        T = getattr(self, "_T", {})
        if self.get_ratio()=="3545": return int(T.get("TH_W_3545", TH_W_3545)), int(T.get("TH_H", TH_H))
        return int(T.get("TH_W_3040", TH_W_3040)), int(T.get("TH_H", TH_H))

    # ?? ?곗뼱 ?ㅼ??? ?좏겙 由щ퉴???곸슜 ?????????????????????????
    @staticmethod
    def _snap3(v: float) -> int:
        try:
            n = int(float(v)); return n - (n % 3)
        except Exception:
            return

    # ?? handlers: delay buttons ???????????????????????????????
    def _on_delay_changed(self, delay_id: int):
        try: v = int(delay_id)
        except Exception: v = 3
        if v not in (3,5,7): v = 3
        self.session["delay_sec"] = v
        try:
            btn = self.delay_group.button(v)
            if btn and not btn.isChecked(): btn.setChecked(True)
        except Exception: pass

    # ?? 珥ъ쁺 ?몃━嫄?移댁슫?몃떎?????????????????????????????????
    def _on_capture_clicked(self):
        """珥ъ쁺 踰꾪듉 ?대┃ ??移댁슫?몃떎?닿낵 ?ㅻ쾭?덉씠瑜??쒖옉?쒕떎."""
        if self._capturing: return
        self._overlay_from_button = True
        self._armed_for_auto = True
        # 珥ъ쁺 ?쒖옉 ???곌껐 ?ㅽ뵾?덇? ?⑥븘 ?덈떎硫??④릿??
        try:
            if hasattr(self, 'busy') and self.busy.isVisible():
                self.busy.hide(); self.busy.lower()
        except Exception:
            pass
        self._clear_captures()
        # UI ?좉툑留??섑뻾(罹≪쿂/Prev/Next 鍮꾪솢??. _capturing? False ?좎?
        self.set_prev_mode("disabled"); self.set_prev_enabled(False)
        self.set_next_mode("disabled"); self.set_next_enabled(False)
        try: self.btn_capture.setEnabled(False)
        except Exception: pass
        # ?ㅻ쾭?덉씠 誘몃━ ?쒖떆(媛?대뜕???덈궡)
        try:
            if hasattr(self.overlay, 'refresh_tokens'):
                self.overlay.refresh_tokens({'show_guide': True})
            self.overlay.setGeometry(self.rect())
            self._overlay_update_hole()
            # ?붾쾭洹? 以묒븰 ?뚯뒪??諛곗?/?щ줈???쒖떆
            try:
                if hasattr(self.overlay, 'set_debug_cross'):
                    self.overlay.set_debug_cross(True)
                if hasattr(self.overlay, 'set_badge_center'):
                    self.overlay.set_badge_center(True)
                if hasattr(self.overlay, 'update_badges'):
                    self.overlay.update_badges('DEBUG: 중앙 테스트', {})
            except Exception:
                pass
            self.overlay.show(); self.overlay.raise_()
        except Exception: pass

    def _on_retake_clicked(self):
        """?ъ눋??踰꾪듉 ?대┃ ??珥ъ쁺 ?곹깭? ?ㅻ쾭?덉씠瑜??댁젣?쒕떎."""
        if getattr(self, "_count_timer", None) and self._count_timer.isActive(): self._count_timer.stop()
        self._count_left = 0; self._capturing = False
        self._overlay_from_button = False
        self.btn_capture.setEnabled(True)
        for b in (self.delay3, self.delay5, self.delay7):
            try: b.setEnabled(False)
            except Exception: pass
        self._overlay_hide()
        self.set_next_enabled(False); self.set_next_mode("disabled")
        self.set_prev_mode("enabled"); self.set_prev_enabled(True)
        self._shot_index = 0; self._clear_captures()
        # ?먮룞 ?곗궗 ?곹깭 由ъ뀑
        self._seq_running = False; self._seq_index = -1; self._ready_since = None
        if self._seq_timer.isActive(): self._seq_timer.stop()

    # F3 珥ъ쁺: 踰꾪듉 1?뚯? ?숈씪?섍쾶 臾댁옣?믩젅??0.8s)?믪뭅?댄듃?ㅼ슫(5s)???곗궗 ?먮쫫???쒖옉?쒕떎.
    def _cmd_shoot_one(self):
        """F3 ???낅젰 ???먮룞 珥ъ쁺 ?쒗?ㅻ? 踰꾪듉 ?대┃怨??숈씪?섍쾶 ?쒖옉?쒕떎."""
        try:
            # 踰꾪듉 ?뚮줈???ъ궗??臾댁옣 諛??ㅻ쾭?덉씠 ?몄텧)
            self._on_capture_clicked()
        except Exception:
            pass

    def _lock_ui_for_capture(self, on: bool):
        """珥ъ쁺 吏꾪뻾 以?UI瑜??좉렇嫄곕굹 ?댁젣?쒕떎."""
        self._capturing = bool(on)
        self.set_prev_mode("disabled"); self.set_prev_enabled(False)
        self.set_next_mode("disabled"); self.set_next_enabled(False)
        for b in (self.delay3, self.delay5, self.delay7):
            try: b.setEnabled(False)
            except Exception: pass
        try: self.btn_capture.setEnabled(not on)
        except Exception: pass

    def _start_countdown(self, sec: int):
        self._count_left = int(sec); self._count_timer.start()

    def _tick_countdown(self):
        self._count_left -= 1
        try:
            if self._count_left == 3:
                self._try_af_async()
        except Exception:
            pass
        # ?ㅻ쾭?덉씠???⑥? ?쒓컙 諛곗?瑜??쒖떆?쒕떎.
        try:
            if hasattr(self, "overlay") and hasattr(self.overlay, "update_badges"):
                    self.overlay.update_badges('DEBUG: 중앙 테스트', {})
                self.overlay.show(); self.overlay.raise_()
        except Exception:
            pass
        if self._count_left > 0: return
        self._count_timer.stop(); self._invoke_shoot(i=0)

    # ?먮룞 ?곗궗??1珥?tick: ?댄썑 ?룸뱾 3珥?媛꾧꺽, 媛?1珥???AF
    def _tick_seq_countdown(self):
        self._seq_count_left -= 1
        if self._seq_count_left == 1:
            try:
                self._try_af_async(idx=(getattr(self, "_seq_index", -1) + 1))
            except Exception:
                self._try_af_async()
        if self._seq_count_left <= 0:
            next_i = self._seq_index + 1
            self._seq_timer.stop()
            self._invoke_shoot(i=next_i)

    def _invoke_shoot(self, i: Optional[int]=None):
        # 湲곗〈 罹≪쿂 ?뚯씠?꾨씪???좎?
        def _work():
            ok = False; path = None; err = ""
            try:
                cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None)
                t_mark = time.time()
                if cam and hasattr(cam, "shoot_one"):
                    res = cam.shoot_one()
                    if isinstance(res, dict):
                        ok = bool(res.get("ok", False)); path = res.get("path") or res.get("file")
                    elif isinstance(res, (list, tuple)):
                        ok = bool(res[0]); path = (res[1] if len(res)>1 else None)
                    elif isinstance(res, bool): ok = res
                    elif isinstance(res, int):  ok = (res == 0)
                    if ok and not path:
                        try:
                            p1 = self._try_fetch_last_saved(cam)
                        except Exception:
                            p1 = None
                        if not p1:
                            try:
                                p1 = self._poll_new_jpeg(since=t_mark, timeout_s=3.0)
                            except Exception:
                                p1 = None
                        if p1:
                            path = p1
                else:
                    # LiveViewService媛 吏곸젒 ?쒓났?섎뒗 寃쎌슦
                    if hasattr(self.lv, "shoot_one"):
                        rc = self.lv.shoot_one()  # 0 == OK
                        ok = (rc == 0)
                    else:
                        err = "shoot api not available"
                # ??寃곌낵 濡쒓퉭
                try:
                    rc_code = 0 if ok else -1
                    _log.info("[SHOT] i=%s rc=%s", (i if i is not None else "?"), rc_code)
                except Exception:
                    pass
            except Exception as e:
                err = str(e)
            def _done(): self._on_shoot_done(ok, path, err, i)
            QTimer.singleShot(0, _done)
        threading.Thread(target=_work, daemon=True).start()

    def _on_shoot_done(self, ok: bool, path: Optional[str], err: str="", idx: Optional[int]=None):
        if ok:
            if not getattr(self, "_seq_running", False):
                try: self._stop_camera()
                except Exception: pass
            # 媛????꾨즺 ???꾨━酉??ㅻ깄?룹쓣 吏??寃쎈줈/?뚯씪紐낆쑝濡????            thumb_path = self._save_preview_snapshot_indexed(int(idx) if idx is not None else 0)
            if not thumb_path:
                thumb_path = self._save_preview_thumbnail()
            # ?ㅼ젣 珥ъ쁺 ?뚯씪??吏??寃쎈줈濡??대룞/由щ꽕??            try:
                move_idx = int(idx) if idx is not None else int(len(self.session.get("shot_paths", [])))
            except Exception:
                move_idx = 0
            try:
                if path:
                    new_path = self._move_capture_to_raw(move_idx, path)
                    if new_path:
                        path = new_path
            except Exception:
                pass
            try:
                self.session.setdefault("shot_paths", [])
                self.session.setdefault("shot_thumbs", [])
                if path: self.session["shot_paths"].append(path)
                if thumb_path: self.session["shot_thumbs"].append(thumb_path)
                # captures/raw_captures ?몃뜳??媛깆떊
                eff_i = move_idx
                arr_cap = self.session.setdefault('captures', ["", "", "", ""])
                arr_raw = self.session.setdefault('raw_captures', ["", "", "", ""])
                if 0 <= eff_i < len(arr_cap):
                    if thumb_path: arr_cap[eff_i] = str(Path(thumb_path).name)
                if 0 <= eff_i < len(arr_raw):
                    if path: arr_raw[eff_i] = str(Path(path).name)
                # [CAP] i=.. thumb=.. raw=.. 濡쒓렇
                try:
                    _log.info("[CAP] i=%s thumb=%s raw=%s", eff_i, (thumb_path or ""), (path or ""))
                except Exception:
                    pass
            except Exception:
                pass
            if getattr(self, "_seq_running", False):
                self._seq_index = int(idx) if idx is not None else (getattr(self, "_seq_index", -1) + 1)
                if self._seq_index >= 3:
                    self._seq_running = False
                    self.end_capture(True)
                else:
                    self._seq_count_left = 3
                    if not self._seq_timer.isActive():
                        self._seq_timer.start()
            else:
                self.end_capture(True)
        else:
            try:
                if hasattr(self, "overlay") and hasattr(self.overlay, "update_badges"):
                    msg = f"珥ъ쁺 ?ㅽ뙣: {err or ''}"
                    self.overlay.update_badges('DEBUG: 중앙 테스트', {})
            except Exception: pass
            self._overlay_hide()
            self.btn_capture.setText("?ъ떆??); self.btn_capture.setEnabled(True)
            for b in (self.delay3, self.delay5, self.delay7):
                try: b.setEnabled(False)
                except Exception: pass
            self.set_prev_mode("enabled"); self.set_prev_enabled(True)
            self.set_next_mode("disabled"); self.set_next_enabled(False)
            self._capturing = False

    def _save_preview_thumbnail(self) -> Optional[str]:
        try:
            pm = self.preview_label.pixmap()
            if not pm or pm.isNull(): return None
            out_dir = Path.cwd() / "captures"; out_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S"); out = out_dir / f"thumb_{ts}.jpg"
            pm.save(str(out), "JPG", 90); return str(out)
        except Exception:
            return None

    # ?꾨━酉??ㅻ깄?룹쓣 ?몃뜳???뚯씪紐낆쑝濡???ν븳??
    def _save_preview_snapshot_indexed(self, idx: int) -> Optional[str]:
        try:
            pm = self.preview_label.pixmap()
            if not pm or pm.isNull():
                return None
            out_dir = Path(r"C:\PhotoBox\cap")
            out_dir.mkdir(parents=True, exist_ok=True)
            name = f"thumb_{int(idx)+1:02d}.jpg"
            out = out_dir / name
            ok = pm.save(str(out), "JPG", 90)
            return str(out) if ok else None
        except Exception:
            return None

    # 珥ъ쁺???ㅼ젣 ?뚯씪??C:\PhotoBox\raw\raw_{i+1:02d}.jpg 濡??대룞/由щ꽕?꾪븳??
    def _move_capture_to_raw(self, idx: int, src_path: str) -> Optional[str]:
        try:
            src = Path(src_path)
            if not src.exists() or not src.is_file():
                return None
            raw_dir = Path(r"C:\PhotoBox\raw")
            raw_dir.mkdir(parents=True, exist_ok=True)
            dest = raw_dir / f"raw_{int(idx)+1:02d}.jpg"
            # ?숈씪 寃쎈줈硫??ㅽ궢
            try:
                if src.resolve() == dest.resolve():
                    return str(dest)
            except Exception:
                pass
            # 湲곗〈 ?뚯씪???덉쑝硫???젣 ???대룞
            try:
                if dest.exists():
                    dest.unlink()
            except Exception:
                pass
            try:
                src.rename(dest)
            except Exception:
                # ?ㅻⅨ ?쒕씪?대툕 ?대룞 ???ㅽ뙣 ??蹂듭궗 ????젣 ?쒕룄
                import shutil
                shutil.copy2(str(src), str(dest))
                try: src.unlink()
                except Exception: pass
            return str(dest)
        except Exception:
            return None

    # SDK?먯꽌 理쒖떊 ????뚯씪??議고쉶?쒕떎. ?ㅽ뙣 ??None 諛섑솚.
    def _try_fetch_last_saved(self, cam) -> Optional[str]:
        try:
            if hasattr(cam, 'get_last_saved_jpeg'):
                p = cam.get_last_saved_jpeg()
                if p:
                    return p
        except Exception:
            pass
        try:
            if hasattr(cam, 'download_latest'):
                p = cam.download_latest()
                if p:
                    return p
        except Exception:
            pass
        return None

    # ?대뜑 媛먯떆 ?대쭅?쇰줈 ?좉퇋 JPEG ?뚯씪??李얜뒗??
    def _poll_new_jpeg(self, since: float, timeout_s: float = 3.0, interval_s: float = 0.2) -> Optional[str]:
        t0 = time.time()
        candidates = [
            Path(r"C:\PhotoBox\raw"),
            Path(r"C:\PhotoBox\JPG"),
            Path(r"C:\PhotoBox"),
        ]
        exts = {'.jpg', '.jpeg', '.JPG', '.JPEG'}
        last_seen: Optional[str] = None
        while (time.time() - t0) < float(timeout_s):
            try:
                for d in candidates:
                    if not d.exists() or not d.is_dir():
                        continue
                    newest_path = None
                    newest_mtime = -1.0
                    for p in d.glob('*'):
                        try:
                            if p.suffix not in exts:
                                continue
                            st = p.stat()
                            if st.st_mtime >= float(since) and st.st_mtime >= newest_mtime:
                                newest_mtime = st.st_mtime
                                newest_path = str(p)
                        except Exception:
                            continue
                    if newest_path:
                        last_seen = newest_path
                        break
                if last_seen:
                    return last_seen
            except Exception:
                pass
            time.sleep(interval_s)
        return last_seen

    # ?? 而⑦듃濡ㅻ컮 ?ㅽ????ш린 ?곸슜 ?????????????????????????????
    def _apply_ctrl_styles(self):
        T = getattr(self, "_T", {})
        primary = self._primary_hex(); r = int(T.get("BTN_R", BTN_R))
        try: self.ctrl.layout().setSpacing(int(T.get("CTRL_GAP", CTRL_GAP)))
        except Exception: pass
        try:
            h = int(T.get("CTRL_H", CTRL_H))
            for b in (self.delay3, self.delay5, self.delay7, self.btn_capture, self.btn_retake):
                b.setFixedHeight(h)
            self.delay3.setMinimumWidth(int(T.get("W_DELAY", 90)))
            self.delay5.setMinimumWidth(int(T.get("W_DELAY", 90)))
            self.delay7.setMinimumWidth(int(T.get("W_DELAY", 90)))
            self.btn_capture.setMinimumWidth(int(T.get("W_ACT", 150)))
            self.btn_retake.setMinimumWidth(int(T.get("W_ACT", 150)))
        except Exception: pass
        thin = self._thin_px()
        # LED ?먰삎 + 怨좎젙?ш린
        try:
            d = int(T.get("LED_D", LED_D))
            self.cam_led.setFixedSize(d, d)
            self.cam_led.setStyleSheet(
                f"QLabel#CamLED {{ border-radius:{d//2}px; background:#D9D9D9; }}"
            )
        except Exception:
            pass
        chip = (
            f"QPushButton#Delay3, QPushButton#Delay5, QPushButton#Delay7 {{ border:{thin}px solid {primary}; border-radius:{r}px; background:transparent; color:{primary}; padding:0 12px; }}"
            f"QPushButton#Delay3:checked, QPushButton#Delay5:checked, QPushButton#Delay7:checked {{ background:{primary}; color:white; }}"
            f"QPushButton#Delay3:disabled, QPushButton#Delay5:disabled, QPushButton#Delay7:disabled {{ opacity:0.5; }}"
        )
        act = (
            f"QPushButton#BtnCapture, QPushButton#BtnRetake {{ border:{thin}px solid {primary}; border-radius:{r}px; padding:0 12px; background:transparent; color:{primary}; }}"
            f"QPushButton#BtnCapture:pressed, QPushButton#BtnRetake:pressed {{ background:{primary}; color:white; }}"
            f"QPushButton#BtnCapture:disabled, QPushButton#BtnRetake:disabled {{ opacity:0.5; }}"
        )
        try: self.ctrl.setStyleSheet(chip + act)
        except Exception: pass
        self._refresh_led()

    # ?? ?꾨━酉??ш린/諛곗튂 ??????????????????????????????????????
    def _preview_size_label(self) -> tuple[int,int]:
        T = getattr(self, "_T", {})
        w = int(T.get("PREV_W_3545", PREV_W_3545)) if self.get_ratio()=="3545" else int(T.get("PREV_W_3040", PREV_W_3040))
        h = int(T.get("PREV_H", PREV_H))
        return int(w), int(h)

    def _preview_size_box(self) -> tuple[int,int]:
        lw, lh = self._preview_size_label(); b = self._normal_px()
        return lw + 2*b, lh + 2*b

    def _rebuild_layout_tokens(self):
        f = float(BasePage._tier_factor())
        g = 6 if f >= 1.9 else (4 if f >= 1.3 else 3)
        def _snap_grid(v: float, grid: int) -> int:
            if grid <= 1: return int(round(v))
            q = v / float(grid)
            return (int(q) + (0 if q.is_integer() else 1)) * grid
        def S(px: int) -> int: return _snap_grid(px * f, g)
        self._T = {
            "TH_COUNT": TH_COUNT, "TH_GAP": S(TH_GAP), "TH_H": S(TH_H),
            "TH_W_3040": S(TH_W_3040), "TH_W_3545": S(TH_W_3545),
            "P_GAP": S(P_GAP), "PREV_H": S(PREV_H),
            "PREV_W_3040": S(PREV_W_3040), "PREV_W_3545": S(PREV_W_3545),
            "P2_GAP": S(P2_GAP), "CTRL_H": S(CTRL_H), "BTN_R": S(BTN_R),
            "LED_D": S(LED_D), "CTRL_GAP": S(CTRL_GAP),
            "W_DELAY": S(90), "W_ACT": S(150),
        }

    def _apply_layout_tokens(self):
        T = getattr(self, "_T", {})
        tw, th = self._tile_size()
        for f in getattr(self, "_thumbs", []): f.setFixedSize(tw, th)
        try: self.strip.layout().setSpacing(int(T.get("TH_GAP", TH_GAP)))
        except Exception: pass
        self._gap36.setFixedHeight(int(T.get("P_GAP", P_GAP)))
        self._gap36b.setFixedHeight(int(T.get("P2_GAP", P2_GAP)))
        bw, bh = self._preview_size_box()
        lw, lh = self._preview_size_label()
        try:
            self.preview_box.setFixedSize(bw, bh)
            b_ = self._normal_px()
            self.preview_box.setStyleSheet(
                f"QFrame#PreviewBox {{ background: transparent; border: {b_}px solid {self._primary_hex()}; padding:0; border-radius: 0px; }}"
            )
            try: self.preview_box.setContentsMargins(b_, b_, b_, b_)
            except Exception: pass
            self.preview_label.setFixedSize(lw, lh)
            self._sync_preview_label_geom()
        except Exception: pass
        self._apply_ctrl_styles()

    # ?? SETTINGS ?좏겙 ?????????????????????????????????????????
    def _settings(self) -> dict:
        app = QApplication.instance()
        return (app.property("SETTINGS") or {}) if app else {}

    def _refresh_settings_tokens(self):
        self._settings_cache = self._settings()

    def _tok_ms_sdk(self) -> int:
        lv = (self._settings_cache.get("liveview", {}) if isinstance(self._settings_cache, dict) else {})
        try: v = int(lv.get("ms", {}).get("sdk", LV_DEFAULT_MS_SDK)) if isinstance(lv.get("ms"), dict) else LV_DEFAULT_MS_SDK
        except Exception: v = LV_DEFAULT_MS_SDK
        return max(16, v)

    def _tok_ms_file(self) -> int:
        lv = (self._settings_cache.get("liveview", {}) if isinstance(self._settings_cache, dict) else {})
        try: v = int(lv.get("ms", {}).get("file", LV_DEFAULT_MS_FILE)) if isinstance(lv.get("ms"), dict) else LV_DEFAULT_MS_FILE
        except Exception: v = LV_DEFAULT_MS_FILE
        return max(33, v)

    def _tok_lv_dir(self) -> str:
        paths = (self._settings_cache.get("paths", {}) if isinstance(self._settings_cache, dict) else {})
        p = paths.get("liveview_dir")
        return str(p) if p else LV_DEFAULT_DIR

    def _on_settings_changed(self, *_):
        """?ㅼ젙 蹂寃???LiveView ?ㅼ젙??媛깆떊?섍퀬 濡쒓퉭?쒕떎."""
        self._refresh_settings_tokens()
        try:
            self.lv.configure(self._tok_lv_dir(), self._tok_ms_sdk(), self._tok_ms_file())
            try: _log.info("[SET] ?ㅼ젙 蹂寃?諛섏쁺: dir=%s ms_sdk=%s ms_file=%s", self._tok_lv_dir(), self._tok_ms_sdk(), self._tok_ms_file())
            except Exception: pass
        except Exception as e:
            try: _log.error("[SET] ?ㅼ젙 蹂寃??곸슜 ?ㅽ뙣: %s", e)
            except Exception: pass

    # ?? LiveView ?쒖옉/?뺤?(鍮꾨룞湲??곌껐) ?????????????????????????
    def _connect_camera_async(self):
        """移대찓??LiveView ?곌껐??鍮꾨룞湲곕줈 ?쒖옉?쒕떎(吏???④퀎 ?쒓굅, 濡쒓퉭 媛뺥솕)."""
        if self._connecting: return
        self._connecting = True
        self.busy.setText("移대찓???곌껐以?); self.busy.show(); self.busy.raise_()
        self.set_led_mode('off')

        # statusChanged 1?뚮쭔
        try:
            if hasattr(self.lv, "statusChanged") and not self._lv_status_hooked:
                try: self.lv.statusChanged.disconnect(self._on_lv_status)
                except Exception: pass
                self.lv.statusChanged.connect(self._on_lv_status)
                self._lv_status_hooked = True
        except Exception: pass

        # 援ъ꽦媛??곸슜
        try:
            self.lv.configure(self._tok_lv_dir(), self._tok_ms_sdk(), self._tok_ms_file(), fallback_ms=3000)
        except Exception: pass

        # ?뚯빱 ?ㅻ젅?쒕줈 start (理쒕? 12珥?媛먯떆)
        def _work():
            ok = False
            try:
                try: _log.info("[CONN] start ?몄텧")
                except Exception: pass
                ok = bool(self.lv.start(on_qimage=self._on_qimage))
            except Exception:
                ok = False
            def _done():
                self._connecting = False
                if ok:
                    self._cam = getattr(self.lv, 'cam', None)
                    self.set_led_mode(getattr(self.lv, 'mode', 'off'))
                    self.busy.hide()
                else:
                    self.set_led_mode('off')
                    self.busy.setText("移대찓???곌껐 ?ㅽ뙣")
                    QTimer.singleShot(1300, self.busy.hide)
            QTimer.singleShot(0, _done)
        threading.Thread(target=_work, daemon=True).start()

        # ??꾩븘??媛먯떆(12珥?
        def _guard():
            try: _log.warning("[CONN] 12s 寃쎄낵: ?꾩쭅 ?곌껐以?)
            except Exception: pass
            return
            if self._connecting:
                self._connecting = False
                try: self.lv.stop()
                except Exception: pass
                self.set_led_mode('off')
                self.busy.setText("移대찓???곌껐 吏??)
                QTimer.singleShot(1300, self.busy.hide)
        QTimer.singleShot(12000, _guard)

    def _on_qimage(self, img: QImage):
        if not self._first_frame_seen:
            self._first_frame_seen = True
            self._conn_timer.stop()
            self._hide_connect_overlay()
            try: _log.info("[LV] 泥??꾨젅???섏떊")
            except Exception: pass

        try:
            w, h = self.preview_label.width(), self.preview_label.height()
            mode = getattr(self.lv, 'mode', 'off')

            # 1) ?뚯쟾/誘몃윭 蹂????媛濡?留욎땄, ?꾨옒 ?щ∼
            pix = QPixmap()
            try:
                pix = render_placeholder(img, w, h) if mode == 'file' else render_transformed(img, w, h)
            except Exception:
                pix = QPixmap()
            # 2) ?대갚: 吏곸젒 ?ㅼ???            if pix.isNull():
                try:
                    pix = QPixmap.fromImage(img).scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                except Exception:
                    pix = QPixmap()

            if not pix.isNull():
                self.preview_label.setPixmap(pix)
                # ?곌껐 吏?????붾쪟 Busy ?ㅻ쾭?덉씠媛 ?덉쑝硫??④릿??
                try:
                    if hasattr(self, 'busy') and self.busy.isVisible():
                        self.busy.hide(); self.busy.lower()
                except Exception:
                    pass
                # 1珥?二쇨린濡??꾨젅??媛깆떊 濡쒓렇瑜??④릿??遺??諛⑹?)
                try:
                    ts_ms = int(time.time() * 1000)
                    if ts_ms - int(getattr(self, '_last_qimage_log_ms', 0)) >= 1000:
                        self._last_qimage_log_ms = ts_ms
                        _log.info("[LV] frame w=%s h=%s mode=%s", w, h, mode)
                except Exception:
                    pass
            # ?먮룞 ?곗궗 議곌굔 ?뺤씤(罹≪쿂 以??꾨땺 ?뚮룄 媛?대뜕???됯?)
            try:
                if (not getattr(self, "_capturing", False) or getattr(self, "_armed_for_auto", False)) and hasattr(self, 'guide'):
                    ts = int(time.time() * 1000)
                    try:
                        if hasattr(self.guide, 'set_input_source'):
                            self.guide.set_input_source('sdk' if mode == 'sdk' else 'file')
                    except Exception:
                        pass
                    _, _, _metrics0 = self.guide.update(
                        pix.toImage() if isinstance(pix, QPixmap) else img,
                        self.get_ratio(), ts,
                        getattr(self, 'face', None), getattr(self, 'pose', None)
                    )
                    try: self._check_auto_sequence(_metrics0)
                    except Exception: pass
            except Exception:
                pass

            # 媛?대뜕???ㅻ쾭?덉씠
            if (getattr(self, "_capturing", False) or getattr(self, "_armed_for_auto", False)) and hasattr(self, 'guide'):
                ts = int(time.time() * 1000)
                # ?낅젰 ?뚯뒪 ?ㅼ젙: ?쇱씠釉뚮럭??'sdk', ?뚯씪 ?ъ깮? 'file'
                try:
                    if hasattr(self.guide, 'set_input_source'):
                        self.guide.set_input_source('sdk' if mode == 'sdk' else 'file')
                except Exception:
                    pass
                payload, badges, metrics = self.guide.update(
                    pix.toImage() if isinstance(pix, QPixmap) else img,
                    self.get_ratio(), ts,
                    getattr(self, 'face', None), getattr(self, 'pose', None)
                )
                try:
                    if hasattr(self.overlay, 'update_landmarks'):
                        self.overlay.update_landmarks(payload, normalized=True)
                except Exception: pass
                try:
                    if hasattr(self.overlay, 'update_badges'):
                    self.overlay.update_badges('DEBUG: 중앙 테스트', {})
                except Exception: pass
                try: self.overlay.show(); self.overlay.raise_()
                except Exception: pass
            else:
                try: self.overlay.hide(); self.overlay.lower()
                except Exception: pass

            self.set_led_mode(mode)
        except Exception:
            pass
    def _show_connect_overlay(self, text: str):
        """移대찓???곌껐/?湲???Busy ?ㅻ쾭?덉씠留??쒖떆?쒕떎."""
        try:
            self.busy.setText(text)
            self.busy.resize(self.size())
            self.busy.show(); self.busy.raise_()
        except Exception:
            pass

    def _hide_connect_overlay(self):
        """?곌껐/?湲?Busy ?ㅻ쾭?덉씠瑜??④릿??"""
        try:
            self.busy.hide(); self.busy.lower()
        except Exception:
            pass
    def _stop_camera(self):
        # statusChanged留??댁젣
        self._conn_timer.stop()
        self._hide_connect_overlay()
        self._first_frame_seen = False

        try:
            if self._lv_status_hooked and hasattr(self.lv, "statusChanged"):
                try: self.lv.statusChanged.disconnect(self._on_lv_status)
                except Exception: pass
                self._lv_status_hooked = False
        except Exception: pass
        try:
            if hasattr(self, 'lv') and self.lv: self.lv.stop()
        except Exception: pass
        self.set_led_mode('off')
        self._show_placeholder()
    
    def on_before_prev(self, session): self._stop_camera(); return True
    def on_before_next(self, session): self._stop_camera(); return True

    def _conn_tick(self):
        if self._first_frame_seen:
            self._conn_timer.stop(); self._hide_connect_overlay(); return
        elapsed = time.time() - getattr(self, "_conn_started", time.time())
        # ?곌껐 吏???④퀎 ?쒓굅: 異붽? ?ㅻ쾭?덉씠 蹂寃??놁씠 諛섑솚
        return
        if elapsed > 10 and self._conn_phase < 1:
            self._conn_phase = 1
            self._show_connect_overlay("移대찓???곌껐 吏??)
        elif elapsed > 20:
            self._show_connect_overlay("移대찓???곌껐 ?ㅽ뙣. USB/?꾩썝???뺤씤?섏꽭??")

    # ?? overlay helpers ???????????????????????????????????????
    def _overlay_update_hole(self):
        try:
            if not getattr(self, "overlay", None): return
            target = self.preview_label
            if hasattr(self.overlay, "bind_hole_widget"):
                # ?꾨━酉??쇰꺼 ?ㅼ젣 ?곸뿭怨??뺥솗???쇱튂?섎룄濡?異뺤냼??쓣 0?쇰줈 ?ㅼ젙
                self.overlay.bind_hole_widget(target, shrink_px=0)
            elif hasattr(self.overlay, "set_hole_widget"):
                self.overlay.set_hole_widget(target)
            elif hasattr(self.overlay, "set_hole"):
                r = target.geometry()
                tl = target.mapTo(self, r.topLeft()); br = target.mapTo(self, r.bottomRight())
                self.overlay.set_hole(QRect(tl, br))
            # ?뺣? 留ㅽ븨?쇰줈 ??踰???蹂댁젙(?ㅻ쾭?덉씠 醫뚰몴 湲곗?)
            try:
                r2 = target.geometry()
                g_tl = target.mapToGlobal(r2.topLeft())
                g_br = target.mapToGlobal(r2.bottomRight())
                tl2 = self.overlay.mapFromGlobal(g_tl)
                br2 = self.overlay.mapFromGlobal(g_br)
                rect2 = QRect(tl2, br2)
                # 오프셋 보정: 기본 -2px, 환경변수 PS_HOLE_OFF로 오버라이드(-3/-1 등 A/B 테스트)
                try:
                    import os as _os
                    _off = int(str(_os.getenv("PS_HOLE_OFF", "-2")).strip())
                except Exception:
                    _off = -2
                rect2.adjust(_off, _off, 0, 0)
                if hasattr(self.overlay, 'set_hole'):
                    self.overlay.set_hole(rect2)
                # ??긽 理쒖긽??蹂댁옣
                try: self.overlay.raise_()
                except Exception: pass
            except Exception:
                pass
        except Exception: pass

    def _overlay_show_during_capture(self):
        """珥ъ쁺 吏꾪뻾 以?媛?대뱶 ?ㅻ쾭?덉씠瑜??쒖떆?쒕떎(踰꾪듉 ?좊컻留?."""
        try:
            # 踰꾪듉?쇰줈 ?쒖옉??珥ъ쁺???꾨땲硫??ㅻ쾭?덉씠瑜??쒖떆?섏? ?딅뒗??            if not getattr(self, "_overlay_from_button", False):
                return
            self._capturing = True
            if not getattr(self, "overlay", None): return
            # 媛?대뱶 ?쇱씤???쒖떆?섎룄濡??좏겙 ?ㅼ젙
            try:
                if hasattr(self.overlay, 'refresh_tokens'):
                    self.overlay.refresh_tokens({'show_guide': True})
            except Exception:
                pass
            # 珥ъ쁺 以??섏씠??留덉뒪???쒓굅 ?붽뎄???곕씪 諛섑닾紐??ㅼ젙? ?앸왂?쒕떎.
            # ?섏씠???쒓굅: 留덉뒪???뚰뙆 0?쇰줈 ?ㅼ젙
            try:
                from PySide6.QtGui import QColor
                if hasattr(self.overlay, "set_mask_color"):
                    self.overlay.set_mask_color(QColor(0,0,0,0))
            except Exception:
                pass
            if hasattr(self.overlay, "set_block_input"):
                self.overlay.set_block_input(True)
            self.overlay.setGeometry(self.rect())
            self._overlay_update_hole()
            # ?붾쾭洹? 以묒븰 ?뚯뒪??諛곗?/?щ줈???쒖떆 ?좎?
            try:
                if hasattr(self.overlay, 'set_debug_cross'):
                    self.overlay.set_debug_cross(True)
                if hasattr(self.overlay, 'set_badge_center'):
                    self.overlay.set_badge_center(True)
                if hasattr(self.overlay, 'update_badges'):
                    self.overlay.update_badges('DEBUG: 중앙 테스트', {})
            except Exception:
                pass
            self.overlay.show(); self.overlay.raise_()
        except Exception: pass

    def _overlay_hide(self):
        """媛?대뱶 ?ㅻ쾭?덉씠瑜??④린怨??낅젰 李⑤떒???댁젣?쒕떎."""
        try:
            self._capturing = False
            if not hasattr(self, "overlay") or self.overlay is None: return
            try:
                if hasattr(self.overlay, 'refresh_tokens'):
                    self.overlay.refresh_tokens({'show_guide': False})
            except Exception:
                pass
            if hasattr(self.overlay, "set_block_input"):
                self.overlay.set_block_input(False)
            self.overlay.hide(); self.overlay.lower()
        except Exception: pass

    def end_capture(self, success: bool):
        """珥ъ쁺 醫낅즺 泥섎━: ?곹깭/?ㅻ쾭?덉씠/踰꾪듉???뺣━?쒕떎."""
        self._overlay_hide()
        self.set_prev_mode("enabled"); self.set_prev_enabled(True)
        if success:
            self.set_next_enabled(True); self.set_next_mode("lit")
        else:
            self.set_next_enabled(False); self.set_next_mode("disabled")
        # 踰꾪듉 ?좊컻 ?뚮옒洹??댁젣 諛?濡쒓퉭
        self._overlay_from_button = False
        try:
            _log.info("[CAPTURE] end: success=%s", success)
        except Exception:
            pass

    def _sync_preview_label_geom(self):
        try:
            r = self.preview_box.contentsRect()
            lw = self.preview_label.width(); lh = self.preview_label.height()
            x = r.x() + max(0, (r.width() - lw) // 2)
            y = r.y() + max(0, (r.height() - lh) // 2)
            self.preview_label.setGeometry(x, y, lw, lh)
        except Exception: pass

    # ?? LED helpers ???????????????????????????????????????????
    def _refresh_led(self):
        try:
            d = int(getattr(self, "_T", {}).get("LED_D", LED_D))
            mode = getattr(self, "_lv_mode", 'off')
            col = "#4CAF50" if mode=='sdk' else ("#FFC107" if mode=='file' else "#f44336")
            self.cam_led.setFixedSize(d, d)
            self.cam_led.setStyleSheet(f"QLabel#CamLED {{ border-radius:{d//2}px; background:{col}; }}")
        except Exception: pass

    def set_camera_connected(self, on: bool):
        self._lv_mode = 'sdk' if on else 'off'; self._refresh_led()

    def set_led_mode(self, mode: str):
        self._lv_mode = mode if mode in ('sdk','file','off') else 'off'; self._refresh_led()

    # ?? ?⑥텞??紐낅졊(F1/F2/F3) ?????????????????????????????????
    def _cmd_one_shot_af(self):
        """F1 ???먮뒗 ?대? ?몄텧濡?AF瑜?1???섑뻾?쒕떎."""
        def _run():
            ok = False
            try:
                cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None) or self.lv
                if hasattr(cam, 'one_shot_af'):
                    rc = cam.one_shot_af(); ok = (rc == 0 or rc is True)
            except Exception: ok = False
            QTimer.singleShot(0, lambda: self.toast.popup("AF ?꾨즺" if ok else "AF ?ㅽ뙣"))
        threading.Thread(target=_run, daemon=True).start()

    def _cmd_one_shot_awb(self):
        def _run():
            ok = False
            try:
                cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None) or self.lv
                if hasattr(cam, 'one_shot_awb'):
                    rc = cam.one_shot_awb(); ok = (rc == 0 or rc is True)
            except Exception: ok = False
            QTimer.singleShot(0, lambda: self.toast.popup("AWB ?꾨즺" if ok else "AWB ?ㅽ뙣"))
        threading.Thread(target=_run, daemon=True).start()

    def _cmd_shoot_one(self):
        self.toast.popup("珥ъ쁺??)
        def _run():
            ok = False
            try:
                cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None)
                if cam and hasattr(cam, 'shoot_one'):
                    rc = cam.shoot_one()
                    ok = (rc == 0 or rc is True or (isinstance(rc, dict) and rc.get("ok")))
                elif hasattr(self.lv, 'shoot_one'):
                    rc = self.lv.shoot_one()
                    ok = (rc == 0 or rc is True)
            except Exception: ok = False
            QTimer.singleShot(0, lambda: self.toast.popup("珥ъ쁺 ?깃났" if ok else "珥ъ쁺 ?ㅽ뙣"))
        threading.Thread(target=_run, daemon=True).start()

    # ?? ?몃꽕???뚯씪 愿由???????????????????????????????????????
    def _set_thumb_from_file(self, idx: int, path: str):
        try:
            if idx < 0 or idx >= len(self._thumb_imgs): return
            pm = QPixmap(path)
            if pm.isNull(): return
            w, h = self._tile_size()
            self._thumb_imgs[idx].setPixmap(pm.scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        except Exception: pass

    def _seq_path(self, idx:int) -> str:
        try:
            CAP_DIR.mkdir(parents=True, exist_ok=True)
            return str(CAP_DIR / CAP_SEQ[idx])
        except Exception:
            return str(CAP_DIR / f"{idx+1:02d}.jpg")

    def _clear_captures(self):
        try:
            CAP_DIR.mkdir(parents=True, exist_ok=True)
            for name in CAP_SEQ:
                p = CAP_DIR / name
                try:
                    if p.exists(): p.unlink()
                except Exception: pass
                self.session['shot_paths'] = []
            self.session['shot_thumbs'] = []
            self.session['captures'] = ["", "", "", ""]
            self.session['raw_captures'] = ["", "", "", ""]
            for i in range(len(getattr(self, '_thumb_imgs', []))):
                try: self._thumb_imgs[i].clear()
                except Exception: pass
        except Exception:
            pass

    # ?? placeholder ??????????????????????????????????????????
    def _show_placeholder(self):
        try:
            p = Path(PLACEHOLDER_DEFAULT)
            if not p.exists():
                p2 = Path.cwd() / "app" / "assets" / "placeholder.png"
                p = p2 if p2.exists() else p
            if not p.exists(): return
            img = QImage(str(p))
            if img.isNull(): return
            pix = render_placeholder(img, self.preview_label.width(), self.preview_label.height())
            if not pix.isNull(): self.preview_label.setPixmap(pix)
        except Exception: pass

    def _on_lv_status(self, mode: str):
        """LiveView ?곹깭 蹂寃???LED? 濡쒓렇瑜?媛깆떊?쒕떎."""
        self.set_led_mode(mode)
        try: _log.info("[LV] status=%s", mode)
        except Exception: pass
        if mode == 'sdk':
            # 연결 직후 저장/프록시 및 저장 폴더 설정 적용(존재 시)
            try:
                cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None) or self.lv
                if hasattr(cam, 'set_save_and_proxy'):
                    try: cam.set_save_and_proxy(True, True)
                    except Exception: pass
                if hasattr(cam, 'set_save_dir'):
                    try: cam.set_save_dir(r"C:\\PhotoBox\\raw")
                    except Exception: pass
            except Exception:
                pass
            try: self._prep_af_awb()
            except Exception: pass

    # 媛?대뜕???곗냽 留뚯” 媛먯? 諛??먮룞 ?곗궗 ?쒖옉
    def _check_auto_sequence(self, metrics: dict):
        """metrics.ready媛 0.8珥??곗냽 True硫??먮룞 4?곗궗瑜??쒖옉?쒕떎."""
        if getattr(self, "_seq_running", False) or getattr(self, "_capturing", False):
            return
        ready = False
        try:
            ready = bool(metrics.get("ready", False))
        except Exception:
            ready = False
        now = time.time()
        if ready:
            if getattr(self, "_ready_since", None) is None:
                self._ready_since = now
            elif (now - float(self._ready_since)) >= 0.8:
                self._start_auto_sequence()
        else:
            self._ready_since = None

    def _start_auto_sequence(self):
        """?먮룞 4?곗궗 ?쒗?ㅻ? ?쒖옉?쒕떎(泥レ꺑 5珥? ?댄썑 3珥?媛꾧꺽)."""
        if getattr(self, "_seq_running", False):
            return
        self._seq_running = True
        self._seq_index = -1
        self._clear_captures()
        self._lock_ui_for_capture(True)
        self._overlay_show_during_capture()
        # 泥???移댁슫?몃떎???쒖옉
        try:
            _log.info("[SEQ] start first=5s")
        except Exception:
            pass
        self._count_left = 5
        if not self._count_timer.isActive():
            self._count_timer.start()

    def _try_af_async(self, idx: Optional[int] = None):
        """AF瑜?鍮꾨룞湲곕줈 1???쒕룄?쒕떎(濡쒓렇: [AF] i=.. rc=..)."""
        def _run():
            try:
                cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None) or self.lv
                if hasattr(cam, 'one_shot_af'):
                    rc_code = -1
                    try:
                        rc = cam.one_shot_af()
                        rc_code = 0 if (rc is True or rc == 0) else -1
                    except Exception:
                        rc_code = -1
                    try:
                        _log.info("[AF] i=%s rc=%s", (idx if idx is not None else "?"), rc_code)
                    except Exception:
                        pass
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    # 媛?대뜕???곗냽 留뚯” 媛먯? 諛??먮룞 ?곗궗 ?쒖옉
    def _check_auto_sequence(self, metrics: dict):
        """metrics.ready媛 0.8珥??곗냽 True硫??먮룞 4?곗궗瑜??쒖옉?쒕떎."""
        if getattr(self, "_seq_running", False) or getattr(self, "_capturing", False):
            return
        ready = False
        try:
            ready = bool(metrics.get("ready", False))
        except Exception:
            ready = False
        now = time.time()
        if ready:
            if getattr(self, "_ready_since", None) is None:
                self._ready_since = now
            elif (now - float(self._ready_since)) >= 0.8:
                self._start_auto_sequence()
        else:
            self._ready_since = None

    def _start_auto_sequence(self):
        """?먮룞 4?곗궗 ?쒗?ㅻ? ?쒖옉?쒕떎(泥レ꺑 5珥? ?댄썑 3珥?媛꾧꺽)."""
        if getattr(self, "_seq_running", False):
            return
        self._seq_running = True
        self._seq_index = -1
        self._clear_captures()
        self._lock_ui_for_capture(True)
        self._overlay_show_during_capture()
        # 泥??? 5珥?移댁슫?몃떎?? T-3??AF
        self._count_left = 5
        if not self._count_timer.isActive():
            self._count_timer.start()

    def _try_af_async(self):
        """AF瑜?鍮꾨룞湲곕줈 1???쒕룄?쒕떎."""
        def _run():
            try:
                cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None) or self.lv
                if hasattr(cam, 'one_shot_af'):
                    try: cam.one_shot_af()
                    except Exception: pass
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    # ?? 蹂댁“: 珥덇린 AF/AWB ????????????????????????????????????
    def _prep_af_awb(self, callback=None):
        def _work():
            try:
                cam = getattr(self.lv, 'cam', None)
                if cam:
                    if hasattr(cam, 'one_shot_af'):
                        try: cam.one_shot_af()
                        except Exception: pass
                    if hasattr(cam, 'one_shot_awb'):
                        try: cam.one_shot_awb()
                        except Exception: pass
            except Exception: pass
            if callable(callback): QTimer.singleShot(0, callback)
        threading.Thread(target=_work, daemon=True).start()




