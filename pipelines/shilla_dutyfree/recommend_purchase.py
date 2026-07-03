#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CMPA-134 구매추천: CEO가 지목한 5종 위스키를 신라면세 라이브 데이터로 가성비 랭킹.

입력: data/shilla-dutyfree/신라면세_위스키_2026-06-06.csv (라이브 수집본, USD)
      data/shilla-dutyfree/면세_매력도_매칭_2026-06-06.csv (국내 교차비교, 검증 딜만)
출력: data/shilla-dutyfree/구매추천_CMPA134_<date>.csv

방법: 면세 USD→KRW(보드 매칭환율 1506.83) 환산 → 병당가·100ml당 단가 → 할인율과
      국내/해외 교차비교(있을 때만)로 '딜 검증도' 표기. 절대가 최저가 아니라
      '검증된 가성비'를 우선하도록 사람이 읽고 판단하게 근거를 모두 노출.
"""
import csv
import os
import sys

FX = 1506.83  # 면세_매력도_매칭 파일과 동일(아부나흐 $80.5→₩121,300 역산). 보드 가정.

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DATE = os.environ.get("SHILLA_DATE", "2026-06-06")
SRC = os.path.join(ROOT, "data", "shilla-dutyfree", f"신라면세_위스키_{DATE}.csv")
MATCH = os.path.join(ROOT, "data", "shilla-dutyfree", f"면세_매력도_매칭_{DATE}.csv")

# CEO 지목 5종 → 상품코드 매핑(설명문 모호어구 해소; 가정은 비고에 명시)
PICKS = [
    ("아벨라워 아부나흐 700ml",            "5887242"),
    ("더 아일라 보이즈 (배틀X 아일라) 700ml", "5232740"),
    ("스카라버스 아일레이 저니 블렌디드몰트 700ml", "5304445"),
    ("라프로익 PX Cask 1000ml",          "3333183"),
    ("폴 존 피티드 1000ml",               "5311922"),
]


def load_src():
    rows = {}
    with open(SRC, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            rows[r["상품코드"]] = r
    return rows


def load_match():
    """국내 교차비교가 있는 행만(검증 딜)."""
    m = {}
    if not os.path.exists(MATCH):
        return m
    with open(MATCH, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            m[r["상품URL"].rsplit("/", 1)[-1]] = r  # 상품코드 키
    return m


def main():
    src = load_src()
    match = load_match()
    out = []
    for label, code in PICKS:
        r = src.get(code)
        if not r:
            print(f"⚠️ 미발견 상품코드 {code} ({label})", file=sys.stderr)
            continue
        name = r["위스키명"]
        usd = float(r["할인가_USD"])
        normal = float(r["정상가_USD"])
        disc = float(r["할인율_%"])
        vol = 1000 if "1000ml" in name else 700
        krw = round(usd * FX)
        per100 = round(krw / vol * 100)
        # 국내 교차비교(있으면)
        mr = match.get(code)
        dom_note = ""
        verified = "검증無(인디/NAS·해외정가 매칭불가)"
        if mr and mr.get("국내최저_KRW"):
            dom = int(mr["국내최저_KRW"])
            adv = mr.get("매력도_%", "")
            dom_note = f"국내최저 ₩{dom:,}({mr.get('국내채널','')}) 대비 -{adv}%"
            verified = "검증O(국내 교차비교)"
        out.append({
            "위스키": label,
            "신라상품명": name,
            "용량_ml": vol,
            "면세_USD": usd,
            "정상가_USD": normal,
            "할인율_%": disc,
            "면세_KRW": krw,
            "100ml당_KRW": per100,
            "딜검증": verified,
            "국내비교": dom_note,
            "상품URL": r["상품URL"],
        })

    # 100ml당 단가 오름차순(절대 가성비)
    out.sort(key=lambda x: x["100ml당_KRW"])
    date = DATE
    dst = os.path.join(ROOT, "data", "shilla-dutyfree", f"구매추천_CMPA134_{date}.csv")
    cols = list(out[0].keys())
    with open(dst, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out)

    # 콘솔 요약
    print(f"FX={FX} KRW/USD  | 출력: {dst}\n")
    print(f"{'순위':<3}{'위스키':<34}{'면세₩':>11}{'100ml₩':>9}{'할인':>6}  딜검증")
    for i, x in enumerate(out, 1):
        print(f"{i:<3}{x['위스키']:<34}{x['면세_KRW']:>11,}{x['100ml당_KRW']:>9,}{x['할인율_%']:>5.0f}%  {x['딜검증']}")
        if x["국내비교"]:
            print(f"   └ {x['국내비교']}")


if __name__ == "__main__":
    main()
