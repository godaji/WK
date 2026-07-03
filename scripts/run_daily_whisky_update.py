#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""[일간 올인원] 면세·마트 수집 후 파생 페이지 직렬 자동 갱신·발행 (CMPA-672 / 부모 CMPA-670).

이 오케스트레이터 한 개가 **데이터 수집부터 리포트 갱신·발행까지 전부**를 의존성 순서대로
직렬로 수행한다(Option A — 보드 확정 2026-06-29). "all-in-one" 루틴이다.

직렬 체인:
  STAGE 0  데이터 수집(best-effort·에러격리)  → 롯데·신세계·데일리샷·신라(크롤+변동감지)·트레이더스OCR
  STAGE 1  normalize_dataset.py            → normalized_prices.csv (국내최저 floor 갱신)
  STAGE 2  build_compare.py --blog --date  → dutyfree-whisky-compare.md(면세 비교 주간 로그)
                                              + mart-cheaper-whisky.md(마트에서 구매할 때/면세보다 싼)
  STAGE 3  build_blog_md.py --latest-only  → 신라 price-patch 이번주 로그 재빌드(멱등; 크롤·메일은
                                              08:00 루틴 71f351fc 가 이미 함 → 여기선 재렌더만)
  STAGE 4  caskcode-publish surgical push  → STAGE2/3 에서 바뀐 _posts 만 commit·push + curl 검증

설계 결정(메모 [[caskcode-publish-deploy-path]] 준수):
- **surgical push** — 톱레벨/_posts 전체 sync(refresh_whisky_publish.publish_live)는 미발행 초안이
  섞여 발행되므로 쓰지 않는다. 바뀐 '대상 글 파일만' 골라 copy→git add <파일>→commit→push.
- 발행 레포는 **origin/main(라이브)과 동기화된** 클론을 자동 선택한다(CMPA-672 발견: WK 파이썬
  스크립트가 계산하는 ../caskcode-publish 클론이 라이브와 diverge 돼 있을 수 있음 → fetch 로 판별).
- STAGE3 는 best-effort(이미 08:00 루틴이 발행) — 실패해도 STAGE2 핵심 페이지 발행을 막지 않는다.
- robots(noindex/index)는 각 글 front matter 그대로 보존(여기서 바꾸지 않음).

데이터 원칙: CMPA-156 누적(스냅샷 덮어쓰기 금지)·CMPA-496 per_source_latest_floor·
CMPA-321 면세 제외·CMPA-177 토큰 병합 금지. 각 STAGE 는 앞 STAGE 성공 후 진행(직렬).
멱등: 변경 없으면 발행 skip.

사용:
  python3 scripts/run_daily_whisky_update.py                 # 전체(정규화→빌드→발행→curl)
  python3 scripts/run_daily_whisky_update.py --dry-run       # 빌드까지, push 없이 미리보기
  python3 scripts/run_daily_whisky_update.py --no-publish    # 빌드만(발행·curl 생략)
  python3 scripts/run_daily_whisky_update.py --skip-normalize # STAGE1 생략(정규화 최신일 때)
  python3 scripts/run_daily_whisky_update.py --date 2026-06-28
  python3 scripts/run_daily_whisky_update.py --force          # 신선도 가드 무시(수동 강제)

