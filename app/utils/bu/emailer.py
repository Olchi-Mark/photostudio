# app/utils/emailer.py
# -*- coding: utf-8 -*-
from __future__ import annotations

# 한 줄 요약: settings.json의 [email] 섹션만 사용해 SMTP 메일 전송 유틸 제공

import os, json, smtplib, ssl, mimetypes, socket
from typing import Dict, List, Optional
from email.message import EmailMessage
from email.utils import make_msgid, formatdate
from dataclasses import dataclass
from datetime import datetime

#─────────────────────────────────────────────────────────────
# 변경 요약
# - 설정 소스 통일: email.json 제거 → settings.json의 [email]로 확정
# - 탐색 순서: ENV:PHOTOSTUDIO_SETTINGS → C:/PhotoBox/settings.json → app/config/settings.json
# - 안전 로그, 기본값 병합, 하위 호환 API(load_email_config) 유지
#─────────────────────────────────────────────────────────────

# 운영 로그
LOG_DIR = "C:/PhotoBox/logs"
LOG_PATH = os.path.join(LOG_DIR, "email.log")

# settings.json 후보 경로
APP_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
CONFIG_DIR = os.path.join(APP_DIR, "config")
SETTINGS_CANDIDATES = [
    os.environ.get("PHOTOSTUDIO_SETTINGS"),           # 1) 환경변수 절대경로
    "C:/PhotoBox/settings.json",                     # 2) 릴리즈 표준 경로
]

_SELECTED_SETTINGS_PATH: Optional[str] = None  # 실제 사용 경로 캐시


def _log(line: str) -> None:
    """한 줄 로그 기록."""
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {line}")
    except Exception:
        pass  # 로깅 실패는 무시


#─────────────────────────────────────────────────────────────
# 기본값(이메일 섹션만)
#─────────────────────────────────────────────────────────────
DEFAULT_EMAIL_CFG: Dict = {
    "simulate": False,  # 실제 송신 대신 성공 처리
    "from_name": "PhotoStudio",  # 발신 표시명 기본값
    "from_email": "wwha0911@gmail.com",
    "subject_template": "[증명사진] {name}님 사진 전송 ({size_key})",
    "body_template": (
        "{name}님,"
        "요청하신 증명사진을 첨부했습니다."
        "- 촬영일: {date} {time}"
        "- 규격: {size_key}"
        "감사합니다."
        "{from_name}"
    ),
    "smtp": {
        "host": "wwha0911@gmail.com",
        "port": 465,
        "use_ssl": True,
        "use_starttls": False,
        "username": "Photo studio",
        "password": "cnohsgtpavecnjfw",
    },
}


#─────────────────────────────────────────────────────────────
# 설정 로딩
#─────────────────────────────────────────────────────────────
# 한 줄 요약: settings.json 경로를 찾고 전체 딕셔너리를 로드

def _resolve_settings_path() -> Optional[str]:
    """settings.json 실제 사용 경로 결정."""
    global _SELECTED_SETTINGS_PATH
    if _SELECTED_SETTINGS_PATH:
        return _SELECTED_SETTINGS_PATH
    for cand in SETTINGS_CANDIDATES:
        if not cand:
            continue
        try:
            if os.path.exists(cand):
                _SELECTED_SETTINGS_PATH = cand
                return _SELECTED_SETTINGS_PATH
        except Exception:
            continue
    _SELECTED_SETTINGS_PATH = None
    return None


def resolve_defaults() -> Dict:
    """defaults.json 로드(app/config/defaults.json). 없으면 빈 dict."""
    try:
        app_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
        defaults_path = os.path.join(app_dir, "config", "defaults.json")
        if os.path.isfile(defaults_path):
            with open(defaults_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
    except Exception as e:
        _log(f"WARN load defaults.json failed: {e}")
    return {}


def load_settings() -> Dict:
    """settings.json 전체 로드. 없으면 defaults.json 로드."""
    path = _resolve_settings_path()
    if not path:
        _log("WARN settings.json not found; falling back to defaults.json")
        return resolve_defaults()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else resolve_defaults()
    except Exception as e:
        _log(f"ERROR load settings.json failed: {e}; using defaults.json")
        return resolve_defaults()

# 이메일 섹션만 추출 + 기본값 병합

# 이메일 섹션만 추출 + 기본값 병합
# - 키 확정: settings['email']만 인정(별칭 'mailer' 제거)

def _load_email_from_settings() -> Dict:
    """settings.json에서 email 섹션을 읽고 DEFAULT_EMAIL_CFG로 보완."""
    settings = load_settings()
    raw = {}
    if isinstance(settings, dict):
        raw = settings.get("email") or {}
    # 얕은 병합(중첩 딕셔너리는 1단계만 병합)
    merged = dict(DEFAULT_EMAIL_CFG)
    for k, v in raw.items():
        if k == "smtp" and isinstance(v, dict):
            merged_smtp = dict(DEFAULT_EMAIL_CFG.get("smtp", {}))
            merged_smtp.update(v)
            merged["smtp"] = merged_smtp
        else:
            merged[k] = v
    return merged


# 하위 호환 API 유지: load_email_config()
# - 과거 파일명 기반 로더를 대체하고 settings['email']만 반환

def load_email_config() -> Dict:
    """이메일 설정을 로드(하위 호환 API)."""
    return _load_email_from_settings()


#─────────────────────────────────────────────────────────────
# 템플릿 보조
#─────────────────────────────────────────────────────────────
# 한 줄 요약: 토큰 미존재 시 {키}를 그대로 남기며 안전 렌더

def render_template(tpl: str, tokens: Dict) -> str:
    """문자열 템플릿을 안전하게 렌더."""
    try:
        return tpl.format_map(_Default(dict(tokens)))
    except Exception:
        return tpl


class _Default(dict):
    def __missing__(self, key):
        return "{" + key + "}"


def _as_bool(v) -> bool:
    """'false', '0', 'no' 같은 문자열까지 불리언으로 변환."""
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "y", "on")
    if isinstance(v, (int, float)):
        return bool(v)
    return False


