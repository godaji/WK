#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""refresh_whisky_publish.py — 위스키 가격 리포트 '배포(publish)' 게이트 오케스트레이터 (CMPA-213).

데이터 수집·정규화·리포트(md) 생성은 별도 통합 루틴(run_whisky_price_pipeline.py / routine
f66b4e58)이 누적한다. **이 스크립트는 그 정본 리포트를 실제로 내보내는(publish) 단계**다 —
오케스트레이터가 의도적으로 분리해 둔 배포 게이트(CMPA-33)라서, 정본 6월 리포트가 생겨도
deploy/ 와 블로그가 5월에 멈춰 있던 문제(CMPA-213)를 자동화로 막는다.

체인(전부 결정론·기존 스크립트 재사용):
  1) reports/make_distribution.py            정본 최신본 → 공개 배포본(데일리샷 컬럼 제거=G1, 면책·19세 고지)
  2) scripts/build_deploy.py                 deploy/ 재빌드(최신 배포본 = whisky-price 최신 포인터 + 에디션 누적)
  3) pipelines/shilla_dutyfree/build_blog_md.py   블로그(blog-md/) 재빌드(자동 패치 글 등)
  4) (--publish, 기본 ON) caskcode-publish 리포에 _posts/·assets/ 스코프 동기화 + commit + push
        → 라이브 https://godaji.github.io/CaskCode/ 반영(GitHub Pages Actions).
        noindex 게이트(c7405e7d)는 build_deploy/build_blog_md 가 이미 유지하므로 그대로 나간다.
  (CMPA-284: 블로그 '앱'(/apps/) 섹션 제거 — deploy/→blog/apps 미러 폐지. deploy/ 데이터
   앱 자체는 build_deploy 가 계속 빌드하지만 블로그로 미러/노출하지 않는다.)

⚠️ 라이브 push 는 외부 공개 경로다. 보드가 CMPA-213 에서 블로그 배포+루틴화를 명시 승인했고,
noindex 가 유지되므로 색인은 막힌 상태로 나간다. push 만 끄려면 --no-publish.

사용:
  python3 scripts/refresh_whisky_publish.py                # 전체(배포본→deploy→blog→라이브 push)
  python3 scripts/refresh_whisky_publish.py --no-publish   # 로컬까지만(blog-md 갱신, 라이브 push 생략)
  python3 scripts/refresh_whisky_publish.py --run-date 2026-06-07
