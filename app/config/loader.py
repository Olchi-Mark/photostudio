# -*- coding: utf-8 -*-
# app/config/loader.py — 설정 부트스트랩/저장/리셋/브로드캐스트 유틸 (config_* 접두어)
from __future__ import annotations

#─────────────────────────────────────────────
#  역할 요약
#  - defaults.json 로드 및 사용자 settings.json 보증/로딩
#  - effective = deep_merge(defaults, settings) 계산
#  - 팔레트/토큰을 qApp 전역 프로퍼티에 주입
#  - 저장/초기화/브로드캐스트 유틸 제공
#─────────────────────────────────────────────

import json, os, shutil, tempfile, time
from pathlib import Path
from typing import Any, Dict

from PySide6.QtWidgets import QApplication

#─────────────────────────────────────────────
# 경로 유틸
#─────────────────────────────────────────────

# 설정 파일 기본 앱 이름
_APP_NAME = "PhotoStudio"

#─────────────────────────────────────────────
#  사용자 경로 반환
#─────────────────────────────────────────────
def config_user_settings_path(app_name: str = _APP_NAME) -> Path:
    # 규칙36: 모든 설정은 C:\PhotoBox 고정
    return Path(r"C:\PhotoBox\settings.json")

#─────────────────────────────────────────────
# JSON 로드/저장(원자적)
#─────────────────────────────────────────────

def config_load_json(path: Path) -> Dict[str, Any]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

# 파일을 안전하게 저장: 임시파일에 쓰고 교체
# - 역할: settings.json 저장 시 중간 손상 방지
# - 수정로그: 신규 구현
#─────────────────────────────────────────────
#  원자적 저장
#─────────────────────────────────────────────
def config_save_json_atomic(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)

#─────────────────────────────────────────────
# defaults / settings 로드
#─────────────────────────────────────────────

