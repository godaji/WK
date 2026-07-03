#!/usr/bin/env python3
"""
refresh_corkage_map.py — 콜키지프리 맵 전체 파이프라인 오케스트레이터
(CMPA-82 분기 갱신 routine 의 단일 진입점 / CMPA-90 리팩토링 후 복구)

루틴 1회 fire = 수집 → 분석 → 리포트 전체 과정. 스테이지:

  1) 수집   find_corkage_free.py --station {역} --radius {r}     LIVE 역별 라이브 재크롤
  2) 분석   estimate_per_person_map.py --stations {live...}      식당별 1인 비용 추정
  3) 리포트 build_supported_stations.py                          지원역 매니페스트 + 신선도 헤더
  4) 변경   diff_corkage_map.py --out _runs/맵diff__run{today}.md 직전 스냅샷 대비 diff

LIVE 역은 매니페스트(`data/corkage-free/지원역_목록.csv` 의 status=live)에서
**동적으로** 읽는다(하드코딩 금지) → 역 추가(예: CMPA-83 여의도) 시 코드/description
수정 없이 자동 반영. 현재 LIVE = 강남·합정·마포·여의도(4역).

WAF 페이싱·메뉴/사진 캐시·`_runs/` 날짜 스냅샷은 각 스테이지 스크립트가 그대로 유지한다
(오케스트레이터는 호출·집계만, 외부호출 로직 중복 없음).

종료코드: 모든 스테이지 exit 0 → 0. 하나라도 실패 → 1. diff 변경 감지는 실패가 아니다.
표준출력 끝에 `PIPELINE RESULT:` 요약(스테이지별 PASS/FAIL + diff 변경여부)을 찍는다 →
실행 이슈 코멘트로 그대로 붙일 수 있다.

용법:
  python3 pipelines/corkage_free/refresh_corkage_map.py            # 전체(라이브 재크롤 포함)
  python3 pipelines/corkage_free/refresh_corkage_map.py --smoke    # 배선 점검(라이브 호출 없음)
  python3 pipelines/corkage_free/refresh_corkage_map.py --skip-crawl  # 수집 생략, 분석부터
  python3 pipelines/corkage_free/refresh_corkage_map.py --stations 강남역 합정역
"""
from __future__ import annotations

import argparse
import csv
import datetime as _dt
import os
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
PKG_DIR = HERE.parent                      # pipelines/corkage_free
ROOT = HERE.parents[2]                     # 리포 루트 (.../WK)
DATA_DIR = ROOT / "data" / "corkage-free"
RUNS_DIR = DATA_DIR / "_runs"
MANIFEST = DATA_DIR / "지원역_목록.csv"

PY = sys.executable or "python3"


def _today() -> str:
    return _dt.date.today().isoformat()


def live_stations() -> list[str]:
    """매니페스트에서 status=live 역명을 읽는다(diff_corkage_map._live_stations 와 동일 규칙)."""
    if not MANIFEST.exists():
        return []
    out: list[str] = []
    with open(MANIFEST, encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(r for r in f if not r.lstrip().startswith("#")):
            if (row.get("status") or "").strip() == "live" and row.get("station"):
                out.append(row["station"].strip())
    return out


def run_stage(name: str, argv: list[str]) -> dict:
    """스테이지 스크립트를 서브프로세스로 실행. cwd=ROOT(상대경로 산출물 보장)."""
    script = PKG_DIR / argv[0]
    cmd = [PY, str(script)] + argv[1:]
    print(f"\n{'='*70}\n[STAGE] {name}\n  $ {' '.join(cmd)}\n{'='*70}", flush=True)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(ROOT))
    dt = time.time() - t0
    ok = proc.returncode == 0
    print(f"[STAGE-END] {name}: exit {proc.returncode} ({dt:.0f}s)", flush=True)
    return {"name": name, "exit": proc.returncode, "ok": ok, "sec": round(dt)}


