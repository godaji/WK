#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""신라면세 피트 위스키 종합 MD 리포트 생성.

기존 산출 CSV(매력도·원화구간·해외비교)와 데일리샷(한국 기준가)을 합쳐
reports/shilla-dutyfree/피트위스키_리포트_<date>.md 를 생성한다.

의존성(CMPA-235): 입력 분석 CSV(`신라면세_피트위스키_매력도_<date>.csv` 등)는 모두 그날의
신라 오늘자 raw CSV `신라면세_위스키_<date>.csv` 수집에서 파생된다. 따라서 리포트 생성은
`<date>` 신라 오늘자 수집에 의존 — 없으면 먼저 수집해야 한다(오케스트레이터
run_shilla_pipeline.py 가 report 스테이지 전에 강제). 일반 위스키가격리포트는 신라와 무관.

보드 확정 사항:
  · 환율 1,500원/USD 가정
  · 심리저항선 10/20/30만원 구간
  · 한국 기준가 = 데일리샷 최저가 (코스트코는 피트 미취급 → 제외)
"""
import csv
import os
import re

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
DATA = os.path.join(ROOT, "data", "shilla-dutyfree")
WP = os.path.join(ROOT, "data", "whisky-prices")
REPORTS = os.path.join(ROOT, "reports", "shilla-dutyfree")
DATE = os.environ.get("SHILLA_DATE", "2026-06-06")
FX = 1500

CORE = ["보모어", "라프로익", "아드벡", "라가불린", "쿨일라", "탈리스커"]
CORE_TOK = {
    "보모어": ["보모어"], "라프로익": ["라프로익"], "아드벡": ["아드벡", "아드베그"],
    "라가불린": ["라가불린"], "쿨일라": ["쿨일라", "카올일라"], "탈리스커": ["탈리스커"],
}


def rd(path):
    with open(path, encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def fnum(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def parse_age(n):
    m = re.findall(r"(\d{1,2})\s*년", n or "")
    a = [int(x) for x in m if 3 <= int(x) <= 80]
    return max(a) if a else None


def size_ml(n):
    if re.search(r"1000ml|1l\b|1L", n or ""):
        return 1000
    if "750" in (n or ""):
        return 750
    return 700


def load_dailyshot():
    rows = []
    for fn in ["2026-06_dailyshot.csv"]:
        p = os.path.join(WP, fn)
        if not os.path.exists(p):
            continue
        for r in rd(p):
            price = fnum(r.get("가격_KRW"))
            if not price:
                continue
            rows.append({"n": r["위스키명"], "p": int(price),
                         "age": parse_age(r["위스키명"]), "size": size_ml(r["위스키명"])})
    return rows


def dailyshot_match(name, brand, ds):
    """(정합가, 정합명, 참고가, 참고명) — 정합=동일증류소+동일연수, 참고=동일증류소 최저."""
    hay = f"{name} {brand}"
    toks = []
    for kr, t in CORE_TOK.items():
        if kr in hay:
            toks.extend(t)
    if not toks:
        return None, None, None, None
    age = parse_age(name)
    same_brand = [d for d in ds if any(t in d["n"] for t in toks)]
    if not same_brand:
        return None, None, None, None
    # 700ml 환산해서 비교 일관성
    for d in same_brand:
        d["p700"] = round(d["p"] * 700 / (d["size"] or 700))
    exact = [d for d in same_brand if age is not None and d["age"] == age]
    e = min(exact, key=lambda x: x["p700"]) if exact else None
    ref = min(same_brand, key=lambda x: x["p700"])
    return (e["p700"] if e else None, e["n"] if e else None,
            ref["p700"], ref["n"])


def band(krw):
    if krw is None:
        return ""
    if krw <= 100_000:
        return "10만 이하"
    if krw <= 200_000:
        return "10~20만"
    if krw <= 300_000:
        return "20~30만"
    return "30만 초과"


def won(v):
    return f"₩{int(v):,}" if v not in (None, "") else "—"


def main():
    attr = rd(os.path.join(DATA, f"신라면세_피트위스키_매력도_{DATE}.csv"))
    intl = rd(os.path.join(DATA, f"신라면세_피트위스키_해외비교_{DATE}_v2.csv"))
    ds = load_dailyshot()

    by_name = {r["위스키명"]: r for r in attr}
    intl_by = {r["위스키명"]: r for r in intl}

    # 데일리샷 한국가 부착
    for r in attr:
        usd = fnum(r.get("라이브할인가")) or fnum(r.get("할인가_USD"))
        r["_usd"] = usd
        r["_krw"] = round(usd * FX) if usd else None
        sz = size_ml(r["위스키명"])
        r["_krw700"] = round(usd * FX * 700 / sz) if usd else None
        e, en, ref, refn = dailyshot_match(r["위스키명"], r.get("브랜드", ""), ds)
        r["_ds_exact"], r["_ds_exact_n"] = e, en
        r["_ds_ref"], r["_ds_ref_n"] = ref, refn

    avail = [r for r in attr if r["구매가능"] == "Y"]
    L = []
    A = L.append
    A(f"# 신라면세 피트 위스키 리포트")
    A("")
    A(f"- 📅 작성일: {DATE}")
    A(f"- 데이터 출처: 신라면세점 라이브(키리스 AJAX) · 사내 해외 위스키 데이터(HK/JP/TW) · 데일리샷(국내 한국가)")
    A(f"- 환율 가정: **1 USD = {FX:,}원** (보드 지정) / 면세가 단위는 USD")
    A(f"- 대상: 신라면세 위스키 656종 → **피트 위스키 64종** 추출 → 구매가능 **{len(avail)}종**")
    A("")
    A("> ⚠️ 한국 기준가는 **데일리샷 최저가**를 사용한다(코스트코는 피트 아일라 싱글몰트 미취급으로 매칭 0건). "
      "피트 위스키는 국내 정규 소매 취급이 희박해 데일리샷 정합 매칭도 소수에 그친다.")
    A("")

    # 1. 방법론
    A("## 1. 방법론")
    A("")
    A("- **피트 판정**: 피트 컬럼이 없어 ①항상-피트 증류소(보모어·라프로익·아드벡·라가불린·쿨일라·옥토모어·포트샬롯) "
      "②명시 키워드(피트/peated/big peat) ③아일라 산지 신호로 판정. 분류 A=강한 피트 / B=스모키 섬 몰트.")
    A("- **구매가능**: 신라면세 라이브 `allowProductPurchase` & `재고>0`. (품절 16종 제외)")
    A("- **매력도**(0~100) = 0.45·가격메리트 + 0.40·희소성 + 0.15·수요 "
      "(가격=할인율+절감액, 희소=숙성연수+한정+재고, 수요=누적판매·리뷰).")
    A("- **가격 비교 신뢰 가드**: 코어 단일증류소 + 동일 숙성연수만 정합 비교(NAS·버전·한정·인디 보틀러는 동일 SKU 매칭 불가→제외). "
      "용량 상이 시 700ml 환산.")
    A("- **한국가(데일리샷)**: 동일 증류소+동일 연수=정합가, 동일 증류소 최저가(표현 상이)=참고가.")
    A("")

    # 2. 매력도 TOP 20
    A("## 2. 매력도 TOP 20 (구매가능)")
    A("")
    A("| # | 위스키 | 면세 USD | 원화(×1500) | 심리구간 | 매력도 | 근거 |")
    A("|---|--------|---------:|-----------:|----------|------:|------|")
    top = sorted([r for r in avail if fnum(r.get("매력도")) is not None],
                 key=lambda r: -fnum(r["매력도"]))[:20]
    for i, r in enumerate(top, 1):
        A(f"| {i} | {r['위스키명']} | ${r['_usd']:.0f} | {won(r['_krw'])} | {band(r['_krw'])} "
          f"| {r['매력도']} | {r.get('매력근거','')} |")
    A("")

    # 3. 심리저항선 구간
    from collections import Counter
    bc = Counter(band(r["_krw"]) for r in avail)
    A("## 3. 심리저항선 구간 분포 (구매가능 48종, 면세가 원화환산)")
    A("")
    A("| 구간 | 종수 |")
    A("|------|-----:|")
    for b in ["10만 이하", "10~20만", "20~30만", "30만 초과"]:
        A(f"| {b} | {bc.get(b,0)} |")
    A("")
    A("**10만원 이하 가성비대 (원화 오름차순)**")
    A("")
    A("| 위스키 | 면세 원화 | 매력도 |")
    A("|--------|---------:|------:|")
    for r in sorted([x for x in avail if x["_krw"] and x["_krw"] <= 100000],
                    key=lambda x: x["_krw"]):
        A(f"| {r['위스키명']} | {won(r['_krw'])} | {r.get('매력도','')} |")
    A("")

    # 4. 한국(데일리샷) 비교
    A("## 4. 한국(데일리샷) vs 신라면세 비교")
    A("")
    A("> 700ml 환산 기준. **정합**=데일리샷에 동일 증류소·동일 연수 존재 / **참고**=동일 증류소 최저가(표현 상이, 참고용).")
    A("")
    A("| 위스키 | 신라면세(700ml환산) | 데일리샷 정합 | 차이 | 데일리샷 참고(표현상이) |")
    A("|--------|------------------:|-------------|-----:|----------------------|")
    any_ds = False
    for r in attr:
        if not (r["_ds_exact"] or r["_ds_ref"]):
            continue
        if r["구매가능"] != "Y" and not r["_ds_exact"]:
            continue
        any_ds = True
        diff = (r["_krw700"] - r["_ds_exact"]) if (r["_krw700"] and r["_ds_exact"]) else None
        exact = f"{won(r['_ds_exact'])} ({r['_ds_exact_n']})" if r["_ds_exact"] else "—"
        refc = f"{won(r['_ds_ref'])} ({r['_ds_ref_n']})" if r["_ds_ref"] else "—"
        diffs = (f"{'+' if diff>0 else ''}{int(diff):,}" if diff is not None else "—")
        A(f"| {r['위스키명']} | {won(r['_krw700'])} | {exact} | {diffs} | {refc} |")
    if not any_ds:
        A("| (정합 매칭 없음) | | | | |")
    A("")
    A("- **정합 매칭은 탈리스커 10년이 사실상 유일** — 신라면세(700ml환산)가 데일리샷보다 비싼 편. "
      "나머지 코어 피트(보모어·아드벡·라가불린 등)는 데일리샷 미취급 또는 연수 불일치로 정합 비교 불가.")
    A("- 즉 **피트 위스키는 국내 소매가 형성이 약해, 신라면세 가격의 적정성을 국내가로 검증하기 어렵다** → 해외 비교(5절)가 더 유효.")
    A("")

    # 5. 해외 비교
    A("## 5. 해외(홍콩·일본·대만) 소매가 비교")
    A("")
    A("> 700ml 환산 USD. 코어 증류소·동일 연수만 신뢰 매칭(9종). +면세유리 / −해외유리. 해외가=현지 소매(세금 포함).")
    A("")
    A("| 위스키 | 구매 | 신라면세 | HK | JP | TW | vs해외중앙 |")
    A("|--------|:---:|--------:|---:|---:|---:|----------:|")
    mi, _seen = [], set()
    for r in intl:
        if not (r.get("매칭지역수") and int(r["매칭지역수"]) > 0):
            continue
        if r["위스키명"] in _seen:
            continue
        _seen.add(r["위스키명"])
        mi.append(r)
    for r in sorted(mi, key=lambda x: -(fnum(x.get("가격매력도_vs중앙_%")) or -999)):
        A(f"| {r['위스키명']} | {r['구매가능']} | ${r['신라700ml환산_USD']} | {r['HK_USD'] or '—'} "
          f"| {r['JP_USD'] or '—'} | {r['TW_USD'] or '—'} | {r['가격매력도_vs중앙_%']}% |")
    A("")
    A("**핵심 인사이트**")
    A("")
    A("- 신라면세 가성비는 **고숙성·희소 보틀(보모어 25·30년)** 에 집중 — 해외 소매보다도 24~37% 저렴.")
    A("- 반대로 **입문 코어 아일라(탈리스커 10·쿨일라 12·라가불린 16)** 는 일본/대만 현지 소매가가 한국 면세보다 50~110% 더 싸 면세 메리트가 없다.")
    A("- 구매가능 3종 중: 보모어 30년=강한 면세 메리트 / 탈리스커 10·쿨일라 12=면세 메리트 약함.")
    A("")

    # 6. 한계
    A("## 6. 한계 및 주의")
    A("")
    A("- 🇪🇺 유럽·🇺🇸 미국 가격은 사내 데이터 자산이 없어 제외(후속 소싱 필요).")
    A("- 코스트코 한국은 피트 아일라 싱글몰트 미취급 → 한국 기준가에서 제외(데일리샷 사용).")
    A("- 해외가는 면세가 아닌 **현지 소매가(세금 포함)** 라 면세 vs 소매 비교의 근사치.")
    A("- NAS·캐스크피니시·한정·인디 보틀러는 동일 SKU 교차매칭이 불가해 가격 비교에서 제외(매력도 순위에는 포함).")
    A("")

    # 7. 산출물
    A("## 7. 산출물 (CSV)")
    A("")
    A("- `data/shilla-dutyfree/신라면세_피트위스키_2026-06-06.csv` — 피트 64종 리스트업")
    A("- `data/shilla-dutyfree/신라면세_피트위스키_매력도_2026-06-06.csv` — 매력도·구매가능·재고")
    A("- `data/shilla-dutyfree/신라면세_피트위스키_TOP20_2026-06-06.csv`")
    A("- `data/shilla-dutyfree/신라면세_피트위스키_100불이하_2026-06-06.csv`")
    A("- `data/shilla-dutyfree/신라면세_피트위스키_원화구간_2026-06-06.csv` — 원화·심리구간")
    A("- `data/shilla-dutyfree/신라면세_피트위스키_해외비교_2026-06-06_v2.csv` — HK/JP/TW 비교")
    A("")

    os.makedirs(REPORTS, exist_ok=True)
    out = os.path.join(REPORTS, f"피트위스키_리포트_{DATE}.md")
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(L))
    print(f"리포트 생성: {out}  ({len(L)} 줄)")
    return out


if __name__ == "__main__":
    main()
