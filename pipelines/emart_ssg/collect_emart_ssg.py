#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
collect_emart_ssg.py — 이마트 SSG(emart.ssg.com) 위스키 가격 수집기 (CMPA-420)

배경 / 왜 이 소스인가
---------------------
국내 트레이더스 현장가는 유튜브 ASR(@whiskeypick/@whiskeykey)에 의존해 불안정하다
(06-01 이후 15일 0행). 이마트 SSG 검색은 **서버 렌더 JSON(`__NEXT_DATA__`)** 에 가격이
그대로 들어 있어 로그인/JS 없이 안정적으로 수집 가능하다(보드 CMPA-419 제보 URL).

수집 방법
---------
- `GET https://emart.ssg.com/search.ssg?query=<위스키|양주|...>` — 로그인/JS 불필요.
- HTML 의 `<script id="__NEXT_DATA__">...</script>` JSON 을 walk 하며
  `itemName`+`finalPrice` 를 가진 dict 를 상품으로 본다.
- 가용 필드: itemName, itemId, finalPrice, strikeOutPrice, discountRate,
  sellUnitCapacity, sellUnitPrice, siteNo, siteName, shppTypeDtlCd, itemUrl,
  reviewCount, needAdultCertification, isVisiblePrice …

⚠️ 채널 라벨링 (정확성 — CLAUDE.md 위치 표기, CMPA-420 검증)
---------------------------------------------------------
실측(2026-06-16): 검색에 노출되는 **진짜 술병**은 전부 `siteNo=6001`(이마트몰)·
`shppTypeDtlCd=31`·`siteName=이마트` 였다. 트레이더스 배송 채널(dvstore_traders /
dispCtgId 6000213467)을 붙여도 같은 이마트몰 가격만 돌아왔다 →
**'트레이더스' 라벨 분리 불가**. 따라서 위치를 정직하게 **`이마트(SSG)`** 로 적는다.
이마트몰 가격을 트레이더스로 오표기하지 않는다.

필터링 (CLAUDE.md 잔세트/번들 삭제 원칙)
----------------------------------------
검색 결과의 대부분은 마켓플레이스(`shppTypeDtlCd=22`, siteName 없음)의 잔/컵/코스터/
받침/브러시 같은 액세서리 노이즈다. 진짜 술병만 남기려면:
  1) 이름 prefix `[위스키]`·`[매장픽업/양주]` 이면 술병(1차 신호).
  2) prefix 없는 경우엔 이마트몰(siteName=이마트) + 위스키 토큰 + 노이즈 게이트 통과만 인정.
  3) prefix 가 비위스키 카테고리(`[스파클링와인]` 등)면 제외.
  4) 액세서리 휴리스틱(잔/글라스/코스터/컵/받침/버킷/브러시/믹서/칵테일 …) + 공통 게이트
     `pipelines/common/whisky_quality.is_quarantined`(번들·비상식가·비제품명) 적용.

출력
----
`data/whisky-prices/YYYY-MM.csv` 에 `이마트(SSG)` 행 append (정본 7컬럼 스키마):
  술이름, 가격_KRW, 위치, 가져온날짜, 출처, 신뢰도, 비고
메트릭: `data/whisky-prices/_emart_ssg_metrics.json`
→ `scripts/normalize_dataset.py` 의 `adapt_domestic` 가 월간 CSV 를 위치 기준으로 읽으므로
  append 만으로 정규화 DB floor·리포트에 자동 통합된다(코스트코/유튜브와 동일 경로).

데이터 관리 (CLAUDE.md 3원칙)
----------------------------
- 가져온날짜 메타 필수, **항목 단위 갱신**(전체 덮어쓰기 금지), 같은 달 재실행 멱등.
- 신뢰도=상(서버 렌더 JSON 정가, ASR/2차 블로그보다 정확).

