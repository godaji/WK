#!/usr/bin/env python3
"""신라면세 위스키 ↔ 홍콩(HK) 소매가 비교 브릿지.

신라(한글명, USD) 와 HK POC(영문명, KRW)를 **브랜드(증류소)+숙성년수**로 매칭해
'면세가 HK보다 싼가'를 판정한다. HK는 공식 보틀링(OB)만 비교 대상으로 삼고
인디 보틀러(Adelphi·Signatory 등)는 제외(동일 증류소라도 다른 제품).

출력 맵: 상품코드 -> {hk_krw, hk_name, age}
"""
import csv
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

# 한글 브랜드(증류소) → 영문(증류소). 긴 키 우선 매칭.
BRAND_KO_EN = {
    "글렌파클라스": "glenfarclas", "글렌알라키": "glenallachie",
    "글렌드로낙": "glendronach", "글렌모렌지": "glenmorangie",
    "글렌피딕": "glenfiddich", "글렌리벳": "glenlivet", "글렌그란트": "glen grant",
    "글렌고인": "glengoyne", "글렌로티스": "glenrothes",
    "발베니": "balvenie", "보모어": "bowmore", "라프로익": "laphroaig",
    "라가불린": "lagavulin", "아벨라워": "aberlour", "아드벡": "ardbeg",
    "맥캘란": "macallan", "탈리스커": "talisker", "카발란": "kavalan",
    "부쉬밀": "bushmills", "탐듀": "tamdhu", "하이랜드파크": "highland park",
    "스프링뱅크": "springbank", "벤리악": "benriach", "벤로막": "benromach",
    "클라이넬리시": "clynelish", "쿨일라": "caol ila", "부나하벤": "bunnahabhain",
    "킬호만": "kilchoman", "달모어": "dalmore", "토민토울": "tomintoul",
    "안녹": "ancnoc", "아란": "arran", "주라": "jura", "오반": "oban",
    "토마틴": "tomatin", "스카파": "scapa", "달위니": "dalwhinnie",
}
# HK 첫 토큰이 이들로 시작하면 인디보틀러 → OB 비교에서 제외
INDIE = ("adelphi", "signatory", "first edition", "murray", "maltbarn",
         "boutique", "berry", "master of malt", "whisky agency", "chorlton",
         "hepburn", "alba", "rare find", "gordon", "cadenhead", "douglas",
         "hunter laing", "whiskyland", "mars", "hibiki", "kilkerran",
         "single malts of scotland", "dramfool", "thompson", "watt whisky",
         "elixir", "valinch", "north star", "kingsbury", "samaroli")


def age_of(name):
    m = re.search(r"(\d{1,2})\s*(?:년|y|yo|year)", name.lower())
    return int(m.group(1)) if m else None


def load_hk_index():
    """(brand_en, age) -> 최저 기준가_KRW (OB만)."""
    p = os.path.join(ROOT, "data", "whisky-prices", "2026-06_hk_whisky_poc.csv")
    idx = {}
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        nm = r["술이름"]
        low = nm.lower()
        if any(low.startswith(i) or (" - " in nm and low.split(" - ")[0].strip().startswith(i))
               for i in INDIE):
            continue
        try:
            krw = int(float(r["기준가_KRW"]))
        except (ValueError, TypeError):
            continue
        if krw <= 0:
            continue
        brand = re.split(r"[-,]", nm)[0].strip().lower()
        age = age_of(nm)
        if age is None:
            continue
        # 브랜드가 알려진 증류소명으로 시작하는지
        for en in set(BRAND_KO_EN.values()):
            if brand.startswith(en):
                key = (en, age)
                if key not in idx or krw < idx[key][0]:
                    idx[key] = (krw, nm)
                break
    return idx


def shilla_brand_en(name):
    low = name.replace(" ", "")
    for ko in sorted(BRAND_KO_EN, key=len, reverse=True):
        if ko in low:
            return BRAND_KO_EN[ko]
    return None


def build_hk_map(date="2026-06-06"):
    """상품코드 -> {hk_krw, hk_name, age} (HK OB 매칭된 신라 위스키만)."""
    idx = load_hk_index()
    src = os.path.join(ROOT, "data", "shilla-dutyfree",
                       f"신라면세_위스키_{date}.csv")
    out = {}
    for r in csv.DictReader(open(src, encoding="utf-8-sig")):
        en = shilla_brand_en(r["위스키명"])
        age = age_of(r["위스키명"])
        if not en or age is None:
            continue
        hit = idx.get((en, age))
        if hit:
            out[r["상품코드"]] = {"hk_krw": hit[0], "hk_name": hit[1], "age": age}
    return out


if __name__ == "__main__":
    m = build_hk_map()
    print(f"HK 매칭 {len(m)}종")
    import json
    src = os.path.join(ROOT, "data", "shilla-dutyfree",
                       "신라면세_위스키_2026-06-06.csv")
    name = {r["상품코드"]: r for r in csv.DictReader(open(src, encoding="utf-8-sig"))}
    rowsel = []
    for code, h in m.items():
        r = name.get(code)
        if not r:
            continue
        sk = round(float(r["할인가_USD"]) * 1500)
        rowsel.append((sk - h["hk_krw"], r["위스키명"], sk, h["hk_krw"], h["hk_name"]))
    for diff, nm, sk, hk, hkn in sorted(rowsel)[:25]:
        tag = "면세싸다" if diff < 0 else "HK싸다"
        print(f"  {tag} 면세{sk:>8,} HK{hk:>8,} ({diff:+,}) | {nm[:30]} ← {hkn[:34]}")
