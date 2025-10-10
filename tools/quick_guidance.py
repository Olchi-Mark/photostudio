# C:\dev\photostudio\tools\quick_guidance.py
# -*- coding: utf-8 -*-
import os, sys, time
from pathlib import Path
from PySide6.QtGui import QImage

PROJECT_HOME = r"C:\dev\photostudio"
PKG_ROOT = rf"{PROJECT_HOME}\app"
TEST_IMG = rf"{PROJECT_HOME}\samples\test.jpg"

# 패키지 경로 추가 및 작업 디렉터리 고정
sys.path.insert(0, PKG_ROOT)
os.chdir(PROJECT_HOME)

from ai.guidance import Guidance          # C:\dev\photostudio\app\ai\guidance.py
from utils.face_engine import FaceEngine  # C:\dev\photostudio\app\utils\face_engine.py

def main():
    img_path = Path(TEST_IMG)
    if not img_path.exists():
        print(f"이미지 없음: {img_path}")
        return

    qimg = QImage(str(img_path))
    if qimg.isNull():
        print(f"로드 실패: {img_path}")
        return

    g = Guidance()             # rate_ms 기본값 사용
    fe = FaceEngine()          # 모델 경로는 face_engine 기본값 사용(작업 폴더 기준)
    fe.start()

    payload, badges, ema = g.update(
        qimg=qimg,
        ratio="3545",
        ts_ms=int(time.time() * 1000),
        face_engine=fe,
        pose_engine=None,      # 빠른 검증용(어깨 미사용)
    )

    fe.stop()

    print("badges:", badges)
    print("metrics:", {k: round(v, 3) for k, v in ema.items()})

if __name__ == "__main__":
    main()
