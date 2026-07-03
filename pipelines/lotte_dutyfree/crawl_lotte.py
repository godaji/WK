#!/usr/bin/env python3
"""롯데면세점(lottedfs.com) 위스키 카탈로그 크롤러 — CMPA-647.

**수집 방법(보드 제보 엔드포인트, CMPA-647 코멘트):**
카테고리 리스트 AJAX `GET /kr/search/searchShopAjax` 가 상품 카드 HTML 을 **서버 렌더로**
돌려준다. 카드 안에 한글 상품명·브랜드·정상가($)·할인가($)·할인율(%)·원화환산가가 모두
인라인으로 박혀 있어 **Playwright 도, 상품별 추가 호출도 불필요**하다(전부 GET, Incapsula
throttle 무관·재현성 최상).

위스키 = 주류(tcat 10055924) > 위스키(mcat 10055930) 의 3개 소分류:
  싱글 몰트(10055960) · 블렌디드(10055954) · 기타 위스키(10055966).
각 소分류를 `scatCD = "10055924^10055930^<scat>"` 로 필터해 페이지네이션하면 위스키만 모인다
(2026-06 기준 싱글몰트 239 · 블렌디드 103 · 기타 70 ≈ 412종).

⚠️ 면세가 가드(CMPA-321): 가격은 전부 **면세가**(세금 0·출국 조건, USD)다. 국내 최저가로
   쓰면 안 된다. `is_dutyfree_listing()` 가 모든 행을 면세로 표시하고 CSV `is_dutyfree=True`.
   향후 대시보드/리포트는 신라면세와 동일 취급.

출력 CSV: `assets/lotte_dutyfree/YYYY-MM_lotte_whisky.csv`
  컬럼: prd_no, prd_opt_no, name, brand, volume_ml, regular_price, sale_price,
        discount_pct, currency, krw_price, category, is_dutyfree, collected_at

사용:
  python -m pipelines.lotte_dutyfree.crawl_lotte            # 전체 위스키 → CSV
  python -m pipelines.lotte_dutyfree.crawl_lotte --dry-run  # CSV 안 쓰고 요약만
  python -m pipelines.lotte_dutyfree.crawl_lotte --limit 50 # 소分류당 앞 50종(점검)
"""
from __future__ import annotations

import argparse
import csv
import html
import random
import re
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    requests = None

BASE = "https://kor.lottedfs.com"
SEARCH_URL = f"{BASE}/kr/search/searchShopAjax"
CATEGORY_LANDING = (f"{BASE}/kr/display/category/first"
                    "?dispShopNo1=10055924&dispShopNo2=10055930&treDpth=2")
SITEMAP_URL = "https://www.lottedfs.com/krsitemap.xml"  # (참고용, 더는 주 경로 아님)

# 주류(10055924) > 위스키(10055930) 의 소分류. scatCD 는 tcat^mcat^scat 트리플렛.
WHISKY_SUBCATS = {
    "싱글 몰트": "10055924^10055930^10055960",
    "블렌디드": "10055924^10055930^10055954",
    "기타 위스키": "10055924^10055930^10055966",
}

CHROME_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)

ASSET_DIR = Path(__file__).resolve().parents[2] / "assets" / "lotte_dutyfree"

CSV_COLUMNS = [
    "prd_no", "prd_opt_no", "name", "brand", "volume_ml",
    "regular_price", "sale_price", "discount_pct", "currency", "krw_price",
    "category", "is_dutyfree", "collected_at",
]


# --------------------------------------------------------------------------- #
# 순수 파서 (네트워크 무관 — 단위 테스트 대상)
# --------------------------------------------------------------------------- #
def parse_volume_ml(name: str) -> int | None:
    """상품명에서 용량(ml)을 파싱. 700ml / 750ML / 1L / 1.75L / 1000ml 등 지원."""
    if not name:
        return None
    s = name.upper().replace(",", "")
    m = re.search(r"(\d+(?:\.\d+)?)\s*ML", s)
    if m:
        try:
            return int(round(float(m.group(1))))
        except ValueError:
            return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*L(?![A-Z])", s)
    if m:
        try:
            return int(round(float(m.group(1)) * 1000))
        except ValueError:
            return None
    return None


def is_dutyfree_listing(row: dict) -> bool:
    """CMPA-321 가드. 롯데면세 수집물은 정의상 전부 면세 리스팅이라 항상 True.

    국내 최저가 파이프라인이 실수로 면세가를 섞지 않도록 모든 행을 면세로 표시한다
    (신라면세 ``service_type==5`` 와 동등한 자가완결 신호 — 소스가 면세점이므로 항상 True).
    """
    return True


