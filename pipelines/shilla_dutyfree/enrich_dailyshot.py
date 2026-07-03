#!/usr/bin/env python3
"""신라면세 추천 위스키 ↔ 데일리샷(국내 온라인 최대 주류몰) 실시간 대조.

보드 피드백: 우리 국내가 DB(정본 88종)는 커버리지가 좁아, 데일리샷에서 파는 술을
'국내 희귀/면세전용'으로 잘못 표기 → 리포트 신뢰도 하락. 데일리샷 검색 API로 추천
위스키의 **실제 국내 판매가·평점(vivino)**을 직접 확인해 보강한다.

API: GET https://api.dailyshot.co/items/search/?q=<kw>  (키리스)
필드: name, price(KRW), discount_percent, vivino_score, review_count, price_usd

사용: build_lookup(names) -> {신라명: {ds_price, vivino, reviews, ds_name, ds_id, ds_url} | None}
      ds_url = 데일리샷 제품 페이지(/m/item/{top_product_id}, 전국 가격비교·구매)
"""
import json
import re
import time
import urllib.parse
import urllib.request

SEARCH = "https://api.dailyshot.co/items/search/?q={q}"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0 Safari/537.36"
EXCLUDE = ("잔", "패키지", "세트", "미니어처", "선물", "글라스", "잔세트",
           "전용잔", "기획", "보냉", "양말", "노징", "바이알", "소분", "샘플",
           "공병", "보틀링노트")


def small_ml(name):
    """600ml 미만(샘플·500ml 등) 표기면 True — 700/750/1000만 비교."""
    for m in re.finditer(r"(\d{2,4})\s*ml", name.lower()):
        if int(m.group(1)) < 600:
            return True
    return False


def signature(name, brand):
    """브랜드·숫자·용량·일반어 제외한 가장 긴 한글 토큰(예: 아부나흐, 레거시)."""
    n = re.sub(r"[a-zA-Z0-9]+|ml|년|년산|싱글몰트|위스키|캐스크|에디션|컬렉션", " ", name)
    if brand:
        n = n.replace(brand, " ")
    toks = [t for t in re.findall(r"[가-힣]{2,}", n)]
    return max(toks, key=len) if toks else None

# 한글 브랜드 토큰(검색 키워드용)
BRANDS = ["발베니", "글렌피딕", "글렌그란트", "글렌리벳", "글렌파클라스",
          "글렌알라키", "글렌드로낙", "글렌모렌지", "아벨라워", "보모어",
          "라프로익", "라가불린", "아드벡", "맥캘란", "탈리스커", "카발란",
          "부쉬밀", "탐듀", "달모어", "조니워커", "시바스", "발렌타인",
          "로얄살루트", "듀어스", "몽키숄더", "와일드터키", "짐빔", "메이커스",
          "우드포드", "벤리악", "폴존", "암룻", "잭다니엘", "에반윌리엄스"]


def age_of(name):
    m = re.search(r"(\d{1,2})\s*(?:년|y|yo|year)", name.lower())
    return int(m.group(1)) if m else None


def kw_of(name):
    """검색 키워드 = 브랜드 + 숙성년수."""
    nn = name.replace(" ", "")
    brand = next((b for b in BRANDS if b in nn), None)
    age = age_of(name)
    if not brand:
        return None
    return f"{brand} {age}" if age else brand


def http_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def search(kw):
    try:
        d = http_json(SEARCH.format(q=urllib.parse.quote(kw)))
    except Exception:
        return []
    return d if isinstance(d, list) else (d.get("results") or d.get("items") or [])


def best_match(name, items):
    """브랜드+숙성 일치, 잡화 제외, 최저가."""
    nn = name.replace(" ", "")
    brand = next((b for b in BRANDS if b in nn), None)
    age = age_of(name)
    sig = signature(name, brand) if age is None else None  # 무숙성 제품은 표현명 강제
    best = None
    for it in items:
        dn = (it.get("name") or "")
        dnn = dn.replace(" ", "")
        if brand and brand not in dnn:
            continue
        if any(x in dn for x in EXCLUDE) or small_ml(dn):
            continue
        if age is not None and age_of(dn) != age:
            continue
        if sig and sig not in dnn:   # 아부나흐/레거시 등 표현 불일치 제외
            continue
        # 데일리샷이 섞어 보여주는 '면세/해외' 리스팅 제외 (국내 소매가만)
        # price_usd / net_price_usd 가 0보다 크면 면세·해외 가격
        if (it.get("price_usd") or 0) > 0 or (it.get("net_price_usd") or 0) > 0:
            continue
        try:
            price = int(it.get("price") or 0)
        except (ValueError, TypeError):
            continue
        if price <= 0:
            continue
        if best is None or price < best["ds_price"]:
            # 데일리샷 제품 페이지(전국 가격비교) = /m/item/{top_product_id}
            # (검색 item id 가 아니라 top_product_id 가 canonical — og:url 자기참조 확인).
            tpid = it.get("top_product_id") or it.get("id")
            best = {
                "ds_price": price,
                "vivino": it.get("vivino_score"),
                "reviews": it.get("review_count"),
                "ds_name": dn,
                "ds_id": it.get("id"),
                "top_product_id": tpid,
                "ds_url": (f"https://dailyshot.co/m/item/{tpid}" if tpid else None),
            }
    return best


