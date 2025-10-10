# -*- coding: utf-8 -*-
# app/ui/virtual_keyboard.py — 가상 키보드(이름/전화/이메일)
# - 숫자패드 중앙 3x3 클러스터 + 마지막 행(⌫ 0 완료)
# - 이메일 도메인 칩 1행
# - 영문 Shift(대/소문자) 토글
# - 3:4:6 스냅 규칙 + 토큰식 DENSITY

from __future__ import annotations
from typing import Optional, Tuple

from PySide6.QtCore import Qt, Signal, QSize
from PySide6.QtGui import QFont, QFontMetrics
from PySide6.QtWidgets import (
    QApplication, QWidget, QPushButton, QHBoxLayout, QVBoxLayout, QSizePolicy,
    QGridLayout, QFrame, QLabel
)

# -------------------- 한글 조합 유틸 --------------------
CHOSEONG  = ["ㄱ","ㄲ","ㄴ","ㄷ","ㄸ","ㄹ","ㅁ","ㅂ","ㅃ","ㅅ","ㅆ","ㅇ","ㅈ","ㅉ","ㅊ","ㅋ","ㅌ","ㅍ","ㅎ"]
JUNGSEONG = ["ㅏ","ㅐ","ㅑ","ㅒ","ㅓ","ㅔ","ㅕ","ㅖ","ㅗ","ㅘ","ㅙ","ㅚ","ㅛ","ㅜ","ㅝ","ㅞ","ㅟ","ㅠ","ㅡ","ㅢ","ㅣ"]
JONGSEONG = ["","ㄱ","ㄲ","ㄳ","ㄴ","ㄵ","ㄶ","ㄷ","ㄹ","ㄺ","ㄻ","ㄼ","ㄽ","ㄾ","ㄿ","ㅀ","ㅁ","ㅂ","ㅄ","ㅅ","ㅆ","ㅇ","ㅈ","ㅊ","ㅋ","ㅌ","ㅍ","ㅎ"]
V_COMBINE = {("ㅗ","ㅏ"):"ㅘ",("ㅗ","ㅐ"):"ㅙ",("ㅗ","ㅣ"):"ㅚ",("ㅜ","ㅓ"):"ㅝ",("ㅜ","ㅔ"):"ㅞ",("ㅜ","ㅣ"):"ㅟ",("ㅡ","ㅣ"):"ㅢ"}
F_COMBINE = {("ㄱ","ㅅ"):"ㄳ",("ㄴ","ㅈ"):"ㄵ",("ㄴ","ㅎ"):"ㄶ",("ㄹ","ㄱ"):"ㄺ",("ㄹ","ㅁ"):"ㄻ",("ㄹ","ㅂ"):"ㄼ",
             ("ㄹ","ㅅ"):"ㄽ",("ㄹ","ㅌ"):"ㄾ",("ㄹ","ㅍ"):"ㄿ",("ㄹ","ㅎ"):"ㅀ",("ㅂ","ㅅ"):"ㅄ"}
F_SPLIT = {"ㄳ": ("ㄱ","ㅅ"), "ㄵ": ("ㄴ","ㅈ"), "ㄶ": ("ㄴ","ㅎ"),
           "ㄺ": ("ㄹ","ㄱ"), "ㄻ": ("ㄹ","ㅁ"), "ㄼ": ("ㄹ","ㅂ"),
           "ㄽ": ("ㄹ","ㅅ"), "ㄾ": ("ㄹ","ㅌ"), "ㄿ": ("ㄹ","ㅍ"),
           "ㅀ": ("ㄹ","ㅎ"), "ㅄ": ("ㅂ","ㅅ") }

def is_hangul_syllable(ch: str) -> bool:
    return 0xAC00 <= ord(ch) <= 0xD7A3

def compose_syllable(cho: str, jung: str, jong: str = "") -> str:
    i = CHOSEONG.index(cho); j = JUNGSEONG.index(jung); k = JONGSEONG.index(jong)
    return chr(0xAC00 + (i * 21 * 28) + (j * 28) + k)

