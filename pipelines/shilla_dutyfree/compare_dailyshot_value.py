#!/usr/bin/env python3
"""CMPA-138 후속 — 신라면세 위스키 vs 데일리샷 현재가 가성비 비교.

보드 요청(2026-06-06 코멘트):
  "면세점에서 몇프로 할인하는지와 데일리샷 현재가대비 가격이 어떠한지 정보를
   csv파일로 정리하되, 데일리샷대비 가성비 좋은 위스키 순으로 정렬해줘."

기존 find_cheaper_than_domestic.py 는 '국내최저 = 보유DB + 데일리샷 중 더 낮은 값'
이었지만, 이 스크립트는 보드 지시대로 **데일리샷 현재가만** 기준으로:
  (1) 신라면세 할인율(정상가 대비 할인가) %  ← shilla 원본 CSV의 할인율_%
  (2) 면세가 vs 데일리샷 현재가 차이(병당·100ml당)
  (3) **데일리샷 대비 가성비(=100ml당 절감률) 큰 순** 정렬

매칭 로직(브랜드·숙성·디스크립터·인디제외·길이 가드)은 find_cheaper_than_domestic
의 검증된 ds_best/ds_keyword 를 그대로 재사용한다.

대상: 신라면세 위스키 중 면세 환산가 ≤ 50만원 (CMPA-138 모집단 유지).
데일리샷 라이브 매칭이 잡힌 종만 비교에 포함.

출력:
  data/shilla-dutyfree/면세_vs_데일리샷_가성비_<date>.csv
  reports/shilla-dutyfree/면세_vs_데일리샷_가성비_<date>.md
"""
import argparse
import csv
import os
import time

import enrich_dailyshot as ds  # noqa: F401  (find_cheaper 가 의존)
import find_cheaper_than_domestic as fc

ROOT = fc.ROOT
KRW_CAP = fc.KRW_CAP


