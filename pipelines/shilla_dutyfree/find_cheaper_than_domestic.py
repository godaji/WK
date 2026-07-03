#!/usr/bin/env python3
"""CMPA-138 — 신라면세 위스키 중 50만원 이하 & '국내 최저가보다 저렴'한 위스키 리스트업.

요청: 신라면세점 위스키 중 (1) 면세 환산가 ≤ 500,000원 이면서 (2) 국내 최저가보다
싼 위스키만 추려서 리스트업.

국내 최저가 출처(이중):
  A) 보유 정본 국내가 DB  data/whisky-prices/normalized/normalized_prices.csv (마트+데일리샷)
  B) 데일리샷 라이브 검색 API (api.dailyshot.co) — 보드 지시: 우리 DB(88종)는 커버리지가
     좁으니 데일리샷 라이브로 실제 국내 판매가를 직접 확인 (커버리지 광역)

매칭 키 = 신라 CSV의 '브랜드' 한글 토큰 + 숙성년수.  데일리샷 검색 결과 중 동일 브랜드·
동일 숙성·표준판(미니/매그넘/면세·해외 리스팅 제외) 최저가를 국내 최저가로 사용.
A·B 둘 다 있으면 더 낮은 값을 국내최저로 채택(가장 보수적 = 면세우위 과대주장 방지).

'저렴' 판정은 용량 차이를 보정한 **100ml당 단가** 기준(공정 비교)으로 하되,
병당 절대가도 함께 표기한다.

출력:
  data/shilla-dutyfree/면세_국내최저대비_저렴_<date>.csv
  reports/shilla-dutyfree/면세_국내최저대비_저렴_<date>.md
"""
import argparse
import csv
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))

import enrich_dailyshot as ds  # 같은 폴더: search / best_match 재사용

KRW_CAP = 500_000

EXCLUDE = ds.EXCLUDE


def vol_of(name):
    for m in re.finditer(r"(\d{3,4})\s*ml", name.lower()):
        return int(m.group(1))
    if re.search(r"\b1\s*l\b|1000ml|1\.0\s*l", name.lower()):
        return 1000
    return 700


def age_of(name):
    m = re.search(r"(\d{1,2})\s*(?:년|y|yo|year)", name.lower())
    return int(m.group(1)) if m else None


def norm(s):
    return re.sub(r"[\s()\[\]/·.,'\"-]", "", (s or "").lower())


def load_fx():
    p = os.path.join(ROOT, "data", "whisky-prices", "fx", "fx_latest.json")
    fx = json.load(open(p, encoding="utf-8"))
    return fx["raw_usd"]["KRW"], fx.get("asof")


def load_domestic_db():
    """canonical_name_ko(norm) -> 국내 최저 KRW (마트+데일리샷). 부분일치 보조용."""
    p = os.path.join(ROOT, "data", "whisky-prices", "normalized",
                     "normalized_prices.csv")
    out = {}
    for r in csv.DictReader(open(p, encoding="utf-8-sig")):
        if r.get("status") != "matched" or r["market"] not in ("KR", "KR-DS"):
            continue
        try:
            price = float(r["price_krw"])
        except (ValueError, TypeError):
            continue
        if price <= 0:
            continue
        key = norm(r["canonical_name_ko"])
        vol = 700
        try:
            vol = int(r["volume_ml"]) if r.get("volume_ml") else 700
        except ValueError:
            vol = 700
        cur = out.get(key)
        if cur is None or price < cur[0]:
            out[key] = (price, vol, r["canonical_name_ko"])
    return out


