#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CMPA-345 — 데일리샷 과거 데이터 dirty 표식.

배경: 2026-06-13 면세(service_type==5) 셀러 제외 수정(CMPA-321/322, 959f073/7ab6496)
이전의 데일리샷 스냅샷은 면세가(세금 0)가 국내 최저 floor 에 섞여 들어가 일부 제품의
국내 최저가를 실제보다 낮게(오염) 적재했다. 본 스크립트는 그 오염 구간을 비파괴적으로
표식한다(CMPA-156 데이터 관리 3원칙 — 삭제/덮어쓰기 금지, 누적·메타 부착).

산출:
1) data/whisky-prices/_dailyshot_dirty.json  — 기계가독 dirty 매니페스트(정본)
2) 2026-05_dailyshot.csv 의 오염 행 '비고' 칸에 `⚠️DIRTY(면세오염의심,CMPA-345)` 가산(가격값은 보존)

판별: 면세 제외 수정 이후의 clean 기준가(2026-06-14, 없으면 2026-06-13) 대비
pre-fix 가격이 90% 미만이면 면세 오염 고신뢰로 본다(정상 시세변동은 통상 ±10% 이내, 오염은 −20~−80%).
"""
import csv, json, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WP = os.path.join(ROOT, "data", "whisky-prices")
THRESH = 0.90
CLEAN_CUTOVER = "2026-06-13"

# pre-fix(=오염 가능) 스냅샷
PREFIX_RUNS = {
    "2026-05-30": "_runs/2026-05_dailyshot__run2026-05-30.csv",
    "2026-05-31": "_runs/2026-05_dailyshot__run2026-05-31.csv",
    "2026-06-01": "_runs/2026-06_dailyshot__run2026-06-01.csv",
    "2026-06-08": "_runs/2026-06_dailyshot__run2026-06-08.csv",
    "2026-06-10": "_runs/2026-06_dailyshot__run2026-06-10.csv",
    "2026-06-11": "_runs/2026-06_dailyshot__run2026-06-11.csv",
    "2026-06-12": "_runs/2026-06_dailyshot__run2026-06-12.csv",
}
CANONICAL_DIRTY = "2026-05_dailyshot.csv"  # May 월 정본 — pre-fix 재수집 안됨
CLEAN_REFS = ["_runs/2026-06_dailyshot__run2026-06-14.csv",
              "_runs/2026-06_dailyshot__run2026-06-13.csv"]


def load_prices(rel):
    d = {}
    with open(os.path.join(WP, rel), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            p = r["가격_KRW"].strip()
            d[r["위스키명"]] = int(p) if p else None
    return d


def main():
    refs = [load_prices(r) for r in CLEAN_REFS]
    ref = {}
    for w in set().union(*[set(r) for r in refs]):
        for r in refs:
            if r.get(w):
                ref[w] = r[w]; break

    def is_dirty(name, price):
        return price and ref.get(name) and price < ref[name] * THRESH

    dirty_products = {}   # name -> {clean_ref, polluted_dates:[]}
    dirty_files = []
    for date, rel in PREFIX_RUNS.items():
        d = load_prices(rel)
        cells = [w for w, v in d.items() if is_dirty(w, v)]
        for w in cells:
            dp = dirty_products.setdefault(w, {"clean_ref": ref[w], "polluted_dates": [], "polluted_prices": {}})
            dp["polluted_dates"].append(date)
            dp["polluted_prices"][date] = d[w]
        dirty_files.append({
            "path": f"data/whisky-prices/{rel}",
            "date": date,
            "priced": sum(1 for v in d.values() if v),
            "dirty_cells": len(cells),
        })

    # May 정본
    mc = load_prices(CANONICAL_DIRTY)
    mc_dirty = [w for w, v in mc.items() if is_dirty(w, v)]
    dirty_files.append({
        "path": f"data/whisky-prices/{CANONICAL_DIRTY}",
        "date": "2026-05 (월 정본)",
        "priced": sum(1 for v in mc.values() if v),
        "dirty_cells": len(mc_dirty),
    })

    manifest = {
        "issue": "CMPA-345",
        "generated": "2026-06-14",
        "title": "데일리샷 과거 데이터 dirty 표식 (면세 floor 오염)",
        "reason": ("2026-06-13 면세(service_type==5) 셀러 제외 수정(CMPA-321/322, "
                   "commit 959f073/7ab6496) 이전 스냅샷은 면세가(세금 0)가 국내 최저 floor 에 "
                   "섞여 일부 제품 국내최저가를 실제보다 낮게 오염시켰다."),
        "clean_cutover_date": CLEAN_CUTOVER,
        "detection_method": (f"pre-fix 가격 < clean 기준가(2026-06-14, fallback 2026-06-13)의 {int(THRESH*100)}% 이면 "
                              "면세오염 고신뢰. 정상 시세변동(±10%)과 오염(−20~−80%)을 분리."),
        "clean_files_from_cutover": [
            "data/whisky-prices/2026-06_dailyshot.csv (06-13 재수집 정본, clean)",
            "data/whisky-prices/_runs/2026-06_dailyshot__run2026-06-13.csv 이후",
        ],
        "caveats": [
            "2026-06-11 run 은 부분 스냅샷(가격 28건, 평소 ~90건) — 불완전 크롤, dirty 와 별개로 주의.",
            "오염은 제품·일자별로 간헐적(검색결과에 면세 셀러가 떴는지에 따라). 같은 제품도 일부 날만 오염.",
            "임계값 미만 소폭 오염은 보수적으로 누락될 수 있음(고신뢰 우선).",
        ],
        "dirty_files": dirty_files,
        "distinct_dirty_products": len(dirty_products),
        "dirty_products": [
            {"name": w, "clean_ref_krw": v["clean_ref"],
             "polluted_run_dates": sorted(v["polluted_dates"]),
             "polluted_prices_krw": v["polluted_prices"]}
            for w, v in sorted(dirty_products.items(), key=lambda x: -x[1]["clean_ref"])
        ],
    }
    out = os.path.join(WP, "_dailyshot_dirty.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)
    print(f"[manifest] {out}  ({len(dirty_files)} files, {len(dirty_products)} dirty products)")

    # May 정본 비고 칸에 비파괴 가산 표식
    if "--annotate-may" in sys.argv:
        path = os.path.join(WP, CANONICAL_DIRTY)
        rows = []
        with open(path, encoding="utf-8-sig") as f:
            rd = csv.DictReader(f); fields = rd.fieldnames
            for r in rd:
                if r["위스키명"] in mc_dirty and "DIRTY" not in r.get("비고", ""):
                    tag = "⚠️DIRTY(면세오염의심,CMPA-345)"
                    r["비고"] = f"{r['비고']} / {tag}".strip(" /") if r.get("비고") else tag
                rows.append(r)
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            wr = csv.DictWriter(f, fieldnames=fields); wr.writeheader(); wr.writerows(rows)
        print(f"[annotate] {path}  ({len(mc_dirty)} rows tagged)")


if __name__ == "__main__":
    main()
