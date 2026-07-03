#!/usr/bin/env python3
r"""받은편지함에서 전일(KST) `[CaskCode` 메일을 'CaskCode' 라벨로 보내 정리 — CMPA-392/393.

보드 메일 계정(shhong@dudaji.com)은 자기 자신에게 발송하므로 발신 리포트가 INBOX 에도
쌓인다. 이 스크립트는 **전일(KST) 받은편지함**에서 제목이 `[CaskCode` 로 시작하는 메일만
골라 Gmail 라벨 'CaskCode' 를 부여하고 INBOX 에서 제거한다(All Mail·Sent 는 보존 —
휴지통 아님, 가역).

인증/접속:
  - IMAP imap.gmail.com:993 SSL.
  - user = env GMAIL_INBOX_USER → GMAIL_SENDER → EMAIL_FROM
           → PAPERCLIP_EMAIL_RECIPIENTS 첫 주소.
  - password = env GMAIL_APP_PASSWORD (SMTP 발송과 동일 앱 비밀번호 재사용).

대상 산정(정확히 그 KST 하루만):
  - 기본 = 어제(KST). --date YYYY-MM-DD 로 다른 날 지정 가능.
  - KST 하루를 UTC 로 환산(KST = UTC+9)해 IMAP SEARCH SINCE/BEFORE 로 후보를 모은 뒤,
    각 메시지의 Date 헤더를 KST 로 변환해 **정확히 그 날짜인 것만** 남긴다.
  - 추가로 제목이 `[CaskCode` 로 시작하는 것만. 그 외 메일은 절대 건드리지 않는다.

동작(각 메시지, 멱등):
  1. 'CaskCode' 메일박스(라벨) 없으면 CREATE 후 UID COPY → 라벨 부여.
  2. INBOX 에서 해당 UID \Deleted STORE 후 EXPUNGE → INBOX 라벨만 제거.

안전장치:
  - --dry-run : 대상만 출력, 변경 없음(검증용).
  - 헤더는 BODY.PEEK 로 읽어 읽음(\Seen) 상태를 바꾸지 않는다.
  - 처리 건수·제목 로그. 제목 prefix·날짜 범위 밖 메일 변경 금지.
  - IMAP 접속/로그인 실패 시 비정상 종료코드 + 'IMAP access disabled' 안내
    → 호출 루틴이 blocked + CEO 에스컬레이션.

사용법:
  python3 scripts/archive_caskcode_inbox.py            # 어제(KST) 처리
  python3 scripts/archive_caskcode_inbox.py --dry-run  # 대상만 확인
  python3 scripts/archive_caskcode_inbox.py --date 2026-06-14
"""
import argparse
import email
import imaplib
import os
import sys
from datetime import datetime, timedelta, timezone
from email.header import decode_header
from email.utils import parsedate_to_datetime

IMAP_HOST = "imap.gmail.com"
IMAP_PORT = 993
KST = timezone(timedelta(hours=9))
SUBJECT_PREFIX = "[CaskCode"
LABEL = "CaskCode"


def _imap_user():
    for key in ("GMAIL_INBOX_USER", "GMAIL_SENDER", "EMAIL_FROM"):
        v = os.environ.get(key)
        if v and v.strip():
            return v.strip()
    env = os.environ.get("PAPERCLIP_EMAIL_RECIPIENTS", "")
    for a in env.split(","):
        if a.strip():
            return a.strip()
    return ""


def _decode_subject(raw):
    if not raw:
        return ""
    out = []
    for text, enc in decode_header(raw):
        if isinstance(text, bytes):
            try:
                out.append(text.decode(enc or "utf-8", errors="replace"))
            except (LookupError, UnicodeDecodeError):
                out.append(text.decode("utf-8", errors="replace"))
        else:
            out.append(text)
    return "".join(out)


def _kst_date(target_date):
    """KST 날짜 D 에 대한 (search_since, search_before, D) 반환.

    KST 하루[D 00:00, D+1 00:00) = UTC [D-1 15:00, D 15:00). IMAP SEARCH 는 날짜
    단위라 UTC 로 D-1, D 두 날에 걸친다 → SINCE (D-1) BEFORE (D+1) 로 후보를 넉넉히
    모은 뒤 Date 헤더로 정밀 필터한다."""
    since = (target_date - timedelta(days=1)).strftime("%d-%b-%Y")
    before = (target_date + timedelta(days=1)).strftime("%d-%b-%Y")
    return since, before


