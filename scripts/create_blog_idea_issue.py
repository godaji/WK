#!/usr/bin/env python3
"""블로그 아이디어 제안(md)을 Paperclip 이슈로 생성 — CMPA-252.

매일 아침 루틴이 아이디어 md 를 만들고, 이 헬퍼로 **아이디어 1개당 이슈 1개**를
생성한다. 보드(사람)가 그 이슈를 보고 토론/선별한다.

⚠️보드 지시(2026-06-09): 이슈는 **Todo 상태 + 미배정**으로 둔다. 블로그 글은
쓰지 않는다(아이디어 제안까지). 미배정이라 CMO 하트비트가 자동으로 깨어 이슈를
'작업'하지 않는다(=토파일 루프 방지). 보드가 골라 누군가에 배정하면 그때 진행.

- 제목: md 첫 `# ` 헤더 → `[블로그 아이디어] <제목>` (접두로 보드가 한눈에 식별)
- 본문(description): md 원문 전체(1페이지 제안)
- 부모(parentIssueId): 기본 CMPA-252(아이디어 허브). project/goal 은 부모에서 상속.
- 상태: **todo** / 담당: **미배정**(기본). --assignee 로 굳이 배정 가능(권장 안 함).

인증: 환경변수 PAPERCLIP_API_KEY / PAPERCLIP_RUN_ID / PAPERCLIP_COMPANY_ID
(루틴 실행 컨텍스트에 항상 주입됨). API_URL 은 PAPERCLIP_API_URL(기본 127.0.0.1:3100).

사용법:
  python3 scripts/create_blog_idea_issue.py --md content/blog-ideas/<파일>.md
  python3 scripts/create_blog_idea_issue.py --md <파일> --parent <issueId> --dry-run
출력(성공): 마지막 줄에 `ISSUE <identifier> <id>` (루틴이 파싱/링크용).
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

# CMPA-252 (블로그 아이디어 허브) — project/goal 은 이 부모에서 상속.
HUB_ISSUE_ID = "f5fde8a4-2d72-4952-a30d-ecdff1d21204"
CMO_AGENT_ID = "130e33fb-86fb-4a3b-8009-bdd642f6784e"

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))


def api_base():
    return (os.environ.get("PAPERCLIP_API_URL")
            or os.environ.get("PAPERCLIP_RUNTIME_API_URL")
            or "http://127.0.0.1:3100").rstrip("/")


def _headers():
    key = os.environ.get("PAPERCLIP_API_KEY")
    run = os.environ.get("PAPERCLIP_RUN_ID", "")
    if not key:
        raise RuntimeError("PAPERCLIP_API_KEY 환경변수가 없습니다.")
    return {"Authorization": f"Bearer {key}", "X-Paperclip-Run-Id": run,
            "Content-Type": "application/json"}


def _call(method, path, body=None):
    req = urllib.request.Request(
        api_base() + path,
        data=json.dumps(body).encode() if body is not None else None,
        headers=_headers(), method=method)
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def first_heading(md_text):
    for line in md_text.splitlines():
        m = re.match(r"^#\s+(.*)$", line.strip())
        if m:
            return m.group(1).strip()
    return "오늘의 블로그 아이디어"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--md", required=True, help="제안 md 파일 경로")
    ap.add_argument("--parent", default=HUB_ISSUE_ID, help="부모 이슈 id")
    ap.add_argument("--assignee", default="",
                    help="담당 agent id. 기본 미배정(권장 — Todo 백로그로 둠)")
    ap.add_argument("--dry-run", action="store_true", help="생성 안 하고 미리보기")
    args = ap.parse_args()

    path = args.md if os.path.isabs(args.md) else os.path.join(ROOT, args.md)
    if not os.path.exists(path):
        print(f"제안 파일이 없습니다: {path}", file=sys.stderr)
        return 2
    with open(path, encoding="utf-8") as f:
        body_md = f.read()

    title = f"[블로그 아이디어] {first_heading(body_md)}"
    co = os.environ.get("PAPERCLIP_COMPANY_ID")

    if args.dry_run:
        print(f"[dry-run] company={co} parent={args.parent} "
              f"assignee={args.assignee or '(미배정)'} status=todo")
        print(f"[dry-run] title: {title}")
        print(f"[dry-run] body bytes: {len(body_md.encode())}")
        return 0

    # 부모에서 project/goal 상속.
    parent = _call("GET", f"/api/issues/{args.parent}")
    payload = {
        "title": title,
        "description": body_md,
        "parentIssueId": args.parent,
        "projectId": parent.get("projectId"),
        "goalId": parent.get("goalId"),
        # 보드 지시: Todo + 미배정 → CMO 자동 하트비트로 '작업'되지 않게.
        "status": "todo",
    }
    if args.assignee:
        payload["assigneeAgentId"] = args.assignee
    try:
        out = _call("POST", f"/api/companies/{co}/issues", payload)
    except urllib.error.HTTPError as e:
        print(f"이슈 생성 실패: HTTP {e.code} {e.read().decode()[:400]}",
              file=sys.stderr)
        return 4
    ident = out.get("identifier") or "?"
    iid = out.get("id") or "?"
    print(f"이슈 생성 완료: {ident} — {title}")
    print(f"ISSUE {ident} {iid}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
