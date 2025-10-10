# -*- coding: utf-8 -*-
from __future__ import annotations
import os
os.add_dll_directory(r"C:\dev\photostudio")
os.environ.setdefault("CRSDK_DLL", r"C:\dev\photostudio\crsdk_pybridge.dll")

import time, threading
from pathlib import Path
from typing import Optional, Dict

from PySide6.QtCore import Qt, QTimer, QRect
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QApplication,
    QPushButton, QButtonGroup, QLabel
)
from PySide6.QtGui import QPixmap, QImage, QShortcut, QKeySequence

from app.ui.base_page import BasePage
from app.constants import STEPS

# CameraControl은 선택적(없어도 동작)
try:
    from app.utils.control_camera import CameraControl  # 호환 별칭(없어도 무방)
except Exception:
    CameraControl = None  # noqa: N816

from app.ui.ai_overlay import AiOverlay
from app.utils.image_ops import render_transformed, render_placeholder
from app.ai.guidance import Guidance

# ── LiveViewService 우선, 없으면 폴백 구현 사용 ─────────────────────────────
try:
    from app.services.liveview import LiveViewService  # 권장 경로
except Exception:
    LiveViewService = None  # type: ignore
    # 폴백: CRSDK DLL을 직접 당겨서 QImage 콜백을 주는 간단 드라이버
    import ctypes as C, os, numpy as np, cv2

    _DLL = os.environ.get("CRSDK_DLL", r"C:\dev\photostudio\crsdk_pybridge.dll")
    _d = C.CDLL(_DLL)
    _d.crsdk_init.restype = C.c_int
    _d.crsdk_release.restype = None
    _d.crsdk_connect_first.argtypes  = [C.POINTER(C.c_void_p)]
    _d.crsdk_connect_first.restype   = C.c_int
    _d.crsdk_connect_usb_serial.argtypes = [C.c_char_p, C.POINTER(C.c_void_p)]
    _d.crsdk_connect_usb_serial.restype  = C.c_int
    _d.crsdk_disconnect.argtypes = [C.c_void_p]; _d.crsdk_disconnect.restype = None
    _d.crsdk_enable_liveview.argtypes = [C.c_void_p, C.c_int]
    _d.crsdk_enable_liveview.restype  = C.c_int
    _d.crsdk_get_lv_info.argtypes     = [C.c_void_p, C.POINTER(C.c_uint)]
    _d.crsdk_get_lv_info.restype      = C.c_int
    _d.crsdk_get_lv_image.argtypes    = [C.c_void_p, C.c_void_p, C.c_uint, C.POINTER(C.c_uint)]
    _d.crsdk_get_lv_image.restype     = C.c_int

    class _InlineLiveView:
        """LiveViewService가 없을 때만 사용하는 최소 폴백."""
        def __init__(self, owner):
            self.owner = owner
            self.mode = 'off'
            self.cam = None           # shoot_one이 없을 수 있음(캡처는 기존 경로 사용)
            self._ms_sdk = 33
            self._stop = threading.Event()
            self._th: Optional[threading.Thread] = None
            self._h = C.c_void_p()

        def configure(self, _lv_dir: str, ms_sdk: int, _ms_file: int, fallback_ms: int = 3000):
            try: self._ms_sdk = max(16, int(ms_sdk))
            except Exception: self._ms_sdk = 33

        def start(self, on_qimage) -> bool:
            if _d.crsdk_init() != 0:
                return False
            rc = _d.crsdk_connect_first(C.byref(self._h))
            if rc != 0 or not self._h.value:
                _d.crsdk_release(); return False
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
                                h, w, _ = rgb.shape
                                qi = QImage(rgb.data, w, h, 3*w, QImage.Format_RGB888).copy()
                                on_qimage(qi)
                    except Exception:
                        pass
                    time.sleep(self._ms_sdk/1000.0)
            self._th = threading.Thread(target=_run, daemon=True)
            self._th.start()
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

# ── 라이브뷰/프레임 주기 디폴트 ─────────────────────────────────
LV_DEFAULT_DIR = r"C:\PhotoBox\lv"
LV_DEFAULT_MS_SDK  = 33
LV_DEFAULT_MS_FILE = 48
PLACEHOLDER_DEFAULT = r"app\assets\placeholder.png"

# ── 고정 저장 경로/순서 ──────────────────────────────────────
CAP_DIR = Path(r"C:\PhotoBox\captures")
CAP_SEQ = ["01.jpg","02.jpg","03.jpg","04.jpg"]

