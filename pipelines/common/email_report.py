#!/usr/bin/env python3
"""Gmail SMTP 로 리포트(md/텍스트)를 이메일 전송하는 공용 헬퍼.

인증: 환경변수 `GMAIL_APP_PASSWORD`(Gmail 앱 비밀번호) 사용.
발신자: `GMAIL_SENDER`(없으면 `EMAIL_FROM`, 둘 다 없으면 첫 수신자).
수신자: 인자 to_addrs 우선, 없으면 `PAPERCLIP_EMAIL_RECIPIENTS`(쉼표 구분).

본문은 md 원문을 text/plain + 간단 변환 text/html(코드블록 monospace) 두 파트로
보낸다. 첨부로 원본 md 파일을 함께 보낼 수 있다.

사용 예:
  from pipelines.common.email_report import send_report
  send_report("제목", md_text, to_addrs=["shhong@dudaji.com"], attach_path="x.md")
"""
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def _recipients(to_addrs):
    if to_addrs:
        return [a.strip() for a in to_addrs if a and a.strip()]
    env = os.environ.get("PAPERCLIP_EMAIL_RECIPIENTS", "")
    return [a.strip() for a in env.split(",") if a.strip()]


def _sender(recipients):
    return (os.environ.get("GMAIL_SENDER")
            or os.environ.get("EMAIL_FROM")
            or (recipients[0] if recipients else ""))


def _inline_md(text):
    """인라인 마크다운(**bold**, [text](url))을 HTML로. 먼저 escape 후 변환."""
    import html
    import re
    out = html.escape(text)
    out = re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)",
                 r'<a href="\2" style="color:#1558d6;text-decoration:none">\1</a>',
                 out)
    # 셀 안의 맨 URL(마크다운 링크 아님)은 깔끔한 '바로가기 ↗' 링크로.
    out = re.sub(
        r'(?<!["\w])(https?://[^\s<]+)',
        r'<a href="\1" style="color:#1558d6;text-decoration:none;'
        r'white-space:nowrap">바로가기 ↗</a>',
        out)
    out = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", out)
    return out


def _num_align(cell):
    """숫자/통화/퍼센트/델타 셀은 우측 정렬해서 표를 읽기 좋게."""
    import re
    return "right" if re.fullmatch(r"[\$\d.,%pP\s∆Δ+\-−–%()]+", cell.strip()) else "left"


def _split_row(line):
    cells = line.strip().strip("|").split("|")
    return [c.strip() for c in cells]


def _md_blocks(md_text):
    """의존성 없는 경량 md→html 블록 렌더(래퍼 없이 본문 파트만 반환).

    표·헤더·굵게·링크·인용·목록·구분선을 렌더링. 또한 '## 추가 정보' 섹션 안의
    `### 술이름` 스토리 카드는 접이식 <details>(이름 눌러 펼치기)로 감싼다
    (보드 CMPA-273 — 메일에서 설명을 클릭해 펼쳐보기. 일부 클라이언트(Gmail)는
    <details>를 무시하고 내용을 그대로 보여줌 — graceful degradation)."""
    import re

    lines = md_text.split("\n")
    parts = []
    i = 0
    n = len(lines)
    in_story = False   # '추가 정보' 섹션 안인지(스토리 카드 접이식 대상)

    th = ('style="border:1px solid #d6d8de;padding:7px 11px;background:#f3f4f7;'
          'text-align:left;font-weight:600;white-space:nowrap"')

    while i < n:
        line = lines[i]
        stripped = line.strip()

        # 표: 연속된 '|' 라인 수집
        if stripped.startswith("|") and "|" in stripped[1:]:
            block = []
            while i < n and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            rows = [_split_row(b) for b in block]
            # 구분선(---) 행 제거, 헤더 = 첫 행
            sep_idx = None
            for idx, r in enumerate(rows):
                if r and all(re.fullmatch(r":?-{2,}:?", c or "-") for c in r):
                    sep_idx = idx
                    break
            header = rows[0]
            body_rows = [r for idx, r in enumerate(rows)
                         if idx != 0 and idx != sep_idx]
            html_rows = []
            html_rows.append(
                "<tr>" + "".join(f"<th {th}>{_inline_md(c)}</th>"
                                 for c in header) + "</tr>")
            for r in body_rows:
                cells = []
                for c in r:
                    align = _num_align(c)
                    cells.append(
                        f'<td style="border:1px solid #e7e8ec;padding:7px 11px;'
                        f'text-align:{align}">{_inline_md(c)}</td>')
                html_rows.append("<tr>" + "".join(cells) + "</tr>")
            parts.append(
                '<table style="border-collapse:collapse;width:100%;'
                'margin:14px 0;font-size:13px">' + "".join(html_rows)
                + "</table>")
            continue

        # 보강 스토리 카드: '추가 정보' 섹션의 `### 술이름` → 접이식 <details>.
        if in_story:
            m3 = re.match(r"^###\s+(.*)$", stripped)
            if m3:
                name = m3.group(1)
                inner = []
                i += 1
                while i < n:
                    s2 = lines[i].strip()
                    if s2.startswith("### ") or re.match(r"^#{1,2}\s", s2):
                        break
                    inner.append(lines[i])
                    i += 1
                inner_html = _md_blocks("\n".join(inner))
                parts.append(
                    '<details style="margin:6px 0;border:1px solid #e4e6eb;'
                    'border-radius:8px;padding:6px 12px">'
                    '<summary style="cursor:pointer;font-weight:600;color:#111">'
                    f'🥃 {_inline_md(name)}</summary>'
                    f'<div style="margin-top:4px">{inner_html}</div></details>')
                continue

        # 헤더
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            if level == 2:   # 섹션 전환 — '추가 정보' 진입/이탈 추적.
                in_story = "추가 정보" in m.group(2)
            size = {1: 20, 2: 18, 3: 16}.get(level, 14)
            mt = 20 if level <= 2 else 14
            parts.append(
                f'<div style="font-size:{size}px;font-weight:700;'
                f'margin:{mt}px 0 6px;color:#111">{_inline_md(m.group(2))}</div>')
            i += 1
            continue

        # 구분선
        if re.fullmatch(r"(-{3,}|\*{3,}|_{3,})", stripped):
            parts.append('<hr style="border:none;border-top:1px solid #e7e8ec;'
                         'margin:18px 0">')
            i += 1
            continue

        # 인용
        if stripped.startswith(">"):
            quote = []
            while i < n and lines[i].strip().startswith(">"):
                quote.append(lines[i].strip().lstrip(">").strip())
                i += 1
            parts.append(
                '<blockquote style="margin:12px 0;padding:8px 14px;'
                'border-left:3px solid #c9ccd3;background:#fafafb;color:#555;'
                f'font-size:13px">{_inline_md(" ".join(quote))}</blockquote>')
            continue

        # 목록
        if re.match(r"^[-*]\s+", stripped):
            items = []
            while i < n and re.match(r"^[-*]\s+", lines[i].strip()):
                items.append(re.sub(r"^[-*]\s+", "", lines[i].strip()))
                i += 1
            lis = "".join(f'<li style="margin:3px 0">{_inline_md(it)}</li>'
                          for it in items)
            parts.append(f'<ul style="margin:8px 0;padding-left:22px">{lis}</ul>')
            continue

        # 빈 줄
        if not stripped:
            i += 1
            continue

        # 일반 문단
        parts.append(f'<p style="margin:8px 0">{_inline_md(stripped)}</p>')
        i += 1

    return "\n".join(parts)


