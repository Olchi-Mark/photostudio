# -*- coding: utf-8 -*-
"""
간이 확인: yaw 정규화(normalize_yaw_degrees) 동작을 빠르게 점검한다.

사용:
  - 워킹 디렉터리에서: python scripts/test_yaw_normalize.py
  - 기대 결과:
      sdk:  +10 -> -10
      file: +10 -> +10
"""

from __future__ import annotations

from app.ai.guidance import normalize_yaw_degrees


def _run():
    # 화면 픽셀 기준. SDK liveview는 90° CCW + 미러 → yaw 부호 반전 필요.
    raw = 10.0
    out_sdk = normalize_yaw_degrees(raw, 'sdk')
    out_file = normalize_yaw_degrees(raw, 'file')

    print(f"sdk:  raw={raw:+.1f} -> norm={out_sdk:+.1f}")
    print(f"file: raw={raw:+.1f} -> norm={out_file:+.1f}")

    assert out_sdk == -10.0, "sdk 정규화 실패: 기대 -10.0"
    assert out_file == +10.0, "file 정규화 실패: 기대 +10.0"


if __name__ == "__main__":
    _run()
    print("OK: normalize_yaw_degrees basic checks passed.")

