#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deploy_external_post.py — 외부 작성 블로그 글 배포 (CMPA-355).

보드가 외부에서 작성해 `content/external-posts/` 에 떨군 `.md` 글을 **검증→배포**한다.
"글 작성은 외부, 우리는 배포만." (계약·폴더는 CMPA-353에서 생성.)

글 1개당 파이프라인:
  1) 프런트매터 검증 — 필수 키(layout=post, title, date, categories) + categories 가
     **렌더 버킷**(dev/data/tasting/wprice)인지. 아니면 거부(고아글 방지, CMPA-326).
  2) 파일명 `YYYY-MM-DD-slug.md`(Jekyll _posts 규칙) + 프런트매터 date 와 날짜 일치.
  3) `blog-md/_posts/<같은이름>.md`(WK 정본) + `caskcode-publish/_posts/` 로 이관.
  4) caskcode-publish **surgical push**(처리한 파일만 commit) → 라이브 반영
     (GIT_SSH ~/.ssh/caskcode_deploy_key 재사용 — 메모리 caskcode-publish-deploy-path).
  5) `curl -s <live-url> | grep` 로 라이브 확인(Pages 빌드 지연 대비 재시도).
  6) 원본을 `content/external-posts/published/` 로 이동(이력 보존, 데이터 3원칙).

사용:
  python3 scripts/deploy_external_post.py                 # inbox 신규/수정 글 배포
  python3 scripts/deploy_external_post.py a.md b.md       # 특정 파일만(경로/이름)
  python3 scripts/deploy_external_post.py --sync           # inbox + 이미 배포된 글의 '수정' 감지·재배포
  python3 scripts/deploy_external_post.py --dry-run        # 검증·미리보기만(push/이동 없음)
  python3 scripts/deploy_external_post.py --no-verify      # 라이브 curl 검증 생략(push 는 함)

멱등: 같은 파일을 두 번 돌려도 publish 에 변경이 없으면 push 를 생략하고, 처리 끝난 inbox 원본은
published/ 로 빠져 다음 스캔에서 다시 잡히지 않는다.

