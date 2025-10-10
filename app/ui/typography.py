# app/ui/typography.py
# -*- coding: utf-8 -*-
#─────────────────────────────────────────────
#  타이포/보더 스케일 토큰 생성 (req_h 기준)
#─────────────────────────────────────────────
from __future__ import annotations
import json, os
from typing import Dict, Any
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont

from app.ui.scale import scale_px_by_reqh

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

# 기능 시작: grid 결정(FHD=3, QHD=4, UHD=6)
def _grid(req_h: int) -> int:
    return 6 if req_h >= 3840 else (4 if req_h >= 2560 else 3)

#─────────────────────────────────────────────
#  내부: 크롬(스텝바/푸터/마진) 토큰 생성
#─────────────────────────────────────────────
# 기능 시작: req_h/scale/snap을 반영해 stepbar/footer/gap/margin 산출
def _build_chrome(req_h: int, ui_section: dict, snap_policy: str) -> dict:
    # FHD 기준 기본값(필수 3의 배수)
    base = {"stepbar_h": 66, "footer_h": 96, "gap_top": 30, "side_margin": 90}
    # settings.ui.chrome가 있으면 숫자 항목만 우선 반영
    chrome_cfg = (ui_section or {}).get("chrome", {}) if isinstance(ui_section, dict) else {}
    if isinstance(chrome_cfg, dict):
        for k, v in chrome_cfg.items():
            if k in base and isinstance(v, (int, float)):
                base[k] = int(v)
    g = _grid(req_h)
    scale = max(1.0, req_h / 1920.0)
    snapped = {k: _snap(v * scale, g, snap_policy) for k, v in base.items()}
    snapped["gap_bottom"] = snapped["gap_top"]  # 하단 갭은 동일 적용
    return snapped

#─────────────────────────────────────────────
#  apply_typography_from_settings
#─────────────────────────────────────────────
# 역할: settings.json(FHD 기준) → req_h(1920/2560/3840) 기준으로 스케일/스냅하여 토큰 생성
# 변경로그:
# - v0.1: 최초 구현(글로벌 앱 프로퍼티에 토큰 저장, 기본 폰트 크기 적용)

def apply_typography_from_settings(settings_path: str, req_h: int) -> Dict[str, Any]:
    """
    - 입력: settings.json 경로, 정규 높이(req_h)
    - 처리: FHD 기준 사이즈를 req_h 배율로 스냅해 토큰 생성
    - 출력: 생성된 토큰 딕셔너리(앱 프로퍼티 "TYPO_TOKENS"에도 저장)
    """
    app = QApplication.instance()

    # 1) 설정 로드(없으면 기본값)
    data: Dict[str, Any] = {}
    if settings_path and os.path.exists(settings_path):
        try:
            with open(settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            data = {}

    ui = data.get("ui", {})
    snap_policy = ui.get("snap_policy", "ceil")  # ceil/floor/round

    # FHD 기준 타이포 기본값(픽셀)
    base_typo_fhd = ui.get("typography_fhd", {
        "label": 15,
        "body": 18,
        "h6": 21,
        "h5": 24,
        "h4": 27,
        "h3": 30,
        "h2": 36,
        "h1": 45,
    })

    # FHD 기준 보더 기본값(픽셀)
    base_borders_fhd = ui.get("borders_fhd", {
        "hairline": 1,  # 예외 규칙 적용(1:1:2)
        "thin": 2,      # 예외 규칙 적용(2:3:4)
        "normal": 3,
        "bold": 6,
    })

    g = _grid(req_h)
    scale = max(1.0, req_h / 1920.0)

    # 2) 타이포 스케일링(그리드 스냅)
    typo_px: Dict[str, int] = {}
    for role, base_px in base_typo_fhd.items():
        # 주의: 1/2px 예외는 타이포엔 거의 없지만, 일관성을 위해 동일 스냅
        v = base_px * scale
        typo_px[role] = _snap(v, g, snap_policy)

    # 3) 보더 스케일링(예외 규칙은 유틸로 적용)
    borders_px: Dict[str, int] = {}
    for key, base_px in base_borders_fhd.items():
        borders_px[key] = scale_px_by_reqh(base_px, req_h, snap_policy)

    # 4) 앱 전역 토큰 저장(테마/QSS에서 참조 가능)
    tokens = {
        "req_h": req_h,
        "grid": g,
        "scale": scale,
        "snap_policy": snap_policy,
        "typography": typo_px,
        "borders": borders_px,
        "chrome": _build_chrome(req_h, ui, snap_policy),  # ← 전역 크롬 규격 주입
    }
    if app is not None:
        app.setProperty("TYPO_TOKENS", tokens)

        # 기본 폰트 크기만 전역 적용(패밀리는 테마/폰트 모듈에서 처리)
        try:
            f = app.font() if app.font() else QFont()
            f.setPixelSize(int(typo_px.get("body", 18)))  # 왜: 본문을 기준 크기로 사용
            app.setFont(f)
        except Exception:
            pass

    return tokens

#─────────────────────────────────────────────
#  수정 로그
#─────────────────────────────────────────────
"""
- v0.2: chrome 토큰(stepbar/footer/gap_top/side_margin/gap_bottom) 생성·주입
- v0.1: 최초 구현 — req_h 기반 스케일/스냅, 앱 전역 프로퍼티 저장, 기본 폰트 크기 적용
"""
