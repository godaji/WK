#!/usr/bin/env python3
"""run_whisky_price_pipeline.py — 위스키 가격 파이프라인 통합(일괄) 실행 오케스트레이터.

보드 루틴 'whisky-price 통합 실행'(CMPA-98)의 단일 진입점.

왜 필요한가 (CMPA-98 포렌식):
  수동 일괄 재실행에서 각 스테이지(수집·정규화·리포트)가 별 이슈/하트비트로 쪼개져
  거의 동시에 실행되면, 최종 소비자인 105 리포트가 상류(수집·정규화)가 CSV 를
  다 쓰기 **전에** 먼저 읽어 **stale 리포트**가 나온다(환율 환산가·데일리샷 매칭 수가
  갱신 전 값으로 박제됨 — 실측 확인). 평상시 cron 은 시간차로 안전하지만, 수동 일괄
  실행은 시간차가 사라진다. 이 오케스트레이터는 **단계 순서를 강제**해 그 레이스를 막는다.

스테이지 (의존성 순서, 순차 실행):
  1) 수집  (서로 파일 격리 → 순차로 안전하게):
       a. 해외     pipelines/overseas/collect_overseas.py    (FX + 홍콩 + 일본 Shopify)   [routine 100]
       b. 데일리샷 pipelines/dailyshot/crawl_dailyshot.py                                   [routine 101]
       c. 코스트코 pipelines/costco_web/collect_costco_web.py                               [routine 103]
       d. 이마트SSG pipelines/emart_ssg/collect_emart_ssg.py  (emart.ssg.com store-pickup) [CMPA-420/422]
     유튜브 트레이더스[102]는 ASR·per-IP 429 ≥60분 페이싱이라 동기 일괄 실행에 부적합 →
     자체 주간 cron 으로 유지. 최신 트레이더스 CSV 가 이미 있으면 정규화가 그걸 사용한다.
     (그래도 포함하려면 --with-traders. 기본 제외.)
  2) 정규화  scripts/normalize_dataset.py                                                   [routine 104]
  3) 리포트  scripts/generate_report.py                                                     [routine 105]
  4) 계약검증 scripts/check_contract.py (CMPA-161/162)                                        — 리포트 성공 직후
  5) 런 아카이브 pipelines/common/run_archive.py (CMPA-151)                                   — 정본 불변·추가 복사

런 아카이브(CMPA-151 output 구조): 정본(data/·reports/)을 latest 포인터로 그대로 두고,
  추가로 `runs/<run_date>/<asset>/` 날짜 폴더에 이 런의 산출물 사본을 모은다(날짜별 누적).
  deploy 는 cross-asset 이라 `runs/<run_date>/deploy/`(배포 단계가 채움). 날짜는
  `pipelines/common/run_dates.run_date()` 단일 출처(스테이지 전체가 같은 날짜 공유).

계약검증(CMPA-161 자산 규약): 리포트 스테이지 성공 직후 OUTPUT 계약을 기계검증한다.
  계약 위반(스키마/메타/불변식 위반)이면 **파이프라인 hard-fail = 배포 차단**.
  --smoke 는 라이브 산출물이 없으므로 계약검증 대신 스크립트 컴파일만 점검한다.

배포(make_distribution)는 분리된 게이트 단계(CMPA-33) → **통합 실행은 배포본을 만들지 않는다.**

성공/실패 규약:
  - 수집 스테이지는 개별 실패해도 경고 후 계속(외부 API 429/일시장애가 리포트 재생성을 막지 않게).
    단 --strict 면 수집 실패도 hard-fail.
  - 정규화·리포트 실패는 항상 hard-fail.
  - exit 0 = 정규화+리포트 PASS. 1 = 그 중 실패. 표준출력 끝에 PIPELINE RESULT 요약 출력.

용법:
  python3 scripts/run_whisky_price_pipeline.py                 # 수집→정규화→리포트(트레이더스 제외)
  python3 scripts/run_whisky_price_pipeline.py --skip-crawl    # 수집 생략, 정규화→리포트만(가장 흔한 안전 재실행)
  python3 scripts/run_whisky_price_pipeline.py --with-traders  # 유튜브 트레이더스 수집도 포함(느림)
  python3 scripts/run_whisky_price_pipeline.py --strict        # 수집 실패도 hard-fail
  python3 scripts/run_whisky_price_pipeline.py --smoke         # 배선 점검만(라이브 호출 없음)
"""
from __future__ import annotations

import argparse
import py_compile
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]                      # 리포 루트 (.../WK)
PY = sys.executable or "python3"

# CMPA-151: 런 날짜 단일 출처. ROOT 를 path 에 넣어 pipelines.common 임포트.
sys.path.insert(0, str(ROOT))
from pipelines.common import run_dates      # noqa: E402  (run_date() = 단일 날짜 출처)

# CMPA-151: 통합 실행 끝에서 이번 런 산출물을 runs/<run_date>/<asset>/ 로 모으는 아카이버.
RUN_ARCHIVE = "pipelines/common/run_archive.py"

