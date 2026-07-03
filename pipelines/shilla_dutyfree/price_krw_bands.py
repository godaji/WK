#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""피트 위스키: 신라면세가 원화환산(1500원 가정) + 심리저항선 구간 + 코스트코 최저가 비교.

보드 지시:
  · 환율 1,500원/USD 가정 → 신라면세가를 원화로
  · 심리저항선 10만/20만/30만원으로 구간화
  · 한국 가격 비교 기준 = 코스트코 최저가

코스트코 최저가는 data/whisky-prices/YYYY-MM.csv 의 `위치`=코스트코 행에서
브랜드+숙성연수로 매칭해 최저가를 취한다. (코스트코 한국은 피트 아일라 거의
미취급 → 매칭 0 가능, 그 경우 사실대로 보고)
"""
import csv
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(ROOT, "data", "shilla-dutyfree")
WP = os.path.join(ROOT, "data", "whisky-prices")
DATE = os.environ.get("SHILLA_DATE", "2026-06-06")
FX_ASSUMED = 1500  # 보드 가정 환율 KRW/USD

SRC = os.path.join(DATA, f"신라면세_피트위스키_매력도_{DATE}.csv")
DOMESTIC = [os.path.join(WP, "2026-06.csv"), os.path.join(WP, "2026-05.csv")]

# 코스트코명(한글) 매칭용 브랜드 토큰
BRAND_KO = {
    "보모어": ["보모어"], "라프로익": ["라프로익"], "아드벡": ["아드벡", "아드베그"],
    "라가불린": ["라가불린"], "쿨일라": ["쿨일라", "카올일라"], "탈리스커": ["탈리스커"],
    "옥토모어": ["옥토모어"], "브룩라디": ["브룩라디"], "암룻": ["암룻"],
    "폴 존": ["폴 존", "폴존"], "벤리악": ["벤리악"], "발베니": ["발베니"],
    "마츠이": ["마츠이"], "킬호만": ["킬호만"], "밀크앤허니": ["밀크앤허니"],
}


def parse_age(name):
    m = re.findall(r"(\d{1,2})\s*년", name)
    a = [int(x) for x in m if 3 <= int(x) <= 80]
    return max(a) if a else None


def band(krw):
    if krw is None:
        return ""
    if krw <= 100_000:
        return "①10만이하"
    if krw <= 200_000:
        return "②10~20만"
    if krw <= 300_000:
        return "③20~30만"
    return "④30만초과"


def load_costco():
    """코스트코 행만 추출, (brand_ko_set, age, min_price) 리스트."""
    rows = []
    seen = {}
    for path in DOMESTIC:
        if not os.path.exists(path):
            continue
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                if "코스트코" not in r.get("위치", ""):
                    continue
                try:
                    price = int(float(r.get("가격_KRW") or 0))
                except ValueError:
                    price = 0
                if price <= 0:
                    continue
                name = r.get("술이름", "")
                # 같은 이름이면 최저가 유지
                if name not in seen or price < seen[name][0]:
                    seen[name] = (price, name)
    for price, name in seen.values():
        rows.append({"name": name, "price": price, "age": parse_age(name)})
    return rows


def costco_min(kr_name, kr_brand, costco):
    """피트 위스키를 코스트코 행과 브랜드+연수로 매칭, 최저가 반환."""
    hay = f"{kr_name} {kr_brand}"
    toks = []
    for kr, t in BRAND_KO.items():
        if kr in hay:
            toks.extend(t)
    if not toks:
        return None, None
    age = parse_age(kr_name)
    cands = []
    for c in costco:
        if not any(t in c["name"] for t in toks):
            continue
        if age is not None and c["age"] != age:
            continue
        cands.append(c)
    if not cands:
        return None, None
    best = min(cands, key=lambda x: x["price"])
    return best["price"], best["name"]


def main():
    with open(SRC, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    costco = load_costco()

    def fnum(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    out = []
    cnt_costco = 0
    for p in rows:
        usd = fnum(p.get("라이브할인가")) or fnum(p.get("할인가_USD"))
        krw = round(usd * FX_ASSUMED) if usd else None
        cprice, cname = costco_min(p["위스키명"], p.get("브랜드", ""), costco)
        if cprice:
            cnt_costco += 1
        diff = (krw - cprice) if (krw and cprice) else None
        out.append({
            "위스키명": p["위스키명"],
            "브랜드": p.get("브랜드", ""),
            "구매가능": p.get("구매가능", ""),
            "신라면세_USD": round(usd, 2) if usd else "",
            "신라면세_KRW_1500": krw if krw else "",
            "심리구간": band(krw),
            "코스트코최저_KRW": cprice or "",
            "코스트코매칭상품": cname or "",
            "신라-코스트코_차이": diff if diff is not None else "",
            "종합매력도": p.get("매력도", ""),
            "피트분류": p.get("피트분류", ""),
            "상품URL": p.get("상품URL", ""),
        })

    # 정렬: 구매가능 우선, 원화가 오름차순
    out.sort(key=lambda r: (r["구매가능"] != "Y",
                            r["신라면세_KRW_1500"] if isinstance(r["신라면세_KRW_1500"], int) else 9e9))

    cols = list(out[0].keys())
    outp = os.path.join(DATA, f"신라면세_피트위스키_원화구간_{DATE}.csv")
    with open(outp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)

    avail = [r for r in out if r["구매가능"] == "Y"]
    from collections import Counter
    bc = Counter(r["심리구간"] for r in avail)
    print(f"코스트코 행 {len(costco)}개 / 피트 매칭 {cnt_costco}건")
    print(f"출력: {outp}\n")
    print("=== 구매가능 48종 심리구간 분포(신라면세 원화, 1500원) ===")
    for b in ["①10만이하", "②10~20만", "③20~30만", "④30만초과"]:
        print(f"  {b}: {bc.get(b,0)}종")
    print("\n=== 구매가능 ①10만이하 (원화 오름차순) ===")
    for r in avail:
        if r["심리구간"] == "①10만이하":
            print(f"  ₩{r['신라면세_KRW_1500']:>7,} (${r['신라면세_USD']}) {r['위스키명']}")
    print("\n=== 코스트코 매칭 결과 ===")
    if cnt_costco == 0:
        print("  피트 위스키 ↔ 코스트코 매칭 0건 — 코스트코 한국은 피트 아일라 싱글몰트 미취급")
        print("  (코스트코 위스키 = 블렌디드/스페이사이드/커클랜드 위주)")
    else:
        for r in out:
            if r["코스트코최저_KRW"]:
                print(f"  신라 ₩{r['신라면세_KRW_1500']:,} vs 코스트코 ₩{r['코스트코최저_KRW']:,} "
                      f"({r['코스트코매칭상품']}) | {r['위스키명']}")
    return out


if __name__ == "__main__":
    main()
