#!/usr/bin/env python3
"""신라면세점 위스키 '면세 가성비 매력도' 분석.

신라면세 할인가(USD)를 환율로 원화 환산한 뒤, 우리 보유 국내가 인텔리전스
(normalized_prices.csv: 마트 KR / 데일리샷 KR-DS)와 교차해 '면세에서 살 때
가장 이득인 위스키'를 랭킹한다.

매력도 = (국내최저가 - 면세환산가) / 국내최저가  (클수록 면세가 유리)

입력:
  data/shilla-dutyfree/신라면세_위스키_<date>.csv
  data/whisky-prices/normalized/normalized_prices.csv  (국내가, KRW)
  assets/whisky-list.csv                                (정본 88종 + 큐레이션 국내가)
  data/whisky-prices/fx/fx_latest.json                 (USD→KRW)

출력:
  reports/shilla-dutyfree/면세_가성비_매력도_<date>.md
  data/shilla-dutyfree/면세_매력도_매칭_<date>.csv

주의: 면세가는 해외 출국 전제 + 면세 주류 한도(2병/2L/$400)가 적용된다.
순수 가격 차익 비교이며, 여행 비용은 미반영.
"""
import argparse
import csv
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def norm(s):
    """공백·괄호 제거 소문자화 — 부분일치용."""
    return re.sub(r"[\s()\[\]/·.,'\"-]", "", (s or "").lower())


def vol_of(name):
    m = re.search(r"(\d{3,4})\s*ml", name.lower())
    if m:
        return int(m.group(1))
    if re.search(r"\b1\s*l\b|1000ml|1\.0l", name.lower()):
        return 1000
    return None


def load_fx():
    p = os.path.join(ROOT, "data", "whisky-prices", "fx", "fx_latest.json")
    fx = json.load(open(p, encoding="utf-8"))
    return fx["raw_usd"]["KRW"], fx.get("asof")


def load_domestic():
    """canonical_id -> {'name':, 'low':, 'channels':set} (마트+데일리샷 최저가).

    ⚠️ low(국내최저 floor) = **소스(매장)별 '최신 관측가' 중 최소값**(CMPA-496 보드). 트레이더스/
    코스트코는 가격을 전 지점 동일하게 오르내리므로 같은 소스의 과거 저가는 무효(superseded) —
    단순 min() 으로 잡으면 가격 인상을 인하처럼 보이게 한다(w030 89,800 옛값 vs 109,800 현재).
    소스 키 = 매장 라벨(데일리샷/코스트코/트레이더스/이마트/롯데마트/마트). cur=최신 date 가격."""
    from pipelines.common.source_floor import per_source_latest_floor
    p = os.path.join(ROOT, "data", "whisky-prices", "normalized",
                     "normalized_prices.csv")
    dom = {}
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        if r.get("status") != "matched":
            continue
        if r["market"] not in ("KR", "KR-DS"):
            continue
        try:
            price = float(r["price_krw"])
        except (ValueError, TypeError):
            continue
        if price <= 0:
            continue
        cid = r["canonical_id"]
        ch = r.get("channel", "")
        if r["market"] == "KR-DS":
            label = "데일리샷"
        elif "코스트코" in ch or "costco" in ch.lower():
            label = "코스트코"
        elif "트레이더스" in ch:
            label = "트레이더스"
        elif "이마트" in ch:
            label = "이마트"
        elif "롯데" in ch:
            label = "롯데마트"
        else:
            label = "마트"
        d = dom.setdefault(cid, {"name": r["canonical_name_ko"], "low": price,
                                 "ch": set(), "cur": price, "curdate": r.get("date", ""),
                                 "_obs": []})
        d["ch"].add(label)
        d["_obs"].append((label, r.get("date", "") or "", price))
        # 현재가 = 최신 date 의 가격
        if (r.get("date", "") or "") >= (d["curdate"] or ""):
            d["curdate"] = r.get("date", "")
            d["cur"] = price
    # low = 소스별 최신가 중 최소값(과거 저가 superseded). _obs 는 산출 후 제거.
    for d in dom.values():
        fl = per_source_latest_floor(d.pop("_obs"))
        if fl:
            d["low"] = fl[0]
    return dom


