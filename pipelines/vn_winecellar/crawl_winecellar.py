#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
베트남 Wine Cellar (winecellar.vn) 위스키·스피릿 가격 크롤러 — CMPA-788

베트남 현지에서 방문 가능한 프리미엄 주류 리테일러.
모든 스피릿 카테고리를 긁어 가격(VND)을 수집하고 KRW 환산·반입추정가를 계산한다.

사용법:
  python3 pipelines/vn_winecellar/crawl_winecellar.py

출력:
  data/whisky-prices/{YM}_vn_winecellar.csv

KRW 환산:
  data/whisky-prices/fx/fx_latest.json 의 USD/KRW 와 실시간 USD/VND cross-rate 사용.
  fallback: FALLBACK_VND_PER_USD = 25,400.

반입추정가 (개인 휴대, 면세 한도 초과분 과세):
  관세 20% → 주세 72% → 교육세 30% → 부가세 10%
  (CMPA-788 범위. 배송/운임 제외. 원산지별 FTA 변수 미적용.)
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time
import urllib.request
from typing import Optional

import requests
from bs4 import BeautifulSoup

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(ROOT, "data", "whisky-prices")

sys.path.insert(0, ROOT)
try:
    from pipelines.common.dated import kst_today, snapshot
except ImportError:
    from datetime import date, datetime
    import pytz
    def kst_today():
        return datetime.now(pytz.timezone("Asia/Seoul")).date().isoformat()
    def snapshot(prefix, suffix, date_str=None):
        d = date_str or kst_today()
        return f"{prefix}{d}{suffix}"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

BASE_URL = "https://winecellar.vn/en/spirits/"
FALLBACK_VND_PER_USD = 25_400  # 2026-07 기준 보수적 폴백


# ---------------------------------------------------------------------------
# FX
# ---------------------------------------------------------------------------

def _load_krw_per_usd() -> float:
    fx_path = os.path.join(DATA, "fx", "fx_latest.json")
    try:
        with open(fx_path, encoding="utf-8") as f:
            data = json.load(f)
        return float(data["raw_usd"]["KRW"])
    except Exception:
        return 1_530.0


