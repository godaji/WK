#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""피트 위스키 매력도 스코어링 + TOP 20.

신라면세 라이브 PLP(키리스 AJAX)를 재조회해 64종 피트 위스키의
  - 구매 가능 여부 (allowProductPurchase & stockAvailable>0)
  - 라이브 가격/할인율, 재고, 누적판매·리뷰(수요)
를 붙인 뒤, 세 축으로 매력도(0~100)를 산출한다.

매력도 = 0.45*가격메리트 + 0.40*희소성 + 0.15*수요
  · 가격메리트 = 할인율 정규화(30%↑ 만점) 70% + 절감액(USD) 정규화 30%
  · 희소성    = 본질희소성(숙성연수+한정에디션 키워드) 60% + 재고희소성(재고 적을수록↑) 40%
  · 수요      = 누적판매수량·리뷰수 로그 정규화 (저재고가 진짜 희소인지 보정)

구매 불가(delisted/품절) 항목은 TOP에서 제외하되 표에는 사유와 함께 남긴다.
"""
import csv
import json
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(ROOT, "data", "shilla-dutyfree")
sys.path.insert(0, HERE)
import crawl_shilla_whisky as C  # noqa: E402

DATE = os.environ.get("SHILLA_DATE", "2026-06-06")
PEATED = os.path.join(DATA, f"신라면세_피트위스키_{DATE}.csv")

LIMITED_KW = [
    "옥토모어", "octomore", "special release", "스페셜 릴리즈", "스페셜릴리즈",
    "cask strength", "캐스크 스트렝스", "캐스크스트렝스", "vintage", "빈티지",
    "single cask", "싱글캐스크", "싱글 캐스크", "limited", "리미티드",
    "fq", "프랭크 콰이어틀리", "타임리스", "코노세어", "스트롱캐릭터",
    "포오크", "우거다일", "코리브레칸", "다크앤인텐스",
]


def fetch_live():
    """1200(주류) 전체를 라이브로 받아 code->product dict 반환."""
    op, tok = C.make_session()
    first = C.fetch_page(op, tok, 0)
    pg = first["pagination"]
    npages = pg["numberOfPages"]
    by_code = {}
    import time
    for page in range(npages):
        res = first["results"] if page == 0 else None
        if res is None:
            time.sleep(0.7)
            try:
                res = C.fetch_page(op, tok, page)["results"]
            except Exception as e:
                print(f"  page {page} 실패: {e}", file=sys.stderr)
                continue
        for p in res:
            by_code[str(p.get("code"))] = p
    print(f"라이브 조회: {len(by_code)}개 상품(주류 전체)", file=sys.stderr)
    return by_code


def parse_age(name):
    m = re.findall(r"(\d{1,2})\s*년", name)
    ages = [int(x) for x in m if 3 <= int(x) <= 80]
    return max(ages) if ages else 0


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def main():
    with open(PEATED, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    live = fetch_live()

    # 1) 라이브 데이터 부착 + 구매가능 판정
    enriched = []
    for r in rows:
        code = str(r.get("상품코드", "")).strip()
        p = live.get(code)
        e = dict(r)
        if p is None:
            e.update(dict(구매가능="N", 재고=0, 라이브할인율="", 라이브할인가="",
                          정상가=r.get("정상가_USD", ""), 누적판매=0, 리뷰수=0,
                          가용사유="라이브 목록에 없음(판매중지/삭제 추정)"))
        else:
            stock = p.get("stockAvailable") or 0
            allow = bool(p.get("allowProductPurchase"))
            ok = "Y" if (allow and stock > 0) else "N"
            reason = "" if ok == "Y" else (
                "판매불가(allowProductPurchase=false)" if not allow else "재고 0(품절)")
            e.update(dict(
                구매가능=ok, 재고=stock,
                라이브할인율=p.get("discountRate"),
                라이브할인가=p.get("discountPrice"),
                정상가=(p.get("userPrice") or {}).get("salePrice") or r.get("정상가_USD"),
                누적판매=p.get("accumInterTotalQuantity") or 0,
                리뷰수=p.get("reviewCountByTipping") or p.get("reviewCount") or 0,
                가용사유=reason))
        enriched.append(e)

    # 정규화 기준
    def fnum(v, d=0.0):
        try:
            return float(v)
        except (TypeError, ValueError):
            return d

    avail = [e for e in enriched if e["구매가능"] == "Y"]
    max_save = max((fnum(e["정상가"]) - fnum(e["라이브할인가"]) for e in avail), default=1) or 1
    max_demand = max((math.log1p(fnum(e["누적판매"]) + fnum(e["리뷰수"])) for e in avail), default=1) or 1
    stocks = [fnum(e["재고"]) for e in avail if fnum(e["재고"]) > 0]
    stock_cap = (sorted(stocks)[int(len(stocks) * 0.9)] if stocks else 30) or 30

    for e in enriched:
        disc = fnum(e["라이브할인율"], fnum(e["할인율_%"]))
        save = fnum(e["정상가"]) - fnum(e["라이브할인가"])
        # 가격메리트
        price_merit = 100 * (0.7 * clamp(disc / 30.0) + 0.3 * clamp(save / max_save))
        # 희소성: 본질(숙성+한정) + 재고희소
        hay = (e["위스키명"] + " " + e.get("브랜드", "")).lower()
        age = parse_age(e["위스키명"])
        intrinsic = 0.0
        intrinsic += clamp(age / 30.0) * 0.6           # 30년↑ 만점
        if any(k in hay for k in LIMITED_KW):
            intrinsic += 0.4
        intrinsic = clamp(intrinsic)
        stock = fnum(e["재고"])
        stock_scarcity = clamp((stock_cap - stock) / stock_cap) if stock > 0 else 0.0
        scarcity = 100 * (0.6 * intrinsic + 0.4 * stock_scarcity)
        # 수요
        demand = 100 * clamp(math.log1p(fnum(e["누적판매"]) + fnum(e["리뷰수"])) / max_demand)

        score = 0.45 * price_merit + 0.40 * scarcity + 0.15 * demand
        e["가격메리트"] = round(price_merit, 1)
        e["희소성"] = round(scarcity, 1)
        e["수요"] = round(demand, 1)
        e["매력도"] = round(score, 1) if e["구매가능"] == "Y" else ""
        bits = []
        if disc:
            bits.append(f"할인{disc:.0f}%")
        if save > 0:
            bits.append(f"절감${save:.0f}")
        if age:
            bits.append(f"{age}년")
        if any(k in hay for k in LIMITED_KW):
            bits.append("한정/특별")
        if stock and stock <= 3:
            bits.append(f"재고{int(stock)}병")
        if fnum(e["누적판매"]) >= 100:
            bits.append("판매多")
        e["매력근거"] = ", ".join(bits)

    # 정렬: 구매가능 우선, 매력도 desc
    enriched.sort(key=lambda e: (e["구매가능"] != "Y",
                                 -(e["매력도"] if isinstance(e["매력도"], float) else -1)))

    cols = ["위스키명", "브랜드", "구매가능", "가용사유", "재고",
            "라이브할인가", "정상가", "라이브할인율", "누적판매", "리뷰수",
            "가격메리트", "희소성", "수요", "매력도", "매력근거",
            "피트분류", "소분류", "상품코드", "SKU", "상품URL"]
    full = os.path.join(DATA, f"신라면세_피트위스키_매력도_{DATE}.csv")
    with open(full, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(enriched)

    top = [e for e in enriched if e["구매가능"] == "Y"][:20]
    top_path = os.path.join(DATA, f"신라면세_피트위스키_TOP20_{DATE}.csv")
    with open(top_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["순위"] + cols, extrasaction="ignore")
        w.writeheader()
        for i, e in enumerate(top, 1):
            e2 = dict(e); e2["순위"] = i
            w.writerow(e2)

    n_avail = sum(1 for e in enriched if e["구매가능"] == "Y")
    print(f"전체 {len(enriched)}종 / 구매가능 {n_avail}종 / 구매불가 {len(enriched)-n_avail}종")
    print(f"출력: {full}")
    print(f"출력: {top_path}")
    print("\n=== TOP 20 ===")
    for i, e in enumerate(top, 1):
        print(f"{i:2d}. [{e['매력도']:>4}] {e['위스키명']}  "
              f"(${e['라이브할인가']}, {e['매력근거']})")
    return enriched, top


if __name__ == "__main__":
    main()