# ── 제품 페이지 실가(페이지 floor) ────────────────────────────────────────
# CMPA-338 근본원인: 검색 API(/items/search) 의 `price` 는 '대표 셀러가'이고,
# 사용자가 링크로 들어가는 제품 페이지(/m/item/{tpid}) 는 **전국 최저 셀러가**를 보여준다.
# 둘이 어긋난다(예: 글렌드로낙16 검색 372,000 vs 페이지 329,000 — 셀러 '피보').
# 따라서 '발행일 라이브 floor' 는 페이지가를 정본으로 쓴다. 페이지 HTML 의
# __NEXT_DATA__(Next.js) 에 dehydrated query 로 price·seller 가 박혀 있어 파싱 가능.
_NEXT_RE = re.compile(
    r'__NEXT_DATA__"[^>]*>(\{.*?\})</script>', re.S)


def _walk_page_price(obj):
    """dehydratedState 안에서 최저 제품가(KRW)와 셀러명을 찾는다. (price, seller)."""
    best_price, best_seller = None, None
    if isinstance(obj, dict):
        p = obj.get("price")
        if isinstance(p, (int, float)) and p > 0 and "name" in obj:
            # 면세/해외(price_usd>0) 는 페이지 floor 에서 제외(CMPA-321 가드).
            if not ((obj.get("price_usd") or 0) > 0):
                seller = obj.get("seller")
                sname = seller.get("name") if isinstance(seller, dict) else None
                best_price, best_seller = int(p), sname
        for v in obj.values():
            cp, cs = _walk_page_price(v)
            if cp is not None and (best_price is None or cp < best_price):
                best_price, best_seller = cp, cs
    elif isinstance(obj, list):
        for v in obj:
            cp, cs = _walk_page_price(v)
            if cp is not None and (best_price is None or cp < best_price):
                best_price, best_seller = cp, cs
    return best_price, best_seller


def item_page_price(tpid):
    """제품 페이지(/m/item/{tpid}) 의 실제 최저 셀러가를 반환. {price, seller} | None.
    네트워크/파싱 실패는 None(비치명) — 호출부가 검색가로 폴백한다."""
    if not tpid:
        return None
    try:
        url = f"https://dailyshot.co/m/item/{tpid}"
        req = urllib.request.Request(url, headers={
            "User-Agent": UA, "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://dailyshot.co/"})
        with urllib.request.urlopen(req, timeout=20) as r:
            html = r.read().decode("utf-8", "replace")
        m = _NEXT_RE.search(html)
        if not m:
            return None
        data = json.loads(m.group(1))
        price, seller = _walk_page_price(
            data.get("props", {}).get("pageProps", {}).get("dehydratedState", {}))
        if price and price > 0:
            return {"price": price, "seller": seller}
    except Exception:
        return None
    return None


def build_lookup(names, pace=0.7, with_page=True):
    """names -> {신라명: best_match | None}.

    '데일리샷 가격(ds_price)' 의 정본 의미 = **제품 페이지(/m/item) 전국 최저 셀러가**.
    보드 확정 2026-06-14(CMPA-344): "앞으로 데일리샷 가격의 의미 자체가 페이지 최저가".
    검색 API `price` 는 대표 셀러가라 실제 전국 최저가보다 높을 수 있다(글렌드로낙16 372k vs
    페이지 329k/피보). 그래서 with_page=True(기본) 면 매칭 항목마다 페이지가를 1회 조회해
    **ds_price 를 페이지가로 덮고**(검색 대표가는 `ds_search_price` 로 보존), `page_price`·
    `seller` 도 채운다. 페이지 조회 실패 시 ds_price 는 검색가로 폴백(비치명).
    면세/해외 제외(CMPA-321)는 페이지 파서(_walk_page_price, price_usd>0 제외)에도 유지."""
    out = {}
    seen = {}
    for nm in names:
        kw = kw_of(nm)
        if not kw:
            out[nm] = None
            continue
        if kw not in seen:
            time.sleep(pace)
            seen[kw] = search(kw)
        m = best_match(nm, seen[kw])
        if with_page and m and m.get("top_product_id"):
            time.sleep(pace)
            pp = item_page_price(m["top_product_id"])
            if pp:
                m["page_price"] = pp["price"]
                m["seller"] = pp.get("seller")
                m["ds_search_price"] = m.get("ds_price")  # 검색 대표가 보존(감사용)
                m["ds_price"] = pp["price"]               # 정본 = 페이지 최저가
        out[nm] = m
    return out


if __name__ == "__main__":
    import sys
    names = sys.argv[1:] or [
        "발베니 12년 Golden Cask 700ml", "글렌피딕 15년 Vat3 Perpetual 700ml",
        "글렌피딕 18년 Vat4 Perpetual 700ml", "발베니 15년 Madeira 700ml",
        "부쉬밀 마르살라 캐스크 21년 700ml", "글렌피딕 21년 700ml",
        "글렌파클라스 15년 700ml", "라가불린 16년 700ml",
    ]
    res = build_lookup(names)
    for nm, m in res.items():
        if m:
            print(f"있음  국내 {m['ds_price']:>8,}원 vivino {m['vivino']} 리뷰{m['reviews']} | {nm[:28]} ← {m['ds_name'][:30]}")
        else:
            print(f"없음(국내 미확인)                       | {nm}")
