#!/usr/bin/env python3
"""신라면세점(Shilla Duty Free) 주류(c/1200) 위스키 수집기.

GNB 위스키 메뉴가 가리키는 카테고리 1200(주류) 전체 상품을 키리스 AJAX
엔드포인트(/estore/kr/ko/ajaxProducts)로 페이지네이션 수집한 뒤,
disp2Depth 카테고리 라벨에 '위스키/Whisky'가 포함된 행만 위스키로 분류한다.

가격은 면세 표준 USD 기준:
  - salePrice      : 할인 전 표시가 (원가)
  - discountPrice  : 할인가(게스트가) = 사이트에 노출되는 판매가
  - discountRate   : 할인율(%)
주의: 신라면세 PLP 가격은 달러(USD)로 노출된다(국내 마트가와 다른 채널).

산출물:
  data/shilla-dutyfree/신라면세_위스키_<run_date>.csv  (위스키만, 메인 산출물)
  data/shilla-dutyfree/신라면세_주류전체_<run_date>.csv (참고: 주류 1200 전체)

사용법:
  python3 pipelines/shilla_dutyfree/crawl_shilla_whisky.py [--date YYYY-MM-DD]
"""
import argparse
import csv
import http.cookiejar
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

CATEGORY = "1200"  # 주류 (GNB 위스키 진입점)
BASE = "https://www.shilladfs.com/estore/kr/ko"
LIST_URL = BASE + f"/c/{CATEGORY}"
AJAX_URL = BASE + "/ajaxProducts"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0 Safari/537.36")
PAGE_SIZE = 100

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
OUT_DIR = os.path.join(ROOT, "data", "shilla-dutyfree")


def make_session():
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    op.addheaders = [("User-Agent", UA)]
    html = op.open(LIST_URL, timeout=30).read().decode("utf-8", "replace")
    m = re.search(r'CSRFToken" value="([^"]+)"', html)
    if not m:
        raise RuntimeError("CSRF 토큰을 페이지에서 찾지 못함")
    return op, m.group(1)


def fetch_page(op, token, page):
    payload = {
        "category": CATEGORY, "sort": "topSelling", "size": PAGE_SIZE,
        "page": page, "text": "", "within": "", "query": "",
        "pagination": "", "condition": {},
    }
    body = urllib.parse.urlencode(
        {"json": json.dumps(payload, ensure_ascii=False)}).encode()
    req = urllib.request.Request(AJAX_URL, data=body)
    req.add_header("CSRFToken", token)
    req.add_header("X-Requested-With", "XMLHttpRequest")
    req.add_header("Referer", LIST_URL)
    req.add_header("Content-Type",
                   "application/x-www-form-urlencoded; charset=UTF-8")
    return json.loads(op.open(req, timeout=30).read().decode("utf-8", "replace"))


def is_whisky(cats):
    for c in cats or []:
        label = c.split(":", 1)[-1].lower()
        if "위스키" in c or "whisky" in label or "whiskey" in label:
            return True
    return False


def cat_label(cats):
    return "; ".join(cats or [])


def row_of(p):
    up = p.get("userPrice") or {}
    sale = up.get("salePrice")
    disc = p.get("discountPrice")
    if disc is None:
        disc = up.get("discountPrice")
    # 신라가 앱/웹에 표시하는 가격 = mileageDcPrice (마일리지 할인가)
    # discountPrice(5% 게스트가)는 UI에 노출되지 않음 — mileageDcPrice가 표시가
    milage_dc = up.get("mileageDcPrice")
    milage_rate = up.get("mileageDcRate")
    stock = p.get("stockAvailable")
    return {
        "위스키명": p.get("productNameForDisp") or p.get("name") or "",
        "브랜드": p.get("brandDisplayName") or p.get("brandName") or "",
        "표시가_USD": milage_dc,   # 신라 앱/웹 표시가 (마일리지 할인가)
        "마일리지할인율_%": milage_rate,
        "할인가_USD": disc,         # 게스트가 (5% 즉시할인, UI에 미노출)
        "정상가_USD": sale,
        "할인율_%": p.get("discountRate"),
        "누적판매": p.get("accumInterTotalQuantity"),
        "리뷰수": p.get("reviewCountByTipping"),
        "평점": p.get("avgReviewRatingByTipping"),
        "재고": stock,
        "구매가능": "Y" if (p.get("allowProductPurchase") and (stock or 0) > 0) else "N",
        "소분류": cat_label(p.get("disp2DepthCategoryList")),
        "상품코드": p.get("code"),
        "SKU": p.get("skuNo"),
        "상품URL": f"{BASE}/p/{p.get('code')}" if p.get("code") else "",
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"),
                    help="run date for filename (KST 권장)")
    args = ap.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    op, token = make_session()
    first = fetch_page(op, token, 0)
    pg = first["pagination"]
    total, npages = pg["totalNumberOfResults"], pg["numberOfPages"]
    print(f"카테고리 {CATEGORY}(주류) 총 {total}건 / {npages}페이지(@{PAGE_SIZE})")

    seen = set()
    all_rows = []
    pages = list(range(npages))
    results = first["results"]
    for page in pages:
        if page != 0:
            time.sleep(0.8)
            try:
                results = fetch_page(op, token, page)["results"]
            except Exception as e:
                print(f"  page {page} 실패: {e}", file=sys.stderr)
                continue
        for p in results:
            code = p.get("code")
            if code in seen:
                continue
            seen.add(code)
            r = row_of(p)
            r["_is_whisky"] = is_whisky(p.get("disp2DepthCategoryList"))
            all_rows.append(r)
        print(f"  page {page}: 누적 {len(all_rows)}건")

    whisky = [r for r in all_rows if r.pop("_is_whisky", False)]
    for r in all_rows:
        r.pop("_is_whisky", None)

    fields = ["위스키명", "브랜드", "표시가_USD", "마일리지할인율_%",
              "할인가_USD", "정상가_USD", "할인율_%",
              "누적판매", "리뷰수", "평점", "재고", "구매가능",
              "소분류", "상품코드", "SKU", "상품URL"]
    w_path = os.path.join(OUT_DIR, f"신라면세_위스키_{args.date}.csv")
    a_path = os.path.join(OUT_DIR, f"신라면세_주류전체_{args.date}.csv")
    for path, rows in ((w_path, whisky), (a_path, all_rows)):
        with open(path, "w", newline="", encoding="utf-8-sig") as f:
            wr = csv.DictWriter(f, fieldnames=fields)
            wr.writeheader()
            wr.writerows(rows)
    print(f"\n위스키 {len(whisky)}건 -> {w_path}")
    print(f"주류 전체 {len(all_rows)}건 -> {a_path}")


if __name__ == "__main__":
    main()
