#!/usr/bin/env python3
"""Build the deploy/ folder from canonical report HTML.

CMPA-106: 보드가 "deploy 폴더째로 배포"하기 위한 정적 산출물 스테이징.
- reports/ 하위의 *최신·정본* HTML 만 deploy/ 에 카테고리별로 복사한다.
- 제외: _runs/ (날짜 스냅샷 = 중간산출물), _demo/ (데모).
- whisky-price 는 공개 안전본인 *배포본* 최신본만 포함(내부 데일리샷 컬럼 리포트 제외).
- deploy/ 는 매번 통째로 재생성(결정론). index.html 자동 생성.

⚠️ 실제 외부 배포(공개)는 부모 가드레일 게이트(c7405e7d) CEO 승인 후에만.
   이 스크립트는 로컬 스테이징만 한다 — 퍼블리시하지 않는다.
"""
from __future__ import annotations
import html
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
REPORTS = ROOT / "reports"
DEPLOY = ROOT / "deploy"

KST = timezone(timedelta(hours=9))


def today_yymmdd() -> str:
    """오늘(한국시간) YYMMDD — 보드 요청 포맷(예: 260606). DEPLOY_DATE 로 오버라이드 가능(재현용)."""
    override = os.environ.get("DEPLOY_DATE")
    if override and re.fullmatch(r"\d{6}", override):
        return override
    return datetime.now(KST).strftime("%y%m%d")


def fmt_date(yymmdd: str) -> str:
    """260606 → 2026-06-06 (사람이 읽기 좋게)."""
    return f"20{yymmdd[:2]}-{yymmdd[2:4]}-{yymmdd[4:6]}"


_DATE_IN_NAME = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


def edition_date(src: Path, fallback: str) -> str:
    """에디션 스냅샷 날짜 = '리포트 자체의 날짜'(소스 파일명에 박힌 YYYY-MM-DD) → YYMMDD.

    배포한 날(wall-clock)이 아니라 *리포트 내용의 날짜*로 폴더를 만든다(CMPA-33 보드 피드백):
    같은 5월 리포트를 6월에 배포해도 폴더는 260531 — 안의 '리포트 작성일'과 일치하고,
    매일 배포해도 동일 리포트가 중복 폴더로 쌓이지 않는다(idempotent). 날짜가 없으면 fallback.
    """
    m = _DATE_IN_NAME.search(src.name)
    return f"{m.group(1)[2:]}{m.group(2)}{m.group(3)}" if m else fallback

# 배포 전에 실행할 '생성형 리포트' 생성기 — reports/ 산출물을 최신화한다.
# 루틴이 build_deploy.py 만 돌려도 리포트가 생성기로부터 재생성되어 결정론적으로 배포된다.
# shilla-dutyfree: 가격은 refresh_report_prices.py 가 만든 리포트_가격_<date>.json(라이브)에서
#   로드한다(CMPA-141). build_report_html 은 렌더만 하므로 빠르고 결정론적이다.
#   JSON 갱신(라이브 호출)은 별도 주간 루틴(refresh_report_prices)에서 수행 — deploy 와 분리.
#   SHILLA_DATE 미설정 → 생성기가 최신 리포트_가격_<date>.json 을 자동 선택(주간 갱신 자동 반영).
# blog (CMPA-174/178): 'Code, Cask & Cabin' 블로그는 보드 피벗으로 **이 Netlify 파이프라인에서 제외**.
#   보드 결정(2026-06-07): HTML/Netlify 대신 **md + GitHub Pages(블로그 전용 별도 리포)**.
#   → 정본 산출물은 deploy/blog-md/ (self-contained Jekyll, 생성기 build_blog_md.py).
#   build_deploy(=Netlify 본 사이트)는 blog 섹션을 더 이상 빌드/보존하지 않는다.
#   (HTML 생성기 build_blog.py 는 dormant — 더는 호출되지 않음.)
GENERATORS = [
    {"script": ROOT / "pipelines" / "shilla_dutyfree" / "build_report_html.py"},
]


def run_generators() -> None:
    for g in GENERATORS:
        name = Path(g["script"]).name
        if not Path(g["script"]).exists():
            print(f"  ⚠️ generator 없음(건너뜀): {name}")
            continue
        try:
            env = {**os.environ, **g.get("env", {})}
            subprocess.run([sys.executable, str(g["script"])], check=True,
                           env=env, capture_output=True, timeout=180)
            print(f"  ✓ generator 실행: {name}")
        except Exception as e:  # 생성기 실패가 배포 전체를 막지 않게
            print(f"  ⚠️ generator 실패(무시, 기존 산출물 사용): {name}: {e}")

