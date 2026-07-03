#!/usr/bin/env python3
"""CMPA-374 (보드 후속) — 신라면세 위스키 전체에 대해 데일리샷 현재 최저가(페이지 floor,
면세/해외 제외, '대표가 아님')를 구해 저장하고 면세가와 비교, '면세<국내최저' 종수를 재점검.

보드 지시: "649종에 대해서 데일리샷 현재 최저가를 구해볼래? 이때 duty free 데이터는 제외한
최저가(대표가 아님)를 구해서 저장한 뒤, 면세가랑 비교해봐. 면세가가 국내 최저보다 싼 기회가
75종이 확실한지 한번만 더 점검."

기존 `find_cheaper_than_domestic.py` 의 매칭 엔진(브랜드+숙성+디스크립터 가드, 인디/희귀 제외,
면세/해외 리스팅 제외, CMPA-344 제품페이지 전국 최저 셀러가)을 **그대로 재사용**하되,
차이점:
  1) ≤50만원 KRW_CAP **제거** — 면세가>0 인 전체(649종) 스윕(>50만원 107종도 포함).
  2) **데일리샷 페이지 floor 를 1차 국내최저 기준**으로 명시 비교(보드 요구). 보유 DB 값도
     함께 기록해 기존 리포트(min(DB,DS)=75종) 와 정합 대조.
  3) 매칭 실패(국내가 미확인) 행도 전부 저장 — 커버리지 투명화.
  4) **체크포인트 재개**: 출력 CSV 에 이미 있는 위스키명은 건너뜀(중간 종료/재실행 안전).
     진행 로그는 stdout(파일 리다이렉트) — 장시간 작업이라 detached 실행 권장.

출력:
  data/shilla-dutyfree/검증_데일리샷floor_<date>.csv   (위스키별 면세 vs 데일리샷 floor)
  data/shilla-dutyfree/검증_데일리샷floor_<date>.summary.json  (집계: 병당/100ml 면세<국내 종수)
"""
import argparse
import csv
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, os.path.join(ROOT, "pipelines", "shilla_dutyfree"))

import enrich_dailyshot as ds
import find_cheaper_than_domestic as fc

FIELDS = [
    "위스키명", "브랜드", "면세_USD", "면세_KRW", "면세용량_ml", "면세_₩100ml",
    "데일리샷floor_KRW", "데일리샷용량_ml", "데일리샷_₩100ml", "데일리샷셀러", "데일리샷매칭명",
    "보유DB_KRW", "국내최저_KRW(min)", "국내최저출처",
    "면세더쌈_병당", "절감_병당_KRW", "면세더쌈_100ml", "절감_100ml_%",
    "구매가능", "상품URL",
]


