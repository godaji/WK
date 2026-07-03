#!/usr/bin/env python3
"""run_shilla_pipeline.py — 신라면세 위스키 리포트 파이프라인 통합/단계 실행 오케스트레이터.

CMPA-139 (프로세스·의존성 정리 문서 `shilla-dutyfree_파이프라인_프로세스_의존성.md`)의 단일 진입점.
보드 200번대 루틴이 이 한 스크립트를 `--stage` 만 바꿔 호출한다.

4단계 (의존성 순서):
  1) collect  수집   pipelines/shilla_dutyfree/crawl_shilla_whisky.py        [routine 200]  ※LIVE(신라 AJAX)
  2) process  가공   pipelines/shilla_dutyfree/filter_peated.py              [routine 201]
  3) analyze  분석   매력도/비교/추천 8종 (피트/스타일/국내가교차/예산)        [routine 202]  ※일부 LIVE
  4) report   리포트 build_report(md) → build_report_html → build_deploy     [routine 203]
  all        전체   1→2→3→4 순서 강제                                       [routine 209]

런 아카이브(CMPA-151/293):
  성공 스텝이 하나라도 있으면 끝에서 이번 런이 만든 <date> 산출물 사본을
  `runs/<run_date>/shilla_data/`(수집 raw + 분석 CSV/JSON) 와
  `runs/<run_date>/shilla_report/`(피트/가성비/예산 md + 발행 html) 로 모은다(정본 불변·추가 복사).
  deploy 는 cross-asset 이라 build_deploy 가 `runs/<run_date>/deploy/` 를 별도로 채운다.
  날짜 단위 멱등(같은 run_date 재실행 = 그 날 폴더 갱신). 매니페스트=`_manifest_shilla.json`.

날짜 일관성:
  --date 하나를 환경변수 SHILLA_DATE 로 모든 서브프로세스에 주입한다. 수집·필터·분석·리포트가
  전부 같은 <date> 파일을 읽고/쓰고, 리포트 본문/파일명 생성일도 그 값으로 정렬된다.
  (하드코딩 2026-06-06 제거: 각 스크립트는 SHILLA_DATE 우선, 없으면 종전 기본값.)

현재(LIVE) vs 간헐(정본 참조):
  LIVE = 신라 AJAX(수집·score_peated 라이브 재조회)·데일리샷 API(find_cheaper). 매 실행 새로 받음.
  간헐 = fx_latest/normalized_prices/whisky-list/해외POC/마트월간 → 별도 루틴이 갱신, 여기선 읽기만.
  LIVE 스텝은 직렬 + 매너 간격(--pace)으로 429 를 피한다.

리포트↔수집 의존성 가드레일(CMPA-235):
  리포트 생성(report 스테이지: build_report / build_report_html / build_deploy)은 요청 `--date`(기본
  오늘 KST)의 **신라 오늘자 raw CSV** `data/shilla-dutyfree/신라면세_위스키_<date>.csv` 에 의존한다.
  report 스텝이 '선행 collect 없이' 도는 경우(`--stage report`, 또는 `--stage all --skip-crawl`)에
  raw CSV 가 없으면:
    - 기본    → collect→process→analyze 를 report 앞에 선행 보강(자동 수집) 후 진행.
    - --skip-crawl → 자동 수집 불가이므로 **명확한 메시지로 hard-fail**(조용한 stale-date 리포트 금지).
  (일반 위스키가격리포트 `run_whisky_price_pipeline.py` 는 신라 데이터와 무관 = 입력 `data/whisky-prices/`.
   거기엔 이 가드를 두지 않는다.)

성공/실패 규약:
  - 수집 실패는 hard-fail(전 단계가 뿌리이므로). --skip-crawl 이면 기존 <date> CSV 재사용.
  - 분석 개별 스텝 실패는 경고 후 계속(한 가지 실패가 리포트 전체를 막지 않게). --strict 면 hard-fail.
  - 리포트 빌드 실패는 hard-fail.
  - exit 0 = 요청한 스테이지의 핵심 스텝 PASS. 끝에 PIPELINE RESULT 요약.

용법:
  python3 scripts/run_shilla_pipeline.py                      # 전체(오늘 날짜로 수집→리포트)
  python3 scripts/run_shilla_pipeline.py --date 2026-06-06    # 날짜 지정
  python3 scripts/run_shilla_pipeline.py --stage collect      # 수집만 [200]
  python3 scripts/run_shilla_pipeline.py --stage analyze --skip-crawl --date 2026-06-06
  python3 scripts/run_shilla_pipeline.py --stage report --date 2026-06-06   # 기존 분석본으로 리포트만 [203]
  python3 scripts/run_shilla_pipeline.py --smoke             # 배선 점검(컴파일만, 라이브 호출 없음)
"""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import py_compile
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve()
ROOT = HERE.parents[1]
PY = sys.executable or "python3"
SD = "pipelines/shilla_dutyfree"