# 카테고리별 표시 제목
CATEGORY_TITLES = {
    "whisky-price": "위스키 가격 리포트",
    # CMPA-206: 식당 맵 2종(할랄·반려동물 동반)은 프로젝트에서 제외(→ _archive/).
    "shilla-dutyfree": "🥃 면세 위스키, 진짜 싼 것만 골랐다 (신라면세)",
}

# ── deploy 에서 완전히 제외하는 카테고리(reports/ 에는 남겨두되 공개 배포만 뺀다) ──
# CMPA-203 보드 지시 2026-06-07: "콜키지 지도도 deploy에서 아얘 빼자."
#   (CMPA-205에서 '콜키지 포함·리스크수용'으로 뒀던 결정을 보드가 번복.)
#   corkage-free 산출물(reports/corkage-free/*)·파이프라인은 내부용으로 보존하되,
#   deploy/ 에는 복사하지 않는다 → 다음 빌드의 rmtree 로 deploy/corkage-free 정리됨.
EXCLUDE_CATEGORIES = {"corkage-free"}

# ── 에디션(EDITIONS): '월간 글'처럼 매 배포마다 새 호(號)가 나오는 카테고리 ──
# CMPA-33 (보드 승인 confirmation:CMPA-33:archive-design:1, 하이브리드안):
#   위스키가격·면세 리포트는 매월 내용이 바뀌는 '에디션' → 지우지 않고 날짜별로 쌓는다.
#   - deploy/<cat>/<YYMMDD>/index.html  = 그 날짜의 스냅샷(영구 아카이브)
#   - deploy/<cat>/index.html           = 최신호 포인터(항상 같은 링크 = 최신)
#   루트 index.html 이 최신호 + '지난 에디션' 아카이브 링크를 모아 보여준다.
#   날짜 목록은 폴더 스캔으로 도출(별도 상태파일 없음·결정론). 명시적 index.html 링크라
#   file:// 로컬·웹서버 양쪽에서 동일하게 열린다(디렉터리 리스팅 '파일 탐색 화면' 방지).
EDITIONS = {"shilla-dutyfree", "whisky-price"}

# 리빙 레퍼런스(역→도보권 맵): 무겁고(임베드 지도) 자주 안 바뀌어 최신 1벌만 유지한다.
# 역/지역별로 여러 HTML 이 있어 원본 파일명을 그대로 쓴다. (corkage-free 등)

# reports/ 에서 생성되지 *않는* 정적 패스스루 폴더 — 재생성 시 보존한다.
# (CMPA-122: 손님용 위스키 테이스팅 메뉴 — PDF는 사용자가 직접 업로드,
#  index.html/qr 은 scripts/build_menu_page.py 가 생성. reports/ 에 원본이 없으므로
#  통째 rmtree 하면 영구 유실된다 → 보존 + index 링크.)
# (CMPA-127: 식당 Poll 페이지 — scripts/build_poll.py 가 정본 카드+StrawPoll 임베드
#  단일 페이지를 deploy/poll/index.html 로 생성. reports/ 에 원본이 없는 admin 생성물이라
#  menu 와 동일하게 STATIC 패스스루로 보존한다.)
# (CMPA-174/178: 블로그는 md+GitHub Pages 별도 리포(deploy/blog-md/)로 이전 — 보드 피벗.
#  이 Netlify 파이프라인에서 blog 섹션 제외. deploy/blog/(구 HTML)는 보존 대상 아님 →
#  STATIC 에서 빠졌으므로 다음 빌드의 rmtree 로 정리된다.)
# CMPA-208: menu·poll 은 deploy/ 에 그대로 보존(아래 build() 의 STATIC 가드로
#   rmtree 제외)하되 index 목록에는 더 이상 노출하지 않는다 — 블로그 '앱' 섹션
#   index 는 가치 리포트(위스키 가격·면세)만 보여준다(콜키지는 CMPA-203 보드 번복으로
#   별도 제외). 메뉴 QR(CMPA-122)이 실물 인쇄로 deploy/menu/ 라이브 URL 을 직접
#   가리키므로 폴더·URL 은 유지한다. → 표시 제목(STATIC_TITLES)은 불필요해 제거,
#   폴더 보존만 남긴다.
STATIC_DIRS = {"menu", "poll"}

DATE_RE = re.compile(r"_\d{4}-\d{2}-\d{2}")


def latest_distribution_whisky(d: Path) -> list[Path]:
    """whisky-price: 최신 배포본 1개만(공개 안전본)."""
    dists = sorted(p for p in d.glob("*배포본_*.html"))
    return [dists[-1]] if dists else []


def canonical_html(d: Path) -> list[Path]:
    """카테고리 폴더에서 정본(날짜 없는) HTML. 없으면 최신 날짜본."""
    files = [p for p in d.glob("*.html") if p.is_file()]
    canon = [p for p in files if not DATE_RE.search(p.stem)]
    if canon:
        return sorted(canon)
    # 날짜본만 있으면 가장 최근 것
    dated = sorted(files)
    return [dated[-1]] if dated else []