#─────────────────────────────────────────────────────────────
# 결과 객체
#─────────────────────────────────────────────────────────────
@dataclass
class SendResult:
    ok: bool
    provider_id: Optional[str]
    error: Optional[str]


#─────────────────────────────────────────────────────────────
# 메일 발송
#─────────────────────────────────────────────────────────────
# 한 줄 요약: settings.json 기반 SMTP로 텍스트 메일과 첨부를 전송

def send_email(
    *,
    to_email: str,
    subject: str,
    body: str,
    attachments: Optional[List[str]] = None,
    cfg: Optional[Dict] = None,
) -> SendResult:
    """SMTP 전송. cfg 미지정 시 settings.json의 [email] 섹션 사용."""
    cfg = cfg or load_email_config()

    # 시뮬레이터 모드
    if _as_bool(cfg.get("simulate", False)):
        _log(f"SIMULATED to={to_email} subj={subject}")
        return SendResult(ok=True, provider_id="SIMULATED", error=None)

    # SMTP 설정
    smtp = cfg.get("smtp", {})
    host = (smtp.get("host") or "").strip()
    port = int(smtp.get("port", 587))
    use_ssl = _as_bool(smtp.get("use_ssl", False))
    use_tls = _as_bool(smtp.get("use_starttls", True))
    username = smtp.get("username") or ""
    password = smtp.get("password") or ""

    # 발신자 헤더: from_email / from.{email} 모두 지원
    from_email = (
        cfg.get("from_email")
        or (cfg.get("from") or {}).get("email")
        or username
    )
    from_name = (
        cfg.get("from_name")
        or (cfg.get("from") or {}).get("name")
        or from_email
    )

    # 구성 검증 & DNS 사전 점검
    if not host:
        msg = "SMTP host empty (settings.json)"
        _log(f"ERROR {msg}")
        return SendResult(ok=False, provider_id=None, error=msg)
    try:
        socket.getaddrinfo(host, port, 0, socket.SOCK_STREAM)
    except Exception as e:
        msg = f"DNS lookup failed for {host}:{port} ({e})"
        _log(f"ERROR {msg}")
        return SendResult(ok=False, provider_id=None, error=msg)

    # 메시지 작성
    msg = EmailMessage()
    msg["Message-ID"] = make_msgid()
    msg["Date"] = formatdate(localtime=True)
    msg["From"] = f"{from_name} <{from_email}>"
    msg["To"] = to_email
    msg["Subject"] = subject
    msg.set_content(body)

    # 첨부(없으면 생략; 실패해도 본문 전송은 진행)
    for path in (attachments or []):
        try:
            if not path or not os.path.exists(path):
                continue
            ctype, _ = mimetypes.guess_type(path)
            if not ctype:
                ctype = "application/octet-stream"
            maintype, subtype = ctype.split("/", 1)
            with open(path, "rb") as f:
                data = f.read()
            msg.add_attachment(
                data, maintype=maintype, subtype=subtype,
                filename=os.path.basename(path)
            )
        except Exception as e:
            _log(f"WARN attach-fail path={path} err={e}")

    # 전송
    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context) as s:
                if username:
                    s.login(username, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=20) as s:
                s.ehlo()
                if use_tls:
                    s.starttls(context=ssl.create_default_context())
                    s.ehlo()
                if username:
                    s.login(username, password)
                s.send_message(msg)

        _log(f"OK to={to_email} subj={subject} via {host}:{port} ssl={use_ssl} starttls={use_tls}")
        return SendResult(ok=True, provider_id=msg["Message-ID"], error=None)

    except Exception as e:
        err = f"SMTP error via {host}:{port} ssl={use_ssl} starttls={use_tls} user={username!r} -> {e}"
        _log(f"ERROR {err}")
        return SendResult(ok=False, provider_id=None, error=err)


def send_email_checked(
    *,
    to_email: str,
    subject: str,
    body: str,
    attachments: Optional[List[str]] = None,
    cfg: Optional[Dict] = None,
    on_error=None,
) -> SendResult:
    """
    전송 래퍼: 결과를 반환하고 실패 시 on_error 콜백을 호출한다.
    사용 예: res = emailer.send_email_checked(..., on_error=show_error)
    """
    res = send_email(
        to_email=to_email,
        subject=subject,
        body=body,
        attachments=attachments,
        cfg=cfg,
    )
    if (not res.ok) and callable(on_error):
        try:
            on_error(res.error or "메일 전송 실패")
        except Exception:
            pass
    return res

# === SUMMARY ===
# v2.2: 문자열 내 실제 개행 제거 → "

# v2.1: settings['email']로 키 확정(별칭 제거)
# v2.0: email.json 제거, settings.json 통합(ENV→C:/PhotoBox→app/config), 기본값 병합
