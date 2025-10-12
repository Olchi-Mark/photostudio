# -*- coding: utf-8 -*-
# app/pages/print_view.py — Photoshop DoAction(비동기) + Neural(ENTER 타이머 즉시 시작)
# + TopMost 안전해제/복구 + 포커스강화 + 파일감시 + 진단로그/하트비트
from __future__ import annotations
from typing import Optional, List, Dict, Tuple
import os, sys, time, json, ctypes, atexit, traceback
from ctypes import wintypes
from datetime import datetime
from pathlib import Path
from PySide6.QtCore import Qt, QTimer, QElapsedTimer, QObject, Signal, QThread
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QApplication, QLabel,
    QGridLayout, QPushButton, QButtonGroup, QSizePolicy,
    QStyleOptionButton, QStyle
)
from PySide6.QtGui import QColor, QPainter, QPixmap, QPen
from app.ui.base_page import BasePage
import subprocess, threading
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0
#──────── 디렉토리/로그/상태 ────────
LOG_DIR   = r"C:\PhotoBox\logs"
LOG_FILE  = os.path.join(LOG_DIR, "print_view.log")
HB_FILE   = os.path.join(LOG_DIR, "pv_heartbeat.txt")
STATE_FILE= os.path.join(LOG_DIR, "pv_state.json")
os.makedirs(LOG_DIR, exist_ok=True)
_LOG_FH = open(LOG_FILE, "a", encoding="utf-8", buffering=1)

def _ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]

def _log(msg: str) -> None:
    line = f"[{_ts()}] [print_view] {msg}"
    try: print(line, flush=True)
    except Exception: pass
    try: _LOG_FH.write(line + "\n"); _LOG_FH.flush()
    except Exception: pass

def _state_update(**kw):
    try:
        data = {"ts": _ts(), **kw}
        with open(STATE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        _log(f"state write fail: {kw}")

def _hb_tick_write():
    try:
        with open(HB_FILE, "w", encoding="utf-8") as f:
            f.write(_ts())
    except Exception:
        pass

def _install_global_exhook():
    def _exhook(etype, e, tb):
        try:
            _log("UNCAUGHT EXCEPTION:")
            for ln in traceback.format_exception(etype, e, tb):
                for l in ln.rstrip().splitlines():
                    _log("  " + l)
            _state_update(phase="crash", reason=str(e.__class__.__name__), message=str(e))
        finally:
            sys.__excepthook__(etype, e, tb)
    sys.excepthook = _exhook

_install_global_exhook()
atexit.register(lambda: _state_update(phase="exit"))

#──────── 공통 유틸 ────────
def _json_load(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def _merge(dst: dict, src: dict) -> dict:
    out = dict(dst or {})
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out

def _deep_get(d: dict, path: str, default=None):
    cur = d
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return default
        cur = cur[key]
    return cur

#──────── 파일 유틸 ────────
def _safe_remove(path: str, *, max_retry: int = 12) -> bool:
    if not os.path.exists(path):
        return True
    for i in range(max_retry):
        try:
            os.remove(path); return True
        except Exception:
            time.sleep(0.10 + 0.10*(i % 2))
    return False

def _copy_small(src: str, dst: str) -> bool:
    try:
        with open(src, "rb") as f: b = f.read()
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "wb") as f: f.write(b)
        _log(f"copy {src} → {dst}")
        return True
    except Exception as e:
        _log(f"copy failed: {src} → {dst}: {e}")
        return False

def _file_sig(path: str) -> Tuple[int, int]:
    try:
        st = os.stat(path)
        return (int(st.st_mtime), int(st.st_size))
    except Exception:
        return (0, 0)

#──────── Photoshop COM ────────
try:
    import pythoncom
    from win32com.client import gencache
except Exception:
    pythoncom = None
    gencache = None

def _ps_get(retries: int = 2, delay: float = 0.2):
    if pythoncom is None or gencache is None:
        return None
    pythoncom.CoInitialize()
    last = None
    for _ in range(max(1, retries)):
        try:
            return gencache.EnsureDispatch("Photoshop.Application")
        except Exception as e:
            last = e; time.sleep(delay)
    raise last

def _ps_do_action(set_name: str, action_name: str,
                  *, open_fallback: bool, fallback_path: str,
                  retries: int = 2, delay: float = 0.2) -> bool:
    try:
        ps = _ps_get(retries=retries, delay=delay)
    except Exception as e:
        _log(f"EnsureDispatch err: {e}")
        return False
    if ps is None:
        _log("pywin32 missing")
        return False
    try: ps.DisplayDialogs = 3
    except Exception: pass
    try: has_doc = int(ps.Documents.Count) > 0
    except Exception: has_doc = False
    if not has_doc and open_fallback:
        _log("no doc. opening fallback or add dummy")
        if fallback_path and os.path.exists(fallback_path):
            try: ps.Open(fallback_path)
            except Exception: ps.Documents.Add(800, 600)
        else:
            ps.Documents.Add(800, 600)
    attempts = max(1, retries)
    for i in range(attempts):
        try:
            _log(f"DoAction start: [{set_name}/{action_name}] try[{i}]")
            ps.DoAction(action_name, set_name)
            _log(f"DoAction ok: [{set_name}/{action_name}]")
            return True
        except Exception as e:
            _log(f"DoAction err try[{i}]: {e}")
            time.sleep(max(0.05, delay))
    _log(f"DoAction fail: [{set_name}/{action_name}]")
    return False

#──────── Windows 입력/포커스 ────────
_user32 = ctypes.windll.user32 if hasattr(ctypes, "windll") else None

if _user32:
    ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p)==8 else ctypes.c_ulong
    class KEYBDINPUT(ctypes.Structure):
        _fields_=[("wVk",wintypes.WORD),("wScan",wintypes.WORD),
                  ("dwFlags",wintypes.DWORD),("time",wintypes.DWORD),
                  ("dwExtraInfo",ULONG_PTR)]
    class MOUSEINPUT(ctypes.Structure):
        _fields_=[("dx",wintypes.LONG),("dy",wintypes.LONG),("mouseData",wintypes.DWORD),
                  ("dwFlags",wintypes.DWORD),("time",wintypes.DWORD),("dwExtraInfo",ULONG_PTR)]
    class HARDWAREINPUT(ctypes.Structure):
        _fields_=[("uMsg",wintypes.DWORD),("wParamL",wintypes.WORD),("wParamH",wintypes.WORD)]
    class INPUT_U(ctypes.Union):
        _fields_=[("ki",KEYBDINPUT),("mi",MOUSEINPUT),("hi",HARDWAREINPUT)]
    class INPUT(ctypes.Structure):
        _fields_=[("type",wintypes.DWORD),("ii",INPUT_U)]
    _user32.SendInput.argtypes = (wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int)
    _user32.SendInput.restype  = wintypes.UINT

def _sendinput_vk(vk: int) -> int:
    if not _user32:
        return 0
    IKEY = 1
    KEYEVENTF_KEYUP = 0x0002
    down = INPUT(type=IKEY, ii=INPUT_U(ki=KEYBDINPUT(vk, 0, 0, 0, ULONG_PTR(0))))
    up   = INPUT(type=IKEY, ii=INPUT_U(ki=KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, ULONG_PTR(0))))
    arr  = (INPUT * 2)(down, up)
    try:
        sent = _user32.SendInput(2, ctypes.byref(arr[0]), ctypes.sizeof(INPUT))
    except Exception as e:
        _log(f"SendInput error: {e}")
        return 0
    _log(f"ENTER SendInput -> sent={sent}")
    return int(sent)

VK = {
    "RETURN": 0x0D, "CTRL": 0x11, "SHIFT": 0x10, "MENU": 0x12,
    "F1":0x70,"F2":0x71,"F3":0x72,"F4":0x73,"F5":0x74,"F6":0x75,"F7":0x76,
    "F8":0x77,"F9":0x78,"F10":0x79,"F11":0x7A,"F12":0x7B
}

def _get_class_name(hwnd: int) -> str:
    if not _user32 or not hwnd: return ""
    buf = ctypes.create_unicode_buffer(256)
    try:
        _user32.GetClassNameW(hwnd, buf, 256)
        return buf.value or ""
    except Exception:
        return ""

def _enum_windows() -> List[int]:
    if not _user32: return []
    res: List[int] = []
    CB = ctypes.WINFUNCTYPE(ctypes.c_bool, wintypes.HWND, wintypes.LPARAM)
    def _cb(hwnd, lparam):
        try:
            if _user32.IsWindowVisible(hwnd):
                res.append(hwnd)
        except Exception:
            pass
        return True
    _user32.EnumWindows(CB(_cb), 0)
    return res

def _is_photoshop(hwnd: int) -> bool:
    if not _user32: return False
    title = ctypes.create_unicode_buffer(256)
    try:
        _user32.GetWindowTextW(hwnd, title, 256)
        t = title.value.lower()
        cls = _get_class_name(hwnd).lower()
        return ("photoshop" in t) or ("photoshop" in cls)
    except Exception:
        return False

def _find_ps_top() -> int:
    for h in _enum_windows():
        if _is_photoshop(h):
            return h
    return 0

# Win32 window ops
SW_SHOW        = 5
SW_RESTORE     = 9
SWP_NOSIZE     = 0x0001
SWP_NOMOVE     = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_SHOWWINDOW = 0x0040
HWND_TOPMOST   = -1
HWND_NOTOPMOST = -2

