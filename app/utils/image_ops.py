# -*- coding: utf-8 -*-
from __future__ import annotations

from PySide6.QtCore import Qt, QRect
from PySide6.QtGui import QImage, QPixmap, QTransform, QPainter

__all__ = ["render_transformed", "render_placeholder"]

def _render_cover_top(src: QImage, target_w: int, target_h: int) -> QPixmap:
    """라벨을 완전히 덮도록 cover 스케일 후, '상단 정렬(top)'로 크롭해서 그린다.
    - 회색 여백(레터박싱/필러박싱) 없음
    - 필요 시 하단(세로 방향) 또는 좌우(가로 방향) 크롭
    """
    if not src or src.isNull() or target_w <= 0 or target_h <= 0:
        return QPixmap()

    # cover scale factor
    s_x = target_w / float(src.width())
    s_y = target_h / float(src.height())
    s = s_x if s_x >= s_y else s_y  # cover

    # source rect(이미지 좌표계) 계산: 상단 정렬 → y=0, 좌우는 중앙 크롭
    src_w = int(round(target_w / s))
    src_h = int(round(target_h / s))
    src_w = max(1, min(src_w, src.width()))
    src_h = max(1, min(src_h, src.height()))

    src_x = max(0, (src.width() - src_w) // 2)  # 좌우는 중앙 정렬로 균형 크롭
    src_y = 0                                   # 상단 정렬 → 위를 기준으로 자르고 아래를 크롭

    canvas = QPixmap(target_w, target_h)
    canvas.fill(Qt.transparent)
    p = QPainter(canvas)
    try:
        # 대상 전체(rect 0,0,w,h)를 소스 일부(src rect)로 채움 → 여백 없음
        p.drawImage(
            QRect(0, 0, target_w, target_h),
            src,
            QRect(src_x, src_y, src_w, src_h),
        )
    finally:
        p.end()
    return canvas


def render_transformed(img: QImage, target_w: int, target_h: int) -> QPixmap:
    """카메라 프레임용:
    - 90° CCW 회전 → 좌우 반전
    - 라벨을 완전히 덮는 cover + 상단정렬(top) 크롭으로 그리기
    """
    try:
        if target_w <= 0 or target_h <= 0 or not img or img.isNull():
            return QPixmap()
        rot = img.transformed(QTransform().rotate(-90), Qt.SmoothTransformation)
        rot = rot.mirrored(True, False)
        return _render_cover_top(rot, target_w, target_h)
    except Exception:
        return QPixmap()


def render_placeholder(img: QImage, target_w: int, target_h: int) -> QPixmap:
    """플레이스홀더/정지 이미지:
    - 회전/반전 없이 cover + 상단정렬(top) 크롭으로 그리기
    """
    try:
        if target_w <= 0 or target_h <= 0 or not img or img.isNull():
            return QPixmap()
        return _render_cover_top(img, target_w, target_h)
    except Exception:
        return QPixmap()
