#!/usr/bin/env python3
"""build_whisky_floor_json.py — CMPA-349 (부모 CMPA-347 앱 데이터).

앱(PWA, `apps/frugal`)이 fetch 하는 **정적 JSON** `whisky_floor.json` 생성기.
신규 백엔드 0 — 기존 파이프라인 산출물(정규화 DB + 데일리샷 정본)만 재사용한다.

floor 규칙 = 국내 최저가 = min(데일리샷 라이브[면세 제외], 정규화 DB floor)
  신라 리포트(`refresh_report_prices`)와 **동일 규칙**이다. 데일리샷은 정규화
  DB(`normalized_prices.csv`)에 `KR-DS` market 으로 이미 병합돼 있고(crawl 단계
  `is_dutyfree_listing` 로 면세/해외 제외, CLAUDE.md/CMPA-321·322), 따라서
  정규화 DB floor = min(마트·트레이더스·코스트코·데일리샷[면세 제외]) 이며 그 자체로
  위 규칙을 만족한다 → **결정론적, 네트워크 0**(기본 모드).
  `--live` 옵션은 데일리샷 라이브 제품-페이지 최저가(`enrich_dailyshot`,
  CMPA-338/343 page floor)를 추가로 접합해 발행시점 신선도까지 신라 리포트와
  완전히 동일하게 맞춘다(네트워크 사용, 비결정론적).

⚠️ 반드시 제외(가드):
  - 면세·해외: `normalized_prices` 에는 `KR`/`KR-DS` market 만 존재(면세 market
    구조적 부재). 데일리샷 `KR-DS` 는 crawl 단계에서 이미 면세 제외됨.
  - dirty(CMPA-345): `_dailyshot_dirty.json` 매니페스트의 오염 source_file 또는
    (제품명, 오염일) 에 해당하는 `KR-DS` 행을 floor 계산에서 제외.

스키마(JSON 루트 = 배열) — T2 PWA 가 의존하므로 고정:
  [ { "product_id", "name", "floor_krw", "collected_at", "dailyshot_url" }, ... ]
  - product_id    = 회사 정본 canonical_id (예: "w001") — 안정 키.
  - name          = canonical_name_ko.
  - floor_krw     = 국내 최저가(정수 KRW).
  - collected_at  = 그 floor 가격을 수집한 날짜(YYYY-MM-DD; 데이터 3원칙
                    '수집 날짜 기준값').
  - dailyshot_url = "https://dailyshot.co/m/item/{top_product_id}" (없으면 null).

출력(기본): apps/frugal/whisky_floor.json — PWA 와 co-locate → 발행 시 함께 배포.
사용: python3 scripts/build_whisky_floor_json.py [--out PATH] [--live]
"""
import argparse
import csv
import glob
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
DATA = os.path.join(ROOT, "data", "whisky-prices")
NORMALIZED = os.path.join(DATA, "normalized", "normalized_prices.csv")
DIRTY = os.path.join(DATA, "_dailyshot_dirty.json")
DEFAULT_OUT = os.path.join(ROOT, "apps", "frugal", "whisky_floor.json")
DS_ITEM_URL = "https://dailyshot.co/m/item/{tid}"


def load_dirty():
    """CMPA-345 매니페스트 → (오염 source_file set, 오염 (제품명,날짜) set)."""
    if not os.path.exists(DIRTY):
        return set(), set()
    m = json.load(open(DIRTY, encoding="utf-8"))
    files = {os.path.basename(f.get("path", "")) for f in m.get("dirty_files", [])}
    pd = set()
    for p in m.get("dirty_products", []):
        for d in p.get("polluted_run_dates", []):
            pd.add((p.get("name"), d))
    return files, pd


def load_tid_map():
    """데일리샷 정본/리스팅 → raw_name(위스키명) -> top_product_id (최신 수집일).

    listings CSV 의 명시 컬럼을 우선, 없으면 정본 CSV 의 URL(/m/item|product/{tid})
    에서 추출(둘은 동일 tid 임을 검증함)."""
    tid, best = {}, {}
    for path in sorted(glob.glob(os.path.join(DATA, "*_dailyshot_listings.csv"))):
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            n, d, t = r.get("위스키명"), r.get("수집일", "") or "", r.get("top_product_id")
            if n and t and d >= best.get(n, ""):
                best[n] = d
                tid[n] = str(t).strip()
    for path in sorted(glob.glob(os.path.join(DATA, "*_dailyshot.csv"))):
        if path.endswith("_listings.csv"):
            continue
        for r in csv.DictReader(open(path, encoding="utf-8-sig")):
            n, d = r.get("위스키명"), r.get("수집일", "") or ""
            mt = re.search(r"/m/(?:item|product)/(\d+)", r.get("URL", "") or "")
            if n and mt and d >= best.get(n, ""):
                best[n] = d
                tid[n] = mt.group(1)
    return tid