# optional foreground APIs
if _user32:
    try:
        _user32.AllowSetForegroundWindow.argtypes = [wintypes.DWORD]
        _user32.AllowSetForegroundWindow.restype  = wintypes.BOOL
    except Exception:
        pass
    try:
        _user32.SwitchToThisWindow.argtypes = [wintypes.HWND, wintypes.BOOL]
        _user32.SwitchToThisWindow.restype  = None
    except Exception:
        pass

def _activate_ps(hwnd: int) -> bool:
    if not _user32 or not hwnd:
        return False
    try:
        try: _user32.AllowSetForegroundWindow(0xFFFFFFFF)
        except Exception: pass
        _user32.ShowWindow(hwnd, SW_SHOW)
        _user32.SetWindowPos(hwnd, HWND_TOPMOST, 0,0,0,0, SWP_NOMOVE|SWP_NOSIZE)
        time.sleep(0.01)
        ok = bool(_user32.SetForegroundWindow(hwnd))
        if not ok:
            _user32.BringWindowToTop(hwnd)
            try: _user32.SwitchToThisWindow(hwnd, True)
            except Exception: pass
            try: _user32.SetActiveWindow(hwnd)
            except Exception: pass
            ok = (_user32.GetForegroundWindow() == hwnd)
        _user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0,0,0,0, SWP_NOMOVE|SWP_NOSIZE)
        return bool(ok)
    except Exception:
        return False

def _win_set_topmost(hwnd: int, topmost: bool, no_activate: bool = True):
    if not _user32 or not hwnd: return
    flags = SWP_NOMOVE | SWP_NOSIZE | SWP_SHOWWINDOW
    if no_activate: flags |= SWP_NOACTIVATE
    try:
        _user32.SetWindowPos(hwnd, HWND_TOPMOST if topmost else HWND_NOTOPMOST, 0,0,0,0, flags)
    except Exception as e:
        _log(f"SetWindowPos error: {e}")

def _activate_hwnd_strong(hwnd: int) -> bool:
    if not _user32 or not hwnd: return False
    try:
        _user32.ShowWindow(hwnd, SW_SHOW)
        _user32.ShowWindow(hwnd, SW_RESTORE)
        _user32.SetForegroundWindow(hwnd)
        time.sleep(0.01)
        if _user32.GetForegroundWindow() == hwnd: return True
        # ALT trick
        _user32.keybd_event(VK["MENU"], 0, 0, 0)
        _user32.keybd_event(VK["MENU"], 0, 2, 0)
        _user32.SetForegroundWindow(hwnd)
        time.sleep(0.01)
        if _user32.GetForegroundWindow() == hwnd: return True
        # TopMost bounce
        _win_set_topmost(hwnd, True, False); time.sleep(0.01)
        _user32.BringWindowToTop(hwnd); time.sleep(0.01)
        _win_set_topmost(hwnd, False, False); time.sleep(0.01)
        _user32.SetForegroundWindow(hwnd); time.sleep(0.01)
        return _user32.GetForegroundWindow() == hwnd
    except Exception as e:
        _log(f"_activate_hwnd_strong error: {e}")
        return False

def _borrow_focus_and(fn) -> None:
    if not _user32:
        fn(); return
    ps = _find_ps_top()
    if not ps:
        _log("borrow: PS not found"); fn(); return
    prev = _user32.GetForegroundWindow()
    pid1 = wintypes.DWORD(); pid2 = wintypes.DWORD()
    tid_prev = _user32.GetWindowThreadProcessId(prev, ctypes.byref(pid1))
    tid_ps   = _user32.GetWindowThreadProcessId(ps, ctypes.byref(pid2))
    _user32.AttachThreadInput(tid_prev, tid_ps, True)
    try:
        ok = _activate_hwnd_strong(ps)
        _log(f"borrow: activate_ps ok={ok} hwnd=0x{ps:X}")
        fn(); time.sleep(0.01)
    finally:
        try:
            if prev: _user32.SetForegroundWindow(prev)
        except Exception: pass
        _user32.AttachThreadInput(tid_prev, tid_ps, False)

def _borrow_focus_for_enter(fn) -> None:
    if not _user32:
        fn(); return
    ps = _find_ps_top()
    if not ps:
        _log("enter-borrow: photoshop hwnd not found"); fn(); return
    prev = _user32.GetForegroundWindow()
    pid1 = wintypes.DWORD(); pid2 = wintypes.DWORD()
    tid_prev = _user32.GetWindowThreadProcessId(prev, ctypes.byref(pid1))
    tid_ps   = _user32.GetWindowThreadProcessId(ps, ctypes.byref(pid2))
    _user32.AttachThreadInput(tid_prev, tid_ps, True)
    try:
        ok = _activate_ps(ps)
        _log(f"enter-borrow: activate_ps ok={ok} hwnd=0x{ps:X}")
        time.sleep(0.01); fn(); time.sleep(0.01)
    finally:
        try:
            if prev: _user32.SetForegroundWindow(prev)
        except Exception: pass
        _user32.AttachThreadInput(tid_prev, tid_ps, False)

def _press_vk(vk: int, *, down: bool) -> None:
    if not _user32: return
    flags = 0 if down else 2
    _user32.keybd_event(vk, 0, flags, 0)

def _send_combo(vk_main: int, *, ctrl=False, shift=False, alt=False) -> None:
    if not _user32: return
    if ctrl:  _press_vk(VK["CTRL"],  down=True)
    if shift: _press_vk(VK["SHIFT"], down=True)
    if alt:   _press_vk(VK["MENU"],  down=True)
    _press_vk(vk_main, down=True); _press_vk(vk_main, down=False)
    if alt:   _press_vk(VK["MENU"],  down=False)
    if shift: _press_vk(VK["SHIFT"], down=False)
    if ctrl:  _press_vk(VK["CTRL"],  down=False)

def _parse_hotkey(hk: str) -> Tuple[int,bool,bool,bool]:
    s = (hk or "").upper().replace(" ", "")
    parts = [p for p in s.split("+") if p]
    ctrl = "CTRL" in parts
    shift= "SHIFT" in parts
    alt  = "ALT" in parts or "MENU" in parts
    main = next((p for p in parts if p.startswith("F")), "F6")
    vk = VK.get(main, VK["F6"])
    return vk, ctrl, shift, alt

def _send_enter_once() -> None:
    sent = _sendinput_vk(VK["RETURN"])
    if sent == 0 and _user32:
        _log("ENTER SendInput -> sent=0 (fallback keybd_event)")
        _press_vk(VK["RETURN"], down=True); _press_vk(VK["RETURN"], down=False)

#──────── 텍스트 그림자 버튼 ────────
class ShadowButton(QPushButton):
    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._sx, self._sy = 0, 1
        self._sc = QColor("#000000")
        self._normal = QColor("#000000")
        self._checked = QColor("#FFFFFF")
    def setTextShadow(self, dx: int, dy: int, color: str):
        self._sx, self._sy, self._sc = int(dx), int(dy), QColor(color); self.update()
    def setTextColors(self, normal: str, checked: str):
        self._normal, self._checked = QColor(normal), QColor(checked); self.update()
    def paintEvent(self, e):
        opt = QStyleOptionButton(); self.initStyleOption(opt)
        txt = opt.text
        base = QStyleOptionButton(opt); base.text = ""
        p = QPainter(self); self.style().drawControl(QStyle.CE_PushButton, base, p, self)
        rect = self.style().subElementRect(QStyle.SE_PushButtonContents, opt, self)
        if txt:
            if self.isChecked():
                p.setPen(self._sc); p.drawText(rect.translated(self._sx, self._sy), Qt.AlignCenter, txt)
                p.setPen(self._checked)
            else:
                p.setPen(self._normal)
            p.drawText(rect, Qt.AlignCenter, txt)
        p.end()

#──────── Busy Overlay ────────
class _Spinner(QWidget):
    def __init__(self, size=72, thick=6, parent=None):
        super().__init__(parent)
        self._angle = 0
        self._size = int(size)
        self._thick = int(thick)
        self._timer = QTimer(self); self._timer.timeout.connect(self._tick)
        self.setFixedSize(self._size, self._size)
    def start(self, interval_ms=16): self._timer.start(max(8, int(interval_ms)))
    def stop(self): self._timer.stop()
    def _tick(self): self._angle = (self._angle + 8) % 360; self.update()
    def paintEvent(self, e):
        p = QPainter(self); p.setRenderHint(QPainter.Antialiasing, True)
        r = self.rect(); rad = min(r.width(), r.height())/2 - self._thick
        p.translate(r.center()); p.rotate(self._angle)
        pen = QPen(self.palette().highlight().color(), self._thick, Qt.SolidLine, Qt.RoundCap)
        p.setPen(pen); p.drawArc(int(-rad), int(-rad), int(2*rad), int(2*rad), 0, 270*16); p.end()

class _BusyOverlay(QFrame):
    def __init__(self, parent=None, *, text="작업중...", bg="rgba(0,0,0,150)"):
        super().__init__(parent)
        self.setObjectName("busyOverlay")
        self.setStyleSheet(
            "QFrame#busyOverlay { background: %s; }"
            "QLabel#busyText { background: transparent; color: #FFFFFF; font-size: 24px; }"
            % bg
        )
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)

        lay = QVBoxLayout(self); lay.setContentsMargins(0,0,0,0); lay.setSpacing(18)
        lay.addStretch(1)
        self.spinner = _Spinner(84, 8, self); lay.addWidget(self.spinner, 0, Qt.AlignHCenter)
        self.lbl = QLabel(text, self); self.lbl.setObjectName("busyText")
        self.lbl.setAutoFillBackground(False)
        self.lbl.setAttribute(Qt.WA_TranslucentBackground, True)
        lay.addWidget(self.lbl, 0, Qt.AlignHCenter)
        lay.addStretch(2)

    def setText(self, t: str): self.lbl.setText(t)
    def start(self): self.show(); self.raise_(); self.spinner.start()
    def stop(self): self.spinner.stop(); self.hide()

