# -*- coding: utf-8 -*-
"""
emailer.py (drop-in replacement)

목적:
- settings.json의 다양한 스키마(과거/현재)를 자동으로 '정규화(normalize)' 하여
  실제 메일 전송에 필요한 공통 형태로 맞춘 뒤 보냅니다.
- Gmail 등 표준 SMTP 서버에서 동작.
- 표준 라이브러리만 사용.

지원 스키마(예시):
1) (과거/정상 동작하던 형태)
{
  "simulate": true,
  "smtp": { "host":"smtp.gmail.com","port":465,"use_ssl":true,"use_starttls":false,
            "username":"...","password":"..." },
  "from": { "email":"wwha0911@gmail.com", "name":"My Sweet Interview" },
  "templates": { "subject":"...", "body":"..." }
}

2) (현재/프로젝트 스키마)
{
  "email": {
    "auth": { "user":"...", "pass":"..." },
    "smtp": { "host":"smtp.gmail.com","port":587,"tls":true },
    "from_email": "wwha0911@gmail.com",
    "from_name": "Photo Studio",
    "customer": {...}, "print_manager": {...}, "retouch_manager": {...}
  }
}

핵심 정규화:
- auth.user/pass → smtp.username/password
- smtp.tls → smtp.use_starttls
- from_address / from.email / from_email 통합
"""

from __future__ import annotations
import os
import json
import ssl
import smtplib
import mimetypes
import logging
from pathlib import Path
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

# ----------------------------kwargs
# 로깅 설정
# ----------------------------
def _get_log_path() -> Path:
    # 우선순위: C:\PhotoBox\logs\email.log → ./email.log
    try:
        base = Path("C:/PhotoBox/logs")
        base.mkdir(parents=True, exist_ok=True)
        return base / "email.log"
    except Exception:
        return Path("./email.log")

_LOG_PATH = _get_log_path()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.FileHandler(_LOG_PATH, encoding="utf-8"), logging.StreamHandler()]
)
logger = logging.getLogger("emailer")


# ----------------------------
# 설정 파일 로딩
# ----------------------------
DEFAULT_SEARCH_PATHS: List[Path] = [
    # 환경변수 PHOTOSTUDIO_SETTINGS로 절대경로가 넘어오는 경우 지원
    Path(os.environ.get("PHOTOSTUDIO_SETTINGS")) if os.environ.get("PHOTOSTUDIO_SETTINGS") else None,
    Path("C:/PhotoBox/settings.json"),
    Path("./settings.json"),
]
DEFAULT_SEARCH_PATHS = [p for p in DEFAULT_SEARCH_PATHS if p is not None]