# defaults.json 탐색(대/소문자 + 확장자 유무 대응)
#─────────────────────────────────────────────
#  defaults 로드
#─────────────────────────────────────────────
def config_load_defaults() -> Dict[str, Any]:
    here = Path(__file__).resolve()
    root = here.parents[2]
    candidates = [
        root / "app" / "config" / "defaults.json",
        root / "App" / "config" / "defaults.json",
        root / "app" / "config" / "defaults",
        root / "App" / "config" / "defaults",
    ]
    for p in candidates:
        data = config_load_json(p)
        if data and isinstance(data, dict) and data.get("ui", {}).get("colors"):
            return data

    # ---- 자가복구: defaults.json이 없으면 최소 템플릿을 생성해서 진행 ----
    DEFAULTS_TEMPLATE: Dict[str, Any] = {
        "schema_version": 1,
        "program_info": {
            "name": "PhotoStudio",
            "brand": "MySweetInterview",
            "version": "1.0.0",
            "changelog": [
                {
                    "version": "1.0.0",
                    "date": "2025-09-01",
                    "notes": ["첫 릴리즈", "환경설정 오버레이 추가", "프린터 기본 설정 반영"],
                }
            ],
        },
        "ui": {
            "snap_policy": "floor",
            "typography_fhd": {"label": 18, "body": 15, "h6": 21, "h5": 27, "h4": 30, "h3": 36, "h2": 45, "h1": 57},
            "borders_fhd": {"hairline": 1, "thin": 2, "normal": 3, "bold": 6},
            "radii_fhd": {"radius": 3, "button": 6, "card": 3},
            "spacing_fhd": {"pad_v": 12, "pad_h": 12, "gap": 12, "checkbox": 15},
            "chrome_fhd": {"stepbar_h": 66, "footer_h": 96, "gap_top": 30, "gap_bottom": 30, "side_margin": 90},
            "colors": {
                "bg": "#FFFFFF", "surface": "#FFFFFF", "card": "#FFFFFF", "border": "#EDEDED",
                "text": "#1A1A1A", "subtext": "#666666",
                "primary": "#FFA9A9", "primary_hover": "#FFB7B7", "primary_active": "#FF9D9D",
                "success": "#2FB573", "warning": "#F2A100", "danger": "#E55454",
                "overlay_08": "rgba(0,0,0,0.08)", "overlay_12": "rgba(0,0,0,0.12)",
            },
            "audio": {"ding_volume": 0.4},
        },
        "flow": {"steps": ["INTRO", "INPUT", "SIZE", "CAPTURE", "PICK", "PREVIEW", "EMAIL", "OUTRO"]},
        "paths": {
            "root": r"C:\PhotoBox",
            "origin": r"C:\PhotoBox\origin_photo.jpg",
            "ai_out": r"C:\PhotoBox\ai_origin_photo.jpg",
            "raw_done": r"C:\PhotoBox\raw.jpg",
            "liquify_done": r"C:\PhotoBox\liquify.jpg",
            "edited_done": r"C:\PhotoBox\edited_photo.jpg",
            "setting_dir": r"C:\PhotoBox\setting",
            "preset_dir": r"C:\PhotoBox\setting\preset",
            "liveview_dir": r"C:\PhotoBox\lv"
        },
        "retention": {"days": 7},
        "input": {"top_guide": "", "bottom_guide": ""},
        "ai": {"rows": [
            {"name": "Raw", "components": ["프리셋01", "프리셋02", "프리셋03"]},
            {"name": "Liquify", "components": ["프리셋04", "프리셋05", "프리셋06"]},
            {"name": "Neural", "components": ["프리셋07", "프리셋08", "프리셋09"]},
            {"name": "Background", "components": ["프리셋10", "프리셋11", "프리셋12"]},
        ]},
        "email": {
            "from_name": "Photo Studio", "from_address": "noreply@example.com",
            "smtp": {"host": "smtp.gmail.com", "port": 587, "tls": True},
            "auth": {"user": "wwha0911@gmail.com", "pass": "cnohsgtpavecnjfw"},
            "customer": {"subject": "증명사진 전송", "body": "사진을 첨부합니다.", "attach": {"lowres": True, "hires": False}},
            "print_manager": {"to": "", "subject": "[출력팀] 신규 촬영 사진 - {date}", "body": "출력 담당자님, 새로운 촬영본이 도착했습니다.", "attach": {"lowres": False, "hires": True}},
            "retouch_manager": {"to": "", "subject": "[보정팀] 보정 작업 요청 - {date}", "body": "보정 담당자님, 새로운 촬영본이 도착했습니다.", "attach": {"lowres": True, "hires": True}},
        },
    }

    target = root / "app" / "config" / "defaults.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    config_save_json_atomic(target, DEFAULTS_TEMPLATE)
    return DEFAULTS_TEMPLATE

# 사용자 settings 로드(없으면 빈 dict)
#─────────────────────────────────────────────
#  settings 로드
#─────────────────────────────────────────────
def config_load_settings(path: Path | None = None) -> Dict[str, Any]:
    path = path or config_user_settings_path()
    return config_load_json(path)

# settings 파일 보증: 없으면 defaults 스냅샷으로 생성
#─────────────────────────────────────────────
#  settings 보증
#─────────────────────────────────────────────
def config_ensure_settings_file(defaults: Dict[str, Any], path: Path | None = None) -> Dict[str, Any]:
    path = path or config_user_settings_path()
    if not path.exists():
        config_save_json_atomic(path, defaults)
        return defaults
    return config_load_settings(path)

#─────────────────────────────────────────────
# 머지/토큰/팔레트
#─────────────────────────────────────────────

