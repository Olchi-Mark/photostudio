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
from PySide6.QtGui import QPixmap, QImage, QFont

from app.ui.base_page import BasePage
from app.constants import STEPS
from app.ui.ai_overlay import AiOverlay
from app.utils.image_ops import render_transformed, render_placeholder
from app.ai.guidance import Guidance

# DLL 경로(필요 시)
os.add_dll_directory(r"C:\dev\photostudio")
os.environ.setdefault("CRSDK_DLL", r"C:\dev\photostudio\crsdk_pybridge.dll")

# 로거: 캡처 페이지용 로거
_log = logging.getLogger("CAP")

# CameraControl은 선택적
try:
    from app.utils.control_camera import CameraControl
except Exception:
    CameraControl = None  # noqa: N816

# ── LiveViewService 우선, 없으면 폴백 구현 사용 ─────────────────────────────
try:
    from app.services.liveview import LiveViewService  # 권장 경로(내부에서 on_qimage 콜백 호출)
except Exception:
    LiveViewService = None  # type: ignore
    # 폴백: CRSDK DLL을 직접 당겨서 QImage 콜백을 주는 간단 드라이버
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
        """LiveViewService가 없을 때만 사용하는 최소 폴백."""
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


# ── 기본 토큰 ───────────────────────────────────────────────────────────────
LV_DEFAULT_DIR = r"C:\PhotoBox\lv"
LV_DEFAULT_MS_SDK  = 33
LV_DEFAULT_MS_FILE = 48
PLACEHOLDER_DEFAULT = r"app\assets\placeholder.png"

CAP_DIR = Path(r"C:\PhotoBox\captures")
CAP_SEQ = ["01.jpg","02.jpg","03.jpg","04.jpg"]

TH_COUNT = 4; TH_GAP = 36; TH_H = 216; TH_W_3040 = 162; TH_W_3545 = 168
P_GAP = 36; PREV_H = 1008; PREV_W_3040 = 756; PREV_W_3545 = 784
P2_GAP = 30; CTRL_H = 45; BTN_R = 12; LED_D = 12; CTRL_GAP = 21


# ── 간단 Busy/Toast 오버레이 ────────────────────────────────────────────────
class BusyOverlay(QWidget):
    def __init__(self, parent: QWidget, text="카메라 연결중"):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.setAttribute(Qt.WA_NoSystemBackground, True)
        self.setStyleSheet("background: rgba(0,0,0,128);")
        self.msg = QLabel(text, self)
        self.msg.setStyleSheet("color:white;")
        f = QFont()
        f.setPointSize(16); f.setBold(True)
        self.msg.setFont(f)
        self.msg.setAlignment(Qt.AlignCenter)
        self._dots = 0
        self._timer = QTimer(self); self._timer.setInterval(450); self._timer.timeout.connect(self._tick)
    def showEvent(self, _):
        self.resize(self.parentWidget().size()); self.msg.setGeometry(0,0,self.width(),self.height())
        self._dots = 0; self._timer.start()
    def hideEvent(self, _): self._timer.stop()
    def setText(self, t:str): self.msg.setText(t)
    def _tick(self):
        self._dots = (self._dots + 1) % 4
        base = self.msg.text().split('…')[0].rstrip('.').rstrip()
        self.msg.setText(f"{base}…" + "."*self._dots)

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