def main() -> int:
    ap = argparse.ArgumentParser(description="콜키지프리 맵 전체 파이프라인 오케스트레이터")
    ap.add_argument("--stations", nargs="*", default=None,
                    help="대상 역(기본=매니페스트 live 역 자동탐지)")
    ap.add_argument("--radius", type=int, default=800, help="수집 반경(m), 기본 800")
    ap.add_argument("--smoke", action="store_true",
                    help="라이브 재크롤·메뉴호출 없이 오프라인 스테이지(리포트·diff)+배선 점검만")
    ap.add_argument("--skip-crawl", action="store_true",
                    help="수집 스테이지 생략(기존 CSV 재사용)")
    a = ap.parse_args()

    stations = a.stations if a.stations else live_stations()
    if not stations:
        print("[오류] LIVE 역을 찾지 못함 — 매니페스트 확인:", MANIFEST, file=sys.stderr)
        return 2

    today = _today()
    RUNS_DIR.mkdir(parents=True, exist_ok=True)
    diff_out = RUNS_DIR / f"맵diff__run{today}.md"

    print(f"[refresh] LIVE 역 {len(stations)}: {', '.join(stations)}")
    print(f"[refresh] 모드={'smoke' if a.smoke else 'full'} "
          f"radius={a.radius} diff_out={diff_out.relative_to(ROOT)}")

    results: list[dict] = []

    # ── 스테이지 1: 수집 (라이브 재크롤) ──────────────────────────────
    if a.smoke:
        # 배선 점검: 수집 스크립트가 import/CLI 동작하는지만(--dry-run, 강남 1역)
        results.append(run_stage("1.수집(smoke:dry-run)",
                                 ["find_corkage_free.py", "--station", stations[0],
                                  "--radius", str(a.radius), "--dry-run"]))
    elif a.skip_crawl:
        print("[refresh] --skip-crawl: 수집 스테이지 생략")
    else:
        for i, st in enumerate(stations):
            results.append(run_stage(f"1.수집:{st}",
                                     ["find_corkage_free.py", "--station", st,
                                      "--radius", str(a.radius)]))
            if i < len(stations) - 1:
                time.sleep(5)  # 역 간 페이싱(스크립트 내부 WAF 페이싱과 별개의 매너 간격)

    # ── 스테이지 2: 분석 (인당비용 추정) ─────────────────────────────
    if a.smoke:
        print("[refresh] smoke: 분석 스테이지(라이브 메뉴호출) 생략")
    else:
        results.append(run_stage("2.분석:estimate_per_person_map",
                                 ["estimate_per_person_map.py", "--stations"] + stations))

    # ── 스테이지 3: 리포트 (지원역 매니페스트 + 신선도 헤더) ─────────
    results.append(run_stage("3.리포트:build_supported_stations",
                             ["build_supported_stations.py"]))

    # ── 스테이지 4: 변경 감지 diff ───────────────────────────────────
    diff = run_stage("4.변경:diff_corkage_map",
                     ["diff_corkage_map.py", "--out", str(diff_out),
                      "--stations"] + stations)
    results.append(diff)
    diff_changed = diff_out.exists() and diff["ok"]

    # ── 요약 ─────────────────────────────────────────────────────────
    print(f"\n{'#'*70}\nPIPELINE RESULT: ({'smoke' if a.smoke else 'full'} / {today})")
    all_ok = True
    for r in results:
        flag = "PASS" if r["ok"] else "FAIL"
        if not r["ok"]:
            all_ok = False
        print(f"  [{flag}] {r['name']:42s} exit {r['exit']}  {r['sec']}s")
    if diff_changed:
        print(f"  [diff] 변경 감지 → {diff_out.relative_to(ROOT)} (리뷰 필요)")
    else:
        print("  [diff] 변경 없음(no-change) 또는 기준 스냅샷 없음")
    print(f"PIPELINE RESULT: {'GREEN ✅' if all_ok else 'RED ❌'}")
    print('#'*70)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
