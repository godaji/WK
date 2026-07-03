#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""신라면세 위스키에서 '셰리' / '버번·아메리칸' 매니아 픽을 분류 + 매력도 TOP.

피트 매니아 섹션(score_peated_attractiveness.py)과 동일한 매력도 공식을 쓰되,
라이브 재조회 대신 2026-06-06 수집 스냅샷(신라면세_위스키_2026-06-06.csv)의
정적 컬럼(구매가능·재고·할인율·할인가·정상가·누적판매·리뷰수)으로 재현 가능하게 산출.

매력도 = 0.45*가격메리트 + 0.40*희소성 + 0.15*수요
  · 가격메리트 = 할인율(30%↑ 만점) 70% + 절감액(USD) 정규화 30%
  · 희소성    = 본질희소성(숙성연수+한정키워드) 60% + 재고희소(재고 적을수록↑) 40%
  · 수요      = 누적판매+리뷰수 로그 정규화

스타일 판정은 증류소/브랜드 + 키워드 기반(피트 분류기와 동일 철학).
"""
import csv
import math
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(ROOT, "data", "shilla-dutyfree")
DATE = os.environ.get("SHILLA_DATE", "2026-06-06")
SRC = os.path.join(DATA, f"신라면세_위스키_{DATE}.csv")

# --- 셰리 판정 ------------------------------------------------------------
SHERRY_KW = [
    "셰리", "쉐리", "sherry", "px", "피엑스", "페드로 히메네스", "페드로히메네스",
    "pedro ximenez", "pedro ximénez", "올로로소", "oloroso", "아몬티야도",
    "amontillado", "팔로 코르타도", "palo cortado", "올로로쏘", "버트", "벗",
    "아부나흐", "abunadh", "a'bunadh", "abunadh",
]
# 항상/거의 셰리 숙성으로 유명한 증류소(셰리밤) -> 강한 셰리
SHERRY_BOMB = [
    "글렌드로낙", "glendronach", "글렌파클라스", "glenfarclas",
    "글렌알라키", "glenallachie", "타무어", "tamdhu", "맥캘란", "macallan",
    "아벨라워", "aberlour",
]
# 셰리 캐스크 라인업이 흔한 증류소(상품명에 셰리 신호 있을 때만 인정) -> 일반
SHERRY_LEANING = [
    "달모어", "dalmore", "글렌고인", "glengoyne", "벤리악", "benriach",
    "글렌파클라스", "에드라두어", "edradour",
]

# --- 버번/아메리칸 판정 ----------------------------------------------------
# 버번/테네시/라이 등 아메리칸 위스키 브랜드(브랜드·상품명 어디든)
BOURBON_BRANDS = [
    "짐빔", "jim beam", "메이커스 마크", "메이커스마크", "maker's", "makers mark",
    "와일드터키", "와일드 터키", "wild turkey", "버팔로 트레이스", "buffalo trace",
    "우드포드", "woodford", "잭다니엘", "잭 다니엘", "jack daniel",
    "놉크릭", "knob creek", "불렛", "bulleit", "에반 윌리엄스", "evan williams",
    "부커스", "booker", "베이커스", "베이질 헤이든", "basil hayden",
    "엘리야 크레이그", "elijah craig", "포 로지스", "포로지스", "four roses",
    "이글 레어", "이글레어", "eagle rare", "올드 포레스터", "old forester",
    "미클터", "michter", "1792", "헤븐 힐", "heaven hill", "사제락", "sazerac",
    "메이플", "blanton", "블랑톤", "george dickel", "조지 디켈",
]
BOURBON_KW = [
    "버번", "버본", "bourbon", "테네시", "tennessee", "라이 위스키", "rye whiskey",
    "콘 위스키", "corn whiskey", "스트레이트 버번", "straight bourbon",
]

LIMITED_KW = [
    "캐스크 스트렝스", "캐스크스트렝스", "cask strength", "single cask", "싱글캐스크",
    "싱글 캐스크", "vintage", "빈티지", "limited", "리미티드", "스페셜 릴리즈",
    "special release", "한정", "batch", "배치", "릴리즈", "프루프", "proof",
    "store pick", "single barrel", "싱글 배럴", "싱글배럴",
]


def low(s):
    return (s or "").lower()


def classify_sherry(name, brand):
    hay = f"{name} {brand}".lower()
    reasons = []
    tier = None
    for d in SHERRY_BOMB:
        if d in hay:
            reasons.append(f"셰리밤증류소:{d}")
            tier = "A"
            break
    for kw in SHERRY_KW:
        if kw in hay:
            reasons.append(f"키워드:{kw}")
            if tier is None:
                tier = "A"
            break
    if tier is None:
        # 셰리 캐스크 라인 증류소 + 셰리 신호 있을 때만
        for d in SHERRY_LEANING:
            if d in hay and any(k in hay for k in ["셰리", "쉐리", "sherry"]):
                reasons.append(f"셰리캐스크라인:{d}")
                tier = "B"
                break
    return bool(reasons), tier, "; ".join(reasons)


def classify_bourbon(name, brand):
    hay = f"{name} {brand}".lower()
    # 숙성 캐스크 언급은 버번(미국위스키)이 아니라 통 종류 -> 매칭 차단
    for cask in ["버번캐스크", "버번 캐스크", "버번배럴", "버번 배럴", "엑스버번",
                 "ex-bourbon", "ex bourbon", "bourbon cask", "bourbon barrel",
                 "퍼스트필 버번", "퍼스트 필 버번", "first fill bourbon", "리필 버번"]:
        hay = hay.replace(cask, "_____")
    reasons = []
    tier = None
    for b in BOURBON_BRANDS:
        if b in hay:
            reasons.append(f"브랜드:{b}")
            tier = "A"
            break
    for kw in BOURBON_KW:
        if kw in hay:
            reasons.append(f"키워드:{kw}")
            if tier is None:
                tier = "A"
            break
    return bool(reasons), tier, "; ".join(reasons)


def parse_age(name):
    m = re.findall(r"(\d{1,2})\s*년", name)
    ages = [int(x) for x in m if 3 <= int(x) <= 80]
    return max(ages) if ages else 0


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def fnum(v, d=0.0):
    try:
        return float(str(v).replace(",", ""))
    except (TypeError, ValueError):
        return d


def score(rows):
    """구매가능 'Y' 항목 기준 정규화 후 매력도 부여."""
    avail = [r for r in rows if r.get("구매가능") == "Y"]
    max_save = max((fnum(r["정상가_USD"]) - fnum(r["할인가_USD"]) for r in avail), default=1) or 1
    max_demand = max((math.log1p(fnum(r["누적판매"]) + fnum(r["리뷰수"])) for r in avail), default=1) or 1
    stocks = [fnum(r["재고"]) for r in avail if fnum(r["재고"]) > 0]
    stock_cap = (sorted(stocks)[int(len(stocks) * 0.9)] if stocks else 6) or 6

    for r in rows:
        disc = fnum(r["할인율_%"])
        save = fnum(r["정상가_USD"]) - fnum(r["할인가_USD"])
        price_merit = 100 * (0.7 * clamp(disc / 30.0) + 0.3 * clamp(save / max_save))
        hay = (r["위스키명"] + " " + r.get("브랜드", "")).lower()
        age = parse_age(r["위스키명"])
        intrinsic = clamp(age / 30.0) * 0.6
        if any(k in hay for k in LIMITED_KW):
            intrinsic += 0.4
        intrinsic = clamp(intrinsic)
        stock = fnum(r["재고"])
        stock_scarcity = clamp((stock_cap - stock) / stock_cap) if stock > 0 else 0.0
        scarcity = 100 * (0.6 * intrinsic + 0.4 * stock_scarcity)
        demand = 100 * clamp(math.log1p(fnum(r["누적판매"]) + fnum(r["리뷰수"])) / max_demand)
        s = 0.45 * price_merit + 0.40 * scarcity + 0.15 * demand
        r["가격메리트"] = round(price_merit, 1)
        r["희소성"] = round(scarcity, 1)
        r["수요"] = round(demand, 1)
        r["매력도"] = round(s, 1) if r.get("구매가능") == "Y" else ""
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
        if fnum(r["누적판매"]) >= 100:
            bits.append("판매多")
        r["매력근거"] = ", ".join(bits)
    return rows


def run(style):
    classify = classify_sherry if style == "sherry" else classify_bourbon
    label = "셰리" if style == "sherry" else "버번"
    with open(SRC, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    picked = []
    for x in rows:
        ok, tier, reason = classify(x.get("위스키명", ""), x.get("브랜드", ""))
        if ok:
            x2 = dict(x)
            x2["스타일분류"] = tier or ""
            x2["스타일근거"] = reason
            picked.append(x2)
    score(picked)
    picked.sort(key=lambda r: (r.get("구매가능") != "Y",
                               -(r["매력도"] if isinstance(r["매력도"], float) else -1)))
    cols = ["순위", "위스키명", "브랜드", "구매가능", "재고", "할인가_USD", "정상가_USD",
            "할인율_%", "누적판매", "리뷰수", "가격메리트", "희소성", "수요", "매력도",
            "매력근거", "스타일분류", "스타일근거", "소분류", "상품코드", "SKU", "상품URL"]
    full = os.path.join(DATA, f"신라면세_{label}위스키_매력도_{DATE}.csv")
    with open(full, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for i, r in enumerate(picked, 1):
            r["순위"] = i
            w.writerow(r)
    top = [r for r in picked if r.get("구매가능") == "Y"][:12]
    top_path = os.path.join(DATA, f"신라면세_{label}위스키_TOP_{DATE}.csv")
    with open(top_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for i, r in enumerate(top, 1):
            r2 = dict(r); r2["순위"] = i
            w.writerow(r2)
    n = sum(1 for r in picked if r.get("구매가능") == "Y")
    print(f"[{label}] 분류 {len(picked)}종 / 구매가능 {n}종 -> {full}")
    print(f"[{label}] TOP -> {top_path}")
    for i, r in enumerate(top, 1):
        print(f"  {i:2d}. [{r['매력도']:>4}] {r['위스키명']} (${r['할인가_USD']}, {r['매력근거']})")
    return picked, top


if __name__ == "__main__":
    run("sherry")
    print()
    run("bourbon")