def db_lookup(shilla_name, db):
    """신라명에 정본명이 부분포함 + 디스크립터 동일 + 희귀아님이면 그 국내가 채택."""
    if RARE_SHILLA.search(shilla_name):
        return None
    shilla_norm = norm(shilla_name)
    sdesc = descriptor_set(shilla_name)
    best = None
    for key, (price, vol, name) in db.items():
        if len(key) >= 4 and key in shilla_norm:
            if descriptor_set(name) != sdesc:
                continue  # 표준 정본에 신라 특별판 매칭 방지
            if best is None or len(key) > len(best[3]):
                best = (price, vol, name, key)
    if best:
        return {"price": best[0], "vol": best[1], "name": best[2], "src": "보유DB"}
    return None


# 비교 부적합: 신라 측에 이런 신호가 있으면 '희귀/단독 보틀링' → 표준 국내가와 비교 불가
RARE_SHILLA = re.compile(
    r"싱글\s*캐스크|single\s*cask|캐스크\s*#|cask\s*#|#\s*\d{2,}|"
    r"펀천|puncheon|패밀리\s*캐스크|family\s*cask|"
    r"\b20\d{2}\b|\bs\d{2}\b|벌크|배치\s*\d|"
    r"시크릿\s*스페이사이드|secret\s*spey", re.I)

# 데일리샷 매칭이 인디/독립 보틀러면 OB 표준판과 비교 부적합 → 제외
INDIE_MARK = ["시그나토리", "signatory", "하트브라더스", "하트 브라더스", "hart",
              "고든앤맥페일", "고든 앤 맥페일", "맥페일", "더글라스랭", "더글라스 랭",
              "douglas", "카덴헤드", "cadenhead", "베리브라더스", "berry",
              "블랙애더", "blackadder", "던컨테일러", "duncan", "위스키칸",
              "명작", "단독", "독점", "한정수량", "창고", "대방출", "스페셜에디션",
              "디 오리지널", "산시바", "sansibar", "파이니스트", "엘릭서", "elixir",
              "더 메일", "이그조틱", "엠오에스"]

# 피니시·강도·named-edition 신호: 두 이름의 '디스크립터 집합'이 같아야 동일 SKU로 인정
EDITION_GROUPS = {
    "sherry": ["셰리", "쉐리", "sherry", "올로로소", "올로로쏘", "oloroso"],
    "port": ["포트", "port"],
    "madeira": ["마데이라", "madeira"],
    "peat": ["피트", "피티드", "peat"],
    "moscatel": ["모스카텔", "모스까뗄", "moscatel"],
    "mizunara": ["미즈나라", "mizunara"],
    "virgin": ["버진오크", "버진 오크", "virginoak", "virgin"],
    "caskstr": ["캐스크스트랭스", "케스크스트랭스", "배치스트렝스", "캐스크스트렝스",
                "caskstrength", "batchstrength", "나두라", "naduurra", "nadurra"],
    "smallbatch": ["스몰배치", "smallbatch"],
    "rye": ["라이", " rye", "rye "],
    "straight": ["스트레이트", "straight"],
    "triple": ["트리플", "triple"],
    "golden": ["골든", "golden"],
    "perpetual": ["퍼페추얼", "퍼페츄얼", "perpetual", "vat", "벳", "벹", "퍼페추열"],
    "firstfill": ["퍼스트필", "firstfill", "first-fill", "firstfilledition"],
    "tribute": ["트리뷰트", "tribute"],
    "nectar": ["넥타", "nectar"],
    "bear": ["bear"],
    "laddie8": ["laddie8", "라디8", "laddie 8"],
    "weekofpeat": ["위크오브피트", "weekofpeat", "weekof"],
    "changeling": ["체인질링", "changeling"],
    "unforgotten": ["언포가튼", "unforgotten"],
    "triumph": ["트라이엄프", "triumph"],
    "px": ["px", "피엑스"],
}


SIG_STOP = {"single", "malt", "whisky", "whiskey", "cask", "casks", "edition",
            "collection", "old", "the", "scotch", "blended", "years", "year",
            "bourbon", "rye", "reserve", "싱글", "몰트", "위스키", "캐스크",
            "에디션", "컬렉션", "블렌디드", "년산", "오크", "스카치"}


