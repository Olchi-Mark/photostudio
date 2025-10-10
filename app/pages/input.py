# -*- coding: utf-8 -*-
#─────────────────────────────────────────────
#  app/pages/input.py — 2단계: 정보입력 (런타임 토큰/팔레트 적용)
#  - 전역 상수 제거 → qApp 프로퍼티(THEME_COLORS/TYPO_TOKENS) 런타임 참조
#  - 설정 변경(settings_bus) 시 즉시 재적용
#  - 1:1:2, 2:3:4 예외 + 3:4:6 스케일은 토큰에 위임
#─────────────────────────────────────────────
from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import Qt, QRegularExpression, QEvent, QSize, QTimer, QPropertyAnimation
from PySide6.QtGui import QRegularExpressionValidator
from PySide6.QtWidgets import (
    QApplication, QWidget, QLabel, QLineEdit, QFormLayout, QVBoxLayout, QCheckBox, QFrame,
    QSizePolicy, QScrollArea, QToolButton, QStyle, QGraphicsOpacityEffect
)

from app.ui.base_page import BasePage
from app import constants as APP_CONST
from app.ui.virtual_keyboard import KeyboardMode
from app.pages.setting import SETTINGS, settings_bus  # 런타임 설정 + 브로드캐스트 버스

#─────────────────────────────────────────────
#  설정 매핑 유틸 (input 섹션)
#─────────────────────────────────────────────

def _s_input(key: str, default: str) -> str:
    """settings.json → constants → default 순으로 문자열 반환"""
    try:
        data = getattr(SETTINGS, "data", {}) or {}
        v = (data.get("input") or {}).get(key, None)
        if isinstance(v, str) and v.strip():
            return v
    except Exception:
        pass
    return default


def _html_from_plain_or_html(raw: str, tag: str = "p") -> str:
    """plain ↔ html 자동 변환"""
    if "<" in raw:
        return raw
    lines = [line.strip() for line in raw.split("\n")]
    parts = [f"<{tag}>{line}</{tag}>" for line in lines if line]
    return "\n".join(parts)


# 안내문 폴백(Plain 또는 HTML 허용)
_DEFAULT_GUIDE_HTML = """<p>아래 안내를 읽고 동의해 주세요.</p>
<ol>
  <li>촬영 시 가이드에 따라 자세를 유지해 주세요.</li>
  <li>AI 보정은 얼굴 윤곽, 피부톤 개선 등을 포함합니다.</li>
  <li>이메일 오기입 시 재전송이 어려울 수 있습니다.</li>
  <li>개인정보는 전달 목적에만 사용되며, 보관 기간 이후 안전하게 파기됩니다.</li>
</ol>
"""
_DEFAULT_BOTTOM_GUIDE = """※ 입력하신 이름/연락처/이메일은 결과물 전달 및 고객 응대 목적에만 사용됩니다.
※ 저장된 정보는 보관 기간 경과 후 안전하게 파기됩니다.
※ 이메일 주소는 정확히 입력해 주세요. 오기입 시 재전송이 어려울 수 있습니다."""

# 이메일 검증
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


