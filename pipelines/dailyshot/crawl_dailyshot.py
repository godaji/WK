#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
데일리샷(dailyshot.co) 최저가 수집기 — CMPA-19

목표(CMPA-19): `(수집일, 위스키명, 가격)` 을 데일리샷에서 수집한다.
대상 위스키 리스트 = 우리가 이미 추적 중인 **이마트(트레이더스)·코스트코** 위스키
  → data/whisky-prices/{2026-03,04,05}.csv 의 `술이름`/`위치` 에서 자동 로드(하드코딩 X).
  → 위치가 이마트/트레이더스/코스트코 인 항목만 사용(롯데마트 등 범위 외 제외).

법무/소싱 가드레일:
  - CMPA-19 부모 가드레일은 CEO 가 해제함(2026-05-30 보드 코멘트: "법무 가드레일 풀었어").
    → 수집·측정 진행 가능. CMPA-1 상업 적재/공개는 별도 티켓·승인 흐름을 따른다.
  - 저빈도(요청 간 슬립), robots/약관 존중, 인증우회 없음, 키워드 질의만(전체 카탈로그 통복제 X).

실측 소스(런타임 디스커버리로 확인):
  GET https://api.dailyshot.co/items/search/?q=<keyword>&page=<n>
    -> {count, next, previous, results:[{id, name, top_product_id, price, discount_percent, category, ...}]}
  데일리샷은 마켓플레이스라 같은 상품(top_product_id)이 셀러별로 여러 가격으로 노출됨
    → 매칭 상품군의 **price 최저값** = 그 위스키의 데일리샷 최저가.
  price 는 이미 할인 반영된 판매가(노출가). (추가 쿠폰가는 비고에 discount_percent 만 기록.)

매칭 정책(정밀도):
  - 결과 중 category == '위스키' 만 채택(코냑/진 등 동명이품 배제).
  - 200ml/500ml/미니어처 등 소용량은 병당가 왜곡 → 최저가 후보에서 제외.
  - 대상명의 핵심 토큰(용량/가격잡음 제거 후)이 상품명에 모두 포함되어야 매칭.
  - '여분 토큰' 이 가장 적은(=대상명에 가장 가까운) 상품군을 우선, 그 안에서 최저가.

출력:
  data/whisky-prices/2026-05_dailyshot.csv   (UTF-8 BOM, 엑셀 한글 호환) — 상품당 최저가 1행
    컬럼: 수집일, 위스키명, 가격_KRW, 데일리샷상품명, 할인율, 국내위치, URL, 비고
  data/whisky-prices/2026-05_dailyshot_listings.csv (CMPA-321) — 상품당 '셀러별 1행'(가격분포)
    컬럼: 수집일, 위스키명, top_product_id, 데일리샷상품명, seller_id, 가격_KRW,
          할인율, sales_count, vivino_score, review_count, 국내위치, 정확도
    ↑ 같은 검색 응답 재직렬화(추가 크롤 부하 0). 판매자 수/가격 분산/인기도 분석용.
  data/whisky-prices/_dailyshot_metrics.json (hit-rate/스토어 범위/가격대 + 셀러 집계)

재현:
  python3 pipelines/dailyshot/crawl_dailyshot.py [수집일=오늘] [출력CSV]
