#!/usr/bin/env python3
"""신라면세 위스키 — 예산대별 TOP 추천.

보드 요청: "사용자가 예산이 있을거야. 예산 범위내에서 Top을 골라주면 좋겠다."

예산 구간(USD, 면세 표준가)별로 구매가능 위스키를 종합 매력도로 랭킹해 TOP N을 뽑는다.
종합점수(구간 내 정규화) = 0.40*인기 + 0.35*가격메리트 + 0.25*평점
  - 인기      : log(누적판매) 구간정규화 — '많이 팔린 검증된 술'
  - 가격메리트 : 0.5*할인율 + 0.5*절감액 구간정규화 — '딜의 깊이'
  - 평점      : avgReviewRatingByTipping/10 (리뷰 없으면 0)
국내가 대비 저렴(면세_매력도_매칭 양수)한 항목은 ⭐로 표시(추가 검증 신호).

입력:
  data/shilla-dutyfree/신라면세_위스키_<date>.csv          (656종, 인기·평점·재고 포함)
  data/shilla-dutyfree/면세_매력도_매칭_<date>.csv          (국내대비 매력도, 선택)
  data/whisky-prices/fx/fx_latest.json                     (USD→KRW)
출력:
  reports/shilla-dutyfree/예산대별_TOP_<date>.md
  data/shilla-dutyfree/예산대별_TOP_<date>.csv
"""
import argparse
import csv
import math
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
import analyze_attractiveness as AA  # 매칭 엔진(norm·canonical·domestic·가드) 재사용

# 원화 심리 저항선 기준 (보드 지시: 10만/20만/30만, 환율 1,500원)
FX = 1500
# (하한 KRW, 상한 KRW, 라벨)
BANDS = [
    (0, 100000, "10만원 이하"),
    (100000, 200000, "10–20만원"),
    (200000, 300000, "20–30만원"),
    (300000, 10**12, "30만원 이상"),
]
TOP_N = 8
W_POP, W_DEAL, W_RATE = 0.40, 0.35, 0.25


def fnum(v, d=0.0):
    try:
        return float(v)
    except (ValueError, TypeError):
        return d


def build_domestic_map(shilla_rows):
    """상품코드 -> {매력도, 국내최저, 국내현재, 국내채널}.

    국내가(normalized_prices)가 있는 정본 위스키에 이름·용량·에디션 가드로 매칭되는
    '모든' 신라 SKU(700·1000ml 등 변형 포함)에 국내 가용성 플래그를 부여한다.
    상품코드 1:1 조인의 누락(사이즈 변형)을 방지한다.
    매력도 = (국내 100ml단가 − 면세 100ml단가)/국내단가 (양수=면세 저렴, FX=1500).
    """
    canon = AA.load_canonical()
    dom = AA.load_domestic()
    code_map = {}
    for c in canon:
        d = dom.get(c["id"])
        if not d:
            continue
        cnorm, cvol = c["_norm"], c["_vol"]
        dom_p100 = d["low"] / cvol * 100
        for s in shilla_rows:
            usd = s["usd"]
            snorm, svol = s["_norm"], s["_vol"]
            if not (cnorm and cnorm in snorm):
                continue
            if svol < AA.MINI_ML or svol > AA.MAGNUM_ML:
                continue
            if any(k in snorm and k not in cnorm for k in AA.EDITION_KW):
                continue
            if len(snorm) - len(cnorm) - 5 > AA.EXTRA_TOL:
                continue
            duty_p100 = (usd * FX) / svol * 100
            attractiveness = (dom_p100 - duty_p100) / dom_p100 * 100
            prev = code_map.get(s["상품코드"])
            # 더 저렴한(매력도 큰) 매칭 우선
            if prev is None or attractiveness > prev["매력도"]:
                code_map[s["상품코드"]] = {
                    "매력도": round(attractiveness, 1),
                    "국내최저": round(d["low"]),
                    "국내현재": round(d["cur"]),
                    "국내채널": "·".join(sorted(d["ch"])),
                }
    return code_map


