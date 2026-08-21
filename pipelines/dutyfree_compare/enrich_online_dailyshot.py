#!/usr/bin/env python3
"""면세 비교 제품을 데일리샷 온라인 전국 최저가로 보강(CMPA-650, 보드 2026-06-28).

배경: 기존 데일리샷 수집(`pipelines/dailyshot/crawl_dailyshot.py`)은 **우리가 트레이더스/
코스트코에서 추적 중인 ~207종**만 검색한다(IN_SCOPE 게이트). 그래서 면세점엔 있지만
트레이더스/코스트코엔 없는 제품(예: 부나하벤 크루아모나 1L, dailyshot item 4611)은
데일리샷에 실제로 있어도 우리 데이터엔 '소매가 없음'으로 나온다.

이 스크립트는 **면세 비교 제품명**으로 데일리샷을 직접 검색해 제품 페이지 전국 최저
셀러가(item_page_price, 면세/해외 제외 — CMPA-321/344)를 가져와 캐시에 누적한다.
build_compare 가 이 캐시를 '데일리샷(온라인)' 국내 소스로 병합한다.

- 날짜별 스냅샷: `data/whisky-prices/_dailyshot_compare_<date>.csv`(기본=KST 오늘). 매 실행이
  직전 최신 스냅샷을 seed-forward 로 이월(CMPA-156)한 뒤 그 위에서 신규·stale 행만 갱신한다.
  파일명 날짜가 매일 전진하므로 build_compare 의 최신 스냅샷 탐색이 stale 되지 않는다(CMPA-1345).
- 멱등/재개: 이미 있는 최신 행은 건너뜀. 크래시 대비 25건마다 전체 재작성(원자적 rename).
- 매칭 가드: 이름 정규화 부분일치 + 용량(±) + CMPA-177 토큰(년수/CS/피티드/셰리/버번) 비대칭 제외.
- 면세 제외는 item_page_price(_walk_page_price, price_usd>0 제외)가 보장.
"""
import argparse
import csv
import datetime
import glob
import os
import re as _re2
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

CACHE_DIR = os.path.join(ROOT, "data", "whisky-prices")
CACHE_GLOB = os.path.join(CACHE_DIR, "_dailyshot_compare_????-??-??.csv")
FIELDS = ["제품명", "_k1", "ds_price_krw", "ds_seller", "ds_vol_ml", "ds_item_id",
          "ds_name", "looked_up_at"]


def kst_today() -> str:
    """KST 오늘 날짜(YYYY-MM-DD). 스냅샷 파일명·looked_up_at 기본값."""
    return ((datetime.datetime.now(datetime.timezone.utc)
             + datetime.timedelta(hours=9)).date()).isoformat()


def cache_path(date: str) -> str:
    """해당 날짜의 보강 스냅샷 경로. CMPA-1345: 날짜별 파일로 슬롯 최신성을 보장한다.

    과거엔 파일명이 2026-06-28 로 하드코딩돼 매 실행이 같은 파일을 덮어써서 build_compare 의
    최신 스냅샷 탐색(_latest_snapshot)이 영원히 06-28 로 stale 판정났다(STALE 경고 원인)."""
    return os.path.join(CACHE_DIR, f"_dailyshot_compare_{date}.csv")


def latest_prior_cache(before_date: str):
    """before_date 이전 날짜의 가장 최신 보강 스냅샷 경로(누적 데이터 seed 용). 없으면 None.

    CMPA-156(데이터 3원칙): 매 실행은 백지에서 시작하지 않고, 직전 스냅샷을 가져와 그 위에서
    갱신한다. 각 행의 looked_up_at(항목별 실제 수집일)은 그대로 보존한다."""
    dated = []
    for fp in glob.glob(CACHE_GLOB):
        m = _re2.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(fp))
        if m and m.group(1) < before_date:
            dated.append((m.group(1), fp))
    return max(dated)[1] if dated else None


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


def load_cache(path):
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig") as f:
        return {r["_k1"]: r for r in csv.DictReader(f)}