# 수집 스테이지: (라벨, 루틴번호, 스크립트 상대경로, 추가 인자)
COLLECT_STEPS = [
    ("해외(FX+홍콩+일본)", 100, "pipelines/overseas/collect_overseas.py", []),
    ("데일리샷",           101, "pipelines/dailyshot/crawl_dailyshot.py", []),
    ("코스트코 웹",         103, "pipelines/costco_web/collect_costco_web.py", []),
    # 이마트(SSG) — emart.ssg.com 서버렌더 JSON 위스키 store-pickup 가격(CMPA-420/422).
    # 파일 격리(2026-06.csv 에 위치='이마트(SSG)' append, 멱등) → 순차로 안전. lean 2쿼리
    # (위스키·양주)·요청 간 pace+지터·429 백오프. adapt_domestic 가 월간 CSV 를 위치 기준
    # 자동 ingest 하므로 정규화 floor·리포트에 자동 통합(코스트코/유튜브와 동일 경로).
    ("이마트(SSG)",        420, "pipelines/emart_ssg/collect_emart_ssg.py", []),
]
# 유튜브 트레이더스(102)는 --with-traders 일 때만. discover→fetch→parse→load 다단계라
# 여기서는 'load'(이미 받아둔 ASR 산출물 적재)만 동기 실행 대상으로 두지 않고, 전체는 자체 cron.
TRADERS_NOTE = ("유튜브 트레이더스(102): 소스=@whiskeypick·@whiskeykey 2채널(싼디/@SSanD3 아님). "
                "ASR·≥60분 per-IP 페이싱으로 동기 일괄 실행 부적합 → 자체 주간 cron 유지. "
                "최신 CSV 가 있으면 정규화가 사용.")

# CMPA-161/162: 리포트 성공 직후 호출하는 자산 계약 검증기.
CONTRACT_PATH = "contracts/whisky-price-intelligence.yaml"
CONTRACT_CHECKER = "scripts/check_contract.py"


def _today() -> str:
    # CMPA-151: 통합 실행의 날짜는 run_dates.run_date() 단일 출처(COLLECT_DATE>RUN_DATE>FX_ASOF>오늘).
    return run_dates.run_date()


def run_stage(name: str, rel_script: str, extra: list[str]) -> dict:
    """스테이지 스크립트를 서브프로세스로 실행. cwd=ROOT(상대경로 산출물 보장)."""
    script = ROOT / rel_script
    if not script.exists():
        print(f"[STAGE-MISS] {name}: 스크립트 없음 {rel_script}", flush=True)
        return {"name": name, "exit": 127, "ok": False, "sec": 0}
    cmd = [PY, str(script)] + extra
    print(f"\n{'='*70}\n[STAGE] {name}\n  $ {' '.join(cmd)}\n{'='*70}", flush=True)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(ROOT))
    dt = time.time() - t0
    ok = proc.returncode == 0
    print(f"[STAGE-END] {name}: exit {proc.returncode} ({dt:.0f}s)", flush=True)
    return {"name": name, "exit": proc.returncode, "ok": ok, "sec": round(dt)}


def smoke_compile(rel_script: str) -> dict:
    """배선 점검: 라이브 호출 없이 스크립트가 컴파일되는지(import/문법)만 확인."""
    script = ROOT / rel_script
    name = rel_script
    if not script.exists():
        print(f"  [MISS] {rel_script}", flush=True)
        return {"name": name, "exit": 127, "ok": False, "sec": 0}
    try:
        py_compile.compile(str(script), doraise=True)
        print(f"  [OK]   compile {rel_script}", flush=True)
        return {"name": name, "exit": 0, "ok": True, "sec": 0}
    except py_compile.PyCompileError as e:
        print(f"  [FAIL] compile {rel_script}: {e}", flush=True)
        return {"name": name, "exit": 1, "ok": False, "sec": 0}