def collect() -> dict[str, list[Path]]:
    """카테고리 -> 배포할 HTML 파일 목록."""
    out: dict[str, list[Path]] = {}
    for cat in sorted(p.name for p in REPORTS.iterdir() if p.is_dir()):
        if cat in EXCLUDE_CATEGORIES:  # CMPA-203: 콜키지 등 deploy 제외 카테고리
            continue
        d = REPORTS / cat
        if cat == "whisky-price":
            files = latest_distribution_whisky(d)
        else:
            files = canonical_html(d)
        if files:
            out[cat] = files
    return out


def build() -> dict[str, list[Path]]:
    # 생성형 리포트(shilla 등)를 먼저 재생성해 reports/ 산출물을 최신화한다.
    run_generators()
    today = today_yymmdd()
    # 정리 정책(하이브리드):
    #  - STATIC_DIRS(menu/poll): 보존(원본이 reports/ 에 없음).
    #  - EDITIONS: 보존 — 과거 날짜 스냅샷을 지우면 안 된다. 안에서 오늘치만 갱신한다.
    #  - 그 외(리빙 맵): 통째 제거 후 재생성 → 최신 1벌·결정론.
    #  - 루트 index.html: 항상 재생성.
    if DEPLOY.exists():
        for entry in DEPLOY.iterdir():
            if entry.name in STATIC_DIRS or entry.name in EDITIONS:
                continue
            if entry.is_dir():
                shutil.rmtree(entry)
            else:
                entry.unlink()
    DEPLOY.mkdir(parents=True, exist_ok=True)

    plan = collect()
    copied: dict[str, list[Path]] = {}
    for cat, files in plan.items():
        if cat in EDITIONS:
            # 에디션: 최신 1개 파일을 날짜 스냅샷 + 최신 포인터로 배포(누적).
            # 폴더 날짜 = 리포트 자체의 날짜(소스 파일명) — 배포한 날이 아니라 내용의 날짜.
            src = files[-1]
            date_dir = DEPLOY / cat / edition_date(src, today)
            date_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, date_dir / "index.html")  # 영구 아카이브
            latest = DEPLOY / cat / "index.html"
            shutil.copy2(src, latest)                    # 최신호 포인터
            copied[cat] = [latest]
        else:
            dest_dir = DEPLOY / cat
            dest_dir.mkdir(parents=True, exist_ok=True)
            copied[cat] = []
            for src in files:
                dest = dest_dir / src.name
                shutil.copy2(src, dest)
                copied[cat].append(dest)
    write_index(copied)
    return copied


def edition_dates(cat: str) -> list[str]:
    """deploy/<cat>/ 아래 YYMMDD 스냅샷 폴더 목록(최신순)."""
    d = DEPLOY / cat
    if not d.is_dir():
        return []
    dates = [p.name for p in d.iterdir() if p.is_dir() and re.fullmatch(r"\d{6}", p.name)]
    return sorted(dates, reverse=True)


def write_index(copied: dict[str, list[Path]]) -> None:
    rows = []
    # CMPA-208: index 에는 가치 카테고리(위스키 가격·면세 리포트)만 노출한다.
    #   - 콜키지 지도는 보드 번복(CMPA-203, 보드 2026-06-07 "deploy에서 아얘 빼자")으로
    #     EXCLUDE_CATEGORIES 에서 이미 collect() 제외 — 여기 목록에도 안 잡힌다(재추가 금지).
    #   - menu·poll STATIC 패스스루 폴더는 deploy/ 에 그대로 보존하되(build() 가드)
    #     index 목록에는 더 이상 싣지 않는다 — 메뉴 QR(CMPA-122) 실물 인쇄 URL 은
    #     유지되지만 블로그 '앱' 인덱스에서만 뺀다(보드 CMPA-205 → 205 통합 확정).
    # 에디션(누적되는 글)을 먼저, 리빙 맵을 뒤에 — 시의성 높은 콘텐츠 우선.
    ordered = [c for c in copied if c in EDITIONS] + [c for c in copied if c not in EDITIONS]
    for cat in ordered:
        files = copied[cat]
        title = CATEGORY_TITLES.get(cat, cat)
        rows.append(f"<h2>{html.escape(title)}</h2>\n<ul>")
        if cat in EDITIONS:
            # 최신호 포인터(명시적 index.html → file:// 안전) + 지난 에디션 아카이브.
            rows.append(f'<li><a href="{cat}/index.html">{html.escape(title)} '
                        f'<span class="latest">최신</span></a></li>')
            dates = edition_dates(cat)
            if dates:
                links = " · ".join(
                    f'<a href="{cat}/{dt}/index.html">{fmt_date(dt)}</a>' for dt in dates)
                rows.append(f'<li class="muted">📚 지난 에디션: {links}</li>')
        else:
            for f in files:
                rel = f.relative_to(DEPLOY).as_posix()
                rows.append(f'<li><a href="{rel}">{html.escape(f.stem)}</a></li>')
        rows.append("</ul>")
    body = "\n".join(rows)
    doc = f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex,nofollow">