def _amt(s: str | None) -> float | None:
    if s is None:
        return None
    try:
        return float(s.replace(",", ""))
    except ValueError:
        return None


def parse_listing_cards(html_text: str, category: str = "") -> list[dict]:
    """``searchShopAjax`` 응답 HTML 의 상품 카드들을 파싱.

    카드 1개 = ``<li><!-- 1. 상품정보 --> ... </li>``. 각 카드에서:
      - prdNo(``data-prdNo``), prdOptNo(onclick ``ga_adltCheckPrdDtlMove``)
      - 한글 상품명(``span.name``), 브랜드(``i.kor``)
      - 정상가(``price01`` $, 할인 없으면 생략 → 판매가와 동일 처리)
      - 판매가(``price02`` $) + 할인율(``i.sale`` %)
      - 원화환산가(``price03`` 원)
    """
    rows: list[dict] = []
    cards = re.split(r"<li>\s*<!-- 1\. 상품정보 -->", html_text)[1:]
    for c in cards:
        m_prd = re.search(r'data-prdNo="(\d+)"', c)
        if not m_prd:
            continue
        m_opt = re.search(r"ga_adltCheckPrdDtlMove\(&#39;\d+&#39;,&#39;(\d+)&#39;", c)
        m_name = re.search(r'<span class="name">(.*?)</span>', c, re.S)
        m_brand = re.search(r'<i class="kor">(.*?)</i>', c, re.S)
        m_reg = re.search(r'price01">&#x0024;([\d,.]+)', c)
        m_sale = re.search(r'price02"[^>]*>(?:<th:bock>)?&#x0024;([\d,.]+)', c)
        m_dc = re.search(r'class="sale">(\d+)&#x0025;', c)
        m_krw = re.search(r'price03">([\d,]+)&#xC6D0;', c)

        sale = _amt(m_sale.group(1)) if m_sale else None
        regular = _amt(m_reg.group(1)) if m_reg else None
        if regular is None:           # 할인 없는 상품 → 정상가=판매가
            regular = sale
        if m_dc:
            discount = float(m_dc.group(1))
        elif regular and sale and sale < regular:
            discount = round((regular - sale) / regular * 100, 1)
        else:
            discount = 0.0
        rows.append({
            "prd_no": m_prd.group(1),
            "prd_opt_no": m_opt.group(1) if m_opt else "",
            "name": html.unescape(m_name.group(1).strip()) if m_name else "",
            "brand": html.unescape(m_brand.group(1).strip()) if m_brand else "",
            "regular_price": regular,
            "sale_price": sale,
            "discount_pct": discount,
            "currency": "USD",
            "krw_price": m_krw.group(1).replace(",", "") if m_krw else "",
            "category": category,
        })
    return rows


def parse_total_count(html_text: str) -> int | None:
    """리스트 응답의 총 상품 수(``totalCnt``)."""
    m = re.search(r'totalCnt["\s:=]+["\']?(\d+)', html_text)
    return int(m.group(1)) if m else None


# --------------------------------------------------------------------------- #
# 네트워크
# --------------------------------------------------------------------------- #
def _session() -> "requests.Session":
    s = requests.Session()
    s.headers.update({
        "User-Agent": CHROME_UA,
        "Referer": CATEGORY_LANDING,
        "X-Requested-With": "XMLHttpRequest",
    })
    return s


def fetch_listing(session, scat_cd: str, start: int, count: int) -> str:
    params = {
        "collection": "GOODS", "shopSchYn": "Y",
        "startCount": start, "listCount": count,
        "sort": "ORD_QTY/DESC,PRD_OPT_NO_INT/DESC",
        "clickPoint": "B003", "priceMin": "0.0", "priceMax": "0.0",
        "curPageNo": start // count + 1,
        "tcatCD": "", "mcatCD": "", "scatCD": scat_cd,
    }
    r = session.get(SEARCH_URL, params=params, timeout=25)
    r.raise_for_status()
    return r.text


def _pace(lo: float = 0.4, hi: float = 1.0) -> None:
    time.sleep(random.uniform(lo, hi))