def normalize(rows, key):
    vals = [r[key] for r in rows]
    lo, hi = min(vals), max(vals)
    span = hi - lo
    for r in rows:
        r[key + "_n"] = (r[key] - lo) / span if span > 0 else 0.5


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    args = ap.parse_args()

    src = os.path.join(ROOT, "data", "shilla-dutyfree",
                       f"신라면세_위스키_{args.date}.csv")
    rows = []
    for r in csv.DictReader(open(src, encoding="utf-8-sig")):
        usd = fnum(r.get("할인가_USD"), None)
        if usd is None or usd <= 0:
            continue
        if r.get("구매가능") != "Y":   # 품절 제외
            continue
        sale = fnum(r.get("정상가_USD"), usd)
        name = r["위스키명"]
        rows.append({
            "위스키명": name, "브랜드": r["브랜드"], "usd": usd,
            "krw": round(usd * FX),
            "_norm": AA.norm(name), "_vol": AA.vol_of(name) or 700,
            "할인율": fnum(r.get("할인율_%")),
            "절감": max(sale - usd, 0),
            "pop": math.log1p(fnum(r.get("누적판매"))),
            "rate": fnum(r.get("평점")) / 10.0,
            "리뷰수": int(fnum(r.get("리뷰수"))),
            "소분류": r.get("소분류", ""),
            "상품코드": r.get("상품코드", ""),
            "상품URL": r.get("상품URL", ""),
        })
    attr = build_domestic_map(rows)

    all_ranked = []
    for lo, hi, label in BANDS:
        band = [r for r in rows if lo < r["krw"] <= hi]
        if not band:
            continue
        normalize(band, "pop")
        normalize(band, "할인율")
        normalize(band, "절감")
        for r in band:
            deal = 0.5 * r["할인율_n"] + 0.5 * r["절감_n"]
            r["score"] = round(
                100 * (W_POP * r["pop_n"] + W_DEAL * deal + W_RATE * r["rate"]), 1)
            r["band"] = label
            r["dom"] = attr.get(r["상품코드"])   # 국내 구매가능시 dict, else None
        band.sort(key=lambda x: -x["score"])
        for i, r in enumerate(band[:TOP_N], 1):
            r["순위"] = i
            all_ranked.append(r)

    out_csv = os.path.join(ROOT, "data", "shilla-dutyfree",
                           f"예산대별_TOP_{args.date}.csv")
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["예산대", "순위", "위스키명", "브랜드", "면세가_KRW",
                    "할인율_%", "종합점수", "평점", "리뷰수",
                    "국내구매처", "국내최저_KRW", "국내현재_KRW",
                    "면세vs국내_%", "상품URL"])
        for r in all_ranked:
            d = r["dom"]
            w.writerow([r["band"], r["순위"], r["위스키명"], r["브랜드"], r["krw"],
                        r["할인율"], r["score"], round(r["rate"] * 10, 1), r["리뷰수"],
                        (d["국내채널"] if d else "국내 미확인"),
                        (d["국내최저"] if d else ""), (d["국내현재"] if d else ""),
                        (f"{d['매력도']:+.0f}" if d else ""), r["상품URL"]])

    rep_dir = os.path.join(ROOT, "reports", "shilla-dutyfree")
    os.makedirs(rep_dir, exist_ok=True)
    out_md = os.path.join(rep_dir, f"예산대별_TOP_{args.date}.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("# 신라면세 위스키 — 예산대별 TOP 추천 (원화 기준)\n\n")
        f.write(f"- 분석일 {args.date} (KST) · 환율 1 USD = {FX:,} KRW · 구매가능(재고>0)만\n")
        f.write("- 종합점수 = 0.40·인기 + 0.35·가격메리트(할인율·절감) + 0.25·평점 (구간 내 정규화)\n")
        f.write("- 국내대비: 트레이더스·코스트코·데일리샷 등에서 쉽게 구할 수 있으면 그 가격과 비교(양수=면세 유리). '국내 미확인'=국내 데이터 없음(면세 전용 매력 가능성)\n\n")
        f.write("> ⚠️ 면세가는 해외 출국 전제 + 주류한도(2병/2L/$400). 수집일 기준, 재고·환율 변동 가능.\n\n")
        for lo, hi, label in BANDS:
            picks = [r for r in all_ranked if r["band"] == label]
            if not picks:
                continue
            f.write(f"## {label}\n\n")
            f.write("| # | 위스키 | 면세가 | 할인율 | 평점(리뷰) | 국내 쉽게? | 면세vs국내 |\n")
            f.write("|--:|---|--:|--:|--:|---|--:|\n")
            for r in picks:
                d = r["dom"]
                rate = f"{r['rate']*10:.1f}({r['리뷰수']})" if r["리뷰수"] else "—"
                if d:
                    home = d["국내채널"][:18]
                    vs = f"{d['매력도']:+.0f}%"
                else:
                    home, vs = "면세 전용?", "—"
                f.write(f"| {r['순위']} | {r['위스키명']} | {r['krw']:,}₩ | "
                        f"{r['할인율']:.0f}% | {rate} | {home} | {vs} |\n")
            f.write("\n")
        f.write("---\n_출처: 신라면세 shilladfs.com · 국내가=normalized_prices(트레이더스·코스트코·데일리샷)_\n")

    print(f"예산대 {len(BANDS)}구간 · 추천 {len(all_ranked)}종 · FX {FX}")
    print(f"CSV  -> {out_csv}\n리포트-> {out_md}")
    for lo, hi, label in BANDS:
        picks = [r for r in all_ranked if r["band"] == label][:4]
        if picks:
            print(f"\n[{label}]")
            for r in picks:
                d = r["dom"]
                tag = (f"국내 {d['국내최저']:,}₩({d['매력도']:+.0f}%)" if d else "면세전용?")
                print(f"  {r['순위']}. {r['위스키명'][:28]:30} {r['krw']:>8,}₩ 점{r['score']:>5} | {tag}")


if __name__ == "__main__":
    main()