def fnum(s):
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    ap.add_argument("--pace", type=float, default=0.6)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    usd_krw, fx_asof = fc.load_fx()

    sp = os.path.join(ROOT, "data", "shilla-dutyfree",
                      f"신라면세_위스키_{args.date}.csv")
    rows = list(csv.DictReader(open(sp, encoding="utf-8-sig")))

    # ≤50만원 면세 후보
    cands = []
    for r in rows:
        usd = fnum(r.get("할인가_USD"))
        if not usd or usd <= 0:
            continue
        krw = round(usd * usd_krw)
        if krw > KRW_CAP:
            continue
        r["_krw"] = krw
        r["_usd"] = usd
        r["_vol"] = fc.vol_of(r["위스키명"])
        cands.append(r)
    if args.limit:
        cands = cands[: args.limit]

    # 데일리샷 라이브 매칭(키워드 캐시)
    kw_cache = {}
    out = []
    for i, r in enumerate(cands):
        kw = fc.ds_keyword(r["브랜드"], r["위스키명"])
        if not kw:
            continue
        if kw not in kw_cache:
            time.sleep(args.pace)
            kw_cache[kw] = ds.search(kw)
        b = fc.ds_best(r["브랜드"], r["위스키명"], kw_cache[kw])
        if i % 40 == 0:
            print(f"...{i}/{len(cands)} (키워드캐시 {len(kw_cache)})", flush=True)
        if not b:
            continue
        ds_price = round(b["price"])
        if ds_price <= 0:
            continue
        duty_p100 = r["_krw"] / r["_vol"] * 100
        ds_p100 = ds_price / max(b["vol"], 1) * 100
        save_bottle = ds_price - r["_krw"]           # +면 면세가 더 쌈(병당)
        save_p100 = ds_p100 - duty_p100              # +면 면세가 더 쌈(100ml)
        save_p100_pct = save_p100 / ds_p100 * 100
        save_bottle_pct = save_bottle / ds_price * 100
        shilla_disc = fnum(r.get("할인율_%"))
        out.append({
            "위스키명": r["위스키명"],
            "브랜드": r["브랜드"],
            "면세_정상가_USD": fnum(r.get("정상가_USD")),
            "면세_할인가_USD": r["_usd"],
            "면세_할인율_%": round(shilla_disc, 1) if shilla_disc is not None else "",
            "면세_KRW": r["_krw"],
            "면세용량_ml": r["_vol"],
            "면세_₩100ml": round(duty_p100),
            "데일리샷_KRW": ds_price,
            "데일리샷용량_ml": b["vol"],
            "데일리샷_₩100ml": round(ds_p100),
            "데일리샷매칭명": b["name"],
            "면세vs데샷_병당_KRW": round(save_bottle),
            "면세vs데샷_병당_%": round(save_bottle_pct, 1),
            "면세vs데샷_100ml_%": round(save_p100_pct, 1),
            "면세가_더쌈": "Y" if save_p100 > 0 else "N",
            "구매가능": r.get("구매가능", ""),
            "상품URL": r.get("상품URL", ""),
        })

    # 데일리샷 대비 가성비(=100ml당 절감률) 큰 순
    out.sort(key=lambda x: -x["면세vs데샷_100ml_%"])

    fields = ["위스키명", "브랜드", "면세_정상가_USD", "면세_할인가_USD",
              "면세_할인율_%", "면세_KRW", "면세용량_ml", "면세_₩100ml",
              "데일리샷_KRW", "데일리샷용량_ml", "데일리샷_₩100ml", "데일리샷매칭명",
              "면세vs데샷_병당_KRW", "면세vs데샷_병당_%", "면세vs데샷_100ml_%",
              "면세가_더쌈", "구매가능", "상품URL"]
    out_csv = os.path.join(ROOT, "data", "shilla-dutyfree",
                           f"면세_vs_데일리샷_가성비_{args.date}.csv")
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(out)

    win = [m for m in out if m["면세가_더쌈"] == "Y"]
    win_avail = [m for m in win if m["구매가능"] == "Y"]
    rep_dir = os.path.join(ROOT, "reports", "shilla-dutyfree")
    os.makedirs(rep_dir, exist_ok=True)
    out_md = os.path.join(rep_dir, f"면세_vs_데일리샷_가성비_{args.date}.md")
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("# 신라면세 위스키 vs 데일리샷 현재가 — 가성비 순위 (CMPA-138)\n\n")
        f.write(f"- 분석일 {args.date} (KST) · 환율 1 USD = {usd_krw:,.2f} KRW (asof {fx_asof})\n")
        f.write(f"- 면세 ≤50만원 후보 {len(cands)}종 중 데일리샷 라이브 매칭 {len(out)}종\n")
        f.write(f"- 그중 면세가가 데일리샷보다 쌈(100ml당): **{len(win)}종** (구매가능 {len(win_avail)}종)\n")
        f.write("- 정렬: **데일리샷 대비 가성비(=100ml당 절감률) 큰 순**\n")
        f.write("- 면세 할인율 = 신라면세 정상가 대비 할인가(면세점 자체 할인)\n\n")
        f.write("> ⚠️ 면세가는 해외 출국 전제 + 주류 면세한도(2병/2L/$400). 데일리샷 매칭은 "
                "브랜드·숙성·표현 자동매칭(표준판 가드)이라 소수 근사오차 가능 → 구매 전 개별 확인.\n\n")
        f.write("| # | 위스키 | 면세할인 | 면세(₩) | 데일리샷(₩) | 면세₩/100ml | 데샷₩/100ml | "
                "가성비(100ml) | 병당차 | 구매 |\n")
        f.write("|--:|---|--:|--:|--:|--:|--:|--:|--:|:--:|\n")
        for i, m in enumerate(out, 1):
            disc = f"{m['면세_할인율_%']}%" if m["면세_할인율_%"] != "" else "-"
            f.write(f"| {i} | {m['위스키명']} | {disc} | {m['면세_KRW']:,} | "
                    f"{m['데일리샷_KRW']:,} | {m['면세_₩100ml']:,} | {m['데일리샷_₩100ml']:,} | "
                    f"{m['면세vs데샷_100ml_%']:+.1f}% | {m['면세vs데샷_병당_KRW']:+,} | "
                    f"{m['구매가능']} |\n")
        f.write("\n---\n_출처: 신라면세 shilladfs.com(USD) · 데일리샷 라이브검색 · FX open.er-api.com_\n")

    print(f"\n[DONE] ≤50만원 {len(cands)}종 · 데일리샷매칭 {len(out)}종 "
          f"(면세가 더쌈 {len(win)}/구매가능 {len(win_avail)})")
    print(f"CSV -> {out_csv}")
    print(f"MD  -> {out_md}")
    print("\n=== 데일리샷 대비 가성비 TOP 20 (100ml 절감률) ===")
    for m in out[:20]:
        disc = f"{m['면세_할인율_%']}%" if m["면세_할인율_%"] != "" else "-"
        print(f"{m['면세vs데샷_100ml_%']:+6.1f}%  면세{m['면세_KRW']:>8,}(할인{disc:>5}) "
              f"데샷{m['데일리샷_KRW']:>8,}  병당{m['면세vs데샷_병당_KRW']:+9,}  "
              f"{m['위스키명'][:30]}")


if __name__ == "__main__":
    main()