<title>WK 앱 — 위스키 가성비 리포트</title>
<style>
body{{margin:0;background:#0f1115;color:#e8eaed;
font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Apple SD Gothic Neo","Malgun Gothic",sans-serif;
line-height:1.6;font-size:16px}}
.container{{max-width:780px;margin:0 auto;padding:40px 22px 80px}}
h1{{font-size:1.8rem;border-bottom:2px solid #e0a84e;padding-bottom:.3em}}
h2{{font-size:1.2rem;color:#e0a84e;margin:1.6em 0 .4em}}
a{{color:#7fd1b9;text-decoration:none}}
a:hover{{text-decoration:underline}}
ul{{margin:.3em 0 1em;padding-left:1.2em}}
li{{margin:.25em 0}}
.muted{{color:#9aa0aa;font-size:.9rem}}
.latest{{background:#e0a84e;color:#0f1115;font-size:.7rem;font-weight:700;
padding:1px 7px;border-radius:10px;margin-left:6px;vertical-align:middle}}
</style>
</head>
<body><div class="container">
<h1>🥃 WK 앱</h1>
<p class="muted">WK 위스키 가성비 리포트 모음 — 카테고리별 최신 산출물.</p>
{body}
</div></body>
</html>
"""
    (DEPLOY / "index.html").write_text(doc, encoding="utf-8")


def archive_deploy_run() -> Path | None:
    """CMPA-151: 방금 빌드한 deploy/ 트리 사본을 runs/<run_date>/deploy/ 로 모은다.

    deploy 는 cross-asset(여러 리포트 카테고리 묶음)이라 자산별 폴더가 아니라
    runs/<run_date>/deploy/ 한곳에 통째로 둔다. 날짜는 run_dates.run_date() 단일 출처
    (통합 파이프라인 stage 5 와 동일 규약). 정본 deploy/ 는 그대로 두고 추가 복사만 한다.
    실패해도 배포 빌드 자체를 깨지 않도록 경고만 한다.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from pipelines.common import run_dates  # 날짜 단일 출처
        run_date = run_dates.run_date()
        dst = ROOT / "runs" / run_date / "deploy"
        if dst.exists():
            shutil.rmtree(dst)  # 같은 run_date 재실행 = 날짜 단위 멱등
        shutil.copytree(DEPLOY, dst)
        n = sum(1 for _ in dst.rglob("*") if _.is_file())
        print(f"[run-archive] runs/{run_date}/deploy/ — {n} files (CMPA-151)")
        return dst
    except Exception as e:  # 아카이브 실패가 배포 빌드를 막지 않게
        print(f"[run-archive] deploy 아카이브 건너뜀(경고): {e}")
        return None


def dry_run_plan() -> None:
    """무네트워크·비변경 검증: 배포 플랜만 출력하고 deploy/ 를 건드리지 않는다.
    (블로그는 deploy/blog-md/ 별도 GitHub Pages 리포로 이전 — 이 파이프라인 밖.)"""
    print("[dry-run] 배포 플랜 (deploy/ 무변경)")
    plan = collect()
    for cat in sorted(plan):
        kind = "EDITION(누적)" if cat in EDITIONS else "copy(최신)"
        print(f"  - {cat}: {len(plan[cat])} HTML · {kind}")
    for name in sorted(STATIC_DIRS):
        present = (DEPLOY / name / "index.html").is_file()
        print(f"  - {name}: STATIC 패스스루 보존 ({'있음' if present else '미생성'})")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="deploy/ 정적 산출물 스테이징 빌더")
    ap.add_argument("--dry-run", action="store_true",
                    help="무네트워크·비변경 검증(배포 플랜 + 블로그 결정론·회귀0)")
    cli = ap.parse_args()
    if cli.dry_run:
        dry_run_plan()
        sys.exit(0)
    result = build()
    total = sum(len(v) for v in result.values())
    print(f"deploy/ rebuilt — {total} HTML across {len(result)} categories + index.html")
    for cat, files in result.items():
        print(f"  [{cat}] {len(files)}")
        for f in files:
            print(f"    - {f.relative_to(ROOT)}")
    archive_deploy_run()  # CMPA-151: runs/<run_date>/deploy/ 누적
