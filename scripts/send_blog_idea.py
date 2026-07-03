#!/usr/bin/env python3
"""블로그 아이디어 제안(md)을 이메일로 전송 — CMPA-252 루틴 진입점 헬퍼.

매일 아침 CMO 가 생성한 '오늘의 블로그 아이디어' 1페이지 제안(md)을
shhong@dudaji.com 으로 보낸다. 본문 = md 원문, 첨부 = 같은 md 파일.

이메일 인증/렌더는 공용 헬퍼 `pipelines.common.email_report.send_report` 재사용
(Gmail SMTP, GMAIL_APP_PASSWORD). 수신자 기본값은 인자 --to → 없으면
PAPERCLIP_EMAIL_RECIPIENTS 환경변수.

사용법:
  python3 scripts/send_blog_idea.py --md content/blog-ideas/2026-06-09_xxx.md \
      --to shhong@dudaji.com
  # 제목 자동(파일 첫 # 헤더) — 직접 지정하려면 --subject
"""
import argparse
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)


def first_heading(md_text):
    for line in md_text.splitlines():
        m = re.match(r"^#\s+(.*)$", line.strip())
        if m:
            return m.group(1).strip()
    return "오늘의 블로그 아이디어"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True, help="제안 md 파일 경로")
    ap.add_argument("--to", default="", help="수신자(쉼표). 미지정 시 env")
    ap.add_argument("--subject", default="", help="제목. 미지정 시 md 첫 # 헤더")
    ap.add_argument("--no-email", action="store_true", help="전송 생략(검증용)")
    args = ap.parse_args()

    path = args.md if os.path.isabs(args.md) else os.path.join(ROOT, args.md)
    if not os.path.exists(path):
        print(f"제안 파일이 없습니다: {path}", file=sys.stderr)
        return 2
    with open(path, encoding="utf-8") as f:
        body = f.read()

    subject = args.subject or f"[CaskCode] 오늘의 블로그 아이디어 — {first_heading(body)}"
    to_addrs = [a.strip() for a in args.to.split(",") if a.strip()] or None

    if args.no_email:
        print(f"[no-email] 제목: {subject}\n파일: {path}")
        return 0

    from pipelines.common.email_report import send_report
    try:
        sent = send_report(subject, body, to_addrs=to_addrs, attach_path=path)
        print(f"이메일 전송 완료 → {', '.join(sent)}")
    except Exception as e:
        print(f"이메일 전송 실패: {e}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
