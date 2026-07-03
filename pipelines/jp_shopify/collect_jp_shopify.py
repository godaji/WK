#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
일본 위스키 가격 크롤러 — CMPA-52 (Rakuten 대안: 키 불필요 Shopify products.json).

배경(메모리 cmpa11/cmpa47): Rakuten Ichiba API 는 board 가 제공해야 하는 RAKUTEN_APP_ID
(에이전트가 셀프 발급 불가)에 막혀 LIVE 수집이 멈춰 있다. 대안으로, 홍콩(CMPA-14)에서
검증된 **Shopify 공개 storefront API(`/products.json`) — API 키 불필요** 패턴을 일본
주류 리테일러에 그대로 적용한다. 에이전트가 즉시·단독 실행 가능(블로커 없음).

소스(검증 완료, 2026-05-31): 모두 Shopify, /products.json HTTP200, 위스키 500+종.
robots.txt 는 /collections/*sort_by* 등 필터 변형만 Disallow — `/products.json` 은 허용
(홍콩과 동일 법무 포지션: 공개 엔드포인트, 비공개 R&D 측정용).

가격 정책(HK 재사용): variant.price = 현재 판매가(기준가), compare_at_price 가 더 크면
할인중으로 기록. 700/750ml 표준 우선, 없으면 최저가 variant.
환산/반입세: pipelines.common.fx_tax (CMPA-11에서 추출한 국가무관 컴포넌트) 재사용.

Usage:
  python3 pipelines/jp_shopify/collect_jp_shopify.py            # FX 자동(open.er-api), 오늘(KST)
  python3 pipelines/jp_shopify/collect_jp_shopify.py 9.46 2026-05-31 out.csv
"""
from __future__ import annotations

import csv
import json
import os
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, ROOT)
from pipelines.common.fx_tax import to_krw, import_landed_cost  # noqa: E402
from pipelines.common.dated import snapshot, kst_today  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

# 검증된 일본 주류 Shopify 스토어프론트(키 불필요). 신뢰 채널(정식 주류 소매)만.
SOURCES = [
    {"name": "酒類ドットコム(syurui)", "domain": "www.syurui.co.jp"},
    {"name": "SAKE People",            "domain": "sake-people.com"},
    {"name": "酒庫住田屋(sumidaya)",   "domain": "shop.sumidaya.co.jp"},
]

# 위스키 식별(제목/타입/태그 어디든). 일본어/영어 동시.
WHISKY_KEYS = ("ウイスキー", "ウィスキー", "whisky", "whiskey", "バーボン", "モルト",
               "スコッチ", "ブレンデッド")
# 병이 아닌 것 → 가격 비교 대상 아님(라핑/세트/잔/글래스/티셔츠/장식/샘플).
EXCLUDE_KEYS = ("ラッピング", "包装", "グラス", "タンブラー", "セット", "ギフトセット",
                "クーポン", "ノベルティ", "tシャツ", "ｔシャツ", "コースター", "空瓶",
                "飲み比べ", "ミニチュア セット", "詰め合わせ", "gift card")


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA,
                                               "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def _blob(p):
    tags = p.get("tags", [])
    tags = tags if isinstance(tags, str) else " ".join(tags)
    return (p.get("title", "") + " " + p.get("product_type", "") + " " + tags).lower()


def is_whisky(p):
    blob = _blob(p)
    if any(k in blob for k in EXCLUDE_KEYS):
        return False
    return any(k in blob for k in WHISKY_KEYS)


def pick_variant(variants):
    """700/750ml 표준(grams 650~800) 우선, 없으면 최저가 variant."""
    avail = [v for v in variants if v.get("price")]
    if not avail:
        return None
    def grams(v):
        return v.get("grams") or 0
    std = [v for v in avail if 650 <= grams(v) <= 800] if any(grams(v) for v in avail) else []
    pool = std if std else avail
    return min(pool, key=lambda v: float(v["price"]))


def crawl_source(src, max_pages=20):
    rows = []
    for page in range(1, max_pages + 1):
        url = f"https://{src['domain']}/products.json?limit=250&page={page}"
        try:
            data = fetch_json(url)
        except Exception as e:  # noqa: BLE001
            print(f"  ! {src['name']} page{page}: {e}", file=sys.stderr)
            break
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
                "price_jpy": round(price),
                "list_jpy": round(cmp_at) if on_offer else "",
                "available": v.get("available", True),
                "url": f"https://{src['domain']}/products/{p['handle']}",
            })
        time.sleep(1.0)  # 예의상 rate-limit
    return rows


def main():
    # FX: 인자 우선, 없으면 라이브(open.er-api) 시도, 실패 시 보수적 폴백.
    if len(sys.argv) > 1:
        fx = float(sys.argv[1])
    else:
        try:
            from pipelines.common.fx_fetch import fx_snapshot
            fx = float(fx_snapshot()["rates"]["JPY"])  # 1 JPY -> KRW
        except Exception:  # noqa: BLE001
            fx = 9.458761  # 2026-05-30 폴백
    asof = sys.argv[2] if len(sys.argv) > 2 else kst_today()
    out = sys.argv[3] if len(sys.argv) > 3 else os.path.join(
        ROOT, "data", "whisky-prices", "jp", f"{asof[:7]}_jp_shopify_poc.csv")

    all_rows = []
    for src in SOURCES:
        r = crawl_source(src)
        print(f"[{src['name']}] whisky rows: {len(r)}", file=sys.stderr)
        all_rows.extend(r)

    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["술이름", "기준가_JPY", "정가_JPY", "환율_1JPY_KRW", "기준가_KRW",
                    "한국반입추정가_KRW", "반입배수", "재고", "출처", "가져온날짜", "URL", "비고"])
        for r in all_rows:
            krw = round(to_krw(r["price_jpy"], fx))
            tax = import_landed_cost(krw)
            note = []
            if r["list_jpy"]:
                note.append(f"할인중(정가 ¥{r['list_jpy']})")
            if not r["available"]:
                note.append("재고없음")
            w.writerow([
                r["title"], r["price_jpy"], r["list_jpy"], fx, krw,
                tax["landed_total"], tax["multiplier"],
                "Y" if r["available"] else "N",
                f"{r['source']}(Shopify products.json)", asof, r["url"],
                "; ".join(note),
            ])
    snap = snapshot(out, run_date=asof if len(asof) == 10 else None)
    print(f"WROTE {len(all_rows)} rows -> {out}  (fx 1JPY={fx} KRW)", file=sys.stderr)
    if snap:
        print(f"SNAPSHOT -> {snap}", file=sys.stderr)


if __name__ == "__main__":
    main()