#─────────────────────────────────────────────
#  클래스 InputPage — 정보입력 화면
#─────────────────────────────────────────────
#─────────────────────────────────────────────
#  2단계: 정보입력 — 안내/동의 + 이름/전화/이메일 수집
#─────────────────────────────────────────────
class InputPage(BasePage):
    """
    2단계: 정보입력 — 안내/동의 체크 + 이름/전화/이메일 입력을 수집.
    - 전역 상수 제거: 팔레트/토큰을 런타임에 재참조
    - settings_bus.changed로 즉시 재적용
    - 세션 출력: name, phone_last4, email(list[str])
    """

    # 위젯 키(재적용 시 순회)
    _LINE_EDITS: tuple[str, ...] = ("name", "phone", "email1", "email2")

    # 기능 시작: FHD 기준 페이지 토큰(하드값) — 이 파일 최상단에서만 조정
    _P_FHD = {
        "LE_H": 54,                 # 라인에딧 높이(px)
        "FORM_HGAP": 15,            # 폼 수평 간격
        "FORM_VGAP": 12,            # 폼 수직 간격
        "GUIDE_BODY_MX": 9,         # 안내본문 좌/우 안쪽 마진
        "SCROLL_W": 9,              # 스크롤바 너비
        "SCROLL_HANDLE_MINH": 48,   # 스크롤 핸들 최소 높이
        "TOP_SPACER": 0,            # 타이틀 위 미세 여백
        "GUIDE_H": 540,             # 안내 박스 고정 높이(FHD 기준)
        "GUIDE_PAD_V": 12,          # 안내 박스 상/하 패딩(FHD 기준)
        "GUIDE_TOP_GAP": 6,        # 안내 박스 위 여백(FHD 기준)
        "GUIDE_TITLE_GAP": 9,
        "GAP_TOP_TO_TITLE": 12,
        "GAP_TITLE_TO_GUIDE": 0,
        "GAP_GUIDE_TO_AGREE": 6,
        "GAP_AGREE_TO_FORM": 45,
        "GAP_FORM_TO_NOTICE": 90,
        "COL_MX": 0,              # 페이지 공통 좌우 마진(px)
        "TITLE_MX": 0,            # 타이틀 박스 좌우 마진(px)
        "GUIDE_OUTER_MX": 0,      # 안내 박스 바깥 좌우 마진(px)
        "NOTICE_MX": 0,           # 하단 노트 좌우 마진(px)
        "FORM_MX": 120,              # 입력 폼 좌우 마진(px)

        # 타이틀과 본문 사이 간격(FHD 기준)
                  # 안내 박스 상/하 패딩(FHD 기준)
        # 폰트(px) — 페이지 전용(전역 typography와 별개로 미세 조정)
        "TITLE_FS": 30,
        "FORM_LABEL_FS": 21,      # 폼 라벨 폰트(px)
        "INPUT_FS": 21,           # 입력칸 폰트(px)
        "CHECK_FS": 18,           # 동의 체크 텍스트(px)
        "GUIDE_BODY_FS": 18,      # 상단 안내 본문(px)
        "NOTICE_FS": 18,          # 하단 노트(px)
        "LE_CLEAR_W": 18,          # 클리어 버튼 한 변(px)
        "LE_CLEAR_MX": 12,         # 클리어 버튼 우측 여백(px)
        "TOAST_FS": 21,           # 토스트 폰트(px)
        "TOAST_PAD": 12,          # 토스트 내부 패딩(px)
        "TOAST_RADIUS": 24,       # 토스트 라운드(px)
        "TOAST_MBY": 48,          # 하단에서 띄울 오프셋(px)
        "TOAST_DUR_MS": 1200,     # 토스트 표시 시간(ms)
        "TOAST_FADE_MS": 198,    # 토스트 페이드 인/아웃(ms) ≈0.2s
        "TOAST_UP":  504,        # (미사용) 과거 하단 위치 오프셋
        "TOAST_OX": 0,          # 중앙 기준 X 오프셋
        "TOAST_OY": 0           # 중앙 기준 Y 오프셋,        # 기본 위치에서 추가 상향(px, 약 500)

    }

    # 기능 시작: 3의 배수 내림 스냅
    @staticmethod
    def _snap3(v: float) -> int:
        vi = int(v)
        return (vi // 3) * 3

    # 기능 시작: 페이지 토큰 빌드(3:4:6 적용)
    def _build_page_tokens(self) -> None:
        app = QApplication.instance()
        TOK = (app.property("TYPO_TOKENS") or {}) if app else {}
        scale = float(TOK.get("scale", 1.0)) if isinstance(TOK, dict) else 1.0
        grid  = int(TOK.get("grid", 3)) if isinstance(TOK, dict) else 3
        P = {k: self._snap3(v * scale) for k, v in self._P_FHD.items()}
        P["GRID"], P["SCALE"] = grid, scale
        self.P = P

    #─────────────────────────────────────
    #  초기화
    #─────────────────────────────────────
    def __init__(self, theme, parent: Optional[QWidget] = None) -> None:
        super().__init__(theme, steps=APP_CONST.STEPS, active_index=0, parent=parent)

        # 토큰/팔레트 로드 + 페이지 토큰 빌드 + QSS 프리빌드
        self._refresh_tokens()
        self._build_page_tokens()
        self._rebuild_qss()

        # (삭제) 상단 여백 제거 — 타이틀과 가이드를 더 붙이기 위해 제거

        # ===== (1) 상단 타이틀 박스 =====
        self.guide_title = QFrame(self)
        self.guide_title.setObjectName("GuideTitleBox")
        self.guide_title.setStyleSheet(self._GUIDE_TITLE_QSS)
        gt_layout = QVBoxLayout(self.guide_title)
        gt_layout.setContentsMargins(self.P.get("TITLE_MX", self.P.get("COL_MX",24)), int(self.P.get("GUIDE_PAD_V",12)/2), self.P.get("TITLE_MX", self.P.get("COL_MX",24)), int(self.P.get("GUIDE_PAD_V",12)/2))
        gt_layout.setSpacing(0)
        self.g_title = QLabel()
        self.g_title.setTextFormat(Qt.RichText)
        self.g_title.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.g_title.setText(
            f"<div style='margin:0;padding:0;line-height:120%;font-size:{int(self.P.get('TITLE_FS',30))}px;font-weight:700;color:{self.C['text']};'>안내 및 약관</div>"
        )
        self.g_title.setContentsMargins(0, 0, 0, 0)
        gt_layout.addWidget(self.g_title)
        # 타이틀 높이 고정 + 남는 높이 흡수 방지
        self.guide_title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.g_title.adjustSize()
        _title_h = self._snap3(self.g_title.sizeHint().height() + int(self.P.get("GUIDE_PAD_V", 12)))
        self.guide_title.setFixedHeight(_title_h)

        # ===== (1-2) 상단 안내 박스(동적 높이) =====
        self.guide = QFrame(self)
        self.guide.setObjectName("GuideBox")
        self.guide.setStyleSheet(self._GUIDE_QSS)

        g_layout = QVBoxLayout(self.guide)
        _gpv = int(self.P.get("GUIDE_PAD_V", 12))
        g_layout.setContentsMargins(self.P.get("GUIDE_OUTER_MX", self.P.get("COL_MX",24)), _gpv, self.P.get("GUIDE_OUTER_MX", self.P.get("COL_MX",24)), _gpv)
        g_layout.setSpacing(0)

        self.guide_scroll = QScrollArea()
        self.guide_scroll.setWidgetResizable(True)
        self.guide_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.guide_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        guide_body = QWidget()
        gb_layout = QVBoxLayout(guide_body)
        gb_layout.setContentsMargins(self.P.get("GUIDE_BODY_MX", 9), 0, self.P.get("GUIDE_BODY_MX", 9), 0)
        gb_layout.setSpacing(0)

        self.guide_label = QLabel()
        self.guide_label.setTextFormat(Qt.RichText)
        self.guide_label.setWordWrap(True)
        self.guide_label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        raw_top = _s_input("top_guide", _DEFAULT_GUIDE_HTML)
        top_html = _html_from_plain_or_html(raw_top, "p")
        self.guide_label.setText(
            f"<div style='line-height:142%; font-size:{int(self.T.get('body',15))}px; color:{self.C['text']};'>{top_html}</div>"
        )
        gb_layout.addWidget(self.guide_label)
        gb_layout.addStretch(1)

        self.guide_scroll.setWidget(guide_body)
        g_layout.addWidget(self.guide_scroll, 1)

        # ===== (2) 스크롤 동의 체크 =====
        self.chkAgree = QCheckBox("위 사항을 모두 확인했으며, 이에 동의합니다.", self)
        self.chkAgree.setTristate(False)
        self.chkAgree.setStyleSheet(self._CHECK_QSS)
        self.chkAgree.setFont(theme.body_font(int(self.P.get("CHECK_FS", 18))))
        self.chkAgree.setEnabled(True)

        # ===== (3) 입력 폼 =====
        form = QWidget(self)
        fl = QFormLayout(form)
        fl.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        fl.setContentsMargins(self.P.get("FORM_MX", 0), 0, self.P.get("FORM_MX", 0), 0)
        fl.setHorizontalSpacing(self.P.get("FORM_HGAP", 15))
        fl.setVerticalSpacing(self.P.get("FORM_VGAP", 12))

        # 라인에딧별 클리어 버튼 레지스트리
        self._clear_btns = {}  # QLineEdit -> QToolButton 매핑

        self.name   = QLineEdit(); self._style_lineedit(self.name)
        self.phone  = QLineEdit(); self._style_lineedit(self.phone)
        self.email1 = QLineEdit(); self._style_lineedit(self.email1)
        self.email2 = QLineEdit(); self._style_lineedit(self.email2)

        self.name.setPlaceholderText("예) 홍길동")
        self.phone.setPlaceholderText("전화번호 뒷자리 4자리 (숫자만)")
        self.phone.setMaxLength(4)
        self.phone.setValidator(QRegularExpressionValidator(QRegularExpression(r"^\d{0,4}$"), self.phone))
        self.email1.setPlaceholderText("예) you@example.com")
        self.email2.setPlaceholderText("예) backup@example.com (선택)")

        def _lbl(text: str) -> QLabel:
            lab = QLabel(text, form)
            lab.setFont(self.theme.body_font(int(self.P.get("FORM_LABEL_FS", 18))))
            lab.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lab.setMinimumHeight(int(self.P.get("LE_H", 48)))  # 입력칸과 수직 정렬
            lab.setStyleSheet(f"color:{self.C['subtext']};")
            return lab

        l1=_lbl("이름"); l2=_lbl("전화번호"); l3=_lbl("이메일주소1"); l4=_lbl("이메일주소2")
        self._form_labels=[l1,l2,l3,l4]
        fl.addRow(l1, self.name)
        fl.addRow(l2, self.phone)
        fl.addRow(l3, self.email1)
        fl.addRow(l4, self.email2)

        # ===== (4) 하단 안내 노트 — 자동높이 =====
        notice = QFrame(self)
        notice.setObjectName("Notice")
        notice.setStyleSheet(self._NOTICE_QSS)
        notice.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        nv = QVBoxLayout(notice)
        nv.setContentsMargins(self.P.get("NOTICE_MX", self.P.get("COL_MX",24)), int(self.S.get("pad_v",12)*1.5), self.P.get("NOTICE_MX", self.P.get("COL_MX",24)), int(self.S.get("pad_v",12)*1.5))
        nv.setSpacing(0)
        self._notice_label = QLabel(); self._notice_label.setObjectName("NoticeText")
        self._notice_label.setTextFormat(Qt.RichText); self._notice_label.setWordWrap(True); self._notice_label.setAlignment(Qt.AlignCenter)
        raw_bottom = _s_input("bottom_guide", _DEFAULT_BOTTOM_GUIDE)
        bottom_html = _html_from_plain_or_html(raw_bottom, "div")
        self._notice_label.setText(
            f"<div style='text-align:center; line-height:120%; font-size:{int(self.T.get('label',18))}px;'>{bottom_html}</div>"
        )
        nv.addWidget(self._notice_label)

        # ===== (5) 센터 컬럼(상단 정렬 + 폭 확장) =====
        center = QWidget(self); cv = QVBoxLayout(center)
        cv.setSpacing(self.S.get("gap", 12)); cv.setContentsMargins(0, 0, 0, 0)

        column = QWidget(center)
        column.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        colv = QVBoxLayout(column)
        colv.setContentsMargins(self.P.get("COL_MX",24), 0, self.P.get("COL_MX",24), 0)
        colv.setSpacing(max(1, int(self.S.get("gap",12)/2)))
        # 타이틀은 GuideBox 내부로 이동했고 top_spacer는 제거됨
        colv.addSpacing(self.P.get("GAP_TOP_TO_TITLE", self.P.get("GUIDE_TOP_GAP", 12)))
        colv.addWidget(self.guide_title)
        colv.addSpacing(self.P.get("GAP_TITLE_TO_GUIDE", self.P.get("GUIDE_TITLE_GAP", 9)))
        colv.addWidget(self.guide)
        colv.addSpacing(self.P.get("GAP_GUIDE_TO_AGREE", 12))
        colv.addWidget(self.chkAgree)
        colv.addSpacing(self.P.get("GAP_AGREE_TO_FORM", 36))
        colv.addWidget(form)
        colv.addSpacing(self.P.get("GAP_FORM_TO_NOTICE", 24))
        colv.addWidget(notice)
        colv.addStretch(1)  # 남는 높이는 빈 공간으로만 처리

        cv.addWidget(column)

        # ----- 토스트 위젯(하단 중앙, 기본 숨김) -----
        self._toast = QFrame(self)
        self._toast.setObjectName("Toast")
        self._toast.setStyleSheet(self._TOAST_QSS)
        self._toast_label = QLabel(self._toast)
        self._toast_label.setAlignment(Qt.AlignCenter)
        self._toast_label.setWordWrap(False)
        self._toast_label.setTextFormat(Qt.PlainText)
        self._toast.hide()
        self._toast_last = ""
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        # Fade 효과 구성
        self._toast_fx = QGraphicsOpacityEffect(self._toast)
        self._toast.setGraphicsEffect(self._toast_fx)
        self._toast_fx.setOpacity(0.0)
        self._toast_anim = QPropertyAnimation(self._toast_fx, b"opacity", self)
        self._toast_anim.setDuration(int(self.P.get("TOAST_FADE_MS", 198)))
        self._toast_timer.timeout.connect(self._fade_out_toast)

        # 바깥 여백 — 페이지 자체 좌/우 마진 제거(전역 BasePage/Theme.chrome 위임)
        #─────────────────────────────────────
        #  페이지는 상/하 간격만 내부적으로 관리하고, 좌/우 마진은 전역 정책(side_margin)에 위임한다.
        self.setCentralWidget(
            center,
            margin=(0, 0, 0, 0),   # ← 좌/우/상/하 모두 0. 외곽 마진은 BasePage에서 처리
            spacing=self.S.get("gap",12)*2,  # 내부 위아래 간격만 유지(3의 배수)
            center=False,
        )

        # 상단 스텝바 여백 압축
        self._squash_stepbar_gap()

        # ===== (6) 시그널/상태 =====
        for w in (self.name, self.phone, self.email1, self.email2):
            w.textChanged.connect(self._validate)
            w.installEventFilter(self)
        self.chkAgree.stateChanged.connect(self._validate)

        sb = self.guide_scroll.verticalScrollBar()
        sb.valueChanged.connect(lambda _: self._on_guide_scrolled(sb))

        # Next 클릭 훅 연결(유효성 실패 시 토스트)
        try:
            self.footer.go_next.connect(self._on_next_clicked)
        except Exception:
            pass
        sb.rangeChanged.connect(lambda *_: self._on_guide_scrolled(sb))
        self._on_guide_scrolled(sb)

        self.set_next_enabled(False)
        self._validate()

        mw = self.window()
        sheet = getattr(mw, "kbd_sheet", None)
        if sheet:
            sheet.completed.connect(self._on_keyboard_completed)

        # 초기 안내 높이 산정 + 설정 변경 브로드캐스트 구독
        self._apply_dynamic_guide_height()
        settings_bus.changed.connect(self._on_settings_changed)
        self._on_settings_changed(None)

    #─────────────────────────────────────
    #  페이지 진입 시 항상 초기화
    #─────────────────────────────────────
    def showEvent(self, e):
        super().showEvent(e)
        try:
            self.name.clear(); self.phone.clear(); self.email1.clear(); self.email2.clear()
            self.chkAgree.setChecked(False); self.chkAgree.setEnabled(True)
            sb = self.guide_scroll.verticalScrollBar(); sb.setValue(sb.minimum())
        except Exception:
            pass
        self.set_prev_mode("enabled")
        # Next 버튼은 항상 클릭 가능. 스타일만 비활성 표현
        self._validate()
        self.set_next_enabled(True)

    #─────────────────────────────────────
    #  런타임 토큰/팔레트 로드
    #─────────────────────────────────────
    def _refresh_tokens(self) -> None:
        """qApp 프로퍼티에서 토큰 로드 + 폴백 채움"""
        app = QApplication.instance()
        TOK = (app.property("TYPO_TOKENS") or {}) if app else {}
        self.T = TOK.get("typography", {}) if isinstance(TOK, dict) else {}
        self.B = TOK.get("borders", {}) if isinstance(TOK, dict) else {}
        self.R = TOK.get("radii",   {}) if isinstance(TOK, dict) else {}
        self.S = TOK.get("spacing", {}) if isinstance(TOK, dict) else {}
        self.C = (app.property("THEME_COLORS") or {}) if app else {}
        # 폴백(3의 배수 근사)
        self.T.setdefault("body", 15); self.T.setdefault("label", 18); self.T.setdefault("h5", 27)
        self.B.setdefault("thin", 2); self.B.setdefault("hairline", 1)
        self.R.setdefault("radius", 3)
        self.S.setdefault("gap", 12); self.S.setdefault("pad_v", 12); self.S.setdefault("pad_h", 12); self.S.setdefault("checkbox", 15)
        self.C.setdefault("text", "#1A1A1A"); self.C.setdefault("subtext", "#666"); self.C.setdefault("primary", "#FFA9A9"); self.C.setdefault("border", "#EDEDED"); self.C.setdefault("card", "#FFF")

    #─────────────────────────────────────
    #  QSS 문자열 재생성
    #─────────────────────────────────────
    def _rebuild_qss(self) -> None:
        """토큰 기반 QSS 문자열 구성(삼중따옴표, 한 덩어리)"""
        padv, padh, gap = int(self.S.get("pad_v",12)), int(self.S.get("pad_h",12)), int(self.S.get("gap",12))
        radius = int(self.R.get("radius",3)); thin = int(self.B.get("thin",2))
        fs_input = int(self.P.get("INPUT_FS", 21))
        cb = int(self.S.get("checkbox",15))

        self._LINEEDIT_QSS = f"""
        QLineEdit {{
            border: {thin}px solid {self.C['primary']};
            border-radius: {radius}px;
            padding: {padv}px {padh}px;
            background: #FFF;
            color: {self.C['text']};
            font-size: {fs_input}px;
        }}
        QLineEdit::placeholder {{ color:#BDBDBD; }}
        """

        self._CHECK_QSS = f"""
        QCheckBox {{ color:{self.C['subtext']}; spacing:{gap}px; }}
        QCheckBox::indicator {{
            width: {cb}px; height: {cb}px;
            border: {thin}px solid {self.C['primary']};
            border-radius: {radius}px; background: transparent;
        }}
        QCheckBox::indicator:checked {{ background: {self.C['primary']}; }}
        """

        self._GUIDE_QSS = f"""
        QFrame#GuideBox {{
            border: {thin}px solid {self.C['primary']};
            border-radius: {radius}px; background: #FFFFFF;
        }}
        QScrollArea {{ border:none; background:transparent; }}
        QScrollBar:vertical {{ width: {int(self.P.get('SCROLL_W', 9))}px; }}
        QScrollBar::handle:vertical {{ background: {self.C['primary']}; min-height: {int(self.P.get('SCROLL_HANDLE_MINH', 48))}px; border-radius: {radius}px; }}
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height:0; }}
        """

        self._GUIDE_TITLE_QSS = f"""
        QFrame#GuideTitleBox {{
            border: none; background: transparent;
        }}
        QFrame#GuideTitleBox * {{ background: transparent; }}
        """

        # 분홍 동그라미 + 하얀 × 버튼 스타일
        _side = int(self.P.get('LE_CLEAR_W', 18))
        _fs_clear = max(12, self._snap3(int(_side * 0.6)))
        _rad = int(_side // 2)
        self._CLEAR_BTN_QSS = f"""
        QToolButton#LineClearBtn {{
            border: none;
            border-radius: {_rad}px;
            background-color: {self.C['primary']};
            color: #FFFFFF;
            font-weight: 800;
            font-size: {_fs_clear}px;
            padding: 0px;
            min-width: {_side}px;
            min-height: {_side}px;
        }}
        QToolButton#LineClearBtn:hover {{
            background-color: {self.C['primary']};
        }}
        """

        self._NOTICE_QSS = f"""
        QFrame#Notice {{ background: {self.C['primary']}; border: {thin}px solid {self.C['primary']}; border-radius: 24px; }}
        QFrame#Notice * {{ background:transparent; }}
        QLabel#NoticeText {{ color:#111; }}
        """

        # 토스트 QSS
        _tp = int(self.P.get('TOAST_PAD', 12)); _tr = int(self.P.get('TOAST_RADIUS', 12)); _tfs = int(self.P.get('TOAST_FS', 15))
        _tp_h = _tp * 2  # 좌우 패딩 2배
        _tp_v = _tp      # 상하 패딩 유지
        self._TOAST_QSS = f"""
        QFrame#Toast {{
            background: rgba(50,50,50,0.68);
            border-radius: {_tr}px;
            padding: {_tp_v}px {_tp_h}px;
        }}
        QFrame#Toast * {{ background:transparent; color:#FFFFFF; font-size:{_tfs}px; }}
        """

    #─────────────────────────────────────
    #  런타임 토큰 적용
    #─────────────────────────────────────
    def _apply_runtime_tokens(self) -> None:
        # 페이지 토큰 재생성(스케일 변동 대비)
        self._build_page_tokens()
        # 라인에딧 공통 QSS 재적용
        for name in self._LINE_EDITS:
            le: QLineEdit = getattr(self, name)
            le.setStyleSheet(self._LINEEDIT_QSS)
        # 체크박스/가이드/노티스 QSS 재적용
        self.chkAgree.setStyleSheet(self._CHECK_QSS)
        self.guide.setStyleSheet(self._GUIDE_QSS)
        if hasattr(self, "guide_title"):
            self.guide_title.setStyleSheet(self._GUIDE_TITLE_QSS)
        if hasattr(self, "_notice_label") and isinstance(self._notice_label, QLabel):
            self._notice_label.parentWidget().setStyleSheet(self._NOTICE_QSS)
        # 클리어 버튼 QSS/재배치
        for le, btn in getattr(self, "_clear_btns", {}).items():
            btn.setStyleSheet(self._CLEAR_BTN_QSS)
            self._position_clear_button(le)
            self._toggle_clear_button(le)
        # 폰트 반영
        self.chkAgree.setFont(self.theme.body_font(int(self.P.get("CHECK_FS", 18))))
        for lab in getattr(self, "_form_labels", []):
            lab.setFont(self.theme.body_font(int(self.P.get("FORM_LABEL_FS", 18))))
            lab.setMinimumHeight(int(self.P.get("LE_H", 48)))
        # 안내/하단문 재적용
        self._reload_guides()

    #─────────────────────────────────────
    #  안내문 텍스트 재생성(설정 변경 대응)
    #─────────────────────────────────────
    def _reload_guides(self) -> None:
        """settings.input 의 guide 텍스트를 현재 토큰 폰트/색으로 다시 그린다."""
        # 상단 안내
        try:
            raw_top = _s_input("top_guide", _DEFAULT_GUIDE_HTML)
            top_html = _html_from_plain_or_html(raw_top, "p")
            fs_body = int(self.P.get("GUIDE_BODY_FS", 15))
            self.guide_label.setText(
                f"<div style='line-height:142%; font-size:{fs_body}px; color:{self.C.get('text', '#111')};'>{top_html}</div>"
            )
        except Exception:
            pass
        # 하단 노트
        try:
            raw_bottom = _s_input("bottom_guide", _DEFAULT_BOTTOM_GUIDE)
            bottom_html = _html_from_plain_or_html(raw_bottom, "div")
            fs_label = int(self.P.get("NOTICE_FS", 18))
            self._notice_label.setText(
                f"<div style='text-align:center; line-height:120%; font-size:{fs_label}px;'>{bottom_html}</div>"
            )
        except Exception:
            pass

    #─────────────────────────────────────
    #  설정 변경 브로드캐스트 콜백
    #─────────────────────────────────────
    def _on_settings_changed(self, _effective=None):
        self._refresh_tokens(); self._build_page_tokens(); self._rebuild_qss(); self._apply_runtime_tokens(); self._apply_dynamic_guide_height()
        try:
            self._toast_anim.setDuration(int(self.P.get("TOAST_FADE_MS", 198)))
        except Exception:
            pass

    #─────────────────────────────────────
    #  라인에딧 공통 스타일 적용
    #─────────────────────────────────────
    def _style_lineedit(self, le: QLineEdit) -> None:
        # 역할: 공통 라인에딧 QSS/크기 + 커스텀 클리어 버튼 장착
        """v1.1 2025-09-19: 기본 clearButton 비활성 후 QToolButton 기반 커스텀 적용"""
        le.setStyleSheet(self._LINEEDIT_QSS)
        le.setClearButtonEnabled(False)  # 기본 X 숨김
        le.setFixedHeight(self.P.get("LE_H", 48))

        # 커스텀 클리어 버튼 생성 및 연결
        btn = QToolButton(le)
        btn.setObjectName("LineClearBtn")
        btn.setCursor(Qt.ArrowCursor)
        btn.setFocusPolicy(Qt.NoFocus)
        btn.setAutoRaise(True)
        btn.setAttribute(Qt.WA_StyledBackground, True)
        btn.setStyleSheet(self._CLEAR_BTN_QSS)
        side = int(self.P.get("LE_CLEAR_W", 18))
        btn.setText("✕")
        btn.setContentsMargins(0, 0, 0, 0)
        btn.clicked.connect(le.clear)
        btn.hide()
        self._clear_btns[le] = btn
        self._position_clear_button(le)
        # 텍스트 변화 시 표시 토글
        le.textChanged.connect(lambda s, _le=le: self._toggle_clear_button(_le))

    #─────────────────────────────────────
    #  클리어 버튼 유틸
    #─────────────────────────────────────
    # 역할: 커스텀 클리어 버튼 위치/가시성 관리
    def _position_clear_button(self, le: QLineEdit) -> None:
        try:
            btn = self._clear_btns.get(le)
            if not btn:
                return
            side = int(self.P.get("LE_CLEAR_W", 18))
            mx = int(self.P.get("LE_CLEAR_MX", 9))
            h = le.height()
            s = min(side, h - 2)  # 과도한 침범 방지
            x = le.width() - s - mx
            y = max(0, (h - s) // 2)
            btn.setFixedSize(s, s)
            btn.move(x, y)
            # 텍스트 영역 우측 여백 확보
            le.setTextMargins(0, 0, mx + s, 0)
        except Exception:
            pass

    def _toggle_clear_button(self, le: QLineEdit) -> None:
        try:
            btn = self._clear_btns.get(le)
            if not btn:
                return
            btn.setVisible(bool(le.text()))
        except Exception:
            pass

    #─────────────────────────────────────
    #  Next 클릭 핸들러
    #─────────────────────────────────────
    # 역할: 유효성 성공 시 다음 단계로, 실패 시 토스트 표시
    def _on_next_clicked(self):
        if self._validation_ok():
            self.go_next.emit()
        else:
            self._show_toast(self._validation_reason())

    # 유효성 현재 상태 반환
    def _validation_ok(self) -> bool:
        name_ok   = len(self.name.text().strip()) >= 1
        phone_ok  = self.phone.text().isdigit() and len(self.phone.text()) == 4
        email1_ok = bool(EMAIL_RE.match(self.email1.text().strip()))
        e2        = self.email2.text().strip()
        email2_ok = True if not e2 else bool(EMAIL_RE.match(e2))
        agree_ok  = self.chkAgree.isChecked() and self.chkAgree.isEnabled()
        return name_ok and phone_ok and email1_ok and email2_ok and agree_ok

    # 실패 사유 메시지 생성(우선순위 규칙)
    def _validation_reason(self) -> str:
        # 순서: 체크박스 → 이름 → 전화번호 → 이메일1 → 이메일2 → 기타
        if not (self.chkAgree.isChecked() and self.chkAgree.isEnabled()):
            return "안내 및 약관에 동의가 필요합니다. 체크해 주세요."
        if not len(self.name.text().strip()) >= 1:
            return "이름을 입력해 주세요."
        if not (self.phone.text().isdigit() and len(self.phone.text()) == 4):
            return "전화번호는 숫자 4자리로 입력해 주세요."
        if not self.email1.text().strip() or not EMAIL_RE.match(self.email1.text().strip()):
            return "이메일 주소를 다시 확인해 주세요."
        e2 = self.email2.text().strip()
        if e2 and not EMAIL_RE.match(e2):
            return "보조 이메일 주소를 다시 확인해 주세요."
        return "입력 값을 확인해 주세요."

    # 토스트 표시/위치 갱신
    def _show_toast(self, msg: str) -> None:
        try:
            self._toast.setStyleSheet(self._TOAST_QSS)
            self._toast_last = msg
            # 한 줄, 줄바꿈 없음. 폭은 텍스트 길이에 맞추되 화면을 넘지 않도록 엘라이드 처리
            lab = self._toast_label
            lab.setWordWrap(False)
            lab.setTextFormat(Qt.PlainText)
            fm = lab.fontMetrics()
            pad_base = int(self.P.get("TOAST_PAD",12))
            pad_h = pad_base * 2  # 좌우 2배
            pad_v = pad_base      # 상하 동일
            w = self.width(); h = self.height()
            max_w = max(60, w - 2 * int(self.S.get("pad_h",12)))
            max_text_w = max(30, max_w - 2 * pad_h)
            elided = fm.elidedText(msg, Qt.ElideRight, max_text_w)
            lab.setText(elided)
            text_w = min(fm.horizontalAdvance(elided), max_text_w)
            text_h = fm.height()
            tw = text_w + 2 * pad_h
            th = text_h + 2 * pad_v
            x = max(0, (w - tw) // 2)
            footer_h = 0
            try:
                f = getattr(self, "footer", None)
                footer_h = f.height() if f else 0
            except Exception:
                footer_h = 0
            y = max(0, h - footer_h - th - int(self.P.get("TOAST_MBY",36)))
            self._toast.setGeometry(x, y, tw, th)
            lab.setGeometry(0, 0, tw, th)
            if not self._toast.isVisible():
                self._fade_in_toast()
            else:
                try:
                    self._toast_anim.stop()
                    try:
                        self._toast_anim.finished.disconnect(self._hide_toast)
                    except Exception:
                        pass
                    self._toast_fx.setOpacity(1.0)
                    self._toast.show(); self._toast.raise_()
                except Exception:
                    pass
            self._toast_timer.stop()
            self._toast_timer.start(int(self.P.get("TOAST_DUR_MS", 1200)))
        except Exception:
            pass

    # Fade 유틸리티
    def _fade_in_toast(self) -> None:
        try:
            self._toast_anim.stop()
            self._toast_fx.setOpacity(0.0)
            self._toast.show(); self._toast.raise_()
            self._toast_anim.setStartValue(0.0)
            self._toast_anim.setEndValue(1.0)
            self._toast_anim.setDuration(int(self.P.get("TOAST_FADE_MS", 198)))
            self._toast_anim.start()
        except Exception:
            pass

    def _hide_toast(self) -> None:
        try:
            self._toast.hide()
            self._toast_fx.setOpacity(0.0)
        except Exception:
            pass

    def _fade_out_toast(self) -> None:
        try:
            self._toast_anim.stop()
            try:
                self._toast_anim.finished.disconnect(self._hide_toast)
            except Exception:
                pass
            self._toast_anim.setStartValue(self._toast_fx.opacity())
            self._toast_anim.setEndValue(0.0)
            self._toast_anim.setDuration(int(self.P.get("TOAST_FADE_MS", 198)))
            self._toast_anim.finished.connect(self._hide_toast)
            self._toast_anim.start()
        except Exception:
            self._hide_toast()

    # 토스트 재배치(타이머/애니메이션은 건드리지 않음)
    def _reposition_toast(self) -> None:
        try:
            if not self._toast.isVisible():
                return
            w, h = self.width(), self.height()
            tw, th = self._toast.width(), self._toast.height()
            footer_h = 0
            try:
                f = getattr(self, "footer", None)
                footer_h = f.height() if f else 0
            except Exception:
                footer_h = 0
            x = max(0, (w - tw) // 2)
            y = max(0, h - footer_h - th - int(self.P.get("TOAST_MBY",36)))
            self._toast.move(x, y)
            self._toast_label.setGeometry(0, 0, tw, th)
        except Exception:
            pass

    # 리사이즈 시 토스트 위치 보정
    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self._toast.isVisible():
            self._reposition_toast()

    #─────────────────────────────────────
    #  안내 박스 높이: 페이지 토큰(GUIDE_H) 고정
    #─────────────────────────────────────
    # 역할: 가이드박스 높이를 페이지 토큰으로 고정(3:4:6 스케일 적용됨)
    def _apply_dynamic_guide_height(self) -> None:
        try:
            h = int(self.P.get("GUIDE_H", 540))  # FHD 540 / QHD 720 / UHD 1080 (스냅 적용)
        except Exception:
            h = 540
        self.guide.setFixedHeight(h)

    #─────────────────────────────────────
    #  상단 스텝바 여백 압축
    #─────────────────────────────────────
    def _squash_stepbar_gap(self) -> None:
        try:
            root_layout = self.layout()
            if root_layout:
                root_layout.setSpacing(0)
                cm = root_layout.contentsMargins()
                root_layout.setContentsMargins(cm.left(), 0, cm.right(), cm.bottom())
        except Exception:
            pass

    # (정리) 리사이즈 시 안내 높이 재계산 — 고정 높이 토큰으로 대체했으므로 제거

    #─────────────────────────────────────
    #  포커스 시 가상 키보드 시트 열기
    #─────────────────────────────────────
    def eventFilter(self, obj, ev):
        if ev.type() in (QEvent.MouseButtonPress, QEvent.FocusIn):
            mw = self.window(); sheet = getattr(mw, "kbd_sheet", None)
            if sheet:
                if obj is self.name:
                    sheet.open(KeyboardMode.NAME, self.name)
                elif obj is self.phone:
                    sheet.open(KeyboardMode.PHONE, self.phone)
                elif obj in (self.email1, self.email2):
                    sheet.open(KeyboardMode.EMAIL, obj)
        # 리사이즈 시 클리어 버튼 위치 재계산
        if ev.type() == QEvent.Resize and isinstance(obj, QLineEdit):
            self._position_clear_button(obj)
        return super().eventFilter(obj, ev)

    #─────────────────────────────────────
    #  스크롤 맨끝 도달 시 동의 체크 가능
    #─────────────────────────────────────
    def _on_guide_scrolled(self, sb) -> None:
        # 읽기 진행에 따른 강제 제약 제거. 체크박스는 항상 활성 상태.
        self._validate()

    #─────────────────────────────────────
    #  입력값 검증 + Next 버튼 활성
    #─────────────────────────────────────
    def _validate(self) -> None:
        name_ok   = len(self.name.text().strip()) >= 1
        phone_ok  = self.phone.text().isdigit() and len(self.phone.text()) == 4
        email1_ok = bool(EMAIL_RE.match(self.email1.text().strip()))
        e2        = self.email2.text().strip()
        email2_ok = True if not e2 else bool(EMAIL_RE.match(e2))
        agree_ok  = self.chkAgree.isChecked() and self.chkAgree.isEnabled()
        ok = name_ok and phone_ok and email1_ok and email2_ok and agree_ok
        # 버튼은 항상 클릭 가능. 스타일로만 상태 표현
        self.set_next_enabled(True)
        self.set_next_mode("lit" if ok else "enabled")
        # 세션 미러(내부 상태로만 유지; 실제 커밋은 상위 네비게이션 훅에서)

    #─────────────────────────────────────
    #  네비게이션 훅 — Prev 시 세션 초기화, Next 시 커밋
    #─────────────────────────────────────
    def on_before_prev(self, session):
        for k in ("name", "phone", "email1", "email2"):
            try:
                session[k] = ""
            except Exception:
                pass
        return True

    def on_before_next(self, session):
        # 유효성 실패 시 네비게이션 차단 + 토스트 안내
        if not self._validation_ok():
            self._show_toast(self._validation_reason())
            return False
        session["name"]   = self.name.text().strip()
        session["phone"]  = self.phone.text().strip()
        session["email1"] = self.email1.text().strip()
        session["email2"] = self.email2.text().strip()
        return True

    #────────────────────────────────────-
    #  가상 키보드 완료 신호 처리
    #─────────────────────────────────────
    def _on_keyboard_completed(self) -> None:
        if self._validation_ok():
            self.go_next.emit()
        else:
            self._show_toast(self._validation_reason())