def _today() -> str:
    # KST 기준일(서버 UTC 가정 +9h). 날짜만 쓰므로 충분.
    return (_dt.datetime.now(_dt.timezone.utc) + _dt.timedelta(hours=9)).date().isoformat()


def whisky_csv(date: str) -> str:
    return str(ROOT / "data" / "shilla-dutyfree" / f"신라면세_위스키_{date}.csv")


def steps_for(stage: str, date: str) -> list[dict]:
    """스테이지 → 실행 스텝 목록(의존성 순서). 각 스텝: label/routine/rel/extra/live/critical."""
    dt = ["--date", date]
    collect = [
        dict(label="신라면세 수집(AJAX)", routine=200, rel=f"{SD}/crawl_shilla_whisky.py",
             extra=dt, live=True, critical=True),
    ]
    process = [
        dict(label="피트 필터", routine=201, rel=f"{SD}/filter_peated.py",
             extra=[whisky_csv(date)], live=False, critical=True),
    ]
    # 분석: 의존성 순서 — score_peated → (compare_intl, price_bands) ; analyze → (recommend, budget) ; style ; find_cheaper
    analyze = [
        dict(label="피트 매력도(라이브 재조회)", routine=202, rel=f"{SD}/score_peated_attractiveness.py",
             extra=[], live=True, critical=False),
        dict(label="피트 해외비교(HK/JP/TW)", routine=202, rel=f"{SD}/compare_international.py",
             extra=[], live=False, critical=False),
        dict(label="피트 원화구간(코스트코)", routine=202, rel=f"{SD}/price_krw_bands.py",
             extra=[], live=False, critical=False),
        dict(label="스타일 매력도(셰리·버번)", routine=202, rel=f"{SD}/score_style_attractiveness.py",
             extra=[], live=False, critical=False),
        dict(label="국내가 교차 매력도(엔진)", routine=202, rel=f"{SD}/analyze_attractiveness.py",
             extra=dt, live=False, critical=True),
        dict(label="구매추천 5종(CMPA-134)", routine=202, rel=f"{SD}/recommend_purchase.py",
             extra=[], live=False, critical=False),
        dict(label="예산대별 TOP", routine=202, rel=f"{SD}/budget_top_picks.py",
             extra=dt, live=False, critical=False),
        dict(label="국내최저대비 저렴(데일리샷 라이브)", routine=202, rel=f"{SD}/find_cheaper_than_domestic.py",
             extra=dt, live=True, critical=False),
    ]
    report = [
        dict(label="피트 리포트(md)", routine=203, rel=f"{SD}/build_report.py",
             extra=[], live=False, critical=True),
        dict(label="발행 HTML(생성일 표기)", routine=203, rel=f"{SD}/build_report_html.py",
             extra=[], live=False, critical=True),
        dict(label="배포(deploy 재생성)", routine=203, rel="scripts/build_deploy.py",
             extra=[], live=False, critical=True),
    ]
    mapping = {"collect": collect, "process": process, "analyze": analyze, "report": report}
    if stage == "all":
        return collect + process + analyze + report
    return mapping[stage]


