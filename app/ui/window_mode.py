# app/ui/window_mode.py
# -*- coding: utf-8 -*-
#─────────────────────────────────────────────
#  윈도우 모드 결정/적용 (9:16, 창/전체화면, 작업표시줄 무시)
#─────────────────────────────────────────────
from __future__ import annotations
from dataclasses import dataclass
from typing import Tuple
from PySide6.QtCore import QRect, Qt

#─────────────────────────────────────────────
#  데이터 구조: 윈도우 모드 결과
#─────────────────────────────────────────────
@dataclass
class WindowModeInfo:
    tier: str                 # FHD/QHD/UHD
    fullscreen: bool          # 전체화면 여부
    req_w: int                # 해당 tier의 요구 폭(9:16)
    req_h: int                # 해당 tier의 요구 높이
    screen_w: int             # 실제 스크린 폭
    screen_h: int             # 실제 스크린 높이
    target_w: int             # 창모드일 때 적용 폭 (fullscreen이면 screen_w와 무관)
    target_h: int             # 창모드일 때 적용 높이
    pos: Tuple[int, int]      # 창모드일 때 좌상단 위치(x, y)

#─────────────────────────────────────────────
#  상수: 티어별 요구 해상도(9:16)
#─────────────────────────────────────────────
TIERS = {
    "FHD": {"h": 1920, "w": 1080},
    "QHD": {"h": 2560, "w": 1440},
    "UHD": {"h": 3840, "w": 2160},
}

# 기능: 근사 비교(허용 오차)
def _near(v: int, target: int, tol: int) -> bool:
    return abs(v - target) <= tol

# 기능: 9:16 폭 계산
def _w_from_h(h: int) -> int:
    return int(round(h * 9 / 16))

#─────────────────────────────────────────────
#  모드 결정: 스크린 지오메트리 기준 1회 계산
#─────────────────────────────────────────────
def decide_window_mode(geo: QRect, avail: QRect, tol: int = 8) -> WindowModeInfo | None:
    """
    - 역할: 화면 높이 기준으로 FHD/QHD/UHD tier와 창/전체화면 모드를 결정한다.
    - 정책: 작업표시줄 무시(geometry 기준 중앙 배치), 재평가 없음.
    - 실패: 최소 요구 폭 미만이면 None 반환(상위에서 종료/안내 처리)
    """
    sw, sh = geo.width(), geo.height()

    # 티어/전체화면 판정
    if sh >= TIERS["UHD"]["h"] - tol:
        tier = "UHD"
        fullscreen = _near(sh, TIERS["UHD"]["h"], tol)
    elif sh >= TIERS["QHD"]["h"]:
        tier = "QHD"
        fullscreen = _near(sh, TIERS["QHD"]["h"], tol)
    elif sh >= TIERS["FHD"]["h"]:
        tier = "FHD"
        fullscreen = _near(sh, TIERS["FHD"]["h"], tol)
    else:
        return None

    req_w = TIERS[tier]["w"]
    req_h = TIERS[tier]["h"]

    # 최소 폭 미달 시 실패
    if sw < req_w - tol:
        return None

    if fullscreen:
        # 전체화면 모드: target/pos는 의미 없음(호출부에서 showFullScreen)
        return WindowModeInfo(tier, True, req_w, req_h, sw, sh, 0, 0, (0, 0))

    # 창모드: 화면 전체(geometry) 기준 중앙 배치, 9:16 유지
    target_h = min(req_h, sh)
    target_w = _w_from_h(target_h)
    if target_w > sw:
        target_w = sw
        target_h = int(round(target_w * 16 / 9))

    x = geo.x() + (sw - target_w) // 2
    y = geo.y() + (sh - target_h) // 2
    return WindowModeInfo(tier, False, req_w, req_h, sw, sh, target_w, target_h, (x, y))

#─────────────────────────────────────────────
#  모드 적용: MainWindow에 플래그/크기 반영
#─────────────────────────────────────────────
def apply_window_mode(win, info: WindowModeInfo):
    """
    - 역할: 프레임 제거 + 항상 위 + (전체화면 또는 창모드 크기/위치 고정)
    - 수정로그: 최초 도입
    """
    # 프레임 제거 + 항상 위
    win.setWindowFlag(Qt.FramelessWindowHint, True)
    win.setWindowFlag(Qt.WindowStaysOnTopHint, True)

    if info.fullscreen:
        win.showFullScreen()
        return

    # 창모드 고정 크기/위치
    win.setFixedSize(info.target_w, info.target_h)
    x, y = info.pos
    win.move(x, y)
    win.show()
