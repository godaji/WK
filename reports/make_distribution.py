#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_distribution.py — 공개 배포본(공개용) 생성기 (CMPA-33 배포 / CMPA-45 날짜 명명).

내부 최종 리포트(reports/whisky-price/{month}_위스키가격리포트_{run-date}.md)를 입력으로 받아
공개 배포본을 만든다:
  1) [1] 표에서 **데일리샷대비(₩)** 컬럼 제거 (G1 데일리샷 상업 이용 게이트 — 공개판은 제외)
  2) 본문에서 데일리샷 관련 문구 정리(컬럼 설명/각주)
  3) 상단에 공개용 면책·출처 블록 prepend

산출(CMPA-45 — 최종 산출물은 정본 자체가 날짜 포함):
  reports/whisky-price/{month}_위스키가격리포트_배포본_{run-date}.md     (정본, 덮어쓰기 금지)
  reports/whisky-price/{month}_위스키가격리포트_배포본_{run-date}.html    (md_to_html, 자동 날짜)
  reports/whisky-price/{month}_위스키가격리포트_배포본_latest.{md,html}   (--latest 줄 때만, 기본 끔)

dated 입력 → dated 출력. 같은 날 재실행은 멱등, 다른 날 실행은 새 파일로 누적.

**왜 배포본을 따로 두나(보드 질문 CMPA-45):** 내부 리포트에는 `데일리샷대비(₩)` 컬럼이 있는데
데일리샷 데이터는 내부 R&D만 허용(법무 게이트 G1·CMPA-19)이라 공개 재배포엔 못 쓴다. 배포본은
그 컬럼을 빼고 공개 면책/19세 고지를 붙인 **공개 안전판**이다 — 단순 복제가 아니라 거버넌스 요구.
**정기 리포트 실행과 분리된 on-demand 단계**다: 실제 외부 배포 시점(CMPA-33 게이트 승인)에만 돌린다.
그래서 매주 배포본을 만들지 않는다 — 평소 정기 실행은 내부 리포트만 누적.

사용:
  python3 reports/make_distribution.py                          # latest 입력, 실행일=소스 리포트 생성일
  python3 reports/make_distribution.py <input.md> --run-date 2026-05-30
**실행일(run-date) 기본값(CMPA-265):** 미지정 시 **소스 리포트 파일명의 생성일**을 따른다(오늘 아님).
  → generate_report 가 무변동이면 새 dated md 를 안 만들므로, 배포본도 같은 날짜로 멱등(가짜-신선 방지).
