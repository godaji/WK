#!/usr/bin/env python3
"""CMPA-234 — shilla_cheaper_keys / _best_shilla_match 센티널 단위테스트.

면세↓ 배지의 핵심 위험 = FP(가짜딜). 정밀 가드(숙성/디스크립터 대칭·sanity)가
실제로 가짜 매칭을 막는지, 진짜 매칭은 잡는지 합성 신라 CSV로 검증한다.
실 fx(data/whisky-prices/fx/fx_latest.json)만 읽으므로 결정론·무네트워크.

국내 최저가는 정본(CMPA-429) current_obs = **품목 단위 최신 수집일** 기준이라, 합성 관측의
수집일(OBSDATE)이 곧 그 품목의 최신일이 된다 → dommin 이 바로 잡힌다(load() 없이도, 별도 시드 불필요).
"""
import csv
import os
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import whisky_report_tables as W

MONTH = W.MONTH_ORDER[-1]          # 마트 관측이 인정되는 실제 최신월
SELLER = W.COLS[0]                 # 게이트 마트(트레이더스)
OBSDATE = f"{MONTH}-01"            # 합성 관측 수집일


def _item(price):
    """current_obs(CMPA-429) 통과용 단일 게이트-마트 관측 1건(이 관측일이 곧 품목 최신일)."""
    return {MONTH: [(price, SELLER, OBSDATE)]}


def _agg_disp(items):
    """items: [(key, display, dom_price)] → (agg, disp)."""
    agg, disp = {}, {}
    for k, dname, price in items:
        agg[k] = _item(price)
        disp[k] = Counter({dname: 1})
    return agg, disp


def _write_shilla(rows):
    """rows: [(위스키명, 브랜드, 할인가_USD)] → 임시 신라 CSV 경로."""
    fd, path = tempfile.mkstemp(suffix=".csv", prefix="shilla_test_")
    os.close(fd)
    with open(path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=["위스키명", "브랜드", "할인가_USD",
                                          "상품코드"])
        w.writeheader()
        for name, brand, usd in rows:
            w.writerow({"위스키명": name, "브랜드": brand,
                        "할인가_USD": usd, "상품코드": "T0000"})
    return path


def run():
    usd_krw, _ = W._shilla_guards().load_fx()
    # CMPA-429: 합성 관측의 수집일(OBSDATE)이 곧 그 품목의 최신일 → current_obs 가 바로 잡는다.
    # 도메스틱 핵심표 SKU(키=공백제거, key 규칙과 동일하게 단순화)
    agg, disp = _agg_disp([
        ("글렌피딕12년", "글렌피딕 12년", 60_000),       # 진짜 면세↓ 후보
        ("제임슨", "제임슨", 30_000),                    # NAS — 18년과 숙성 비대칭 FP 방지
        ("맥캘란12년", "맥캘란 12년", 50_000),           # 디스크립터 비대칭(셰리오크) FP 방지
        ("발베니12년더블우드", "발베니 12년 더블우드", 80_000),  # sanity(2.5배↑) 보류
    ])
    # 합성 신라 CSV
    shilla = _write_shilla([
        ("글렌피딕 12년 700ml", "글렌피딕", 50.0),          # duty≈77k ∈ [60k, 150k] → 배지 ✓
        ("제임슨 18년 700ml", "제임슨", 300.0),             # 숙성 18 ≠ NAS → 매칭 금지
        ("맥캘란 12년 셰리오크 700ml", "맥캘란", 90.0),       # 셰리 디스크립터 비대칭 → 금지
        ("발베니 12년 더블우드 700ml", "발베니", 200.0),     # duty≈309k > 80k×2.5 → sanity 보류
    ])
    try:
        keys = W.shilla_cheaper_keys(agg, disp, csv_path=shilla)
        matches = W.shilla_cheaper_matches(agg, disp, csv_path=shilla)
    finally:
        os.unlink(shilla)

    bym = {m["key"]: m for m in matches}
    fails = []

    # 1) 진짜 매칭은 배지가 달려야
    if "글렌피딕12년" not in keys:
        fails.append("글렌피딕 12년: 진짜 면세↓ 매칭이 누락됨")
    else:
        g = bym["글렌피딕12년"]
        if not (g["dom"] <= g["duty_krw"]):
            fails.append(f"글렌피딕: dom({g['dom']}) ≤ duty({g['duty_krw']}) 위배")

    # 2) 숙성 비대칭(제임슨 ↔ 제임슨18년) FP 차단
    if "제임슨" in keys:
        fails.append("제임슨: 18년과 잘못 매칭(숙성 비대칭 가드 실패) — 가짜딜!")

    # 3) 디스크립터 비대칭(맥캘란12 ↔ 셰리오크) 차단
    if "맥캘란12년" in keys:
        fails.append("맥캘란 12년: 셰리오크와 잘못 매칭(디스크립터 가드 실패)")

    # 4) sanity(면세가 국내×2.5↑) 보류
    if "발베니12년더블우드" in keys:
        fails.append("발베니: 면세가 국내×2.5 초과인데 배지(sanity 가드 실패)")

    print(f"fx USD→KRW = {usd_krw:,.2f}")
    print(f"매칭된 키: {sorted(keys)}")
    for m in matches:
        print(f"  ✓ {m['domname']}: 국내 {m['dom']:,} ≤ 면세 {m['duty_krw']:,} "
              f"(USD {m['duty_usd']}) ← {m['sname']}")
    if fails:
        print("\nFAIL:")
        for f in fails:
            print("  ✗", f)
        sys.exit(1)
    print("\nPASS — 진짜 매칭 1종 배지 + FP 3종(숙성/디스크립터/sanity) 전부 차단")


if __name__ == "__main__":
    run()
