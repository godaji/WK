#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""피트 위스키: 신라면세(USD) vs 해외 현지 소매가(HK/JP/TW) 가격매력도.

회사 보유 해외 위스키 데이터셋(HK/JP/TW Shopify·소매 크롤)을 USD로 환산해
신라면세 면세가와 비교, 가격매력도를 계산한다.

매칭: 각 피트 위스키의 (영문 브랜드 토큰 + 숙성연수)로 해외 행의
      상품명·URL(영문 슬러그)을 스캔해 같은 표현을 찾는다. (HK=영문명,
      JP/TW=일/중문명이지만 URL에 영문 슬러그가 있어 교차매칭 가능)

가격: 모든 해외 파일의 공통 컬럼 `기준가_KRW` ÷ FX(KRW/USD) = 현지가 USD.
      용량 차이 보정 위해 700ml 환산 단가(USD/700ml)로 비교.

가격매력도% = (해외참조가 - 신라면세가) / 해외참조가 × 100
  · 양수 = 신라면세가 더 쌈(유리). 참조가 = 매칭된 해외 최저가 / 중앙값.

주의: 해외가는 '현지 소매가(세금 포함, 면세 아님)' — 여행자 현지구매 기준
      근사치. EU/US는 사내 데이터 자산이 없어 이번 비교에서 제외(후속 소싱 필요).