SIG_STRIP = ["싱글몰트위스키", "싱글 몰트 위스키", "싱글몰트", "싱글 몰트",
             "블렌디드몰트", "위스키", "whiskey", "whisky", "싱글", "몰트",
             "캐스크", "casks", "cask", "에디션", "edition", "컬렉션",
             "collection", "스카치", "scotch", "블렌디드", "blended", "오크",
             "years", "year", "old", "the", "reserve", "바틀드", "bottled"]


def sig_token(name, brand):
    """브랜드·숙성·용량·일반어 제외 후 가장 긴 식별 토큰(한·영). NAS 라인 구분용.

    일반어는 부분문자열로 먼저 제거('싱글몰트' 같은 붙은 합성어도 잡음)."""
    t = name.lower()
    t = re.sub(r"\d+\s*(?:ml|년|y|yo|years?|l)\b", " ", t)
    t = t.replace((brand or "").lower(), " ")
    for g in SIG_STRIP:
        t = t.replace(g, " ")
    toks = re.findall(r"[a-z]{3,}|[가-힣]{2,}", t)
    toks = [x for x in toks if x not in SIG_STOP]
    return max(toks, key=len) if toks else None


def descriptor_set(name):
    n = norm(name)
    nl = name.lower()
    out = set()
    for g, variants in EDITION_GROUPS.items():
        for v in variants:
            vv = v.strip()
            if (vv and norm(vv) and norm(vv) in n) or (v in nl):
                out.add(g)
                break
    # 프루프/표현 식별번호(80~151 범위의 단독 2~3자리: 101 vs 81 등 구분)
    t = re.sub(r"\d+\s*(?:ml|년|y|yo|years?|l|%)\b", " ", nl)
    for num in re.findall(r"(?<!\d)(\d{2,3})(?!\d)", t):
        if 80 <= int(num) <= 151:
            out.add(f"n{num}")
    return out


def hangul_anchor(name, brand):
    """신라명에서 가장 긴 한글 식별 토큰(브랜드 포함). 교차브랜드 오매칭 방지용."""
    t = name.lower()
    t = t.replace((brand or "").lower(), " " + (brand or "").lower() + " ")
    for g in SIG_STRIP:
        t = t.replace(g, " ")
    toks = [x for x in re.findall(r"[가-힣]{3,}", t) if x not in SIG_STOP]
    if brand and re.search(r"[가-힣]{3,}", brand):
        toks.append(re.sub(r"\s", "", brand))
    return max(toks, key=len) if toks else None


def ds_keyword(brand, name):
    brand = (brand or "").strip()
    age = age_of(name)
    if not brand or not re.search(r"[가-힣]", brand):
        return None
    return f"{brand} {age}" if age else brand