def load_done(path):
    done = set()
    if os.path.exists(path):
        try:
            for r in csv.DictReader(open(path, encoding="utf-8-sig")):
                if r.get("위스키명"):
                    done.add(r["위스키명"])
        except Exception:
            pass
    return done


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    ap.add_argument("--pace", type=float, default=0.6)
    ap.add_argument("--limit", type=int, default=0, help="디버그: 앞 N행만")
    args = ap.parse_args()

    usd_krw, fx_asof = fc.load_fx()
    db = fc.load_domestic_db()

    sp = os.path.join(ROOT, "data", "shilla-dutyfree",
                      f"신라면세_위스키_{args.date}.csv")
    rows = list(csv.DictReader(open(sp, encoding="utf-8-sig")))

    out_csv = os.path.join(ROOT, "data", "shilla-dutyfree",
                           f"검증_데일리샷floor_{args.date}.csv")
    done = load_done(out_csv)
    fresh = not os.path.exists(out_csv)
    fout = open(out_csv, "a", newline="", encoding="utf-8-sig")
    writer = csv.DictWriter(fout, fieldnames=FIELDS)
    if fresh:
        writer.writeheader()
        fout.flush()

    # 면세가>0 전체(캡 없음)
    cands = []
    for r in rows:
        try:
            usd = float(r["할인가_USD"])
        except (ValueError, TypeError):
            continue
        if usd <= 0:
            continue
        r["_usd"] = usd
        r["_krw"] = round(usd * usd_krw)
        r["_vol"] = fc.vol_of(r["위스키명"])
        cands.append(r)
    if args.limit:
        cands = cands[: args.limit]

    kw_cache, page_cache = {}, {}
    n_total = len(cands)
    n_done = 0
    t0 = time.time()
    print(f"[start] {args.date} 면세가>0 {n_total}종 · 이미완료 {len(done)}종 · "
          f"환율 {usd_krw:,.2f}(asof {fx_asof})", flush=True)

    for i, r in enumerate(cands):
        name = r["위스키명"]
        if name in done:
            continue
        # A) 보유 DB floor
        a = fc.db_lookup(name, db)
        # B) 데일리샷 라이브 → 제품 페이지 전국 최저 셀러가(면세/해외 제외)
        b = None
        kw = fc.ds_keyword(r["브랜드"], name)
        if kw:
            if kw not in kw_cache:
                time.sleep(args.pace)
                try:
                    kw_cache[kw] = ds.search(kw)
                except Exception as e:
                    kw_cache[kw] = []
                    print(f"  [search 실패 {kw}: {e}]", flush=True)
            b = fc.ds_best(r["브랜드"], name, kw_cache[kw])
            if b and b.get("top_product_id"):
                tpid = b["top_product_id"]
                if tpid not in page_cache:
                    time.sleep(args.pace)
                    try:
                        page_cache[tpid] = ds.item_page_price(tpid)
                    except Exception as e:
                        page_cache[tpid] = None
                        print(f"  [page 실패 {tpid}: {e}]", flush=True)
                pp = page_cache[tpid]
                if pp and pp.get("price"):
                    b["ds_search_price"] = b["price"]
                    b["price"] = pp["price"]      # floor = 페이지 최저 셀러가(대표가 아님)
                    b["seller"] = pp.get("seller")

        ds_floor = round(b["price"]) if b else None
        ds_vol = b["vol"] if b else None
        ds_p100 = round(ds_floor / max(ds_vol, 1) * 100) if ds_floor else None
        db_floor = round(a["price"]) if a else None
        # 국내최저(min) = 보유DB·데일리샷 중 100ml단가 최저(기존 리포트 방법론과 동일)
        opts = [x for x in (a, b) if x]
        dom = (min(opts, key=lambda x: x["price"] / max(x["vol"], 1))
               if opts else None)
        dom_min = round(dom["price"]) if dom else None
        dom_src = dom["src"] if dom else ""

        duty_p100 = r["_krw"] / r["_vol"] * 100
        # 면세 vs 데일리샷 floor (보드 1차 요구)
        cheaper_bottle = ds_floor is not None and r["_krw"] < ds_floor
        save_bottle = (ds_floor - r["_krw"]) if ds_floor is not None else ""
        cheaper_100 = ds_p100 is not None and round(duty_p100) < ds_p100
        save_100 = (round((ds_p100 - duty_p100) / ds_p100 * 100, 1)
                    if ds_p100 else "")

        writer.writerow({
            "위스키명": name, "브랜드": r["브랜드"],
            "면세_USD": r["_usd"], "면세_KRW": r["_krw"],
            "면세용량_ml": r["_vol"], "면세_₩100ml": round(duty_p100),
            "데일리샷floor_KRW": ds_floor if ds_floor is not None else "",
            "데일리샷용량_ml": ds_vol if ds_vol is not None else "",
            "데일리샷_₩100ml": ds_p100 if ds_p100 is not None else "",
            "데일리샷셀러": (b or {}).get("seller", "") if b else "",
            "데일리샷매칭명": (b or {}).get("name", "") if b else "",
            "보유DB_KRW": db_floor if db_floor is not None else "",
            "국내최저_KRW(min)": dom_min if dom_min is not None else "",
            "국내최저출처": dom_src,
            "면세더쌈_병당": "Y" if cheaper_bottle else "N",
            "절감_병당_KRW": save_bottle,
            "면세더쌈_100ml": "Y" if cheaper_100 else "N",
            "절감_100ml_%": save_100,
            "구매가능": r.get("구매가능", ""),
            "상품URL": r.get("상품URL", ""),
        })
        fout.flush()
        n_done += 1
        if n_done % 20 == 0:
            el = time.time() - t0
            print(f"...{i + 1}/{n_total} 처리 (신규 {n_done}, 키워드캐시 "
                  f"{len(kw_cache)}, 페이지캐시 {len(page_cache)}, {el:.0f}s)",
                  flush=True)

    fout.close()

    # 집계(전체 CSV 재독 — 재개 누적 포함)
    allrows = list(csv.DictReader(open(out_csv, encoding="utf-8-sig")))
    matched = [r for r in allrows if r.get("데일리샷floor_KRW")]
    ds_cheaper_bottle = [r for r in matched if r.get("면세더쌈_병당") == "Y"]
    ds_cheaper_100 = [r for r in matched if r.get("면세더쌈_100ml") == "Y"]
    buyA = [r for r in ds_cheaper_bottle if (r.get("구매가능") or "").upper() == "Y"]
    summary = {
        "date": args.date, "fx_usd_krw": usd_krw, "fx_asof": fx_asof,
        "면세가>0_전체": n_total,
        "데일리샷floor_확인": len(matched),
        "면세더쌈_병당(데일리샷floor)": len(ds_cheaper_bottle),
        "그중_구매가능": len(buyA),
        "면세더쌈_100ml(데일리샷floor)": len(ds_cheaper_100),
        "비교": "기존 리포트 75종(병당, ≤50만원·min(DB,DS) 기준)과 대조",
    }
    sp_json = out_csv.replace(".csv", ".summary.json")
    json.dump(summary, open(sp_json, "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("\n[summary]", json.dumps(summary, ensure_ascii=False, indent=2),
          flush=True)
    print(f"-> {out_csv}\n-> {sp_json}", flush=True)


if __name__ == "__main__":
    main()
