# -*- coding: utf-8 -*-

from __future__ import annotations
import os, time, threading, logging
from pathlib import Path
from typing import Optional, Dict
from app.utils import control_camera_sdk as cam_sdk

from PySide6.QtCore import Qt, QTimer, QRect, Signal
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


os.add_dll_directory(r"C:\dev\photostudio")
os.environ.setdefault("CRSDK_DLL", r"C:\dev\photostudio\crsdk_pybridge.dll")

CAP_UNIFIED = str(os.getenv("CAP_UNIFIED", "1")).strip().lower() not in ("0", "off", "false")


_log = logging.getLogger("CAP")
DEBUG_CAP = (str(os.getenv("CAP_DEBUG", "1")).strip() == "1")

CAP_OVERLAY_OFF = str(os.getenv("CAP_OVERLAY", "1")).strip().lower() in ("0", "off", "false")

try:
    from app.utils.control_camera import CameraControl
except Exception:
    CameraControl = None  # noqa: N816

LiveViewService = None  # disabled
LV_DEFAULT_DIR = r"C:\PhotoBox\lv"
LV_DEFAULT_MS_SDK  = 33
LV_DEFAULT_MS_FILE = 48
PLACEHOLDER_DEFAULT = r"app\assets\placeholder.png"

CAP_DIR = Path(r"C:\PhotoBox\captures")
CAP_SEQ = ["01.jpg","02.jpg","03.jpg","04.jpg"]

TH_COUNT = 4; TH_GAP = 36; TH_H = 216; TH_W_3040 = 162; TH_W_3545 = 168
P_GAP = 36; PREV_H = 1008; PREV_W_3040 = 756; PREV_W_3545 = 784
P2_GAP = 30; CTRL_H = 45; BTN_R = 12; LED_D = 12; CTRL_GAP = 21

class BusyOverlay(QWidget):
    """Busy overlay with dim background and message."""
    def __init__(self, parent: QWidget, text: str = "Connecting to camera"):
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
        base = str(t or "").rstrip(" .")
        self.msg.setText(base)

    def _tick(self):
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
            start_angle = int((self._angle % 360) * 16)
            span_angle = int(120 * 16)
            qp.drawArc(cx - r, cy - r, 2*r, 2*r, start_angle, span_angle)
        except Exception:
            pass