"""
import argparse
import glob
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from pipelines.common.dated import kst_today  # noqa: E402

REPORTS = os.path.join(HERE, "whisky-price")  # CMPA-88: 가격 리포트는 reports/whisky-price 하위
os.makedirs(REPORTS, exist_ok=True)
DROP_COL = "데일리샷대비"  # 공개판에서 제거할 컬럼(헤더 부분일치)

DISCLAIMER = (
    "<!-- 배포본(공개용) — 데일리샷 비교 컬럼 제외, 출처·면책 표기 포함. CMPA-33 게이트 체크 반영. -->\n"
    "\n"
    "> **ℹ️ 이 자료는 공개 배포용입니다.** 가격은 **수집 기준일의 관측값**이며 실시간 시세가 "
    "아닙니다. 재고·행사·매장별로 실제 가격은 달라질 수 있으니 **구매 전 매장에서 반드시 확인**하세요. "
    "본 자료는 **정보 제공 목적**이며 특정 제품의 구매·판매를 권유하지 않습니다. 저희는 어떤 유통사·"
    "브랜드와도 **제휴/광고 관계가 없습니다**.\n"
    ">\n"
    "> 🔞 **음주는 19세 이상만 가능합니다. 지나친 음주는 건강을 해칩니다. 임신 중 음주는 태아의 "
    "건강을 해칩니다.**\n"
    "\n"
)


def split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def is_sep_cells(cells):
    return cells and all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c != "")


def drop_dailyshot_column(md):
    """헤더에 DROP_COL 이 들어간 컬럼을 그 표 전체(헤더·구분선·본문)에서 제거. 표 수에 무관."""
    lines = md.split("\n")
    out = []
    i, n = 0, len(lines)
    dropped = 0
    while i < n:
        line = lines[i]
        # 표 시작 후보: '|' 로 시작 + 다음 줄이 구분선
        if line.strip().startswith("|") and i + 1 < n and is_sep_cells(split_row(lines[i + 1])):
            header = split_row(line)
            drop_idx = next((k for k, h in enumerate(header) if DROP_COL in h), None)
            # 표 본문 끝까지 수집
            j = i + 2
            body = []
            while j < n and lines[j].strip().startswith("|"):
                body.append(lines[j])
                j += 1
            if drop_idx is None:
                out.extend(lines[i:j])  # 해당 컬럼 없는 표는 그대로
            else:
                def rm(cells):
                    return [c for k, c in enumerate(cells) if k != drop_idx]

                def render(cells):
                    return "| " + " | ".join(cells) + " |"

                out.append(render(rm(header)))
                out.append(render(rm(split_row(lines[i + 1]))))
                for b in body:
                    out.append(render(rm(split_row(b))))
                dropped += 1
            i = j
            continue
        out.append(line)
        i += 1
    return "\n".join(out), dropped


def clean_prose(md):
    """본문 내 데일리샷 관련 설명/각주를 공개판에 맞게 정리(베스트-에포트, 미일치 시 무해)."""
    # 컬럼 나열 코드라인: '… → 데일리샷대비(₩) → …' 에서 토큰 제거
    md = md.replace("과거평균比(₩) → 데일리샷대비(₩) →", "과거평균比(₩) →")
    md = md.replace("과거평균比(₩)·데일리샷대비(₩)·", "과거평균比(₩)·")
    # INTRO: '과거평균·데일리샷·매력도' → '과거평균·매력도'
    md = md.replace("과거평균·데일리샷·매력도", "과거평균·매력도")
    # SEC1_FOOT 의 데일리샷대비 설명 문장(줄 시작) 제거
    md = re.sub(r"^\*\*데일리샷대비\(₩\)\*\*.*?(?:\n|$)", "", md, flags=re.M)
    # '… 데일리샷 매칭 N종.' 각주 제거
    md = re.sub(r"\*\(\s*\d+종 중 데일리샷 매칭 \d+종\.\s*\)\*", "", md)
    return md


def date_from_report_name(path):
    """입력 리포트 파일명에 박힌 생성일(YYYY-MM-DD)을 뽑는다(CMPA-265).
    배포본 실행일을 '오늘'이 아니라 **소스 리포트의 생성일**에 맞춰, 무변동(생성 게이트가
    리포트를 새로 안 찍은) 주에 06-01 데이터에 오늘 날짜가 박히는 가짜-신선 배포본을 막는다.
    (generate_report 가 변동 시에만 새 dated md 를 만들므로, 소스 날짜=프리즈된 생성일.)
    파일명에 날짜가 없으면 None."""
    m = re.search(r"_(\d{4}-\d{2}-\d{2})\.md$", os.path.basename(path or ""))
    return m.group(1) if m else None


def resolve_input(arg, month_hint=None):
    if arg:
        return arg
    # 우선순위: latest 포인터 → 가장 최근 날짜 박힌 정본
    latest = glob.glob(os.path.join(REPORTS, "*_위스키가격리포트_latest.md"))
    latest = [p for p in latest if "배포본" not in p]
    if latest:
        return sorted(latest)[-1]
    dated = glob.glob(os.path.join(REPORTS, "*_위스키가격리포트_20[0-9][0-9]-[0-1][0-9]-[0-3][0-9].md"))
    dated = [p for p in dated if "배포본" not in p]
    if dated:
        return sorted(dated)[-1]
    raise SystemExit("입력 리포트를 찾을 수 없습니다. generate_report.py 를 먼저 실행하세요.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", nargs="?", help="입력 리포트 MD. 미지정 시 latest 포인터/최근 날짜본.")
    ap.add_argument("--run-date", help="배포본 파일명 실행일(YYYY-MM-DD). 미지정 시 오늘(KST).")
    ap.add_argument("--latest", action="store_true", help="_latest 포인터 사본도 생성(기본 끔).")
    ap.add_argument("--no-html", action="store_true", help="HTML 변환 생략(MD만).")
    args = ap.parse_args()

    inp = resolve_input(args.input)
    # CMPA-265: 배포본 실행일 = (1) --run-date 명시 > (2) 소스 리포트 생성일 > (3) 오늘(폴백).
    # 소스 리포트가 무변동으로 프리즈돼 있으면 배포본도 같은 날짜로 멱등 — 새 dated 산출물 미생성.
    run_date = args.run_date or date_from_report_name(inp) or kst_today()
    base = os.path.basename(inp)
    m = re.match(r"(\d{4}-\d{2})", base)
    month = m.group(1) if m else "report"

    with open(inp, encoding="utf-8") as f:
        md = f.read()
    md, dropped = drop_dailyshot_column(md)
    md = clean_prose(md)
    md = DISCLAIMER + md

    out_md = os.path.join(REPORTS, f"{month}_위스키가격리포트_배포본_{run_date}.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write(md)
    print(f"wrote {os.path.relpath(out_md, ROOT)}  (데일리샷 컬럼 제거 표 {dropped}개)")

    latest_md = None
    if args.latest:
        import shutil
        latest_md = os.path.join(REPORTS, f"{month}_위스키가격리포트_배포본_latest.md")
        shutil.copy2(out_md, latest_md)
        print(f"  latest pointer: {os.path.relpath(latest_md, ROOT)}")

    if not args.no_html:
        # dated 입력 → dated 출력(md_to_html 가 .md→.html 로 같은 날짜명을 만든다)
        subprocess.run([sys.executable, os.path.join(HERE, "md_to_html.py"), out_md], check=True)
        if latest_md:
            subprocess.run([sys.executable, os.path.join(HERE, "md_to_html.py"), latest_md], check=True)


if __name__ == "__main__":
    main()
