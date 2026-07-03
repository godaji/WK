#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
홍콩 위스키 가격 크롤러 — CMPA-14 POC (내부 R&D / 측정·비공개 한정)

주 소스(Watson's Wine)는 Akamai 봇차단(403)으로 단순 HTTP 크롤 불가 → 별도 문서 기록.
보조 소스: 홍콩 위스키 전문 리테일러의 Shopify 공개 storefront API (`/products.json`).
robots.txt 확인: `/products.json` 은 Disallow 대상 아님(차단은 /recommendations/products 뿐). 공개 엔드포인트.

다중 가격 필드 정책:
  Shopify variant 는 `price`(현재 판매가) 와 `compare_at_price`(정가/할인 전) 두 필드를 가진다.
  - 비교 기준가(기준가_HKD) := variant.price  (실제 현재 판매가 = Watson's 'offer' 개념에 대응)
  - 정가_HKD := compare_at_price (있고 price 보다 클 때만; 할인 중이면 기록)
  - 다중 variant(용량 옵션) 일 때: 700/750ml 표준 병을 우선, 없으면 최저가 variant 사용.
  - 재고없음(available=False) 도 가격 신호로 수집하되 비고에 표시.

KRW 환산 + 한국 반입 추정가:
  HKD→KRW = open.er-api.com 실시간(2026-05-30 기준 192.27). 인자로 덮어쓰기 가능.
  반입 추정가(개인수입, 면세한도 초과분 과세):
    관세  = V × 관세율            (일반 20%. UK/EU FTA 시 0% — 원산지별 상이, 보수적 20% 기본)
    주세  = (V + 관세) × 72%
    교육세 = 주세 × 30%
    부가세 = (V + 관세 + 주세 + 교육세) × 10%
    반입추정가 = V + 관세 + 주세 + 교육세 + 부가세
  (V = HKD 판매가의 KRW 환산액을 신고가 proxy 로 사용. 배송·수수료 제외 추정.)
"""
import csv
import json
import os
import sys
import time
import urllib.request

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
from pipelines.common.dated import snapshot  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

SOURCES = [
    {"name": "Caskells",     "domain": "www.caskells.com"},
    {"name": "TheRareMalt",  "domain": "www.theraremalt.com"},
    {"name": "Mizunara",     "domain": "www.mizunaratheshop.com"},
]

WHISKY_KEYS = ("whisky", "whiskey", "bourbon", "위스키")

# 병이 아닌 액세서리/세트/이벤트 → 가격 비교 대상 아님, 제외
EXCLUDE_KEYS = (
    "glass", "glencairn", "decanter", "jigger", "coaster", "book", "cigar",
    "ticket", "event ", "gift card", "gift set", "tote", "badge", "accessor",
    "tasting set", "tasting (", "tasting,", "(5x3cl)", "(3x3cl)", "sample set",
    "tdb wallet", "merch", "t-shirt", "apron",
)


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def is_whisky(p):
    blob = (p.get("product_type", "") + " " + p.get("tags", "") if isinstance(p.get("tags"), str)
            else p.get("product_type", "") + " " + " ".join(p.get("tags", []))).lower()
    title = p.get("title", "").lower()
    if any(k in title for k in EXCLUDE_KEYS):
        return False
    return any(k in blob or k in title for k in WHISKY_KEYS)


def pick_variant(variants):
    """다중 가격/용량 정책: 700/750ml 표준 우선, 없으면 최저가 variant."""
    avail = [v for v in variants if v.get("price")]
    if not avail:
        return None
    def grams(v):
        return v.get("grams") or 0
    std = [v for v in avail if 650 <= grams(v) <= 800] if any(grams(v) for v in avail) else []
    pool = std if std else avail
    return min(pool, key=lambda v: float(v["price"]))


def crawl_source(src, max_pages=10):
    rows = []
    for page in range(1, max_pages + 1):
        url = f"https://{src['domain']}/products.json?limit=250&page={page}"
        data = fetch_json(url)
        products = data.get("products", [])
        if not products:
            break
        for p in products:
            if not is_whisky(p):
                continue
            v = pick_variant(p.get("variants", []))
            if not v:
                continue
            price = float(v["price"])
            if price <= 0:
                continue
            cmp_at = v.get("compare_at_price")
            cmp_at = float(cmp_at) if cmp_at else None
            on_offer = cmp_at is not None and cmp_at > price
            rows.append({
                "source": src["name"],
                "title": p["title"].strip(),
                "price_hkd": round(price, 2),
                "list_hkd": round(cmp_at, 2) if on_offer else "",
                "available": v.get("available", True),
                "url": f"https://{src['domain']}/products/{p['handle']}",
            })
        time.sleep(1.0)  # 예의상 rate-limit
    return rows


def import_estimate_krw(v_krw, tariff=0.20):
    customs = v_krw * tariff
    liquor = (v_krw + customs) * 0.72
    edu = liquor * 0.30
    base = v_krw + customs + liquor + edu
    vat = base * 0.10
    return round(base + vat)


def main():
    fx = float(sys.argv[1]) if len(sys.argv) > 1 else 192.27
    asof = sys.argv[2] if len(sys.argv) > 2 else "2026-05-30"
    out = sys.argv[3] if len(sys.argv) > 3 else "data/whisky-prices/2026-05_hk_whisky_poc.csv"

    all_rows = []
    for src in SOURCES:
        try:
            r = crawl_source(src)
            print(f"[{src['name']}] whisky rows: {len(r)}", file=sys.stderr)
            all_rows.extend(r)
        except Exception as e:
            print(f"[{src['name']}] ERROR: {e}", file=sys.stderr)

    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["술이름", "기준가_HKD", "정가_HKD", "환율_HKDKRW", "기준가_KRW",
                    "반입추정가_KRW_관세20", "반입추정가_KRW_FTA0", "재고",
                    "출처", "가져온날짜", "URL", "비고"])
        for r in all_rows:
            krw = round(r["price_hkd"] * fx)
            note = []
            if r["list_hkd"]:
                note.append(f"할인중(정가 HK${r['list_hkd']})")
            if not r["available"]:
                note.append("재고없음")
            w.writerow([
                r["title"], r["price_hkd"], r["list_hkd"], fx, krw,
                import_estimate_krw(krw, 0.20), import_estimate_krw(krw, 0.0),
                "Y" if r["available"] else "N",
                f"{r['source']}(Shopify products.json)", asof, r["url"],
                "; ".join(note),
            ])
    snap = snapshot(out, run_date=asof if len(asof) == 10 else None)
    print(f"WROTE {len(all_rows)} rows -> {out}", file=sys.stderr)
    if snap:
        print(f"SNAPSHOT -> {snap}", file=sys.stderr)


if __name__ == "__main__":
    main()
