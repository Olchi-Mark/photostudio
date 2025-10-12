# main.py
# Photostudio 애플리케이션의 엔트리 포인트를 정의한다
import sys, os
ROOT = os.path.dirname(os.path.abspath(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QFontDatabase, QFontInfo, QFont

from app.fonts import register_fonts
from app.themes import Theme
from app.main_window import MainWindow
from app.ui.typography import apply_typography_from_settings
from app.ui.window_mode import decide_window_mode, apply_window_mode  # 윈도우 모드 분리

# 설정 부트스트랩/경로 유틸
from pathlib import Path
from app.config.loader import (
    config_bootstrap_settings,
    config_user_settings_path,
    config_load_settings,
    config_save_settings_atomic,
)

# main(): Photostudio Qt 애플리케이션을 초기화하고 실행하는 진입점
def main():
    # DPI 잠금(배율 무시: 물리 픽셀 1:1)
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")   # Qt 자체 HighDPI 스케일 끔
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0")  # 자동 스케일 감지 끔
    os.environ.setdefault("QT_SCALE_FACTOR", "1")              # 강제 1x 스케일
    os.environ.setdefault("QT_FONT_DPI", "96")                 # 폰트 DPI 고정

    app = QApplication(sys.argv)

    # 설정/토큰/팔레트 주입 (defaults.json → settings.json 보증 포함)
    effective = config_bootstrap_settings()

    # --- DEBUG: 부트스트랩 직후 토큰/티어 확인 ---
    TOK = app.property("TYPO_TOKENS") or {}
    print("BOOT TIER=", app.property("DISPLAY_TIER"), "req_h=", TOK.get("req_h"), "scale=", TOK.get("scale"))

    # 폰트 등록 → Theme는 팔레트 주입 이후 생성
    font_info = register_fonts()

    # 스펙트랄 보증 등록(누락 시 assets/fonts에서 직접 추가)
    # - 앱 배포 환경에 따라 시스템 설치가 없을 수 있으므로 예방적으로 확인
    try:
        families = set(QFontDatabase.families())
        if "Spectral" not in families:
            F = Path(ROOT) / "app" / "assets" / "fonts"
            for fname in ("Spectral-Regular.ttf", "Spectral-Bold.ttf"):
                QFontDatabase.addApplicationFont(str(F / fname))
        # DEBUG: 실제 적용 패밀리 확인(필요 시 주석처리 가능)
        print("SPECTRAL?=", QFontInfo(QFont("Spectral")).family())
    except Exception:
        pass

    theme = Theme(font_info)

    # 레거시 호환: 프로젝트 루트에 settings.json 그림자 저장(없는 경우만)
    try:
        user_settings = config_load_settings(config_user_settings_path())
        proj_settings_path = Path(ROOT) / "settings.json"
        if not proj_settings_path.exists():
            config_save_settings_atomic(user_settings, proj_settings_path)
    except Exception:
        pass

    # 화면 정보 (재평가 없이 1회 측정 고정)
    scr = app.primaryScreen()
    geo: QRect = scr.geometry()                 # 작업표시줄 포함 전체 화면
    avail: QRect = scr.availableGeometry()      # 작업표시줄 제외 영역

    #─────────────────────────────────────────
    #  디스플레이 모드 결정 (외부 모듈)
    #─────────────────────────────────────────
    info = decide_window_mode(geo, avail, tol=8)
    if info is None:
        QMessageBox.critical(None, "Display Error", "화면 해상도 또는 폭이 9:16 최소 요구 조건을 만족하지 않습니다.")
        return 1

    # 티어 힌트 전역 주입 (위젯/로그용)
    app.setProperty("DISPLAY_TIER", getattr(info, "tier", None))

    # 타이포 스케일 적용: 정규 높이(req_h) 기준
    settings_path = os.path.join(ROOT, "settings.json")
    # 타이포 스케일 적용: 정규 높이(req_h) 기준
    apply_typography_from_settings(settings_path, info.req_h)

    # --- DEBUG: 타이포 적용 직후 토큰/티어 확인 ---
    TOK = app.property("TYPO_TOKENS") or {}
    print("AFTER TYPO TIER=", app.property("DISPLAY_TIER"), "req_h=", TOK.get("req_h"), "scale=", TOK.get("scale"))

    # 메인 윈도우 생성 + 적용
    win = MainWindow(theme, display=info)
    apply_window_mode(win, info)

    return app.exec()

# 모듈이 직접 실행될 때 애플리케이션을 구동한다
if __name__ == "__main__":
    sys.exit(main())
# 테스22트하는중입니다.

# testtestest