# 딥 머지: b가 우선, dict만 재귀적으로 병합
#─────────────────────────────────────────────
#  딥 머지
#─────────────────────────────────────────────
def config_deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(a or {})
    for k, v in (b or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = config_deep_merge(out[k], v)
        else:
            out[k] = v
    return out

# 팔레트 추출: effective.ui.colors
#─────────────────────────────────────────────
#  팔레트 추출
#─────────────────────────────────────────────
def config_extract_palette(effective: Dict[str, Any]) -> Dict[str, Any]:
    ui = effective.get("ui", {}) if isinstance(effective, dict) else {}
    return dict(ui.get("colors", {}))

# 토큰 빌드: FHD 기준값을 tier/req_h에 맞춰 스냅
# - bootstrap 시점에는 req_h/tier가 없을 수 있으므로 scale=1.0로 제한
# - apply_typography_from_settings()가 이후에 실제 req_h로 다시 빌드함
#─────────────────────────────────────────────
#  토큰 빌드
#─────────────────────────────────────────────
def config_build_tokens(ui: Dict[str, Any], tier: str | None = None, req_h: int | None = None) -> Dict[str, Any]:
    typ_fhd = dict(ui.get("typography_fhd", {}))
    borders = dict(ui.get("borders_fhd", {}))
    spacing = dict(ui.get("spacing_fhd", {}))
    radii   = dict(ui.get("radii_fhd",   {}))

    # scale: 부트 단계에서는 1.0 (타이포 적용 단계에서 재계산)
    scale = 1.0
    tokens = {
        "typography": typ_fhd,
        "borders": borders,
        "spacing": spacing,
        "radii": radii,
        "req_h": req_h,
        "scale": scale,
    }
    if tier:
        tokens["tier"] = tier
    return tokens

# qApp 프로퍼티에 주입
#─────────────────────────────────────────────
#  전역 주입
#─────────────────────────────────────────────
def config_push_globals(palette: Dict[str, Any], tokens: Dict[str, Any]) -> None:
    app = QApplication.instance()
    if not app:
        return
    app.setProperty("THEME_COLORS", palette or {})
    app.setProperty("TYPO_TOKENS", tokens or {})
    # tier 힌트가 있으면 같이 올림
    if tokens and tokens.get("tier"):
        app.setProperty("DISPLAY_TIER", tokens.get("tier"))

# 변경 브로드캐스트: settings_bus가 로드된 경우에만 안전하게 호출
#─────────────────────────────────────────────
#  브로드캐스트
#─────────────────────────────────────────────
def config_broadcast_settings(effective: Dict[str, Any]) -> None:
    try:
        # 지연 임포트로 순환 의존 회피
        from app.pages.setting import settings_bus  # type: ignore
        settings_bus.changed.emit(effective)
    except Exception:
        # 설정 화면을 아직 로드하지 않았을 수 있음 — 무시
        pass

#─────────────────────────────────────────────
# 적용 + 방송 (필요시)
#─────────────────────────────────────────────
#  전역 적용 + 방송
#─────────────────────────────────────────────
def config_apply_and_broadcast(effective: Dict[str, Any], tier: str | None = None) -> None:
    palette = config_extract_palette(effective)
    # 필수 키 확인
    required = ("bg","card","border","text","subtext","primary","primary_hover","primary_active")
    missing = [k for k in required if k not in palette]
    if missing:
        raise RuntimeError(f"THEME_COLORS missing keys: {missing}. Ensure defaults/settings provide 'ui.colors'.")
    tokens  = config_build_tokens(effective.get("ui", {}), tier=tier)
    config_push_globals(palette, tokens)
    config_broadcast_settings(effective)

#─────────────────────────────────────────────
# 부트스트랩 (앱 시작 시 1회)
#─────────────────────────────────────────────
#  부트스트랩
#─────────────────────────────────────────────
def config_bootstrap_settings() -> Dict[str, Any]:
    """
    - 역할: defaults.json 로드 → 사용자 settings.json 보증/로드 → 머지 → 팔레트/토큰 전역 주입
    - 토큰 scale/req_h는 1차 부트에서는 미설정(=1.0/None). 이후 apply_typography_from_settings에서 확정됨.
    """
    defaults = config_load_defaults()
    user_settings = config_ensure_settings_file(defaults)
    effective = config_deep_merge(defaults, user_settings)
    # 팔레트만 있어도 Theme 생성 가능 — 우선 팔레트+기본 토큰 주입
    palette = config_extract_palette(effective)
    config_push_globals(palette, config_build_tokens(effective.get("ui", {})))
    return effective

#─────────────────────────────────────────────
# 저장(원자적)
#─────────────────────────────────────────────
#  저장
#─────────────────────────────────────────────
def config_save_settings_atomic(settings: Dict[str, Any], path: Path | None = None) -> None:
    path = path or config_user_settings_path()
    config_save_json_atomic(path, settings)