#──────── Photoshop Action 워커(비동기) ────────
class _PSActionWorker(QObject):
    finished = Signal(bool)  # ok

    def __init__(self, set_name: str, action_name: str,
                 open_fallback: bool, fallback_path: str,
                 retries: int, delay: float):
        super().__init__()
        self.set_name = set_name
        self.action_name = action_name
        self.open_fallback = bool(open_fallback)
        self.fallback_path = str(fallback_path or "")
        self.retries = int(retries)
        self.delay = float(delay)

    def run(self):
        ok = False
        try:
            ok = _ps_do_action(
                self.set_name,
                self.action_name,
                open_fallback=self.open_fallback,
                fallback_path=self.fallback_path,
                retries=self.retries,
                delay=self.delay,
            )
        except Exception as e:
            _log(f"_PSActionWorker.run error: {e}")
            ok = False
        try:
            self.finished.emit(bool(ok))
        except Exception:
            pass


#──────── AI 전처리 워커(비동기) ────────
class _AIWorker(QObject):
    finished = Signal(bool, str)  # ok, message

    def __init__(self, origin_path: str, ai_out_path: str, ratio_code: str, eye_strength: float = 0.4):
        super().__init__()
        self.origin_path = origin_path
        self.ai_out_path = ai_out_path
        self.ratio_code = ratio_code  # "3040" / "3545"
        self.eye_strength = float(eye_strength)

    def run(self):
        import os, shutil, importlib
        try:
            # ai_retouch 모듈 로드(패키지/단일 파일 모두 대응)
            try:
                AIR = importlib.import_module("app.utils.ai_retouch")
            except Exception:
                AIR = importlib.import_module("ai_retouch")

            if not os.path.exists(self.origin_path):
                self.finished.emit(False, "origin missing")
                return

            # ratio_code → 튜플
            ratio = (3, 4) if str(self.ratio_code).strip() == "3040" else (7, 9)

            # 파일 기반 최소 파이프라인(조명보정 X, 경량)
            ok = False
            try:
                ok = bool(AIR.process_file_core(
                    self.origin_path,
                    self.ai_out_path,
                    target_ratio=ratio,
                    spec_profile=None,              # ratio로 자동 선택
                    eye_strength=self.eye_strength,
                    mirror_logic=False,
                ))
            except Exception as e:
                _log(f"_AIWorker pipeline error: {e}")
                ok = False

            if ok and os.path.exists(self.ai_out_path):
                self.finished.emit(True, "ok")
                return

            # 폴백: 원본 복사
            try:
                os.makedirs(os.path.dirname(self.ai_out_path) or ".", exist_ok=True)
                shutil.copy2(self.origin_path, self.ai_out_path)
                self.finished.emit(True, "fallback copy")
            except Exception as e2:
                self.finished.emit(False, f"save fail: {e2}")
        except Exception as e:
            self.finished.emit(False, f"worker error: {e}")


class PrintViewPage(BasePage):
    """
    설정: C:\\PhotoBox\\settings.json (릴리즈 전 defaults.json으로 복사 예정).
    단계: Ratio → Liquify → Neural(DoAction 비동기; ENTER 타이머 즉시 시작) → Background.
    """
    def __init__(self, theme, session: dict, parent: Optional[QWidget] = None):
        # 하트비트 시작(사라짐 진단)
        self._hb_timer = QTimer()
        self._hb_timer.timeout.connect(_hb_tick_write)
        self._hb_timer.start(1000)
        _state_update(phase="init")

        # 설정 로드
        app_dir = os.path.dirname(os.path.dirname(__file__))
        defaults  = _json_load(os.path.join(app_dir, "config", "defaults.json"))
        overrides = _json_load(r"C:\PhotoBox\settings.json")
        self.config = _merge(defaults, overrides)

        # ✅ 공통 지연
        self.DLY_MS = int(_deep_get(self.config, "photoshop.pipeline_delay_ms", 1000))

        # 스텝바
        step_labels = _deep_get(self.config, "flow.step_labels",
                                ["인트로","정보입력","사이즈선택","촬영","사진선택","AI 보정","이메일전송","추가옵션","종료"])
        steps_tokens = _deep_get(self.config, "flow.steps",
                                 ["INTRO","INPUT","SIZE","CAPTURE","PICK","PREVIEW","EMAIL","ENHANCE","OUTRO"])
        try: active_idx = steps_tokens.index("PREVIEW")
        except Exception: active_idx = 4
        super().__init__(theme, steps=step_labels, active_index=active_idx, parent=parent)

        # 경로
        self.ORIGIN_PATH  = _deep_get(self.config, "paths.origin",       r"C:\PhotoBox\origin_photo.jpg")
        self.EDITED_DONE  = _deep_get(self.config, "paths.edited_done",  r"C:\PhotoBox\edited_photo.jpg")
        self.RAW_DONE     = _deep_get(self.config, "paths.raw_done",     r"C:\PhotoBox\raw.jpg")
        self.LIQUIFY_DONE = _deep_get(self.config, "paths.liquify_done", r"C:\PhotoBox\liquify.jpg")
        self.SETTING_DIR  = _deep_get(self.config, "paths.setting_dir",  r"C:\PhotoBox\setting")
        self.PRESET_DIR   = _deep_get(self.config, "paths.preset_dir",   r"C:\PhotoBox\setting\preset")
        self.AI_ORIGIN    = _deep_get(self.config, "paths.ai_out",       r"C:\PhotoBox\ai_origin_photo.jpg")

        # 액션
        self.PS_RATIO_SET = _deep_get(self.config, "photoshop.ratio.set", "셀프스튜디오")
        self.PS_ACT_3040  = _deep_get(self.config, "photoshop.ratio.action_3040", "3X4")
        self.PS_ACT_3545  = _deep_get(self.config, "photoshop.ratio.action_3545", "3.5X4.5")
        self.PS_LIQ_SET   = _deep_get(self.config, "photoshop.liquify.set", "셀프스튜디오")
        self.PS_LIQ_ACT   = _deep_get(self.config, "photoshop.liquify.action", "liquify")

        # Background
        self.PS_BG_SET    = _deep_get(self.config, "photoshop.background.set", "셀프스튜디오")
        self.PS_BG_ACTIONS= _deep_get(self.config, "photoshop.background.actions",
                                      ["grada_blue","grada_brown","grada_gray"])

        # Neural(DoAction 사용)# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, Any, Tuple, Optional
from math import atan2, degrees, fabs
from PySide6.QtGui import QImage