def decompose_syllable(s: str) -> Tuple[str, str, str]:
    code = ord(s) - 0xAC00; i = code // (21 * 28); j = (code % (21 * 28)) // 28; k = code % 28
    return CHOSEONG[i], JUNGSEONG[j], JONGSEONG[k]

def is_consonant(j: str) -> bool:
    return j in CHOSEONG or j in JONGSEONG[1:]

def is_vowel(j: str) -> bool:
    return j in JUNGSEONG

def hangul_insert(prev: str, cur: int, jamo: str) -> Tuple[str, int]:
    if not jamo:
        return prev, cur
    L, R = prev[:cur], prev[cur:]
    last = L[-1] if L else ""
    if is_vowel(jamo):
        # 자음 단독 뒤 → 새 음절 생성
        if last and not is_hangul_syllable(last) and is_consonant(last):
            new = compose_syllable(last, jamo); out = L[:-1] + new + R
            return out, len(L)
        # 완성 음절 뒤
        if last and is_hangul_syllable(last):
            cho, jung, jong = decompose_syllable(last)
            if not jong:
                comb = V_COMBINE.get((jung, jamo))
                if comb:
                    out = L[:-1] + compose_syllable(cho, comb) + R; return out, len(L)
                out = L + jamo + R; return out, len(L) + len(jamo)
            # 종성 이동 규칙
            if jong in F_SPLIT:
                base, head = F_SPLIT[jong]
                left  = compose_syllable(cho, jung, base)
                right = compose_syllable(head, jamo)
            else:
                left  = compose_syllable(cho, jung)
                right = compose_syllable(jong, jamo)
            out = L[:-1] + left + right + R
            return out, len(L[:-1] + left + right)
    if is_consonant(jamo):
        if last and is_hangul_syllable(last):
            cho, jung, jong = decompose_syllable(last)
            if not jong:
                out = L[:-1] + compose_syllable(cho, jung, jamo) + R; return out, len(L)
            comb = F_COMBINE.get((jong, jamo))
            if comb:
                out = L[:-1] + compose_syllable(cho, jung, comb) + R; return out, len(L)
        out = L + jamo + R; return out, len(L) + len(jamo)
    out = L + jamo + R; return out, len(L) + len(jamo)

# -------------------- 모드 --------------------
class KeyboardMode:
    NAME  = "name"
    PHONE = "phone"
    EMAIL = "email"