커버리지 (CMPA-422 실측 — 중요)
-------------------------------
- 카테고리 쿼리 '위스키'(+'양주')가 이마트몰 store-pickup 술병을 **전부 포괄**(현재 9종).
- **브랜드 키워드 쿼리(발베니/맥캘란/조니워커 …)는 술병을 더 못 찾는다**: 마켓플레이스
  잔/디캔터/잡화/의류·잡지 노이즈만 나와 is_bottle 가 정상 기각(16쿼리×375항목→여전히 9종).
- 페이지네이션(page>1)도 이마트몰 술병 수확 0(hasNext=False).
- 근본 원인: 한국법상 일반 온라인 주류배송 금지(전통주만) → 이마트몰 온라인 위스키 카탈로그
  자체가 [매장픽업/양주] 픽업 리스팅 ≈9종으로 얇다(사실상 천장). 브랜드 sweep 은 향후
  대비 옵션(`--brands`)으로만 남기고 일일 수집 기본값은 lean(위스키·양주) 유지.

정중한 크롤 (가드레일)
---------------------
- 요청 간 pace(기본 3s + 랜덤 지터 ≤1.5s), UA 지정, 쿼리/페이지 최소화. 429 시 지수 백오프.
- 일 1회 스냅샷이면 충분(상용 사이트 robots/ToS 존중). CEO 가 빠른 연속요청으로 429 실측.

용법
----
  python3 pipelines/emart_ssg/collect_emart_ssg.py            # 수집 + 해당월 CSV append
  python3 pipelines/emart_ssg/collect_emart_ssg.py --dry-run  # 수집만, 파일 미수정
  python3 pipelines/emart_ssg/collect_emart_ssg.py --queries 위스키 양주
  python3 pipelines/emart_ssg/collect_emart_ssg.py --brands   # 브랜드 풀도 sweep(점검용, 수확≈0)
  python3 pipelines/emart_ssg/collect_emart_ssg.py --pages 1 --sleep 3 --jitter 1.5