def _connect():
    user = _imap_user()
    pw = os.environ.get("GMAIL_APP_PASSWORD")
    if not user:
        raise RuntimeError("IMAP user 를 결정할 수 없습니다 "
                           "(GMAIL_INBOX_USER/GMAIL_SENDER/EMAIL_FROM/"
                           "PAPERCLIP_EMAIL_RECIPIENTS).")
    if not pw:
        raise RuntimeError("GMAIL_APP_PASSWORD 환경변수가 없습니다.")
    try:
        m = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
        m.login(user, pw)
    except imaplib.IMAP4.error as e:
        msg = str(e)
        hint = ""
        if "disabled" in msg.lower() or "imap" in msg.lower():
            hint = (" — Gmail/Workspace 에서 IMAP 접근이 비활성화되어 있을 수 있습니다. "
                    "CEO 에스컬레이션 필요(사람에게 직접 요청 금지).")
        raise RuntimeError(f"IMAP 로그인 실패: {msg}{hint}") from e
    return m, user


def _ensure_label(m):
    """'CaskCode' 메일박스(Gmail 라벨)가 없으면 생성. 멱등."""
    typ, data = m.list()
    exists = False
    if typ == "OK":
        for line in data:
            s = line.decode(errors="replace") if isinstance(line, bytes) else str(line)
            # 라벨명이 따옴표로 감싸여 끝에 오는 경우 등 폭넓게 매칭
            if f'"{LABEL}"' in s or s.rstrip().endswith(" " + LABEL):
                exists = True
                break
    if not exists:
        m.create(LABEL)


def _candidates(m, target_date):
    """INBOX 에서 (uid, subject, kst_dt) 후보 중 prefix·날짜 일치만 반환."""
    m.select("INBOX", readonly=True)
    since, before = _kst_date(target_date)
    typ, data = m.uid("SEARCH", None, f'(SINCE {since} BEFORE {before})')
    if typ != "OK":
        raise RuntimeError(f"IMAP SEARCH 실패: {data!r}")
    uids = data[0].split() if data and data[0] else []
    hits = []
    for uid in uids:
        typ, fetched = m.uid(
            "FETCH", uid, "(BODY.PEEK[HEADER.FIELDS (SUBJECT DATE)])")
        if typ != "OK" or not fetched or not fetched[0]:
            continue
        raw = fetched[0][1]
        hdr = email.message_from_bytes(raw)
        subject = _decode_subject(hdr.get("Subject", ""))
        date_raw = hdr.get("Date", "")
        try:
            dt = parsedate_to_datetime(date_raw)
        except (TypeError, ValueError):
            continue
        if dt is None:
            continue
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        kst_dt = dt.astimezone(KST)
        if kst_dt.date() != target_date.date():
            continue
        if not subject.lstrip().startswith(SUBJECT_PREFIX):
            continue
        hits.append((uid, subject, kst_dt))
    return hits


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--date", default="",
                    help="처리할 KST 날짜 YYYY-MM-DD (기본=어제 KST)")
    ap.add_argument("--dry-run", action="store_true",
                    help="대상만 출력, 변경 없음")
    args = ap.parse_args()

    if args.date:
        try:
            target = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=KST)
        except ValueError:
            print(f"[ERROR] --date 형식 오류: {args.date} (YYYY-MM-DD)", file=sys.stderr)
            return 2
    else:
        now_kst = datetime.now(KST)
        target = (now_kst - timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0)

    print(f"[archive_caskcode_inbox] 대상 KST 날짜: {target.date()} "
          f"{'(DRY-RUN)' if args.dry_run else ''}")

    try:
        m, user = _connect()
    except RuntimeError as e:
        print(f"[BLOCKED] {e}", file=sys.stderr)
        return 3

    try:
        print(f"[archive_caskcode_inbox] 계정: {user}")
        hits = _candidates(m, target)
        print(f"[archive_caskcode_inbox] 대상 {len(hits)}건 "
              f"(제목 '{SUBJECT_PREFIX}' + {target.date()} KST):")
        for uid, subject, kst_dt in hits:
            print(f"  - uid={uid.decode() if isinstance(uid, bytes) else uid} "
                  f"[{kst_dt.strftime('%Y-%m-%d %H:%M KST')}] {subject}")

        if not hits:
            print("[archive_caskcode_inbox] 처리할 메일 없음.")
            return 0
        if args.dry_run:
            print("[archive_caskcode_inbox] DRY-RUN — 변경 없음.")
            return 0

        _ensure_label(m)
        # 변경 작업은 INBOX 를 쓰기 모드로 다시 선택
        m.select("INBOX", readonly=False)
        copied = 0
        for uid, subject, _ in hits:
            typ, _r = m.uid("COPY", uid, LABEL)
            if typ != "OK":
                print(f"  [WARN] COPY 실패 uid={uid!r} — 건너뜀(INBOX 유지)")
                continue
            m.uid("STORE", uid, "+FLAGS", "(\\Deleted)")
            copied += 1
        m.expunge()
        print(f"[archive_caskcode_inbox] 완료: {copied}건 'CaskCode' 라벨 부여 + "
              f"INBOX 제거 (All Mail/Sent 보존).")
        return 0
    finally:
        try:
            m.logout()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
