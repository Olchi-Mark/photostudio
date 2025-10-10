# app/ui/scale.py
# -*- coding: utf-8 -*-
#─────────────────────────────────────────────
#  스케일 유틸: 티어/정규높이 기반 스케일 + 호환 API
#─────────────────────────────────────────────
from __future__ import annotations

#─────────────────────────────────────────────
#  내부 상수/매핑
#─────────────────────────────────────────────
_TIER_INFO = {
    "FHD": {"req_h": 1920, "grid": 3},
    "QHD": {"req_h": 2560, "grid": 4},
    "UHD": {"req_h": 3840, "grid": 6},
}

#─────────────────────────────────────────────
#  정규높이 기반 스케일(권장)
#─────────────────────────────────────────────
# 역할: FHD 기준 px → req_h(1920/2560/3840) 기준으로 스케일 + 스냅
# 변경로그: 신규 도입
def scale_px_by_reqh(base_fhd_px: int, req_h: int, snap_policy: str = "ceil") -> int:
    """
    - 1px : 1:1:2 (FHD/QHD/UHD)
    - 2px : 2:3:4 (FHD/QHD/UHD)
    - 기타: FHD=3의 배수 설계, QHD/UHD는 3:4:6 배수로 스냅
    """
    # ─ 예외 우선 처리 ─
    if base_fhd_px == 1:
        return 2 if req_h >= 3840 else 1
    if base_fhd_px == 2:
        if req_h >= 3840:
            return 4
        if req_h >= 2560:
            return 3
        return 2

    # ─ 일반 규칙 ─
    scale = max(1.0, req_h / 1920.0)  # 왜: FHD=1.0, QHD≈1.333, UHD=2.0
    grid  = 6 if req_h >= 3840 else (4 if req_h >= 2560 else 3)
    return _snap(base_fhd_px * scale, grid, snap_policy)

#─────────────────────────────────────────────
#  티어 기반 스케일(가독성↑)
#─────────────────────────────────────────────
# 역할: 티어 문자열(FHD/QHD/UHD)만으로 스케일 계산
# 변경로그: 신규 도입
def scale_px_by_tier(base_fhd_px: int, tier: str, snap_policy: str = "ceil") -> int:
    info = _TIER_INFO.get((tier or "").upper())
    if not info:
        info = _TIER_INFO["FHD"]  # 알 수 없는 티어면 FHD로 폴백
    return scale_px_by_reqh(base_fhd_px, info["req_h"], snap_policy)

#─────────────────────────────────────────────
#  (구) screen_h 기반 호환 API
#─────────────────────────────────────────────
# 역할: 기존 screen_h 호출을 유지하되 내부적으로 정규높이로 스냅 위임
# 변경로그: 내부 위임으로 전환
def scale_px(base_fhd_px: int, screen_h: int, snap_policy: str = "ceil") -> int:
    # 정규 높이 스냅(1920/2560/3840)
    req_h = 3840 if screen_h >= 3200 else (2560 if screen_h >= 2240 else 1920)
    return scale_px_by_reqh(base_fhd_px, req_h, snap_policy)

#─────────────────────────────────────────────
#  내부: 스냅 함수
#─────────────────────────────────────────────
# 기능 시작: 값 v를 g 배수로 스냅
def _snap(v: float, g: int, policy: str) -> int:
    if g <= 1:
        return int(round(v))
    q = v / g
    if policy == "floor":
        return int(q) * g
    if policy == "round":
        return int(round(q)) * g
    # default: ceil(가독성 우선)
    return (int(q) + (0 if q.is_integer() else 1)) * g

#─────────────────────────────────────────────
#  수정 로그
#─────────────────────────────────────────────
"""
- v0.2: tier/req_h 기반 API 추가, screen_h 기반은 내부 위임으로 호환 유지
- v0.1: 초기 screen_h 기반 스케일 함수 추가
"""