# ── CapturePage ─────────────────────────────────────────────────────────────
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
        # 3/5/7초 버튼은 비활성/비표시 처리
        try:
            self.delay_group.idClicked.disconnect(self._on_delay_changed)
        except Exception:
            pass
        for b in (self.delay3, self.delay5, self.delay7):
            try:
                b.setEnabled(False)
                b.setVisible(False)
            except Exception:
                pass

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
        # 자동 연사 제어 상태
        self._seq_running = False
        self._seq_index = -1
        self._ready_since = None
        self._seq_timer = QTimer(self); self._seq_timer.setInterval(1000)
        self._seq_timer.timeout.connect(self._tick_seq_countdown)
        self._seq_count_left = 0

        self._lv_status_hooked = False   # statusChanged 연결 플래그
        self._connecting = False         # 연결 진행 중 플래그

        self._rebuild_layout_tokens(); self._apply_layout_tokens()

        # 설정 버스
        try:
            bus = QApplication.instance().property("settings_bus")
            if hasattr(bus, "changed"): bus.changed.connect(self._on_settings_changed)
        except Exception: pass

        self.setCentralWidget(center, margin=(0,0,0,0), spacing=0, center=False, max_width=None)
        self.set_prev_mode("enabled"); self.set_next_mode("disabled"); self.set_next_enabled(False)

        self._read_ratio()

        # 오버레이들
        self.overlay = AiOverlay(self)
        try: self.overlay.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        except Exception: pass
        try:
            if hasattr(self.overlay, "bind_session"): self.overlay.bind_session(self.session)
        except Exception: pass
        self.overlay.setGeometry(self.rect()); self.overlay.hide(); self.overlay.lower()

        self.busy = BusyOverlay(self, "카메라 연결중")
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

        # LiveViewService 인스턴스(없으면 폴백)
        self.lv = LiveViewService(self) if LiveViewService else _InlineLiveView(self)  # type: ignore[name-defined]
        self._first_frame_seen = False
        self._conn_timer = QTimer(self); self._conn_timer.setInterval(400)
        self._conn_timer.timeout.connect(self._conn_tick)


    # ──────────────────────────────────────────────────────────
    def showEvent(self, e):
        super().showEvent(e)
        self.set_prev_mode("enabled"); self.set_next_mode("disabled"); self.set_next_enabled(False)
        self._read_ratio()
        self._rebuild_layout_tokens(); self._apply_layout_tokens(); self._apply_ctrl_styles()
        self._show_placeholder()
        # 비동기 연결 시작(UI 먼저 표시)
        QTimer.singleShot(0, self._connect_camera_async)

        try:
            if self.face: self.face.start()
        except Exception: pass
        try:
            if self.pose: self.pose.start()
        except Exception: pass

        self._first_frame_seen = False
        self._conn_phase = 0               # 0: 연결중, 1: 지연중
        self._conn_started = time.time()
        self._show_connect_overlay("카메라 연결중")
        self._conn_timer.start()


        try:
            self.overlay.setGeometry(self.rect())
            self.overlay.hide(); self.overlay.lower()
            self.preview_box.raise_(); self.preview_label.raise_()
        except Exception: pass

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        try:
            if hasattr(self, "overlay"):
                self.overlay.setGeometry(self.rect())
                self._overlay_update_hole()
                if getattr(self, "_capturing", False):
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
        # 촬영 단축키
        if k == Qt.Key_F1:  # AF
            self._cmd_one_shot_af(); return
        if k == Qt.Key_F2:  # AWB
            self._cmd_one_shot_awb(); return
        if k == Qt.Key_F3:  # SHOT
            self._cmd_shoot_one(); return
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
        self._clear_captures()
        self._lock_ui_for_capture(True)
        self._overlay_show_during_capture()
        self._start_countdown(5)

    def _on_retake_clicked(self):
        if getattr(self, "_count_timer", None) and self._count_timer.isActive(): self._count_timer.stop()
        self._count_left = 0; self._capturing = False
        self.btn_capture.setEnabled(True)
        for b in (self.delay3, self.delay5, self.delay7):
            try: b.setEnabled(False)
            except Exception: pass
        self._overlay_hide()
        self.set_next_enabled(False); self.set_next_mode("disabled")
        self.set_prev_mode("enabled"); self.set_prev_enabled(True)
        self._shot_index = 0; self._clear_captures()
        # 자동 연사 상태 리셋
        self._seq_running = False; self._seq_index = -1; self._ready_since = None
        if self._seq_timer.isActive(): self._seq_timer.stop()

    def _lock_ui_for_capture(self, on: bool):
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
        if self._count_left > 0: return
        self._count_timer.stop(); self._invoke_shoot(i=0)

    # 자동 연사용 1초 tick: 이후 샷들 3초 간격, 각 1초 전 AF
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
        # 기존 캡처 파이프라인 유지
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
                    # LiveViewService가 직접 제공하는 경우
                    if hasattr(self.lv, "shoot_one"):
                        rc = self.lv.shoot_one()  # 0 == OK
                        ok = (rc == 0)
                    else:
                        err = "shoot api not available"
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
            # 각 샷 완료 후 프리뷰 스냅샷을 지정 경로/파일명으로 저장
            thumb_path = self._save_preview_snapshot_indexed(int(idx) if idx is not None else 0)
            if not thumb_path:
                thumb_path = self._save_preview_thumbnail()
            # 실제 촬영 파일을 지정 경로로 이동/리네임
            try:
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
                # captures/raw_captures 인덱스 갱신
                eff_i = move_idx
                arr_cap = self.session.setdefault('captures', ["", "", "", ""])
                arr_raw = self.session.setdefault('raw_captures', ["", "", "", ""])
                if 0 <= eff_i < len(arr_cap):
                    if thumb_path: arr_cap[eff_i] = thumb_path
                if 0 <= eff_i < len(arr_raw):
                    if path: arr_raw[eff_i] = path
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
                    msg = f"촬영 실패: {err or ''}"
                    self.overlay.update_badges(msg, {})
            except Exception: pass
            self._overlay_hide()
            self.btn_capture.setText("재시도"); self.btn_capture.setEnabled(True)
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

    # 프리뷰 스냅샷을 인덱스 파일명으로 저장한다.
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

    # 촬영된 실제 파일을 C:\PhotoBox\raw\raw_{i+1:02d}.jpg 로 이동/리네임한다.
    def _move_capture_to_raw(self, idx: int, src_path: str) -> Optional[str]:
        try:
            src = Path(src_path)
            if not src.exists() or not src.is_file():
                return None
            raw_dir = Path(r"C:\PhotoBox\raw")
            raw_dir.mkdir(parents=True, exist_ok=True)
            dest = raw_dir / f"raw_{int(idx)+1:02d}.jpg"
            # 동일 경로면 스킵
            try:
                if src.resolve() == dest.resolve():
                    return str(dest)
            except Exception:
                pass
            # 기존 파일이 있으면 삭제 후 이동
            try:
                if dest.exists():
                    dest.unlink()
            except Exception:
                pass
            try:
                src.rename(dest)
            except Exception:
                # 다른 드라이브 이동 등 실패 시 복사 후 삭제 시도
                import shutil
                shutil.copy2(str(src), str(dest))
                try: src.unlink()
                except Exception: pass
            return str(dest)
        except Exception:
            return None

    # SDK에서 최신 저장 파일을 조회한다. 실패 시 None 반환.
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

    # 폴더 감시 폴링으로 신규 JPEG 파일을 찾는다.
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
        # LED 원형 + 고정크기
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

    # ── LiveView 시작/정지(비동기 연결) ─────────────────────────
    def _connect_camera_async(self):
        if self._connecting: return
        self._connecting = True
        self.busy.setText("카메라 연결중"); self.busy.show(); self.busy.raise_()
        self.set_led_mode('off')

        # statusChanged 1회만
        try:
            if hasattr(self.lv, "statusChanged") and not self._lv_status_hooked:
                try: self.lv.statusChanged.disconnect(self._on_lv_status)
                except Exception: pass
                self.lv.statusChanged.connect(self._on_lv_status)
                self._lv_status_hooked = True
        except Exception: pass

        # 구성값 적용
        try:
            self.lv.configure(self._tok_lv_dir(), self._tok_ms_sdk(), self._tok_ms_file(), fallback_ms=3000)
        except Exception: pass

        # 워커 스레드로 start (최대 12초 감시)
        def _work():
            ok = False
            try:
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
                    self.busy.setText("카메라 연결 실패")
                    QTimer.singleShot(1300, self.busy.hide)
            QTimer.singleShot(0, _done)
        threading.Thread(target=_work, daemon=True).start()

        # 타임아웃 감시(12초)
        def _guard():
            if self._connecting:
                self._connecting = False
                try: self.lv.stop()
                except Exception: pass
                self.set_led_mode('off')
                self.busy.setText("카메라 연결 지연")
                QTimer.singleShot(1300, self.busy.hide)
        QTimer.singleShot(12000, _guard)

    def _on_qimage(self, img: QImage):
        if not self._first_frame_seen:
            self._first_frame_seen = True
            self._conn_timer.stop()
            self._hide_connect_overlay()

        try:
            w, h = self.preview_label.width(), self.preview_label.height()
            mode = getattr(self.lv, 'mode', 'off')

            # 1) 회전/미러 변환 후 가로 맞춤, 아래 크롭
            pix = QPixmap()
            try:
                pix = render_placeholder(img, w, h) if mode == 'file' else render_transformed(img, w, h)
            except Exception:
                pix = QPixmap()
            # 2) 폴백: 직접 스케일
            if pix.isNull():
                try:
                    pix = QPixmap.fromImage(img).scaled(w, h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                except Exception:
                    pix = QPixmap()

            if not pix.isNull():
                self.preview_label.setPixmap(pix)
            # 자동 연사 조건 확인(캡처 중 아닐 때도 가이던스 평가)
            try:
                if not getattr(self, "_capturing", False) and hasattr(self, 'guide'):
                    ts = int(time.time() * 1000)
                    _, _, _metrics0 = self.guide.update(
                        pix.toImage() if isinstance(pix, QPixmap) else img,
                        self.get_ratio(), ts,
                        getattr(self, 'face', None), getattr(self, 'pose', None)
                    )
                    try: self._check_auto_sequence(_metrics0)
                    except Exception: pass
            except Exception:
                pass

            # 가이던스/오버레이
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
    def _show_connect_overlay(self, text: str):
        try:
            if hasattr(self.overlay, "set_block_input"): self.overlay.set_block_input(False)
            if hasattr(self.overlay, "update_badges"): self.overlay.update_badges(text, {})
            self.overlay.setGeometry(self.rect()); self._overlay_update_hole()
            self.overlay.show(); self.overlay.raise_()
        except Exception: pass

    def _hide_connect_overlay(self):
        try:
            if hasattr(self.overlay, "update_badges"): self.overlay.update_badges("", {})
            self.overlay.hide(); self.overlay.lower()
        except Exception: pass
    def _stop_camera(self):
        # statusChanged만 해제
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
        if elapsed > 10 and self._conn_phase < 1:
            self._conn_phase = 1
            self._show_connect_overlay("카메라 연결 지연")
        elif elapsed > 20:
            self._show_connect_overlay("카메라 연결 실패. USB/전원을 확인하세요.")

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
        try:
            self._capturing = True
            if not getattr(self, "overlay", None): return
            if hasattr(self.overlay, "set_mask_color"):
                from PySide6.QtGui import QColor
                self.overlay.set_mask_color(QColor(0,0,0,128))
            if hasattr(self.overlay, "set_block_input"):
                self.overlay.set_block_input(True)
            self.overlay.setGeometry(self.rect())
            self._overlay_update_hole()
            self.overlay.show(); self.overlay.raise_()
        except Exception: pass

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
            self.cam_led.setFixedSize(d, d)
            self.cam_led.setStyleSheet(f"QLabel#CamLED {{ border-radius:{d//2}px; background:{col}; }}")
        except Exception: pass

    def set_camera_connected(self, on: bool):
        self._lv_mode = 'sdk' if on else 'off'; self._refresh_led()

    def set_led_mode(self, mode: str):
        self._lv_mode = mode if mode in ('sdk','file','off') else 'off'; self._refresh_led()

    # ── 단축키 명령(F1/F2/F3) ─────────────────────────────────
    def _cmd_one_shot_af(self):
        def _run():
            ok = False
            try:
                cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None) or self.lv
                if hasattr(cam, 'one_shot_af'):
                    rc = cam.one_shot_af(); ok = (rc == 0 or rc is True)
            except Exception: ok = False
            QTimer.singleShot(0, lambda: self.toast.popup("AF 완료" if ok else "AF 실패"))
        threading.Thread(target=_run, daemon=True).start()

    def _cmd_one_shot_awb(self):
        def _run():
            ok = False
            try:
                cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None) or self.lv
                if hasattr(cam, 'one_shot_awb'):
                    rc = cam.one_shot_awb(); ok = (rc == 0 or rc is True)
            except Exception: ok = False
            QTimer.singleShot(0, lambda: self.toast.popup("AWB 완료" if ok else "AWB 실패"))
        threading.Thread(target=_run, daemon=True).start()

    def _cmd_shoot_one(self):
        self.toast.popup("촬영…")
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
            QTimer.singleShot(0, lambda: self.toast.popup("촬영 성공" if ok else "촬영 실패"))
        threading.Thread(target=_run, daemon=True).start()

    # ── 썸네일/파일 관리 ──────────────────────────────────────
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

    # ── placeholder ──────────────────────────────────────────
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
        if mode == 'sdk':
            try: self._prep_af_awb()
            except Exception: pass

    # 가이던스 연속 만족 감지 및 자동 연사 시작
    def _check_auto_sequence(self, metrics: dict):
        """metrics.ready가 0.8초 연속 True면 자동 4연사를 시작한다."""
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
        """자동 4연사 시퀀스를 시작한다(첫샷 5초, 이후 3초 간격)."""
        if getattr(self, "_seq_running", False):
            return
        self._seq_running = True
        self._seq_index = -1
        self._clear_captures()
        self._lock_ui_for_capture(True)
        self._overlay_show_during_capture()
        # 첫 샷 카운트다운 시작
        try:
            _log.info("[SEQ] start first=5s")
        except Exception:
            pass
        self._count_left = 5
        if not self._count_timer.isActive():
            self._count_timer.start()

    def _try_af_async(self, idx: Optional[int] = None):
        """AF를 비동기로 1회 시도한다(로그: [AF] i=.. rc=..)."""
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

    # 가이던스 연속 만족 감지 및 자동 연사 시작
    def _check_auto_sequence(self, metrics: dict):
        """metrics.ready가 0.8초 연속 True면 자동 4연사를 시작한다."""
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
        """자동 4연사 시퀀스를 시작한다(첫샷 5초, 이후 3초 간격)."""
        if getattr(self, "_seq_running", False):
            return
        self._seq_running = True
        self._seq_index = -1
        self._clear_captures()
        self._lock_ui_for_capture(True)
        self._overlay_show_during_capture()
        # 첫 샷: 5초 카운트다운, T-3에 AF
        self._count_left = 5
        if not self._count_timer.isActive():
            self._count_timer.start()

    def _try_af_async(self):
        """AF를 비동기로 1회 시도한다."""
        def _run():
            try:
                cam = getattr(self.lv, 'cam', None) or getattr(self, '_cam', None) or self.lv
                if hasattr(cam, 'one_shot_af'):
                    try: cam.one_shot_af()
                    except Exception: pass
            except Exception:
                pass
        threading.Thread(target=_run, daemon=True).start()

    # ── 보조: 초기 AF/AWB ────────────────────────────────────
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
