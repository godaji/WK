#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""신라면세 '오랜만의 큰 인하' 감지 (CMPA-644 보드 후속 2026-06-27).

보드 요청: "계속 할인하는 것 말고, 원래 할인을 잘 안했는데 오랜만에 (20%↑) 큰 폭으로
가격이 인하된 것을 따로 표시." 즉 **잔잔한 변동·상시 할인 품목은 빼고**, 거의 정상가로
오래 고정돼 있다가 **처음으로 크게 떨어진** 위스키만 골라낸다.

데이터: data/shilla-dutyfree/신라면세_위스키_<날짜>.csv 일간 스냅샷(상품코드 = 안정 키).
가격 신호 = **할인가_USD**(모든 스냅샷 공통·자기일관 = 정상가×(1−할인율)).
⚠️ 표시가_USD/마일리지할인율_% 컬럼은 2026-06-20 스냅샷부터 추가됐고(마일리지 조건부가),
   스키마 경계에서 가짜 −50% 낙폭 아티팩트를 만든다 → **여기선 쓰지 않는다**(할인가_USD만).

판정(한 ISO 주 [start,end] 대상):
  ① 그 주에 처음으로 저가에 도달(first_low ∈ 주) — '이번 주에 떨어진' 것만.
  ② 직전까지 **flat**(min_flat_days 일 이상 ±flat_tol 안에서 고정) = 원래 잘 안 변함.
  ③ 직전 **할인율 ≤ max_base_disc**(거의 정상가) = 원래 할인 잘 안 함.
  ④ 낙폭 ≥ min_drop(기본 20%) · 저가가 그 주 마지막 관측일까지 **유지**(1일 반등 글리치 제외).
드물게(주당 0~수 종) 잡히는 게 정상 — '진짜 오랜만'만 따로 표시하려는 의도.
"""
import csv
import glob
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA_DIR = os.path.join(ROOT, "data", "shilla-dutyfree")

_HISTORY_CACHE = None


def _f(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def load_price_history(data_dir=DATA_DIR):
    """{상품코드: {date: (price_usd, disc_pct, name)}} — 할인가_USD 기준(스키마 경계 안전)."""
    global _HISTORY_CACHE
    if _HISTORY_CACHE is not None and data_dir == DATA_DIR:
        return _HISTORY_CACHE
    hist = {}
    files = sorted(glob.glob(os.path.join(data_dir, "신라면세_위스키_2026-*.csv")))
    for f in files:
        date = os.path.basename(f).split("_")[-1][:-4]
        try:
            rows = list(csv.DictReader(open(f, encoding="utf-8-sig")))
        except OSError:
            continue
        for r in rows:
            code = (r.get("상품코드") or "").strip()
            price = _f(r.get("할인가_USD"))
            if not code or price is None or price <= 0:
                continue
            disc = _f(r.get("할인율_%")) or 0.0
            hist.setdefault(code, {})[date] = (price, disc, (r.get("위스키명") or "").strip())
    if data_dir == DATA_DIR:
        _HISTORY_CACHE = hist
    return hist


def rare_drops(week_start, week_end, *, history=None, min_flat_days=6,
               min_drop=0.20, max_base_disc=20.0, plateau_tol=0.02, flat_tol=0.04):
    """그 주에 '원래 거의 정상가였다가 처음 ≥20% 인하'된 품목 리스트(낙폭 desc).

    각 항목: code/name/baseline_usd/current_usd/drop/drop_date/flat_days/base_disc/cur_disc."""
    history = history if history is not None else load_price_history()
    out = []
    for code, ser in history.items():
        ds = sorted(ser)
        if len(ds) < min_flat_days + 1:
            continue
        in_wk = [x for x in ds if week_start <= x <= week_end]
        if not in_wk:
            continue
        cur_date = in_wk[-1]
        current, cur_disc, name = ser[cur_date]
        if current <= 0:
            continue
        # baseline = current 보다 충분히 높고 min_flat_days 이상 지속된 최고 가격대(plateau).
        persisted = {}
        for x in ds:
            px = ser[x][0]
            persisted[px] = sum(1 for y in ds if abs(ser[y][0] - px) / px <= plateau_tol)
        cands = [px for px, cnt in persisted.items()
                 if cnt >= min_flat_days and px > current * (1 + min_drop * 0.5)]
        if not cands:
            continue
        baseline = max(cands)
        drop = (baseline - current) / baseline
        if drop < min_drop:
            continue
        # 저가(현재가 ±tol)에 처음 도달한 날 = 인하 시점. 그 주 안이어야 '이번 주 인하'.
        low_dates = [x for x in ds if ser[x][0] <= current * (1 + plateau_tol)]
        first_low = min(low_dates)
        if not (week_start <= first_low <= week_end):
            continue
        # 1일 반등 글리치 제외 — 주 마지막 관측일도 저가 유지.
        if ser[cur_date][0] > current * (1 + plateau_tol):
            continue
        pre = [x for x in ds if x < first_low]
        if len(pre) < min_flat_days:
            continue
        pre_prices = [ser[x][0] for x in pre]
        if (max(pre_prices) - min(pre_prices)) / baseline > flat_tol:
            continue                      # 직전이 flat 해야(잔잔한 변동·상시할인 제외)
        base_disc = ser[pre[-1]][1]
        if base_disc > max_base_disc:
            continue                      # 원래 거의 정상가(할인 잘 안 함)였어야
        out.append({
            "code": code, "name": name, "baseline_usd": baseline, "current_usd": current,
            "drop": drop, "drop_date": first_low, "flat_days": len(pre),
            "base_disc": base_disc, "cur_disc": cur_disc,
        })
    out.sort(key=lambda r: -r["drop"])
    return out


if __name__ == "__main__":
    import sys
    ws = sys.argv[1] if len(sys.argv) > 1 else "2026-06-22"
    we = sys.argv[2] if len(sys.argv) > 2 else "2026-06-28"
    rd = rare_drops(ws, we)
    print(f"주 {ws}..{we}: 오랜만의 큰 인하 {len(rd)}종")
    for r in rd:
        print(f"  -{r['drop']*100:4.1f}% | {r['flat_days']}일 flat · 할인율 "
              f"{r['base_disc']:.0f}→{r['cur_disc']:.0f}% | @{r['drop_date']} | {r['name']}")