def run_step(s: dict, env: dict, pace: float) -> dict:
    script = ROOT / s["rel"]
    name = f"[{s['routine']}] {s['label']}"
    if not script.exists():
        print(f"[STEP-MISS] {name}: 스크립트 없음 {s['rel']}", flush=True)
        return {**s, "exit": 127, "ok": False, "sec": 0}
    cmd = [PY, str(script)] + s["extra"]
    tag = " ·LIVE" if s["live"] else ""
    print(f"\n{'='*70}\n[STEP]{tag} {name}\n  $ {' '.join(cmd)}\n{'='*70}", flush=True)
    if s["live"] and pace > 0:
        time.sleep(pace)  # LIVE 호출 전 매너 간격(429 회피)
    t0 = time.time()
    proc = subprocess.run(cmd, cwd=str(ROOT), env=env)
    sec = time.time() - t0
    ok = proc.returncode == 0
    print(f"[STEP-END] {name}: exit {proc.returncode} ({sec:.0f}s)", flush=True)
    return {**s, "exit": proc.returncode, "ok": ok, "sec": round(sec)}


def smoke(stage: str, date: str) -> int:
    print(f"[shilla] smoke(배선 점검) stage={stage} date={date} — 라이브 호출 없음")
    rels = []
    for st in (["collect", "process", "analyze", "report"] if stage == "all" else [stage]):
        rels += [s["rel"] for s in steps_for(st, date)]
    seen, ok_all = set(), True
    for rel in rels:
        if rel in seen:
            continue
        seen.add(rel)
        script = ROOT / rel
        if not script.exists():
            print(f"  [MISS] {rel}"); ok_all = False; continue
        try:
            py_compile.compile(str(script), doraise=True)
            print(f"  [OK]   {rel}")
        except py_compile.PyCompileError as e:
            print(f"  [FAIL] {rel}: {e}"); ok_all = False
    print(f"\nPIPELINE RESULT (smoke): {'GREEN ✅' if ok_all else 'RED ❌'} ({len(seen)} scripts)")
    return 0 if ok_all else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="신라면세 위스키 리포트 파이프라인 오케스트레이터")
    ap.add_argument("--stage", choices=["collect", "process", "analyze", "report", "all"],
                    default="all", help="실행할 스테이지(기본 all)")
    ap.add_argument("--date", default=None, help="기준일 YYYY-MM-DD(기본 오늘 KST). 전 스텝에 SHILLA_DATE 주입")
    ap.add_argument("--skip-crawl", action="store_true", help="수집 생략(기존 <date> CSV 재사용)")
    ap.add_argument("--strict", action="store_true", help="분석 개별 스텝 실패도 hard-fail")
    ap.add_argument("--pace", type=float, default=3.0, help="LIVE 스텝 전 대기초(429 회피, 기본 3)")
    ap.add_argument("--smoke", action="store_true", help="배선 점검만(컴파일, 라이브 없음)")
    a = ap.parse_args()

    date = a.date or _today()
    if a.smoke:
        return smoke(a.stage, date)

    env = dict(os.environ, SHILLA_DATE=date)
    steps = steps_for(a.stage, date)
    if a.skip_crawl:
        steps = [s for s in steps if s["routine"] != 200]

    # 가드레일(CMPA-235): report 스테이지는 <date> 신라 오늘자 raw CSV 에 의존.
    # report 스텝이 '선행 collect 없이' 도는 경우에만 검사 → raw 가 없으면 stale-date
    # 리포트가 조용히 생성되는 것을 막는다(요청 date 의 raw 가 있을 때만 그 date 로 진행).
    has_report = any(s["routine"] == 203 for s in steps)
    has_collect = any(s["routine"] == 200 for s in steps)
    if has_report and not has_collect and not Path(whisky_csv(date)).exists():
        if a.skip_crawl:
            print(f"\n{'!'*70}")
            print(f"[GUARD-FAIL] 리포트 의존성 위반(CMPA-235): {date} 신라 오늘자 CSV 없음")
            print(f"  필요: {whisky_csv(date)}")
            print(f"  --skip-crawl 이므로 자동 수집 불가 → stale-date 리포트 방지 위해 중단.")
            print(f"  조치: --skip-crawl 을 빼고 다시 실행(자동 collect→…→report) 하거나, 먼저")
            print(f"        python3 {SD}/crawl_shilla_whisky.py {date}  로 수집 후 재실행.")
            print('!'*70, flush=True)
            return 2
        print(f"\n[GUARD] {date} 신라 raw CSV 없음 → collect→process→analyze 선행 보강 후 "
              f"report (stale-date 방지, CMPA-235)", flush=True)
        prefix: list[dict] = []
        for st in ("collect", "process", "analyze"):
            for s in steps_for(st, date):
                if not any(s["rel"] == x["rel"] for x in prefix):
                    prefix.append(s)
        steps = prefix + steps

    print(f"[shilla] stage={a.stage} date={date} "
          f"{'(--skip-crawl)' if a.skip_crawl else ''}")
    print(f"[shilla] SHILLA_DATE={date} 주입 · LIVE 스텝 pace={a.pace}s · "
          f"간헐 정본(fx/normalized/해외POC)은 읽기만(별도 루틴 갱신)")

    results: list[dict] = []
    for s in steps:
        r = run_step(s, env, a.pace)
        results.append(r)
        if not r["ok"]:
            if r["routine"] == 200:  # 수집 = 뿌리 → 항상 hard-fail
                print("  ! 수집 실패 = 뿌리 데이터 없음 → 파이프라인 중단", flush=True)
                return _summary(results, date, hard_stop=True)
            if s["critical"] or a.strict:
                print(f"  ! 핵심 스텝 실패({s['label']}) → 중단"
                      f"{' (--strict)' if (a.strict and not s['critical']) else ''}", flush=True)
                return _summary(results, date, hard_stop=True)
            print(f"  ! 스텝 실패({s['label']}) → 경고 후 계속(부분 산출)", flush=True)

    # 런 아카이브(CMPA-151/293): 정본(data/·reports/) latest 는 그대로 두고, 이번 런이
    # 만든 <date> 산출물 사본을 runs/<run_date>/<asset>/ 로 추가 수집(날짜별 누적). deploy 는
    # cross-asset 이라 build_deploy 가 runs/<run_date>/deploy/ 를 별도로 채운다. 추가 복사라
    # 실패해도 파이프라인을 막지 않는다(경고만).
    _archive_run(date, results)

    return _summary(results, date)