def ds_best(brand, name, items):
    """데일리샷 결과 중 **동일 SKU로 신뢰 가능한** 표준 국내 소매가 최저.

    가드: 동일 브랜드 + 동일 숙성 + 디스크립터집합 동일 + 인디보틀러 제외 +
    이름길이 과도 차이 제외. 정밀도 우선(오매칭으로 면세우위 과대주장 방지)."""
    if RARE_SHILLA.search(name):
        return None  # 신라 측이 희귀/단독 → 표준 국내가 비교 불가
    bnorm = norm(brand)
    age = age_of(name)
    sdesc = descriptor_set(name)
    base = len(norm(name))
    # 무숙성(NAS) 제품은 표현 시그니처(한·영) 일치 강제 — 같은 브랜드 다른 라인 오매칭 방지
    sig = sig_token(name, brand) if age is None else None
    anchor = hangul_anchor(name, brand)
    best = None
    for it in items:
        dn = it.get("name") or ""
        dnn = norm(dn)
        if bnorm and bnorm not in dnn:
            continue
        if anchor and norm(anchor) not in dnn:
            continue  # 교차브랜드/다른제품 방지(레드브레스트↔제임슨 등)
        if any(x in dn for x in EXCLUDE) or ds.small_ml(dn):
            continue
        if any(m in dn for m in INDIE_MARK):
            continue  # 인디/단독 보틀러 → OB 표준 비교 부적합
        if age_of(dn) != age:   # 숙성 대칭(둘 다 무숙성이거나 동일 숙성만)
            continue
        if descriptor_set(dn) != sdesc:
            continue  # 피니시·강도·named-edition 불일치 → 다른 SKU
        if sig and norm(sig) not in dnn:
            continue
        # 신라명에 없는 추가 수식어가 8자 초과면 다른(특별)판 → 제외
        extra = len(dnn) - base
        if extra > 10:
            continue
        # 데일리샷이 섞어 보여주는 면세·해외 리스팅 제외(국내 소매가만)
        if (it.get("price_usd") or 0) > 0 or (it.get("net_price_usd") or 0) > 0:
            continue
        try:
            price = int(it.get("price") or 0)
        except (ValueError, TypeError):
            continue
        if price <= 0:
            continue
        if best is None or price < best["price"]:
            # top_product_id = 제품 페이지(/m/item/{tpid}) 전국 최저 셀러가 조회용(CMPA-344)
            best = {"price": price, "vol": vol_of(dn), "name": dn,
                    "src": "데일리샷", "vivino": it.get("vivino_score"),
                    "top_product_id": it.get("top_product_id") or it.get("id")}
    return best


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=time.strftime("%Y-%m-%d"))
    ap.add_argument("--pace", type=float, default=0.6)
    ap.add_argument("--limit", type=int, default=0, help="디버그: 앞 N행만")
    args = ap.parse_args()

    usd_krw, fx_asof = load_fx()
    db = load_domestic_db()

    sp = os.path.join(ROOT, "data", "shilla-dutyfree",
                      f"신라면세_위스키_{args.date}.csv")
    rows = list(csv.DictReader(open(sp, encoding="utf-8-sig")))

    # ≤500K 면세 후보
    cands = []
    for r in rows:
        try:
            usd = float(r["할인가_USD"])
        except (ValueError, TypeError):
            continue
        if usd <= 0:
            continue
        krw = round(usd * usd_krw)
        if krw > KRW_CAP:
            continue
        r["_krw"] = krw
        r["_usd"] = usd
        r["_vol"] = vol_of(r["위스키명"])
        r["_norm"] = norm(r["위스키명"])
        cands.append(r)
    if args.limit:
        cands = cands[: args.limit]

    # 데일리샷 키워드별 캐시 검색
    kw_cache = {}
    page_cache = {}   # CMPA-344: tpid -> 제품 페이지 최저 셀러가(중복 조회 방지)
    results = []
    n_page_hit = n_page_used = 0
    for i, r in enumerate(cands):
        # A) 보유 DB
        a = db_lookup(r["위스키명"], db)
        # B) 데일리샷 라이브
        b = None
        kw = ds_keyword(r["브랜드"], r["위스키명"])
        if kw:
            if kw not in kw_cache:
                time.sleep(args.pace)
                kw_cache[kw] = ds.search(kw)
            b = ds_best(r["브랜드"], r["위스키명"], kw_cache[kw])
            # CMPA-344: 데일리샷 floor 를 검색 대표가 → 제품 페이지 전국 최저가로 전환.
            # 매칭된 후보에만 페이지 1회 조회(tpid 캐시), 실패 시 검색가로 폴백.
            # 페이지 파서(_walk_page_price)도 면세/해외(price_usd>0) 제외 유지(CMPA-321).
            if b and b.get("top_product_id"):
                tpid = b["top_product_id"]
                if tpid not in page_cache:
                    time.sleep(args.pace)
                    page_cache[tpid] = ds.item_page_price(tpid)
                pp = page_cache[tpid]
                if pp and pp.get("price"):
                    n_page_hit += 1
                    if pp["price"] != b["price"]:
                        n_page_used += 1
                    b["ds_search_price"] = b["price"]   # 추적용(검색 대표가)
                    b["price"] = pp["price"]             # floor = 페이지 최저 셀러가
                    b["seller"] = pp.get("seller")
        # 국내최저 = A·B 중 더 낮은 값(있는 것만)
        opts = [x for x in (a, b) if x]
        if not opts:
            r["_dom"] = None
            continue
        dom = min(opts, key=lambda x: x["price"] / max(x["vol"], 1))  # 100ml단가 최저
        r["_dom"] = dom
        if i % 40 == 0:
            print(f"...{i}/{len(cands)} 검색 (키워드캐시 {len(kw_cache)})", flush=True)

    # 비교 산출
    out = []
    for r in cands:
        dom = r.get("_dom")
        if not dom:
            continue
        dom_price = round(dom["price"])
        duty_p100 = r["_krw"] / r["_vol"] * 100
        dom_p100 = dom_price / max(dom["vol"], 1) * 100
        save_p100 = (dom_p100 - duty_p100) / dom_p100 * 100
        save_bottle = dom_price - r["_krw"]
        out.append({
            "위스키명": r["위스키명"],
            "브랜드": r["브랜드"],
            "면세_USD": r["_usd"],
            "면세_KRW": r["_krw"],
            "면세용량_ml": r["_vol"],
            "면세_₩100ml": round(duty_p100),
            "국내최저_KRW": dom_price,
            "국내용량_ml": dom["vol"],
            "국내_₩100ml": round(dom_p100),
            "국내출처": dom["src"],
            "국내매칭명": dom["name"],
            "절감_100ml_%": round(save_p100, 1),
            "절감_병당_KRW": round(save_bottle),
            "구매가능": r.get("구매가능", ""),
            "상품URL": r.get("상품URL", ""),
        })

    # '저렴' = 100ml당 단가 면세가 더 쌈
    cheaper = [m for m in out if m["절감_100ml_%"] > 0]
    for m in cheaper:
        m["구분"] = "①병당도쌈" if m["절감_병당_KRW"] > 0 else "②용량당만쌈"
    # TierA(병당도 쌈) 먼저: 병당 절감 큰 순 → TierB: 100ml 절감 큰 순
    cheaper.sort(key=lambda x: (0 if x["절감_병당_KRW"] > 0 else 1,
                                -x["절감_병당_KRW"] if x["절감_병당_KRW"] > 0
                                else -x["절감_100ml_%"]))

    out_csv = os.path.join(ROOT, "data", "shilla-dutyfree",
                           f"면세_국내최저대비_저렴_{args.date}.csv")
    fields = ["구분", "위스키명", "브랜드", "면세_USD", "면세_KRW", "면세용량_ml",
              "면세_₩100ml", "국내최저_KRW", "국내용량_ml", "국내_₩100ml",
              "국내출처", "국내매칭명", "절감_100ml_%", "절감_병당_KRW",
              "구매가능", "상품URL"]
    with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(cheaper)

    tierA = [m for m in cheaper if m["절감_병당_KRW"] > 0]   # 병당 절대가도 면세<국내
    tierB = [m for m in cheaper if m["절감_병당_KRW"] <= 0]  # 100ml단가만 면세<국내(용량효과)
    tierA.sort(key=lambda x: -x["절감_병당_KRW"])

    rep_dir = os.path.join(ROOT, "reports", "shilla-dutyfree")
    os.makedirs(rep_dir, exist_ok=True)
    out_md = os.path.join(rep_dir, f"면세_국내최저대비_저렴_{args.date}.md")
    availA = [m for m in tierA if m["구매가능"] == "Y"]
    with open(out_md, "w", encoding="utf-8") as f:
        f.write("# 신라면세 위스키 — 50만원 이하 & 국내 최저가보다 저렴 (CMPA-138)\n\n")
        f.write(f"- 분석일 {args.date} (KST) · 환율 1 USD = {usd_krw:,.2f} KRW (asof {fx_asof})\n")
        f.write(f"- 면세 ≤50만원 후보 {len(cands)}종 중 국내가 확인된 {len(out)}종 비교\n")
        f.write(f"- **① 병당 절대가도 국내최저보다 싼 위스키: {len(tierA)}종** (구매가능 {len(availA)}종) ← 핵심 답\n")
        f.write(f"- ② 100ml당 단가만 면세가 쌈(면세 1L vs 국내 700ml 용량효과): {len(tierB)}종 (병당가는 면세가 더 비쌈)\n")
        f.write("- 국내최저 = 보유 정본 국내가 DB(마트·데일리샷) + 데일리샷 라이브검색 중 더 낮은 값.\n\n")
        f.write("> ⚠️ 면세가는 **해외 출국 전제** + 주류 면세한도(2병/2L/$400). 순수 가격차익이며 여행비 미반영. "
                "국내가 매칭은 브랜드·숙성·표현 자동매칭(표준판·동일숙성·동일피니시 가드)으로 소수 근사오차 가능 → 구매 전 개별 확인 권장.\n\n")

        def table(rows, by_bottle=True):
            f.write("| # | 위스키 | 면세(₩) | 국내최저(₩) | 면세₩/100ml | 국내₩/100ml | 절감(병당) | 절감(100ml) | 국내출처 | 구매 |\n")
            f.write("|--:|---|--:|--:|--:|--:|--:|--:|---|:--:|\n")
            for i, m in enumerate(rows, 1):
                f.write(f"| {i} | {m['위스키명']} | {m['면세_KRW']:,} | {m['국내최저_KRW']:,} | "
                        f"{m['면세_₩100ml']:,} | {m['국내_₩100ml']:,} | {m['절감_병당_KRW']:+,} | "
                        f"{m['절감_100ml_%']:+.1f}% | {m['국내출처']} | {m['구매가능']} |\n")

        f.write("## ① 병당 절대가가 국내 최저가보다 싼 위스키 (핵심)\n\n")
        f.write("_병당 절감액 큰 순. 구매가능=Y 만 현재 신라면세 온라인 구매 가능._\n\n")
        table(tierA)
        f.write("\n## ② 용량(100ml)당 단가만 면세가 저렴 (면세 1L vs 국내 700ml)\n\n")
        f.write("_병당가는 면세가 더 비싸지만, 용량당으로는 면세가 이득. 100ml단가 절감 큰 순._\n\n")
        tierB.sort(key=lambda x: -x["절감_100ml_%"])
        table(tierB)
        f.write("\n---\n_출처: 신라면세 shilladfs.com(USD) · 국내 normalized_prices + 데일리샷 라이브 · FX open.er-api.com_\n")

    print(f"\n[DONE] ≤50만원 {len(cands)}종 · 국내가확인 {len(out)}종 · 면세저렴 {len(cheaper)}종 "
          f"(①병당도쌈 {len(tierA)}/구매가능 {len(availA)} · ②용량당만쌈 {len(tierB)})")
    print(f"[CMPA-344] 데일리샷 floor=페이지가: 페이지조회 성공 {n_page_hit}건 "
          f"(검색가와 다름 {n_page_used}건) · tpid캐시 {len(page_cache)}개")
    print(f"CSV  -> {out_csv}")
    print(f"MD   -> {out_md}")
    print("\n=== ① 병당 절대가도 국내보다 싼 TOP 20 (병당 절감순) ===")
    for m in tierA[:20]:
        print(f"병당{m['절감_병당_KRW']:+9,}  면세{m['면세_KRW']:>8,}  국내{m['국내최저_KRW']:>8,}  "
              f"[{m['국내출처']}] {m['위스키명'][:32]}")


if __name__ == "__main__":
    main()