"""
import argparse
import csv
import json
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
import urllib.error
import datetime

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from pipelines.common.dated import snapshot  # noqa: E402
from pipelines.common.whisky_quality import canonical_store  # noqa: E402  CMPA-165 매장 라벨 정본화
from pipelines.dailyshot import sellers as SELLERS  # noqa: E402  CMPA-322 셀러 메타 해소·캐시
from pipelines.shilla_dutyfree.enrich_dailyshot import item_page_price  # noqa: E402  CMPA-352 페이지 floor

DATA_DIR = os.path.join(ROOT, "data", "whisky-prices")
DOMESTIC_CSVS = ["2026-03.csv", "2026-04.csv", "2026-05.csv"]
ALIASES_CSV = os.path.join(ROOT, "assets", "whisky-aliases.csv")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
SEARCH = "https://api.dailyshot.co/items/search/?q={q}&page={p}"
PRODUCT_URL = "https://dailyshot.co/m/product/{tid}"

# CMPA-322: 면세점(service_type=5) 셀러 메타 해소·캐시·업종 라벨은 sellers 모듈로 분리.
#   floor 오염의 핵심 원인 = 데일리샷 마켓플레이스에 면세점(신라면세점 등)이 KRW로 섞여
#   들어와 '국내 최저가'를 끌어내린 것(면세가는 출국·한도 조건이라 국내 floor가 아니다).

# 범위: 이마트/트레이더스/코스트코 (롯데마트 등 제외)
IN_SCOPE = ("이마트", "트레이더스", "코스트코")
# 비위스키(동명이품) 대상 제외 마커
NON_WHISKY = ("드라이진", "런던 드라이", " xo", "꼬약", "꽃약", "브랜디", "드라이 진")
# 최저가 후보에서 뺄 소용량/패키지 마커(병당가 왜곡; 표준 700/750ml·1L 만 인정)
SMALL_VOL = ("500ml", "375ml", "250ml", "200ml", "180ml", "100ml", "50ml",
             "미니어처", "미니어쳐", "미니 ")
PKG = ("전용잔", "전용 잔", "잔세트", "메가잔", "잔 패키지", "두 개입", "두개입", "기획세트")
# 용량/가격잡음 토큰 제거용
VOL_RE = re.compile(r"\d+\.?\d*\s*m?ml\b|\d+\s*l\d*\b|\d+\.?\d*l\b", re.I)
PRICEJUNK_RE = re.compile(r"\d+만\d*")
ENT_RE = re.compile(r"&[a-z]+;|&#\d+;|>>|<<")


def clean_name(nm):
    s = ENT_RE.sub(" ", nm)
    s = PRICEJUNK_RE.sub(" ", s)   # "67만8", "14만1" 등 OCR 가격잡음
    s = VOL_RE.sub(" ", s)         # 700ml / 750mml / 1L / 1L9
    for w in PKG:
        s = s.replace(w, " ")
    s = re.sub(r"\b(패키지|세트)\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def norm(s):
    return re.sub(r"[^0-9a-z가-힣]", "", s.lower())


def tokens(name):
    """용량 제거된 이름에서 핵심 토큰(한글 단어/영문/숫자)."""
    name = VOL_RE.sub(" ", name)
    toks = re.findall(r"[가-힣]+|[a-zA-Z]+|\d+", name)
    drop = {"더", "the", "위스키", "스카치", "싱글", "몰트", "싱글몰트", "싱글트",
            "모트", "에디션", "캐스크", "케스크", "캐스", "오크", "리저브"}
    return [t for t in toks if t.lower() not in drop and (len(t) >= 2 or t.isdigit())]


def _load_alias_canon():
    """aliases CSV → {norm(raw_name): canonical_name_ko}. 정규화 중복 방지용.

    OCR/ASR 오류로 잘린 이름(예: '조니워커 블루라')이 canonical('조니워커 블루라벨')과
    별도 타겟으로 생성돼 같은 데일리샷 제품을 중복 조회하는 문제를 막는다. CMPA-735.
    """
    alias_map = {}
    if not os.path.exists(ALIASES_CSV):
        return alias_map
    with open(ALIASES_CSV, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row.get("status") != "matched":
                continue
            raw = row.get("raw_name", "").strip()
            canon = row.get("canonical_name_ko", "").strip()
            if raw and canon:
                alias_map[norm(raw)] = canon
    return alias_map


def load_targets():
    """국내 추적 CSV → 이마트/트레이더스/코스트코 대상만, 정제·중복제거.

    OCR/ASR 오류 이름은 aliases를 통해 canonical name으로 resolve한 뒤 중복을 합친다.
    예: '조니워커 블루라' + '조니워커 블루라벨' → 모두 '조니워커 블루라벨' 단일 타겟.
    """
    alias_map = _load_alias_canon()  # norm(raw) → canonical_name_ko

    raw = {}
    for fn in DOMESTIC_CSVS:
        p = os.path.join(DATA_DIR, fn)
        if not os.path.exists(p):
            continue
        with open(p, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                nm = (row.get("술이름") or "").strip()
                loc = canonical_store(row.get("위치"))   # CMPA-165: 지점명 제거(트레이더스 구월점→트레이더스)
                if not nm or not loc:
                    continue
                if not any(s in loc for s in IN_SCOPE):
                    continue  # 범위 외 매장(롯데마트 등)
                raw.setdefault(nm, set()).add(loc)
    targets = {}
    for nm, locs in raw.items():
        cleaned = clean_name(nm)
        if not cleaned:
            continue
        low = " " + cleaned.lower() + " "
        if any(mk in low for mk in NON_WHISKY):
            continue  # 진/코냑 등 비위스키
        # aliases로 canonical name 해소 → 중복 타겟 방지 (CMPA-735)
        canon = alias_map.get(norm(cleaned))
        질의명 = canon if canon else cleaned
        key = norm(질의명)
        if not key:
            continue
        t = targets.setdefault(key, {"질의명": 질의명, "원본": set(), "위치": set()})
        t["원본"].add(nm)
        t["위치"].update(locs)
        # canonical이 없는 경우에만 더 짧은 표현을 질의명으로 선택
        if not canon and len(cleaned) < len(t["질의명"]):
            t["질의명"] = cleaned
    out = []
    for k, v in targets.items():
        out.append({
            "key": k, "질의명": v["질의명"],
            "원본": " / ".join(sorted(v["원본"])),
            "국내위치": " / ".join(sorted(v["위치"])),
        })
    out.sort(key=lambda x: x["질의명"])
    return out


# ---- HTTP -------------------------------------------------------------------
def http_json(url, timeout=20):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA, "Accept": "application/json",
        "Accept-Language": "ko-KR,ko;q=0.9", "Referer": "https://dailyshot.co/"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def search(keyword, diag, max_pages=2):
    """keyword → category=위스키 상품 후보 리스트(셀러별 listing 포함)."""
    products, page, total = [], 1, None
    while page <= max_pages:
        url = SEARCH.format(q=urllib.parse.quote(keyword), p=page)
        try:
            d = http_json(url)
        except urllib.error.HTTPError as e:
            diag.append(f"  page{page} HTTP {e.code}")
            break
        except Exception as e:
            diag.append(f"  page{page} ERR {type(e).__name__}")
            break
        total = d.get("count") if total is None else total
        for r in d.get("results", []):
            if r.get("category") != "위스키":
                continue
            nm = (r.get("name") or "").strip()
            pr = r.get("price")
            if not nm or not isinstance(pr, (int, float)) or pr < 1000:
                continue
            products.append({
                "name": nm, "price": int(pr),
                "disc": r.get("discount_percent") or 0,
                "tid": r.get("top_product_id") or r.get("id"),
                # CMPA-321: 같은 응답에 들어오는 셀러별 메타(추가 크롤 부하 0).
                #   데일리샷=마켓플레이스라 seller_id 가 '판매자 식별자'(물리 주소 없음).
                "seller_id": r.get("seller_id"),
                "sales_count": r.get("sales_count") or "",   # "구매 2만+" 인기 신호
                "vivino": r.get("vivino_score"),
                "reviews": r.get("review_count"),
                # CMPA-322: 면세/해외 리스팅 판별 신호. price_usd / net_price_usd 가
                #   0보다 크면 면세(신라면세 svc5)·해외가 — 국내 floor 에서 제외한다.
                #   (enrich_dailyshot.best_match 와 동일 신호로 코드베이스 일관 유지.)
                "price_usd": r.get("price_usd") or 0,
                "net_price_usd": r.get("net_price_usd") or 0,
            })
        if not d.get("next"):
            break
        page += 1
    diag.append(f"  results(위스키)={len(products)} / count~{total}")
    return products


def is_dutyfree_listing(p):
    """CMPA-322: 면세/해외 리스팅이면 True.

    데일리샷 마켓플레이스 검색에 면세점(신라면세 svc5)·해외가가 KRW 로 섞여 들어와
    '국내 최저가' floor 를 오염시켰다(예: 듀어스15년 48,864 면세 vs 국내최저 113,000).
    면세·해외 리스팅은 `price_usd`/`net_price_usd` 가 0보다 크다(국내 소매가는 0).
    이는 enrich_dailyshot.best_match 가 쓰는 신호와 동일하며 service_type==5(면세)뿐
    아니라 해외가까지 한 번에 걸러 더 견고하고, 셀러 API 가용성과 무관하다.
    백스톱: price_usd 가 누락된 면세 리스팅 대비, 해소된 셀러 업종(service_type)이
    면세점(svc5)이면 함께 제외한다."""
    if (p.get("price_usd") or 0) > 0 or (p.get("net_price_usd") or 0) > 0:
        return True
    return p.get("service_type") == SELLERS.DUTYFREE_SVC


def match_lowest(query_name, products):
    """대상 핵심토큰이 상품명(정규화)에 모두 부분문자열로 존재해야 매칭.
    띄어쓰기 차이(더블캐스크↔더블 캐스크)에 견고. 추가문자 최소(=plain 우선) 후
    그 군에서 최저가. 추가문자 0 이면 '정확', 아니면 '근접'.

    CMPA-322: 국내 floor 계산에서 면세/해외 리스팅(is_dutyfree_listing)을 제외한다.
    면세가는 listings 동반 데이터셋에는 남기되(업종=면세점 태그) floor 로 채택하지 않는다."""
    qtoks = [norm(t) for t in tokens(query_name)]
    qtoks = [t for t in qtoks if t]
    if not qtoks:
        return None
    qlen = sum(len(t) for t in qtoks)
    scored = []   # (extra, p) — 면세 포함 전체(listings 용)
    for p in products:
        low = " " + p["name"].lower() + " "
        if any(mk in low for mk in SMALL_VOL):
            continue
        if any(mk in p["name"] for mk in PKG):
            continue
        pnorm = norm(VOL_RE.sub(" ", p["name"]))
        if not all(t in pnorm for t in qtoks):
            continue
        extra = max(0, len(pnorm) - qlen)   # 상품명 추가 글자수(작을수록 plain 근접)
        scored.append((extra, p))
    if not scored:
        return None
    # CMPA-322: 국내 floor 후보 = 면세/해외 제외. 국내가가 하나도 없으면 floor MISS
    #   (면세가를 국내 최저가로 채택하지 않는다 — floor 오염 방지).
    domestic = [(e, p) for e, p in scored if not is_dutyfree_listing(p)]
    if not domestic:
        return None
    best_extra = min(e for e, p in domestic)
    tier = [p for e, p in domestic if e == best_extra]
    best = min(tier, key=lambda x: x["price"])
    # CMPA-321/322: 매칭된 동일상품(top_product_id)의 셀러별 listing 전체를 함께 반환한다.
    #   tid 가 같으면 면세 리스팅도 포함해 listings 에 남긴다(업종 태그로 구분).
    #   동명 다른 SKU 가 섞이지 않도록 best 와 같은 tid 만 셀러로 본다.
    sellers = [p for e, p in scored if p.get("tid") == best["tid"]]
    return {"price": best["price"], "matched_name": best["name"],
            "disc": best["disc"], "tid": best["tid"], "extra": best_extra,
            "n_listings": len(tier), "n_pool": len(domestic),
            "sellers": sellers}


# ── CMPA-352: 정본 floor = 제품 페이지(/m/item) 전국 최저 셀러가 ───────────────
# 배경(CMPA-344 보드 확정 2026-06-14): "앞으로 데일리샷 가격의 의미 자체가 페이지
#   최저가". 검색 API(/items/search) 의 `price` 는 '대표 셀러가'라 전국 모든 셀러를
#   노출하지 않아 제품 페이지 최저가보다 높을 수 있다(글렌드로낙16 검색 372,000 vs
#   페이지 329,000/셀러'피보'). 이 정본 파이프라인의 floor → 정규화 DB floor → 메인
#   위스키 리포트·블로그 국내최저가 로 흘러 블라스트가 크므로 페이지가로 통일한다.
# 방법: match_lowest 로 매칭 상품(tid)을 고른 뒤, 그 tid 의 제품 페이지 최저 셀러가를
#   floor 로 채택한다. 페이지 조회 실패 시 검색 셀러 min 으로 폴백(비치명).
#   면세/해외 제외(CMPA-321)는 페이지 파서(_walk_page_price, price_usd>0 제외)에도 유지.
#   tid 캐시(런 내 1회 조회)·pace 로 추가 부하를 매칭당 페이지 1회로 제한한다.
def page_floor(tid, cache, pace=0.7):
    """매칭 상품 tid 의 제품 페이지 전국 최저 셀러가 {price, seller} | None.
    tid 캐시로 런 내 중복 조회를 막고, 조회 직전 pace 만큼 슬립한다."""
    if not tid:
        return None
    if tid in cache:
        return cache[tid]
    time.sleep(pace)
    pp = item_page_price(tid)
    cache[tid] = pp
    return pp


# CMPA-297/156: 일간 수집은 백지에서 시작하지 않는다. 데일리샷 API throttle 로
# 오늘 MISS 가 난 항목이라도 정본에 직전 수집값이 있으면 그 값을 보존한다
# (좋은 가격을 빈칸으로 덮지 않는다). _runs/ 일별 스냅샷은 '날것'(raw) 그대로 둬서
# 선행지표(lead-lag) 패널이 관측 결측을 정직하게 반영하게 한다.
_CARRY_RX = re.compile(
    r"\s*/\s*\d{4}-\d{2}-\d{2} 수집 (?:미관측 →|throttle로) \d{4}-\d{2}-\d{2}값 보존")


def load_prior_canonical(path):
    """직전 정본 CSV → {위스키명: row}. 없으면 빈 dict."""
    if not path or not os.path.exists(path):
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["위스키명"]: r for r in csv.DictReader(f)}


def preserve_misses(rows, prior, today):
    """오늘 MISS(가격 빈칸)인데 직전 정본에 가격이 있으면 그 행을 이월(carry-forward).
    이월 행은 직전 수집일을 유지하고 비고에 '{today} 수집 미관측 → {수집일}값 보존'을
    덧붙인다(중복 누적 방지로 기존 동일 꼬리표는 먼저 제거). 보존 건수를 반환."""
    kept = 0
    for r in rows:
        if r["가격_KRW"] != "":
            continue
        p = prior.get(r["위스키명"])
        if not p or not (p.get("가격_KRW") or "").strip():
            continue
        prev_date = p.get("수집일", "")
        base = _CARRY_RX.sub("", p.get("비고", "")).rstrip()
        carried = dict(p)
        carried["비고"] = f"{base} / {today} 수집 미관측 → {prev_date}값 보존".lstrip(" /")
        r.clear()
        r.update(carried)
        kept += 1
    return kept


def main():
    ap = argparse.ArgumentParser(description="데일리샷 최저가 수집기 (CMPA-19/313)")
    ap.add_argument("date", nargs="?", default=None,
                    help="수집일 YYYY-MM-DD (기본: 오늘 KST)")
    ap.add_argument("out", nargs="?", default=None,
                    help="출력 CSV 경로 (기본: data/whisky-prices/{ym}_dailyshot.csv)")
    ap.add_argument("--slot", choices=["am", "pm"], default=None,
                    help="intraday 슬롯 (기본: KST 시각 자동탐지, 12시 미만=am 이상=pm)")
    args = ap.parse_args()

    today = args.date or datetime.date.today().isoformat()
    # 기본 출력은 수집일의 YYYY-MM 로 자동 도출(주간 루틴이 월 경계에서 올바른 파일에 적재).
    ym = today[:7]
    out_path = args.out or os.path.join(DATA_DIR, f"{ym}_dailyshot.csv")
    metrics_path = os.path.join(DATA_DIR, "_dailyshot_metrics.json")

    # CMPA-313: intraday 슬롯 자동탐지 (KST 기준, 12:00 미만=am 이상=pm)
    from datetime import datetime as _dt, timezone as _tz, timedelta as _td
    _KST = _tz(_td(hours=9))
    slot = args.slot or ("am" if _dt.now(_KST).hour < 12 else "pm")

    prior = load_prior_canonical(out_path)  # CMPA-297: throttle 보존용 직전 정본
    targets = load_targets()
    print(f"[targets] 이마트/트레이더스/코스트코 대상 {len(targets)}종(정제·중복제거 후) 로드")
    print(f"[slot] intraday 슬롯={slot}")

    # CMPA-322: seller_id → 상호·업종·지역 해소(캐시 우선, 신규 셀러만 API 조회).
    resolver = SELLERS.SellerResolver(fetched_date=today)
    rows, diag_all, hit = [], [], 0
    listing_rows = []   # CMPA-321: 상품당 셀러별 1행(동반 데이터셋)
    dutyfree_excluded = 0   # CMPA-321: 수집에서 제외한 면세/해외 리스팅 수(분석 정직성)
    page_cache = {}     # CMPA-352: tid → 페이지 floor (런 내 1회 조회)
    page_adopted = 0    # CMPA-352: floor 를 페이지 최저가로 채택한 hit 수
    page_fallback = 0   # CMPA-352: 페이지 조회 실패로 검색 셀러 min 폴백한 hit 수
    floor_lowered = 0   # CMPA-352: 페이지가가 검색가보다 낮아진 hit 수(방법론 전환 가시화)
    for t in targets:
        q = t["질의명"]
        diag = [f"# {q}  (원본: {t['원본'][:60]})"]
        try:
            products = search(q, diag)
        except Exception as e:
            products = []
            diag.append(f"  ERR {type(e).__name__}")
        # CMPA-322: 모든 후보에 셀러 상호/업종/지역 enrich + service_type 부착.
        #   면세는 여기서 '드롭하지 않는다' — match_lowest 가 floor 에서만 제외하고
        #   listings 동반 데이터셋에는 업종=면세점 태그로 남긴다(분석 가시성 유지).
        for p in products:
            meta = resolver.resolve(p.get("seller_id")) or {}
            p["service_type"] = meta.get("service_type")
            p["seller_name"] = meta.get("셀러명") or ""
            p["seller_svc"] = meta.get("업종") or ""
            p["seller_region"] = meta.get("지역") or meta.get("address") or ""
        m = match_lowest(q, products) if products else None
        if m:
            hit += 1
            acc = "정확" if m["extra"] == 0 else "근접"
            # CMPA-352: floor = 제품 페이지 전국 최저 셀러가(검색 셀러 min 은 폴백).
            search_min = m["price"]
            pp = page_floor(m["tid"], page_cache)
            if pp and pp.get("price", 0) > 0:
                floor = pp["price"]
                page_adopted += 1
                seller = pp.get("seller") or "?"
                floor_note = f" / 페이지최저 {floor:,}(셀러:{seller})"
                if floor != search_min:
                    floor_note += f"[검색 {search_min:,}]"
                    if floor < search_min:
                        floor_lowered += 1
            else:
                floor = search_min
                page_fallback += 1
                floor_note = " / 검색최저(페이지 조회 실패 폴백)"
            note = f"셀러 {m['n_listings']}/{m['n_pool']} 중 최저"
            if m["disc"]:
                note += f" / 노출가 할인 {m['disc']}%"
            note += floor_note
            rows.append({
                "수집일": today, "위스키명": q, "가격_KRW": floor,
                "데일리샷상품명": m["matched_name"], "정확도": acc,
                "할인율": m["disc"], "국내위치": t["국내위치"],
                "URL": PRODUCT_URL.format(tid=m["tid"]),
                "비고": note,
            })
            # CMPA-321: 매칭상품의 셀러별 listing 을 동반 데이터셋에 적재(수집일 메타 포함).
            # CMPA-321 보드 2026-06-13: 면세점은 '수집에서 제외'한다. floor 뿐 아니라
            #   listings 동반 데이터셋에서도 면세/해외 리스팅을 아예 빼서, 데일리샷
            #   데이터셋은 순수 국내가만 담는다(면세는 별도 신라면세 파이프라인이 다룬다).
            for s in m["sellers"]:
                if is_dutyfree_listing(s):
                    dutyfree_excluded += 1
                    continue
                listing_rows.append({
                    "수집일": today, "위스키명": q,
                    "top_product_id": m["tid"],
                    "데일리샷상품명": s["name"],
                    "seller_id": s.get("seller_id") if s.get("seller_id") is not None else "",
                    "셀러명": s.get("seller_name") or "",
                    "업종": s.get("seller_svc") or "",
                    "지역": s.get("seller_region") or "",
                    "가격_KRW": s["price"],
                    "할인율": s.get("disc") or 0,
                    "sales_count": s.get("sales_count") or "",
                    "vivino_score": s["vivino"] if s.get("vivino") is not None else "",
                    "review_count": s["reviews"] if s.get("reviews") is not None else "",
                    "국내위치": t["국내위치"], "정확도": acc,
                })
            diag.append(f"  -> HIT {floor:,}원 [{acc}] ({m['matched_name']}) "
                        f"셀러 {len(m['sellers'])}곳{floor_note}")
        else:
            rows.append({
                "수집일": today, "위스키명": q, "가격_KRW": "",
                "데일리샷상품명": "", "정확도": "", "할인율": "",
                "국내위치": t["국내위치"],
                "URL": "", "비고": f"MISS / 검색후보 {len(products)}",
            })
            diag.append(f"  -> MISS (후보 {len(products)})")
        diag_all.extend(diag)
        time.sleep(0.7)

    # CMPA-322: 갱신된 seller 캐시 저장(신규 셀러만 늘어남 — 다음 런 추가부하 최소).
    SELLERS.save_cache(resolver.cache)
    print(f"[sellers] 캐시 {len(resolver.cache)}곳 "
          f"(이번 런 신규 {resolver.fetched}곳, 해소실패 {resolver.failed}곳)")
    print(f"[floor] 페이지 최저가 채택 {page_adopted}종 "
          f"(검색가보다 낮아짐 {floor_lowered}종), 폴백(검색가) {page_fallback}종")

    cols = ["수집일", "위스키명", "가격_KRW", "데일리샷상품명", "정확도", "할인율",
            "국내위치", "URL", "비고"]
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    def _write(path, data):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=cols)
            w.writeheader()
            w.writerows(data)

    # 1) 날것(raw) 오늘 관측을 정본에 쓰고 그대로 _runs/ 스냅샷에 박는다.
    #    스냅샷 = 선행지표(lead-lag) 패널이라 결측을 메우지 않고 정직하게 둔다(CMPA-276).
    _write(out_path, rows)
    snap = snapshot(out_path, run_date=today)  # 날짜단위 멱등 유지(lead-lag CMPA-277 호환)

    # CMPA-313: intraday 슬롯 스냅샷 — 같은 날 2회(09:00 am / 18:00 pm) 수집 분리 보존.
    # 기존 _runs/ 날짜 스냅샷은 그대로 유지(lead-lag 호환). 추가 사본만 기록.
    runs_dir = os.path.join(os.path.dirname(os.path.abspath(out_path)), "_runs")
    intraday_dir = os.path.join(runs_dir, "intraday")
    os.makedirs(intraday_dir, exist_ok=True)
    _stem = os.path.splitext(os.path.basename(out_path))[0]
    intraday_snap = os.path.join(intraday_dir, f"{_stem}__run{today}_{slot}.csv")
    _write(intraday_snap, rows)  # raw 관측(보존 전) 그대로
    print(f"[intraday] {os.path.relpath(intraday_snap, ROOT)}")

    # CMPA-321: 셀러별 동반 데이터셋 — 상품당 1행이 아니라 '셀러별 1행'.
    #   최저가 CSV(위)는 그대로 두고(신라리포트·변동감지·블로그 의존), 여기서만 분포를 적재한다.
    #   같은 응답 재직렬화이므로 신규 크롤·페이싱 부하 0. _runs/intraday 스냅샷으로 이력 보존.
    lcols = ["수집일", "위스키명", "top_product_id", "데일리샷상품명", "seller_id",
             "셀러명", "업종", "지역",
             "가격_KRW", "할인율", "sales_count", "vivino_score", "review_count",
             "국내위치", "정확도"]

    def _write_l(path, data):
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=lcols)
            w.writeheader()
            w.writerows(data)

    listings_path = os.path.join(os.path.dirname(os.path.abspath(out_path)),
                                 f"{_stem}_listings.csv")
    _write_l(listings_path, listing_rows)
    listings_snap = os.path.join(intraday_dir, f"{_stem}_listings__run{today}_{slot}.csv")
    _write_l(listings_snap, listing_rows)
    _seen = set()
    multiseller = 0
    for q in {r["위스키명"] for r in listing_rows}:
        sids = {r["seller_id"] for r in listing_rows if r["위스키명"] == q}
        _seen |= sids
        if len(sids) > 1:
            multiseller += 1
    # CMPA-321 보드: 면세/해외 리스팅은 수집에서 완전 제외(floor·listings 모두).
    dutyfree_listings = dutyfree_excluded
    print(f"[listings] {os.path.relpath(listings_path, ROOT)} "
          f"— {len(listing_rows)}행 / 멀티셀러 상품 {multiseller}종 "
          f"/ 면세·해외 제외 {dutyfree_listings}행")

    # CMPA-321 가드레일(런타임 자가검증): 면세점(업종)이 출력에 단 한 줄도 남으면 안 된다.
    #   필터가 깨지거나 미래에 누가 우회로를 만들면 여기서 시끄럽게 잡힌다(회귀 방어).
    dutyfree_leak = sum(1 for r in listing_rows if r.get("업종") == "면세점")
    if dutyfree_leak:
        print(f"  ⚠️⚠️ DUTYFREE LEAK: 면세점 {dutyfree_leak}행이 출력에 남음 — "
              f"is_dutyfree_listing 가드레일 점검 필요!", file=sys.stderr)

    # 오늘 '관측된' 적중 행(보존 이월 전) — 메트릭은 오늘 수집을 정직하게 보고한다.
    hit_rows = [r for r in rows if r["가격_KRW"] != ""]

    # 2) 정본(out_path)은 throttle MISS 를 직전값으로 보존해 빈칸 회귀를 막는다(CMPA-297/156).
    #    주간 정규화·리포트 체인이 degraded 일자에도 안정적으로 소비한다.
    preserved = preserve_misses(rows, prior, today)
    if preserved:
        _write(out_path, rows)
        print(f"[preserve] 오늘 MISS 중 {preserved}종을 직전 정본값으로 보존(throttle 방어)")
    canonical_priced = sum(1 for r in rows if str(r.get("가격_KRW", "")).strip())

    metrics = {
        "issue": "CMPA-19",
        "routine": "CMPA-675 (101 · 데일리샷 온라인 최저가 일 1회 수집, 매일 09:00 KST / CMPA-29·276·313). 보드 2026-06-28: pm(18:00) 슬롯이 라이브 산출물 비적재라 일 2회→1회 축소. am/pm 슬롯 코드는 유지(재활성 용이).",
        "cadence": "once-daily (am, 09:00 KST)",
        "collected_date": today,
        "source": "https://api.dailyshot.co/items/search/",
        "scope_stores": "이마트 / 트레이더스 / 코스트코 (롯데마트 제외)",
        "legal_gate": "CEO 해제 완료(2026-05-30 보드 코멘트). CMPA-1 적재는 별도 티켓.",
        "targets": len(targets),
        "hits": hit,
        "hit_rate": round(hit / len(targets), 3) if targets else 0.0,
        "hits_exact": sum(1 for r in hit_rows if r.get("정확도") == "정확"),
        "hits_approx": sum(1 for r in hit_rows if r.get("정확도") == "근접"),
        "price_min": min((r["가격_KRW"] for r in hit_rows), default=None),
        "price_max": max((r["가격_KRW"] for r in hit_rows), default=None),
        # 정본은 throttle MISS 를 직전값으로 보존하므로 'hits'(오늘 관측)보다 클 수 있다.
        "canonical_priced": canonical_priced,
        "preserved_from_prior": preserved,
        "output_csv": os.path.relpath(out_path, ROOT),
        "snapshot_csv": os.path.relpath(snap, ROOT) if snap else None,
        "intraday_snapshot_csv": os.path.relpath(intraday_snap, ROOT),
        "slot": slot,
        # CMPA-321: 셀러별 동반 데이터셋 집계
        "listings_csv": os.path.relpath(listings_path, ROOT),
        "listings_intraday_csv": os.path.relpath(listings_snap, ROOT),
        "listings_rows": len(listing_rows),
        "distinct_sellers": len(_seen),
        "multiseller_products": multiseller,
        # CMPA-322: floor 에서 제외된 면세 리스팅(listings 에는 업종=면세점 태그로 잔존).
        "dutyfree_excluded": dutyfree_listings,   # 수집 전체에서 제외한 면세/해외 리스팅
        "dutyfree_leak": dutyfree_leak,           # 가드레일: 0 이어야 정상(>0 이면 누수)
        # CMPA-352: floor = 제품 페이지 전국 최저가(검색 셀러 min 은 폴백) 채택 집계.
        "floor_source": "item_page_price (검색 셀러 min 폴백)",
        "page_floor_adopted": page_adopted,       # 페이지가를 floor 로 채택한 hit 수
        "page_floor_fallback": page_fallback,     # 페이지 조회 실패→검색가 폴백 hit 수
        "page_floor_lowered": floor_lowered,      # 페이지가가 검색가보다 낮아진 hit 수
        "sellers_cached": len(resolver.cache),
        "sellers_fetched_this_run": resolver.fetched,
        "sellers_resolve_failed": resolver.failed,
    }
    with open(metrics_path, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)

    print("\n".join(diag_all))
    print("\n==== METRICS ====")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
