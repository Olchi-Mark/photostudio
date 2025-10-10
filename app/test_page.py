# test_page.py
# 요구사항 반영본
# - 전체 배경: 흰색
# - 스텝바: 분홍 바탕 + 얇은 분홍 테두리(항상)
#   · 비선택 스텝: 분홍 배경 + 흰 글씨(더 작게)
#   · 선택 스텝: 흰색 하이라이트(양쪽 팁 모두 → 방향), 분홍 글씨(더 두껍고 크게)
#   · tip 비율: seg_w * 0.05 (매우 완만)
#   · 가장 왼쪽 스텝: 왼쪽 팁 생략 / 가장 오른쪽 스텝: 오른쪽 팁 생략
# - FooterBar: 흰 배경, 좌/우 이미지 버튼(불투명도로 눌림/비활성 표현), 중앙 브랜드
# - 레이아웃 비율: StepBar 1/16, FooterBar 1/14 → LCM 112 → 7:97:8

import sys
from typing import List

from PySide6.QtCore import Qt, QRectF, QSize
from PySide6.QtGui import QPainter, QColor, QFont, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QSizePolicy, QGraphicsOpacityEffect
)

# ----------------------------- 색상/자산 -----------------------------
PINK  = QColor("#FFA9A9")
WHITE = QColor("#FFFFFF")

ASSETS = {
    "brand": "assets/images/brand_logo.jpg",
    "prev":  "assets/images/btn_prev.jpg",
    "next":  "assets/images/btn_next.jpg",
}

