"""CameraControl: ??⑤㈇??癲????嶺????????됱뎽??잙갭큔筌???熬곣뫖利??????ш끽維뽳㎘?琉? ????쑩딂キ?

???꿔꺂??袁ㅻ븶???? ???뚯????CRSDKBridge(????쇰뮚?????繹먮냱????????)????醫딆┫?????
??濚밸Ŧ?????⑥ル츥???熬곣뫖利??????ш끽維뽳㎘?琉?on_frame_bytes)?????곌떽釉붾???β뼯爰귨㎘??????????怨몄벂??????紐꾩죩????猿롫쭡?????ㅻ쿋????嶺뚮㉡???
????????嶺뚮ㅏ嫄???? ?癲ル슢?뤸뤃????????????꾣뤃??CRSDKBridge?????녾컯嶺???export ??嶺뚮㉡???
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Optional, Dict, Any
import queue


from .control_camera_sdk import CRSDKBridge, enable_liveview, get_lv_info, get_lv_image
from .crsdk_pybridge import error_name as _errname

_log = logging.getLogger("CAM")


class CameraControl:
    """??⑤㈇??癲??????뮻??癲ル슢??蹂좊쨨????援온??+ ??濚밸Ŧ?????⑥ル츥???熬곣뫖利??????ш끽維뽳㎘?琉??????

    - ????쇰뮚?????繹먮냱?????????? ???? CRSDKBridge??????썹땟?④덩???嶺뚮ㅏ嫄??????繹먮냱??????)
    - ??濚밸Ŧ?????⑥ル츥????????????怨몄벂??嶺?獄??get_lv_info/get_lv_image ??on_frame_bytes ?癲ル슢????
    - ????썹땟????汝??吏???1Hz??????寃??, keepalive??2?????녿뮝??怨룸렓???    """

    def __init__(self) -> None:

        self._b = CRSDKBridge()

        self._th: Optional[threading.Thread] = None
        self._stop = threading.Event()
        self._cb: Optional[Callable[[bytes, int, Dict[str, Any]], None]] = None
        self._ms = 33
        self._last_log_ms = 0
        self._last_keep = 0.0
        self._last_dir: Optional[str] = None

        # 내부 명령 처리 큐
        self._q: "queue.Queue[Dict[str, Any]]" = queue.Queue()



    def connect_first(self) -> bool:
        """??⑤㈇??癲????????????쇰뮚?????嶺뚮㉡????嶺뚮㉡???USB_SERIAL ???????얠?)."""
        return bool(self._b.connect_first())

    def disconnect(self) -> None:
        """??⑤㈇??癲??????쇰뮚???????띻샴癲??嶺뚮㉡???"""
        try:
            self.stop_liveview()
        except Exception:
            pass
        self._b.disconnect()

    def set_save_dir(self, path: str, retries: int = 3, delay_ms: int = 200, timeout_s: float = 3.0) -> bool:
        """?????嚥▲굧???뚪뜮?熬곣벀嫄????繹먮냱???嶺뚮㉡?????????꿔꺂??????????덊떀, ?????????."""
        self._last_dir = str(path or "") or None
        cmd: Dict[str, Any] = {"op": "set_save_dir", "path": str(path), "retries": int(retries), "delay_ms": int(delay_ms)}
        return bool(self._enqueue_cmd(cmd, timeout_s=timeout_s, default=False))

    def shoot_one(self, timeout_s: float = 4.0) -> int:
        """????뮻????????????됰Ŋ????嶺뚮㉡?????????꿔꺂??????????덊떀, ??????썹땟?????s)."""
        cmd: Dict[str, Any] = {"op": "shoot_one"}
        return int(self._enqueue_cmd(cmd, timeout_s=timeout_s, default=-1))

    def get_last_saved_jpeg(self, timeout_s: float = 2.0) -> Optional[str]:
        """?꿔꺂?????????逆곷틳爰덂퐲?JPEG ?嚥▲굧???뚪뜮?熬곣벀嫄???됰슦?????嶺뚮㉡?????????꿔꺂??????????덊떀)."""
        cmd: Dict[str, Any] = {"op": "last_saved"}
        return self._enqueue_cmd(cmd, timeout_s=timeout_s, default=None)

    def one_shot_af(self, timeout_s: float = 3.0) -> Optional[int]:
        """?????AF???????덊떀??嶺뚮㉡?????????꿔꺂??????????덊떀)."""
        cmd: Dict[str, Any] = {"op": "af"}
        return self._enqueue_cmd(cmd, timeout_s=timeout_s, default=None)

    def one_shot_awb(self, timeout_s: float = 3.0) -> Optional[int]:
        """?????AWB???????덊떀??嶺뚮㉡?????????꿔꺂??????????덊떀)."""
        cmd: Dict[str, Any] = {"op": "awb"}
        return self._enqueue_cmd(cmd, timeout_s=timeout_s, default=None)


    def _enqueue_cmd(self, cmd: Dict[str, Any], timeout_s: float, default: Any):
        """????????????影?れ쉠???? ?鶯ㅺ동????궰??嚥▲굧?????ル벥嫄????뚯????β뼯猷????살퓢??"""
        evt = threading.Event()
        box: Dict[str, Any] = {"evt": evt, "res": default}
        cmd["_box"] = box
        try:
            self._q.put(cmd, timeout=0.1)
        except Exception:
            return default
        ok = evt.wait(timeout=max(0.01, float(timeout_s)))
        return box.get("res", default) if ok else default


    def start_liveview(self, on_frame_bytes: Callable[[bytes, int, Dict[str, Any]], None], frame_interval_ms: int = 33) -> bool:
        """??濚밸Ŧ?????⑥ル츥??????볥궚?????嶺뚮??ｆ뤃???野껊뿈???熬곣뫖利??????ш끽維뽳㎘?琉???癲ル슢?????嶺뚮㉡???

        - ????썹땟?????醫딆┣??醫딅?? ???뚯????33ms(??0fps), ?꿔꺂????쭍??16ms ??????        - keepalive: 2?????녿뮝??怨룸렓?enable_liveview(1) ??        - ??ш끽維뽳㎘?琉????繹먮굝?????嶺뚮Ŋ???????影??낟??
        """
        self.stop_liveview()
        self._cb = on_frame_bytes
        try:
            self._ms = max(16, int(frame_interval_ms))
        except Exception:
            self._ms = 33
        self._stop.clear()
        self._last_log_ms = 0
        self._last_keep = 0.0


        try:
            h0 = getattr(self._b, "h", None)
            if not h0 or not getattr(h0, "value", None):
                self._b.connect_first()
        except Exception:
            pass
        h0 = getattr(self._b, "h", None)
        if not h0 or not getattr(h0, "value", None):

            try:
                self._b.connect_first()
            except Exception:
                pass
            h0 = getattr(self._b, "h", None)
            if not h0 or not getattr(h0, "value", None):
                try:
                    _log.info("[CAM] no handle; start_liveview aborted (pre)")
                except Exception:
                    pass
                return False

        try:
            os.environ.setdefault("CRSDK_FORCE_ENUM", "1")
            try:
                if os.environ.get("CRSDK_FORCE_ENUM", "1").strip().lower() in ("1", "true", "on"):
                    os.environ.pop("CRSDK_USB_SERIAL", None)
            except Exception:
                pass
        except Exception:
            pass

        def _run():
            try:

                try:
                    if not getattr(self._b, "h", None) or not getattr(getattr(self._b, "h", None), "value", None):
                        self._b.connect_first()
                except Exception:
                    pass
                h = getattr(self._b, "h", None)
                if not h or not getattr(h, "value", None):
                    _log.info("[CAM] no handle; start_liveview aborted")
                    return


                try:
                    rc_en = int(enable_liveview(h, True))
                    _log.info("[CAM] lv_on rc=%s", rc_en)
                except Exception:
                    rc_en = -1
                time.sleep(0.150)

                gap = self._ms / 1000.0
                need0 = 0
                last_need_ts = time.time()

                backoff = 0.5
                reapply_done = False
                last_frame_ts = time.time()
                while not self._stop.is_set():

                    try:
                        while True:
                            cmd = self._q.get_nowait()
                            box = cmd.get("_box") or {}
                            op = str(cmd.get("op", ""))
                            res = None
                            if op == "set_save_dir":
                                path = str(cmd.get("path", ""))
                                retries = int(cmd.get("retries", 3))
                                delay_ms = int(cmd.get("delay_ms", 200))
                                ok = False
                                for i in range(max(0, retries) + 1):
                                    try:
                                        rc = self._b.set_save_dir(path)
                                    except Exception:
                                        rc = -1
                                    ok = (rc == 0 or rc is True)
                                    if ok:
                                        _log.info("[SAVE] dir=%s rc=%s", path, rc)
                                        break
                                    if i < retries:
                                        time.sleep(max(0, delay_ms) / 1000.0)
                                if not ok:
                                    _log.error("[SAVE] set_save_dir failed dir=%s", path)
                                res = bool(ok)
                            elif op == "shoot_one":
                                try:
                                    rc = int(self._b.shoot_one())
                                except Exception:
                                    rc = -1
                                try:
                                    _log.info("[SHOT] rc=%s err=%s", rc, _errname(int(rc)))
                                except Exception:
                                    pass
                                res = int(rc)
                            elif op == "last_saved":
                                try:
                                    res = self._b.get_last_saved_jpeg()
                                except Exception:
                                    res = None
                            elif op == "af":
                                try:
                                    rc = self._b.one_shot_af()
                                except Exception:
                                    rc = None
                                try:
                                    _log.info("[AF] rc=%s", rc)
                                except Exception:
                                    pass
                                res = rc
                            elif op == "awb":
                                try:
                                    rc = self._b.one_shot_awb()
                                except Exception:
                                    rc = None
                                try:
                                    _log.info("[AWB] rc=%s", rc)
                                except Exception:
                                    pass
                                res = rc

                            box["res"] = res
                            evt = box.get("evt")
                            if isinstance(evt, threading.Event):
                                try:
                                    evt.set()
                                except Exception:
                                    pass
                    except queue.Empty:
                        pass

                    now = time.time()
                    if now - self._last_keep > 2.0:
                        try:
                            enable_liveview(h, True)
                        except Exception:
                            pass
                        self._last_keep = now


                    need = 0
                    try:
                        need = int(get_lv_info(h))
                    except Exception:
                        need = 0
                    if need <= 0:
                        if need0 == 0:

                            need0 = 1
                            last_need_ts = now
                        elif (now - last_need_ts) >= 1.0:
                            last_need_ts = now
                            try:
                                _log.info("[CAM] lv_info need=0; recheck")
                            except Exception:
                                pass
                        time.sleep(0.08)

                        if now - last_frame_ts >= 1.2:
                            if self._stop.is_set():
                                break
                            try:
                                _log.info("[CAM] reconnect (need=0) backoff=%.1fs", backoff)
                            except Exception:
                                pass
                            try:
                                try:
                                    enable_liveview(h, False)
                                except Exception:
                                    pass
                                try:
                                    self._b.disconnect()
                                except Exception:
                                    pass
                                ok = bool(self._b.connect_first())
                                h = getattr(self._b, "h", None)
                                if ok and h and getattr(h, "value", None):
                                    try:
                                        enable_liveview(h, True)
                                    except Exception:
                                        pass
                                    time.sleep(0.150)
                                    if (not reapply_done) and self._last_dir:

                                        try:
                                            rc = self._b.set_save_dir(self._last_dir)
                                            _log.info("[SAVE] reapply dir=%s rc=%s", self._last_dir, rc)
                                        except Exception:
                                            pass
                                        reapply_done = True
                                    backoff = 0.5
                                    last_frame_ts = time.time()
                                else:
                                    time.sleep(backoff)
                                    backoff = min(2.0, backoff * 2.0)
                            except Exception:
                                time.sleep(backoff)
                                backoff = min(2.0, backoff * 2.0)
                        continue


                    try:
                        data = bytes(get_lv_image(h) or b"")
                    except Exception:
                        data = b""

                    if data:
                        last_frame_ts = now
                        ts_ms = int(time.time() * 1000)
                        meta: Dict[str, Any] = {"mode": "sdk", "w": None, "h": None}
                        cb = self._cb
                        if cb:
                            try:
                                cb(data, ts_ms, meta)
                            except Exception:
                                _log.exception("[CAM] on_frame_bytes error")


                        try:
                            if ts_ms - int(self._last_log_ms or 0) >= 1000:
                                self._last_log_ms = ts_ms
                                _log.info("[CAM] frame bytes=%s mode=%s", len(data), meta.get("mode", "sdk"))
                        except Exception:
                            pass

                    time.sleep(gap)
            finally:

                try:
                    h2 = getattr(self._b, "_h", None)
                    if h2 and getattr(h2, "value", None):
                        try:
                            enable_liveview(h2, False)
                        except Exception:
                            pass
                except Exception:
                    pass

        self._th = threading.Thread(target=_run, daemon=True)
        try:
            self._th.start()
            return True
        except Exception:
            return False

    def stop_liveview(self) -> None:
        """??濚밸Ŧ?????⑥ル츥??????볥궚???嚥싳쉶瑗??꾧틡???嶺뚮㉡???"""
        self._stop.set()
        t = self._th
        self._th = None
        if t is not None:
            try:
                t.join(timeout=1.0)
            except Exception:
                pass


__all__ = ["CRSDKBridge", "CameraControl"]