def _write_cache(path, cache):
    """전체 캐시 dict → 파일(원자적 rename). seed-forward·stale 갱신으로 행을 덮어쓰므로
    append 가 아니라 전체 재작성한다. FIELDS 외 여분 키는 버린다."""
    tmp = path + ".tmp"
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        for r in cache.values():
            w.writerow(r)
    os.replace(tmp, path)


def _is_stale(row, today, days):
    """행의 looked_up_at 이 days 일 이상 오래됐으면 True(재조회 대상). days<=0 이면 항상 False."""
    if days <= 0:
        return False
    lu = (row.get("looked_up_at") or "").strip()
    try:
        d = datetime.date.fromisoformat(lu)
    except (ValueError, TypeError):
        return True  # 날짜 불량/누락 → 갱신 대상
    return (datetime.date.fromisoformat(today) - d).days >= days


def _lookup_row(nm, k1, date, pace):
    """데일리샷 검색+제품페이지가 1건 조회 → 캐시 행. (면세/해외 제외는 item_page_price 가 보장)."""
    row = {"제품명": nm, "_k1": k1, "looked_up_at": date,
           "ds_price_krw": "", "ds_seller": "", "ds_vol_ml": "",
           "ds_item_id": "", "ds_name": ""}
    cands = ed.search(ed.kw_of(nm) or nm)
    m = best_ds(nm, cands)
    if m:
        tpid, dsname, dvol = m
        time.sleep(pace)
        pp = ed.item_page_price(tpid)
        if pp and pp.get("price"):
            row.update(ds_price_krw=pp["price"], ds_seller=pp.get("seller", ""),
                       ds_vol_ml=dvol or "", ds_item_id=tpid, ds_name=dsname)
    return row


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0,
                    help="이번 실행 최대 조회 수(신규+stale재조회, 0=무제한)")
    ap.add_argument("--pace", type=float, default=0.6)
    ap.add_argument("--date", default=None, help="스냅샷 날짜(기본=KST 오늘). 파일명·looked_up_at 에 사용")
    ap.add_argument("--refresh-stale-days", type=int, default=0,
                    help="looked_up_at 이 N일 이상 오래된 행을 재조회(0=끔, seed-forward+신규만)")
    args = ap.parse_args()
    date = args.date or kst_today()

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

    target = cache_path(date)
    # 오늘 스냅샷을 seed: 이미 있으면 이어서, 없으면 직전 최신 스냅샷을 가져와 그 위에서 갱신(CMPA-156).
    cache = load_cache(target)
    if not cache:
        prior = latest_prior_cache(date)
        if prior:
            cache = load_cache(prior)
            print(f"seed-forward: {os.path.basename(prior)} → {os.path.basename(target)} "
                  f"({len(cache)}행 이월, looked_up_at 보존)", flush=True)
    # 즉시 오늘자 파일을 만들어 슬롯 날짜를 전진시킨다(신규 조회가 0건이어도 stale 해소).
    _write_cache(target, cache)

    done = hit = refreshed = 0
    for nm in names:
        k1 = norm(nm)
        existing = cache.get(k1)
        needs = existing is None or _is_stale(existing, date, args.refresh_stale_days)
        if not needs:
            continue
        if args.limit and done >= args.limit:
            break
        done += 1
        try:
            time.sleep(args.pace)
            row = _lookup_row(nm, k1, date, args.pace)
            if row.get("ds_price_krw"):
                hit += 1
            if existing is not None:
                refreshed += 1
            cache[k1] = row
            if done % 25 == 0:
                _write_cache(target, cache)   # 크래시 대비 주기적 flush
        except Exception as e:
            print(f"ERR {nm}: {e}", flush=True)
    _write_cache(target, cache)

    total = len(cache)
    priced = sum(1 for r in cache.values() if r.get("ds_price_krw"))
    print(f"스냅샷 {date}: 조회 {done}(신규+재조회, 그중 갱신 {refreshed}) · 가격확보 {hit} "
          f"· 캐시 누적 {total}(가격보유 {priced}) → {os.path.basename(target)}",
          flush=True)


if __name__ == "__main__":
    main()