def crawl_subcat(session, name: str, scat_cd: str,
                 page_size: int = 100, limit: int | None = None,
                 pace: bool = True) -> list[dict]:
    """한 소分류 전체를 페이지네이션하며 수집."""
    rows: list[dict] = []
    start = 0
    total = None
    while True:
        html_text = fetch_listing(session, scat_cd, start, page_size)
        if total is None:
            total = parse_total_count(html_text)
        page = parse_listing_cards(html_text, category=f"주류/위스키/{name}")
        rows.extend(page)
        got = len(page)
        print(f"  [{name}] {start+got}/{total if total is not None else '?'}"
              f" (이번 {got}종)")
        start += page_size
        if got < page_size or (limit and len(rows) >= limit) \
                or (total is not None and start >= total):
            break
        if pace:
            _pace()
    if limit:
        rows = rows[:limit]
    return rows


# --------------------------------------------------------------------------- #
# 오케스트레이션
# --------------------------------------------------------------------------- #
def crawl(limit: int | None = None, pace: bool = True) -> list[dict]:
    """위스키 3개 소分류 전체 수집 → 중복(prdNo) 제거 후 CSV 행 리스트 반환."""
    session = _session()
    collected_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # 워밍업(쿠키)
    try:
        session.get(CATEGORY_LANDING, timeout=25)
    except Exception:  # noqa: BLE001
        pass

    seen: set[str] = set()
    out: list[dict] = []
    for name, scat in WHISKY_SUBCATS.items():
        print(f"[수집] {name}")
        for r in crawl_subcat(session, name, scat, limit=limit, pace=pace):
            if not r["prd_no"] or r["prd_no"] in seen:
                continue
            if not r["sale_price"]:
                print(f"  - 가격없음 스킵: {r['prd_no']} {r['name']}", file=sys.stderr)
                continue
            seen.add(r["prd_no"])
            vol = parse_volume_ml(r["name"])
            if vol is not None and vol < 500:  # CMPA-733: 500ml 미만 소용량 수집 금지
                print(f"  - 소용량 스킵({vol}ml): {r['name']}", file=sys.stderr)
                continue
            r["volume_ml"] = vol
            r["is_dutyfree"] = True
            r["collected_at"] = collected_at
            assert is_dutyfree_listing(r)  # CMPA-321 가드
            out.append(r)
        if pace:
            _pace()
    print(f"[완료] 위스키 {len(out)}종(중복 제거)")
    return out


def _write_one(rows: list[dict], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in CSV_COLUMNS})
    return path


def write_csv(rows: list[dict], path: Path | None = None,
              snapshot: bool = True) -> Path:
    """월별 'latest' CSV + 날짜별 스냅샷을 함께 기록한다.

    CMPA-156(누적 기록) 준수: '오늘부터 매일 수집' 시 각 수집일을 보존하기 위해
    ``snapshots/YYYY-MM-DD_lotte_whisky.csv`` 를 남긴다. 월별 파일은 최신값(latest)이며
    각 행의 ``collected_at`` 으로 수집 시점을 알 수 있다.
    """
    if path is None:
        ym = date.today().strftime("%Y-%m")
        path = ASSET_DIR / f"{ym}_lotte_whisky.csv"
    _write_one(rows, path)
    if snapshot:
        snap = ASSET_DIR / "snapshots" / f"{date.today():%Y-%m-%d}_lotte_whisky.csv"
        _write_one(rows, snap)
        print(f"스냅샷 기록: {snap}")
    return path


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="롯데면세점 위스키 크롤러 (CMPA-647)")
    ap.add_argument("--limit", type=int, default=None,
                    help="소分류당 앞 N종만(점검용)")
    ap.add_argument("--no-pace", action="store_true", help="요청 간 딜레이 끄기")
    ap.add_argument("--dry-run", action="store_true", help="CSV 안 쓰고 요약만")
    ap.add_argument("--out", type=str, default=None, help="출력 CSV 경로 직접 지정")
    args = ap.parse_args(argv)

    if requests is None:
        print("requests 모듈이 필요합니다.", file=sys.stderr)
        return 2

    rows = crawl(limit=args.limit, pace=not args.no_pace)
    if not rows:
        print("수집 0건 — 사이트 구조 변경 또는 차단 가능성. 보고 필요.", file=sys.stderr)
        return 1
    n_null = sum(1 for r in rows if not r["sale_price"])
    n_vol = sum(1 for r in rows if r["volume_ml"])
    n_dc = sum(1 for r in rows if r["discount_pct"])
    print(f"\n검증: 행 {len(rows)} / 가격null {n_null} / 용량파싱 {n_vol}"
          f" ({n_vol/len(rows)*100:.0f}%) / 할인표기 {n_dc}")
    if args.dry_run:
        print("[dry-run] CSV 미기록")
        return 0
    out = write_csv(rows, Path(args.out) if args.out else None)
    print(f"CSV 기록: {out} ({len(rows)}행)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