def _fetch_vnd_per_usd() -> float:
    """open.er-api.com 에서 USD/VND 실시간 환율."""
    try:
        req = urllib.request.Request(
            "https://open.er-api.com/v6/latest/USD",
            headers={"User-Agent": UA}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.load(r)
        return float(data["rates"]["VND"])
    except Exception as e:
        print(f"  [FX] VND 환율 조회 실패 ({e}), 폴백 {FALLBACK_VND_PER_USD:,} 사용")
        return FALLBACK_VND_PER_USD


def calc_krw(vnd: float, vnd_per_usd: float, krw_per_usd: float) -> int:
    if vnd <= 0:
        return 0
    return round(vnd / vnd_per_usd * krw_per_usd)


def calc_import_est(krw: int) -> int:
    """
    개인 반입 추정가 (세금만, 배송비 제외):
      관세(20%) → 주세(72%) → 교육세(30%) → 부가세(10%)
    """
    if krw <= 0:
        return 0
    customs = krw * 0.20
    liquor_tax = (krw + customs) * 0.72
    edu_tax = liquor_tax * 0.30
    vat = (krw + customs + liquor_tax + edu_tax) * 0.10
    return round(krw + customs + liquor_tax + edu_tax + vat)


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

HEADERS = {"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
PACE_S = 1.5  # 요청 간격 (예의 있게)


def _fetch_page(page: int) -> Optional[str]:
    url = BASE_URL if page == 1 else f"{BASE_URL}page/{page}/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text
    except requests.RequestException as e:
        print(f"  [ERR] 페이지 {page} 실패: {e}")
        return None


def _parse_price_vnd(price_str: str) -> Optional[float]:
    """'1.639.000₫' 형식 파싱 → float (점은 천단위 구분자)"""
    if not price_str:
        return None
    # 숫자만 남긴다 (점·쉼표·통화 기호 전부 제거)
    digits = re.sub(r"[^\d]", "", price_str)
    try:
        val = float(digits)
        return val if val > 100 else None
    except ValueError:
        return None


def _infer_category(name: str, url: str = "", raw_cat: str = "") -> str:
    """상품명·URL·WooCommerce 카테고리로 카테고리 추론."""
    blob = (name + " " + raw_cat).lower()
    url_l = url.lower()

    # URL 경로로 가장 정확하게 판단
    if "/whisky/" in url_l or "/whiskey/" in url_l:
        return "위스키"
    if "/cognac/" in url_l or "/brandy/" in url_l or "/armagnac/" in url_l:
        return "코냑/브랜디"
    if "/rum/" in url_l or "/rhum/" in url_l:
        return "럼"
    if "/gin/" in url_l:
        return "진"
    if "/vodka/" in url_l:
        return "보드카"
    if "/tequila/" in url_l or "/mezcal/" in url_l:
        return "데킬라"

    # WooCommerce 카테고리 클래스
    if "product_cat-whisky" in raw_cat or "product_cat-whiskey" in raw_cat:
        return "위스키"

    # 이름 키워드 폴백
    if any(k in blob for k in ["whisky", "whiskey", "bourbon", "scotch", "single malt"]):
        return "위스키"
    if any(k in blob for k in ["cognac", "armagnac", "brandy", "champagne"]):
        return "코냑/브랜디"
    if any(k in blob for k in ["rum ", "rhum", "kill devil"]):
        return "럼"
    if any(k in blob for k in [" gin", "gin "]):
        return "진"
    if any(k in blob for k in ["vodka"]):
        return "보드카"
    if any(k in blob for k in ["tequila", "mezcal"]):
        return "데킬라"
    if any(k in blob for k in ["vermouth", "amaretto", "liqueur", "amaro"]):
        return "리큐르/기타"
    return "위스키"  # 이 사이트는 대부분 위스키


def parse_products(html: str) -> list[dict]:
    """BeautifulSoup 으로 WooCommerce 상품 목록 파싱 (Flatsome 테마)."""
    soup = BeautifulSoup(html, "html.parser")
    products = []

    # Flatsome 테마: div.products > div.product-small[data-index]
    # data-index 가 있는 것만 메인 상품 목록 (related/sidebar 중복 제외)
    products_div = soup.select_one("div.products")
    if not products_div:
        return products

    items = [el for el in products_div.select(".product-small") if el.get("data-index")]

    for item in items:
        # 상품명: p.name 또는 .product-title
        name_el = item.select_one("p.name") or item.select_one(".product-title")
        name = name_el.get_text(strip=True) if name_el else ""
        # "Whisky " 같은 접두어 제거 (일부 상품명에 붙음)
        name = re.sub(r"^(?:Whisky|Rượu Whisky)\s+", "", name, flags=re.IGNORECASE).strip()

        # 가격: .price bdi (점 구분자 VND 형식)
        price_el = item.select_one(".price bdi")
        price_raw = price_el.get_text(strip=True) if price_el else ""
        price_vnd = _parse_price_vnd(price_raw)

        # 상품 URL
        link_el = item.select_one("a[href]")
        url = link_el["href"] if link_el else ""

        # 카테고리: 클래스에서 product_cat-XXX 추출
        classes = " ".join(item.get("class", []))
        cat_m = re.search(r"product_cat-(\S+)", classes)
        raw_cat = cat_m.group(1).replace("-", " ") if cat_m else ""
        category = _infer_category(name, url=url, raw_cat=raw_cat + " " + classes)

        if not name:
            continue

        products.append({
            "name": name,
            "price_vnd": price_vnd,
            "price_raw": price_raw,
            "category": category,
            "url": url,
        })

    return products


def get_total_pages(html: str) -> int:
    """페이지네이션에서 총 페이지 수 추출."""
    soup = BeautifulSoup(html, "html.parser")
    # WooCommerce result-count
    count_el = soup.select_one(".woocommerce-result-count")
    if count_el:
        m = re.search(r"(\d+)\s*(?:results|상품)", count_el.get_text())
        if m:
            total = int(m.group(1))
            return (total + 23) // 24  # per_page=24

    # 페이지네이션 링크에서 최대 페이지 번호
    page_links = soup.select(".page-numbers a.page-numbers")
    nums = []
    for a in page_links:
        try:
            nums.append(int(a.get_text(strip=True)))
        except ValueError:
            pass
    return max(nums) if nums else 1


# ---------------------------------------------------------------------------
# 메인
# ---------------------------------------------------------------------------

def run():
    today = kst_today()
    ym = today[:7]

    # FX
    print("[FX] 환율 로드 중...")
    krw_per_usd = _load_krw_per_usd()
    vnd_per_usd = _fetch_vnd_per_usd()
    krw_per_vnd = krw_per_usd / vnd_per_usd
    print(f"  USD/KRW={krw_per_usd:.2f}  USD/VND={vnd_per_usd:.0f}  VND/KRW={krw_per_vnd:.5f}")

    # 페이지 1 — 총 페이지 수 확인
    print("\n[크롤] 페이지 1 수집 중...")
    html1 = _fetch_page(1)
    if not html1:
        print("[ERR] 페이지 1 접근 실패. 종료.")
        sys.exit(1)

    total_pages = get_total_pages(html1)
    print(f"  총 {total_pages} 페이지")

    all_products = parse_products(html1)

    for page in range(2, total_pages + 1):
        print(f"[크롤] 페이지 {page}/{total_pages} 수집 중...")
        time.sleep(PACE_S)
        html = _fetch_page(page)
        if html:
            all_products.extend(parse_products(html))
        else:
            print(f"  [경고] 페이지 {page} 스킵")

    print(f"\n총 {len(all_products)}개 상품 파싱 완료")

    # KRW 환산 + 반입 추정가 계산
    for p in all_products:
        vnd = p["price_vnd"] or 0
        krw = calc_krw(vnd, vnd_per_usd, krw_per_usd)
        p["price_krw"] = krw
        p["price_import_est_krw"] = calc_import_est(krw) if krw > 0 else 0

    # 저장
    out_dir = DATA
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{ym}_vn_winecellar.csv")

    fieldnames = [
        "name", "category", "price_vnd", "price_krw",
        "price_import_est_krw", "url", "collected_date",
        "fx_vnd_per_usd", "fx_krw_per_usd",
    ]
    with open(out_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for p in all_products:
            writer.writerow({
                "name": p["name"],
                "category": p["category"],
                "price_vnd": p["price_vnd"] or "",
                "price_krw": p["price_krw"],
                "price_import_est_krw": p["price_import_est_krw"],
                "url": p["url"],
                "collected_date": today,
                "fx_vnd_per_usd": round(vnd_per_usd),
                "fx_krw_per_usd": round(krw_per_usd, 2),
            })

    print(f"\n저장: {out_path}")

    # 가격 있는 상품 요약
    priced = [p for p in all_products if p["price_vnd"]]
    no_price = len(all_products) - len(priced)
    print(f"  가격 있음: {len(priced)}개 / 가격 없음: {no_price}개")

    # 카테고리 별 집계
    from collections import Counter
    cats = Counter(p["category"] for p in all_products)
    print("\n카테고리별 상품 수:")
    for cat, cnt in cats.most_common():
        print(f"  {cat}: {cnt}개")

    # 저렴 상품 미리보기 (KRW 기준 오름차순 상위 10)
    cheap = sorted(priced, key=lambda p: p["price_krw"])[:10]
    print("\n저렴한 상위 10개 (KRW 환산):")
    for p in cheap:
        print(f"  {p['name'][:50]:50s}  {p['price_vnd']:>12,.0f} VND  → {p['price_krw']:>9,} KRW")

    return out_path, all_products


if __name__ == "__main__":
    run()