"""
import argparse
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PY = sys.executable

MAKE_DIST = os.path.join(ROOT, "reports", "make_distribution.py")
BUILD_DEPLOY = os.path.join(ROOT, "scripts", "build_deploy.py")
BUILD_BLOG = os.path.join(ROOT, "pipelines", "shilla_dutyfree", "build_blog_md.py")

# CMPA-214/250: 블로그 글(_posts/)이 발행 스코프 — 자동 생성 패치 글
# (_posts/<날짜>-price-patch.md)이 라이브에 올라가게 동기화한다.
BLOG_POSTS = os.path.join(ROOT, "blog-md", "_posts") + os.sep
# CMPA-255: CSS·이미지(assets/)도 발행 스코프에 포함 — style.css 는 generator(_css())
# 산출물이라 표 가로스크롤/모바일 CSS 를 고쳐도 _posts/ 만 동기화하면 라이브 stale.
BLOG_ASSETS = os.path.join(ROOT, "blog-md", "assets") + os.sep
PUBLISH_REPO = os.path.abspath(os.path.join(ROOT, "..", "caskcode-publish"))
PUBLISH_POSTS = os.path.join(PUBLISH_REPO, "_posts") + os.sep
PUBLISH_ASSETS = os.path.join(PUBLISH_REPO, "assets") + os.sep
DEPLOY_KEY = os.path.expanduser("~/.ssh/caskcode_deploy_key")
GIT_SSH = f"ssh -i {DEPLOY_KEY} -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new"


def run(label, cmd, **kw):
    print(f"\n=== {label} ===\n$ {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, **kw)
    ok = proc.returncode == 0
    print(f"  -> {'OK' if ok else 'FAIL(rc=%d)' % proc.returncode}", flush=True)
    return ok


# 발행 스코프 = (소스 → publish) 동기화 페어. _posts/(블로그 글) + assets/(CSS/이미지).
# blog-md 가 _posts 의 정본(손글 글 포함)이라 --delete 안전 — publish 의 잉여만 정리.
# (CMPA-284: apps/ 미러 폐지 — 블로그 '앱' 섹션 제거.)
SYNC_PAIRS = [
    ("_posts/", BLOG_POSTS, PUBLISH_POSTS),   # CMPA-214 갭 해소: 블로그 글 포함.
    ("assets/", BLOG_ASSETS, PUBLISH_ASSETS),  # CMPA-255 갭 해소: CSS/이미지 포함.
]


def publish_live(run_date_tag, dry_run=False):
    """발행 스코프(_posts/ + assets/) 를 caskcode-publish 로 동기화 + commit + push(라이브).

    dry_run=True 면 rsync -n(미변경) 으로 '무엇이 올라갈지'만 출력하고 git 은 건드리지
    않는다 — 라이브 push 없이 발행 스코프가 새 블로그 글을 포함함을 증명할 때 쓴다(CMPA-250).
    """
    if not os.path.isdir(PUBLISH_REPO):
        print(f"  ⚠️ publish 리포 없음({PUBLISH_REPO}) → 동기화 스킵.")
        return False
    if not dry_run and not os.path.isfile(DEPLOY_KEY):
        print(f"  ⚠️ 배포키 없음({DEPLOY_KEY}) → 라이브 push 스킵. (로컬 blog-md 는 최신)")
        return False

    if dry_run:
        # 실제 변경 없이 발행 스코프 미리보기(itemized). _posts/ 에 새 패치 글이
        # 포함되는지 여기서 눈으로 확인 가능.
        for label, src, dst in SYNC_PAIRS:
            if not os.path.isdir(src):
                print(f"  (소스 없음 — 스킵: {label})")
                continue
            run(f"publish[dry-run]: rsync {label}",
                ["rsync", "-rcn", "--delete", "--itemize-changes", src, dst])
        print("  [dry-run] git add/commit/push 생략 — 라이브 미변경.")
        return True

    # 0) 발행 클론 자가치유(CMPA-674): 이 리포는 순수 배포 미러다(콘텐츠는 항상 blog-md 에서
    #    rsync). 다른 발행 경로(주간 다이제스트·일간 오케스트레이터 등)가 origin 에 push 하면
    #    이 클론이 뒤처지거나 갈라져(ahead/behind) push 가 'fetch first' 로 거부된다(신라 루틴
    #    상습 실패). rsync 전에 origin/main 으로 fetch+reset 해 갈라짐을 폐기하고 fast-forward
    #    push 가 되게 한다. 로컬 배포커밋은 재-rsync 로 재현되므로 손실 없음. fetch 실패(네트워크)
    #    시엔 reset 을 건너뛰고 기존 동작(그대로 push 시도)으로 폴백한다.
    env = {**os.environ, "GIT_SSH_COMMAND": GIT_SSH}
    g = ["git", "-C", PUBLISH_REPO]
    if run("publish: fetch origin/main(자가치유)", g + ["fetch", "origin", "main"], env=env):
        run("publish: reset --hard origin/main", g + ["reset", "--hard", "origin/main"])
    else:
        print("  ⚠️ fetch 실패 → reset 생략, 기존 클론 상태로 push 시도(폴백).")

    # 1) 발행 스코프 동기화(소스 → publish)
    for label, src, dst in SYNC_PAIRS:
        if not os.path.isdir(src):
            print(f"  (소스 없음 — 스킵: {label})")
            continue
        if not run(f"publish: rsync {label}",
                   ["rsync", "-rc", "--delete", src, dst]):
            return False

    scoped = ["_posts", "assets"]
    # 변경 없으면 commit 생략(멱등)
    st = subprocess.run(g + ["status", "--porcelain"] + scoped,
                        capture_output=True, text=True)
    if not st.stdout.strip():
        print("  변경 없음(_posts/·assets/) → commit/push 스킵(멱등).")
        return True
    subprocess.run(g + ["add"] + scoped, check=True)
    msg = (f"deploy(_posts,assets): 위스키 블로그 글·CSS publish 최신화 ({run_date_tag})\n\n"
           f"refresh_whisky_publish.py 자동 배포 · _posts/(CMPA-214)·assets/(CMPA-255) 발행 스코프 · "
           f"noindex 게이트 유지(c7405e7d).\n\n"
           f"Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>")
    subprocess.run(g + ["-c", "user.name=WK CEO",
                        "-c", "user.email=shhong@dudaji.com",
                        "commit", "-q", "-m", msg], check=True)
    return run("publish: git push", g + ["push", "origin", "HEAD"], env=env)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--run-date", help="배포본 실행일(YYYY-MM-DD). 미지정 시 오늘(KST).")
    ap.add_argument("--no-publish", action="store_true",
                    help="라이브(caskcode-publish) push 생략 — 로컬 blog-md 까지만.")
    ap.add_argument("--dry-run-publish", action="store_true",
                    help="발행 스코프(_posts/+assets/)를 rsync -n 으로 미리보기만(라이브 미변경).")
    args = ap.parse_args()

    steps_ok = []
    # 1) 배포본(공개 안전판) — 최신 정본 자동 선택
    dist_cmd = [PY, MAKE_DIST]
    if args.run_date:
        dist_cmd += ["--run-date", args.run_date]
    steps_ok.append(("배포본 생성", run("1.배포본(make_distribution)", dist_cmd, cwd=ROOT)))
    # 2) deploy 재빌드
    steps_ok.append(("deploy 빌드", run("2.deploy(build_deploy)", [PY, BUILD_DEPLOY], cwd=ROOT)))
    # 3) 블로그 재빌드(자동 패치 글 — 블로그 '앱' 섹션은 CMPA-284 로 제거됨)
    #    루틴 자동발행은 오늘자/최신 패치 1건만 생성(CMPA-264) — 과거 글 보존, 전체 재생성 금지.
    steps_ok.append(("blog 빌드", run("3.blog(build_blog_md)",
                                      [PY, BUILD_BLOG, "--latest-only"], cwd=ROOT)))
    # 4) 라이브 push
    if args.no_publish:
        print("\n--no-publish → 라이브 push 생략.")
    else:
        tag = args.run_date or "latest"
        steps_ok.append(("라이브 publish", publish_live(tag, dry_run=args.dry_run_publish)))

    print("\n=== 요약 ===")
    hard_fail = False
    for name, ok in steps_ok:
        print(f"  {'✅' if ok else '❌'} {name}")
        # 1~3 단계 실패는 hard-fail(배포 무결성). publish 실패는 경고(로컬은 최신).
        if not ok and name in ("배포본 생성", "deploy 빌드", "blog 빌드"):
            hard_fail = True
    if hard_fail:
        print("핵심 빌드 단계 실패 → 비정상 종료.")
        return 1
    print("GREEN — 위스키 리포트 publish 완료.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