# -------------------- 본체 --------------------
class VirtualKeyboard(QWidget):
    """가상 키보드: 이름/전화/이메일"""
    done = Signal()  # 완료

    # 밀도/치수 토큰(FHD 기준)
    DENSITY = dict(
        row_h=66, gap=12, outer=12, key_h=48, func_h=48,
        font_key=18, font_func=18, font_hdr=21, radius=6,
        phone_key_min_w=120  # 숫자패드 각 키의 최소 폭(FHD 기준)
    )
    _COLS = 10

    def __init__(self, theme, parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.theme   = theme
        self._target: Optional[QWidget] = None
        self._mode   = KeyboardMode.NAME
        self._name_lang = "ko"
        self._korean_shift = False
        self._en_shift = False

        # 루트 레이아웃
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(14, 12, 14, 12)
        self.root.setSpacing(8)

        # 헤더
        self.header = QHBoxLayout()
        self.header.setContentsMargins(0, 0, 0, 0)
        self.header.setSpacing(8)
        self.title = QLabel("키보드")
        self.header.addWidget(self.title)
        self.header.addStretch(1)

        # 메인 그리드
        self.grid_host = QFrame()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(self.DENSITY["gap"])
        self.grid.setVerticalSpacing(self.DENSITY["gap"])

        # 조립
        self.root.addLayout(self.header)
        self.root.addWidget(self.grid_host)

        # 초기 빌드
        self._apply_qss()
        self._rebuild(KeyboardMode.NAME)

    # ---------- 유틸 ----------
    def _snap3(self, v: int) -> int:
        app = QApplication.instance()
        TOK = (app.property("TYPO_TOKENS") or {}) if app else {}
        scale = float(TOK.get("scale", 1.0) or 1.0)
        x = int(v * scale)
        return (x // 3) * 3

    def _scale_line(self, px: int) -> int:
        """Scale 1px/2px style lines without 3-multiple snapping (1/1/2, 2/3/4)."""
        app = QApplication.instance()
        TOK = (app.property("TYPO_TOKENS") or {}) if app else {}
        scale = float(TOK.get("scale", 1.0) or 1.0)
        val = int(round(px * scale))
        return max(1, val)

    def _iter_buttons(self):
        return self.grid_host.findChildren(QPushButton)

    # 외부 API
    def attach(self, target: QWidget) -> None:
        self._target = target

    def set_mode(self, mode: str) -> None:
        if mode not in (KeyboardMode.NAME, KeyboardMode.PHONE, KeyboardMode.EMAIL):
            return
        self._rebuild(mode)

    def open(self, mode: Optional[str] = None, target: Optional[QWidget] = None) -> int:
        if target is not None:
            self._target = target
        if mode:
            self.set_mode(mode)
        self.show()
        return self.preferred_height()

    # ---------- 스타일/QSS ----------
    def _apply_qss(self) -> None:
        d = self.DENSITY
        gap = self._snap3(d["gap"])
        outer = self._snap3(d["outer"])

        # layout paddings / spacing
        self.root.setContentsMargins(outer, outer, outer, outer)
        self.root.setSpacing(gap)
        self.grid.setHorizontalSpacing(gap)
        self.grid.setVerticalSpacing(gap)

        # grid row/column stretch
        rows = self._row_count_for_mode()
        for r in range(10):
            self.grid.setRowMinimumHeight(r, 0)
            self.grid.setRowStretch(r, 0)
        for r in range(rows):
            self.grid.setRowMinimumHeight(r, self._snap3(d["row_h"]))
            self.grid.setRowStretch(r, 1)
        for c in range(self._COLS):
            self.grid.setColumnStretch(c, 1)

        # fonts
        self.title.setFont(self.theme.body_font(self._snap3(d["font_hdr"])) )

        # --- dynamic QSS (theme colors) ---
        app = QApplication.instance()
        C = getattr(self.theme, "COLORS", None) or (app.property("THEME_COLORS") if app else {}) or {}
        primary = C.get("primary", "#f4a6a6")
        primary_hover = C.get("primary_hover", primary)
        border = C.get("border", primary)
        text = C.get("text", "#222")
        surface = C.get("surface", "#fff")
        card = C.get("card", "#fff")

        rad = self._scale_line(d.get("radius", 6))
        bw  = self._scale_line(2)

        # apply role-based style
        self.setStyleSheet(
            f"""
            /* header */
            QLabel {{ color: {text}; }}

            QPushButton[role="key"] {{
                background: {surface};
                color: {text};
                border: {bw}px solid {border};
                border-radius: {rad}px;
            }}
            QPushButton[role="key"]:hover {{
                border-color: {primary_hover};
            }}

            QPushButton[role="primary"] {{
                background: {primary};
                color: #ffffff;
                border: {bw}px solid {primary};
                border-radius: {rad}px;
            }}

            /* toggle active (Shift / 쌍자음) */
            QPushButton[active="1"] {{
                background: {primary_hover};
                color: #ffffff;
                border-color: {primary};
            }}

            QPushButton[role="chip"] {{
                background: {card};
                color: {text};
                border: {bw}px solid {border};
                border-radius: {rad}px;
                padding-left: {self._snap3(9)}px; padding-right: {self._snap3(9)}px;
            }}
            """
        )

        # button size / font apply
        for w in self._iter_buttons():
            if not isinstance(w, QPushButton):
                continue
            role = w.property("role") or "key"
            h = self._snap3(d["func_h"]) if role == "primary" else self._snap3(d["key_h"])
            w.setMinimumHeight(h)
            pt = self._snap3(d["font_func"]) if role == "primary" else self._snap3(d["font_key"]) 
            w.setFont(self.theme.body_font(pt))
            if w.property("phone"):
                # phone pad: 유연 높이(행 스트레치로 분배) + 최소 폭 보장
                min_h = self._snap3(d["key_h"])  # 버튼 최소 높이만 보장
                w.setMinimumHeight(min_h)
                w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
                w.setMinimumWidth(self._snap3(d.get("phone_key_min_w", 120)))
            self._fit_font_to_btn(w)

    def _row_count_for_mode(self) -> int:
        return 6 if self._mode == KeyboardMode.EMAIL else 4

    def preferred_height(self) -> int:
        d = self.DENSITY
        rows = self._row_count_for_mode()
        grid_h = rows * d["row_h"] + (rows - 1) * d["gap"]
        header_h = d["outer"] + max(36, d["func_h"])
        return d["outer"] + header_h + grid_h + d["outer"]

    def sizeHint(self) -> QSize:
        h = self._snap3(self.preferred_height())
        return QSize(800, h)  # 폭은 컨테이너에 의해 결정됨

    # ---------- 빌드 ----------
    def _clear_grid(self) -> None:
        while self.grid.count():
            it = self.grid.takeAt(0)
            if it and it.widget():
                it.widget().deleteLater()

    def _rebuild(self, mode: str) -> None:
        self._clear_grid()
        self._mode = mode
        self._korean_shift = False
        self.title.setText({"name":"이름 입력","phone":"전화번호 뒤 4자리","email":"이메일"}[mode])

        if mode == KeyboardMode.PHONE:
            self._build_phone()
        elif mode == KeyboardMode.EMAIL:
            self._build_email()
        else:
            self._build_korean()

        self._apply_qss()

    def _add_span_row(self, r: int, cells):
        col = 0
        for cell in cells:
            if isinstance(cell, tuple):
                text, span, role = (cell + ("key",))[:3]
            else:
                text, span, role = cell, 1, "key"

            if not text:
                col += span
                continue

            insert = (role in {"key", "chip"}) and (text not in {"쌍자음","한/영","⌫","완료","스페이스","Shift"})
            btn_role = "primary" if text in {"⌫","완료"} else role
            b = self._mk_btn(text, role=btn_role, insert=insert)

            if text == "⌫":     b.clicked.connect(self._backspace)
            if text == "완료":   b.clicked.connect(self._on_done)
            if text == "쌍자음": b.clicked.connect(self._toggle_korean_shift)
            if text == "한/영":  b.clicked.connect(self._toggle_name_lang)
            if text == "Shift": b.clicked.connect(self._toggle_en_shift)

            self.grid.addWidget(b, r, col, 1, span)
            col += span
        self._refresh_toggle_styles()

    def _mk_btn(self, text: str, role: str = "key", insert: bool = True, phone: bool = False) -> QPushButton:
        b = QPushButton(text)
        b.setProperty("role", role)
        if phone:
            b.setProperty("phone", True)
        b.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        if insert:
            if role == "chip":
                b.clicked.connect(lambda _, d=text: self._chip_insert(d))
            else:
                b.clicked.connect(lambda _, t=text: self._on_key(t))
        return b

    def _build_korean(self) -> None:
        if self._name_lang == "ko":
            rows = [
                list("ㅂㅈㄷㄱㅅㅛㅕㅑㅐㅔ"),
                list("ㅁㄴㅇㄹㅎㅗㅓㅏㅣ·"),
                list("ㅋㅌㅊㅍㅠㅜㅡ") + ["","",""],
                [("쌍자음",2,"key"), ("한/영",2,"key"), ("스페이스",4,"key"), ("⌫",1,"primary"), ("완료",1,"primary")],
            ]
        else:
            row1 = list("qwertyuiop")
            row2 = list("asdfghjkl")
            row3 = list("zxcvbnm")
            if self._en_shift:
                row1 = [c.upper() for c in row1]
                row2 = [c.upper() for c in row2]
                row3 = [c.upper() for c in row3]
            rows = [
                row1,
                row2 + [""],
                row3 + ["","",""],
                [("Shift",2,"key"), ("한/영",2,"key"), ("스페이스",4,"key"), ("⌫",1,"primary"), ("완료",1,"primary")],
            ]
        for i, row in enumerate(rows):
            self._add_span_row(i, row)

    def _build_phone(self) -> None:
        host = QWidget(self)
        hbox = QHBoxLayout(host)
        hbox.setContentsMargins(0, 0, 0, 0)
        hbox.setSpacing(0)
        hbox.addStretch(1)

        inner_host = QWidget(host)
        inner = QGridLayout(inner_host)
        inner.setContentsMargins(0, 0, 0, 0)
        gap = self._snap3(self.DENSITY["gap"])
        inner.setHorizontalSpacing(gap)
        inner.setVerticalSpacing(gap)

        # 숫자판 행/열이 남는 높이를 고르게 나눠 갖도록 스트레치 적용
        for r in range(4):
            inner.setRowStretch(r, 1)
        for c in range(3):
            inner.setColumnStretch(c, 1)

        # 숫자판이 너무 가늘어지지 않도록 내부 호스트에 최소 폭을 부여
        wmin = self._snap3(self.DENSITY.get("phone_key_min_w", 120))
        inner_host.setMinimumWidth(wmin * 3 + gap * 2)

        # 3x3 + (⌫ 0 완료)
        nums = (("1","2","3"),("4","5","6"),("7","8","9"))
        for r, row in enumerate(nums):
            for c, t in enumerate(row):
                btn = self._mk_btn(t, phone=True)
                inner.addWidget(btn, r, c, 1, 1)

        back = self._mk_btn("⌫", role="primary", insert=False, phone=True); back.clicked.connect(self._backspace)
        zero = self._mk_btn("0", phone=True)
        done = self._mk_btn("완료", role="primary", insert=False, phone=True); done.clicked.connect(self._on_done)
        inner.addWidget(back, 3, 0, 1, 1)
        inner.addWidget(zero, 3, 1, 1, 1)
        inner.addWidget(done, 3, 2, 1, 1)

        hbox.addWidget(inner_host, 0, Qt.AlignHCenter)
        hbox.addStretch(1)
        self.grid.addWidget(host, 0, 0, 4, self._COLS)

    def _build_email(self) -> None:
        chip_row = [
            ("gmail.com", 2, "chip"), ("naver.com", 2, "chip"), ("daum.net",  2, "chip"), ("kakao.com", 2, "chip"),
            (".co.kr",    1, "chip"), (".com",      1, "chip"),
        ]
        self._add_span_row(0, chip_row)

        rows = [
            list("1234567890"),
            list("qwertyuiop"),
            list("asdfghjkl") + [""],
            list("zxcvbnm")   + ["","",""],
            [("@",1,"key"), (".",1,"key"), ("_",1,"key"), ("-",1,"key"), ("",2,"key"), ("⌫",2,"primary"), ("완료",2,"primary")],
        ]
        for i, row in enumerate(rows, start=1):
            self._add_span_row(i, row)

    # ---------- 입력 처리 ----------
    def _target_edit(self):
        return self._target if self._target and self._target.isEnabled() else None

    def _on_key(self, text: str) -> None:
        if text in {"완료","⌫"}:
            return
        edit = self._target_edit()
        if not edit:
            return
        if self._mode == KeyboardMode.NAME and self._name_lang == "ko":
            if text == "스페이스":
                self._insert_plain(edit, " "); edit.setFocus(Qt.OtherFocusReason); return
            if self._korean_shift:
                doubles = {"ㄱ":"ㄲ","ㄷ":"ㄸ","ㅂ":"ㅃ","ㅅ":"ㅆ","ㅈ":"ㅉ","ㅐ":"ㅒ","ㅔ":"ㅖ"}
                text = doubles.get(text, text)
            t = edit.text(); pos = edit.cursorPosition()
            new_t, new_pos = hangul_insert(t, pos, text)
            edit.setText(new_t); edit.setCursorPosition(new_pos)
        else:
            if text == "스페이스":
                text = " "
            self._insert_plain(edit, text)
        edit.setFocus(Qt.OtherFocusReason)

    def _chip_insert(self, domain: str):
        edit = self._target_edit()
        if not edit:
            return
        self._insert_plain(edit, domain)
        edit.setFocus(Qt.OtherFocusReason)

    def _insert_plain(self, edit, ch: str) -> None:
        if edit.hasSelectedText():
            s = edit.selectionStart(); e = s + len(edit.selectedText()); full = edit.text()
            edit.setText(full[:s] + ch + full[e:]); edit.setCursorPosition(s + len(ch))
        else:
            pos = edit.cursorPosition(); t = edit.text()
            edit.setText(t[:pos] + ch + t[pos:]); edit.setCursorPosition(pos + len(ch))

    def _backspace(self) -> None:
        edit = self._target_edit()
        if not edit:
            return
        if edit.hasSelectedText():
            s = edit.selectionStart(); e = s + len(edit.selectedText()); full = edit.text()
            edit.setText(full[:s] + full[e:]); edit.setCursorPosition(s)
        else:
            pos = edit.cursorPosition()
            if pos > 0:
                t = edit.text(); edit.setText(t[:pos-1] + t[pos:]); edit.setCursorPosition(pos-1)

    def _toggle_korean_shift(self) -> None:
        self._korean_shift = not self._korean_shift
        self._refresh_toggle_styles()

    def _toggle_name_lang(self) -> None:
        self._name_lang = "en" if self._name_lang == "ko" else "ko"
        if self._name_lang == "en":
            self._en_shift = False
        self._clear_grid()
        self._build_korean()
        self._apply_qss()
        self._refresh_toggle_styles()

    def _on_done(self) -> None:
        self.done.emit()

    # ---------- 폰트 핏 ----------
    def _fit_font_to_btn(self, btn: QPushButton, min_pt: int = 11) -> None:
        f = QFont(btn.font()); fm = QFontMetrics(f)
        wpad = 16; maxw = max(24, btn.width() - wpad)
        while fm.horizontalAdvance(btn.text()) > maxw and f.pointSize() > min_pt:
            f.setPointSize(f.pointSize()-1); fm = QFontMetrics(f)
        btn.setFont(f)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        for w in self._iter_buttons():
            if not isinstance(w, QPushButton):
                continue
            if w.property("phone"):
                pass  # allow flexible width; keep fixed height via _apply_qss()
            self._fit_font_to_btn(w)

    # ----- 영문 쉬프트 토글 -----
    def _toggle_en_shift(self) -> None:
        self._en_shift = not self._en_shift
        self._clear_grid()
        self._build_korean()
        self._apply_qss()
        self._refresh_toggle_styles()

    # ----- 토글 버튼 스타일 -----
    def _refresh_toggle_styles(self) -> None:
        for w in self._iter_buttons():
            if not isinstance(w, QPushButton):
                continue
            if w.text() == "쌍자음":
                w.setProperty("active", 1 if self._korean_shift else 0)
                w.style().unpolish(w); w.style().polish(w)
            if w.text() == "Shift":
                w.setProperty("active", 1 if self._en_shift else 0)
                w.style().unpolish(w); w.style().polish(w)
