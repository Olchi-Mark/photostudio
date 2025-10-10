# app/utils/control_camera.py
# 역할: 호환 셈(shim). 기존 'CameraControl'과 새 'CRSDKBridge' 둘 다 노출.
# 수정 로그:
# - 2025-09-22: CRSDKBridge, CameraControl 동시 export. 외부 코드는 둘 중 아무거나 import 가능.

from __future__ import annotations

from .control_camera_sdk import CRSDKBridge

# 과거 코드 호환용 별칭
CameraControl = CRSDKBridge

__all__ = ["CRSDKBridge", "CameraControl"]