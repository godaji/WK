#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
해외 위스키 소매가 + 환율 주기 수집 오케스트레이터 — CMPA-30.

한 번의 실행으로 (1) 환율 스냅샷 (2) 홍콩 Shopify (3) 일본 Rakuten 을 묶어 돌리고,
실행 매니페스트(JSON)를 남긴다. 주간~격주 루틴의 단일 진입점.

  python3 pipelines/overseas/collect_overseas.py

단계
  1) FX   : open.er-api.com 에서 HKD/JPY→KRW cross-rate 산출 → data/whisky-prices/fx/
            (이번 실행에서 산출한 라이브 환율을 HK/JP 환산 입력으로 그대로 전달)
  2) HK   : Caskells 외 Shopify /products.json 라이브 크롤 → {실행일}_hk_whisky_poc.csv
  3) JP   : 일본 주류 Shopify /products.json 라이브 크롤(키 불필요) → {실행일}_jp_shopify_poc.csv.
            CMPA-52/CMPA-53 에서 Rakuten(키 대기, CMPA-47 cancelled) 자리를 키리스 Shopify 로 교체.

가드레일(메모리 ssandi/ dailyshot/ cmpa9): 본 수집은 내부 R&D·측정용. 공개/상업 표면
재배포는 CMPA-15 상위 이슈의 법무·소싱 가드레일 통과 후에만. 스크립트는 측정만 한다.

종료코드: HK 가 0행이면 비정상(2). JP fixture/LIVE 실패는 경고(매니페스트에 기록)하되
환율·HK 가 성공이면 0. 매니페스트에 단계별 상태/행수/사용환율을 남긴다.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(ROOT, "data", "whisky-prices")
FX_DIR = os.path.join(DATA, "fx")

sys.path.insert(0, ROOT)
from pipelines.common.fx_fetch import fx_snapshot, write_snapshot  # noqa: E402
from pipelines.common.dated import kst_today  # noqa: E402


def _count_csv_rows(path: str) -> int:
    if not os.path.exists(path):
        return 0
    with open(path, encoding="utf-8-sig") as f:
        return max(0, sum(1 for _ in f) - 1)  # minus header


def run_step(label: str, cmd: list[str], env_extra: dict | None = None) -> dict:
    env = dict(os.environ)
    if env_extra:
        env.update(env_extra)
    print(f"\n=== [{label}] {' '.join(cmd)} ===", flush=True)
    try:
        p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True,
                           text=True, timeout=600)
        tail = (p.stdout or "")[-600:] + (p.stderr or "")[-600:]
        print(tail, flush=True)
        return {"label": label, "returncode": p.returncode,
                "ok": p.returncode == 0, "tail": tail.strip()[-800:]}
    except Exception as e:  # noqa: BLE001
        print(f"  ! {label} failed: {type(e).__name__} {e}", flush=True)
        return {"label": label, "returncode": -1, "ok": False, "tail": str(e)}


