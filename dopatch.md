# dopatch.md

> 목적: `control_camera.py`, `control_camera_sdk.py`, `crsdk_pybridge.py`의 연결 안정성·저장 경로 일관성·반환 타입·성능 이슈를 한 번에 수정한다.
> 적용 방법: 아래 PR 가이드 또는 Codex CLI 지시문을 사용.

---

## 1) 변경 요약

### A. `control_camera.py`
- 최신 핸들로 종료 처리: finally 블록에서 내부 필드 `_h` 대신 공개 속성 `h` 사용.
- 명령 만료(expiry): 호출자 타임아웃 뒤 큐에 남은 명령이 지연 실행되지 않도록 만료 시각 체크.
- 모노토닉 시계 사용: time.time() → time.monotonic()으로 간격·백오프·keepalive 판정.
- 불필요한 바이트 복사 제거: get_lv_image 반환이 이미 bytes면 재복사 금지.
- keepalive 최소화: need==0 상태가 일정 시간 지속될 때만 enable_liveview(True) 호출.

### B. `control_camera_sdk.py`
- 경로 인코딩 일치: Windows는 'mbcs', 그 외는 'utf-8'로 set_download_dir 인코딩.
- SaveInfo 동시 설정: 카메라 저장모드(Host) + PC 다운로드 경로를 함께 설정.
- 촬영 반환 타입 통일: shoot_one()을 정수 rc 반환으로 변경(0=성공).
- print 제거: 모듈 로거 사용.

### C. `crsdk_pybridge.py`
- USB 시리얼 직접 연결 바인딩 추가: connect_usb_serial(serial).

---

## 2) 패치(코드 diff)

### 2.1 `control_camera.py`

```patch
*** Begin Patchset ***

*** Update File: control_camera.py
@@
-                try:
-                    h2 = getattr(self._b, "_h", None)
+                try:
+                    # 최신 핸들 사용: 재연결 후 내부 필드가 바뀔 수 있으므로 공개 속성 'h' 참조
+                    h2 = getattr(self._b, "h", None)
                 if h2 and getattr(h2, "value", None):
                     try:
                         enable_liveview(h2, False)
                     except Exception:
                         pass
@@
-        evt = threading.Event()
-        box: Dict[str, Any] = {"evt": evt, "res": default}
+        evt = threading.Event()
+        box: Dict[str, Any] = {"evt": evt, "res": default}
+        # 호출자 타임아웃 이후 늦게 실행되는 부작용을 막기 위한 만료 시각
+        try:
+            import time as _t
+            cmd["expires_at"] = _t.monotonic() + max(0.01, float(timeout_s))
+        except Exception:
+            cmd["expires_at"] = None
         cmd["_box"] = box
         try:
             self._q.put(cmd, timeout=0.1)
         except Exception:
             return default
         ok = evt.wait(timeout=max(0.01, float(timeout_s)))
         return box.get("res", default) if ok else default
@@
-                            box = cmd.get("_box") or {}
+                            box = cmd.get("_box") or {}
+                            # 만료 검증: 만료된 명령은 실행하지 않고 완료만 통지
+                            try:
+                                import time as _t
+                                exp = cmd.get("expires_at", None)
+                                if exp is not None and _t.monotonic() > float(exp):
+                                    if isinstance(box.get("evt"), threading.Event):
+                                        box["res"] = box.get("res", None)
+                                        box["evt"].set()
+                                    continue
+                            except Exception:
+                                pass
@@
-                last_need_ts = time.time()
-                last_frame_ts = time.time()
+                # 시스템 시간 변경의 영향을 받지 않도록 모노토닉 시계 사용
+                last_need_ts = time.monotonic()
+                last_frame_ts = time.monotonic()
@@
-                    now = time.time()
+                    now = time.monotonic()
@@
-                    try:
-                        data = bytes(get_lv_image(h) or b"")
+                    try:
+                        _img = get_lv_image(h)
+                        data = _img if isinstance(_img, (bytes, bytearray)) else bytes(_img or b"")
                     except Exception:
                         data = b""
@@
-                # keepalive
-                if now - self._last_keep >= 2.0:
-                    try:
-                        enable_liveview(h, True)
-                    except Exception:
-                        pass
-                    self._last_keep = now
+                # keepalive 최적화: need 신호가 0으로 일정 시간 지속될 때만 호출
+                if now - self._last_keep >= 2.0 and (need == 0):
+                    try:
+                        enable_liveview(h, True)
+                    except Exception:
+                        pass
+                    self._last_keep = now
*** End Patch
```

### 2.2 `control_camera_sdk.py`

