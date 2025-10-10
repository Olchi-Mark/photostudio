# -*- coding: utf-8 -*-
#─────────────────────────────────────────────
#  App/components/footer_bar.py — 푸터 바(로컬 하드토큰, primary만 THEME_COLORS)
#  - 전역 하드값 제거: THEME_COLORS/TYPO_TOKENS 런타임 참조
#  - 높이/마진은 BasePage의 chrome 토큰으로만 제어(footer_h)
#  - 내부 패딩/간격은 spacing 토큰으로만 제어(3의 배수)
#─────────────────────────────────────────────
from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, QSize, Signal, QTimer, QUrl
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPainterPath, QPainterPathStroker
from PySide6.QtWidgets import (
    QApplication, QWidget, QHBoxLayout, QLabel, QSizePolicy,
)
from PySide6.QtMultimedia import QSoundEffect

import math
import os

#─────────────────────────────────────────────
#  로컬 하드토큰(이 파일에서만 사용) — FHD 기준
#  전역 토큰은 쓰지 않고, 색상만 THEME_COLORS.primary를 사용한다.
PAD_H      = 12    # 좌우 패딩(px)
PAD_V      = 6    # 상하 패딩(px)
GAP        = 12    # Prev/Brand/Next 사이 간격(px)

BTN_FS_FHD       = 21    # 버튼 글자 크기(px, FHD 기준)
BTN_CORNER_R_FHD = 12    # 버튼 코너 라운드(px, FHD 기준)
BTN_PAD_H_FHD    = 12    # 버튼 텍스트 좌우 패딩(px, FHD 기준)
BTN_AR           = 1.1   # 버튼 폭/높이 비율


