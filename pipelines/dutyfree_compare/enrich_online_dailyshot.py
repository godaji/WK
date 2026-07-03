#!/usr/bin/env python3
"""면세 비교 제품을 데일리샷 온라인 전국 최저가로 보강(CMPA-650, 보드 2026-06-28).

배경: 기존 데일리샷 수집(`pipelines/dailyshot/crawl_dailyshot.py`)은 **우리가 트레이더스/
코스트코에서 추적 중인 ~207종**만 검색한다(IN_SCOPE 게이트). 그래서 면세점엔 있지만
트레이더스/코스트코엔 없는 제품(예: 부나하벤 크루아모나 1L, dailyshot item 4611)은
데일리샷에 실제로 있어도 우리 데이터엔 '소매가 없음'으로 나온다.

이 스크립트는 **면세 비교 제품명**으로 데일리샷을 직접 검색해 제품 페이지 전국 최저
셀러가(item_page_price, 면세/해외 제외 — CMPA-321/344)를 가져와 캐시에 누적한다.
build_compare 가 이 캐시를 '데일리샷(온라인)' 국내 소스로 병합한다.

- 멱등/재개: 캐시(`data/whisky-prices/_dailyshot_compare_<date>.csv`)에 이미 있으면 건너뜀.
  중간에 끊겨도 다음 실행이 이어서 채운다(행 단위 즉시 flush).
- 매칭 가드: 이름 정규화 부분일치 + 용량(±) + CMPA-177 토큰(년수/CS/피티드/셰리/버번) 비대칭 제외.
- 면세 제외는 item_page_price(_walk_page_price, price_usd>0 제외)가 보장.
"""
import argparse
import csv
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
sys.path.insert(0, os.path.join(ROOT, "pipelines", "shilla_dutyfree"))
import enrich_dailyshot as ed                       # noqa: E402  search/item_page_price
from build_compare import (                          # noqa: E402  매칭 가드 재사용
    norm, extract_volume_ml, _cmpa177_ok, _make_key,
)

CACHE = os.path.join(ROOT, "data", "whisky-prices", "_dailyshot_compare_2026-06-28.csv")
FIELDS = ["제품명", "_k1", "ds_price_krw", "ds_seller", "ds_vol_ml", "ds_item_id",
          "ds_name", "looked_up_at"]


def _vol_ok(a, b):
    if not a or not b:
        return True
    lo, hi = sorted((a, b))
    return hi / lo <= 1.6        # 700↔1000 등 변형 허용, 미니/매그넘 배제는 호출측


import re as _re
_VOLTOK = _re.compile(r"\d+(?:\.\d+)?(?:ml|l|리터|밀리)")


def _novol(s):
    """norm() 결과에서 용량 토큰 제거(1000ml/1l 차이로 부분일치 실패 방지)."""
    return _VOLTOK.sub("", s)


def best_ds(name, cands):
    """검색 후보 중 이름·용량·CMPA-177 가드 통과하는 최저 페이지가 후보. (item_id, ds_name, vol)."""
    nm = norm(name)
    nmv = _novol(nm)        # 용량 제거 비교용
    tvol = extract_volume_ml(name)
    best = None
    for c in cands:
        dsname = c.get("name") or c.get("title") or ""
        tpid = c.get("top_product_id") or c.get("id") or c.get("product_id")
        if not tpid:
            continue
        dn = norm(dsname)
        dnv = _novol(dn)
        # 용량 제거 후 양방향 부분일치(짧은 쪽이 긴 쪽에 포함)
        if not (nmv and dnv and (nmv in dnv or dnv in nmv)):
            continue
        if not _cmpa177_ok(nm, dn):
            continue
        dvol = extract_volume_ml(dsname)
        if tvol and dvol and not _vol_ok(tvol, dvol):
            continue
        # 더 구체적(이름 길이 근접) 우선
        score = abs(len(dn) - len(nm))
        if best is None or score < best[0]:
            best = (score, str(tpid), dsname, dvol)
    return best[1:] if best else None


def load_cache():
    if not os.path.exists(CACHE):
        return {}
    with open(CACHE, encoding="utf-8-sig") as f:
        return {r["_k1"]: r for r in csv.DictReader(f)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0, help="이번 실행 최대 신규 조회 수(0=무제한)")
    ap.add_argument("--pace", type=float, default=0.6)
    ap.add_argument("--date", default="2026-06-28")
    args = ap.parse_args()

    # 비교 대상 제품명 = build_compare 의 both + 단독(전체 면세 제품)
    from build_compare import build_rows
    both, s_only, l_only, g_only, *_ = build_rows()
    names = []
    seen = set()
    for r in both + s_only + l_only + g_only:
        nm = r.get("제품명") or ""
        k1 = norm(nm)
        if k1 and k1 not in seen:
            seen.add(k1)
            names.append(nm)

    cache = load_cache()
    new_file = not os.path.exists(CACHE)
    f = open(CACHE, "a", newline="", encoding="utf-8-sig")
    w = csv.DictWriter(f, fieldnames=FIELDS)
    if new_file:
        w.writeheader()
        f.flush()

    done = 0
    hit = 0
    for nm in names:
        k1 = norm(nm)
        if k1 in cache:
            continue
        if args.limit and done >= args.limit:
            break
        done += 1
        try:
            time.sleep(args.pace)
            cands = ed.search(ed.kw_of(nm) or nm)
            m = best_ds(nm, cands)
            row = {"제품명": nm, "_k1": k1, "looked_up_at": args.date,
                   "ds_price_krw": "", "ds_seller": "", "ds_vol_ml": "",
                   "ds_item_id": "", "ds_name": ""}
            if m:
                tpid, dsname, dvol = m
                time.sleep(args.pace)
                pp = ed.item_page_price(tpid)
                if pp and pp.get("price"):
                    row.update(ds_price_krw=pp["price"], ds_seller=pp.get("seller", ""),
                               ds_vol_ml=dvol or "", ds_item_id=tpid, ds_name=dsname)
                    hit += 1
            w.writerow(row)
            f.flush()
            cache[k1] = row
        except Exception as e:
            print(f"ERR {nm}: {e}", flush=True)
    f.close()
    total = len(load_cache())
    priced = sum(1 for r in load_cache().values() if r.get("ds_price_krw"))
    print(f"이번 실행 신규 조회 {done} (가격확보 {hit}) · 캐시 누적 {total} (가격보유 {priced})",
          flush=True)


if __name__ == "__main__":
    main()