class Guidance:
    """검출 결합 + 메트릭 + 메시지 + 레이트리밋 + EMA.
    update()는 QImage와 ratio를 받아 (payload, badges, metrics_ema)를 반환.

    배지 포맷:
      {
        "primary": str,  # 중앙: Yaw/Pitch/OK/Fallback
        "left": str,     # 좌: 눈 수평
        "right": str     # 우: 어깨 수평
      }
    """

    # ─ 정책 임계 ─
    SHOULDER_OK = 3.0
    SHOULDER_WARN = 5.0
    SHOULDER_ON = SHOULDER_OK + 1.5   # on/off 히스테리시스
    SHOULDER_OFF = SHOULDER_OK - 1.0

    EYE_OK = 1.5                       # dy(%H)
    EYE_WARN = 2.5
    EYE_ON = EYE_WARN                  # 2.5% 에서 ON
    EYE_OFF = EYE_OK - 0.7             # 0.8% 에서 OFF

    YAW_OK = 6.0
    YAW_WARN = 9.0
    YAW_ON = YAW_OK + 4.0              # 10°
    YAW_OFF = YAW_OK - 3.0             # 3°

    PITCH_LOW = 3.0                    # 권장 +3°~+10°
    PITCH_HIGH = 10.0
    PITCH_ON_DELTA = 2.0               # 권장범위 이탈량 기준
    PITCH_OFF_DELTA = 1.0

    def __init__(self, rate_ms: int = 500, ema_alpha: float = 2.0/11.0):
        self.rate_ms = int(rate_ms)
        self.alpha = float(ema_alpha)
        self._last_ts: int = 0
        self._ema: Dict[str, float] = {}
        self._last_badges: Dict[str, str] = {"primary": "", "left": "", "right": ""}
        self._gate: Dict[str, bool] = {"shoulder": False, "eye": False, "yaw": False, "pitch": False}

    def reset(self):
        self._last_ts = 0
        self._ema.clear()
        self._gate = {"shoulder": False, "eye": False, "yaw": False, "pitch": False}
        self._last_badges = {"primary": "", "left": "", "right": ""}

    def update(
        self,
        qimg: QImage,
        ratio: str,
        ts_ms: int,
        face_engine=None,
        pose_engine=None,
    ) -> Tuple[Dict[str, Any], Dict[str, str], Dict[str, float]]:
        w, h = qimg.width(), qimg.height()
        payload: Dict[str, Any] = {}

        # 검출 호출은 예외 흡수
        if face_engine is not None:
            try:
                fr = face_engine.process_frame(qimg, (w, h), ts_ms)
                if isinstance(fr, dict):
                    payload["face"] = fr
            except Exception:
                pass
        if pose_engine is not None:
            try:
                pr = pose_engine.process_frame(qimg, (w, h), ts_ms)
                if isinstance(pr, dict):
                    payload["pose"] = pr
            except Exception:
                pass

        raw = self.compute_metrics(payload, w, h)

        # 2 Hz로만 배지/EMA 갱신
        if ts_ms - self._last_ts >= self.rate_ms:
            self._last_ts = ts_ms
            self._ema = self._ema_merge(self._ema, raw, self.alpha)
            self._last_badges = self.decide_message(self._ema, payload)

        return payload, dict(self._last_badges), dict(self._ema)

    # ─ metrics/message ─
    @staticmethod
    def _get_core_point(face: Dict[str, Any], key: str) -> Optional[Tuple[float, float]]:
        try:
            core = face.get("core") or {}
            v = core.get(key)
            if isinstance(v, (tuple, list)) and len(v) >= 2:
                return float(v[0]), float(v[1])
        except Exception:
            pass
        return None

    def compute_metrics(self, payload: Dict[str, Any], w: int, h: int) -> Dict[str, float]:
        m: Dict[str, float] = {}
        try:
            f = payload.get("face") or {}
            p = payload.get("pose") or {}

            # 포인트 존재 플래그
            face_pts = f.get("pro_mesh") or []
            if not face_pts and isinstance(f.get("core"), dict):
                face_pts = list(f["core"].values())
            pose_pts = p.get("shoulder_support") or []
            m["has_face"] = 1.0 if (len(face_pts) > 0) else 0.0
            m["has_pose"] = 1.0 if (len(pose_pts) > 0 or ("shoulder_L" in p and "shoulder_R" in p)) else 0.0

            # 어깨 각도(deg). 정규화 좌표 → 픽셀 스케일 보정 뒤 atan2
            sh_L = p.get("shoulder_L"); sh_R = p.get("shoulder_R")
            if isinstance(sh_L, (tuple, list)) and isinstance(sh_R, (tuple, list)) and len(sh_L) >= 2 and len(sh_R) >= 2:
                dx = (float(sh_R[0]) - float(sh_L[0])) * float(w)
                dy = (float(sh_R[1]) - float(sh_L[1])) * float(h)
                m["shoulder_deg"] = float(degrees(atan2(dy, dx)))
            else:
                m["shoulder_deg"] = 0.0

            # 눈 수평(%H). face 엔진은 0..1 정규화 → *100만 하면 %H
            eL = self._get_core_point(f, "eye_L")
            eR = self._get_core_point(f, "eye_R")
            if eL and eR:
                dy = float(eL[1]) - float(eR[1])
                m["eye_h%"] = float(fabs(dy) * 100.0)
                # sign>0: 왼쪽 눈이 더 아래 → 오른쪽으로 기울여 보정
                m["eye_sign"] = 1.0 if dy > 0 else (-1.0 if dy < 0 else 0.0)
            else:
                m["eye_h%"] = 0.0
                m["eye_sign"] = 0.0

            # yaw/pitch(deg) — 페이로드에 있으면 사용
            yaw = pitch = None
            for k in ("angles", "euler", "pose"):
                if isinstance(f.get(k), dict):
                    yaw = f[k].get("yaw")
                    pitch = f[k].get("pitch")
                    break
            # 파일 스틸 입력이므로 미러 보정 금지('file')
            try:
                from app.ai.guidance import normalize_yaw_degrees
                m["yaw_deg"] = normalize_yaw_degrees(yaw, 'file')
            except Exception:
                m["yaw_deg"] = float(yaw) if isinstance(yaw, (int, float)) else 0.0
            m["pitch_deg"] = float(pitch) if isinstance(pitch, (int, float)) else 0.0
            m["has_yaw"] = 1.0 if isinstance(yaw, (int, float)) else 0.0
            m["has_pitch"] = 1.0 if isinstance(pitch, (int, float)) else 0.0

            # OK flags — yaw/pitch 미제공 시 OK 간주
            m["ok_shoulder"] = 1.0 if fabs(m["shoulder_deg"]) <= self.SHOULDER_OK else 0.0
            m["ok_eye"] = 1.0 if m["eye_h%"] <= self.EYE_OK else 0.0
            m["ok_yaw"] = 1.0 if (m.get("has_yaw", 0.0) < 0.5 or fabs(m["yaw_deg"]) <= self.YAW_OK) else 0.0
            if m.get("has_pitch", 0.0) >= 0.5:
                m["ok_pitch"] = 1.0 if (self.PITCH_LOW <= m["pitch_deg"] <= self.PITCH_HIGH) else 0.0
            else:
                m["ok_pitch"] = 1.0
            m["ok_all"] = float(m["ok_shoulder"] * m["ok_eye"] * m["ok_yaw"] * m["ok_pitch"])
        except Exception:
            m.setdefault("has_face", 0.0); m.setdefault("has_pose", 0.0)
            m.setdefault("shoulder_deg", 0.0); m.setdefault("eye_h%", 0.0); m.setdefault("eye_sign", 0.0)
            m.setdefault("yaw_deg", 0.0); m.setdefault("pitch_deg", 0.0)
            m.setdefault("ok_all", 0.0)
        return m

    def _update_gates(self, m: Dict[str, float]) -> None:
        # shoulder
        v = fabs(m.get("shoulder_deg", 0.0))
        if self._gate["shoulder"]:
            if v < self.SHOULDER_OFF: self._gate["shoulder"] = False
        else:
            if v > self.SHOULDER_ON: self._gate["shoulder"] = True

        # eye
        v = m.get("eye_h%", 0.0)
        if self._gate["eye"]:
            if v < self.EYE_OFF: self._gate["eye"] = False
        else:
            if v > self.EYE_ON: self._gate["eye"] = True

        # yaw
        if m.get("has_yaw", 0.0) >= 0.5:
            v = fabs(m.get("yaw_deg", 0.0))
            if self._gate["yaw"]:
                if v < self.YAW_OFF: self._gate["yaw"] = False
            else:
                if v > self.YAW_ON: self._gate["yaw"] = True
        else:
            self._gate["yaw"] = False

        # pitch
        if m.get("has_pitch", 0.0) >= 0.5:
            p = m.get("pitch_deg", 0.0)
            delta = (self.PITCH_LOW - p) if p < self.PITCH_LOW else ((p - self.PITCH_HIGH) if p > self.PITCH_HIGH else 0.0)
            if self._gate["pitch"]:
                if delta < self.PITCH_OFF_DELTA: self._gate["pitch"] = False
            else:
                if delta > self.PITCH_ON_DELTA: self._gate["pitch"] = True
        else:
            self._gate["pitch"] = False

    def decide_message(self, metrics: Dict[str, float], payload: Dict[str, Any]) -> Dict[str, str]:
        self._update_gates(metrics)

        has_face = metrics.get("has_face", 0.0) >= 0.5
        has_pose = metrics.get("has_pose", 0.0) >= 0.5

        left = ""; right = ""; primary = ""

        # 우측 배지: 어깨
        if self._gate["shoulder"] and has_pose:
            theta = metrics.get("shoulder_deg", 0.0)
            if theta > +2.0:
                right = "오른쪽 어깨를 살짝 올리세요"
            elif theta < -2.0:
                right = "왼쪽 어깨를 살짝 올리세요"
            else:
                right = "어깨를 수평에 맞춰 주세요"

        # 좌측 배지: 눈 수평(방향 포함)
        if self._gate["eye"] and has_face:
            s = metrics.get("eye_sign", 0.0)
            if s > 0:
                left = "고개를 오른쪽으로 아주 살짝 기울여 균형"
            elif s < 0:
                left = "고개를 왼쪽으로 아주 살짝 기울여 균형"
            else:
                left = "고개를 아주 살짝 기울여 균형"

        # 중앙 배지: Yaw → Pitch → OK/Fallback
        if self._gate["yaw"] and has_face:
            yaw_abs = fabs(metrics.get("yaw_deg", 0.0))
            primary = f"정면을 바라봐 주세요 ({yaw_abs:.1f}°)"
        elif self._gate["pitch"] and has_face:
            p = metrics.get("pitch_deg", 0.0)
            primary = "턱을 조금 풀어 주세요" if p < self.PITCH_LOW else "턱을 조금 당겨 주세요"
        else:
            if not has_face:
                primary = "얼굴이 화면에 들어오게 정면을 바라봐 주세요"
            elif not has_pose:
                primary = "어깨가 화면에 들어오게 조금만 뒤로 이동해 주세요"
            else:
                primary = "OK" if metrics.get("ok_all", 0.0) >= 0.5 else "자세를 조금만 보정해 주세요"

        return {"primary": primary, "left": left, "right": right}

    # ─ helpers ─
    @staticmethod
    def _ema_merge(ema: Dict[str, float], cur: Dict[str, float], alpha: float) -> Dict[str, float]:
        out: Dict[str, float] = dict(ema)
        for k, v in cur.items():
            try:
                pv = float(out.get(k, v))
                out[k] = pv + alpha * (float(v) - pv)
            except Exception:
                out[k] = float(v) if isinstance(v, (int, float)) else 0.0
        return out

        self.PS_NEU_SET   = _deep_get(self.config, "photoshop.neural.set", "셀프스튜디오")
        self.PS_NEU_ACT1  = _deep_get(self.config, "photoshop.neural.mode1.action", "neural")
        self.PS_NEU_ACT2  = _deep_get(self.config, "photoshop.neural.mode2.action", "neural_2")
        self.NEURAL_USE_ACTION = bool(_deep_get(self.config, "photoshop.neural.use_action", True))

        # 핫키(보존만)
        self.NHK1 = _deep_get(self.config, "photoshop.neural.mode1.hotkey", "Ctrl+F6")
        self.NHK2 = _deep_get(self.config, "photoshop.neural.mode2.hotkey", "Ctrl+F7")
        self.N_FIRST_DELAY = int(_deep_get(self.config, "photoshop.neural.progress.first_delay_ms", 5000))
        self.N_PERIOD      = int(_deep_get(self.config, "photoshop.neural.progress.period_ms", 1000))
        self.N_TIMEOUT     = int(_deep_get(self.config, "photoshop.neural.progress.timeout_ms", 120000))

        # 상태
        self.session = session or {}
        self._sel_idx: Dict[int,int] = {}
        self._overlay = _BusyOverlay(self, text="포토샵 보정중...", bg="rgba(0,0,0,150)")
        self._overlay.hide()

        # Overlay lifetime 제어
        self._overlay_hold: bool = False  # 파이프라인 전체 유지 여부

        # Neural 진행상태
        self._neural_plan: List[str] = []
        self._neural_step = -1
        self._neural_timer: QTimer|None = None
        self._neural_elapsed = 0
        self._edited_baseline = (0, 0)
        self._enter_topmost_dropped = False

        # 워커
        self._act_thread: QThread|None = None
        self._act_worker: _PSActionWorker|None = None
        self._ai_thread: QThread|None = None
        self._ai_worker: _AIWorker|None = None

        # UI
        root = QWidget(self)
        self.setCentralWidget(root, margin=(0,0,0,0), spacing=0, max_width=None, center=False)
        v = QVBoxLayout(root); v.setContentsMargins(0,0,0,0); v.setSpacing(0)

        self._refresh_tokens()
        self._top_sp = QWidget(root); v.addWidget(self._top_sp, 0)
        self.preview = QFrame(root); self.preview.setObjectName("preview"); self.preview.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        v.addWidget(self.preview, 0, Qt.AlignHCenter | Qt.AlignTop)
        self.preview_img = QLabel(self.preview); self.preview_img.setObjectName("previewImg"); self.preview_img.setAlignment(Qt.AlignCenter); self.preview_img.setAttribute(Qt.WA_TransparentForMouseEvents, True); self.preview_img.setGeometry(self.preview.contentsRect())
        self._pv_sp = QWidget(root); v.addWidget(self._pv_sp, 0)

        mid = QWidget(root); mid.setObjectName("midbar"); mb = QHBoxLayout(mid); mb.setContentsMargins(0,0,0,0); mb.setSpacing(int(self.TOK.get('btn_hgap',12))); mb.addStretch(1)
        self._btn_original = QPushButton("원본", mid); self._btn_original.setObjectName("midbtn")
        self._btn_original.pressed.connect(lambda: self._show_original(True))
        self._btn_original.released.connect(lambda: self._show_original(False))
        mb.addWidget(self._btn_original, 0, Qt.AlignRight)
        self._btn_apply = QPushButton("적용하기", mid); self._btn_apply.setObjectName("midbtn"); self._btn_apply.clicked.connect(self.on_apply); mb.addWidget(self._btn_apply, 0, Qt.AlignRight)
        v.addWidget(mid, 0, Qt.AlignRight)

        self._mid_sp = QWidget(root); v.addWidget(self._mid_sp, 0)
        self._ui = QWidget(root); self._ui.setObjectName("retouchUI"); self.grid = QGridLayout(self._ui); self.grid.setContentsMargins(0,0,0,0); self.grid.setAlignment(Qt.AlignLeft)
        self._ui.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed); v.addWidget(self._ui, 0, Qt.AlignLeft)
        self._bottom_sp = QWidget(root); v.addWidget(self._bottom_sp, 0)

        self._top_sp.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self._bottom_sp.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Expanding)
        v.setStretch(v.indexOf(self._top_sp),0); v.setStretch(v.indexOf(self.preview),0); v.setStretch(v.indexOf(self._pv_sp),0); v.setStretch(v.indexOf(self._ui),0); v.setStretch(v.indexOf(self._bottom_sp),1)

        # 행/버튼 라벨
        rows_cfg = _deep_get(self.config, "ai.rows", [
            {"name":"Raw","components":["1","2","3"]},
            {"name":"Liquify","components":["1","2","3"]},
            {"name":"Neural","components":["1","2","3"]},
            {"name":"Background","components":["1","2","3"]},
        ])
        self._rows: List[Dict] = []
        for i in range(4):
            row = rows_cfg[i] if i < len(rows_cfg) else {"name": f"Row{i+1}", "components": ["1","2","3"]}
            comps = list(row.get("components", []))[:3]
            while len(comps) < 3:
                comps.append(str(len(comps)+1))
            self._rows.append({"name": str(row.get("name","")), "components": comps})

        # 4행×3열
        self._groups: List[QButtonGroup] = []
        for r_idx, row in enumerate(self._rows):
            lbl = QLabel(row["name"], self._ui); lbl.setObjectName("rowTitle"); lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter); self.grid.addWidget(lbl, r_idx, 0)
            grp = QButtonGroup(self._ui); grp.setExclusive(True); self._groups.append(grp)
            for c_idx, text in enumerate(row["components"][:3]):
                btn = ShadowButton(str(text), self._ui); btn.setObjectName("sel"); btn.setCheckable(True)
                btn.setTextShadow(int(self.TOK.get('shadow_dx',0)), int(self.TOK.get('shadow_dy',1)), self.TOK.get('shadow_color','#000000'))
                btn.setTextColors(self.COL['primary_str'], '#FFFFFF')
                btn.setFixedHeight(int(self.TOK.get('btn_h',45))); btn.setMinimumWidth(int(self.TOK.get('btn_w_min',90)))
                self.grid.addWidget(btn, r_idx, c_idx+1, alignment=Qt.AlignCenter)
                grp.addButton(btn, c_idx)
                if c_idx == 0:
                    btn.setChecked(True); self._sel_idx[r_idx] = 0
                def _on_toggled(checked: bool, rr=r_idx, cc=c_idx, b=btn):
                    if checked: self._sel_idx[rr] = cc
                    b.update()
                btn.toggled.connect(_on_toggled)

        self._rebuild_qss(); self._apply_tokens_runtime(); self._apply_preview_size()
        self._elapsed = QElapsedTimer(); self._min_load_ms = 2000
        _state_update(phase="ready")

        app = QApplication.instance()
        if app:
            app.aboutToQuit.connect(lambda: self._stop_act_thread(where="aboutToQuit"))

    #── 토큰/QSS/프리뷰 ──
    def _refresh_tokens(self) -> None:
        app = QApplication.instance(); tok = (app.property("TYPO_TOKENS") or {}) if app else {}
        try: scale = float(tok.get("scale", getattr(self.theme, "scale", 1.0) or 1.0))
        except Exception: scale = getattr(self.theme, "scale", 1.0) or 1.0
        def snap3(px: int) -> int: return px if px in (1,2) else px - (px % 3)
        primary = None
        try:
            colors = getattr(self.theme, "colors", {}) or {}; v = colors.get("primary")
            primary = v if isinstance(v, QColor) else (QColor(v) if isinstance(v, str) else None)
        except Exception: primary = None
        if primary is None and app:
            pal = app.property("THEME_COLORS") or {}; v = pal.get("primary")
            primary = v if isinstance(v, QColor) else (QColor(v) if isinstance(v, str) else None)
        if primary is None: primary = QColor("#0B3D91")
        BORDER=2; PV_H=1008; PV_W_3040=756; PV_W_3545=784; PV_GAP=21; UI_TOP=30; UI_BOTTOM=30; MID_GAP=30; GRID_GAP=12
        BTN_H=60; BTN_W_MIN=150; PAD_V=6; PAD_H=6; HGAP=21; VGAP=21; ROW_FS=30; ROW_W=600; BTN_FS=24; PV_R=0; BTN_R=6
        self.TOK = {
            "scale":scale,
            "preview_h":snap3(int(PV_H*scale)),
            "preview_w_3040":snap3(int(PV_W_3040*scale)),
            "preview_w_3545":snap3(int(PV_W_3545*scale)),
            "border":max(1,int(round(BORDER*scale))),
            "preview_gap":snap3(int(PV_GAP*scale)),
            "grid_gap":snap3(int(GRID_GAP*scale)),
            "ui_top_gap":snap3(int(UI_TOP*scale)),
            "ui_bottom_gap":snap3(int(UI_BOTTOM*scale)),
            "midbar_gap":snap3(int(MID_GAP*scale)),
            "btn_h":snap3(int(BTN_H*scale)),
            "btn_w_min":snap3(int(BTN_W_MIN*scale)),
            "btn_pad_v":snap3(int(PAD_V*scale)),
            "btn_pad_h":snap3(int(PAD_H*scale)),
            "btn_hgap":snap3(int(HGAP*scale)),
            "btn_vgap":snap3(int(VGAP*scale)),
            "row_fs":snap3(int(ROW_FS*scale)),
            "row_weight":int(ROW_W),
            "btn_fs":snap3(int(BTN_FS*scale)),
            "preview_radius":snap3(int(PV_R*scale)),
            "btn_radius":snap3(int(BTN_R*scale)),
            "shadow_dx":0, "shadow_dy":1, "shadow_color":"#000000",
            "toast_pad":snap3(int(9*scale)), "toast_fs":snap3(int(18*scale)),
            "toast_radius":snap3(int(12*scale)), "toast_offset_up":snap3(int(150*scale)),
        }
        self.COL={"primary":primary,"primary_str":primary.name()}

    # 워커 안전 정리
    def _stop_act_thread(self, *, where: str = "manual", timeout_ms: int = 10000):
        th = getattr(self, "_act_thread", None)
        if not th: return
        try:
            if th.isRunning():
                _log(f"ACT[{where}] stopping thread...")
                try: th.quit()
                except Exception: pass
                if not th.wait(int(timeout_ms)):
                    _log("ACT wait timeout → terminate()")
                    try: th.terminate()
                    except Exception: pass
                    th.wait(2000)
            _log(f"ACT[{where}] thread stopped")
        finally:
            try:
                wk = getattr(self, "_act_worker", None)
                if wk: wk.deleteLater()
            except Exception: pass
            try: th.deleteLater()
            except Exception: pass
            self._act_thread = None
            self._act_worker = None

    def _rebuild_qss(self) -> None:
        c = self.COL["primary_str"]; p = self.COL["primary"]; r,g,b = p.red(),p.green(),p.blue()
        hov = f"rgba({r},{g},{b},30)"
        bdr = int(self.TOK["border"]); pv=int(self.TOK["btn_pad_v"]); ph=int(self.TOK["btn_pad_h"])
        br_prev=int(self.TOK['preview_radius']); br_btn=int(self.TOK['btn_radius'])
        fs_row=int(self.TOK['row_fs']); fw_row=int(self.TOK['row_weight']); fs_btn=int(self.TOK['btn_fs']); b2=max(1, int(self.TOK['border']*2))
        self._qss = f"""
        QFrame#preview {{
            background: rgba(0,0,0,0);
            border: {bdr}px solid {c};
            border-radius: {br_prev}px;
        }}
        QLabel#rowTitle {{
            color: {c};
            font-weight: {fw_row};
            font-size: {fs_row}px;
        }}
        QPushButton#sel {{
            border: {bdr}px solid {c};
            padding: {pv}px {ph}px;
            border-radius: {br_btn}px;
            background: transparent;
            color: {c};
            font-size: {fs_btn}px;
        }}
        QPushButton#sel:checked {{ background: {c}; color: #FFFFFF; border-width: {b2}px; }}
        QPushButton#midbtn {{
            border: {bdr}px solid {c};
            padding: {pv}px {ph}px;
            border-radius: {br_btn}px;
            background: transparent;
            color: {c};
            font-size: {fs_btn}px;
        }}
        QPushButton#midbtn:hover {{ background: {hov}; color: {c}; }}
        QPushButton#midbtn:pressed {{ background: {c}; color: #FFFFFF; }}
        QWidget#retouchUI {{}}
        """

    def _apply_tokens_runtime(self) -> None:
        self.preview.setStyleSheet(self._qss); self._ui.setStyleSheet(self._qss); self.findChild(QWidget,"midbar").setStyleSheet(self._qss)
        self._top_sp.setMinimumHeight(self.TOK['ui_top_gap']); self._pv_sp.setFixedHeight(self.TOK['preview_gap']); self._mid_sp.setFixedHeight(self.TOK['midbar_gap']); self._bottom_sp.setMinimumHeight(self.TOK['ui_bottom_gap'])
        try: self.grid.setHorizontalSpacing(self.TOK['btn_hgap']); self.grid.setVerticalSpacing(self.TOK['btn_vgap'])
        except Exception: pass
        for b in self._ui.findChildren(QPushButton, "sel"):
            b.setFixedHeight(int(self.TOK.get('btn_h',45))); b.setMinimumWidth(int(self.TOK.get('btn_w_min',90)))
        for b in self.findChildren(QPushButton, "midbtn"):
            b.setFixedHeight(int(self.TOK.get('btn_h',45))); b.setMinimumWidth(int(self.TOK.get('btn_w_min',90)))
        for b in self._ui.findChildren(ShadowButton, "sel"):
            b.setTextColors(self.COL['primary_str'], '#FFFFFF')

    def _apply_preview_size(self) -> None:
        code = self._ratio_code_from_session(self.session)
        w = self.TOK['preview_w_3040'] if code == "3040" else self.TOK['preview_w_3545']; h = self.TOK['preview_h']; b = int(self.TOK['border'])
        self.preview.setFixedSize(w+2*b, h+2*b); self.preview_img.setGeometry(self.preview.contentsRect())

    def _ratio_code_from_session(self, sess: dict) -> str:
        r = (sess or {}).get("ratio")
        if isinstance(r, str):
            return "3545" if r.strip() == "3545" else "3040"
        return "3040"


    # ==== 오버레이 수명 관리 ====
    def _overlay_show(self, text="작업중..."):
        try:
            self._overlay.setGeometry(self.rect())
            self._overlay.setText(text)
            self._overlay.start()
        except Exception as e:
            _log(f"overlay show err: {e}")

    def _overlay_hide(self):
        try:
            self._overlay.stop()
        except Exception:
            pass

    def _overlay_pipeline_start(self, text="포토샵 보정중..."):
        """파이프라인 전체 동안 오버레이 유지 시작."""
        self._overlay_hold = True
        self._overlay_show(text)

    def _overlay_pipeline_end(self):
        """파이프라인 종료(성공/실패) 시 오버레이 해제."""
        self._overlay_hold = False
        self._overlay_hide()

    def _overlay_hide_if_free(self):
        """중간 단계에서 오버레이를 끄려 할 때, 파이프라인 유지 중이면 무시."""
        if self._overlay_hold:
            _log("overlay hold active → skip hide")
            return
        self._overlay_hide()
    
    # ===== 페이지 진입 시: AI 원본 감시 오버레이 =====
    def showEvent(self, e):
        super().showEvent(e)
        try:
            if getattr(self, "_ai_entry_watch_started", False):
                return
            self._ai_entry_watch_started = True
            # AI 원본이 이미 있으면 곧바로 표시
            if os.path.exists(self.AI_ORIGIN):
                try: self._set_preview(self.AI_ORIGIN)
                except Exception: pass
                return
            # 없으면 오버레이 띄우고 주기 감시
            self._overlay_show("AI 전처리 작업중... ")
            self._ai_entry_timer = QTimer(self)
            self._ai_entry_timer.setInterval(300)
            def _tick():
                try:
                    if os.path.exists(self.AI_ORIGIN):
                        try: self._ai_entry_timer.stop()
                        except Exception: pass
                        self._set_preview(self.AI_ORIGIN)
                        self._overlay_hide_if_free()
                except Exception:
                    pass
            self._ai_entry_timer.timeout.connect(_tick)
            self._ai_entry_timer.start()
        except Exception:
            pass


    # ───────── Photoshop 종료 유틸 ─────────
    def _ps_running() -> bool:
        if os.name != "nt":
            return False
        try:
            p = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq Photoshop.exe", "/FO", "CSV", "/NH"],
                capture_output=True, text=True, creationflags=CREATE_NO_WINDOW
            )
            return "Photoshop.exe" in (p.stdout or "")
        except Exception:
            return False

    def _ps_close_async(grace_ms: int = 1500, force: bool = True) -> None:
        """파이프라인 완료 시 포토샵 종료. 먼저 정상 종료 시도, 남아있으면 강제 종료."""
        if os.name != "nt":
            return
        def _run():
            try:
                # 1) 정상 종료 시도(창 닫기)
                subprocess.run(
                    ["powershell", "-NoProfile", "-NonInteractive",
                     "Get-Process -Name Photoshop -ErrorAction SilentlyContinue "
                     "| ForEach-Object { $_.CloseMainWindow() | Out-Null }"],
                    creationflags=CREATE_NO_WINDOW
                )
            except Exception as e:
                _log(f"ps-close: close request err: {e}")
            time.sleep(max(0, grace_ms) / 1000.0)
            # 2) 여전히 살아있으면 강제 종료
            if force and _ps_running():
                try:
                    subprocess.run(
                        ["taskkill", "/IM", "Photoshop.exe", "/T", "/F"],
                        creationflags=CREATE_NO_WINDOW
                    )
                    _log("ps-close: taskkill /F issued")
                except Exception as e:
                    _log(f"ps-close: taskkill err: {e}")
        threading.Thread(target=_run, daemon=True).start()

    
