#!/usr/bin/env python3
"""신라면세 가격변동 감지 — 통합 실행 (CMPA-168, 루틴 진입점).

흐름: ① 오늘(KST) 신라 위스키 크롤 → 새 스냅샷 적재
      ② detect_price_changes.py 로 직전 스냅샷과 달러기준 비교 → md 리포트
      ③ 리포트를 이메일로 전송 (기본 수신자 = PAPERCLIP_EMAIL_RECIPIENTS).

데이터 3원칙 준수: 직전 정본 스냅샷을 가져와 비교(①), 날짜별 스냅샷은
덮어쓰지 않고 누적(②), 리포트 상단에 양쪽 수집일 노출(③).

루틴(매일 08:00 / 18:00 KST)에서 이 스크립트를 호출한다.

CMPA-250: --publish-blog 를 주면 ④ 변동 감지 시 블로그 패치 글(_posts/<날짜>-price-patch.md)
까지 생성하고 발행 스코프(apps/+_posts/)를 caskcode-publish 로 동기화한다(라이브). 변동 0건이면
글 생성·발행을 건너뛴다(멱등, 데이터 3원칙). --dry-run-publish 면 라이브 push 없이 미리보기만.

CMPA-334(보드 승인): --publish-blog 이면 **매주 일요일** 주간 리포트(지난주 환율·할인 종목 +
현재 추천 위스키, 데일리샷 링크 포함)도 build_weekly_digest 로 생성·발행한다(가격변동 0건이어도).
--weekly 로 요일 무관 강제, --no-weekly 로 일요일에도 생략. 가격변동은 기존대로 매일.

사용법:
  python3 scripts/run_shilla_price_change.py
  python3 scripts/run_shilla_price_change.py --skip-crawl   # 비교+메일만
  python3 scripts/run_shilla_price_change.py --no-email     # 메일 생략
  python3 scripts/run_shilla_price_change.py --to a@b.com,c@d.com
  # 단일 명령: 크롤→detect→(변동 있으면) 블로그 글 생성+발행
  python3 scripts/run_shilla_price_change.py --publish-blog --no-email
  # 검증(라이브 push 없이): 발행 스코프 미리보기
  python3 scripts/run_shilla_price_change.py --skip-crawl --no-email \
      --publish-blog --dry-run-publish
"""
import argparse
import datetime
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, ROOT)

SHILLA_DIR = os.path.join(ROOT, "pipelines", "shilla_dutyfree")
CRAWLER = os.path.join(SHILLA_DIR, "crawl_shilla_whisky.py")
DETECTOR = os.path.join(SHILLA_DIR, "detect_price_changes.py")
BUILD_BLOG = os.path.join(SHILLA_DIR, "build_blog_md.py")
WEEKLY = os.path.join(SHILLA_DIR, "build_weekly_digest.py")
FIND_CHEAPER = os.path.join(SHILLA_DIR, "find_cheaper_than_domestic.py")
DATA_DIR = os.path.join(ROOT, "data", "shilla-dutyfree")
REPORT_DIR = os.path.join(ROOT, "reports", "shilla-dutyfree")


def kst_today():
    return (datetime.datetime.now(datetime.timezone.utc)
            + datetime.timedelta(hours=9)).strftime("%Y-%m-%d")


