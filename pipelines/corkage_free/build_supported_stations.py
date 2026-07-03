#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
build_supported_stations.py — 콜키지프리 맵 '지원 역 리스트' 정본 매니페스트 생성 (CMPA-76)

목적
----
콜키지프리 `맵생성` 제품이 **실제로 LIVE 커버하는 역**을 정본 데이터 자산으로 추출한다.
지금까지 지원 역은 코드(`STATION_COORDS`)와 `data/corkage-free/*_콜키지프리.csv` glob에만
암묵적으로 존재했다 → 이 스크립트가 그것을 단일 매니페스트(`지원역_목록.csv`/`.md`)로 굳힌다.

설계 원칙
---------
- **결정론·재크롤 금지.** DiningCode 등 외부 호출을 일절 하지 않는다. 입력은
  (1) `data/corkage-free/*_콜키지프리.csv` 산출물 파일과
  (2) `find_corkage_free.STATION_COORDS` 좌표 사전 — 둘 다 이미 디스크에 있는 것뿐이다.
- 같은 디스크 상태 → 항상 같은 매니페스트.

역 분류 규칙 (README §역 3종 참고)
--------------------------------
- **status=live**  : `{역명}_콜키지프리.csv` 산출물이 실제로 존재하는 역 (강남역·합정역).
- **status=candidate** : 좌표 사전(`STATION_COORDS`)에는 있으나 아직 맵 산출물이 없는 역.
  → 좌표가 준비돼 있어 `find_corkage_free.py --station` 한 줄로 바로 LIVE 승격 가능한 역.
  (다음에 돌릴 역 *랭킹* 35역은 `data/stations/evening-hotspot-stations.csv`의 별개 자산 —
   여기 candidate 와 혼동 금지. 여기 candidate = '좌표는 있고 산출물만 없는' 좁은 집합.)

신선도 헤더 (CMPA-82)
--------------------
- `맵생성`은 분기(3개월) 1회 정기 재크롤로 갱신된다(routine `refresh_corkage_map.py`).
- 매니페스트에 **마지막 갱신일 / 다음 갱신 예정일(=마지막+분기)** 을 표기해, 데이터가
  얼마나 신선한지/언제 다시 돌아야 하는지를 한눈에 보이게 한다.
  - 마지막 갱신일 = live 역들의 `생성일`(산출물 csv mtime) 중 가장 최신.
  - 다음 갱신 예정일 = 마지막 갱신일 + 3개월.
- CSV: 헤더 위에 `#` 주석 2줄로(머신 파서는 `comment='#'` 로 무시). MD: 헤더 블록에 표기.

스키마 (CMPA-60 교훈: data/stations/ evening-hotspot CSV 와 파일/스키마 중복·충돌 금지.
좌표는 동일 `lat,lng` WGS84 표기.)
    station, lat, lng, 식당수, 인당비용행수, status, 생성일, csv경로, md경로, html경로, source

사용법
------
    python3 pipelines/corkage_free/build_supported_stations.py
    # 새 역 맵을 만든 뒤 다시 돌리면 매니페스트가 갱신된다.