신선도 가드(CMPA-678): 요청일이 최신 면세 스냅샷보다 미래면(=오늘 수집 미완료) 멱등
no-op 으로 즉시 종료한다. 06-28 데이터로 06-29 미래날짜 페이지를 찍어 중복글을 발행하는
사고를 막는다 — 수집 루틴(06:00~08:40 KST) 이후 재실행하면 통과. --force 로 우회 가능.
"""
import argparse
import datetime
import glob
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
PY = sys.executable

NORMALIZE = os.path.join(ROOT, "scripts", "normalize_dataset.py")
BUILD_COMPARE = os.path.join(ROOT, "pipelines", "dutyfree_compare", "build_compare.py")
BUILD_BLOG = os.path.join(ROOT, "pipelines", "shilla_dutyfree", "build_blog_md.py")
BUILD_CHANGELOG = os.path.join(ROOT, "pipelines", "changelog", "build_changelog.py")
POSTS_DIR = os.path.join(ROOT, "blog-md", "_posts")
DEPLOY_KEY = os.environ.get(
    "CASKCODE_DEPLOY_KEY",
    os.path.join(os.path.expanduser("~"), ".ssh", "caskcode_deploy_key"))
GIT_SSH = (f"ssh -i {DEPLOY_KEY} -o IdentitiesOnly=yes "
           f"-o StrictHostKeyChecking=accept-new")
LIVE_BASE = "https://godaji.github.io/CaskCode"


def kst_today():
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=9)).date()


# ── STAGE 0 수집기 (Option A — 보드 확정 2026-06-29) ───────────────────────────
# 한 루틴이 수집까지 전부 한다. 각 수집기는 **best-effort·에러격리**: 한 소스가 실패해도
# 전체를 막지 않고 '최신 가용 스냅샷'으로 빌드 계속(데이터 3원칙 CMPA-156). 각 수집기는
# 자체 멱등(같은 날 재수집=그 날 스냅샷 갱신)·pacing(OCR 12h·dailyshot slot) 가드를 가진다.
# (정본 명령은 각 수집 루틴 설명과 동일: dailyshot 101·lotte 647·ssg 652·shilla 168·OCR 424.)
COLLECTORS = [
    ("롯데면세", [PY, "-m", "pipelines.lotte_dutyfree.crawl_lotte"], 300),
    ("신세계SSG", [PY, "-m", "pipelines.ssg_dutyfree.crawl_ssg"], 300),
    # 데일리샷: 워치리스트 per-item 페이지가 조회(0.7s pace)라 느림 → 넉넉히(routine 101 이 09:00
    # 에 별도 수집하므로 09:15 스케줄 실행 땐 이미 신선; 타임아웃은 standalone 완주용 안전망).
    ("데일리샷", [PY, os.path.join("pipelines", "dailyshot", "crawl_dailyshot.py")], 900),
    # 신라: STAGE0 수집 제거(CMPA-701 보드 승인 2026-06-29). 신라는 08:00 전용 루틴
    # (71f351fc)이 크롤+변동감지+이메일+발행을 모두 담당 → 09:15 올인원이 한 번 더 크롤하는 것은
    # 순수 중복이었다. 정규화(STAGE1)·발행(STAGE3/4)은 08:00 적재분(신라 일별 CSV)을 그대로 읽는다.
    # 트레이더스/코스트코 OCR: 최신순 2개·pace 12h 자체 가드(중복 다운로드 회피)
    ("트레이더스OCR",
     [PY, os.path.join("pipelines", "youtube_traders", "frame_ocr", "run_ocr_collection.py"),
      "--newest-first", "--max", "2", "--blog"], 420),
]


def stage0_collect():
    """5개 소스를 직렬 수집(best-effort). 실패/타임아웃은 경고 후 계속(빌드는 최신 가용본)."""
    ok, fail = [], []
    for name, cmd, to in COLLECTORS:
        print(f"\n$ [STAGE0 수집·{name}] {' '.join(str(c) for c in cmd)} (timeout {to}s)",
              flush=True)
        try:
            r = subprocess.run(cmd, cwd=ROOT, timeout=to)
            if r.returncode == 0:
                ok.append(name)
                print(f"  ✓ {name} 수집 완료", flush=True)
            else:
                fail.append(name)
                print(f"⚠️ STAGE0 {name} 수집 실패(exit {r.returncode}) — 최신 가용 스냅샷으로 계속",
                      file=sys.stderr, flush=True)
        except subprocess.TimeoutExpired:
            fail.append(name)
            print(f"⚠️ STAGE0 {name} 타임아웃({to}s) — 최신 가용 스냅샷으로 계속",
                  file=sys.stderr, flush=True)
        except Exception as e:  # noqa: BLE001
            fail.append(name)
            print(f"⚠️ STAGE0 {name} 오류({e}) — 계속", file=sys.stderr, flush=True)
    print(f"\nSTAGE0 수집 요약: 성공 {ok} · 실패/스킵 {fail}", flush=True)
    return ok, fail


def iso_week_monday(d: datetime.date) -> datetime.date:
    """d 가 속한 ISO 주(월~일)의 월요일 — 신라 price-patch 주간 로그 파일명."""
    return d - datetime.timedelta(days=d.weekday())


# ── 수집 신선도 가드 (CMPA-678) ───────────────────────────────────────────────
# build_compare 의 면세 스냅샷 글롭과 동일(소스: pipelines/dutyfree_compare/build_compare.py).
# 파일명 위치(접두/접미)와 무관하게 YYYY-MM-DD 토큰으로 최신일을 뽑는다.
_DF_SNAPSHOT_GLOBS = (
    os.path.join(ROOT, "assets", "lotte_dutyfree", "snapshots", "????-??-??_lotte_whisky.csv"),
    os.path.join(ROOT, "data", "shilla-dutyfree", "신라면세_위스키_????-??-??.csv"),
    os.path.join(ROOT, "assets", "ssg_dutyfree", "snapshots", "????-??-??_ssg_whisky.csv"),
)


def _date_from_path(path):
    m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(path or ""))
    return m.group(1) if m else ""


def newest_dutyfree_snapshot_date():
    """세 면세점 위스키 스냅샷 중 가장 최신 수집일(YYYY-MM-DD). 없으면 ""."""
    dates = [d for pat in _DF_SNAPSHOT_GLOBS for f in glob.glob(pat)
             if (d := _date_from_path(f))]
    return max(dates) if dates else ""


def run(label, cmd, check=True, **kw):
    print(f"\n$ [{label}] {' '.join(str(c) for c in cmd)}", flush=True)
    r = subprocess.run(cmd, **kw)
    if check and r.returncode != 0:
        raise SystemExit(f"❌ STAGE 실패: {label} (exit {r.returncode})")
    return r


# ── 발행 레포 해소 (라이브와 동기화된 클론 자동선택) ─────────────────────────────
def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args],
                          capture_output=True, text=True)


def resolve_publish_repo():
    """origin/main(라이브)과 동기화된(또는 깔끔히 fast-forward 가능한) 발행 클론을 고른다.

    후보: $CASKCODE_PUBLISH → ~/Desktop/caskcode-publish → <ROOT>/../caskcode-publish.
    각 후보를 fetch 한 뒤 (clean & ahead==0) 이면 채택(behind 면 ff). diverge/dirty 는 배제.
    """
    cands, seen = [], set()
    for p in (os.environ.get("CASKCODE_PUBLISH"),
              os.path.join(os.path.expanduser("~"), "Desktop", "caskcode-publish"),
              os.path.abspath(os.path.join(ROOT, "..", "caskcode-publish"))):
        if not p:
            continue
        rp = os.path.realpath(p)
        if rp in seen or not os.path.isdir(os.path.join(rp, ".git")):
            continue
        seen.add(rp)
        cands.append(rp)

    env = dict(os.environ, GIT_SSH_COMMAND=GIT_SSH)
    for repo in cands:
        f = subprocess.run(["git", "-C", repo, "fetch", "origin", "main", "-q"],
                           env=env, capture_output=True, text=True)
        if f.returncode != 0:
            print(f"  · {repo}: fetch 실패 — 건너뜀", flush=True)
            continue
        if _git(repo, "status", "--porcelain").stdout.strip():
            print(f"  · {repo}: 워킹트리 dirty — 건너뜀", flush=True)
            continue
        cnt = _git(repo, "rev-list", "--left-right", "--count",
                   "HEAD...origin/main").stdout.split()
        ahead, behind = (int(cnt[0]), int(cnt[1])) if len(cnt) == 2 else (1, 1)
        if ahead != 0:
            print(f"  · {repo}: 로컬 {ahead} ahead(diverge) — 건너뜀", flush=True)
            continue
        if behind:
            print(f"  · {repo}: {behind} behind → fast-forward", flush=True)
            _git(repo, "merge", "--ff-only", "origin/main")
        print(f"  ✓ 발행 레포 선택: {repo} (라이브 동기화됨)", flush=True)
        return repo
    raise SystemExit("❌ 라이브와 동기화된 caskcode-publish 클론을 찾지 못함 — 수동 점검 필요.")


def surgical_push(repo, src_files, date_tag, dry_run=False):
    """src_files(WK blog-md/_posts) 중 발행본과 달라진 것만 골라 copy→add <파일>→commit→push.

    반환: 실제로 발행(또는 dry-run 예정)된 _posts 상대경로 목록."""
    changed = []
    for src in src_files:
        if not os.path.exists(src):
            print(f"  · 소스 없음(건너뜀): {os.path.basename(src)}", flush=True)
            continue
        rel = os.path.join("_posts", os.path.basename(src))
        dst = os.path.join(repo, rel)
        if os.path.exists(dst):
            with open(src, "rb") as a, open(dst, "rb") as b:
                if a.read() == b.read():
                    print(f"  · 변경 없음(skip): {os.path.basename(src)}", flush=True)
                    continue
        shutil.copy2(src, dst)
        changed.append(rel)
        print(f"  + 발행 대기: {rel}", flush=True)

    if not changed:
        print("  변경 없음 → commit/push 생략(멱등).", flush=True)
        return []
    if dry_run:
        print(f"  [dry-run] commit/push 생략. 발행 예정 {len(changed)}개.", flush=True)
        _git(repo, "checkout", "--", *changed)  # 워킹트리 복원
        return changed

    _git(repo, "add", *changed)                 # 대상 파일만 정확히 스테이지(surgical)
    if not _git(repo, "diff", "--cached", "--name-only").stdout.strip():
        print("  스테이지 비어있음 → push 생략(멱등).", flush=True)
        return []
    msg = (f"deploy(_posts): 일간 면세·마트 파생 페이지 갱신 ({date_tag}) (CMPA-672)\n\n"
           f"run_daily_whisky_update.py 자동 발행 · surgical push(대상 글만)\n\n"
           f"Co-Authored-By: Paperclip <noreply@paperclip.ing>")
    _git(repo, "commit", "-q", "-m", msg)
    env = dict(os.environ, GIT_SSH_COMMAND=GIT_SSH)
    p = subprocess.run(["git", "-C", repo, "push", "origin", "main"],
                       env=env, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"❌ push 실패:\n{p.stderr}")
    print(f"  ✓ push 완료 ({len(changed)}개 글)", flush=True)
    return changed


def _post_url(rel_or_name):
    """_posts 파일명(YYYY-MM-DD-slug.md) → 라이브 URL (/YYYY/MM/DD/slug/)."""
    base = os.path.basename(rel_or_name)[:-3]   # drop .md
    y, m, d, *slug = base.split("-")
    return f"{LIVE_BASE}/{y}/{m}/{d}/{'-'.join(slug)}/"


def curl_verify(rels, tries=4, pause=25):
    """발행한 글의 라이브 URL 이 200 인지 확인(GitHub Pages 재빌드 대기 재시도)."""
    ok = {}
    for attempt in range(1, tries + 1):
        for f in [x for x in rels if not ok.get(x)]:
            url = _post_url(f)
            try:
                req = urllib.request.Request(
                    url, method="GET", headers={"User-Agent": "caskcode-verify"})
                with urllib.request.urlopen(req, timeout=15) as resp:
                    if resp.status == 200:
                        ok[f] = url
                        print(f"  ✓ 200 {url}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"  · ({attempt}/{tries}) 대기 {url} — {e}", flush=True)
        if all(ok.get(f) for f in rels):
            break
        if attempt < tries:
            time.sleep(pause)
    failed = [_post_url(f) for f in rels if not ok.get(f)]
    return ok, failed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None, help="기준 날짜(KST 기본)")
    ap.add_argument("--skip-collect", action="store_true",
                    help="STAGE0(데이터 수집) 생략 — 기존 스냅샷으로 빌드만")
    ap.add_argument("--skip-normalize", action="store_true", help="STAGE1(정규화) 생략")
    ap.add_argument("--no-publish", action="store_true", help="빌드만(STAGE4 발행·curl 생략)")
    ap.add_argument("--dry-run", action="store_true", help="발행 미리보기(push 없음)")
    ap.add_argument("--force", action="store_true",
                    help="수집 신선도 가드 무시(스냅샷보다 미래 날짜라도 강제 빌드)")
    args = ap.parse_args()

    date_str = args.date or kst_today().isoformat()
    print(f"==== 일간 올인원(수집+갱신+발행) 시작 (기준 {date_str}, KST) ====", flush=True)

    # STAGE 0 — 데이터 수집(Option A, 보드 확정 2026-06-29). best-effort·에러격리.
    if not args.skip_collect:
        print("\n==== STAGE0 데이터 수집(면세 3사 + 데일리샷 + 트레이더스OCR) ====", flush=True)
        stage0_collect()
    else:
        print("STAGE0 수집 생략(--skip-collect) — 기존 스냅샷으로 빌드만", flush=True)

    # 신선도 가드(CMPA-678): 요청일이 최신 면세 스냅샷보다 미래면 오늘 수집이 아직
    # 안 들어온 것 — 06-28 데이터로 06-29 페이지를 찍어 미래날짜 중복글을 발행하지
    # 않도록 멱등 no-op 으로 종료한다. 수집 루틴(06:00~08:40 KST) 이후 재실행하면 통과.
    newest = newest_dutyfree_snapshot_date()
    if newest and date_str > newest and not args.force:
        print(f"⏭️  no-op: 요청일 {date_str} > 최신 면세 스냅샷 {newest} — "
              f"오늘 수집 미완료(06:00~08:40 KST 이후 실행). 강제하려면 --force.",
              flush=True)
        return 0

    # STAGE 1 — 정규화(국내최저 floor 갱신). build_compare 가 normalized_prices.csv 를 읽으므로 선행.
    if not args.skip_normalize:
        run("STAGE1 normalize", [PY, NORMALIZE], cwd=ROOT)
    else:
        print("STAGE1 정규화 생략(--skip-normalize)", flush=True)

    # STAGE 2 — 면세 비교 + 마트(면세보다 싼) 페이지 빌드(동적 스냅샷 날짜·staleness 가드).
    run("STAGE2 build_compare", [PY, BUILD_COMPARE, "--blog", "--date", date_str], cwd=ROOT)
    compare_md = os.path.join(POSTS_DIR, f"{date_str}-dutyfree-whisky-compare.md")
    mart_md = os.path.join(POSTS_DIR, f"{date_str}-mart-cheaper-whisky.md")

    # STAGE 3 — 신라 price-patch 이번주 주간 로그 재렌더(멱등, best-effort).
    week_monday = iso_week_monday(datetime.date.fromisoformat(date_str))
    patch_md = os.path.join(POSTS_DIR, f"{week_monday.isoformat()}-price-patch.md")
    try:
        run("STAGE3 price-patch rebuild", [PY, BUILD_BLOG, "--latest-only"], cwd=ROOT)
    except SystemExit as e:
        print(f"⚠️ STAGE3 best-effort 실패(무시하고 계속 — 08:00 루틴이 이미 발행): {e}",
              file=sys.stderr, flush=True)

    # STAGE 3.5 — 업데이트 로그(릴리스 노트) 원장 upsert + 단일 롤링 글 렌더(CMPA-687).
    #   detect(가격변동) 산출 뒤에 두어 그날 요약을 원장에 누적한다. best-effort·에러격리
    #   (실패해도 STAGE2 핵심 페이지 발행을 막지 않는다). build_changelog 가 페이지 링크를
    #   relative_url 로 직접 출력하므로 build_blog_md 의 발행 게이트와 byte-stable.
    try:
        run("STAGE3.5 build_changelog", [PY, BUILD_CHANGELOG, "--date", date_str], cwd=ROOT)
    except SystemExit as e:
        print(f"⚠️ STAGE3.5 best-effort 실패(무시하고 계속): {e}", file=sys.stderr, flush=True)
    # 파일명 prefix = 원장 최초일(고정)이라 글롭으로 찾는다(today 날짜가 아님).
    updates_mds = sorted(glob.glob(os.path.join(POSTS_DIR, "*-whisky-updates.md")))

    targets = [compare_md, mart_md, patch_md] + updates_mds

    # STAGE 4 — surgical push + curl 검증.
    if args.no_publish:
        print("\nSTAGE4 발행 생략(--no-publish). 빌드 산출물:", flush=True)
        for t in targets:
            print(f"  - {os.path.basename(t)} ({'있음' if os.path.exists(t) else '없음'})",
                  flush=True)
        return 0

    print("\n==== STAGE4 발행(surgical push) ====", flush=True)
    repo = resolve_publish_repo()
    pushed = surgical_push(repo, targets, date_str, dry_run=args.dry_run)
    if args.dry_run:
        print(f"\n[dry-run] 발행 예정 {len(pushed)}개 — 라이브 미변경.", flush=True)
        return 0
    if not pushed:
        print("\n변경 없음 — 라이브 이미 최신(멱등).", flush=True)
        return 0

    print("\n==== curl 라이브 검증 ====", flush=True)
    ok, failed = curl_verify(pushed)
    if failed:
        print(f"⚠️ 라이브 검증 미완(GitHub Pages 지연 가능): {failed}",
              file=sys.stderr, flush=True)
        return 5
    print(f"\n✅ 완료 — {len(ok)}개 페이지 라이브 갱신·검증.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