def _archive_run(date: str, results: list[dict]) -> None:
    """이번 런 산출물 사본을 runs/<date>/{shilla_data,shilla_report}/ 로 모은다(정본 불변)."""
    if not any(r["ok"] for r in results):
        return  # 아무것도 성공 못한 런은 모을 것이 없음
    try:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from pipelines.common.run_archive import (  # noqa: E402
            collect_run_outputs, SHILLA_ASSET_OUTPUTS)
        res = collect_run_outputs(date, assets=SHILLA_ASSET_OUTPUTS, glob_all=True,
                                  manifest_name="_manifest_shilla.json")
        summary = ", ".join(f"{a}:{len(f)}" for a, f in res["assets"].items())
        print(f"\n[run-archive·CMPA-151] runs/{res['run_date']}/ — "
              f"{res['copied']} files ({summary})", flush=True)
    except Exception as e:  # 아카이브는 부가 기능 → 정본/리포트에 영향 없이 경고만
        print(f"[run-archive] 경고: 아카이브 건너뜀(정본 영향 없음): {e}", flush=True)


def _summary(results: list[dict], date: str, hard_stop: bool = False) -> int:
    print(f"\n{'#'*70}\nPIPELINE RESULT (신라면세 / {date}):")
    for r in results:
        flag = "PASS" if r["ok"] else "FAIL"
        print(f"  [{flag}] [{r['routine']}] {r['label']:30s} exit {r['exit']}  {r['sec']}s")
    crit = [r for r in results if r["critical"]]
    crit_ok = bool(crit) and all(r["ok"] for r in crit) and not hard_stop
    soft_fail = [r for r in results if not r["ok"] and not r["critical"]]
    if soft_fail:
        print(f"  [note] 비핵심 스텝 {len(soft_fail)}건 실패(부분 산출): "
              + ", ".join(r["label"] for r in soft_fail))
    print(f"PIPELINE RESULT: {'GREEN ✅' if crit_ok else 'RED ❌'}")
    print('#'*70, flush=True)
    return 0 if crit_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