변경 감지(`--sync`): inbox 신규/수정 글을 배포한 뒤, 이미 배포돼 `published/` 에 보관된
원본을 라이브 정본(`blog-md/_posts/<같은이름>`)과 비교해 **내용이 달라진 글만** 다시 배포한다.
즉 보드가 (a) inbox 에 수정본을 새로 떨구거나 (b) `published/` 의 글을 직접 고쳐도 모두 잡힌다.
변경이 없으면 아무것도 push 하지 않는다(멱등). 폴더 감시 루틴이 이 모드로 주기 실행한다.
"""
import argparse
import filecmp
import os
import re
import shutil
import subprocess
import sys
import time

import yaml

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
INBOX = os.path.join(ROOT, "content", "external-posts")
PUBLISHED = os.path.join(INBOX, "published")
BLOG_POSTS = os.path.join(ROOT, "blog-md", "_posts")
PUBLISH_REPO = os.path.abspath(os.path.join(ROOT, "..", "caskcode-publish"))
PUBLISH_POSTS = os.path.join(PUBLISH_REPO, "_posts")
DEPLOY_KEY = os.path.expanduser("~/.ssh/caskcode_deploy_key")
GIT_SSH = f"ssh -i {DEPLOY_KEY} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"

# 라이브 사이트(GitHub Pages). 영구링크 = /:year/:month/:day/:title/ (publish _config.yml).
LIVE_BASE = "https://godaji.github.io/CaskCode"

# 렌더 버킷 = 템플릿이 실제로 어떤 목록에 글을 거는 categories 값.
#   dev/data → Code 기둥(blog-md/code.md), tasting/wprice → Cask 기둥(blog-md/cask.md).
# 이 집합 밖이면 URL 200 이어도 어느 목록에도 안 걸리는 '고아글'(CMPA-326).
# (CMPA-400: invest 버킷 전면 폐지 — 더는 받지 않는다.)
RENDER_BUCKETS = {"dev", "data", "tasting", "wprice"}
# 자주 쓰는 오해 → 올바른 버킷 안내(특히 'price' 는 known 목록엔 있으나 렌더 섹션이 없어 고아).
BUCKET_HINTS = {"price": "wprice"}

FNAME_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})-[a-z0-9][a-z0-9-]*\.md$")
FM_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def parse_front_matter(text):
    """파일 맨 위 YAML 프런트매터를 dict 로. 없으면 None."""
    m = FM_RE.match(text)
    if not m:
        return None
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError as e:
        raise ValueError(f"프런트매터 YAML 파싱 실패: {e}")
    return data if isinstance(data, dict) else None


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def validate(path):
    """(ok, errors[], slug, date_str) 반환. ok=False 면 errors 에 거부 사유."""
    name = os.path.basename(path)
    errors = []

    m = FNAME_RE.match(name)
    fname_date = m.group(1) if m else None
    if not m:
        errors.append(
            f"파일명 규칙 위반: '{name}' — `YYYY-MM-DD-slug.md` 여야 함"
            " (slug 은 소문자·숫자·하이픈)."
        )
    slug = name[len("0000-00-00-"):-3] if m else None

    text = open(path, encoding="utf-8").read()
    try:
        fm = parse_front_matter(text)
    except ValueError as e:
        return False, [str(e)], slug, fname_date
    if fm is None:
        return False, ["프런트매터(--- 사이 YAML) 가 없습니다."], slug, fname_date

    # 필수 키
    if str(fm.get("layout", "")).strip() != "post":
        errors.append("`layout: post` 필요(현재: %r)." % fm.get("layout"))
    if not str(fm.get("title", "")).strip():
        errors.append("`title` 필요(비어있음).")
    date_val = fm.get("date")
    if date_val is None or not str(date_val).strip():
        errors.append("`date` 필요(`YYYY-MM-DD HH:MM:SS +0900`).")

    # categories = 렌더 버킷?
    cats = [str(c).strip() for c in as_list(fm.get("categories")) if str(c).strip()]
    if not cats:
        errors.append("`categories` 필요(예: `[data]`).")
    elif not (set(cats) & RENDER_BUCKETS):
        hint = ""
        for c in cats:
            if c in BUCKET_HINTS:
                hint = f" '{c}' 대신 '{BUCKET_HINTS[c]}' 을 쓰세요."
                break
        errors.append(
            f"categories {cats} 에 렌더 버킷이 없습니다(고아글, CMPA-326)."
            f" 허용: {sorted(RENDER_BUCKETS)}.{hint}"
        )

    # 파일명 날짜 ↔ 프런트매터 date 일치
    if fname_date and date_val is not None and str(date_val)[:10] != fname_date:
        errors.append(
            f"파일명 날짜({fname_date}) ≠ 프런트매터 date({str(date_val)[:10]})."
        )

    return (not errors), errors, slug, fname_date


def git(args, **kw):
    return subprocess.run(["git", "-C", PUBLISH_REPO] + args,
                          capture_output=True, text=True, **kw)


def surgical_push(rel_paths, titles, dry_run):
    """처리한 _posts/ 파일만 commit + push(surgical). 변경 없으면 멱등 스킵.

    rel_paths: ['_posts/2026-06-20-x.md', ...] (publish 리포 기준 상대경로).
    반환: True=push 성공/변경없음, False=실패.
    """
    st = git(["status", "--porcelain"] + rel_paths)
    if not st.stdout.strip():
        print("  변경 없음 → commit/push 스킵(멱등).")
        return True
    if dry_run:
        print("  [dry-run] 발행 대기:")
        print("   " + git(["status", "--short"] + rel_paths).stdout.strip())
        return True
    if not os.path.isfile(DEPLOY_KEY):
        print(f"  ⚠️ 배포키 없음({DEPLOY_KEY}) → push 생략(로컬 _posts 는 최신).")
        return False
    git(["add"] + rel_paths).check_returncode()
    label = titles[0] if len(titles) == 1 else f"{len(titles)}건"
    msg = (
        f"deploy(post): 외부 작성 글 배포 — {label} (CMPA-355)\n\n"
        f"deploy_external_post.py surgical push · 외부글 검증→발행"
        f"(렌더버킷·고아글 가드 CMPA-326).\n\n"
        f"Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>"
    )
    git(["-c", "user.name=WK CEO", "-c", "user.email=shhong@dudaji.com",
         "commit", "-q", "-m", msg]).check_returncode()
    env = {**os.environ, "GIT_SSH_COMMAND": GIT_SSH}
    p = subprocess.run(["git", "-C", PUBLISH_REPO, "push", "origin", "HEAD"],
                       capture_output=True, text=True, env=env)
    print("  push:", "OK" if p.returncode == 0 else f"FAIL\n{p.stderr}")
    return p.returncode == 0


def live_url(slug, date_str):
    y, mth, d = date_str.split("-")
    return f"{LIVE_BASE}/{y}/{mth}/{d}/{slug}/"


def verify_live(url, title, tries=8, pause=20):
    """Pages 빌드 지연 대비 재시도하며 라이브 페이지에서 제목 일부를 grep."""
    needle = re.sub(r"\s+", " ", title).strip()[:18]
    for i in range(1, tries + 1):
        p = subprocess.run(["curl", "-s", "-o", "-", "-w", "\n%{http_code}", url],
                           capture_output=True, text=True)
        body, _, code = p.stdout.rpartition("\n")
        if code == "200" and needle and needle in body:
            print(f"  ✅ 라이브 확인({code}) — '{needle}' 발견: {url}")
            return True
        print(f"  …시도 {i}/{tries} (HTTP {code or '?'}) — Pages 빌드 대기 {pause}s")
        if i < tries:
            time.sleep(pause)
    print(f"  ⚠️ 라이브 미확인(빌드 지연일 수 있음): {url}")
    return False


def discover(args_files):
    """배포 대상 .md 경로 목록. 인자 지정 없으면 INBOX 전체 스캔(_*·README 제외)."""
    if args_files:
        out = []
        for f in args_files:
            p = f if os.path.isabs(f) else os.path.join(INBOX, os.path.basename(f))
            out.append(p)
        return out
    files = []
    for n in sorted(os.listdir(INBOX)):
        if n.endswith(".md") and not n.startswith("_") and n != "README.md":
            files.append(os.path.join(INBOX, n))
    return files


def stage(path, name, dry_run):
    """검증 통과한 글을 blog-md/_posts(WK 정본)+publish/_posts 로 복사(스테이징).

    dry_run 이면 publish 쪽에만 임시 복사해 git diff 미리보기를 가능하게 한다."""
    if not dry_run:
        shutil.copy2(path, os.path.join(BLOG_POSTS, name))
    shutil.copy2(path, os.path.join(PUBLISH_POSTS, name))


def published_changes():
    """이미 배포돼 published/ 에 보관된 글 중 라이브 정본(blog-md/_posts)과 내용이
    달라진(또는 _posts 에 없는) 것들의 경로 목록. inbox 수정 워크플로와 별개로,
    published/ 의 글을 직접 고친 경우의 '변경'을 잡는다."""
    if not os.path.isdir(PUBLISHED):
        return []
    out = []
    for n in sorted(os.listdir(PUBLISHED)):
        if not n.endswith(".md") or n.startswith("_") or n == "README.md":
            continue
        pub = os.path.join(PUBLISHED, n)
        live = os.path.join(BLOG_POSTS, n)
        if not os.path.isfile(live) or not filecmp.cmp(pub, live, shallow=False):
            out.append(pub)
    return out


def main():
    ap = argparse.ArgumentParser(description="외부 작성 블로그 글 검증→배포 (CMPA-355)")
    ap.add_argument("files", nargs="*", help="특정 .md 파일(미지정 시 inbox 전체 스캔)")
    ap.add_argument("--sync", action="store_true",
                    help="inbox 배포 + 이미 배포된(published/) 글의 '수정'도 감지·재배포")
    ap.add_argument("--dry-run", action="store_true",
                    help="검증·미리보기만(이관/push/이동 없음)")
    ap.add_argument("--no-verify", action="store_true",
                    help="라이브 curl 검증 생략(push 는 수행)")
    args = ap.parse_args()

    # 처리 대상 = inbox 신규/수정(move_after=True) + (--sync) published 수정(move_after=False).
    # 이름 기준 dedup — inbox 가 우선(같은 이름이면 inbox 본을 쓰고 published 본은 건너뜀).
    queue = [(p, True) for p in discover(args.files)]
    seen = {os.path.basename(p) for p, _ in queue}
    if args.sync and not args.files:
        for p in published_changes():
            if os.path.basename(p) not in seen:
                queue.append((p, False))
                seen.add(os.path.basename(p))

    if not queue:
        print("배포·갱신할 외부 글이 없습니다(inbox 비었고 변경된 published 글 없음).")
        return 0

    deployed = []  # (rel, title, slug, date, src, move_after)
    rejected = 0
    for path, move_after in queue:
        name = os.path.basename(path)
        origin = "inbox" if move_after else "수정 감지(published)"
        print(f"\n📄 {name}  [{origin}]")
        if not os.path.isfile(path):
            print(f"  ⛔ 파일 없음: {path}")
            rejected += 1
            continue
        ok, errors, slug, date_str = validate(path)
        if not ok:
            print("  ⛔ 거부:")
            for e in errors:
                print(f"     - {e}")
            rejected += 1
            continue
        title = parse_front_matter(open(path, encoding="utf-8").read())["title"]
        print(f"  ✓ 검증 통과 — slug={slug} date={date_str}")
        if args.dry_run:
            print(f"  [dry-run] 발행 예정 → {live_url(slug, date_str)}")
        stage(path, name, args.dry_run)
        deployed.append((os.path.join("_posts", name), title, slug, date_str,
                         path, move_after))

    if not deployed:
        print(f"\n결과: 배포 0건, 거부 {rejected}건.")
        return 1 if rejected else 0

    print(f"\n=== surgical push ({len(deployed)}건) ===")
    rel_paths = [d[0] for d in deployed]
    titles = [d[1] for d in deployed]
    pushed = surgical_push(rel_paths, titles, args.dry_run)

    if args.dry_run:
        # dry-run: publish 에 복사해 둔 임시 파일 원복(워킹트리 clean 유지).
        git(["checkout", "--", "_posts"])
        git(["clean", "-fq", "--", "_posts"])
        print(f"\n[dry-run] 검증 {len(deployed)}건 통과 · 거부 {rejected}건 · 라이브 미변경.")
        return 0

    if not pushed:
        print("\n⚠️ push 실패 — inbox 원본은 published/ 로 옮기지 않음(재시도 가능).")
        return 1

    # 라이브 검증 + (inbox 원본만) 이력 이동. published 수정본은 제자리 유지.
    os.makedirs(PUBLISHED, exist_ok=True)
    for rel, title, slug, date_str, src, move_after in deployed:
        if not args.no_verify:
            print(f"\n🔎 라이브 검증: {title}")
            verify_live(live_url(slug, date_str), title)
        if move_after:
            shutil.move(src, os.path.join(PUBLISHED, os.path.basename(src)))
            print(f"  📦 원본 → published/{os.path.basename(src)}")
        else:
            print("  ♻️ published 수정본 재배포(제자리 유지).")

    print(f"\n✅ 배포/갱신 {len(deployed)}건 완료 · 거부 {rejected}건.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