# ── FHD 하드 토큰 ────────────────────────────────────────────
TH_COUNT = 4; TH_GAP = 36; TH_H = 216; TH_W_3040 = 162; TH_W_3545 = 168
P_GAP = 36; PREV_H = 1008; PREV_W_3040 = 756; PREV_W_3545 = 784
P2_GAP = 30; CTRL_H = 45; BTN_R = 12; LED_D = 12; CTRL_GAP = 21


class CapturePage(BasePage):
    """촬영 페이지(썸네일 스트립 + 라이브뷰 + 컨트롤 바)."""
    def __init__(self, theme, session: dict, parent=None):
        super().__init__(theme, steps=STEPS, active_index=2, parent=parent)
        self.session = session; self.session.setdefault("guide_skip", True)

        center = QWidget(self)
        layout = QVBoxLayout(center); layout.setContentsMargins(0,0,0,0); layout.setSpacing(0)

        # ── 썸네일 스트립 ──
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

        # 간격
        self._gap36 = QWidget(self); self._gap36.setFixedHeight(0); layout.addWidget(self._gap36, 0)

        # ── 프리뷰 ──
        self.preview_box = QFrame(self); self.preview_box.setObjectName("PreviewBox")
        self.preview_box.setStyleSheet(f"QFrame#PreviewBox {{ background: transparent; border: {self._normal_px()}px solid {self._primary_hex()}; border-radius: 0px; }}")
        layout.addWidget(self.preview_box, 0, Qt.AlignHCenter)
        self.preview_label = QLabel(self.preview_box)
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setAttribute(Qt.WA_TranslucentBackground, False)
        self.preview_label.setStyleSheet("background: #808080; padding:0; margin:0; border:none;")

        self._gap36b = QWidget(self); self._gap36b.setFixedHeight(0); layout.addWidget(self._gap36b, 0)

        # ── 컨트롤 바 ──
        self.ctrl = QWidget(self)
        hb = QHBoxLayout(self.ctrl); hb.setContentsMargins(0,0,0,0); hb.setSpacing(0); hb.setAlignment(Qt.AlignHCenter)

        self.cam_led = QLabel(self.ctrl); self.cam_led.setObjectName("CamLED")
        hb.addWidget(self.cam_led, 0)

        self.delay3 = QPushButton("3초", self.ctrl); self.delay3.setObjectName("Delay3"); self.delay3.setCheckable(True)
        self.delay5 = QPushButton("5초", self.ctrl); self.delay5.setObjectName("Delay5"); self.delay5.setCheckable(True)
        self.delay7 = QPushButton("7초", self.ctrl); self.delay7.setObjectName("Delay7"); self.delay7.setCheckable(True)
        self.delay_group = QButtonGroup(self)
        for i, b in ((3,self.delay3),(5,self.delay5),(7,self.delay7)): self.delay_group.addButton(b, i); hb.addWidget(b, 0)
        self.delay_group.setExclusive(True); self.delay3.setChecked(True)
        self.delay_group.idClicked.connect(self._on_delay_changed)

        self.btn_capture = QPushButton("촬영", self.ctrl); self.btn_capture.setObjectName("BtnCapture")
        self.btn_retake  = QPushButton("재촬영", self.ctrl); self.btn_retake.setObjectName("BtnRetake")
        self.btn_capture.clicked.connect(self._on_capture_clicked)
        self.btn_retake.clicked.connect(self._on_retake_clicked)
        hb.addWidget(self.btn_capture, 0); hb.addWidget(self.btn_retake, 0)
        layout.addWidget(self.ctrl, 0, Qt.AlignHCenter)
        layout.addStretch(1)

        # 런타임 상태
        self._cam: CameraControl | None = None
        self._settings_cache = {}; self._refresh_settings_tokens()
        self._count_timer = QTimer(self); self._count_timer.setInterval(1000)
        self._count_timer.timeout.connect(self._tick_countdown)
        self._count_left = 0; self._capturing = False
        self._cam: CameraControl | None = None
        self._settings_cache = {}; self._refresh_settings_tokens()
        self._count_timer = QTimer(self); self._count_timer.setInterval(1000)
        self._count_timer.timeout.connect(self._tick_countdown)
        self._count_left = 0; self._capturing = False

        # LiveView signals
        self._lv_status_hooked = False   # statusChanged 연결 여부

        self._rebuild_layout_tokens(); self._apply_layout_tokens()

        try:
            bus = QApplication.instance().property("settings_bus")
            if hasattr(bus, "changed"): bus.changed.connect(self._on_settings_changed)
        except Exception: pass

        self.setCentralWidget(center, margin=(0,0,0,0), spacing=0, center=False, max_width=None)
        self.set_prev_mode("enabled"); self.set_next_mode("disabled"); self.set_next_enabled(False)

        self._read_ratio()
        self.overlay = AiOverlay(self)
        try: self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        except Exception: pass
        try:
            if hasattr(self.overlay, "bind_session"): self.overlay.bind_session(self.session)
        except Exception: pass
        self.overlay.setGeometry(self.rect()); self.overlay.hide(); self.overlay.lower()

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
        self._bind_shortcuts()
        # LiveViewService 인스턴스(없으면 폴백)
        self.lv = LiveViewService(self) if LiveViewService else _InlineLiveView(self)  # type: ignore[name-defined]
    
    def _bind_shortcuts(self):
        """F1=AF, F2=AWB, F3=촬영"""
        # 포커스 이슈 없이 페이지 내에서 동작
        self.setFocusPolicy(Qt.StrongFocus)

        self._sc_af  = QShortcut(QKeySequence(Qt.Key_F1), self)
        self._sc_awb = QShortcut(QKeySequence(Qt.Key_F2), self)
        self._sc_sh  = QShortcut(QKeySequence(Qt.Key_F3), self)

        ctx = Qt.WidgetWithChildrenShortcut
        self._sc_af.setContext(ctx);  self._sc_awb.setContext(ctx);  self._sc_sh.setContext(ctx)

        self._sc_af.activated.connect(self._do_af)
        self._sc_awb.activated.connect(self._do_awb)
        self._sc_sh.activated.connect(self._do_shoot)

    def _do_af(self):
        cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None)
        if cam and hasattr(cam, 'one_shot_af'):
            threading.Thread(target=lambda: cam.one_shot_af(), daemon=True).start()

    def _do_awb(self):
        cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None)
        if cam and hasattr(cam, 'one_shot_awb'):
            threading.Thread(target=lambda: cam.one_shot_awb(), daemon=True).start()

    def _do_shoot(self):
        """지연 없이 바로 1장 촬영"""
        if self._capturing:
            return
        self._clear_captures()
        self._lock_ui_for_capture(True)
        self._overlay_show_during_capture()
        # 카운트다운 없이 즉시 촬영
        QTimer.singleShot(0, self._invoke_shoot)

    
    # ──────────────────────────────────────────────────────────
    def showEvent(self, e):
        super().showEvent(e)
        self.set_prev_mode("enabled"); self.set_next_mode("disabled"); self.set_next_enabled(False)
        self._read_ratio()
        self._rebuild_layout_tokens(); self._apply_layout_tokens(); self._apply_ctrl_styles()
        self._show_placeholder()

        self._ensure_camera_started()
        self._refresh_led()

        try:
            if self.face: self.face.start()
        except Exception: pass
        try:
            if self.pose: self.pose.start()
        except Exception: pass

        try:
            self.overlay.setGeometry(self.rect())
            self.overlay.hide(); self.overlay.lower()
            #self.preview_box.raise_(); self.preview_label.raise_()
        except Exception: pass

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        try:
            if hasattr(self, "overlay"):
                self.overlay.setGeometry(self.rect())
                self._overlay_update_hole()
                if getattr(self, "_capturing", False):
                    self.overlay.show(); self.overlay.raise_()   # 캡처 중엔 오버레이를 위로
                else:
                    self.overlay.hide(); self.overlay.lower()    # 평소엔 숨김
        except Exception:
            pass
        try:
            self._sync_preview_label_geom()
        except Exception:
            pass


    def keyPressEvent(self, e):
        k = e.key()
        cam = getattr(self.lv, 'cam', None)

        if k == Qt.Key_F1 and cam:
            cam.one_shot_af()
            return
        if k == Qt.Key_F2 and cam:
            cam.one_shot_awb()
            return
        if k == Qt.Key_F3 and cam:
            # 촬영 + 최신 파일 다운로드 경로 획득
            if cam.shoot_one():
                p = cam.download_latest()
                if p:
                    print(f"[SHOT] saved -> {p}")
            return

        if k == Qt.Key_Left:
            self.go_prev.emit(); return
        if k == Qt.Key_Right and self.footer.nextBtn.isEnabled():
            self.go_next.emit(); return
        super().keyPressEvent(e)


        

    # ── ratio helpers ─────────────────────────────────────────
    def _read_ratio(self):
        r = str(self.session.get("ratio", "3040")).strip()
        if r not in ("3040","3545"): r = "3040"
        self._ratio = r

    def get_ratio(self) -> str: return getattr(self, "_ratio", "3040")
    def ratio_tuple(self) -> tuple[int, int]: return (3,4) if self.get_ratio()=="3040" else (7,9)

    # ── helpers: theme/size ───────────────────────────────────
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

    # ── 티어 스케일: 토큰 리빌드/적용 ─────────────────────────
    @staticmethod
    def _snap3(v: float) -> int:
        try:
            n = int(float(v)); return n - (n % 3)
        except Exception:
            return

    # ── handlers: delay buttons ───────────────────────────────
    def _on_delay_changed(self, delay_id: int):
        try: v = int(delay_id)
        except Exception: v = 3
        if v not in (3,5,7): v = 3
        self.session["delay_sec"] = v
        try:
            btn = self.delay_group.button(v)
            if btn and not btn.isChecked(): btn.setChecked(True)
        except Exception: pass

    # ── 촬영 트리거/카운트다운 ───────────────────────────────
    def _on_capture_clicked(self):
        if self._capturing: return
        v = int(self.session.get("delay_sec", 3) or 3)
        if v not in (3,5,7): v = 3
        self.session["delay_sec"] = v
        self._clear_captures()
        self._lock_ui_for_capture(True)
        self._overlay_show_during_capture()
        self._start_countdown(v)

    def _on_retake_clicked(self):
        if getattr(self, "_count_timer", None) and self._count_timer.isActive(): self._count_timer.stop()
        self._count_left = 0; self._capturing = False
        self.btn_capture.setEnabled(True)
        for b in (self.delay3, self.delay5, self.delay7): b.setEnabled(True)
        self._overlay_hide()
        self.set_next_enabled(False); self.set_next_mode("disabled")
        self.set_prev_mode("enabled"); self.set_prev_enabled(True)
        self._shot_index = 0; self._clear_captures()

    def _lock_ui_for_capture(self, on: bool):
        self._capturing = bool(on)
        self.set_prev_mode("disabled"); self.set_prev_enabled(False)
        self.set_next_mode("disabled"); self.set_next_enabled(False)
        for b in (self.delay3, self.delay5, self.delay7):
            try: b.setEnabled(not on)
            except Exception: pass
        try: self.btn_capture.setEnabled(not on)
        except Exception: pass

    def _start_countdown(self, sec: int):
        self._count_left = int(sec); self._count_timer.start()

    def _tick_countdown(self):
        self._count_left -= 1
        if self._count_left > 0: return
        self._count_timer.stop(); self._invoke_shoot()

    def _invoke_shoot(self):
        def _work():
            ok = False; path = None; err = ""
            try:
                cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None)
                if cam and hasattr(cam, "shoot_one"):
                    res = cam.shoot_one()
                    if isinstance(res, dict):
                        ok = bool(res.get("ok", False)); path = res.get("path") or res.get("file")
                    elif isinstance(res, (list, tuple)):
                        ok = bool(res[0]); path = (res[1] if len(res)>1 else None)
                    elif isinstance(res, bool): ok = res
                    elif isinstance(res, int):  ok = (res == 0)
                else:
                    err = "camera not ready"
            except Exception as e:
                err = str(e)
            def _done(): self._on_shoot_done(ok, path, err)
            QTimer.singleShot(0, _done)
        threading.Thread(target=_work, daemon=True).start()

    def _on_shoot_done(self, ok: bool, path: Optional[str], err: str=""):
        if ok:
            try: self._stop_camera()
            except Exception: pass
            thumb_path = self._save_preview_thumbnail()
            try:
                self.session.setdefault("shot_paths", [])
                self.session.setdefault("shot_thumbs", [])
                if path: self.session["shot_paths"].append(path)
                if thumb_path: self.session["shot_thumbs"].append(thumb_path)
            except Exception: pass
            self.end_capture(True)
        else:
            try:
                if hasattr(self, "overlay") and hasattr(self.overlay, "update_badges"):
                    msg = f"촬영 실패: {err or ''}"
                    self.overlay.update_badges(msg, {})
            except Exception: pass
            self._overlay_hide()
            self.btn_capture.setText("재시도"); self.btn_capture.setEnabled(True)
            for b in (self.delay3, self.delay5, self.delay7): b.setEnabled(True)
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

    # ── 컨트롤바 스타일/크기 적용 ─────────────────────────────
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
        # LED를 확실히 원형으로 고정
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

    # ── 프리뷰 크기/배치 ──────────────────────────────────────
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

    # ── SETTINGS 토큰 ─────────────────────────────────────────
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
        try: self.lv.configure(self._tok_lv_dir(), self._tok_ms_sdk(), self._tok_ms_file())
        except Exception: pass

    # ── LiveView 시작/수신 콜백/정지 ──────────────────────────
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

    def _ensure_camera_started(self):
        # 설정 적용
        try:
            self.lv.configure(self._tok_lv_dir(), self._tok_ms_sdk(), self._tok_ms_file(), fallback_ms=3000)
        except Exception:
            pass

        # statusChanged는 1회만
        try:
            if hasattr(self.lv, "statusChanged") and not self._lv_status_hooked:
                self.lv.statusChanged.connect(self._on_lv_status)
                self._lv_status_hooked = True
        except Exception:
            pass

        # 시작: 프레임은 서비스가 frameReady→on_qimage로 직접 연결
        try:
            self.lv.start(on_qimage=self._on_qimage)
            self.set_led_mode(getattr(self.lv, 'mode', 'off'))
            self._cam = getattr(self.lv, 'cam', None)
        except Exception:
            self.set_led_mode('off')


    def _on_qimage(self, img: QImage):
        print(f"[CAPTURE] img={img.width()}x{img.height()} label={self.preview_label.width()}x{self.preview_label.height()}")
        print(f"[CAPTURE] img={img.width()}x{img.height()} label={self.preview_label.width()}x{self.preview_label.height()} mode={getattr(self.lv,'mode','off')}")
        try:
            w, h = self.preview_label.width(), self.preview_label.height()
            mode = getattr(self.lv, 'mode', 'off')

            # 1) 기존 변환
            try:
                pix = render_placeholder(img, w, h) if mode == 'file' else render_transformed(img, w, h)
            except Exception:
                pix = QPixmap()

            # 2) 폴백(직접 스케일)
            if pix.isNull():
                pix = QPixmap.fromImage(img).scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)

            if not pix.isNull():
                self.preview_label.setPixmap(pix)
                if not getattr(self, "_dbg_shown", False):
                    print(f"[CAPTURE] label={w}x{h} img={img.width()}x{img.height()}")
                    self._dbg_shown = True
            else:
                print(f"[CAPTURE] qimage invalid? {img.width()}x{img.height()}")

            # 오버레이/LED 유지
            if getattr(self, "_capturing", False) and hasattr(self, 'guide'):
                ts = int(time.time() * 1000)
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
                        self.overlay.update_badges(badges.get('primary',''), metrics)
                except Exception: pass
                try: self.overlay.show(); self.overlay.raise_()
                except Exception: pass
            else:
                try: self.overlay.hide(); self.overlay.lower()
                except Exception: pass

            self.set_led_mode(mode)
        except Exception:
            pass



    def _stop_camera(self):
        # statusChanged만 해제
        try:
            if self._lv_status_hooked and hasattr(self.lv, "statusChanged"):
                try:
                    self.lv.statusChanged.disconnect(self._on_lv_status)
                except Exception:
                    pass
                self._lv_status_hooked = False
        except Exception:
            pass
        try:
            if hasattr(self, 'lv') and self.lv:
                self.lv.stop()
        except Exception:
            pass
        self.set_led_mode('off')
        self._show_placeholder()


    def on_before_prev(self, session): self._stop_camera(); return True
    def on_before_next(self, session): self._stop_camera(); return True

    # ── overlay helpers ───────────────────────────────────────
    def _overlay_update_hole(self):
        try:
            if not getattr(self, "overlay", None): return
            target = self.preview_label
            if hasattr(self.overlay, "bind_hole_widget"):
                self.overlay.bind_hole_widget(target, shrink_px=3)
            elif hasattr(self.overlay, "set_hole_widget"):
                self.overlay.set_hole_widget(target)
            elif hasattr(self.overlay, "set_hole"):
                r = target.geometry()
                tl = target.mapTo(self, r.topLeft()); br = target.mapTo(self, r.bottomRight())
                self.overlay.set_hole(QRect(tl, br))
        except Exception: pass

    def _overlay_show_during_capture(self):
        self._capturing = True
        try:
            # 색·입력제어는 기존대로
            self.overlay.setGeometry(self.rect())
            self._overlay_update_hole()
            self.overlay.show()
            self.overlay.raise_()
        except Exception:
            pass

        print("OV show", self.overlay.isVisible(), self.overlay.geometry())

    def _overlay_hide(self):
        try:
            self._capturing = False
            if not hasattr(self, "overlay") or self.overlay is None: return
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
        print(f"[CAPTURE] end: success={success}")

    def _sync_preview_label_geom(self):
        try:
            r = self.preview_box.contentsRect()
            lw = self.preview_label.width(); lh = self.preview_label.height()
            x = r.x() + max(0, (r.width() - lw) // 2)
            y = r.y() + max(0, (r.height() - lh) // 2)
            self.preview_label.setGeometry(x, y, lw, lh)
        except Exception: pass

    # ── LED helpers ───────────────────────────────────────────
    def _refresh_led(self):
        try:
            d = int(getattr(self, "_T", {}).get("LED_D", LED_D))
            mode = getattr(self, "_lv_mode", 'off')
            col = "#4CAF50" if mode=='sdk' else ("#FFC107" if mode=='file' else "#f44336")
            # 크기 고정(레이아웃이 늘려도 유지)
            self.cam_led.setFixedSize(d, d)
            self.cam_led.setStyleSheet(f"QLabel#CamLED {{ border-radius:{d//2}px; background:{col}; }}")
        except Exception: pass

    def set_camera_connected(self, on: bool):
        self._lv_mode = 'sdk' if on else 'off'; self._refresh_led()

    def set_led_mode(self, mode: str):
        self._lv_mode = mode if mode in ('sdk','file','off') else 'off'; self._refresh_led()

    # ── 촬영 보조/버스트/AF/AWB ──────────────────────────────
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

    def _is_ready(self, metrics: Dict[str, float]) -> bool:
        return metrics.get('has_face', 0.0) >= 0.5 and metrics.get('has_pose', 0.0) >= 0.5

    def _do_one_shot_and_continue(self, initial: bool=False):
        def _work():
            cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None)
            ok = False; path = None; err = ''
            try:
                pm = self.preview_label.pixmap()
                if pm and not pm.isNull():
                    out_dir = Path.cwd() / 'captures'
                    out_dir.mkdir(parents=True, exist_ok=True)
                    idx = len(self.session.get('shot_thumbs', []))
                    p = Path(self._seq_path(idx))
                    pm.save(str(p), 'JPG', 90)
                    fname = CAP_SEQ[idx]
                    self.session.setdefault("captures", ["", "", "", ""])
                    self.session["captures"][idx] = fname
                    self.session.setdefault('shot_thumbs', []).append(str(p))
                    def _set_thumb_ui(path=str(p)): self._set_thumb_from_file(idx, path)
                    QTimer.singleShot(0, _set_thumb_ui)
            except Exception: pass
            try:
                if cam and hasattr(cam, 'one_shot_af'): cam.one_shot_af()
            except Exception: pass
            try:
                if cam and hasattr(cam, 'shoot_one'):
                    res = cam.shoot_one()
                    if isinstance(res, dict):
                        ok = bool(res.get('ok', False)); path = res.get('path') or res.get('file')
                    elif isinstance(res, (list, tuple)):
                        ok = bool(res[0]); path = (res[1] if len(res) > 1 else None)
                    elif isinstance(res, bool): ok = res
                    elif isinstance(res, int):  ok = (res == 0)
                    if path: self.session.setdefault('shot_paths', []).append(path)
                else:
                    err = 'camera not ready'
            except Exception as e:
                err = str(e)
            def _done():
                if not ok:
                    try:
                        if hasattr(self, 'overlay') and hasattr(self.overlay, 'update_badges'):
                            self.overlay.update_badges(f"촬영 실패: {err}", {})
                    except Exception: pass
                self._on_shoot_done(ok, path, err)
                try: self.btn_capture.setText('촬영')
                except Exception: pass
            QTimer.singleShot(0, _done)
        threading.Thread(target=_work, daemon=True).start()

    def _on_lv_status(self, mode: str):
        self.set_led_mode(mode)
        if mode == 'sdk':
            try:
                cam = getattr(self.lv, 'cam', None)
                if cam:
                    # 카드는 계속 저장 + PC로 프록시 복사
                    cam.set_save_and_proxy(True, True)
                    # PC 저장 폴더
                    cam.set_download_dir(r"C:\PhotoBox\raw")
                    # 필요하면 AF/AWB 한 번 준비
                    cam.one_shot_af()
            except Exception:
                pass


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
            for i in range(len(getattr(self, '_thumb_imgs', []))):
                try: self._thumb_imgs[i].clear()
                except Exception: pass
        except Exception:
            pass