"""
import csv
import os
import re
import json
import statistics

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(ROOT, "data", "shilla-dutyfree")
WP = os.path.join(ROOT, "data", "whisky-prices")
DATE = os.environ.get("SHILLA_DATE", "2026-06-06")

SRC_PEATED = os.path.join(DATA, f"신라면세_피트위스키_매력도_{DATE}.csv")
OVERSEAS = {
    "HK": os.path.join(WP, "2026-06_hk_whisky_poc.csv"),
    "JP": os.path.join(WP, "jp", "2026-06_jp_shopify_poc.csv"),
    "TW": os.path.join(WP, "2026-05_tw_whisky_poc.csv"),
}

# 한국어 브랜드 -> 매칭 신호(영문 슬러그 + 日/中 표기). 상품명+URL 에서 검색.
# 코어 6종은 JP(가타카나)·TW(중문) 표기를 함께 넣어 다지역 매칭.
BRAND_TOKENS = {
    "보모어": ["bowmore", "ボウモア", "波摩"],
    "라프로익": ["laphroaig", "ラフロイグ", "拉弗格", "拉佛格"],
    "아드벡": ["ardbeg", "アードベッグ", "雅柏", "阿貝"],
    "라가불린": ["lagavulin", "ラガヴーリン", "樂加維林"],
    "쿨일라": ["caol ila", "caolila", "caol-ila", "カリラ", "卡爾里拉", "卡里拉"],
    "옥토모어": ["octomore"],
    "포트샬롯": ["port charlotte", "port-charlotte"],
    "브룩라디": ["bruichladdich"],
    "탈리스커": ["talisker", "タリスカー", "泰斯卡"],
    "암룻": ["amrut"],
    "폴 존": ["paul john", "paul-john"],
    "폴존": ["paul john", "paul-john"],
    "컴파스 박스": ["compass box", "compass-box", "peat monster"],
    "밀크앤허니": ["milk & honey", "milk and honey", "m&h", "milk-honey"],
    "마츠이": ["matsui"],
    "벤리악": ["benriach"],
    "발베니": ["balvenie"],
    "더글라스랭": ["big peat", "douglas laing", "big-peat"],
    "킬호만": ["kilchoman"],
    "글렌리벳": ["caperdonich"],   # 시크릿 스페이사이드 = Caperdonich
}
# 브랜드를 상품명에서 영문으로 못잡는 인디/한정(해외소매 부재 가능성↑) → 매핑 없음 처리
NO_MAP_NOTE = "해외 소매 데이터에 표준화 매칭 어려움(인디/한정/소량)"

# 신라(피트) 쪽 인디 보틀러 브랜드 = 공식 OB 아님 → 점수 제외
INDIE_BOTTLER_BRANDS = [
    "고든 앤 맥패일", "고든앤맥패일", "시그나토리", "더글라스랭", "더글라스 랭",
    "엘리먼츠 오브 아일라", "컴파스 박스", "더 아일라 보이즈", "턴테이블",
]
# 해외 행이 인디 보틀러·한정·싱글캐스크면 공식 OB 비교 대상서 제외(가격왜곡 방지)
OB_EXCLUDE_MARKERS = [
    "smws", "berry", "first editions", "murray mcdavid", "north star",
    "gordon & macphail", "gordon and macphail", "g&m", "signatory",
    "douglas laing", "kinship", "decadent", "hunter laing", "boutique",
    "cadenhead", "single cask", "distillery exclusive", "feis ile",
    "hand filled", "handfilled", "hand-filled", "connoisseurs choice",
    "old particular", "provenance", "chieftain", "blackadder", "elixir",
    "adelphi", "watt whisky", "claxton", "dramfool", "thompson",
    "carn mor", "càrn mòr", "secret", "equinox", "solstice", "exclusive",
    "px sherry cask", "sherry oak cask", "rare release", "edition no",
    "cask series", "benchmark", "that boutique", "1990", "1991", "1992",
    "1993", "1994", "1995", "1996", "1997", "1998", "1999", "2000", "2001",
    "2002", "2003", "2004", "2005", "2006", "2007", "2008",
    # 日: 인디·한정·DE 등 (正規/並行=정식/병행수입이라 유지)
    "キングスバリー", "ゴードン", "マクファイル", "シグナトリー", "限定",
    "スペシャルリリース", "ディスティラーズ エディション", "ディスティラーズエディション",
    "酒廠", "ハンドフィルド", "カスクストレングス", "シングルカスク",
    # 中: 限量(한정)·原酒(CS)·臻選/酒廠限定/聯名(특별)
    "限量", "原酒", "臻選", "酒廠限定", "聯名", "單桶", "私人",
]


def parse_age(name):
    # 년(한)·年(日/中)·y/yo/yr/year(영) 모두 인식
    m = re.findall(r"(\d{1,2})\s*(?:년|年|y\b|yo|yr|year)", name.lower())
    ages = [int(x) for x in m if 3 <= int(x) <= 80]
    return max(ages) if ages else None


def parse_size_ml(name):
    m = re.search(r"(\d{3,4})\s*ml", name.lower())
    if m:
        return int(m.group(1))
    if re.search(r"\b1l\b|1000ml|1\.0l", name.lower()):
        return 1000
    return 700


def brand_signals(kr_name, kr_brand):
    hay = f"{kr_name} {kr_brand}"
    sigs = []
    for kr, toks in BRAND_TOKENS.items():
        if kr in hay:
            sigs.extend(toks)
    return list(dict.fromkeys(sigs))


def load_overseas():
    krw_usd = None
    with open(os.path.join(WP, "fx", "fx_latest.json"), encoding="utf-8") as f:
        krw_usd = json.load(f)["raw_usd"]["KRW"]
    out = {}
    for region, path in OVERSEAS.items():
        rows = []
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                krw = r.get("기준가_KRW") or ""
                try:
                    krw = float(krw)
                except ValueError:
                    continue
                if krw <= 0:
                    continue
                name = r.get("술이름", "")
                url = r.get("URL", "")
                rows.append({
                    "name": name, "url": url,
                    "hay": (name + " " + url).lower(),
                    "usd": krw / krw_usd,
                    "size": parse_size_ml(name),
                    "age": parse_age(name),
                    "stock": r.get("재고", ""),
                })
        out[region] = rows
    return out


# 신뢰 매칭 가능한 단일증류소 코어(숙성표기+브랜드 = 동일 SKU 근사)
CORE_DISTILLERY = ["보모어", "라프로익", "아드벡", "라가불린", "쿨일라", "탈리스커"]


def match_region(sigs, age, rows):
    """브랜드 신호+숙성연수로 해외행 매칭. 700ml 환산 USD 리스트 반환.

    숙성표기 동일(±0) + 용량 500ml↑(미니 제외)만 채택해 동일 SKU 근사."""
    if not sigs or age is None:
        return []
    hits = []
    for row in rows:
        if (row["size"] or 700) < 500:      # 미니/샘플 제외
            continue
        if any(m in row["hay"] for m in OB_EXCLUDE_MARKERS):  # 인디/한정 제외
            continue
        if not any(s in row["hay"] for s in sigs):
            continue
        if row["age"] != age:               # 동일 숙성연수만
            continue
        unit = row["usd"] * (700.0 / (row["size"] or 700))
        hits.append((unit, row))
    return hits


def main():
    with open(SRC_PEATED, encoding="utf-8-sig") as f:
        peated = list(csv.DictReader(f))
    overseas = load_overseas()

    def fnum(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    out_rows = []
    for p in peated:
        name = p["위스키명"]
        shilla_usd = fnum(p.get("라이브할인가")) or fnum(p.get("할인가_USD"))
        size = parse_size_ml(name)
        shilla_unit = shilla_usd * (700.0 / size) if shilla_usd else None
        age = parse_age(name)
        sigs = brand_signals(name, p.get("브랜드", ""))
        is_core = any(c in name or c in p.get("브랜드", "") for c in CORE_DISTILLERY)
        is_indie = any(b in p.get("브랜드", "") or b in name for b in INDIE_BOTTLER_BRANDS)
        scoreable = is_core and age is not None and not is_indie

        region_prices = {}   # region -> median unit usd
        region_n = {}
        if scoreable:
            for region, rows in overseas.items():
                hits = match_region(sigs, age, rows)
                if hits:
                    units = [h[0] for h in hits]
                    region_prices[region] = round(statistics.median(units), 1)
                    region_n[region] = len(hits)

        all_units = list(region_prices.values())
        ref_min = min(all_units) if all_units else None
        ref_max = max(all_units) if all_units else None
        ref_med = round(statistics.median(all_units), 1) if all_units else None

        if shilla_unit and ref_med:
            attr_vs_min = round((ref_min - shilla_unit) / ref_min * 100, 1)
            attr_vs_med = round((ref_med - shilla_unit) / ref_med * 100, 1)
        else:
            attr_vs_min = attr_vs_med = None

        if not scoreable:
            note = "비교제외: 표준 표현 매칭 불가(NAS/버전/한정/인디)"
            conf = ""
        elif not all_units:
            note = "코어 증류소·동일숙성 해외 매칭 0건"
            conf = ""
        else:
            conf = "MED(고숙성·에디션편차)" if age >= 25 else "HIGH"
            note = f"동일숙성 매칭 {sum(region_n.values())}건/{len(all_units)}개지역"

        out_rows.append({
            "위스키명": name,
            "브랜드": p.get("브랜드", ""),
            "구매가능": p.get("구매가능", ""),
            "신라면세가_USD": round(shilla_usd, 1) if shilla_usd else "",
            "신라700ml환산_USD": round(shilla_unit, 1) if shilla_unit else "",
            "HK_USD": region_prices.get("HK", ""),
            "JP_USD": region_prices.get("JP", ""),
            "TW_USD": region_prices.get("TW", ""),
            "해외최저_USD": ref_min if ref_min else "",
            "해외중앙_USD": ref_med if ref_med else "",
            "해외최고_USD": ref_max if ref_max else "",
            "매칭지역수": len(all_units),
            "신뢰도": conf,
            "가격매력도_vs최저_%": attr_vs_min if attr_vs_min is not None else "",
            "가격매력도_vs중앙_%": attr_vs_med if attr_vs_med is not None else "",
            "종합매력도": p.get("매력도", ""),
            "라이브할인율": p.get("라이브할인율", ""),
            "비고": note,
            "상품URL": p.get("상품URL", ""),
        })

    # 매칭된 것(구매가능) 우선, 가격매력도 vs최저 desc
    def sk(r):
        v = r["가격매력도_vs최저_%"]
        return (r["구매가능"] != "Y", r["매칭지역수"] == 0,
                -(v if isinstance(v, float) else -999))
    out_rows.sort(key=sk)

    cols = list(out_rows[0].keys())
    out = os.path.join(DATA, f"신라면세_피트위스키_해외비교_{DATE}_v2.csv")
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out_rows)

    matched = [r for r in out_rows if r["매칭지역수"] > 0]
    print(f"전체 {len(out_rows)}종 / 해외 신뢰매칭 {len(matched)}종 "
          f"(코어 증류소·동일숙성만)")
    print(f"출력: {out}\n")
    print("=== 신라면세 vs 해외 가격매력도 (vs해외중앙값 내림차순, 700ml환산 USD) ===")
    for r in sorted(matched, key=lambda x: -(x["가격매력도_vs중앙_%"]
                    if isinstance(x["가격매력도_vs중앙_%"], float) else -999)):
        sign = "신라쌈" if isinstance(r["가격매력도_vs중앙_%"], float) and r["가격매력도_vs중앙_%"] > 0 else "해외쌈"
        print(f"  vs중앙 {str(r['가격매력도_vs중앙_%'])+'%':>7} [{sign}] {r['신뢰도']:<14} "
              f"신라${r['신라700ml환산_USD']:>6} vs HK={r['HK_USD']} JP={r['JP_USD']} TW={r['TW_USD']}"
              f" ({r['구매가능']}) | {r['위스키명']}")
    return out_rows


if __name__ == "__main__":
    main()