def build(live=False):
    """정규화 DB floor 를 canonical_id 단위로 집계해 floor 레코드 + 통계 반환."""
    dirty_files, dirty_pd = load_dirty()
    tid_map = load_tid_map()

    agg = {}              # cid -> {name, floor, date, channel}
    cid_rawnames = {}     # cid -> [raw_name...] (KR-DS, tid 조회용)
    stat = {"rows": 0, "matched_kr": 0, "matched_krds": 0,
            "nonmatched": 0, "other_market": 0,
            "dirty_skipped": 0, "dutyfree_market_rows": 0}

    for r in csv.DictReader(open(NORMALIZED, encoding="utf-8-sig")):
        stat["rows"] += 1
        if r.get("status") != "matched":
            stat["nonmatched"] += 1
            continue
        mk = r.get("market")
        if mk not in ("KR", "KR-DS"):
            # 면세·해외 market(HK/JP/DUTYFREE 등)은 국내 floor 대상 아님 → 제외.
            stat["other_market"] += 1
            continue
        try:
            price = float(r["price_krw"])
        except (ValueError, TypeError):
            continue
        if price <= 0:
            continue
        date = (r.get("date") or "").strip()
        name = (r.get("canonical_name_ko") or "").strip()
        cid = r.get("canonical_id")
        if not cid:
            continue

        if mk == "KR-DS":
            # dirty 가드(CMPA-345): 오염 파일 또는 (제품, 오염일) 제외.
            if r.get("source_file") in dirty_files or (name, date) in dirty_pd:
                stat["dirty_skipped"] += 1
                continue
            stat["matched_krds"] += 1
            cid_rawnames.setdefault(cid, []).append((r.get("raw_name") or "").strip())
        else:
            stat["matched_kr"] += 1

        a = agg.setdefault(cid, {"name": name, "floor": price,
                                 "date": date, "channel": r.get("channel", "")})
        if name:
            a["name"] = name
        # floor = 최저가. 동가면 더 최근 수집일을 채택(신선도).
        if price < a["floor"] or (price == a["floor"] and date > a["date"]):
            a["floor"], a["date"], a["channel"] = price, date, r.get("channel", "")

    # (옵션) 데일리샷 라이브 page floor 접합 — 신라 리포트와 동일 규칙.
    if live:
        _fold_live(agg)

    # 레코드 조립
    out, no_url = [], 0
    for cid in sorted(agg):
        a = agg[cid]
        tid = a.get("live_tid")
        if not tid:
            for rn in cid_rawnames.get(cid, ()):
                if rn in tid_map:
                    tid = tid_map[rn]
                    break
        url = DS_ITEM_URL.format(tid=tid) if tid else None
        if url is None:
            no_url += 1
        out.append({
            "product_id": cid,
            "name": a["name"],
            "floor_krw": int(round(a["floor"])),
            "collected_at": a["date"],
            "dailyshot_url": url,
        })
    stat["no_dailyshot_url"] = no_url
    return out, stat


def _fold_live(agg):
    """enrich_dailyshot 라이브 제품-페이지 최저가를 floor 에 접합(네트워크)."""
    sys.path.insert(0, os.path.join(ROOT, "pipelines", "shilla_dutyfree"))
    try:
        import enrich_dailyshot as DS
        from pipelines.common.dated import kst_today
    except Exception as e:  # noqa: BLE001
        print(f"[live] enrich_dailyshot 임포트 실패 → 라이브 생략: {e}", file=sys.stderr)
        return
    today = kst_today()
    names = [a["name"] for a in agg.values() if a.get("name")]
    print(f"[live] 데일리샷 라이브 page floor 조회 {len(names)}종 …", file=sys.stderr)
    lookup = DS.build_lookup(names, with_page=True)
    by_name = {}
    for cid, a in agg.items():
        by_name.setdefault(a["name"], cid)
    for nm, m in (lookup or {}).items():
        if not m:
            continue
        cid = by_name.get(nm)
        if not cid:
            continue
        a = agg[cid]
        if m.get("top_product_id"):
            a["live_tid"] = str(m["top_product_id"])
        p = m.get("page_price") or m.get("ds_price")
        if p and p < a["floor"]:
            a["floor"], a["date"], a["channel"] = p, today, "데일리샷(라이브)"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=DEFAULT_OUT, help=f"출력 경로(기본 {DEFAULT_OUT})")
    ap.add_argument("--live", action="store_true",
                    help="데일리샷 라이브 page floor 접합(네트워크, 비결정론)")
    args = ap.parse_args()

    records, stat = build(live=args.live)

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as fp:
        json.dump(records, fp, ensure_ascii=False, indent=2, sort_keys=True)
        fp.write("\n")

    # --- 검증 로그(수용 기준 증빙) ---
    with_url = sum(1 for r in records if r["dailyshot_url"])
    print(f"JSON -> {args.out}  ({len(records)}종)")
    print(f"  소스 행: {stat['rows']}  (matched KR={stat['matched_kr']}, "
          f"KR-DS={stat['matched_krds']}, 비매칭={stat['nonmatched']}, "
          f"기타 market={stat['other_market']})")
    print(f"  ✅ 면세/해외 market 행 floor 반영: {stat['dutyfree_market_rows']} "
          f"(normalized 에 KR/KR-DS 만 존재 → 면세 구조적 0)")
    print(f"  ✅ dirty 제외(CMPA-345): {stat['dirty_skipped']}건")
    print(f"  데일리샷 링크 있음 {with_url} / 없음 {stat['no_dailyshot_url']}")

    # 스키마 자가검증
    REQ = {"product_id", "name", "floor_krw", "collected_at", "dailyshot_url"}
    bad = [r for r in records if set(r) != REQ or not isinstance(r["floor_krw"], int)
           or r["floor_krw"] <= 0 or not r["collected_at"]]
    if bad:
        print(f"  ❌ 스키마 위반 {len(bad)}건 (예: {bad[0]})", file=sys.stderr)
        sys.exit(1)
    print("  ✅ 스키마 검증 통과(모든 원소 5필드, floor_krw>0, collected_at 존재)")


if __name__ == "__main__":
    main()