"""
from __future__ import annotations

import calendar
import csv
import datetime as _dt
import os
import sys
from pathlib import Path

# STATION_COORDS 좌표 사전을 정본 소스에서 그대로 가져온다(중복 정의 금지).
sys.path.insert(0, str(Path(__file__).resolve().parent))
from find_corkage_free import STATION_COORDS  # noqa: E402

# ── 경로 ─────────────────────────────────────────────────────────────────────
REPO = Path(__file__).resolve().parents[2]
DATA_DIR = REPO / "data" / "corkage-free"
# CMPA-88: 사람이 보는 리포트(md/html)는 reports/corkage-free 로 이전됨(데이터 csv 는 data 유지).
REPORT_DIR = REPO / "reports" / "corkage-free"
SUFFIX = "_콜키지프리.csv"
PER_PERSON_ALL = DATA_DIR / "콜키지프리_인당비용_전체.csv"

OUT_CSV = DATA_DIR / "지원역_목록.csv"
OUT_MD = DATA_DIR / "지원역_목록.md"

FIELDS = ["station", "lat", "lng", "식당수", "인당비용행수", "status",
          "생성일", "csv경로", "md경로", "html경로", "source"]

# 갱신 주기(개월) — 분기 = 3개월 (CMPA-82). routine cron 과 동일한 주기여야 한다.
REFRESH_MONTHS = 3


def _count_rows(path: Path) -> int:
    """헤더 제외 데이터 행 수 (utf-8-sig)."""
    with path.open(encoding="utf-8-sig", newline="") as f:
        return sum(1 for _ in csv.reader(f)) - 1


def _per_person_counts() -> dict[str, int]:
    """콜키지프리_인당비용_전체.csv 의 역별 행 수 (없으면 빈 dict)."""
    counts: dict[str, int] = {}
    if not PER_PERSON_ALL.exists():
        return counts
    with PER_PERSON_ALL.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            st = (row.get("역") or "").strip()
            if st:
                counts[st] = counts.get(st, 0) + 1
    return counts


def _rel(path: Path) -> str:
    return path.relative_to(REPO).as_posix()


def _gen_date(csv_path: Path) -> str:
    """산출물 csv 파일의 수정시각(날짜) — 맵이 생성된 시점의 결정론적 프록시."""
    ts = csv_path.stat().st_mtime
    return _dt.date.fromtimestamp(ts).isoformat()


def _add_months(d: _dt.date, months: int) -> _dt.date:
    """월 단위 가산(말일 클램프). 분기 주기 계산용 — dateutil 없이 결정론."""
    m = d.month - 1 + months
    y = d.year + m // 12
    m = m % 12 + 1
    day = min(d.day, calendar.monthrange(y, m)[1])
    return _dt.date(y, m, day)


def _freshness(rows: list[dict]) -> tuple[str, str]:
    """(마지막 갱신일, 다음 갱신 예정일). 마지막 = live 생성일 중 최신, 다음 = +분기."""
    live_dates = [r["생성일"] for r in rows
                  if r["status"] == "live" and r["생성일"]]
    if live_dates:
        last_d = max(_dt.date.fromisoformat(x) for x in live_dates)
    else:
        last_d = _dt.date.fromtimestamp(DATA_DIR.stat().st_mtime)
    return last_d.isoformat(), _add_months(last_d, REFRESH_MONTHS).isoformat()


def build() -> list[dict]:
    per_person = _per_person_counts()
    rows: list[dict] = []
    live_stations: set[str] = set()

    # 1) LIVE = 산출물 csv 가 실제 존재하는 역
    for csv_path in sorted(DATA_DIR.glob("*" + SUFFIX)):
        station = csv_path.name[: -len(SUFFIX)]
        live_stations.add(station)
        lat, lng = STATION_COORDS.get(station, ("", ""))
        md_path = REPORT_DIR / (station + "_콜키지프리.md")
        html_path = REPORT_DIR / (station + "_콜키지프리.html")
        rows.append({
            "station": station,
            "lat": lat,
            "lng": lng,
            "식당수": _count_rows(csv_path),
            "인당비용행수": per_person.get(station, 0),
            "status": "live",
            "생성일": _gen_date(csv_path),
            "csv경로": _rel(csv_path),
            "md경로": _rel(md_path) if md_path.exists() else "",
            "html경로": _rel(html_path) if html_path.exists() else "",
            "source": "find_corkage_free.py + estimate_per_person_map.py",
        })

    # 2) CANDIDATE = 좌표 사전엔 있으나 아직 산출물 없는 역
    for station, (lat, lng) in STATION_COORDS.items():
        if station in live_stations:
            continue
        rows.append({
            "station": station,
            "lat": lat,
            "lng": lng,
            "식당수": 0,
            "인당비용행수": 0,
            "status": "candidate",
            "생성일": "",
            "csv경로": "",
            "md경로": "",
            "html경로": "",
            "source": "STATION_COORDS (좌표만 준비, 미생성)",
        })

    # live 먼저(식당수 내림차순), 그다음 candidate(역명 가나다순)
    rows.sort(key=lambda r: (r["status"] != "live", -int(r["식당수"]), r["station"]))
    return rows


def write_csv(rows: list[dict], last: str, nxt: str) -> None:
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        # 신선도 헤더 — 머신 파서는 comment='#' 로 무시(아래 데이터는 표준 CSV).
        f.write(f"# 마지막갱신일,{last}\n")
        f.write(f"# 다음갱신예정일,{nxt},(분기={REFRESH_MONTHS}개월 주기 = 마지막+{REFRESH_MONTHS}개월)\n")
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


def write_md(rows: list[dict], last: str, nxt: str) -> None:
    live = [r for r in rows if r["status"] == "live"]
    cand = [r for r in rows if r["status"] == "candidate"]
    total_rest = sum(int(r["식당수"]) for r in live)

    lines = [
        "# 콜키지프리 맵 — 지원 역 목록 (커버리지 매니페스트)",
        "",
        "> **이 파일 = `맵생성`(콜키지프리 식당 맵) 제품이 실제 LIVE 커버하는 역의 정본 매니페스트.** (CMPA-76)",
        f"> 결정론 생성 — `data/corkage-free/*{SUFFIX}` 산출물 + `STATION_COORDS` 좌표 사전에서만 집계 (재크롤 없음).",
        "> 재생성: `python3 pipelines/corkage_free/build_supported_stations.py`",
        "",
        f"> 🕒 **마지막 갱신일: {last}** · **다음 갱신 예정일: {nxt}** "
        f"(분기 {REFRESH_MONTHS}개월 주기 = 마지막+{REFRESH_MONTHS}개월, routine `refresh_corkage_map.py`).",
        "",
        f"- **LIVE 역: {len(live)}곳** · 콜키지프리 식당 총 **{total_rest}곳**",
        f"- **CANDIDATE 역: {len(cand)}곳** (좌표 준비됨, 산출물 미생성)",
        "",
        "## LIVE — 맵 산출물 존재",
        "",
        "| station | lat | lng | 식당수 | 인당비용행수 | 생성일 | csv |",
        "| --- | ---: | ---: | ---: | ---: | --- | --- |",
    ]
    for r in live:
        lines.append(
            f"| {r['station']} | {r['lat']} | {r['lng']} | {r['식당수']} | "
            f"{r['인당비용행수']} | {r['생성일']} | `{r['csv경로']}` |"
        )
    lines += [
        "",
        "## CANDIDATE — 좌표만 준비 (산출물 미생성)",
        "",
        "> `find_corkage_free.py --station {역명}` 한 줄로 바로 LIVE 승격 가능. "
        "다음에 돌릴 역 *랭킹*은 별개 자산 `data/stations/evening-hotspot-stations.csv` 참고.",
        "",
        "| station | lat | lng |",
        "| --- | ---: | ---: |",
    ]
    for r in cand:
        lines.append(f"| {r['station']} | {r['lat']} | {r['lng']} |")
    lines += [
        "",
        "---",
        "> 내부 R&D 자산. 공개 배포는 가드레일 게이트 `c7405e7d` 대상 (이 매니페스트는 내부 자산화까지만).",
        "",
    ]
    OUT_MD.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    if not DATA_DIR.exists():
        print(f"[error] 데이터 디렉토리 없음: {DATA_DIR}", file=sys.stderr)
        return 1
    rows = build()
    last, nxt = _freshness(rows)
    write_csv(rows, last, nxt)
    write_md(rows, last, nxt)
    live = sum(1 for r in rows if r["status"] == "live")
    cand = sum(1 for r in rows if r["status"] == "candidate")
    print(f"[ok] {OUT_CSV.relative_to(REPO)} 생성 — live {live} / candidate {cand} (총 {len(rows)}행)")
    print(f"     🕒 마지막 갱신 {last} · 다음 갱신 예정 {nxt} (분기 {REFRESH_MONTHS}개월)")
    for r in rows:
        print(f"  - {r['status']:9s} {r['station']:8s} 식당 {r['식당수']:>3} / 인당비용 {r['인당비용행수']:>3}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