# ----------------------------- 이미지 버튼 -----------------------------
class ImageButton(QWidget):
    """이미지 1장으로 상태를 불투명도로 표현하는 단순 버튼"""
    def __init__(self, image_path: str, tooltip: str = "", parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self._pix = QPixmap(image_path)
        self._pressed = False
        self._enabled = True
        self.setToolTip(tooltip)
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._apply_opacity()

    def sizeHint(self) -> QSize:
        if not self._pix.isNull():
            return QSize(int(self._pix.width()*0.5), int(self._pix.height()*0.5))
        return QSize(120, 80)

    def setEnabled(self, enabled: bool):
        self._enabled = enabled
        super().setEnabled(enabled)
        self._apply_opacity()

    def _apply_opacity(self):
        if not self._enabled:
            self._fx.setOpacity(0.6)     # 비활성
        elif self._pressed:
            self._fx.setOpacity(0.92)    # 눌림
        else:
            self._fx.setOpacity(1.0)     # 기본

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self._enabled:
            self._pressed = True
            self._apply_opacity()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pressed and self._enabled:
            self._pressed = False
            self._apply_opacity()
            if hasattr(self.parent(), "onButtonClicked"):
                self.parent().onButtonClicked(self)
        super().mouseReleaseEvent(e)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if not self._pix.isNull():
            h = max(1, self.height())
            ratio = h / max(1, self._pix.height())
            w = int(self._pix.width() * ratio)
            x = (self.width() - w) // 2
            p.drawPixmap(x, 0, w, h, self._pix)
        p.end()

# ------------------------------- 스텝바 -------------------------------
class StepBar(QWidget):
    """
    하나의 분홍 직사각형 바 위에 '선택된' 구간만 흰색 하이라이트.
    양쪽 팁 모두 → 방향:
      - 왼쪽: 오목(안으로 파임) → i==0이면 생략
      - 오른쪽: 돌출 → i==n-1이면 생략
    비선택: 분홍 배경 + 흰 글씨(작게), 선택: 흰 배경 + 분홍 글씨(굵고 크게)
    """
    def __init__(self, steps: List[str], parent=None):
        super().__init__(parent)
        self.steps = steps
        self.active_index = 0
        self.setMinimumHeight(56)

    def setActive(self, index: int):
        self.active_index = max(0, min(index, len(self.steps)-1))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        W, H = self.width(), self.height()
        n = len(self.steps)
        if n == 0:
            p.fillRect(self.rect(), WHITE)
            p.end()
            return

        seg_w = W / n

        # (1) 전체 분홍 바 + 얇은 분홍 테두리
        p.fillRect(self.rect(), PINK)
        p.setPen(PINK)
        p.drawRect(self.rect().adjusted(0, 0, -1, -1))

        # (2) 선택 구간 흰색 하이라이트 (양쪽 팁 모두 → 방향)
        i = self.active_index
        x0, x1 = i * seg_w, (i + 1) * seg_w
        tip = seg_w * 0.05   # 매우 완만한 팁 (요청값)

        path = QPainterPath()
        # 시작: 왼쪽 위
        if i > 0:
            # 왼쪽 오목 팁을 만들기 위해 먼저 좌상단에서 우상단으로 그리고,
            # 좌측 중앙으로 '들어가는' 선을 마지막에 추가
            path.moveTo(x0, 0)
        else:
            # 첫 번째 스텝이면 왼쪽 팁 없음
            path.moveTo(x0, 0)

        # 상단 라인 → 오른쪽 상단
        path.lineTo(x1, 0)

        # 오른쪽 돌출 팁 (마지막 스텝이면 생략)
        if i < n - 1:
            path.lineTo(x1 + tip, H/2)

        # 오른쪽 아래
        path.lineTo(x1, H)

        # 왼쪽 아래
        path.lineTo(x0, H)

        # 왼쪽 오목 팁 (첫 스텝이면 생략)
        if i > 0:
            path.lineTo(x0 + tip, H/2)

        path.closeSubpath()
        p.fillPath(path, WHITE)

        # (3) 텍스트: 선택(분홍/굵고 크게) vs 비선택(흰/작게)
        for k, label in enumerate(self.steps):
            rect = QRectF(k * seg_w, 0, seg_w, H)
            is_active = (k == i)

            # 글자 크기: 비선택 더 작게, 선택 더 크게
            pt = max(10.0, H * (0.30 if not is_active else 0.42))
            font = QFont()
            font.setPointSizeF(pt)
            font.setBold(is_active)  # 선택은 더 두껍게
            p.setFont(font)

            p.setPen(PINK if is_active else WHITE)
            p.drawText(rect, Qt.AlignCenter, str(label))

        p.end()

# ------------------------------- 하단 바 -------------------------------
class FooterBar(QWidget):
    """좌: 이전 버튼 | 중: 브랜드 | 우: 다음 버튼 (배경 흰색)"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(80)

        self.prevBtn = ImageButton(ASSETS["prev"], tooltip="이전")
        self.nextBtn = ImageButton(ASSETS["next"], tooltip="다음")

        self.brand = QLabel()
        pm = QPixmap(ASSETS["brand"])
        if not pm.isNull():
            self.brand.setPixmap(pm)
        self.brand.setAlignment(Qt.AlignCenter)
        self.brand.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(16, 8, 16, 6)  # 브랜드 하단 여백 6px
        lay.setSpacing(12)
        lay.addWidget(self.prevBtn, 0)
        lay.addWidget(self.brand, 1)
        lay.addWidget(self.nextBtn, 0)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), WHITE)
        p.end()

# ------------------------------- 테스트 창 -------------------------------
class TestWindow(QMainWindow):
    """상단 StepBar(1/16) + 중앙(97/112) + 하단 FooterBar(1/14) 레이아웃"""
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Test Page — StepBar & FooterBar")
        self.setMinimumSize(1200, 700)

        central = QWidget(); self.setCentralWidget(central)
        v = QVBoxLayout(central); v.setContentsMargins(0, 0, 0, 0); v.setSpacing(0)

        steps = ["정보입력", "사이즈선택", "촬영", "사진선택", "AI 보정", "이메일전송", "추가옵션"]
        self.stepbar = StepBar(steps)
        self.footer  = FooterBar()

        content = QLabel("중앙 콘텐츠")
        content.setAlignment(Qt.AlignCenter)
        content.setStyleSheet("background:#FFFFFF; color:#555; font-size:22px;")

        v.addWidget(self.stepbar)
        v.addWidget(content)
        v.addWidget(self.footer)

        # 비율: 7:97:8 (StepBar 1/16, FooterBar 1/14의 LCM 112 기준)
        v.setStretch(0, 7)
        v.setStretch(1, 97)
        v.setStretch(2, 8)

        # Prev/Next로 현재 스텝 이동 (데모)
        self.footer.onButtonClicked = self.onFooterClicked
        self._idx = 0
        self._sync()

        self.showMaximized()

    def _sync(self):
        self.stepbar.setActive(self._idx)
        self.footer.prevBtn.setEnabled(self._idx > 0)
        self.footer.nextBtn.setEnabled(self._idx < 6)

    def onFooterClicked(self, btn: QWidget):
        if btn is self.footer.prevBtn and self._idx > 0:
            self._idx -= 1
        elif btn is self.footer.nextBtn and self._idx < 6:
            self._idx += 1
        self._sync()

# --------------------------------- main -----------------------------------
if __name__ == "__main__":
    app = QApplication(sys.argv)
    win = TestWindow()
    win.show()
    sys.exit(app.exec())