class Toast(QWidget):
    """Simple toast message at top of the screen."""
    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setStyleSheet("background: rgba(0,0,0,160); border-radius:10px;")
        self.lbl = QLabel("", self)
        self.lbl.setStyleSheet("color:white; padding:10px;")
        self.lbl.setAlignment(Qt.AlignCenter)
        self._timer = QTimer(self)
        self._timer.setInterval(1400)
        self._timer.timeout.connect(self.hide)
        self.hide()

    def popup(self, text: str):
        self.lbl.setText(text)
        pw = self.parentWidget().width() if self.parentWidget() else 800
        w = max(200, pw // 3); h = 50
        x = (pw - w) // 2
        self.setGeometry(x, 40, w, h)
        self.lbl.setGeometry(0, 0, w, h)
        self.show(); self.raise_(); self._timer.start()
class CapturePage(BasePage):
    # 프레임 전달을 위한 UI 스레드 시그널
    frameReady = Signal(QImage)
    __doc__ = "Capture page: camera preview and shooting UI."
    def __init__(self, theme, session: dict, parent=None):
        super().__init__(theme, steps=STEPS, active_index=2, parent=parent)
        self.session = session; self.session.setdefault("guide_skip", True)

        center = QWidget(self)
        layout = QVBoxLayout(center); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)

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


        self._gap36 = QWidget(self); self._gap36.setFixedHeight(0); layout.addWidget(self._gap36, 0)


        self.preview_box = QFrame(self); self.preview_box.setObjectName("PreviewBox")
        self.preview_box.setStyleSheet(f"QFrame#PreviewBox {{ background: transparent; border: {self._normal_px()}px solid {self._primary_hex()}; border-radius: 0px; }}")
        layout.addWidget(self.preview_box, 0, Qt.AlignHCenter)
        self.preview_label = QLabel(self.preview_box)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setAttribute(Qt.WA_TranslucentBackground, False)
        self.preview_label.setStyleSheet("background: #808080; padding:0; margin:0; border:none;")

        self._gap36b = QWidget(self); self._gap36b.setFixedHeight(0); layout.addWidget(self._gap36b, 0)


        self.ctrl = QWidget(self)
        hb = QHBoxLayout(self.ctrl); hb.setContentsMargins(0,0,0,0); hb.setSpacing(0); hb.setAlignment(Qt.AlignHCenter)
        self.cam_led = QLabel(self.ctrl); self.cam_led.setObjectName("CamLED"); hb.addWidget(self.cam_led, 0)
        self.btn_capture = QPushButton("Shoot", self.ctrl); self.btn_capture.setObjectName("BtnCapture")
        self.btn_retake  = QPushButton("Retake", self.ctrl); self.btn_retake.setObjectName("BtnRetake")
        self.btn_capture.clicked.connect(self._on_capture_clicked)
        self.btn_retake.clicked.connect(self._on_retake_clicked)
        hb.addWidget(self.btn_capture, 0); hb.addWidget(self.btn_retake, 0)
        layout.addWidget(self.ctrl, 0, Qt.AlignHCenter)
        layout.addStretch(1)

        # CameraControl handle (assigned at connect time)
        self._cam = None
        self._settings_cache = {}; self._refresh_settings_tokens()
        self._count_timer = QTimer(self); self._count_timer.setInterval(1000)
        self._count_timer.timeout.connect(self._tick_countdown)
        self._count_left = 0; self._capturing = False
        self._armed_for_auto = False
        self._seq_running = False
        self._seq_index = -1
        self._ready_since = None
        self._seq_timer = QTimer(self); self._seq_timer.setInterval(1000)
        self._seq_timer.timeout.connect(self._tick_seq_countdown)
        self._last_qimage_log_ms = 0
        self._seq_count_left = 0
        # 카운트다운 표시 활성 플래그(중복 호출 방지용)
        self._countdown_active = False
        self._connecting = False
        # 연결 시도 중복 방지를 위한 락/디바운싱 상태
        self._connect_lock = threading.Lock()
        self._last_connect_ms = 0

        self._lv_status_hooked = False
        # 연결 처리 중복(inflight) 상태 플래그
        self._conn_inflight = False
        # AF 사용 여부 설정(CAP_USE_AF=1이면 AF 시도)
        try:
            self._use_af = str(os.getenv("CAP_USE_AF", "0")).strip().lower() in ("1","true","on")
        except Exception:
            self._use_af = False
        self._rebuild_layout_tokens(); self._apply_layout_tokens()

        try:
            bus = QApplication.instance().property("settings_bus")
            if hasattr(bus, "changed"): bus.changed.connect(self._on_settings_changed)
        except Exception: pass
        try: _log.info("[CONN] start enter")
        except Exception: pass

        self.setCentralWidget(center, margin=(0,0,0,0), spacing=0, center=False, max_width=None)
        self.set_prev_mode("enabled"); self.set_next_mode("disabled"); self.set_next_enabled(False)
        # frameReady 시그널을 UI 스레드로 안전하게 연결(QueuedConnection 권장)
        # 프레임 시그널을 UI 슬롯에 연결(Queue 방식)
        try:
            try:
                self.frameReady.connect(self._on_qimage, Qt.ConnectionType.QueuedConnection)
            except Exception:
                self.frameReady.connect(self._on_qimage)
        except Exception:
            pass

        self._read_ratio()

        self.overlay = AiOverlay(self)
        try: self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        except Exception: pass

        try:
            if hasattr(self.overlay, "bind_session"): self.overlay.bind_session(self.session)
        except Exception: pass
        try:
            if hasattr(self.overlay, 'set_ratio_from_session'):
                self.overlay.set_ratio_from_session(self.get_ratio())
            if hasattr(self.overlay, 'bind_hole_widget'):
                self.overlay.bind_hole_widget(self.preview_label, shrink_px=0)
        except Exception:
            pass
        self.overlay.setGeometry(self.rect()); self.overlay.hide(); self.overlay.lower()

        self.busy = BusyOverlay(self, "Connecting camera...")
        try:
            self.busy.setText("Connecting camera...")
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

        try:
            if getattr(self, 'face', None) and hasattr(self.face, 'start'):
                self.face.start()
        except Exception:
            pass
        try:
            if getattr(self, 'pose', None) and hasattr(self.pose, 'start'):
                self.pose.start()
        except Exception:
            pass

        self._ai_rate_ms = 500; self._ai_last_ms = 0; self._ema: Dict[str, float] = {}
        self.guide = Guidance(rate_ms=500)
        # Guidance 입력 최신 프레임 버퍼(ndarray)와 처리 주기(10~15Hz)
        self._rgb_latest = None
        self._rgb_lock = threading.Lock()
        self._ai_timer = QTimer(self)
        try:
            _ai_iv = int(getattr(self, '_ai_rate_ms', 83) or 83)
        except Exception:
            _ai_iv = 83
        _ai_iv = max(66, min(100, _ai_iv))
        self._ai_timer.setInterval(_ai_iv)
        self._ai_timer.timeout.connect(self._ai_tick)
        self._ai_timer.start()

        # 프로그램 종료 시 카메라/라이브뷰를 안전하게 종료한다.
        try:
            app = QApplication.instance()
            if app and hasattr(app, 'aboutToQuit'):
                app.aboutToQuit.connect(self._stop_camera)
        except Exception:
            pass


        try:
            if CAP_OVERLAY_OFF:
                _log.info("[OVL] overlay disabled by CAP_OVERLAY=0: fallback to Toast")
        except Exception:
            pass

        self.lv = None
        self._first_frame_seen = False
        self._conn_timer = QTimer(self); self._conn_timer.setInterval(400)
        self._conn_timer.timeout.connect(self._conn_tick)

        self._debug = bool(DEBUG_CAP)
        self._dbg_last_ms = 0


        try:
            if hasattr(self.lv, 'stop'):
                self.lv.stop()
        except Exception:
            pass


        self._save_dir_set = False


    def _overlay_badge(self, text: str) -> None:
        try:
            if CAP_OVERLAY_OFF:
                try:
                    self.toast.popup(text or "")
                except Exception:
                    pass
            # Guidance 호출 조건 계산(중복 호출 방지) 및 주기(약 10~15Hz)
                return
            if hasattr(self.overlay, "set_badge_center"):
                try: self.overlay.set_badge_center(True)
                except Exception: pass
            if hasattr(self.overlay, "update_badges"):
                try: self.overlay.update_badges(text or "", {})
                except Exception: pass
            try: self.overlay.show(); self.overlay.raise_()
            except Exception: pass
        except Exception:
            pass


    def showEvent(self, e):
        super().showEvent(e)
        self.set_prev_mode("enabled"); self.set_next_mode("disabled"); self.set_next_enabled(False)
        self._read_ratio()
        self._rebuild_layout_tokens(); self._apply_layout_tokens(); self._apply_ctrl_styles()
        self._show_placeholder()
        QTimer.singleShot(0, self._connect_camera_async)

        try:
            if self.face: self.face.start()
        except Exception: pass
        try:
            if self.pose: self.pose.start()
        except Exception: pass

        self._first_frame_seen = False
        self._conn_phase = 0
        self._conn_started = time.time()
        self._show_connect_overlay("Connecting camera...")
        self._conn_timer.start()


        try:
            self.overlay.setGeometry(self.rect())
            self.overlay.hide(); self.overlay.lower()
            self.preview_box.raise_(); self.preview_label.raise_()

            try: QTimer.singleShot(0, self._overlay_force_bind_and_show)
            except Exception: pass
        except Exception: pass

    def resizeEvent(self, ev):
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
            self._cmd_one_shot_af(); return
        if k == Qt.Key_F2:  # AWB
            self._cmd_one_shot_awb(); return
        if k == Qt.Key_F3:  # SHOT
            self._cmd_shoot_one(); return
        super().keyPressEvent(e)

    def _read_ratio(self):
        r = str(self.session.get("ratio", "3040")).strip()
        if r not in ("3040","3545"): r = "3040"
        self._ratio = r

    def get_ratio(self) -> str: return getattr(self, "_ratio", "3040")
    def ratio_tuple(self) -> tuple[int, int]: return (3,4) if self.get_ratio()=="3040" else (7,9)

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

    @staticmethod
    def _snap3(v: float) -> int:
        try:
            n = int(float(v)); return n - (n % 3)
        except Exception:
            return

    def _on_delay_changed(self, delay_id: int):
        try: v = int(delay_id)
        except Exception: v = 3
        if v not in (3,5,7): v = 3
        self.session["delay_sec"] = v
        try:
            btn = self.delay_group.button(v)
            if btn and not btn.isChecked(): btn.setChecked(True)
        except Exception: pass

    def _on_capture_clicked(self):
        # 캡처 버튼 클릭 처리: 중복 클릭 방지 및 저장 경로 설정
        # 캡처 버튼 클릭 처리: 중복 클릭 방지 및 저장 경로 설정
        
        try:
            _log.info("[BTN] capture clicked armed=%s capturing=%s", getattr(self, "_armed_for_auto", False), getattr(self, "_capturing", False))
        except Exception:
            pass
        # 디버그 토스트("BTN")는 비활성화한다.
        if self._capturing: return
        self._overlay_from_button = True
        self._armed_for_auto = True
        try:
            if hasattr(self, 'busy') and self.busy.isVisible():
                self.busy.hide(); self.busy.lower()
        except Exception:
            pass
        self._clear_captures()

        try:
            raw_dir = Path(r"C:\\PhotoBox\\raw")
            raw_dir.mkdir(parents=True, exist_ok=True)
            # Unified: CameraControl 인스턴스만 사용한다.
            # Unified 경로: CameraControl 인스턴스를 우선 사용한다.
            cam = getattr(self, '_cam', None)
            ok_set = False
            if cam and hasattr(cam, 'set_save_dir'):
                try:
                    ok_set = bool(cam.set_save_dir(str(raw_dir)))
                except Exception:
                    ok_set = False
                try:
                    _log.info("[SDK] set_save_dir rc=%s path=%s", ok_set, str(raw_dir))
                except Exception:
                    pass
            # 폴백 경로 제거: 핸들 없이 저장 설정 호출은 수행하지 않는다.
            if ok_set:
                self._save_dir_set = True
        except Exception:
            pass
        self._lock_ui_for_capture(True)
        # 자동 시퀀스 시작: 캡처 진행 오버레이 표시 및 프리뷰/오버레이 최상위로 정렬
        
        
        try:
            if hasattr(self.overlay, 'refresh_tokens'):
                self.overlay.refresh_tokens({'show_guide': True})
            self.overlay.setGeometry(self.rect())
            self._overlay_update_hole()
            try: self._overlay_force_bind_and_show()
            except Exception: pass
            try:
                if hasattr(self.overlay, 'set_debug_cross'):
                    self.overlay.set_debug_cross(True)
                self._overlay_badge("GUIDE ARMED")
            except Exception: pass

        except Exception: pass
        try:
            self._overlay_show_during_capture()
        except Exception:
            pass


        try:
            # CAP_FORCE_SEQ=1 이면 4장 연속 촬영(첫 5초, 이후 3초 간격)
            # CAP_FORCE_SEQ=1이면 4컷 자동 시퀀스를 강제로 실행(첫 5초, 이후 3초 간격)
            force_seq = str(os.getenv("CAP_FORCE_SEQ", "1")).strip().lower() in ("1","true","on")
        except Exception:
            force_seq = True
        try:
            if force_seq:
                self._start_auto_sequence(); return
        except Exception:
            pass
        try:
            self._seq_running = False
            self._seq_index = -1
            self._invoke_shoot(i=0)
        except Exception:
            pass

    def _on_retake_clicked(self):
        if getattr(self, "_count_timer", None) and self._count_timer.isActive(): self._count_timer.stop()
        self._count_left = 0; self._capturing = False
        self._overlay_from_button = False
        self.btn_capture.setEnabled(True)
        for _name in ('delay3','delay5','delay7'):
            b = getattr(self, _name, None)
            if b is None: continue
            try:
                b.setEnabled(False)
            except Exception:
                pass
        self._overlay_hide()
        self.set_next_enabled(False); self.set_next_mode("disabled")
        self.set_prev_mode("enabled"); self.set_prev_enabled(True)
        self._shot_index = 0; self._clear_captures()

        self._seq_running = False; self._seq_index = -1; self._ready_since = None
        if self._seq_timer.isActive(): self._seq_timer.stop()

    def _lock_ui_for_capture(self, on: bool):
        self._capturing = bool(on)
        self.set_prev_mode("disabled"); self.set_prev_enabled(False)
        self.set_next_mode("disabled"); self.set_next_enabled(False)
        for _name in ('delay3','delay5','delay7'):
            b = getattr(self, _name, None)
            if b is None: continue
            try:
                b.setEnabled(False)
            except Exception:
                pass
        try: self.btn_capture.setEnabled(not on)
        except Exception: pass

    def _start_countdown(self, sec: int):
        self._count_left = int(sec); self._count_timer.start()

    def _tick_countdown(self):
        self._count_left -= 1
        try:
            if self._count_left == 3 and getattr(self, '_use_af', False):
                self._try_af_async()
        except Exception:
            pass
        try:
            # 프리뷰 중앙 숫자(흰색) 표시: 오버레이 활성 시 남은 초를 중앙에 크게 띄운다.
            if self._count_left > 0:
                self._countdown_active = True
                if not CAP_OVERLAY_OFF:
                    self._overlay_badge(str(int(self._count_left)))
                else:
                    self.toast.popup(f"COUNTDOWN T-{int(self._count_left)}s")
        except Exception:
            pass
        if self._count_left > 0: return
        self._count_timer.stop(); self._countdown_active = False; self._invoke_shoot(i=0)

    def _tick_seq_countdown(self):
        self._seq_count_left -= 1

        try:
            if self._seq_count_left > 0:
                self._countdown_active = True
                if not CAP_OVERLAY_OFF:
                    if int(self._seq_count_left) <= 2:
                        self._overlay_badge(str(int(self._seq_count_left)))
                    else:
                        self._overlay_badge("")
                else:
                    if int(self._seq_count_left) <= 2:
                        self.toast.popup(f"COUNTDOWN T-{int(self._seq_count_left)}s")
        except Exception:
            pass
        if self._seq_count_left == 1 and getattr(self, '_use_af', False):
            try:
                self._try_af_async(idx=(getattr(self, "_seq_index", -1) + 1))
            except Exception:
                pass
        if self._seq_count_left <= 0:
            next_i = self._seq_index + 1
            self._seq_timer.stop()
            self._invoke_shoot(i=next_i)

    def _invoke_shoot(self, i: Optional[int]=None):
        def _work():
            ok = False; path = None; err = ""
            try:
                # Unified: CameraControl을 사용하여 촬영한다.
                cam = getattr(self, '_cam', None)
                t_mark = time.time()
                # Dry-run 토글: CAP_DRY_SHOT=1이면 네이티브 촬영 호출을 건너뛰고 UI/캡처만 수행한다.
                try:
                    dry = str(os.getenv("CAP_DRY_SHOT", "0")).strip().lower() in ("1","true","on")
                except Exception:
                    dry = False

                if dry:
                    rc = 0; ok = True
                elif cam and hasattr(cam, "shoot_one"):
                    try:
                        rc = int(cam.shoot_one())
                    except Exception:
                        rc = -1
                    ok = (rc == 0)
                    if ok:
                        # 최근 저장 파일을 우선 조회하고, 없으면 폴링으로 확보한다.
                        try:
                            p1 = self._try_fetch_last_saved(cam)
                        except Exception:
                            p1 = None
                        if not p1:
                            try:
                                p1 = self._poll_new_jpeg(since=t_mark, timeout_s=8.0, interval_s=0.2)
                            except Exception:
                                p1 = None
                        if p1:
                            path = p1
                else:
                    err = "shoot api not available"
                try:
                    rc_code = 0 if ok else -1
                    try:
                        _log.info("[SHOT] i=%s rc=%s%s", (i if i is not None else "?"), rc_code, " (dry)" if dry else "")
                    except Exception:
                        _log.info("[SHOT] i=%s rc=%s", (i if i is not None else "?"), rc_code)
                except Exception:
                    pass
            except Exception as e:
                err = str(e)
            def _done(): self._on_shoot_done(ok, path, err, i)
            QTimer.singleShot(0, _done)
        threading.Thread(target=_work, daemon=True).start()

    def _on_shoot_done(self, ok: bool, path: Optional[str], err: str="", idx: Optional[int]=None):
        thumb_path: Optional[str] = None
        # 인덱스를 먼저 계산한다(캡처 파일 cap_XX 저장에 사용).
        try:
            move_idx = int(idx) if idx is not None else int(len(self.session.get("shot_paths", [])))
        except Exception:
            move_idx = 0
        # 촬영 성공 여부와 무관하게 프리뷰 스크린샷(cap_XX)을 우선 저장한다.
        try:
            thumb_path = self._save_preview_snapshot_indexed(move_idx)
        except Exception:
            thumb_path = self._save_preview_thumbnail()
        if ok:
            if not getattr(self, "_seq_running", False):
                pass  # keep liveview after shot
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
                eff_i = move_idx
                arr_cap = self.session.setdefault('captures', ["", "", "", ""])
                arr_raw = self.session.setdefault('raw_captures', ["", "", "", ""])
                if 0 <= eff_i < len(arr_cap):
                    if thumb_path: arr_cap[eff_i] = str(Path(thumb_path).name)
                if 0 <= eff_i < len(arr_raw):
                    if path: arr_raw[eff_i] = str(Path(path).name)
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

            if getattr(self, "_seq_running", False):
                try:
                    self._seq_index = int(idx) if idx is not None else (getattr(self, "_seq_index", -1) + 1)
                    if self._seq_index >= 3:
                        self._seq_running = False
                        self.end_capture(False)
                    else:
                        self._seq_count_left = 3
                        if not self._seq_timer.isActive():
                            self._seq_timer.start()
                    return
                except Exception:
                    pass

            try:
                self._overlay_hide()
                self.btn_capture.setText("Capture"); self.btn_capture.setEnabled(True)
                for _name in ('delay3','delay5','delay7'):
                    b = getattr(self, _name, None)
                    if b is None: continue
                    try:
                        b.setEnabled(False)
                    except Exception:
                        pass
                self.set_prev_mode("enabled"); self.set_prev_enabled(True)
                self.set_next_mode("disabled"); self.set_next_enabled(False)
                self._capturing = False
            except Exception:
                pass

    def _save_preview_thumbnail(self) -> Optional[str]:
        try:
            pm = self.preview_label.grab()
            if not pm or pm.isNull(): return None
            out_dir = Path.cwd() / "captures"; out_dir.mkdir(parents=True, exist_ok=True)
            ts = time.strftime("%Y%m%d_%H%M%S"); out = out_dir / f"thumb_{ts}.jpg"
            pm.save(str(out), "JPG", 90); return str(out)
        except Exception:
            return None

    def _save_preview_snapshot_indexed(self, idx: int) -> Optional[str]:
        try:
            pm = self.preview_label.grab()
            if not pm or pm.isNull():
                return None
            out_dir = Path(r"C:\PhotoBox\cap")
            out_dir.mkdir(parents=True, exist_ok=True)
            # 요구사항: cap_01.jpg ~ cap_04 저장
            name = f"cap_{int(idx)+1:02d}.jpg"
            out = out_dir / name
            ok = pm.save(str(out), "JPG", 90)
            return str(out) if ok else None
        except Exception:
            return None

    def _move_capture_to_raw(self, idx: int, src_path: str) -> Optional[str]:
        try:
            src = Path(src_path)
            if not src.exists() or not src.is_file():
                return None
            raw_dir = Path(r"C:\\PhotoBox\\raw")
            raw_dir.mkdir(parents=True, exist_ok=True)
            dest = raw_dir / f"raw_{int(idx)+1:02d}.jpg"
            try:
                if src.resolve() == dest.resolve():
                    return str(dest)
            except Exception:
                pass
            try:
                if dest.exists():
                    dest.unlink()
            except Exception:
                pass
            try:
                src.rename(dest)
            except Exception:
                import shutil
                shutil.copy2(str(src), str(dest))
                try: src.unlink()
                except Exception: pass
            return str(dest)
        except Exception:
            return None

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

        try:
            p = cam_sdk.get_last_saved_jpeg(r"C:\\PhotoBox\\raw")
            if p:
                return p
        except Exception:
            pass
        try:
            _log.info("[SAVE] last_saved not found via SDK/Bridge (dir=%s)", r"C:\\PhotoBox\\raw")
        except Exception:
            pass
        return None

    def _poll_new_jpeg(self, since: float, timeout_s: float = 3.0, interval_s: float = 0.2) -> Optional[str]:
        t0 = time.time()
        candidates = [
            Path(r"C:\\PhotoBox\\raw"),
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

    def _apply_ctrl_styles(self):
        T = getattr(self, "_T", {})
        primary = self._primary_hex(); r = int(T.get("BTN_R", BTN_R))
        try: self.ctrl.layout().setSpacing(int(T.get("CTRL_GAP", CTRL_GAP)))
        except Exception: pass
        try:
            h = int(T.get("CTRL_H", CTRL_H))
            for b in (self.btn_capture, self.btn_retake):
                b.setFixedHeight(h)
            self.btn_capture.setMinimumWidth(int(T.get("W_ACT", 150)))
            self.btn_retake.setMinimumWidth(int(T.get("W_ACT", 150)))
        except Exception:
            pass
        thin = self._thin_px()
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
        try: self.ctrl.setStyleSheet(act)
        except Exception: pass
        self._refresh_led()

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
        self._refresh_settings_tokens()
        try:
            self.lv.configure(self._tok_lv_dir(), self._tok_ms_sdk(), self._tok_ms_file())
            try: _log.info("[SET] configure dir=%s ms_sdk=%s ms_file=%s", self._tok_lv_dir(), self._tok_ms_sdk(), self._tok_ms_file())
            except Exception: pass
        except Exception as e:
            try: _log.error("[SET] configure failed: %s", e)
            except Exception: pass

    def _connect_camera_async(self):
        # 연결 시도 디바운싱 및 중복 실행 방지 (중복 호출/빈번 호출)
        # 연결 시도 디바운싱 및 중복 실행 방지 (기능 동일, 주석 보정)
        # 연결 시작 디바운스(중복 호출/경합 방지)
        now_ms = int(time.time() * 1000)
        # 이미 연결 시도가 진행 중이면 드랍한다.
        if getattr(self, "_conn_inflight", False):
            try: _log.debug("[CONN] start drop: inflight")
            except Exception: pass
            return
        if (now_ms - int(getattr(self, "_last_connect_ms", 0))) < 300:
            try: _log.debug("[CONN] start drop: debounced (<300ms)")
            except Exception: pass
            return
        with getattr(self, "_connect_lock"):
            if self._connecting:
                try: _log.debug("[CONN] start drop: already connecting")
                except Exception: pass
                return
            self._connecting = True
            self._last_connect_ms = now_ms
            self._conn_inflight = True
        self.busy.setText("Connecting camera...")
        self.set_led_mode('off')

        if not CAP_UNIFIED:
            try:
                if hasattr(self.lv, "statusChanged") and not self._lv_status_hooked:
                    try: self.lv.statusChanged.disconnect(self._on_lv_status)
                    except Exception: pass
                    self.lv.statusChanged.connect(self._on_lv_status)
                    self._lv_status_hooked = True
            except Exception: pass

        try:
            self.lv.configure(self._tok_lv_dir(), self._tok_ms_sdk(), self._tok_ms_file(), fallback_ms=3000)
        except Exception: pass

        def _work():
            ok = False
            try:
                try:
                    _log.info("[CONN] start enter (legacy)")
                except Exception:
                    pass
                ok = bool(self.lv.start(on_qimage=self._on_qimage))
            except Exception:
                ok = False
            def _done():
                if ok:
                    self._cam = getattr(self.lv, 'cam', None)
                    self.set_led_mode(getattr(self.lv, 'mode', 'off'))
                    self.busy.hide()
                else:
                    # 실패 시에만 즉시 해제(재시도 허용). 성공은 첫 프레임 수신 시 해제.
                    self._connecting = False
                    self.set_led_mode('off')
                    self.busy.setText("Camera connection failed")
                    QTimer.singleShot(1300, self.busy.hide)
                # inflight 종료(성공/실패 공통)
                try: self._conn_inflight = False
                except Exception: pass
            QTimer.singleShot(0, _done)

        def _work_unified():
            ok = False
            try:
                cam = getattr(self, '_cam', None)
                if cam is None and CameraControl is not None:
                    try:
                        cam = CameraControl(); self._cam = cam
                    except Exception:
                        cam = None; self._cam = None
                if cam is not None:
                    try:
                        raw_dir = str(Path(r"C:\\PhotoBox\\raw")); Path(raw_dir).mkdir(parents=True, exist_ok=True)
                        if hasattr(cam, 'set_save_dir'):
                            try: cam.set_save_dir(raw_dir)
                            except Exception: pass
                        # Unified 경로에서도 카드 저장+PC 프록시 저장을 활성화한다.
                        try:
                            if hasattr(cam, 'set_save_and_proxy'):
                                ok_sp = bool(cam.set_save_and_proxy(True, True))
                                try: _log.info("[SAVE] set_save_and_proxy rc=%s", ok_sp)
                                except Exception: pass
                        except Exception:
                            pass
                        ms = self._tok_ms_sdk()
                    except Exception:
                        ms = 33
                    try:
                        ok = bool(cam.start_liveview(self._on_frame_bytes, frame_interval_ms=ms))
                    except Exception:
                        ok = False
            except Exception:
                ok = False
            def _done():
                if ok:
                    try: self.set_led_mode('sdk')
                    except Exception: pass
                    try: self.busy.hide()
                    except Exception: pass
                else:
                    self._connecting = False
                    self.set_led_mode('off')
                    self.busy.setText("Camera connection failed")
                    QTimer.singleShot(1300, self.busy.hide)
                # inflight 종료(성공/실패 공통)
                try: self._conn_inflight = False
                except Exception: pass
            QTimer.singleShot(0, _done)
        # 스레드 기동 단일화: CAP_UNIFIED이면 unified만, 아니면 legacy만 실행
        # 런타임 분기: CAP_UNIFIED이면 unified 경로를 사용(legacy는 비활성)
        # 런타임 분기: CAP_UNIFIED이면 unified 경로 사용(legacy 비활성)
        threading.Thread(target=_work_unified, daemon=True).start()


    def _on_qimage(self, img: QImage):
        # 첫 프레임 수신 시 연결 오버레이/LED 상태 초기화 및 로그 출력.
        # 첫 프레임 수신 시 연결 오버레이/LED 상태를 초기화하고 로그를 남긴다.
        if not self._first_frame_seen:
            self._first_frame_seen = True
            self._conn_timer.stop()
            self._hide_connect_overlay()
            # 첫 프레임 수신 시 연결 진행 플래그 해제(싱글플라이트 종료)
            # 첫 프레임 수신 시 플래그/LED 정리
            try:
                if getattr(self, '_connecting', False):
                    self._connecting = False
            except Exception:
                self._connecting = False
            try:
                self.set_led_mode('sdk')
            except Exception:
                pass
            try:
                _log.info("[LV] first frame received")
            except Exception:
                pass

        try:
            w, h = self.preview_label.width(), self.preview_label.height()
            mode = 'sdk'
            # 저장 경로 설정은 연결 직후(unified 경로) 1회만 수행한다.

            pix = QPixmap()
            try:
                pix = render_placeholder(img, w, h) if mode == 'file' else render_transformed(img, w, h)
            except Exception:
                pix = QPixmap()
                try:
                    pix = QPixmap.fromImage(img).scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                except Exception:
                    pix = QPixmap()
            if not pix.isNull():
                self.preview_label.setPixmap(pix)
                try:
                    self.set_led_mode('sdk')
                except Exception:
                    pass
                try:
                    if hasattr(self, 'busy') and self.busy.isVisible():
                        self.busy.hide(); self.busy.lower()
                except Exception:
                    pass
                try:
                    ts_ms = int(time.time() * 1000)
                    if ts_ms - int(getattr(self, '_last_qimage_log_ms', 0)) >= 1000:
                        self._last_qimage_log_ms = ts_ms
                        _log.info("[LV] frame w=%s h=%s mode=%s", w, h, mode)
                except Exception:
                    pass
            # Guidance는 아래 레이트리미터 구간에서만 실행(중복 호출 제거)

            # Guidance 레이트리미트(10–15Hz 범위)
            try:
                ts_ai = int(time.time() * 1000)
                # 기본 12Hz(≈83ms), 10–15Hz 범위 클램프
                ai_rate = int(getattr(self, '_ai_rate_ms', 83) or 83)
                ai_rate = max(66, min(100, ai_rate))
                should_ai = (ts_ai - int(getattr(self, '_ai_last_ms', 0) or 0) >= ai_rate)
            except Exception:
                ts_ai, should_ai = int(time.time() * 1000), True
            if should_ai and hasattr(self, 'guide'):
                try:
                    self._ai_last_ms = ts_ai
                    if hasattr(self.guide, 'set_input_source'):
                        self.guide.set_input_source('sdk' if mode == 'sdk' else 'file')
                    # 입력 전달: 원본 QImage(img) 전달(추가 변환 불필요)
                    # 단일 디코딩: 원본 QImage(img)만 전달(추가 변환 없음)
                    payload, badges, metrics = self.guide.update(
                        img,
                        self.get_ratio(), ts_ai,
                        getattr(self, 'face', None), getattr(self, 'pose', None)
                    )
                    try:
                        if hasattr(self.overlay, 'update_landmarks'):
                            self.overlay.update_landmarks(payload, normalized=True)
                    except Exception:
                        pass
                    try:
                        if hasattr(self, '_guidance_message') and hasattr(self.overlay, 'update_badges'):
                            msg = self._guidance_message(metrics)
                            # 카운트다운 중에는 배지 클리어를 건너뜀(숫자 유지)
                            if not getattr(self, '_countdown_active', False):
                                self.overlay.update_badges("", {})
                        elif hasattr(self.overlay, 'update_badges'):
                            if not getattr(self, '_countdown_active', False):
                                self.overlay.update_badges("", {})
                    except Exception:
                        pass
                    try:
                        self.overlay.show(); self.overlay.raise_()
                    except Exception:
                        pass
                except Exception:
                    pass
            else:
                try: self.overlay.hide(); self.overlay.lower()
                except Exception: pass

            self.set_led_mode(mode)
        except Exception:
            pass
    def _show_connect_overlay(self, text: str):
        try:
            self.busy.setText(text)
            self.busy.resize(self.size())
            self.busy.show(); self.busy.raise_()
        except Exception:
            pass

    def _hide_connect_overlay(self):
        try:
            self.busy.hide(); self.busy.lower()
        except Exception:
            pass
    
    def _guidance_message(self, metrics: dict) -> str:
        try:

            def _ema(key: str, val: float) -> float:
                alpha = 2.0 / (10.0 + 1.0)  # 10-frame EMA
                prev = float(self._ema.get(key, val))
                cur = (alpha * float(val)) + ((1.0 - alpha) * prev)
                self._ema[key] = cur
                return cur

            sh_ok = bool(metrics.get('shoulder_ok', False))
            eye_ok = bool(metrics.get('eyes_ok', False) or metrics.get('eye_level_ok', False))
            yaw_ok = bool(metrics.get('yaw_ok', False))
            pitch_ok = bool(metrics.get('pitch_ok', False))


            if 'shoulder_level' in metrics:
                sh = abs(float(metrics.get('shoulder_level', 0.0)))
                sh = _ema('shoulder_level', sh)
                sh_ok = sh <= float(metrics.get('shoulder_thr', 2.0))
            if 'eyes_horiz' in metrics:
                eh = abs(float(metrics.get('eyes_horiz', 0.0)))
                eh = _ema('eyes_horiz', eh)
                eye_ok = eh <= float(metrics.get('eyes_thr', 2.0))
            if 'yaw_deg' in metrics:
                yw = abs(float(metrics.get('yaw_deg', 0.0)))
                yw = _ema('yaw_deg', yw)
                yaw_ok = yw <= float(metrics.get('yaw_thr', 5.0))
            if 'pitch_deg' in metrics:
                ph = abs(float(metrics.get('pitch_deg', 0.0)))
                ph = _ema('pitch_deg', ph)
                pitch_ok = ph <= float(metrics.get('pitch_thr', 5.0))

            if not sh_ok:
                return "Adjust shoulders level"
            if not eye_ok:
                return "Align eyes level"
            if not yaw_ok:
                return "Adjust yaw"
            if not pitch_ok:
                return "Adjust pitch"
        except Exception:
            pass

    def _stop_camera(self):
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
        try:
            cam = getattr(self, '_cam', None)
            if cam and hasattr(cam, 'disconnect'):
                cam.disconnect()
        except Exception:
            pass
        try:
            self._cam = None
        except Exception:
            pass
        self.set_led_mode('off')
        self._show_placeholder()
    
    def on_before_prev(self, session): self._stop_camera(); return True
    def on_before_next(self, session): self._stop_camera(); return True

    def _conn_tick(self):
        if self._first_frame_seen:
            self._conn_timer.stop(); self._hide_connect_overlay(); return
        elapsed = time.time() - getattr(self, "_conn_started", time.time())
        return
        if elapsed > 10 and self._conn_phase < 1:
            self._conn_phase = 1
            self._show_connect_overlay("Connecting...")
        elif elapsed > 20:
            self._show_connect_overlay("Connection cannot be established. Check USB/power.")

    def _overlay_update_hole(self):
        try:
            if not getattr(self, "overlay", None): return
            target = self.preview_label
            if hasattr(self.overlay, "bind_hole_widget"):
                self.overlay.bind_hole_widget(target, shrink_px=0)
            elif hasattr(self.overlay, "set_hole_widget"):
                self.overlay.set_hole_widget(target)
            elif hasattr(self.overlay, "set_hole"):
                r = target.geometry()
                tl = target.mapTo(self, r.topLeft()); br = target.mapTo(self, r.bottomRight())
                self.overlay.set_hole(QRect(tl, br))
            try:
                r2 = target.geometry()
                g_tl = target.mapToGlobal(r2.topLeft())
                g_br = target.mapToGlobal(r2.bottomRight())
                tl2 = self.overlay.mapFromGlobal(g_tl)
                br2 = self.overlay.mapFromGlobal(g_br)
                rect2 = QRect(tl2, br2)
                try:
                    import os as _os
                    _off = int(str(_os.getenv("PS_HOLE_OFF", "-2")).strip())
                except Exception:
                    _off = -2
                rect2.adjust(_off, _off, 0, 0)
                if hasattr(self.overlay, 'set_hole'):
                    self.overlay.set_hole(rect2)
                try: self.overlay.raise_()
                except Exception: pass
            except Exception:
                pass
        except Exception: pass

    def _overlay_force_bind_and_show(self):
        """If hole is invalid, retry binding a few times then show overlay."""
        try:
            if not getattr(self, "overlay", None):
                return
            self.overlay.setGeometry(self.rect())
            ok = False
            try:
                ok = bool(self._overlay_try_bind())
            except Exception:
                ok = False
            if ok:
                self.overlay.show(); self.overlay.raise_()
                return
            try: _log.info("[OVL] hole zero, schedule retry")
            except Exception: pass

            self._hole_retry_left = 20
            QTimer.singleShot(16, self._overlay_retry_tick)
        except Exception:
            pass

    def _overlay_retry_tick(self):
        try:
            if getattr(self, "_hole_retry_left", 0) <= 0:
                return
            self._hole_retry_left -= 1
            try: self._sync_preview_label_geom()
            except Exception: pass
            if getattr(self, "overlay", None):
                self.overlay.setGeometry(self.rect())
            ok = False
            try:
                ok = bool(self._overlay_try_bind())
            except Exception:
                ok = False
            if ok:
                self.overlay.show(); self.overlay.raise_()
            else:
                QTimer.singleShot(16, self._overlay_retry_tick)
        except Exception:
            pass

    def _overlay_show_during_capture(self):
        try:
            if not getattr(self, "_overlay_from_button", False):
                return
            if hasattr(self.overlay, "refresh_tokens"):
                self.overlay.refresh_tokens({"show_guide": True})
        except Exception:
            pass
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
            try:
                if hasattr(self.overlay, 'set_debug_cross'):
                    self.overlay.set_debug_cross(True)
                self._overlay_badge("GUIDE ARMED")
            except Exception:
                pass

            try:
                if (getattr(self, '_armed_for_auto', False) or getattr(self, '_capturing', False)):
                    if hasattr(self, 'overlay') and self.overlay and not self.overlay.isVisible():
                        self.overlay.setGeometry(self.rect())
                        self._overlay_update_hole()
                        self.overlay.show(); self.overlay.raise_()
                        try:
                            _log.info("[OVL] forced show (armed=%s cap=%s)", getattr(self, '_armed_for_auto', False), getattr(self, '_capturing', False))
                        except Exception:
                            pass
            except Exception:
                pass
            self.overlay.show(); self.overlay.raise_()
        except Exception: pass

    def _overlay_hide(self):
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
        self._overlay_hide()
        self.set_prev_mode("enabled"); self.set_prev_enabled(True)
        if success:
            self.set_next_enabled(True); self.set_next_mode("lit")
        else:
            self.set_next_enabled(False); self.set_next_mode("disabled")
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

    def _cmd_one_shot_af(self):
        def _run():
            ok = False
            try:
                cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None) or self.lv
                if hasattr(cam, 'one_shot_af'):
                    rc = cam.one_shot_af(); ok = (rc == 0 or rc is True)
            except Exception: ok = False
            QTimer.singleShot(0, lambda: self.toast.popup("AF OK" if ok else "AF Failed"))
        threading.Thread(target=_run, daemon=True).start()

    def _cmd_one_shot_awb(self):
        def _run():
            ok = False
            try:
                cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None) or self.lv
                if hasattr(cam, 'one_shot_awb'):
                    rc = cam.one_shot_awb(); ok = (rc == 0 or rc is True)
            except Exception: ok = False
            QTimer.singleShot(0, lambda: self.toast.popup("AWB OK" if ok else "AWB Failed"))
        threading.Thread(target=_run, daemon=True).start()

    def _cmd_shoot_one(self):
        self.toast.popup("  ?? ?..")
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
            QTimer.singleShot(0, lambda: self.toast.popup("Shoot OK" if ok else "Shoot Failed"))
        threading.Thread(target=_run, daemon=True).start()

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
        self.set_led_mode(mode)
        try: _log.info("[LV] status=%s", mode)
        except Exception: pass
        if mode == 'sdk':
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

    def _check_auto_sequence(self, metrics: dict):
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
        if getattr(self, "_seq_running", False):
            return
        self._seq_running = True
        self._seq_index = -1
        self._clear_captures()
        self._lock_ui_for_capture(True)
        # 카운트다운 시작을 위해 오버레이를 전면에 강제로 표시
        try:
            self._overlay_show_during_capture()
            if hasattr(self, 'busy'):
                try: self.busy.hide()
                except Exception: pass
            try:
                # 프리뷰 위에 오버레이가 오도록 순서 보장
                self.preview_label.raise_()
                self.overlay.raise_()
            except Exception:
                pass
        except Exception:
            pass
        try:
            _log.info("[SEQ] start first=4s")
        except Exception:
            pass
        # 첫 컷 카운트다운 활성화 및 숫자(4) 배지 표시
        self._countdown_active = True
        self._count_left = 4
        try:
            if not CAP_OVERLAY_OFF:
                self._overlay_badge("4")
        except Exception:
            pass
        if not self._count_timer.isActive():
            self._count_timer.start()

    def _try_af_async(self, idx: Optional[int] = None):
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
        # CAP_UNIFIED 경로가 활성화되어도 _work_unified 가 없을 수 있으므로 안전하게 가드한다.
        try:
            _target_fn = _work_unified if (CAP_UNIFIED and CameraControl) else _work
        except NameError:
            _target_fn = _work
        threading.Thread(target=_target_fn, daemon=True).start()








    def _overlay_try_bind(self) -> bool:
        """Compute overlay hole from preview label. True on success."""
        try:
            if not getattr(self, "overlay", None):
                return False
            target = self.preview_label
            if target.width() <= 0 or target.height() <= 0:
                try: _log.info("[OVL] hole bind skip: label size w=%s h=%s", target.width(), target.height())
                except Exception: pass
                return False
            r2 = target.geometry()
            g_tl = target.mapToGlobal(r2.topLeft())
            g_br = target.mapToGlobal(r2.bottomRight())
            tl2 = self.overlay.mapFromGlobal(g_tl)
            br2 = self.overlay.mapFromGlobal(g_br)
            from PySide6.QtCore import QRect, QRectF
            rect2 = QRect(tl2, br2)
            try:
                off = int(str(os.getenv("PS_HOLE_OFF", "0")).strip())
            except Exception:
                off = 0
            rect2.adjust(off, off, 0, 0)
            if rect2.width() <= 0 or rect2.height() <= 0:
                try: _log.info("[OVL] hole calc invalid after off=%s (w=%s h=%s)", off, rect2.width(), rect2.height())
                except Exception: pass
                return False
            if hasattr(self.overlay, 'set_hole'):
                self.overlay.set_hole(rect2)
            elif hasattr(self.overlay, 'set_hole_rect'):
                self.overlay.set_hole_rect(QRectF(rect2))
            try:
                _log.info("[OVL] hole-upd: ovl_w=%s ovl_h=%s hole_w=%s hole_h=%s off=%s",
                          self.overlay.width(), self.overlay.height(), rect2.width(), rect2.height(), off)
            except Exception: pass
            try: self.overlay.raise_()
            except Exception: pass
            return True
        except Exception:
            return False

    def _on_frame_bytes(self, data: bytes, ts_ms: int, meta: dict):
        # 단일 디코딩: bytes -> ndarray RGB, 미리보기는 얕은 래핑 후 copy(), 분석은 동일 ndarray 사용
        try:
            import numpy as np, cv2
            arr = np.frombuffer(data, dtype=np.uint8)
            bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if bgr is None:
                # 순수 OpenCV 경로만 사용: 환경변수 CAP_PURE_OPENCV=1 이면 폴백을 건너뛴다.
                try:
                    if str(os.getenv('CAP_PURE_OPENCV', '0')).strip().lower() in ('1','true','on'):
                        return
                except Exception:
                    return
                # 폴백: OpenCV 디코딩 실패 시 QImage.fromData로 직접 시도한다.
                try:
                    qi2 = QImage.fromData(data, "JPG")
                    if (qi2 is not None) and (not qi2.isNull()):
                        try: _log.info("[LV-DECODE] fallback qimage w=%s h=%s", qi2.width(), qi2.height())
                        except Exception: pass
                        try:
                            self.frameReady.emit(qi2)
                        except Exception:
                            try: self._on_qimage(qi2)
                            except Exception: pass
                        return
                except Exception:
                    pass
                return
            rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
            h_, w_, _ = rgb.shape
            with self._rgb_lock:
                self._rgb_latest = rgb
            qi = QImage(rgb.data, w_, h_, 3*w_, QImage.Format_RGB888).copy()
        except Exception:
            return
        try:
            self.frameReady.emit(qi)
        except Exception:
            try:
                self._on_qimage(qi)
            except Exception:
                pass

    def _ai_tick(self):
        try:
            if getattr(self, "_capturing", False) and not getattr(self, "_armed_for_auto", False):
                return
            if not hasattr(self, 'guide'):
                return
            rgb = None
            with self._rgb_lock:
                rgb = self._rgb_latest
            if rgb is None:
                return
            h_, w_, _ = getattr(rgb, 'shape', (0, 0, 0))
            if w_ <= 0 or h_ <= 0:
                return
            qimg = QImage(rgb.data, w_, h_, 3*w_, QImage.Format_RGB888)
            ts_ai = int(time.time() * 1000)
            try:
                if hasattr(self.guide, 'set_input_source'):
                    self.guide.set_input_source('sdk')
            except Exception:
                pass
            payload, badges, metrics = self.guide.update(
                qimg,
                self.get_ratio(), ts_ai,
                getattr(self, 'face', None), getattr(self, 'pose', None)
            )
            try:
                if hasattr(self.overlay, 'update_landmarks'):
                    self.overlay.update_landmarks(payload, normalized=True)
            except Exception:
                pass
        except Exception:
            pass