def load_raw_settings(explicit_path: Optional[str] = None) -> Dict[str, Any]:
    """
    settings.json 원본을 읽어 dict로 반환. 실패 시 {} 반환.
    """
    candidates: List[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    candidates.extend(DEFAULT_SEARCH_PATHS)

    for p in candidates:
        try:
            if p.is_file():
                with p.open("r", encoding="utf-8") as f:
                    data = json.load(f)
                    logger.info(f"Loaded settings from: {p}")
                    return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning(f"Failed to load settings from {p}: {e}")
    logger.warning("No settings.json found. Using empty config.")
    return {}


def _as_bool(v: Any, default: bool = False) -> bool:
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        return v.strip().lower() in {"1", "true", "yes", "y", "on"}
    if isinstance(v, (int, float)):
        return bool(v)
    return default


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except Exception:
        return default


# ----------------------------
# 스키마 정규화
# ----------------------------
def normalize_email_config(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    다양한 스키마를 하나의 공통 구조로 통합.

    최종 반환 형태 예:
    {
      "simulate": False,
      "from_email": "...",
      "from_name": "...",
      "smtp": {
        "host": "...",
        "port": 587,
        "use_ssl": False,
        "use_starttls": True,
        "username": "...",
        "password": "..."
      },
      # 필요 시 그대로 보존
      "templates": {...},
      "customer": {...}, "print_manager": {...}, "retouch_manager": {...}
    }
    """
    # 1) email 섹션/루트 섹션 병합
    email_section = dict(raw.get("email") or {})
    cfg: Dict[str, Any] = {}

    # simulate
    cfg["simulate"] = _as_bool(email_section.get("simulate", raw.get("simulate", False)))

    # templates (루트/이메일 섹션 둘 다 허용)
    templates = email_section.get("templates", raw.get("templates"))
    if isinstance(templates, dict):
        cfg["templates"] = templates

    # 2) FROM 정보(별칭 지원)
    # 우선순위: email_section.from_email → email_section.from.email → raw.from.email → raw.from_email → email_section.from_address
    from_email = (
        email_section.get("from_email")
        or (email_section.get("from") or {}).get("email")
        or (raw.get("from") or {}).get("email")
        or email_section.get("from_address")
        or raw.get("from_email")
        or raw.get("from_address")
    )
    from_name = (
        email_section.get("from_name")
        or (email_section.get("from") or {}).get("name")
        or (raw.get("from") or {}).get("name")
        or raw.get("from_name")
    )
    if from_email:
        cfg["from_email"] = str(from_email).strip()
    if from_name:
        cfg["from_name"] = str(from_name).strip()

    # 3) SMTP 블록 수집: email.smtp 또는 root.smtp
    smtp = {}
    src_smtp = email_section.get("smtp") or raw.get("smtp") or {}
    if isinstance(src_smtp, dict):
        smtp.update(src_smtp)

    # 3-1) HOST
    smtp["host"] = (smtp.get("host") or "").strip()

    # 3-2) PORT
    smtp["port"] = _as_int(smtp.get("port", 587), 587)

    # 3-3) SSL / STARTTLS / TLS 별칭 매핑
    # - 우선 key 존재 여부를 그대로 존중하되, 없는 경우 보수적으로 STARTTLS를 기본 True로 둠(587 기준)
    use_ssl = _as_bool(smtp.get("use_ssl", False))
    use_starttls = _as_bool(smtp.get("use_starttls", smtp.get("tls", True)))
    smtp["use_ssl"] = use_ssl
    smtp["use_starttls"] = use_starttls
    if "tls" in smtp:
        smtp.pop("tls", None)  # 별칭 제거

    # 3-4) AUTH → USERNAME/PASSWORD 별칭 매핑
    auth = email_section.get("auth") or raw.get("auth") or {}
    if isinstance(auth, dict):
        # 비어있을 때만 채운다
        smtp.setdefault("username", auth.get("user") or auth.get("username") or "")
        smtp.setdefault("password", auth.get("pass") or auth.get("password") or "")
    # 루트/이메일 smtp에 직접 username/password가 이미 있으면 그대로 둔다.
    smtp["username"] = (smtp.get("username") or "").strip()
    smtp["password"] = smtp.get("password") or ""

    # 3-5) 최종 적용
    cfg["smtp"] = {
        "host": smtp["host"],
        "port": smtp["port"],
        "use_ssl": smtp["use_ssl"],
        "use_starttls": smtp["use_starttls"],
        "username": smtp["username"],
        "password": smtp["password"],
    }

    # 4) email_section에 있는 보조 섹션 그대로 보존(필요 시 외부에서 사용)
    for key in ("customer", "print_manager", "retouch_manager"):
        if key in email_section and isinstance(email_section[key], dict):
            cfg[key] = email_section[key]

    return cfg


def load_email_config(explicit_path: Optional[str] = None) -> Dict[str, Any]:
    raw = load_raw_settings(explicit_path)
    cfg = normalize_email_config(raw)

    # 합리적 기본값 보정
    smtp = cfg.get("smtp", {})
    # HOST 필수
    if not smtp.get("host"):
        # 과거 기본값 오류 예방: host가 비어있으면 명시적으로 실패시켜 원인 파악 빠르게
        raise ValueError("SMTP host가 설정되지 않았습니다. settings.json의 email.smtp.host 또는 smtp.host를 확인하세요.")
    # FROM 필수
    if not cfg.get("from_email"):
        # 'from' 별칭을 쓰는 과거 스키마를 위해 이미 normalize에서 시도했음.
        # 그래도 없으면 실패사유 명확화
        raise ValueError("발신 주소(from_email)가 없습니다. settings.json의 email.from_email 또는 from.email을 확인하세요.")
    return cfg


# ----------------------------
# 메일 본문/첨부 메시지 생성
# ----------------------------
def _guess_mime_type(path: Path) -> Tuple[str, str]:
    mtype, _ = mimetypes.guess_type(str(path))
    if not mtype:
        return ("application", "octet-stream")
    major, minor = mtype.split("/", 1)
    return (major, minor)


def build_message(
    from_email: str,
    from_name: Optional[str],
    to_addrs: List[str],
    subject: str,
    body: str,
    subtype: str = "plain",
    cc_addrs: Optional[List[str]] = None,
    bcc_addrs: Optional[List[str]] = None,
    attachments: Optional[List[str]] = None,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid()
    msg["From"] = formataddr((from_name or "", from_email))
    msg["To"] = ", ".join(to_addrs)
    if cc_addrs:
        msg["Cc"] = ", ".join(cc_addrs)
    msg["Subject"] = subject

    msg.set_content(body, subtype=subtype)

    # 첨부 파일
    if attachments:
        for p in attachments:
            if not p:
                continue
            path = Path(p)
            if not path.is_file():
                logger.warning(f"[attach] not found: {path}")
                continue
            major, minor = _guess_mime_type(path)
            with path.open("rb") as f:
                data = f.read()
            msg.add_attachment(data, maintype=major, subtype=minor, filename=path.name)

    return msg


# ----------------------------
# 메일 전송
# ----------------------------
def send_email(
    to: List[str] | str,
    subject: str,
    body: str,
    *,
    attachments: Optional[List[str]] = None,
    cc: Optional[List[str]] = None,
    bcc: Optional[List[str]] = None,
    subtype: str = "plain",
    config_path: Optional[str] = None,
    config: Optional[Dict[str, Any]] = None,
) -> str:
    """
    실제 메일 전송 함수.
    - to: 수신자(단일 이메일 또는 리스트)
    - subject/body: 제목/본문 (utf-8)
    - attachments: 선택. 파일 경로 리스트
    - subtype: "plain" 또는 "html"
    - config_path: 특정 settings.json 경로를 강제하고 싶을 때
    - config: 이미 정규화된 설정 dict를 직접 전달할 때

    Returns: Message-ID (simulate인 경우 'SIMULATED-...')
    Raises: ValueError / smtplib.SMTPException 등
    """
    # 수신자 정규화
    to_addrs = [to] if isinstance(to, str) else list(to)
    if not to_addrs:
        raise ValueError("수신자(to)가 비었습니다.")

    # 설정 로딩/정규화
    if config is None:
        cfg = load_email_config(config_path)
    else:
        # 외부에서 normalize까지 끝낸 config라 가정
        cfg = dict(config)

    simulate = _as_bool(cfg.get("simulate", False))
    smtp = cfg.get("smtp", {})
    from_email = cfg.get("from_email")
    from_name = cfg.get("from_name")

    # 필수 체크
    if not from_email:
        raise ValueError("발신 주소(from_email)가 없습니다.")
    host = smtp.get("host") or ""
    port = _as_int(smtp.get("port", 587), 587)
    use_ssl = _as_bool(smtp.get("use_ssl", False))
    use_starttls = _as_bool(smtp.get("use_starttls", True))
    username = smtp.get("username") or ""
    password = smtp.get("password") or ""

    # 메시지 구성
    msg = build_message(
        from_email=from_email,
        from_name=from_name,
        to_addrs=to_addrs,
        subject=subject,
        body=body,
        subtype=subtype,
        cc_addrs=cc,
        bcc_addrs=bcc,
        attachments=attachments,
    )

    # 시뮬레이션 모드
    if simulate:
        sim_id = f"SIMULATED-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
        logger.info(f"[SIMULATE] To={to_addrs} Subject={subject!r} Attach={attachments or []}")
        return sim_id

    # 실제 발송
    if not host:
        raise ValueError("SMTP host가 비어 있습니다.")
    if not (use_ssl or use_starttls or port in (25, 2525)):
        # 보안 설정이 모두 꺼져 있고, 특수 포트도 아니라면 실수 방지
        logger.warning("경고: SSL/STARTTLS가 모두 비활성화되어 있습니다. 서버 정책을 확인하세요.")

    try:
        if use_ssl:
            context = ssl.create_default_context()
            with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as s:
                s.ehlo()
                if username:
                    s.login(username, password)
                s.send_message(msg)
        else:
            with smtplib.SMTP(host, port, timeout=30) as s:
                s.ehlo()
                if use_starttls:
                    context = ssl.create_default_context()
                    s.starttls(context=context)
                    s.ehlo()
                if username:
                    s.login(username, password)
                s.send_message(msg)

        logger.info(f"[SENT] To={to_addrs} Subject={subject!r} via {host}:{port} SSL={use_ssl} STARTTLS={use_starttls} user={username!r}")
        return msg["Message-ID"]
    except smtplib.SMTPAuthenticationError as e:
        # 자주 겪는 인증 문제의 친절한 설명
        hint = (
            "SMTP 인증 실패입니다. Gmail이라면 '앱 비밀번호(16자리)'를 사용해야 합니다.\n"
            "- settings.json의 email.auth.pass 또는 smtp.password가 올바른지 확인하세요.\n"
            "- 2단계 인증이 켜져 있어야 앱 비밀번호를 발급받을 수 있습니다."
        )
        logger.error(f"Authentication failed: {e}")
        raise ValueError(hint) from e
    except Exception as e:
        logger.error(f"SMTP error: {e}")
        raise


# ----------------------------
# 사용 예시 (참고용)
# ----------------------------
if __name__ == "__main__":
    # 간단 테스트: 실제 발송 대신 simulate로 로그만 남기려면
    # settings.json에 "simulate": true 를 넣거나, 아래처럼 config로 전달하세요.
    demo_cfg = {
        "simulate": True,
        "smtp": {"host": "smtp.gmail.com", "port": 587, "use_starttls": True},
        "from_email": "example@example.com",
        "from_name": "Photo Studio",
    }
    try:
        mid = send_email(
            to="someone@example.com",
            subject="테스트 메일",
            body="안녕하세요, 테스트입니다.",
            config=demo_cfg,
        )
        print("Message-ID:", mid)
    except Exception as e:
        print("Error:", e)
