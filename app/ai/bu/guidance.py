# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Dict, Any, Tuple, Optional
from app.ai.guidance import normalize_yaw_degrees
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
        # 입력 소스: 'sdk' | 'file' (yaw 미러 보정)
        self._src: str = 'file'

    # 입력 소스를 설정한다.
    def set_input_source(self, source: str) -> None:
        """yaw 정규화를 위한 입력 소스를 설정한다('sdk' 또는 'file')."""
        try:
            s = str(source).strip().lower()
            if s in ('sdk', 'file'):
                self._src = s
        except Exception:
            pass
        self._green_since_ms: int = 0  # OK 유지 시작 시각(ms)

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

        # 검출 호출(예외 흡수)
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

        # 2 Hz 갱신(EMA/문구)
        if ts_ms - self._last_ts >= self.rate_ms:
            self._last_ts = ts_ms
            self._ema = self._ema_merge(self._ema, raw, self.alpha)
            self._last_badges = self.decide_message(self._ema, payload)

        # ───────── All-Green 0.8s Gate ─────────
        ok_now = bool(self._ema.get("ok_all", 0.0) >= 0.5)
        if ok_now:
            if self._green_since_ms == 0:
                self._green_since_ms = ts_ms
        else:
            self._green_since_ms = 0
        ready = ok_now and (self._green_since_ms > 0) and ((ts_ms - self._green_since_ms) >= 800)

        # ready 플래그를 메트릭 사본에 포함해 돌려준다
        metrics_out = dict(self._ema)
        metrics_out["ready"] = 1.0 if ready else 0.0

        return payload, dict(self._last_badges), metrics_out

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
            # Yaw 정규화 적용
            m["yaw_deg"] = normalize_yaw_degrees(yaw, getattr(self, '_src', 'file'))
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
