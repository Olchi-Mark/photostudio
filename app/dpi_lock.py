# -*- coding: utf-8 -*-
"""
dpi_lock.py — Windows 디스플레이 배율(100~175%)과 무관하게
픽셀 기준 레이아웃/폰트가 동일하도록 고정.

사용법: QApplication 생성 '이전'에 import만 하면 적용됨.
"""
import os

# 1) Qt 스케일링 완전 고정 — 논리/물리 픽셀 1:1
#    (HighDPI 자동 스케일링/오토 스케일 모두 끔)
os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "0")   # Qt 자체 HighDPI 끔
os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "0") # 자동 스케일 감지 끔
os.environ.setdefault("QT_SCALE_FACTOR", "1")             # 스케일 강제 1.0
os.environ.setdefault("QT_FONT_DPI", "96")                # 폰트 DPI 96 고정
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

# 2) Windows DPI Awareness: 모니터 이동에도 계산 흔들림 방지
try:
    import ctypes  # type: ignore
    # PER_MONITOR_AWARE_V2 = -4
    ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
except Exception:
    try:
        # PROCESS_PER_MONITOR_DPI_AWARE = 2
        ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore
    except Exception:
        pass

# 3) Qt 라운딩 정책 — 스케일 1.0이어도 일관된 위젯/폰트 메트릭 유지
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
    Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
)

# (선택) 디버그: 잘못된 import 순서 감지용
if __name__ == "__main__":  # 직접 실행시 간단 점검
    import sys
    print("[dpi_lock] OK. Must be imported before any PySide6 modules.", file=sys.stderr)