def main():
    asof = os.environ.get("COLLECT_DATE") or os.environ.get("FX_ASOF") or ""
    manifest = {"asof": asof, "steps": {}, "outputs": {}}

    # ---- 1) FX snapshot (live) ----
    print("=== [fx] open.er-api.com HKD/JPY -> KRW ===", flush=True)
    try:
        snap = fx_snapshot(["HKD", "JPY"])
        csv_path, json_path = write_snapshot(snap, FX_DIR)
        # NOTE: FX rate as-of (snap["asof"]) is recorded separately in manifest["fx"].
        # 'asof' here is the COLLECTION/RUN date — it must NOT inherit the FX rate date,
        # else each run gets stamped one day behind (FX API publishes prior-day asof in KST)
        # and the per-run snapshot collides instead of accumulating. CMPA-156/CMPA-391.
        hkd = snap["krw_per"]["HKD"]
        jpy = snap["krw_per"]["JPY"]
        manifest["fx"] = {"asof": snap["asof"], "HKD_KRW": hkd, "JPY_KRW": jpy,
                          "source": snap["source"]}
        manifest["steps"]["fx"] = {"ok": True}
        manifest["outputs"]["fx_snapshot_csv"] = os.path.relpath(csv_path, ROOT)
        manifest["outputs"]["fx_latest_json"] = os.path.relpath(json_path, ROOT)
        print(f"  HKD->KRW={hkd}  JPY->KRW={jpy}  asof={snap['asof']}", flush=True)
    except Exception as e:  # noqa: BLE001
        print(f"  ! FX fetch failed: {e}", flush=True)
        manifest["steps"]["fx"] = {"ok": False, "error": str(e)}
        # FX 없이는 환산 불가 — 메모리 기본값으로 폴백(주의 기록).
        hkd, jpy = 192.27, 9.46
        manifest["fx"] = {"asof": asof, "HKD_KRW": hkd, "JPY_KRW": jpy,
                          "source": "FALLBACK (memory defaults — FX API unreachable)"}

    # 실행일은 절대 'unknown' 으로 두지 않는다(파일명 추적 불가 방지). CMPA-38.
    # asof = 이번 실행의 '실행일'(run date, KST). 데이터의 '월'(asof[:7])과는 별개 개념.
    asof = asof or kst_today()
    manifest["asof"] = asof

    # ---- 2) Hong Kong (Shopify, live) ----
    # 정본 파일명은 데이터 '월' 유지(다운스트림 안정 = latest 포인터). 하위 수집기가
    # 쓴 직후 _runs/ 에 '실행일' 스냅샷을 남겨 주간/격주 재실행이 누적된다. CMPA-38.
    hk_out = os.path.join(DATA, f"{asof[:7]}_hk_whisky_poc.csv")
    hk = run_step("hk", [sys.executable, os.path.join("pipelines", "hk-whisky",
                  "crawl_hk_whisky.py"), str(hkd), asof, hk_out])
    hk_rows = _count_csv_rows(hk_out)
    hk["rows"] = hk_rows
    manifest["steps"]["hk"] = hk
    manifest["outputs"]["hk_csv"] = os.path.relpath(hk_out, ROOT)

    # ---- 3) Japan (Shopify /products.json, live; 키 불필요) ----
    # CMPA-52/CMPA-53: Rakuten(applicationId 대기, CMPA-47 cancelled) 자리를 키리스 Shopify 로 교체.
    # 인자: collect_jp_shopify.py <1JPY->KRW> <asof(YYYY-MM-DD)> <out.csv>
    jp_out = os.path.join(DATA, "jp", f"{asof[:7]}_jp_shopify_poc.csv")
    jp_mode = "LIVE"
    jp = run_step("jp", [sys.executable, os.path.join("pipelines", "jp_shopify",
                  "collect_jp_shopify.py"), str(jpy), asof, jp_out])
    jp_rows = _count_csv_rows(jp_out)
    jp["rows"] = jp_rows
    jp["mode"] = jp_mode
    manifest["steps"]["jp"] = jp
    manifest["outputs"]["jp_csv"] = os.path.relpath(jp_out, ROOT)

    # ---- write manifest ----
    man_path = os.path.join(DATA, "_overseas_last_run.json")
    with open(man_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    # ---- summary ----
    print("\n" + "=" * 60)
    print("CMPA-30 해외 수집 — 실행 요약")
    print("=" * 60)
    print(f"asof              : {asof}")
    print(f"FX HKD->KRW       : {hkd}   ({manifest['fx']['source']})")
    print(f"FX JPY->KRW       : {jpy}")
    print(f"HK rows           : {hk_rows}  -> {os.path.relpath(hk_out, ROOT)}  "
          f"[{'OK' if hk['ok'] else 'FAIL'}]")
    print(f"JP rows ({jp_mode:7}) : {jp_rows}  -> {os.path.relpath(jp_out, ROOT)}  "
          f"[{'OK' if jp['ok'] else 'FAIL'}]")
    print(f"manifest          : {os.path.relpath(man_path, ROOT)}")
    print("=" * 60)

    # exit non-zero only if HK (the live commercial-grade source) produced nothing
    if hk_rows == 0 or not hk["ok"]:
        print("[ERROR] HK live crawl produced 0 rows or failed — investigate.", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