#─────────────────────────────────────────────
#  텍스트 삼각형 버튼(좌/우)
#─────────────────────────────────────────────
#  클래스 TriButton
#─────────────────────────────────────────────
class TriButton(QWidget):
    """
    좌/우 삼각형 + 텍스트 버튼.
    - 방향: left/right
    - 모드: disabled / enabled / lit(점등)
    - 색상: THEME primary 기반(약간 투명도)
    - 스케일: TOK.scale로 3:4:6 적용, 텍스트 크기 스냅3
    """
    clicked = Signal()

    # 모드 상수
    MODE_DISABLED = 0
    MODE_ENABLED  = 1
    MODE_LIT      = 2
    MODE_HIDDEN   = 3  # 아예 안보이게

    # 역할: 생성자(라벨/방향/초기색)
    def __init__(self, label: str, direction: str = "left", color: str = "#FF4081", parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self._label = label
        self._dir = direction  # 'left' or 'right'
        self._color = QColor(color)
        self._scale = 1.0
        self._pressed = False
        self._mode = TriButton.MODE_ENABLED
        # 점등(펄스) 애니메이션 상태
        self._pulse_phase = 0.0
        self._pulse_alpha = 200
        self._pulse_fill_alpha = 220
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(16)  # ~60fps
        self._pulse_timer.timeout.connect(self._on_pulse)
        # 사운드: 점등 펄스(1.2s)와 동기화된 ding 효과
        self._phase_prev = 0.0  # 펄스 위상 래핑 검출용
        self._beep = QSoundEffect(self)  # 점등 사운드 객체
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # .../app
        wav_path = os.path.join(base_dir, "assets", "sound", "ding.wav")   # app/assets/sound/ding.wav
        self._beep.setSource(QUrl.fromLocalFile(wav_path))
        self._beep.setLoopCount(1)
        # 볼륨 토큰 적용: TYPO_TOKENS.audio.ding_volume (기본 0.4, 0.0~1.0)
        try:
            app = QApplication.instance()
            TOK = (app.property("TYPO_TOKENS") or {}) if app else {}
            audio = TOK.get("audio", {}) if isinstance(TOK, dict) else {}
            vol = float(audio.get("ding_volume", 0.4))
        except Exception:
            vol = 0.6
        self._beep.setVolume(max(0.0, min(1.0, vol)))
        # 점등 사운드 사용 여부 플래그(Prev 클릭 시 소리만 끄기용)
        self._beep_enabled = True
        self.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)

        self._fs_fhd = 18         # 글자 px(FHD)
        self._corner_r_fhd = 12   # 코너 라운드 px(FHD)
        self._pad_h_fhd = 12      # 텍스트 좌우 패딩 px(FHD)
        self._ar = 1.5            # 폭/높이 비율

    def set_tokens(self, fs_fhd=18, corner_r_fhd=12, pad_h_fhd=12, ar=1.5):
        self._fs_fhd = int(fs_fhd)
        self._corner_r_fhd = int(corner_r_fhd)
        self._pad_h_fhd = int(pad_h_fhd)
        self._ar = float(ar) if ar and ar > 0 else 1.5
        self.update()
      
    # 역할: 스케일/색상 갱신
    def set_theme(self, color: str, scale: float) -> None:
        self._color = QColor(color)
        self._scale = float(scale) if scale else 1.0
        self.update()

    # 역할: 모드 설정(비활성/활성/점등)
    def set_mode(self, mode: int) -> None:
        if mode not in (
            TriButton.MODE_DISABLED, TriButton.MODE_ENABLED, TriButton.MODE_LIT, TriButton.MODE_HIDDEN
        ):
            mode = TriButton.MODE_ENABLED
        self._mode = mode
        # 표시/포인터/타이머
        if mode == TriButton.MODE_HIDDEN:
            self.setVisible(False)
            self._pulse_timer.stop()
            self._beep.stop()
        else:
            self.setVisible(True)
            self.setEnabled(mode != TriButton.MODE_DISABLED)
            self.setCursor(Qt.ArrowCursor if mode == TriButton.MODE_DISABLED else Qt.PointingHandCursor)
            if mode == TriButton.MODE_LIT:
                # 소리 다시 허용
                self._beep_enabled = True
                # 펄스 위상 초기화(소리 래핑 기준 동기화)
                self._pulse_phase = 0.0
                self._phase_prev = 0.0
                self._pulse_timer.start()
            else:
                self._pulse_timer.stop()
                self._beep.stop()
        self.update()

    # 역할: 크기 힌트(높이 대비 비율로 폭 산정)
    def sizeHint(self) -> QSize:
        h = max(48, int(64 * self._scale))
        w = int(h * getattr(self, "_ar", 1.5))
        return QSize(w, h)

    # 역할: 마우스 프레스/릴리즈(클릭)
    def mousePressEvent(self, e):
        if self._mode == TriButton.MODE_DISABLED:
            return
        if e.button() == Qt.LeftButton:
            self._pressed = True
            self.update()
        super().mousePressEvent(e)

    def mouseReleaseEvent(self, e):
        if self._mode == TriButton.MODE_DISABLED:
            return
        if self._pressed:
            self._pressed = False
            self.update()
            self.clicked.emit()
        super().mouseReleaseEvent(e)

    # 역할: 3의 배수 스냅
    def _snap3(self, v: float) -> int:
        vi = int(v)
        return (vi // 3) * 3

    # 역할: 펄스 알파 업데이트(1.2초 주기 코사인 보간, 위상=0에서 최대값 → 소리와 동기)
    def _on_pulse(self) -> None:
        if self._mode != TriButton.MODE_LIT:
            return
        prev = self._pulse_phase
        self._pulse_phase = (self._pulse_phase + 16.0 / 1200.0) % 1.0
        # 위상 래핑(1.0→0.0) 시 ding 재생
        if self._pulse_phase < prev and self._beep.isLoaded() and getattr(self, "_beep_enabled", True):
            self._beep.play()
        s = 0.5 + 0.5 * math.cos(2.0 * math.pi * self._pulse_phase)
        self._pulse_alpha = int(150 + (255 - 150) * s)
        self._pulse_fill_alpha = int(200 + (255 - 200) * s)
        self.update()

    # 역할: 사운드/펄스 강제 정지(화면 전환·클릭 등)
    def silence(self) -> None:
        try:
            self._pulse_timer.stop()
        except Exception:
            pass
        try:
            self._beep.stop()
        except Exception:
            pass

    # 역할: 사운드만 일시 정지/뮤트
    def mute_beep(self, mute: bool = True) -> None:
        try:
            self._beep_enabled = not mute
            self._beep.stop()
        except Exception:
            pass

    # 역할: 삼각형(둥근 모서리) + 텍스트 렌더
    def paintEvent(self, ev):
        # 숨김 모드: 렌더 스킵
        if self._mode == TriButton.MODE_HIDDEN:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        w, h = self.width(), self.height()
        r = max(3, self._snap3(self._corner_r_fhd * self._scale))  # 둥근 코너 반경(토큰)

        path = QPainterPath()
        if self._dir == "left":
            # 오른쪽 위 → 왼쪽 중앙 → 오른쪽 아래, 각 꼭짓점에 곡선 코너
            path.moveTo(w - r, 0)
            path.quadTo(w, 0, w, r)
            path.lineTo(w, h - r)
            path.quadTo(w, h, w - r, h)
            path.lineTo(r, h / 2 + r / 2)
            path.quadTo(0, h / 2, r, h / 2 - r / 2)
            path.closeSubpath()
        else:  # right
            path.moveTo(r, 0)
            path.quadTo(0, 0, 0, r)
            path.lineTo(0, h - r)
            path.quadTo(0, h, r, h)
            path.lineTo(w - r, h / 2 + r / 2)
            path.quadTo(w, h / 2, w - r, h / 2 - r / 2)
            path.closeSubpath()

        # 채우기 색/알파(모드별)
        base = QColor(self._color)
        if self._mode == TriButton.MODE_DISABLED:
            base.setAlpha(90)
        elif self._mode == TriButton.MODE_LIT:
            base.setAlpha(self._pulse_fill_alpha if not self._pressed else 255)
        else:  # enabled
            base.setAlpha(180 if not self._pressed else 210)
        p.fillPath(path, base)

        # 점등 모드일 때 내부 글로우(스트로크 제거, 외부로 번짐 없음)
        if self._mode == TriButton.MODE_LIT:
            stroker = QPainterPathStroker()
            stroker.setWidth(max(1, self._snap3(6 * self._scale)))
            stroker.setJoinStyle(Qt.RoundJoin)
            stroke = stroker.createStroke(path)
            p.save()
            p.setClipPath(path)  # 내부만 남김
            p.fillPath(stroke, QColor(255, 255, 255, self._pulse_alpha))
            p.restore()

        # 텍스트(S-Core Dream)
        fs = self._snap3(self._fs_fhd * self._scale)
        font = QFont("S-Core Dream")
        font.setPixelSize(fs)
        font.setWeight(QFont.Bold if self._mode == TriButton.MODE_LIT else (QFont.DemiBold if self._mode != TriButton.MODE_DISABLED else QFont.Medium))
        p.setFont(font)
        text_color = QColor("#FFFFFF")
        if self._mode == TriButton.MODE_DISABLED:
            text_color.setAlpha(170)
        p.setPen(text_color)

        # 라벨 정규화: Prev/Next (첫 글자만 대문자)
        label_norm = self._label.strip().lower()
        if label_norm.startswith("prev"):
            text = "Prev"
            align = Qt.AlignVCenter | Qt.AlignRight
        elif label_norm.startswith("next"):
            text = "Next"
            align = Qt.AlignVCenter | Qt.AlignLeft
        else:
            text = self._label
            align = Qt.AlignCenter

        pad = self._snap3(self._pad_h_fhd * self._scale)
        rect = self.rect().adjusted(pad, 0, -pad, 0)
        if self._mode == TriButton.MODE_LIT:
            p.setPen(QColor(0, 0, 0, 120))
            p.drawText(rect.adjusted(1, 1, 1, 1), align, text)
            p.setPen(text_color)
        p.drawText(rect, align, text)
        p.end()


#─────────────────────────────────────────────
#  클래스 FooterBar
#─────────────────────────────────────────────
class FooterBar(QWidget):
    """
    하단 푸터 바 — 브랜드/이전/다음.
    - 높이: chrome.footer_h 토큰 고정(3:4:6)
    - 배경/보더: THEME_COLORS.card / border + hairline 두께(1:1:2)
    - 내부 패딩/간격: spacing 토큰(pad_h/pad_v/gap)
    """
    go_prev = Signal()
    go_next = Signal()

    # ── FHD 기준 하드 토큰(브랜드 타이포) ─────────────────────
    BRAND_BIG_FS_FHD   = 39  # M/S/I 크기
    BRAND_SMALL_FS_FHD = 33  # 나머지 크기
    BRAND_LS_FHD       = 0.4 # letter-spacing(px) # letter-spacing(px)

    # 모드 포워딩 상수(외부에서 보기 쉽게)
    MODE_DISABLED = TriButton.MODE_DISABLED
    MODE_ENABLED  = TriButton.MODE_ENABLED
    MODE_LIT      = TriButton.MODE_LIT


    # 3의 배수 내림 스냅
    def _snap3(self, v: float) -> int:
        vi = int(v)
        return (vi // 3) * 3

    # 역할: 브랜드 텍스트 구성("MY SWEET INTERVIEW" — M/S/I만 크게)
    def _apply_brand_text(self) -> None:
        """
        - 역할: 브랜드 텍스트 HTML 구성(스케일/스냅 반영)
        """
        color = self._C.get("primary", "#FF4081")
        scale = float(getattr(self, "_SCALE", 1.0)) or 1.0
        px_small = self._snap3(self.BRAND_SMALL_FS_FHD * scale)
        px_big   = self._snap3(self.BRAND_BIG_FS_FHD   * scale)
        ls_px    = round(self.BRAND_LS_FHD * scale, 2)
        html = f"""
            <div style="text-align:center; font-family:'Spectral', serif; letter-spacing:{ls_px}px; font-weight:600; color:{color};">
              <span style="font-size:{px_big}px;">M</span><span style="font-size:{px_small}px;">Y</span> &nbsp;
              <span style="font-size:{px_big}px;">S</span><span style="font-size:{px_small}px;">WEET</span> &nbsp;
              <span style="font-size:{px_big}px;">I</span><span style="font-size:{px_small}px;">NTERVIEW</span>
            </div>
        """
        self.brand.setTextFormat(Qt.RichText)
        self.brand.setText(html)

    # 역할: 푸터바 초기화(토큰 로드 → 레이아웃 구성 → 1회 스케일)
    def __init__(self, brand_path: Optional[str] = None, prev_path: Optional[str] = None,
                 next_path: Optional[str] = None, parent=None):
        super().__init__(parent)

        # 토큰/팔레트 로드
        self._refresh_tokens()

        # 위젯 구성
        self.prevBtn = TriButton("PREV", direction="left", color=self._C.get("primary", "#FF4081"))
        self.nextBtn = TriButton("NEXT", direction="right", color=self._C.get("primary", "#FF4081"))

        # 브랜드는 텍스트로 렌더
        self.brand = QLabel()
        self.brand.setAlignment(Qt.AlignCenter)
        self.brand.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 시그널 브리지
        self.prevBtn.clicked.connect(self._on_prev_clicked)
        self.nextBtn.clicked.connect(self._on_next_clicked)

        # 레이아웃
        self._lay = QHBoxLayout(self)
        self._apply_layout_metrics()
        self._lay.addWidget(self.prevBtn, 0)
        self._lay.addWidget(self.brand, 1)
        self._lay.addWidget(self.nextBtn, 0)

        # 초기 1회 렌더
        self._apply_brand_text()

        # 초기 버튼 스케일/컬러 적용(초기 진입에서도 QHD급 크기 가능)
        self.prevBtn.set_theme(self._C.get("primary", "#FF4081"), self._BTN_SCALE)
        self.nextBtn.set_theme(self._C.get("primary", "#FF4081"), self._BTN_SCALE)
        # 버튼 외형 토큰 적용(비율/글자/라운드/패딩)
        self.prevBtn.set_tokens(
            fs_fhd=self._BTN.get("fs_fhd", 18),
            corner_r_fhd=self._BTN.get("corner_r_fhd", 12),
            pad_h_fhd=self._BTN.get("pad_h_fhd", 12),
            ar=float(self._BTN.get("ar", 1.5)),
        )
        self.nextBtn.set_tokens(
            fs_fhd=self._BTN.get("fs_fhd", 18),
            corner_r_fhd=self._BTN.get("corner_r_fhd", 12),
            pad_h_fhd=self._BTN.get("pad_h_fhd", 12),
            ar=float(self._BTN.get("ar", 1.5)),
        )

        # 설정 변경 브로드캐스트 구독(선택)
        try:
            from app.pages.setting import settings_bus
            settings_bus.changed.connect(self._on_settings_changed)
        except Exception:
            pass

    #─────────────────────────────────────
    #  토큰/팔레트 로드 & 적용
    #─────────────────────────────────────
    # 역할: qApp 프로퍼티에서 토큰을 새로 읽어 캐시
    def _refresh_tokens(self) -> None:
        app = QApplication.instance()
        cols = (app.property("THEME_COLORS") or {}) if app else {}
        TOK  = (app.property("TYPO_TOKENS") or {}) if app else {}
        scale = float(TOK.get("scale", 1.0) or 1.0)
        # primary만 THEME에서 사용. 나머지는 로컬 하드토큰 + 스케일
        self._C = {
            "primary": cols.get("primary", "#FF4081"),
            "card": "#FFFFFF",
        }
        self._SCALE = scale
        self._BTN_SCALE = scale
        self._S = {
            "pad_h": self._snap3(PAD_H * scale),
            "pad_v": self._snap3(PAD_V * scale),
            "gap":   self._snap3(GAP   * scale),
        }
        # 버튼 외형 토큰은 FHD 기준 px 값이며, 렌더 시 _scale로 스케일됨
        self._BTN = {
            "fs_fhd": int(BTN_FS_FHD),
            "corner_r_fhd": int(BTN_CORNER_R_FHD),
            "pad_h_fhd": int(BTN_PAD_H_FHD),
            "ar": float(BTN_AR),
        }
        # 높이는 BasePage의 chrome 토큰에서만 제어. 여기서는 설정하지 않음.

    # 역할: 레이아웃 마진/스페이싱을 토큰으로 적용
    def _apply_layout_metrics(self) -> None:
        pad_h = int(self._S.get("pad_h", 12))
        pad_v = int(self._S.get("pad_v", 12))
        gap   = int(self._S.get("gap", 12))
        self._lay.setContentsMargins(pad_h, pad_v, pad_h, pad_v)
        self._lay.setSpacing(gap)

    # 역할: 설정 변경 시 토큰 재적용
    def _on_settings_changed(self, *_):
        self._refresh_tokens()
        self._apply_layout_metrics()
        self._apply_brand_text()
        # 버튼 테마 재적용(색/스케일)
        self.prevBtn.set_theme(self._C.get("primary", "#FF4081"), self._BTN_SCALE)
        self.nextBtn.set_theme(self._C.get("primary", "#FF4081"), self._BTN_SCALE)
        # 버튼 외형 토큰 재적용
        self.prevBtn.set_tokens(
            fs_fhd=self._BTN.get("fs_fhd", 18),
            corner_r_fhd=self._BTN.get("corner_r_fhd", 12),
            pad_h_fhd=self._BTN.get("pad_h_fhd", 12),
            ar=float(self._BTN.get("ar", 1.5)),
        )
        self.nextBtn.set_tokens(
            fs_fhd=self._BTN.get("fs_fhd", 18),
            corner_r_fhd=self._BTN.get("corner_r_fhd", 12),
            pad_h_fhd=self._BTN.get("pad_h_fhd", 12),
            ar=float(self._BTN.get("ar", 1.5)),
        )
        self.update()

    # 내부 클릭 처리: Prev/Next
    def _on_prev_clicked(self):
        # 요구사항: 이전 버튼을 눌렀을 때 점등음만 즉시 중지(시각 효과 유지)
        try:
            self.prevBtn.mute_beep(True)
            self.nextBtn.mute_beep(True)
        except Exception:
            # 하위 호환: public API 없던 버전 대비
            try:
                self.prevBtn._beep.stop(); self.nextBtn._beep.stop()
            except Exception:
                pass
        self.go_prev.emit()

    # 내부 클릭 처리: Next 누르면 즉시 사운드 정지 후 시그널 전달
    def _on_next_clicked(self):
        try:
            self.nextBtn.silence()
        except Exception:
            pass
        self.go_next.emit()

    #─────────────────────────────────────
    #  공개 API(모드 제어)
    #─────────────────────────────────────
    def set_prev_mode(self, mode: int) -> None:
        self.prevBtn.set_mode(mode)

    def set_next_mode(self, mode: int) -> None:
        self.nextBtn.set_mode(mode)

    #─────────────────────────────────────
    #  내부 동작
    #─────────────────────────────────────
    # 역할: 브랜드 텍스트는 픽셀 폰트 고정이므로 리사이즈에서 별도 처리 없음
    def resizeEvent(self, e):
        super().resizeEvent(e)
        # 푸터 안쪽 유효 높이 기준으로 버튼 폭을 비율(ar)대로 강제
        pad_v = int(self._S.get("pad_v", 12))
        h_in  = max(24, self.height() - 2 * pad_v)
        ar    = float(self._BTN.get("ar", 1.5))
        w_in  = int(round(h_in * ar))
        self.prevBtn.setFixedSize(w_in, h_in)
        self.nextBtn.setFixedSize(w_in, h_in)

    # 역할: 배경만 렌더(상단 보더 제거)
    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(self._C.get("card", "#FFFFFF")))
        p.end()

#─────────────────────────────────────────────
#  수정 로그
#─────────────────────────────────────────────
# 2025-09-20 v2.9: TriButton에 beep 전용 mute 플래그/메서드 추가(mute_beep). Prev 클릭 시 양쪽 버튼 소리만 즉시 중지, 시각 효과는 유지.
# 2025-09-18 v2.8: 점등 알파를 코사인 보간으로 변경해 위상 0에서 최대. 소리 트리거(위상 래핑)와 시각 최대 동기화. 기본 볼륨 0.4.
# 2025-09-18 v2.7: 펄스 주기 1.2s로 변경, 볼륨 토큰(TYPO_TOKENS.audio.ding_volume) 적용, 모드 이탈/숨김 시 사운드 정지.
# 2025-09-18 v2.6: LIT 펄스 주기(0.8s) 래핑마다 app/assets/sound/ding.wav 재생. 볼륨 0.6.
# 2025-09-14 v2.5: TriButton 모드 4종(Disabled/Enabled/Lit/Hidden). Lit에 0.8s 펄스(α180↔235).
# 2025-09-14 v2.4: Prev/Next에 모드 추가(비활성/활성/점등).
#                   MODE_DISABLED/MODE_ENABLED/MODE_LIT 제공 + 외곽선 글로우.
# 2025-09-14 v2.3: TriButton 라벨을 Prev/Next(첫 글자만 대문자)로 정규화,
#                   Prev=오른쪽 정렬, Next=왼쪽 정렬. 내부 패딩 적용.
# 2025-09-14 v2.2: 상단 보더 라인 제거. 브랜드 폰트/자간 하드토큰(BRAND_BIG_FS/SMALL_FS/LS) 도입.
#                   이미지 버튼 제거 → 텍스트 삼각형 버튼(TriButton) 도입.
# 2025-09-14 v2.1: 브랜드 이미지를 텍스트("MY SWEET INTERVIEW")로 교체, M/S/I만 크게(30px) 나머지 24px.
#                   Spectral 폰트, primary 컬러 적용. 티어 스케일(3:4:6)+스냅 반영.
# 2025-09-14 v2.0: 토큰/팔레트 런타임 참조, footer_h 고정 높이 적용, 배경/보더 색 토큰화, 레이아웃 패딩 토큰화.
# 2025-09-11 v1.0: 초기 도입.