#── AI 전처리 시작(비동기) ──
    def _start_ai_origin_build(self):
        try:
            # 중복 방지
            if self._ai_thread and isinstance(self._ai_thread, QThread) and self._ai_thread.isRunning():
                _log("ai_origin: thread busy → skip"); return
            ratio_code = self._ratio_code_from_session(self.session)  # "3040"/"3545"
            eye = float(_deep_get(self.config, "ai.eye_strength", 0.4))
            th = QThread(self)
            wk = _AIWorker(self.ORIGIN_PATH, self.AI_ORIGIN, ratio_code, eye_strength=eye)
            wk.moveToThread(th)
            def _finished(ok: bool, msg: str):
                _log(f"ai_origin: finished ok={ok} msg={msg}")
            th.started.connect(wk.run)
            wk.finished.connect(_finished)
            wk.finished.connect(th.quit)
            th.finished.connect(wk.deleteLater)
            th.finished.connect(th.deleteLater)
            self._ai_thread = th
            self._ai_worker = wk
            th.start()
        except Exception as e:
            _log(f"ai_origin: start error {e}")

# ==== DoAction용 ENTER 펄스 + 파일감시/TopMost 관리 ====
    def _drop_topmost_for_enter(self):
        if self._enter_topmost_dropped: return
        try:
            owner = self.window(); hwnd = int(owner.winId()) if owner else 0
            _win_set_topmost(hwnd, False, True)
            self._enter_topmost_dropped = True
            _log("enter-watch: TopMost dropped")
            _state_update(phase="enter_watch", topmost="dropped")
        except Exception as e:
            _log(f"drop topmost err: {e}")

    def _restore_topmost_after_enter(self):
        if not self._enter_topmost_dropped: return
        try:
            owner = self.window(); hwnd = int(owner.winId()) if owner else 0
            _win_set_topmost(hwnd, True, True)
            self._enter_topmost_dropped = False
            _log("enter-watch: TopMost restored")
            _state_update(phase="enter_watch", topmost="restored")
        except Exception as e:
            _log(f"restore topmost err: {e}")

    def _start_enter_watch(self, next_step_fn):
        """DoAction 직후 즉시 시작: first_delay 후 period 주기로 ENTER 전송 + edited_photo 감시."""
        self._edited_baseline = _file_sig(self.EDITED_DONE)
        self._neural_elapsed = 0
        if self._neural_timer:
            try: self._neural_timer.stop()
            except Exception: pass
        self._neural_timer = QTimer(self)

        self._drop_topmost_for_enter()
        _state_update(phase="enter_watch_start", step=self._neural_step+1, plan=self._neural_plan)

        def _tick():
            try:
                nonlocal next_step_fn
                if self._neural_elapsed == 0:
                    self._neural_timer.setInterval(max(100, int(self.N_PERIOD)))
                    _log(f"neural(action) pulse period set: {self.N_PERIOD} ms")
                self._neural_elapsed += self._neural_timer.interval()

                _borrow_focus_for_enter(_send_enter_once)
                _log("neural(action): ENTER pulse")

                cur = _file_sig(self.EDITED_DONE)
                if cur != (0, 0) and cur != self._edited_baseline:
                    _log(f"neural(action): edited_photo.jpg updated -> {cur}")
                    try: self._neural_timer.stop()
                    except Exception: pass
                    # 오버레이는 유지(파이프라인 계속)
                    self._restore_topmost_after_enter()
                    _state_update(phase="enter_watch_stop", reason="file_updated")
                    self._delay(next_step_fn)
                    return

                if self._neural_elapsed >= max(1000, int(self.N_TIMEOUT)):
                    _log("neural(action): timeout")
                    try: self._neural_timer.stop()
                    except Exception: pass
                    # 오버레이 유지(다음 단계로 진행은 동일 정책), 필요 시 토스트만
                    self._restore_topmost_after_enter()
                    self._toast("Neural 진행 시간초과")
                    _state_update(phase="enter_watch_stop", reason="timeout")
                    self._delay(next_step_fn)
            except Exception as e:
                _log(f"enter-watch tick error: {e}")

        self._neural_timer.timeout.connect(_tick)
        self._neural_timer.start(max(10, int(self.N_FIRST_DELAY)))
        _log(f"neural(action) first wait: {self.N_FIRST_DELAY} ms")

    #── 공통 지연 실행 ──
    def _delay(self, fn, ms: int | None = None):
        QTimer.singleShot(max(0, int(ms if ms is not None else self.DLY_MS)), fn)

    #── Neural 진행 시퀀스(선택 → 계획) ──
    def _neural_plan_from_selection(self) -> List[str]:
        sel = int(self._sel_idx.get(2, 0))
        if sel == 0:  return ["mode1"]
        if sel == 1:  return ["mode1", "mode2"]
        return ["mode1", "mode2", "mode2"]

    # ========== Neural: DoAction 모드 (기본) ==========
    def _start_neural_chain(self):
        self._overlay_show("포토샵 작업중... - Neural 준비")
        self._neural_plan = self._neural_plan_from_selection()
        self._neural_step = -1
        _log(f"neural plan: {self._neural_plan} (use_action={self.NEURAL_USE_ACTION})")
        _state_update(phase="neural_start", plan=self._neural_plan)
        if self.NEURAL_USE_ACTION:
            if self._neural_timer:
                try: self._neural_timer.stop()
                except Exception: pass
            self._delay(self._next_neural_step_action)
        else:
            self._delay(self._next_neural_step_hotkey)

    # ---- 비동기 DoAction 호출 ----
    def _start_ps_action_async(self, set_name: str, action_name: str,
                               *, open_fallback: bool, fallback_path: str,
                               retries: int = 2, delay: float = 0.1,
                               on_finished=None):
        # 이미 작업 중이면 시작하지 않음
        if self._act_thread and self._act_thread.isRunning():
            _log("ACT thread busy → skip start"); return

        th = QThread(self)
        wk = _PSActionWorker(set_name, action_name, open_fallback, fallback_path, retries, delay)
        wk.moveToThread(th)

        def _finished_slot(ok: bool, s=set_name, a=action_name):
            _log(f"DoAction async finished: [{s}/{a}] ok={ok}")
            if callable(on_finished):
                try: on_finished(bool(ok))
                except Exception: pass

        def _thread_done():
            _log("ACT thread finished")
            self._act_worker = None
            self._act_thread = None

        th.started.connect(wk.run)
        wk.finished.connect(_finished_slot)
        wk.finished.connect(th.quit)
        th.finished.connect(wk.deleteLater)
        th.finished.connect(_thread_done)
        th.finished.connect(th.deleteLater)

        self._act_thread = th
        self._act_worker = wk
        th.start()

    # ---- DoAction 경로 ----
    def _next_neural_step_action(self):
        self._neural_step += 1
        if self._neural_step >= len(self._neural_plan):
            _log("neural action chain complete → background (delayed)")
            return self._delay(self._start_background)

        mode = self._neural_plan[self._neural_step]
        act  = self.PS_NEU_ACT1 if mode == "mode1" else self.PS_NEU_ACT2

        # 오버레이는 파이프라인 시작 시 이미 켜져 있음(필요 시 텍스트만 보정)
        self._overlay_show("포토샵 보정중...")

        # ENTER 타이머/파일감시 즉시 시작
        self._start_enter_watch(self._next_neural_step_action)

        # DoAction은 워커 스레드에서 수행
        def _on_finished(ok: bool):
            if not ok:
                if self._neural_timer:
                    try: self._neural_timer.stop()
                    except Exception: pass
                self._restore_topmost_after_enter()
                self._toast(f"Neural({mode}) 액션 실패")
                # 실패로 파이프라인 종료 → 오버레이 해제
                self._overlay_pipeline_end()
                self._stop_act_thread(where="on_finished-fail")

        self._start_ps_action_async(self.PS_NEU_SET, act,
                                    open_fallback=False, fallback_path=self.ORIGIN_PATH,
                                    retries=2, delay=0.1,
                                    on_finished=_on_finished)

    # ========== (보존) 핫키 경로 ==========
    def _next_neural_step_hotkey(self):
        self._neural_step += 1
        if self._neural_step >= len(self._neural_plan):
            _log("neural chain complete → background (delayed)")
            return self._delay(self._start_background)
        mode = self._neural_plan[self._neural_step]
        hk_str = self.NHK1 if mode == "mode1" else self.NHK2
        vk, ctrl, shift, alt = _parse_hotkey(hk_str)
        self._edited_baseline = _file_sig(self.EDITED_DONE)
        self._neural_elapsed = 0
        _log(f"neural(hotkey) step[{self._neural_step+1}/{len(self._neural_plan)}] queued: {hk_str}")
        self._overlay_show("포토샵 작업중... - Neural")
        self._delay(lambda: _borrow_focus_and(lambda: _send_combo(vk, ctrl=ctrl, shift=shift, alt=alt)))

        if self._neural_timer:
            try: self._neural_timer.stop()
            except Exception: pass
        self._neural_timer = QTimer(self)
        self._neural_timer.timeout.connect(self._neural_tick)
        self._neural_timer.start(max(10, int(self.N_FIRST_DELAY)))
        _log(f"neural first wait: {self.N_FIRST_DELAY} ms")

    def _neural_tick(self):
        if self._neural_elapsed == 0 and self._neural_timer:
            self._neural_timer.setInterval(max(100, int(self.N_PERIOD)))
            _log(f"neural pulse period set: {self.N_PERIOD} ms")
        self._neural_elapsed += self._neural_timer.interval()
        _borrow_focus_for_enter(_send_enter_once)
        _log("neural: ENTER pulse (hotkey route)")
        cur = _file_sig(self.EDITED_DONE)
        if cur != (0,0) and cur != self._edited_baseline:
            _log(f"[neural] edited_photo.jpg updated -> {cur}")
            if self._neural_timer:
                try: self._neural_timer.stop()
                except Exception: pass
            return self._delay(self._next_neural_step_hotkey)
        if self._neural_elapsed >= max(1000, int(self.N_TIMEOUT)):
            _log("neural: timeout")
            if self._neural_timer:
                try: self._neural_timer.stop()
                except Exception: pass
            self._toast("Neural 진행 시간초과")
            # 타임아웃은 실패로 간주 → 파이프라인 종료
            self._overlay_pipeline_end()

    #── Background 실행 ──
    def _start_background(self):
        self._overlay_show("포토샵 보정중... - Resizing")
        QApplication.processEvents()

        bg_idx = int(self._sel_idx.get(3, 0))
        bg_actions = list(self.PS_BG_ACTIONS) if isinstance(self.PS_BG_ACTIONS, (list, tuple)) else []
        bg_action = bg_actions[bg_idx] if bg_idx < len(bg_actions) else f"Background{bg_idx+1}"
        _log(f"Background: {bg_action}")

        ok = _ps_do_action(self.PS_BG_SET, bg_action, open_fallback=False,
                           fallback_path=self.ORIGIN_PATH, retries=2, delay=0.1)
        if not ok:
            self._toast("Background 액션 실패")
            self._overlay_pipeline_end()   # 실패 시에는 그대로 전체 오버레이 종료
            return

        time.sleep(0.2)
        if os.path.exists(self.EDITED_DONE):
            self._set_preview(self.EDITED_DONE)

        # ✅ 성공 시: 전체 파이프라인 종료(오버레이 끄고 NEXT 활성화)
        self._pipeline_done()

    # PrintViewPage 내부 아무 곳(예: _start_background 위/아래)에 추가
    def _pipeline_done(self):
        """파이프라인 성공 종료: 오버레이/hold 정리 + Next 활성화 + 상태기록 + PS 종료"""
        try:
            self._overlay_hold = False
            self._overlay_hide()
        except Exception:
            pass
        try:
            self.set_next_enabled(True)
        except Exception:
            pass
        _state_update(phase="pipeline_done")
        _log("pipeline done")
        # ⇩ 추가: 포토샵 종료(비동기)
        try:
            _ps_close_async(grace_ms=1500, force=True)
        except Exception as e:
            _log(f"ps-close dispatch err: {e}")



    #── Apply 파이프라인 ──
    def on_apply(self):
        # 파이프라인 전구간 오버레이 ON
        self._overlay_pipeline_start("포토샵 보정중...")
        QApplication.processEvents()
        QTimer.singleShot(0, self._run_pipeline)

    def _run_pipeline(self):
        _state_update(phase="pipeline_start")
        for p in (self.RAW_DONE, self.LIQUIFY_DONE, self.EDITED_DONE):
            _safe_remove(p)
        try:
            raw_idx = int(self._sel_idx.get(0, 0)); liq_idx = int(self._sel_idx.get(1, 0))
            raw_src = os.path.join(self.PRESET_DIR, f"{raw_idx+1:02d}.xmp")
            liq_src = os.path.join(self.PRESET_DIR, f"{liq_idx+1:02d}.msh")
            raw_dst = os.path.join(self.SETTING_DIR, "raw.xmp")
            liq_dst = os.path.join(self.SETTING_DIR, "liquify.msh")
            if not _copy_small(raw_src, raw_dst):
                self._toast("Raw 프리셋 복사 실패"); _state_update(phase="fail", where="copy_raw")
                self._overlay_pipeline_end(); return
            if not _copy_small(liq_src, liq_dst):
                self._toast("Liquify 프리셋 복사 실패"); _state_update(phase="fail", where="copy_liquify")
                self._overlay_pipeline_end(); return
        except Exception as e:
            self._toast("프리셋 준비 실패"); _state_update(phase="fail", where="prep", err=str(e))
            self._overlay_pipeline_end(); return

        ratio_code = self._ratio_code_from_session(self.session)
        ratio_act  = self.PS_ACT_3040 if ratio_code == "3040" else self.PS_ACT_3545
        
        self._overlay_show("포토샵 Raw 작업중...")
        
        if not _ps_do_action(self.PS_RATIO_SET, ratio_act, open_fallback=False, fallback_path=self.ORIGIN_PATH):
            self._toast("Ratio 액션 실패"); _state_update(phase="fail", where="ratio")
            self._overlay_pipeline_end(); return

        self._delay(self._run_liquify)

    def _run_liquify(self):
        self._overlay_show("포토샵 Liquify 작업중...")
        if not _ps_do_action(self.PS_LIQ_SET, self.PS_LIQ_ACT, open_fallback=False, fallback_path=self.ORIGIN_PATH):
            self._toast("Liquify 액션 실패"); _state_update(phase="fail", where="liquify")
            self._overlay_pipeline_end(); return
        self._delay(self._start_neural_chain)

    #── 원본 보기/미리보기 ──
    def _set_preview(self, path: str) -> bool:
        try:
            if not os.path.exists(path): return False
            pm = QPixmap(path)
            if pm.isNull(): return False
            r = self.preview.contentsRect()
            pix = pm.scaled(r.width(), r.height(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.preview_img.setGeometry(self.preview.contentsRect()); self.preview_img.setPixmap(pix); self.preview_img.show(); self._preview_current = path; return True
        except Exception:
            return False

    def _show_original(self, on: bool) -> None:
        try:
            if on:
                target = self.AI_ORIGIN if os.path.exists(self.AI_ORIGIN) else self.ORIGIN_PATH
                if os.path.exists(target): self._set_preview(target)
                else: self._toast("파일 없음")
                return
            if os.path.exists(self.EDITED_DONE): self._set_preview(self.EDITED_DONE)
        except Exception:
            pass

    #── 이벤트/리사이즈 ──
    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.preview_img.setGeometry(self.preview.contentsRect())
        if self._overlay.isVisible(): self._overlay.setGeometry(self.rect())
        cur = getattr(self, "_preview_current", None)
        if cur: self._set_preview(cur)

    def _toast(self, text: str, ms: int = 1200) -> None:
        try:
            if not hasattr(self, "_toast_lbl"):
                self._toast_lbl = QLabel(self); self._toast_lbl.setObjectName("toast"); self._toast_lbl.setAttribute(Qt.WA_TransparentForMouseEvents, True)
                self._toast_timer = QTimer(self); self._toast_timer.setSingleShot(True); self._toast_timer.timeout.connect(lambda: self._toast_lbl.hide())
            self._toast_lbl.setText(text)
            bg = "rgba(0,0,0,160)"; fs=int(self.TOK.get("toast_fs",18)); pad=int(self.TOK.get("toast_pad",9)); rad=int(self.TOK.get("toast_radius",6))
            self._toast_lbl.setStyleSheet(f"""
                QLabel#toast {{
                    background: {bg};
                    color: #FFFFFF;
                    padding: {pad}px {pad*2}px;
                    border-radius: {rad}px;
                    font-size: {fs}px;
                }}
            """)
            self._toast_lbl.setAlignment(Qt.AlignCenter); self._toast_lbl.adjustSize()
            g = self.rect(); sz = self._toast_lbl.sizeHint(); margin = int(self.TOK.get("ui_bottom_gap",12))
            x=(g.width()-sz.width())//2; y=g.height()-sz.height()-margin-int(self.TOK.get("toast_offset_up",0)); y = 0 if y<0 else y
            self._toast_lbl.setGeometry(x, y, sz.width(), sz.height()); self._toast_lbl.show(); self._toast_lbl.raise_(); self._toast_timer.start(int(ms))
        except Exception as e:
            _log(f"toast err: {e}")

    def before_enter(self, session) -> bool:
        self.session = session or {}
        try:
            # 처음 진입: 이전/다음 모두 비활성
            self.set_prev_enabled(False)
            self.set_next_enabled(False)
            #self.set_next_mode(1)
        except Exception:
            pass
        self._apply_preview_size()
        QTimer.singleShot(0, self._start_ai_origin_build)
        return True

    # ======================= PATCH: PS auto-quit on pipeline done =======================
# 붙여넣기 위치: app/pages/print_view.py 파일 맨 끝

import os, subprocess, threading, time
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

def _ps_running() -> bool:
    """Photoshop.exe 프로세스 존재 여부"""
    if os.name != "nt":
        return False
    try:
        p = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq Photoshop.exe", "/FO", "CSV", "/NH"],
            capture_output=True, text=True, creationflags=CREATE_NO_WINDOW
        )
        return "Photoshop.exe" in (p.stdout or "")
    except Exception:
        return False

def _ps_close_async(grace_ms: int = 1500, force: bool = True) -> None:
    """
    1) 창 닫기 요청(정상 종료) → grace_ms 대기 → 2) 아직 살아있으면 강제 종료(taskkill /F).
    비동기 스레드로 실행.
    """
    if os.name != "nt":
        return
    def _run():
        # 정상 종료 요청
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive",
                 "Get-Process -Name Photoshop -ErrorAction SilentlyContinue "
                 "| ForEach-Object { $_.CloseMainWindow() | Out-Null }"],
                creationflags=CREATE_NO_WINDOW
            )
        except Exception as e:
            try: _log(f"ps-close: close request err: {e}")
            except Exception: pass

        time.sleep(max(0, grace_ms) / 1000.0)

        # 강제 종료(여전히 실행중이면)
        if force and _ps_running():
            try:
                subprocess.run(
                    ["taskkill", "/IM", "Photoshop.exe", "/T", "/F"],
                    creationflags=CREATE_NO_WINDOW
                )
                try: _log("ps-close: taskkill /F issued")
                except Exception: pass
            except Exception as e:
                try: _log(f"ps-close: taskkill err: {e}")
                except Exception: pass

    threading.Thread(target=_run, daemon=True).start()

# --- 기존 pipeline_done 보존 후 후킹 ---
try:
    _orig_pipeline_done = getattr(PrintViewPage, "_pipeline_done")
except Exception:
    _orig_pipeline_done = None

def _patched_pipeline_done(self, *args, **kwargs):
    # 원래 동작 먼저 수행(오버레이 종료, Next 활성화 등)
    if _orig_pipeline_done:
        try:
            _orig_pipeline_done(self, *args, **kwargs)
        except Exception:
            pass
    # PS 종료 트리거
    try:
        _ps_close_async(grace_ms=1500, force=True)
    except Exception as e:
        try: _log(f"ps-close dispatch err: {e}")
        except Exception: pass

try:
    PrintViewPage._pipeline_done = _patched_pipeline_done
except Exception:
    pass
# ======================= /PATCH =======================
