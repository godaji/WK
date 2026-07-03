#!/usr/bin/env python3
"""CMPA-275 — 위스키 월별 가격 추이 + 위치군×궤적 분류 (Phase 0 데이터 기반).

국내(KR+KR-DS) 정규화 최저가 시계열에서:
  1) 병별 월별 floor(국내 최저가) 시리즈 추출 (수집 월 메타 포함)
  2) 위치군 분류: 비싼군 / 애매한군 / 저렴한군 (자기 역대 [min,max] 내 위치)
  3) 궤적 태그: ↩️되돌림(reversion) / ⬇️하락추세(downtrend) / ⬆️상승 / —
  4) 대표 병 모바일 우선 추이 차트(PNG) 렌더

데이터 3원칙 준수: 각 점에 '수집 월', 시계열 빈 구간은 그리지 않음(>=3개월만 차트).
보드 검증된 사실(CMPA-275): 대중 가성비 병은 되돌림 우세(lag-1 r=-0.37, 하락후 80% 반등).
"""
import csv, collections, argparse, os

MONTHS = ["2026-03", "2026-04", "2026-05", "2026-06"]
SRC = "data/whisky-prices/normalized/normalized_all_rows.csv"


def _num(x):
    try:
        return float(str(x).replace(",", "").strip())
    except Exception:
        return None


def load_floors(src=SRC):
    """canonical_id -> {month: floor_krw}, and id->name."""
    floor = collections.defaultdict(dict)
    name = {}
    for r in csv.DictReader(open(src, encoding="utf-8-sig")):
        if (r.get("status") or "").strip() != "matched":
            continue
        if (r.get("market") or "").strip() not in ("KR", "KR-DS"):
            continue
        v = _num(r.get("volume_ml"))
        if v is not None and v not in (700.0, 750.0):
            continue
        p = _num(r.get("price_krw"))
        if not p or p <= 0:
            continue
        mo = (r.get("date") or "")[:7]
        if mo not in MONTHS:
            continue
        cid = r.get("canonical_id")
        name[cid] = r.get("canonical_name_ko")
        floor[cid][mo] = min(floor[cid].get(mo, 1e18), p)
    return floor, name


def classify(series):
    """series: list[(month, price)] sorted. -> (tier, trajectory, pct_pos)."""
    prices = [p for _, p in series]
    lo, hi = min(prices), max(prices)
    cur = prices[-1]
    rng = hi - lo
    pct = 0.0 if rng == 0 else (cur - lo) / rng  # 0=역대저점, 1=역대고점
    if rng == 0:
        tier = "변동없음"
    elif pct <= 0.25:
        tier = "저렴한군"
    elif pct >= 0.75:
        tier = "비싼군"
    else:
        tier = "애매한군"
    # trajectory from recent moves.
    # 핵심: '되돌림(reversion)' = 큰 변동 뒤 반대로 꺾임/평탄화 ↔ '하락추세' = 연속 하락 지속.
    chg = [(prices[i] - prices[i - 1]) / prices[i - 1] for i in range(1, len(prices))]
    traj = "—"
    if chg:
        last = chg[-1]
        prev = chg[-2] if len(chg) >= 2 else 0.0
        FLAT = 0.015  # ±1.5% 이내는 평탄
        if prev < -FLAT and abs(last) <= FLAT:
            traj = "↩️되돌림(하락후 평탄)"   # 떨어진 뒤 멈춤 → 매수창 굳음
        elif prev < -FLAT and last >= FLAT:
            traj = "↩️되돌림(반등)"          # 떨어졌다 다시 오름
        elif prev > FLAT and last <= -FLAT:
            traj = "↩️되돌림(상승후 꺾임)"
        elif last < -FLAT and prev < -FLAT:
            traj = "⬇️하락추세(연속)"        # 진짜 연속 하락 → 더 빠질 수 있음
        elif last <= -FLAT:
            traj = "⬇️하락(1개월)"
        elif last >= FLAT:
            traj = "⬆️상승"
        else:
            traj = "→ 횡보"
    return tier, traj, pct


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--charts", action="store_true", help="대표 병 PNG 차트 렌더")
    ap.add_argument("--outdir", default="blog-md/_drafts/assets/price-trend")
    args = ap.parse_args()

    floor, name = load_floors()
    full = {cid: fm for cid, fm in floor.items() if len([m for m in MONTHS if m in fm]) >= 3}
    print(f"국내 matched 병: {len(floor)}  /  3개월+ 시계열: {len(full)}")

    rows = []
    for cid, fm in full.items():
        series = [(m, fm[m]) for m in MONTHS if m in fm]
        tier, traj, pct = classify(series)
        rows.append((name[cid], len(series), series, tier, traj, pct))
    # sort: 저렴한군 먼저, 그 안에서 역대저점 가까운 순
    order = {"저렴한군": 0, "애매한군": 1, "비싼군": 2, "변동없음": 3}
    rows.sort(key=lambda r: (order.get(r[3], 9), r[5]))

    print("\n| 위스키 | 개월 | 월별 최저가(천원) | 위치군 | 궤적 |")
    print("|---|---|---|---|---|")
    for nm, n, series, tier, traj, pct in rows:
        sp = " → ".join(f"{p/1000:.0f}" for _, p in series)
        print(f"| {nm} | {n} | {sp} | **{tier}** | {traj} |")

    tally = collections.Counter(r[3] for r in rows)
    print("\n군집 분포:", dict(tally))

    if args.charts:
        render_charts(full, name, rows, args.outdir)


def render_charts(full, name, rows, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    # romanized labels for chart titles (no CJK font available)
    ROMAN = {
        "글렌피딕 12년": "Glenfiddich 12",
        "발베니 12년 더블우드": "Balvenie 12 DoubleWood",
        "맥캘란 12년 더블캐스크": "Macallan 12 DoubleCask",
        "글렌모렌지 12년": "Glenmorangie 12",
        "발렌타인 17년": "Ballantine's 17",
        "몽키숄더": "Monkey Shoulder",
    }
    os.makedirs(outdir, exist_ok=True)
    picks = [nm for nm in ROMAN if any(r[0] == nm for r in rows)][:4]
    mlabels = [m[5:] for m in MONTHS]  # MM
    for nm in picks:
        fm = full[[cid for cid, n in name.items() if n == nm][0]]
        series = [(m, fm[m]) for m in MONTHS if m in fm]
        xs = [m[5:] for m, _ in series]
        ys = [p / 10000 for _, p in series]  # 만원
        fig, ax = plt.subplots(figsize=(4.0, 3.2), dpi=150)  # mobile-first narrow
        ax.plot(xs, ys, "-o", color="#b5651d", linewidth=2.5, markersize=7)
        for x, y in zip(xs, ys):
            ax.annotate(f"{y:.1f}", (x, y), textcoords="offset points",
                        xytext=(0, 8), ha="center", fontsize=9)
        ax.set_title(ROMAN[nm], fontsize=12, fontweight="bold")
        ax.set_ylabel("price (10k KRW)", fontsize=10)
        ax.set_xlabel("2026 month (collected)", fontsize=9)
        ax.grid(True, alpha=0.3)
        fig.tight_layout()
        out = os.path.join(outdir, ROMAN[nm].replace(" ", "_").replace("'", "") + ".png")
        fig.savefig(out)
        plt.close(fig)
        print("chart:", out)


if __name__ == "__main__":
    main()
