# -*- coding: utf-8 -*-
from __future__ import annotations
import os

# === 경로 상수(필수) ===
APP_DIR     = os.path.abspath(os.path.dirname(__file__))     # .../photostudio/app
ASSETS_DIR  = os.path.join(APP_DIR, "assets")
IMAGES_DIR  = os.path.join(ASSETS_DIR, "images")
SOUND_DIR   = os.path.join(ASSETS_DIR, "sound")
DATA_DIR    = os.path.join(APP_DIR, "data")   


# Fallback sample image (used when no selection / no captures)
FALLBACK_IMAGE = os.path.join(IMAGES_DIR, "test_id.jpg")

# UI constants
THUMB_BAR_HEIGHT = 180

# Step labels (router order aligned)
STEPS: list[str] = [
    "정보입력",     # input.py
    "사이즈선택",   # size_select.py
    "촬영",         # capture.py
    "사진선택",     # pick_photo.py
    "AI 보정",      # print_view.py
    "이메일전송",   # email_send.py
    "추가옵션",     # enhance_select.py
]
FLOW = [
    "intro",
    "input",
    "size_select",
    "capture",
    "pick_photo",
    "print_view",
    "email_send",
    "enhance_select",
    "outro",
]

# app/constants.py 일부
PRINT_PPI = 300
SIZES_MM = {
    "ID_30x40": (30, 40),
    "ID_35x45": (35, 45),
}
DATA_DIR = os.path.join(APP_DIR, "data")   # APP_DIR은 네가 이미 쓰는 루트 경로 상수
EMAIL_LONG_PX = 1600
THUMB_LONG_PX = 480



INPUT_GUIDE_TITLE = "안내 / 약관"
INPUT_GUIDE_HTML = """
<p>촬영 및 이미지 처리에 관한 안내 사항입니다. 본 서비스는 사진 촬영, 보정, 출력 및 이메일 전송을 포함합니다.
개인정보는 촬영 및 결과 전달 목적에만 사용되며, 정해진 보관 기간 이후 안전하게 파기됩니다.
본 안내를 끝까지 읽고 동의하셔야 다음 단계로 진행할 수 있습니다.</p>
<ol>
촬영 시 가이드에 따라 자세를 유지해 주세요.</div>"
</div>"AI 보정은 얼굴 윤곽, 피부톤 개선 등을 포함합니다.</div>"
</div>"이메일 오기입 시 재전송이 어렵습니다.</div>"
</div>"기타 자세한 사항은 매장 정책을 따릅니다.</div>"
<p>감사합니다.</p>
"""

# ====== Email / Print Tokens (환경설정 값) ======

# 이메일 발신 정보
SENDER_EMAIL = "wwha0911@gmail.com"
SENDER_NAME  = "My Sweet Interview"

# SMTP 설정 (진짜 발송 시 사용 / 미설정이면 에러를 띄우고 발송 안 함)
SMTP_HOST   = "smtp.gmail.com"          # 예) "smtp.gmail.com"
SMTP_PORT   = 587         # TLS 보통 587
SMTP_USE_TLS = True
SMTP_USER   = "wwha0911@gmail.com"          # 예) 전체 메일주소
SMTP_PASS   = "cnohsgtpavecnjfw"          # 앱 비밀번호 또는 SMTP 패스워드

# 메일 제목/본문 템플릿 (세션 값으로 치환)
# 사용가능 플레이스홀더: {name}, {phone}, {shoot_time}, {job_id}
EMAIL_SUBJECT_TEMPLATE = "증명사진 전송 - {name}"
EMAIL_BODY_TEMPLATE = (
    "안녕하세요 {name}님,\n"
    "요청하신 증명사진을 첨부합니다.\n"
    "- (저용량) 이메일용\n"
    "- (고해상도) 출력용\n\n"
    "촬영시각: {shoot_time}\n"
    "문의: {phone}\n"
    "감사합니다.\n"
)

# PDF 출력 기본값 (size_select.py 값이 없을 때의 fallback)
PRINT_DPI_DEFAULT        = 300
PRINT_SPACING_MM_DEFAULT = 3.0
PRINT_PAGE_NAME_DEFAULT  = "A4"   # "A4", "A5", "4x6" 등
PRINT_PAGE_MM_DEFAULT    = (210, 297)  # 위 이름을 해석 못했을 때 쓸 기본 mm

# (참고) 이메일 주소를 input.py에서 쉼표/스페이스로 구분해 여러 개 저장해도 됩니다.
# 이메일
SENDER_EMAIL = "noreply@example.com"
SENDER_NAME  = "Photo Studio"
EMAIL_SUBJECT = "증명사진 전송"
EMAIL_BODY    = "사진을 첨부합니다."

# 출력
PRINT_PAPER_MM = (210.0, 297.0)   # A4
PRINT_PHOTO_MM = (30.0, 40.0)     # 3x4 cm
PRINT_DPI      = 300
PRINT_GAP_MM   = 3.0
PRINT_MARGIN_MM = 5.0
PRINT_DESKTOP_DIRNAME = "IDPhoto"


# ==== 출력(관리자 설정) ====
# 기본값: 바탕화면/WIDPhoto


# 출력 저장 경로(관리자 설정). 비워두면 Desktop/IDPhoto 사용
PRINT_EXPORT_DIR = r"C:\devWIDPhoto"  # 필요 시 변경, 없으면 빈 문자열 ""
PRINT_DESKTOP_DIRNAME = "IDPhoto"

# ==== Retouch Grid Settings (print_view.py용) ====
GRID_LABELS    = [f"{i:02d}" for i in range(1,13)]  # "01"~"12"
ROW_NAMES      = ["Raw", "Liquify", "Neural", "Background"]
BG_HOTKEYS     = {10: ("ctrl","f8"), 11: ("ctrl","f9"), 12: ("ctrl","f10")}
RATIO_DEFAULT  = "3040"  # 또는 "3545"
ALLOW_PS_AUTORUN = True  # 포토샵 자동 실행 허용
CLEAN_RESIDUALS  = True  # 잔존 산출물 선삭제