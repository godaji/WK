#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
대만 위스키 가격 크롤러 — CMPA-13 POC (내부 R&D / 측정·비공개 한정)

배경(CMPA-10): 대만은 공식 가격 API 없음 → HTML/JSON 크롤링. 가격이 텍스트라 OCR 불요.

핵심 발견 — 일반 마켓플레이스는 병(bottle) 가격 소스가 아니다
  대만 菸酒管理法(담배주류관리법) 제30조: 신원/연령 확인이 안 되는 통신판매(인터넷·우편·자판기)로
  주류를 팔 수 없다. → PChome 24h / momo購物網 같은 종합몰은 위스키 '잔·제빙기·가구'만 노출하고
  실제 병은 안 판다(검증: PChome v3.3 검색 API 로 麥卡倫/格蘭菲迪 질의 시 위스키 잔·往生紙紮만 반환).
  실제 병 가격은 연령확인·라이선스를 갖춘 '주류 전문 EC' 에만 있다.
    - momo: robots.txt 가 /api/*, /ajax/* Disallow → XHR JSON 수집도 ToS 상 불가.
    - PChome: /search/v3.3/all/results 는 robots 허용이나 병 미취급 → 소스 부적합.

채택 소스 (둘 다 주류 전문 라이선스 리테일러, 실제 병 취급):
  A) my9.com.tw (買酒網)   — Shopify 공개 storefront API `/products.json`.
        product_type == '威士忌' 로 깔끔히 분류됨. robots.txt 가 products.json 미차단.
        → CMPA-14(홍콩) 와 동일 자산 재사용(Shopify 어댑터).
  B) drinks.com.tw (橡木桶 洋酒) — ASP.NET 서버렌더 HTML. 이 POC 의 'HTML 파서' 실증 소스.
        product.aspx?Id=N : og:title=상품명, <li data-type="price">N 元</li>=建議售價(정가),
        '會員價N元'=공개 회원가(비로그인도 HTML 노출). 噶瑪蘭(Kavalan, 대만 현지 위스키) 1차 가치 높음.

가격 필드 정책 (CMPA-14 와 동형):
  - 기준가(現價) := 회원가(會員價) 있으면 그 값, 없으면 建議售價/Shopify price. "지금 사면 내는 값".
  - 정가       := 建議售價/compare_at_price. 기준가보다 클 때만 기록(할인중 표시).

환율 + 한국 반입 추정가: pipelines/common/fx_tax.py 재사용(국가 공통 컴포넌트).
  반입추정가 = KoreaWhiskyImportTax (관세20→배수≈2.556 / FTA0→≈2.130). 스카치=UK FTA 0% 가능,
  대만(Kavalan)·일본 위스키는 무FTA 20% → 두 컬럼 병기로 범위 제시. (CIF proxy=現地價 KRW, 배송 제외.)

재현:
  python3 pipelines/tw_whisky/crawl_tw_whisky.py [환율] [날짜] [출력경로]
  기본: 라이브 TWD→KRW(open.er-api.com)  오늘  data/whisky-prices/2026-05_tw_whisky_poc.csv
"""
import csv
import json
import os
import re
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common.fx_tax import to_krw, import_landed_cost, KR_TAX  # noqa: E402
from common.dated import snapshot  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 위스키 식별 / 액세서리 제외 키워드 (한·중·영)
WHISKY_KEYS = ("威士忌", "single malt", "單一麥芽", "whisky", "whiskey", "bourbon",
               "波本", "蘇格蘭", "噶瑪蘭", "kavalan")
EXCLUDE_KEYS = ("杯", "glass", "glencairn", "醒酒", "decanter", "冰", "ice", "禮盒卡",
                "gift card", "提袋", "tote", "書", "book", "杯墊", "coaster",
                "開瓶", "酒器", "酒架", "櫃", "家具")


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_html(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", errors="replace")


def is_whisky_text(text):
    low = text.lower()
    if any(k in low for k in EXCLUDE_KEYS):
        return False
    return any(k.lower() in low for k in WHISKY_KEYS)


# ----------------------------------------------------------------------------
# Source A — my9.com.tw (Shopify products.json)  [CMPA-14 어댑터 재사용]
# ----------------------------------------------------------------------------
def pick_variant(variants):
    avail = [v for v in variants if v.get("price") and float(v["price"]) > 0]
    if not avail:
        return None

    def grams(v):
        return v.get("grams") or 0
    std = [v for v in avail if 650 <= grams(v) <= 800] if any(grams(v) for v in avail) else []
    pool = std if std else avail
    return min(pool, key=lambda v: float(v["price"]))


def crawl_my9(max_pages=10, rate=1.0):
    domain = "www.my9.com.tw"
    rows, seen_pages = [], 0
    for page in range(1, max_pages + 1):
        data = fetch_json(f"https://{domain}/products.json?limit=250&page={page}")
        products = data.get("products", [])
        if not products:
            break
        seen_pages += 1
        for p in products:
            ptype = p.get("product_type", "")
            title = p.get("title", "")
            # product_type 威士忌 우선, 아니면 제목 키워드. 액세서리 제외.
            if "威士忌" not in ptype and not is_whisky_text(title):
                continue
            if any(k in title.lower() for k in EXCLUDE_KEYS):
                continue
            v = pick_variant(p.get("variants", []))
            if not v:
                continue
            price = float(v["price"])
            cmp_at = v.get("compare_at_price")
            cmp_at = float(cmp_at) if cmp_at else None
            on_offer = cmp_at is not None and cmp_at > price
            rows.append({
                "source": "my9買酒網",
                "title": title.split("||")[0].strip(),
                "base_twd": round(price, 2),                 # 現價
                "list_twd": round(cmp_at, 2) if on_offer else "",
                "available": v.get("available", True),
                "url": f"https://{domain}/products/{p['handle']}",
                "note": "할인중" if on_offer else "",
            })
        time.sleep(rate)
    return rows, seen_pages


# ----------------------------------------------------------------------------
# Source B — drinks.com.tw (橡木桶, ASP.NET 서버렌더 HTML)  [본 POC HTML 파서]
# ----------------------------------------------------------------------------
RE_OG_TITLE = re.compile(r'og:title[^>]+content=["\']([^"\']+)')
RE_RECO_PRICE = re.compile(
    r'Recommend_SalePrice S-->.*?<li[^>]*data-type="price"[^>]*>\s*([\d,]+)\s*元', re.S)
RE_MEMBER = re.compile(r'會員價\s*([\d,]+)\s*元')


def parse_drinks_product(pid):
    """product.aspx?Id=pid → (name, list_twd建議售價, member_twd會員價) or None."""
    html = fetch_html(f"https://www.drinks.com.tw/product.aspx?Id={pid}")
    m = RE_OG_TITLE.search(html)
    if not m:
        return None
    name = re.split(r"[｜|]", m.group(1))[0].strip()
    lm = RE_RECO_PRICE.search(html)
    mm = RE_MEMBER.search(html)
    list_twd = int(lm.group(1).replace(",", "")) if lm else None
    member_twd = int(mm.group(1).replace(",", "")) if mm else None
    return {"name": name, "list_twd": list_twd, "member_twd": member_twd}


def drinks_brand_product_ids(brand_id):
    html = fetch_html(f"https://www.drinks.com.tw/brand.aspx?Id={brand_id}")
    return list(dict.fromkeys(re.findall(r"product\.aspx\?Id=(\d+)", html)))


def crawl_drinks(brand_ids=(320,), sweep_range=None, rate=0.5):
    """
    brand_ids: 위스키 브랜드 (기본 320=噶瑪蘭 Kavalan, 대만 현지 위스키).
    sweep_range: (start, end) 최근 product Id 스윕(파서 hit-rate 측정용).
    반환: (rows, stats) — stats 에 hit-rate 계산용 카운터.
    """
    brand_ids_set, rows = [], []
    for b in brand_ids:
        brand_ids_set += drinks_brand_product_ids(b)
        time.sleep(rate)
    brand_ids_set = list(dict.fromkeys(brand_ids_set))
    sweep_ids = [str(i) for i in range(sweep_range[0], sweep_range[1] + 1)] if sweep_range else []
    candidate_ids = list(dict.fromkeys(brand_ids_set + sweep_ids))
    brand_set = set(brand_ids_set)

    fetched = parsed_name = priced = whisky = 0
    brand_whisky = sweep_whisky = 0
    for pid in candidate_ids:
        try:
            info = parse_drinks_product(pid)
        except Exception:
            time.sleep(rate)
            continue
        fetched += 1
        if not info:
            time.sleep(rate)
            continue
        parsed_name += 1
        base = info["member_twd"] or info["list_twd"]
        if base:
            priced += 1
        if not is_whisky_text(info["name"]) or not base:
            time.sleep(rate)
            continue
        whisky += 1
        if pid in brand_set:
            brand_whisky += 1
        else:
            sweep_whisky += 1
        on_offer = info["list_twd"] and info["member_twd"] and info["list_twd"] > info["member_twd"]
        rows.append({
            "source": "橡木桶drinks",
            "title": info["name"],
            "base_twd": base,
            "list_twd": info["list_twd"] if on_offer else "",
            "available": True,
            "url": f"https://www.drinks.com.tw/product.aspx?Id={pid}",
            "note": "할인중(會員價)" if on_offer else "",
        })
        time.sleep(rate)
    stats = {"candidates": len(candidate_ids), "fetched": fetched,
             "parsed_name": parsed_name, "priced": priced, "whisky_rows": whisky,
             "brand_candidates": len(brand_set), "brand_whisky": brand_whisky,
             "sweep_candidates": len(sweep_ids), "sweep_whisky": sweep_whisky}
    return rows, stats


# ----------------------------------------------------------------------------
# 정규화 + 출력
# ----------------------------------------------------------------------------
HEADER = ["술이름", "기준가_TWD", "정가_TWD", "환율_TWDKRW", "기준가_KRW",
          "반입추정가_KRW_관세20", "반입추정가_KRW_FTA0", "재고", "출처",
          "가져온날짜", "URL", "비고"]


def build_rows(raw_rows, twd_krw, today):
    out = []
    fta_tax = dict(KR_TAX, customs=0.0)  # 한·EU/한·英 FTA: 스카치 등 관세 0%
    for r in raw_rows:
        base_krw = round(to_krw(float(r["base_twd"]), twd_krw))
        landed20 = import_landed_cost(base_krw)["landed_total"]
        landed_fta = import_landed_cost(base_krw, tax=fta_tax)["landed_total"]
        out.append([
            r["title"], r["base_twd"], r["list_twd"], twd_krw, base_krw,
            landed20, landed_fta, "Y" if r["available"] else "N",
            r["source"], today, r["url"], r["note"],
        ])
    return out


def main():
    rate_arg = sys.argv[1] if len(sys.argv) > 1 else None
    today = sys.argv[2] if len(sys.argv) > 2 else None
    out_path = sys.argv[3] if len(sys.argv) > 3 else \
        "data/whisky-prices/2026-05_tw_whisky_poc.csv"

    # 환율: 인자 우선, 없으면 라이브(open.er-api.com)
    if rate_arg:
        twd_krw = float(rate_arg)
        fx_src = f"manual:{rate_arg}"
    else:
        fxj = fetch_json("https://open.er-api.com/v6/latest/TWD")
        twd_krw = round(float(fxj["rates"]["KRW"]), 4)
        fx_src = "open.er-api.com"
    if not today:
        # 날짜 인자 미지정 시 FX 업데이트 일자 사용(스크립트 내 시계 비의존)
        try:
            today = fxj["time_last_update_utc"].split(" +")[0]
            import datetime as _dt
            today = _dt.datetime.strptime(today, "%a, %d %b %Y %H:%M:%S").strftime("%Y-%m-%d")
        except Exception:
            today = "2026-05-30"

    print(f"[FX] 1 TWD = {twd_krw} KRW ({fx_src}, {today})", file=sys.stderr)
    print("[A] my9買酒網 (Shopify products.json) 수집...", file=sys.stderr)
    my9_rows, my9_pages = crawl_my9()
    print(f"    → {len(my9_rows)}종 ({my9_pages} 페이지)", file=sys.stderr)

    print("[B] 橡木桶 drinks.com.tw (HTML) 수집...", file=sys.stderr)
    # 브랜드 타깃 크롤(고수율): 320=噶瑪蘭Kavalan(현지), 3=百富Balvenie, 66=格蘭菲迪Glenfiddich, 89=위스키
    drinks_rows, dstats = crawl_drinks(brand_ids=(320, 3, 66, 89), sweep_range=(23430, 23470))
    hit = (dstats["priced"] / dstats["fetched"] * 100) if dstats["fetched"] else 0
    brand_hit = (dstats["brand_whisky"] / dstats["brand_candidates"] * 100) if dstats["brand_candidates"] else 0
    sweep_hit = (dstats["sweep_whisky"] / dstats["sweep_candidates"] * 100) if dstats["sweep_candidates"] else 0
    print(f"    → {len(drinks_rows)}종 | HTML 파서: 가격추출 {dstats['priced']}/{dstats['fetched']} ({hit:.0f}%) | "
          f"브랜드타깃 위스키 {dstats['brand_whisky']}/{dstats['brand_candidates']} ({brand_hit:.0f}%) vs "
          f"블라인드스윕 {dstats['sweep_whisky']}/{dstats['sweep_candidates']} ({sweep_hit:.0f}%)", file=sys.stderr)

    raw = my9_rows + drinks_rows
    rows = build_rows(raw, twd_krw, today)
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(HEADER)
        w.writerows(rows)
    snap = snapshot(out_path, run_date=today if today and len(today) == 10 else None)

    metrics = {
        "date": today, "fx_twd_krw": twd_krw, "fx_source": fx_src,
        "sources": {
            "my9買酒網(Shopify)": len(my9_rows),
            "橡木桶drinks(HTML)": len(drinks_rows),
        },
        "drinks_html_parser": dstats,
        "drinks_html_price_extract_pct": round(hit, 1),
        "drinks_brand_targeted_whisky_pct": round(brand_hit, 1),
        "drinks_blind_sweep_whisky_pct": round(sweep_hit, 1),
        "total_rows": len(rows),
        "output": out_path,
        "snapshot": snap,
    }
    mpath = os.path.join(os.path.dirname(out_path) or ".", "tw", "_poc_metrics.json")
    os.makedirs(os.path.dirname(mpath), exist_ok=True)
    with open(mpath, "w", encoding="utf-8") as f:
        json.dump(metrics, f, ensure_ascii=False, indent=2)
    print(f"[OUT] {out_path} : {len(rows)} 행", file=sys.stderr)
    print(f"[METRICS] {mpath}", file=sys.stderr)
    print(json.dumps(metrics, ensure_ascii=False), file=sys.stderr)


if __name__ == "__main__":
    main()