def run(cmd):
    print(f"$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=True)


def discover_snapshots():
    import re
    rx = re.compile(r"^신라면세_위스키_(\d{4}-\d{2}-\d{2})\.csv$")
    return sorted(rx.match(fn).group(1) for fn in os.listdir(DATA_DIR)
                  if rx.match(fn))


def _snapshot_rows(date):
    """해당 날짜 신라 위스키 스냅샷의 데이터 행수(헤더 제외)."""
    fp = os.path.join(DATA_DIR, f"신라면세_위스키_{date}.csv")
    with open(fp, encoding="utf-8") as f:
        return max(0, sum(1 for _ in f) - 1)


def pick_prev(snaps, latest_date, min_ratio=0.90):
    """가장 최근의 '완전한' 직전 스냅샷을 고른다 (부분 크롤 베이스라인 방지).

    직전 스냅샷이 부분 크롤(행수 < 최신 × min_ratio)이면, 그 누락분이 다음 날
    재등장하며 허위 '신규' 로 잡혀 블로그·메일을 오염시킨다(CMPA-156: 부분 수집을
    완전 스냅샷처럼 베이스라인으로 쓰지 말 것). 그런 직전은 건너뛰고 더 과거의
    완전 스냅샷까지 walk-back 한다. 후보가 전부 부분이면 그냥 바로 직전을 쓴다(최선).

    배경(CMPA-302): 2026-06-11 크롤이 561/649건(부분)이라 06-12 비교에서 '신규 88건'
    이 허위로 잡혔다. min_ratio=0.90 → 561/649=0.86 가 걸러진다(카탈로그는 ~649로 안정)."""
    latest_rows = _snapshot_rows(latest_date)
    for d in reversed(snaps[:-1]):
        rows = _snapshot_rows(d)
        if latest_rows == 0 or rows >= latest_rows * min_ratio:
            return d
        print(f"⚠️ 직전 스냅샷 {d} 부분 크롤 추정({rows}/{latest_rows}행, "
              f"<{min_ratio:.0%}) → 베이스라인 제외하고 더 과거로", flush=True)
    return snaps[-2]


def report_is_noop(report_path):
    """리포트(가격변동_*.md)가 변동 0건인지 — 빌더와 같은 판정(단일 소스).

    detect 는 변동이 없어도 리포트를 항상 쓰므로, 블로그 글/발행은 여기서 멱등
    게이트한다(CMPA-156/250). build_blog 의 parse/판정을 재사용한다."""
    sys.path.insert(0, SHILLA_DIR)   # build_blog 가 같은 디렉터리 brand 를 import.
    import build_blog as bb
    return bb.is_noop_patch(bb.parse_patch_md(report_path))


def publish_blog(prev_date, latest_date, report_path, dry_run=False):
    """가격변동 → 블로그 글 생성 + 발행. 변동 0건이면 no-op(멱등).

    ① 멱등 게이트: 변동 0건이면 글 생성·발행 안 함(no-op 로그).
    ② build_blog_md 로 blog-md/_posts/<latest>-price-patch.md (재)생성.
    ③ refresh_whisky_publish.publish_live 로 발행 스코프(apps/+_posts/) 동기화.
       dry_run=True 면 라이브 push 없이 발행 스코프 미리보기만(CMPA-250 검증용).
    반환: True=발행(또는 dry-run) 진행, False=no-op 으로 생략."""
    if report_is_noop(report_path):
        print(f"변동 0건 → 블로그 글 생성·발행 생략(no-op, 멱등). "
              f"{prev_date}→{latest_date}", flush=True)
        return False

    # ② 블로그 (재)빌드 — 루틴 자동실행은 최신 패치가 속한 '그 주' 글만 재렌더(CMPA-264).
    #    CMPA-644: 일일 글이 아니라 주간 로그(_posts/<주시작(월)>-price-patch.md)에 오늘치를
    #    시간역순으로 append. 과거 주·이번 달 base 글은 보존(전체 재생성 금지).
    print(f"변동 감지 → 주간 로그에 {latest_date} 추가(현재 주 글 재렌더)", flush=True)
    run([sys.executable, BUILD_BLOG, "--latest-only"])

    # ③ 발행 동기화(apps/ + _posts/) — 라이브 push 또는 dry-run 미리보기.
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import refresh_whisky_publish as rwp
    ok = rwp.publish_live(latest_date, dry_run=dry_run)
    print(f"발행 {'미리보기(dry-run)' if dry_run else '라이브 push'}: "
          f"{'OK' if ok else 'FAIL/스킵'}", flush=True)
    return True


def is_sunday(date_str):
    """KST 날짜 문자열이 일요일이면 True (weekday 6=일)."""
    try:
        return datetime.date.fromisoformat(date_str).weekday() == 6
    except (ValueError, TypeError):
        return False


def refresh_floor_report(date):
    """발행일(오늘) floor 리포트(면세_국내최저대비_저렴_<date>)를 데일리샷 라이브로 생성한다.

    CMPA-338(기회 회고 재설계): 이 리포트는 더 이상 주간 표를 '덮어써서 갭을 숨기는' 용도가
    아니라, 주간 회고의 **'이번주 스냅샷'** 한 축이다. build_weekly_digest 의 retro_section 이
    지난주 보존본(면세_..._<지난주date>)과 이 발행일본, 그리고 enrich_dailyshot 라이브 floor 를
    **대조**해 🔻사라진/🆕새/✅유지 기회로 분류한다. 지난주 보존본은 덮어쓰지 않으므로 비교
    기준선이 유지된다.

    네트워크(데일리샷 API) 실패는 비치명으로 흡수한다 — 재생성이 실패해도 가장 최근 floor
    리포트로 다이제스트는 발행되며, 이때도 정직한 라벨('○○ 기준 스냅샷')이 stale 임을 드러낸다."""
    if not os.path.exists(os.path.join(DATA_DIR, f"신라면세_위스키_{date}.csv")):
        print(f"⚠️ {date} 신라 스냅샷 없음 → floor 리포트 재생성 생략(기존 최신본 사용)", flush=True)
        return
    print(f"🔄 floor 리포트 재생성(데일리샷 라이브): {date}", flush=True)
    try:
        subprocess.run([sys.executable, FIND_CHEAPER, "--date", date],
                       check=True, cwd=ROOT)
    except subprocess.CalledProcessError as e:
        print(f"⚠️ floor 리포트 재생성 실패({e}) → 기존 최신 floor 리포트로 진행", flush=True)


def publish_weekly(date, dry_run=False):
    """주간 리포트(지난주 환율·할인 종목 + 현재 추천) 생성 + 블로그 발행 (CMPA-334 보드 승인).

    매주 일요일에 일일 가격변동과 별개로 실행한다(가격변동 0건이어도 발행). build_weekly_digest
    가 reports + blog-md/_posts/<date>-weekly-digest.md 를 만들고, publish_live 가 발행 스코프를
    동기화한다(데일리샷 링크 포함). CMPA-339: 발행 직전 floor 리포트를 당일 라이브로 재생성."""
    print(f"📅 일요일 주간 리포트 생성·발행: {date}", flush=True)
    refresh_floor_report(date)
    run([sys.executable, WEEKLY, "--date", date, "--publish-blog"])
    sys.path.insert(0, os.path.join(ROOT, "scripts"))
    import refresh_whisky_publish as rwp
    ok = rwp.publish_live(date, dry_run=dry_run)
    print(f"주간 발행 {'미리보기(dry-run)' if dry_run else '라이브 push'}: "
          f"{'OK' if ok else 'FAIL/스킵'}", flush=True)
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=kst_today(), help="크롤 날짜 (KST 기본)")
    ap.add_argument("--skip-crawl", action="store_true", help="크롤 생략")
    ap.add_argument("--no-email", action="store_true", help="이메일 생략")
    ap.add_argument("--to", default="", help="수신자(쉼표). 미지정 시 env")
    ap.add_argument("--publish-blog", action="store_true",
                    help="변동 감지 시 블로그 패치 글 생성 후 발행(apps/+_posts/ 동기화). "
                         "변동 0건이면 글 생성·발행 생략(멱등).")
    ap.add_argument("--dry-run-publish", action="store_true",
                    help="--publish-blog 와 함께: 발행 스코프 미리보기만(라이브 push 없음).")
    ap.add_argument("--weekly", action="store_true",
                    help="요일과 무관하게 주간 리포트도 생성·발행(강제). 기본은 일요일 자동.")
    ap.add_argument("--no-weekly", action="store_true",
                    help="일요일이라도 주간 리포트 생성·발행 생략.")
    args = ap.parse_args()

    # ① 크롤 (실패 시 명확히 종료)
    if not args.skip_crawl:
        run([sys.executable, CRAWLER, "--date", args.date])
    else:
        print("크롤 생략(--skip-crawl)")

    snaps = discover_snapshots()
    if len(snaps) < 2:
        print(f"비교할 스냅샷 부족(발견 {len(snaps)}개). 최소 2개 필요.", file=sys.stderr)
        return 2
    latest_date = snaps[-1]
    prev_date = pick_prev(snaps, latest_date)

    # ② 비교 리포트 생성
    run([sys.executable, DETECTOR, "--latest", latest_date, "--prev", prev_date])
    report = os.path.join(REPORT_DIR, f"가격변동_{prev_date}_to_{latest_date}.md")
    if not os.path.exists(report):
        print(f"리포트가 생성되지 않음: {report}", file=sys.stderr)
        return 3

    # ③ 블로그 글 생성 + 발행 (변동 있으면) — CMPA-250.
    if args.publish_blog:
        publish_blog(prev_date, latest_date, report,
                     dry_run=args.dry_run_publish)

    # ③.5 주간 리포트 — 매주 일요일(또는 --weekly) 별도 생성·발행 (CMPA-334 보드 승인).
    #     일일 가격변동 0건이어도 발행한다(지난주 분석 + 현재 추천).
    if args.publish_blog and (args.weekly
                              or (is_sunday(latest_date) and not args.no_weekly)):
        publish_weekly(latest_date, dry_run=args.dry_run_publish)

    # ③.6 위스키 적금 PWA(/frugal/) + floor 일/주 갱신 발행 — CMPA-351 T3.
    #      apps/frugal/ 은 발행 SYNC 스코프 밖(CMPA-284)이라 surgical push.
    #      floor 는 build_whisky_floor_json.py 로 발행 레포에 직접 재생성(결정론, 면세/dirty 제외).
    #      비치명적: 실패해도 블로그/이메일 발행을 막지 않는다(경고만).
    if args.publish_blog:
        frugal_sh = os.path.join(os.path.dirname(os.path.abspath(__file__)), "publish_frugal.sh")
        frugal_cmd = ["bash", frugal_sh] + (["--dry-run"] if args.dry_run_publish else [])
        try:
            subprocess.run(frugal_cmd, check=False)
        except Exception as e:  # noqa: BLE001
            print(f"  ! frugal 발행 경고(무시하고 계속): {e}", file=sys.stderr)

    # ④ 이메일 전송
    if args.no_email:
        print("이메일 생략(--no-email). 리포트:", report)
        return 0

    from pipelines.common.email_report import send_report
    with open(report, encoding="utf-8") as f:
        body = f.read()
    to_addrs = [a.strip() for a in args.to.split(",") if a.strip()] or None
    subject = f"[CaskCode] 신라면세 위스키 가격변동 {prev_date}→{latest_date}"
    try:
        sent = send_report(subject, body, to_addrs=to_addrs, attach_path=report)
        print(f"이메일 전송 완료 → {', '.join(sent)}")
    except Exception as e:
        print(f"이메일 전송 실패: {e}", file=sys.stderr)
        return 4
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