def load_canonical():
    p = os.path.join(ROOT, "assets", "whisky-list.csv")
    rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
    for r in rows:
        r["_norm"] = norm(r["name_ko"])
        try:
            r["_vol"] = int(r["volume_ml"]) if r["volume_ml"] else 700
        except ValueError:
            r["_vol"] = 700
    return rows


def load_shilla(date):
    p = os.path.join(ROOT, "data", "shilla-dutyfree",
                     f"신라면세_위스키_{date}.csv")
    rows = list(csv.DictReader(open(p, encoding="utf-8-sig")))
    for r in rows:
        r["_norm"] = norm(r["위스키명"])
        r["_vol"] = vol_of(r["위스키명"]) or 700
        try:
            # 표시가_USD = 신라 앱/웹에 실제 표시되는 마일리지 할인가 (우선)
            # 구버전 CSV 호환: 표시가_USD 없으면 할인가_USD 폴백
            usd_val = r.get("표시가_USD") or r.get("할인가_USD")
            r["_usd"] = float(usd_val)
        except (ValueError, TypeError):
            r["_usd"] = None
    return rows


EXTRA_TOL = 8  # canonical 외 추가 글자수 허용치(용량표기≈5-6 + 여유)
               # 초과 시 특별/프리미엄 에디션으로 보고 제외(국내가는 표준판 기준)
MINI_ML = 500      # 미만은 소용량 수집 금지(CMPA-733) + 용량당 단가 왜곡 → 제외
MAGNUM_ML = 1500   # 초과는 매그넘/기프트 → 제외
# 비표준 피니시·강도·에디션 신호: 신라명에만 있고 canonical엔 없으면 매칭 제외
EDITION_KW = ["마데이라", "셰리", "포트", "캐스크스트랭스", "케스크스트랭스",
              "스트랭스", "캐스크피니시", "리미티드", "에디션", "퍼페추얼",
              "perpetual", "vat", "스몰배치", "프루프", "더블오크", "어코드"]