"""
import argparse
import datetime
import json
import os
import random
import re
import sys
import time
import urllib.parse

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from pipelines.common.dated import snapshot  # noqa: E402
from pipelines.common.whisky_quality import is_bundle_noise, is_garbage_name  # noqa: E402

SEARCH_URL = "https://emart.ssg.com/search.ssg"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
OUT_DIR = os.path.join(ROOT, "data", "whisky-prices")
METRICS = os.path.join(OUT_DIR, "_emart_ssg_metrics.json")
SCHEMA = ["술이름", "가격_KRW", "위치", "가져온날짜", "출처", "신뢰도", "비고"]
SOURCE_LABEL = "emart.ssg.com"
STORE_LABEL = "이마트(SSG)"   # ⚠️ 트레이더스 아님(검증: 분리 불가) — CMPA-420
# 실측상 [위스키]/[매장픽업/양주] 술병이 노출되는 카테고리 쿼리. 일일 수집 기본값.
DEFAULT_QUERIES = ["위스키", "양주"]
# ── 브랜드 쿼리 풀(--brands 일 때만 추가) — CMPA-422 ─────────────────────────
# ⚠️ 실측 결론(2026-06-16, 16쿼리 375항목): 브랜드 키워드 검색은 이마트몰 '술병'을 더
# 노출하지 못한다(전부 마켓플레이스 잔/디캔터/잡화/의류·잡지 노이즈 → is_bottle 가 정상 기각).
# 카테고리 쿼리 '위스키' 한 개가 이마트몰 store-pickup 술병(현재 9종)을 이미 포괄한다.
# 한국법상 일반 온라인 주류배송 금지(전통주만 허용) → 이마트몰은 [매장픽업/양주] 픽업
# 리스팅만 노출하므로 온라인 위스키 카탈로그 자체가 얇다(≈9종 = 사실상 천장).
# 그래도 향후 이마트몰이 온라인 위스키를 늘릴 경우를 대비해 브랜드 sweep 옵션은 남긴다
# (기본 OFF — 매일 쓰면 요청만 늘려 429 위험↑·수확 0). 운영자가 가끔 점검용으로만 사용.
BRAND_QUERIES = [
    "발렌타인", "조니워커", "시바스리갈", "발베니", "맥캘란", "글렌피딕", "글렌리벳",
    "글렌모렌지", "라프로익", "아벨라워", "싱글몰트", "스카치위스키", "버번위스키",
    "산토리", "야마자키", "히비키", "짐빔", "잭다니엘", "제임슨", "윈저", "임페리얼",
]
PRICE_MIN, PRICE_MAX = 5_000, 5_000_000  # 위스키 1병 KRW 합리범위(저가 미니까지 폭넓게)

NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
# 이름 맨 앞 대괄호 카테고리 prefix 추출: "[위스키] 산토리…" → "위스키"
BRACKET = re.compile(r"^\s*\[([^\]]+)\]")
# 술병 카테고리 prefix(허용)
BOTTLE_PREFIXES = {"위스키", "매장픽업/양주"}
# 비위스키 카테고리 prefix(제외)
NONWHISKY_PREFIXES = {"스파클링와인", "와인", "맥주", "논알콜", "사케", "전통주"}
# 액세서리/잔 노이즈 휴리스틱(이름에 들어 있으면 술병 아님) — CLAUDE.md 잔세트 삭제
ACCESSORY = re.compile(
    r"잔|글라스|글래스|코스터|컵|받침|버[킷켓]|브러[시쉬]|미니어[처쳐]|"
    r"믹서|칵테일|얼음|큐브|디스펜서|텀블러|머그|홀더|정리[대台]|세척|솔|"
    r"디캔터|스포이드|아이스|냉매|냉장|스탠드")
# prefix 없는 술병 후보 인정용 위스키 토큰
WHISKY_TOKENS = ("위스키", "위스키", "스카치", "싱글몰트", "싱글 몰트", "버번", "버본",
                 "블렌디드", "년산", "whisky", "whiskey", "bourbon")


def fetch(session, url, retries=4, base_delay=2.0):
    """200+본문이면 텍스트 반환. 429/오류는 지수 백오프로 재시도."""
    last = None
    for i in range(retries):
        try:
            r = session.get(url, timeout=25)
            if r.status_code == 200 and r.text:
                return r.text
            last = f"http={r.status_code}"
            if r.status_code == 429:
                time.sleep(base_delay * (2 ** i))   # 지수 백오프
                continue
        except requests.RequestException as e:
            last = str(e)
        time.sleep(base_delay * (i + 1))
    sys.stderr.write(f"[warn] fetch 실패 {url}: {last}\n")
    return None


def parse_items(htmlstr):
    """__NEXT_DATA__ JSON 을 walk 하며 itemName+finalPrice dict 수집(itemId 로 dedup)."""
    m = NEXT_DATA.search(htmlstr or "")
    if not m:
        return None
    try:
        data = json.loads(m.group(1))
    except (ValueError, json.JSONDecodeError):
        return None
    out = []

    def walk(o):
        if isinstance(o, dict):
            if "itemName" in o and "finalPrice" in o:
                out.append(o)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    walk(data)
    return list({o.get("itemId"): o for o in out}.values())


def price_to_int(s):
    try:
        return int(str(s).replace(",", "").strip())
    except (ValueError, AttributeError):
        return None


def is_bottle(o):
    """진짜 술병이면 True. 액세서리/번들/비위스키 카테고리는 False."""
    name = (o.get("itemName") or "").strip()
    if not name:
        return False
    if ACCESSORY.search(name):           # 잔/컵/코스터 등 액세서리
        return False
    mb = BRACKET.match(name)
    prefix = mb.group(1).strip() if mb else None
    if prefix in NONWHISKY_PREFIXES:     # [스파클링와인] 등 비위스키 카테고리
        return False
    if prefix in BOTTLE_PREFIXES:        # [위스키]·[매장픽업/양주] = 1차 신호
        return True
    # prefix 없는 후보 — 이마트몰(siteName=이마트) + 위스키 토큰만 보수적 인정
    if (o.get("siteName") or "").strip() == "이마트" and any(t in name for t in WHISKY_TOKENS):
        return True
    return False


def clean_name(name):
    """비고/매칭용으로 카테고리 prefix 제거한 이름. ('[위스키] 산토리 가쿠빈 700ml'→'산토리 가쿠빈 700ml')"""
    return BRACKET.sub("", name or "").strip()


def load_normalizer():
    try:
        from scripts.normalize_whisky_name import Normalizer, load_rules
        return Normalizer(load_rules())
    except Exception as e:  # noqa: BLE001
        sys.stderr.write(f"[info] normalizer 비활성({e}); raw 표기만 기록\n")
        return None


def collect(queries, pages=1, sleep=3.0, jitter=1.5):
    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9"})
    norm = load_normalizer()

    raw_seen, bottles = set(), {}   # itemId → row dict
    stats = {"queries": {}, "items_seen": 0, "bottles": 0, "quarantined": 0, "non_bottle": 0,
             "http_fail": 0}
    for q in queries:
        qcount = 0
        for pg in range(1, pages + 1):
            params = {"query": q}
            if pg > 1:
                params["page"] = pg
            url = SEARCH_URL + "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
            h = fetch(session, url)
            # 정중한 크롤(CMPA-422): 요청 간 sleep + 랜덤 지터로 일정 간격 버스트를 피한다.
            # (CEO 가 빠른 연속요청으로 SSG IP 429 실측 — yt-dlp timedtext 429 교훈과 동일.)
            time.sleep(sleep + random.uniform(0, max(0.0, jitter)))
            if not h:
                stats["http_fail"] += 1
                continue
            items = parse_items(h)
            if items is None:
                stats["http_fail"] += 1
                continue
            for o in items:
                iid = o.get("itemId")
                if iid in raw_seen:
                    continue
                raw_seen.add(iid)
                stats["items_seen"] += 1
                if not is_bottle(o):
                    stats["non_bottle"] += 1
                    continue
                name = clean_name(o.get("itemName"))
                price = price_to_int(o.get("finalPrice"))
                if price is None or not (PRICE_MIN <= price <= PRICE_MAX):
                    stats["non_bottle"] += 1
                    continue
                # 공통 노이즈 게이트(번들/잔세트 + 비제품명) — 수집·정규화·리포트 동일 규칙.
                # ⚠️ 단, ASR용 15,000원 price floor(is_sane_price)는 적용하지 않는다:
                # 그 하한은 ASR 가 'N천원 할인'(5,000/8,000)을 가격으로 오인하는 것을 막기 위한
                # 것인데, SSG 는 서버 JSON 의 '정가'라 그 오인 위험이 없다. 하한을 그대로 쓰면
                # 블랙앤화이트 700ml(9,900) 같은 실제 저가 블렌디드 술병이 탈락한다.
                # → 번들/비제품명만 거르고, 가격 상식은 위 PRICE_MIN/MAX 밴드로만 본다.
                reason = "bundle_glass_set" if is_bundle_noise(name) else (
                    "garbage_name" if is_garbage_name(name) else "")
                if reason:
                    stats["quarantined"] += 1
                    sys.stderr.write(f"[skip:{reason}] {name} ({price:,}원)\n")
                    continue
                if iid in bottles:
                    continue
                # 비고: itemId/채널/용량당단가/할인/URL + 정본 매칭 힌트
                cap = (o.get("sellUnitCapacity") or "").strip()
                unitp = (o.get("sellUnitPrice") or "").strip()
                disc = (o.get("discountRate") or "").strip()
                strike = (o.get("strikeOutPrice") or "").strip()
                note_bits = [f"itemId={iid}",
                             f"채널={o.get('siteName') or '?'}/shpp{o.get('shppTypeDtlCd')}"]
                if cap and unitp:
                    note_bits.append(f"{cap}당 {unitp}원")
                if disc and strike:
                    note_bits.append(f"정가 {strike}→{disc}할인")
                note = "; ".join(note_bits)
                if norm:
                    c = norm.canonicalize(name)
                    if c["status"] == "matched":
                        note = f"정본={c['id']}({c['name_ko']}); " + note
                iu = (o.get("itemUrl") or "").split("&tlidSrchWd")[0]   # 검색어 꼬리 제거
                if iu:
                    note += f"; {iu}"
                bottles[iid] = {
                    "술이름": name, "가격_KRW": price, "위치": STORE_LABEL,
                    "출처": f"WebScrape({SOURCE_LABEL})", "신뢰도": "상", "비고": note,
                }
                qcount += 1
        stats["queries"][q] = qcount
    rows = list(bottles.values())
    stats["bottles"] = len(rows)
    return rows, stats


def month_path(month):
    return os.path.join(OUT_DIR, f"{month}.csv")


def append_rows(rows, month, today):
    import csv
    path = month_path(month)
    exists = os.path.exists(path)
    # 같은 달 (술이름,가격) 중복 방지(멱등). 위치=이마트(SSG) 행만 본다.
    have = set()
    if exists:
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if (r.get("위치") or "").strip() == STORE_LABEL:
                    have.add(((r.get("술이름") or "").strip(),
                              (r.get("가격_KRW") or "").strip()))
    written = 0
    with open(path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if not exists:
            w.writerow(SCHEMA)   # utf-8-sig 가 첫 write 때 BOM 자동 기록(이중 BOM 금지)
        for r in rows:
            key = (r["술이름"], str(r["가격_KRW"]))
            if key in have:
                continue
            have.add(key)
            w.writerow([r["술이름"], r["가격_KRW"], r["위치"], today,
                        r["출처"], r["신뢰도"], r["비고"]])
            written += 1
    return written


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--queries", nargs="*", default=None, help="검색어(기본: 위스키 양주)")
    ap.add_argument("--brands", action="store_true",
                    help="브랜드 쿼리 풀(BRAND_QUERIES)도 추가 sweep — 점검용. "
                         "⚠️ 실측상 이마트몰 술병은 더 안 나온다(429 위험만↑). 기본 OFF.")
    ap.add_argument("--pages", type=int, default=1,
                    help="쿼리당 페이지 수(실측: 이마트몰 술병은 1p에 전부, page>1 수확 0)")
    ap.add_argument("--month", default=None, help="YYYY-MM (기본: 오늘 기준)")
    ap.add_argument("--sleep", type=float, default=3.0, help="요청 간 기본 pace(초)")
    ap.add_argument("--jitter", type=float, default=1.5,
                    help="요청 간 추가 랜덤 지터 상한(초) — 일정 간격 버스트 회피")
    args = ap.parse_args()

    today = datetime.date.today().isoformat()
    month = args.month or today[:7]
    queries = list(args.queries or DEFAULT_QUERIES)
    if args.brands:
        for q in BRAND_QUERIES:
            if q not in queries:
                queries.append(q)

    rows, stats = collect(queries, pages=args.pages, sleep=args.sleep, jitter=args.jitter)
    print(f"=== 이마트 SSG 수집: 술병 {stats['bottles']}종 "
          f"(쿼리 {queries}, 항목 {stats['items_seen']} / 비술병 {stats['non_bottle']} / "
          f"격리 {stats['quarantined']} / http실패 {stats['http_fail']}) ===")
    for r in sorted(rows, key=lambda x: x["가격_KRW"]):
        print(f"  {r['가격_KRW']:>9,}  {r['술이름']}")

    if args.dry_run:
        print("\n[dry-run] CSV 미수정.")
        return
    written = append_rows(rows, month, today)
    snap = snapshot(month_path(month), run_date=today)
    metrics = {
        "source": SOURCE_LABEL, "store_label": STORE_LABEL,
        "queries": queries, "pages": args.pages,
        "stats": stats, "collected_date": today,
        "rows_written": written, "month_file": f"{month}.csv",
        "snapshot": os.path.relpath(snap, ROOT) if snap else None,
        "traders_channel_separable": False,   # CMPA-420 검증 결론
    }
    with open(METRICS, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"\n→ {month}.csv 에 신규 {written}행 append (위치={STORE_LABEL}, 중복 제외). 메트릭: {METRICS}")
    if snap:
        print(f"→ 실행 스냅샷: {os.path.relpath(snap, ROOT)}")


if __name__ == "__main__":
    main()