def _md_to_html(md_text):
    """경량 md→html(이메일 본문). 블록 렌더(_md_blocks)를 완성 HTML 로 감싼다."""
    body = _md_blocks(md_text)
    return (
        '<html><body style="margin:0;background:#f0f1f4;padding:18px">'
        '<div style="max-width:720px;margin:0 auto;background:#fff;'
        'border:1px solid #e4e6eb;border-radius:10px;padding:24px 26px;'
        'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Roboto,sans-serif;'
        'font-size:14px;line-height:1.55;color:#222">'
        f'{body}'
        '<div style="margin-top:22px;padding-top:12px;border-top:1px solid #eee;'
        'color:#9aa0a6;font-size:12px">WK 데이터봇 · 자동 생성 리포트</div>'
        '</div></body></html>'
    )


def _ensure_caskcode_prefix(subject):
    """모든 메일 제목에 '[CaskCode' prefix 를 구조적으로 강제(멱등) — CMPA-392/393.

    제목이 '[CaskCode'(대괄호 포함)로 시작하지 않으면 '[CaskCode] ' 를 앞에 붙인다.
    이미 붙어 있으면(`[CaskCode]`, `[CaskCode 면세]` 등) 그대로 둔다. 향후 새 발신자가
    prefix 를 누락하는 것을 정본 1곳(send_report)에서 구조적으로 불가능하게 만든다."""
    s = (subject or "").lstrip()
    if s.startswith("[CaskCode"):
        return subject
    return "[CaskCode] " + (subject or "")


def send_report(subject, body_md, to_addrs=None, attach_path=None,
                sender_name="WK 데이터봇"):
    """리포트를 이메일로 전송. 성공 시 수신자 리스트 반환, 자격 없으면 RuntimeError."""
    subject = _ensure_caskcode_prefix(subject)
    password = os.environ.get("GMAIL_APP_PASSWORD")
    if not password:
        raise RuntimeError("GMAIL_APP_PASSWORD 환경변수가 없어 이메일을 보낼 수 없습니다.")
    recipients = _recipients(to_addrs)
    if not recipients:
        raise RuntimeError("수신자가 없습니다 (to_addrs / PAPERCLIP_EMAIL_RECIPIENTS).")
    sender = _sender(recipients)
    if not sender:
        raise RuntimeError("발신자를 결정할 수 없습니다 (GMAIL_SENDER/EMAIL_FROM).")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = formataddr((sender_name, sender))
    msg["To"] = ", ".join(recipients)
    msg.set_content(body_md)
    msg.add_alternative(_md_to_html(body_md), subtype="html")

    if attach_path and os.path.exists(attach_path):
        with open(attach_path, "rb") as f:
            data = f.read()
        msg.add_attachment(data, maintype="text", subtype="markdown",
                           filename=os.path.basename(attach_path))

    ctx = ssl.create_default_context()
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as s:
        s.starttls(context=ctx)
        s.login(sender, password)
        s.send_message(msg)
    return recipients


if __name__ == "__main__":
    # 셀프테스트: 발신자/수신자 해석만 출력(실제 전송 안 함).
    recips = _recipients(None)
    print("recipients:", recips)
    print("sender:", _sender(recips))
    print("has password:", bool(os.environ.get("GMAIL_APP_PASSWORD")))