def best_shilla_match(canon, shilla_rows):
    """canonical 부분일치 + 표준판(에디션·길이 가드) 중 용량당 단가 최저 행.

    700/750/1000ml 등 다른 용량도 허용하되 비교는 100ml당 단가로 정규화한다.
    미니(<350ml)·매그넘(>1500ml)은 용량당 단가가 왜곡되어 제외.
    """
    cand = []
    base = len(canon["_norm"])
    for s in shilla_rows:
        if s["_usd"] is None or s["_vol"] < MINI_ML or s["_vol"] > MAGNUM_ML:
            continue
        if not (canon["_norm"] and canon["_norm"] in s["_norm"]):
            continue
        if any(kw in s["_norm"] and kw not in canon["_norm"] for kw in EDITION_KW):
            continue  # 비표준 피니시·강도·에디션 → 표준 국내가와 비교 부적합
        extra = len(s["_norm"]) - base - 5
        if extra > EXTRA_TOL:
            continue  # 특별 에디션(추가 수식어) → 표준 국내가와 비교 부적합
        per100 = s["_usd"] / s["_vol"] * 100
        cand.append((extra, per100, s))
    if not cand:
        return None
    cand.sort(key=lambda x: (x[0], x[1]))  # 표준판 우선, 용량당 최저가
    return cand[0][2]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    args = ap.parse_args()

    usd_krw, fx_asof = load_fx()
    dom = load_domestic()
    canon = load_canonical()
    shilla = load_shilla(args.date)

    matches = []
    for c in canon:
        cid = c["id"]
        d = dom.get(cid)
        if not d:
            continue  # 국내가 없는 정본은 비교 불가
        s = best_shilla_match(c, shilla)
        if not s:
            continue
        dom_vol = c["_vol"]                       # 국내 표준 용량(대개 700ml)
        duty_krw = round(s["_usd"] * usd_krw)      # 면세 병당 환산가
        dom_low = round(d["low"])                  # 국내 병당 최저가
        # 100ml당 단가로 정규화(700 vs 1000ml 등 용량차 보정)
        duty_p100 = duty_krw / s["_vol"] * 100
        dom_p100 = dom_low / dom_vol * 100
        save_pct = (dom_p100 - duty_p100) / dom_p100 * 100
        matches.append({
            "canonical_id": cid,
            "위스키": c["name_ko"],
            "신라상품명": s["위스키명"],
            "면세_USD": s["_usd"],
            "면세용량_ml": s["_vol"],
            "면세_KRW": duty_krw,
            "면세_₩100ml": round(duty_p100),
            "국내용량_ml": dom_vol,
            "국내최저_KRW": dom_low,
            "국내현재_KRW": round(d["cur"]),
            "국내_₩100ml": round(dom_p100),
            "국내채널": "·".join(sorted(d["ch"])),
            "매력도_%": round(save_pct, 1),
            "면세할인율_%": s["할인율_%"],
            "상품URL": s["상품URL"],
        })

    matches.sort(key=lambda x: -x["매력도_%"])

    # CSV 산출
    out_csv = os.path.join(ROOT, "data", "shilla-dutyfree",
                           f"면세_매력도_매칭_{args.date}.csv")
    fields = ["canonical_id", "위스키", "신라상품명", "면세_USD", "면세용량_ml",
              "면세_KRW", "면세_₩100ml", "국내용량_ml", "국내최저_KRW",
              "국내현재_KRW", "국내_₩100ml", "국내채널", "매력도_%",
              "면세할인율_%", "상품URL"]
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(matches)

    # 리포트 MD
    rep_dir = os.path.join(ROOT, "reports", "shilla-dutyfree")
    os.makedirs(rep_dir, exist_ok=True)
    out_md = os.path.join(rep_dir, f"면세_가성비_매력도_{args.date}.md")
    win = [m for m in matches if m["매력도_%"] > 0]
    lose = [m for m in matches if m["매력도_%"] <= 0]
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("# 신라면세 위스키 — 면세 가성비 매력도 분석\n\n")
        f.write(f"- 분석일: {args.date} (KST)  ·  환율: 1 USD = {usd_krw:,.2f} KRW (asof {fx_asof})\n")
        f.write(f"- 매칭: 정본 88종 중 **국내가·면세가 동시 보유 {len(matches)}종** 비교\n")
        f.write(f"- 면세 유리 {len(win)}종 / 국내 유리 {len(lose)}종\n")
        f.write("- **매력도 = (국내 100ml단가 − 면세 100ml단가) / 국내단가** · 양수=면세가 저렴(용량차 보정)\n\n")
        f.write("> ⚠️ 면세가는 **해외 출국 전제** + 면세 주류 한도(2병/2L/$400) 적용. 순수 가격차익이며 여행비 미반영. 표준판만 비교(특별 피니시·미니·매그넘 제외). 국내가는 마트/데일리샷 최저가.\n\n")

        def table(rows):
            f.write("| 위스키 | 면세 | 면세₩/100ml | 국내최저 | 국내₩/100ml | 매력도 | 국내채널 |\n")
            f.write("|---|--:|--:|--:|--:|--:|---|\n")
            for m in rows:
                f.write(f"| {m['위스키']} | ${m['면세_USD']:,.0f}/{m['면세용량_ml']}ml | "
                        f"{m['면세_₩100ml']:,} | {m['국내최저_KRW']:,}/{m['국내용량_ml']}ml | "
                        f"{m['국내_₩100ml']:,} | {m['매력도_%']:+.1f}% | {m['국내채널']} |\n")

        f.write("## 🥇 면세 가성비 TOP (면세가 더 저렴한 순)\n\n")
        table(win)
        if lose:
            f.write("\n## 국내가 더 저렴 (면세 메리트 없음)\n\n")
            table(lose)
        f.write("\n---\n_출처: 신라면세 shilladfs.com(USD) · 국내 normalized_prices(마트·데일리샷) · FX open.er-api.com_\n")

    print(f"매칭 {len(matches)}종 (면세유리 {len(win)} / 국내유리 {len(lose)})")
    print(f"환율 1USD={usd_krw:.2f}KRW")
    print(f"CSV  -> {out_csv}")
    print(f"리포트-> {out_md}")
    print("\n=== 면세 매력도 순위 ===")
    for m in matches:
        print(f"{m['매력도_%']:+6.1f}%  {m['위스키']:18} 면세{m['면세_₩100ml']:>6,}₩/100ml vs 국내{m['국내_₩100ml']:>6,}₩/100ml ({m['면세용량_ml']}ml)")


if __name__ == "__main__":
    main()