```patch
*** Begin Patchset ***

*** Update File: control_camera_sdk.py
@@
-def _safe_set_download_dir(path: str) -> int:
-    """다운로드 경로 설정(심볼 부재 시 -1 반환)."""
-    if not '_HAS_SAVE_DIR' in globals() or not _HAS_SAVE_DIR:
-        return -1
-    try:
-        return int(_d.crsdk_set_download_dir(path.encode("utf-8")))
-    except Exception:
-        return -1
+def _safe_set_download_dir(path: str) -> int:
+    """다운로드 경로 설정(심볼 부재 시 -1 반환)."""
+    if not '_HAS_SAVE_DIR' in globals() or not _HAS_SAVE_DIR:
+        return -1
+    try:
+        enc = "mbcs" if os.name == "nt" else "utf-8"
+        return int(_d.crsdk_set_download_dir(path.encode(enc, errors="ignore")))
+    except Exception:
+        return -1
@@
-    def shoot_one(self) -> bool:
-        """정지 이미지를 1회 촬영한다."""
-        if not self.h.value: return False
-        return _d.crsdk_shoot_one(self.h, 0) == 0
+    def shoot_one(self) -> int:
+        """정지 이미지를 1회 촬영한다. 정수 rc 반환(0=성공)."""
+        if not self.h.value:
+            return -1
+        try:
+            return int(_d.crsdk_shoot_one(self.h, 0))
+        except Exception:
+            return -1
@@
-    def set_download_dir(self, path: str) -> bool:
-        """다운로드 저장 경로를 설정한다(심볼 부재 시 False)."""
-        rc = -1
-        try:
-            rc = _safe_set_download_dir(path)
-        except Exception:
-            rc = -1
-        print(f"[SDK] set_download_dir rc={rc} path={path}")
-        return rc == 0
+    def set_download_dir(self, path: str) -> bool:
+        """다운로드 저장 경로 + 카메라 SaveInfo(Host) 동시 설정."""
+        rc = -1
+        try:
+            rc = _safe_set_download_dir(path)
+        except Exception:
+            rc = -1
+        # 가능하면 카메라 저장모드도 Host로 지정
+        try:
+            _d.crsdk_set_save_info.argtypes = [C.c_void_p, C.c_int, C.c_char_p, C.c_char_p]
+            _d.crsdk_set_save_info.restype  = C.c_int
+            SAVE_MODE_HOST = 2
+            enc = "mbcs" if os.name == "nt" else "utf-8"
+            _ = int(_d.crsdk_set_save_info(self.h, SAVE_MODE_HOST, path.encode(enc, "ignore"), None))
+        except Exception:
+            pass
+        _log.info("[SDK] set_download_dir rc=%s path=%s", rc, path)
+        return rc == 0
@@
-        print(f"[SDK] AF rc={rc}")
+        _log.info("[SDK] AF rc=%s", rc)
@@
-        print(f"[SDK] AWB rc={rc}")
+        _log.info("[SDK] AWB rc=%s", rc)
*** End Patch
```

### 2.3 `crsdk_pybridge.py`

```patch
*** Begin Patchset ***

*** Update File: crsdk_pybridge.py
@@
 if _sym("crsdk_connect_first"):      _d.crsdk_connect_first.argtypes = [POINTER(c_void_p)]; _d.crsdk_connect_first.restype = c_int
+if _sym("crsdk_connect_usb_serial"):
+    _d.crsdk_connect_usb_serial.argtypes = [c_char_p, POINTER(c_void_p)]
+    _d.crsdk_connect_usb_serial.restype  = c_int
@@
 def connect_first() -> c_void_p | None:
@@
     return out if rc == 0 and out.value else None
+
+def connect_usb_serial(serial: str) -> c_void_p | None:
+    """USB 시리얼로 직접 연결."""
+    f = _sym("crsdk_connect_usb_serial")
+    if not f: return None
+    out = c_void_p()
+    rc = int(f(serial.encode("ascii", errors="ignore"), C.byref(out)))
+    return out if rc == 0 and out.value else None
*** End Patchset
```

---

## 3) 테스트 시나리오

1) 연결·라이브뷰: connect_first → start_liveview → 3초 관찰. keepalive는 need==0일 때만 주기 호출.
2) 저장 경로 재적용: set_save_dir("C:\\Test\\Captures") → USB 분리/재연결 → reapply 로그 확인.
3) 촬영/AF/AWB: shoot_one(), one_shot_af(), one_shot_awb() 결과 rc 로깅 확인.
4) 명령 만료: timeout_s가 작은 명령을 다수 enqueue 후 지연 실행 없음 확인.
5) USB 시리얼 연결: connect_usb_serial("YOUR_SERIAL") 테스트.

---

## 4) GitHub에서의 할 일

- 이슈: 핸들 불일치, 만료, 모노토닉, 인코딩, SaveInfo+DownloadDir, rc 정수화, 로깅 일원화.
- PR: PR‑1(안정화) → PR‑2(저장정책) → PR‑3(저수준 유틸).
- 문서: runtime.md(타이머·keepalive), storage.md(SaveInfo/DownloadDir).