def main() -> int:
    ap = argparse.ArgumentParser(description="위스키 가격 파이프라인 통합 실행 오케스트레이터")
    ap.add_argument("--skip-crawl", action="store_true",
                    help="수집 스테이지 생략(기존 CSV 재사용) → 정규화·리포트만")
    ap.add_argument("--with-traders", action="store_true",
                    help="유튜브 트레이더스 수집(load)도 포함(느림, 기본 제외)")
    ap.add_argument("--strict", action="store_true",
                    help="수집 스테이지 실패도 hard-fail(기본은 경고 후 계속)")
    ap.add_argument("--smoke", action="store_true",
                    help="배선 점검만: 모든 스테이지 스크립트 컴파일 확인(라이브 호출 없음)")
    a = ap.parse_args()

    today = _today()
    all_steps = COLLECT_STEPS + [
        ("정규화·검증", 104, "scripts/normalize_dataset.py", []),
        ("리포트(md) 생성", 105, "scripts/generate_report.py", []),
    ]

    # ── smoke: 컴파일 점검만 ──────────────────────────────────────────
    if a.smoke:
        print(f"[pipeline] smoke(배선 점검) / {today} — 라이브 호출 없음")
        results = [smoke_compile(rel) for _, _, rel, _ in all_steps]
        results.append(smoke_compile("scripts/whisky_report_tables.py"))
        results.append(smoke_compile("scripts/kr_jp_compare.py"))
        results.append(smoke_compile(CONTRACT_CHECKER))  # CMPA-162: 계약검증기도 배선 점검
        results.append(smoke_compile(RUN_ARCHIVE))       # CMPA-151: 런 아카이버 배선 점검
        results.append(smoke_compile("pipelines/common/run_dates.py"))  # CMPA-151: 날짜 단일 출처
        all_ok = all(r["ok"] for r in results)
        print(f"\nPIPELINE RESULT (smoke): {'GREEN ✅' if all_ok else 'RED ❌'} "
              f"({sum(r['ok'] for r in results)}/{len(results)} compiled)")
        return 0 if all_ok else 1

    print(f"[pipeline] 통합 실행 / {today}")
    print(f"[pipeline] 순서: 수집(해외→데일리샷→코스트코) → 정규화 → 리포트  "
          f"(배포는 별도 게이트, 미생성)")
    print(f"[pipeline] {TRADERS_NOTE}")

    results: list[dict] = []
    collect_failed = False

    # ── 스테이지 1: 수집 (파일 격리, 순차) ────────────────────────────
    if a.skip_crawl:
        print("\n[pipeline] --skip-crawl: 수집 스테이지 전체 생략(기존 CSV 재사용)")
    else:
        steps = list(COLLECT_STEPS)
        if a.with_traders:
            steps.append(("유튜브 트레이더스(load)", 102,
                          "pipelines/youtube_traders/collect_traders_prices.py", ["load"]))
        for i, (label, rnum, rel, extra) in enumerate(steps):
            r = run_stage(f"1.수집[{rnum}] {label}", rel, extra)
            results.append(r)
            if not r["ok"]:
                collect_failed = True
                print(f"  ! 수집 실패({label}). "
                      f"{'중단(--strict)' if a.strict else '경고 후 계속(기존 CSV 사용)'}", flush=True)
                if a.strict:
                    return _summary(results, today, hard_stop=True)
            if i < len(steps) - 1:
                time.sleep(3)  # 수집 간 매너 간격

    # ── 스테이지 2: 정규화 (모든 수집 출력 의존) ──────────────────────
    norm = run_stage("2.정규화·검증[104]", "scripts/normalize_dataset.py", [])
    results.append(norm)
    if not norm["ok"]:
        print("  ! 정규화 실패 → 리포트 스테이지 중단(stale 리포트 방지)", flush=True)
        return _summary(results, today, hard_stop=True)

    # ── 스테이지 3: 리포트 (정규화 완료 후에만) ───────────────────────
    rep = run_stage("3.리포트(md)[105]", "scripts/generate_report.py", [])
    results.append(rep)
    if not rep["ok"]:
        print("  ! 리포트 실패 → 계약검증 생략(검증할 산출물 없음)", flush=True)
        return _summary(results, today, hard_stop=True)

    # ── 스테이지 4: 계약검증 (CMPA-161/162, 리포트 성공 직후) ──────────
    # OUTPUT 계약 위반이면 hard-fail = 배포 차단. 결정론적·네트워크 없음.
    chk = run_stage("4.계약검증[CMPA-162]", CONTRACT_CHECKER, ["--contract", CONTRACT_PATH])
    results.append(chk)
    if not chk["ok"]:
        print("  ! 계약 위반 → 파이프라인 hard-fail(배포 차단). 위반 항목은 위 STAGE 로그 참조.", flush=True)

    # ── 스테이지 5: 런 아카이브 (CMPA-151, 정본 불변·추가 복사) ─────────
    # 정본(latest)은 그대로 두고, 이번 런 산출물 사본을 runs/<run_date>/<asset>/ 로 모은다.
    # 같은 run_date 단일 출처를 명시 전달(스테이지 간 날짜 표류 방지).
    arc = run_stage("5.런 아카이브[CMPA-151]", RUN_ARCHIVE, [today])
    results.append(arc)

    return _summary(results, today, collect_failed=collect_failed)


def _summary(results: list[dict], today: str, hard_stop: bool = False,
             collect_failed: bool = False) -> int:
    print(f"\n{'#'*70}\nPIPELINE RESULT: (통합 실행 / {today})")
    for r in results:
        flag = "PASS" if r["ok"] else "FAIL"
        print(f"  [{flag}] {r['name']:34s} exit {r['exit']}  {r['sec']}s")
    # 핵심 게이트 = 정규화 + 리포트 + 계약검증 모두 PASS 여야 GREEN (CMPA-162: 계약위반=배포차단)
    crit = [r for r in results if r["name"].startswith(("2.정규화", "3.리포트", "4.계약검증"))]
    crit_ok = bool(crit) and all(r["ok"] for r in crit) and not hard_stop
    if collect_failed:
        print("  [note] 일부 수집 실패 → 해당 소스는 기존(직전) CSV 로 리포트 생성됨(부분 신선도).")
    print(f"PIPELINE RESULT: {'GREEN ✅' if crit_ok else 'RED ❌'}")
    print('#'*70, flush=True)
    return 0 if crit_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
