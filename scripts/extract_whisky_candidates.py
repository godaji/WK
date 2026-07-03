#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
extract_whisky_candidates.py — CMPA-170 bottom-up 신규 SKU 후보 추출기.

normalize_whisky_name 의 audit 미매칭(raw → unmatched)을 용량/케이스/표기변형을
정규화 키(normalize_text)로 묶어 distinct 제품 후보로 만들고, 각 후보에 대해
  - freq(관측 행수), n_variants(원시표기 수), 관측 가격대(min/max)
  - 출처 파일, 대표 원시표기
  - 정본(whisky-list.csv)과의 최근접 유사도(difflib) + 연식 비교
  - 자동 분류 제안: new_sku / synonym_of_existing / review / noise
을 채운 후보 CSV 를 assets/_runs/whisky-list-candidates_<date>.csv 로 생성한다.

over-merge 양방향 가드:
  - 정본과 매우 유사 + 같은(또는 둘 다 없음) 연식 → synonym_of_existing (신규 id 금지, 동의어 흡수)
  - 정본 브랜드는 같지만 연식이 다름 → new_sku (진짜 다른 익스프레션)
  - 위스키로 보이지 않음/가비지 → noise (confidence=low)

자동 제안은 보조일 뿐이며 최종 분류는 사람이 검수한다(CEO 승인 1패스).

용법:
  python3 scripts/extract_whisky_candidates.py 2026-06-07
  python3 scripts/extract_whisky_candidates.py            # 날짜 인자 없으면 _undated
"""
import csv, os, re, sys, difflib
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from normalize_whisky_name import Normalizer, load_rules

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# (파일, 이름컬럼, 가격컬럼) — 가격을 가진 한글 수집 소스
PRICE_SOURCES = [
    ("data/whisky-prices/2026-03.csv", "술이름", "가격_KRW"),
    ("data/whisky-prices/2026-04.csv", "술이름", "가격_KRW"),
    ("data/whisky-prices/2026-05.csv", "술이름", "가격_KRW"),
    ("data/whisky-prices/2026-06.csv", "술이름", "가격_KRW"),
    ("data/whisky-prices/2026-05_dailyshot.csv", "위스키명", "가격_KRW"),
    ("data/whisky-prices/2026-06_dailyshot.csv", "위스키명", "가격_KRW"),
    ("data/whisky-prices/2026-05_whiskeypick_traders_guwol.csv", "술이름", "가격_KRW"),
]

# 브랜드 추정용 키워드 → (brand, category, origin). 구체 키워드가 위로.
BRAND_HINTS = [
    ("발렌타인", "Ballantine's", "블렌디드", "스코틀랜드"),
    ("발베니", "Balvenie", "싱글몰트", "스코틀랜드-스페이사이드"),
    ("라프로익", "Laphroaig", "싱글몰트", "스코틀랜드-아일라"),
    ("부쉬밀", "Bushmills", "싱글몰트", "아일랜드"),
    ("부시밀", "Bushmills", "싱글몰트", "아일랜드"),
    ("글렌파클라스", "Glenfarclas", "싱글몰트", "스코틀랜드-스페이사이드"),
    ("파클라스", "Glenfarclas", "싱글몰트", "스코틀랜드-스페이사이드"),
    ("글렌알라키", "GlenAllachie", "싱글몰트", "스코틀랜드-스페이사이드"),
    ("글렌라키", "GlenAllachie", "싱글몰트", "스코틀랜드-스페이사이드"),
    ("글렌피딕", "Glenfiddich", "싱글몰트", "스코틀랜드-스페이사이드"),
    ("글렌고인", "Glengoyne", "싱글몰트", "스코틀랜드-하일랜드"),
    ("글렌모렌", "Glenmorangie", "싱글몰트", "스코틀랜드-하일랜드"),
    ("글렌리벳", "The Glenlivet", "싱글몰트", "스코틀랜드-스페이사이드"),
    ("탈리스커", "Talisker", "싱글몰트", "스코틀랜드-스카이"),
    ("주라", "Jura", "싱글몰트", "스코틀랜드-아일랜드(섬)"),
    ("맥캘란", "The Macallan", "싱글몰트", "스코틀랜드-스페이사이드"),
    ("맥켈란", "The Macallan", "싱글몰트", "스코틀랜드-스페이사이드"),
    ("아벨라워", "Aberlour", "싱글몰트", "스코틀랜드-스페이사이드"),
    ("스모크헤드", "Smokehead", "싱글몰트", "스코틀랜드-아일라"),
    ("린도어스", "Lindores Abbey", "싱글몰트", "스코틀랜드-로우랜드"),
    ("네이키드", "The Naked Malt", "블렌디드몰트", "스코틀랜드"),
    ("러셀", "Russell's Reserve", "버번", "미국"),
    ("에반", "Evan Williams", "버번", "미국"),
    ("잭다니", "Jack Daniel's", "테네시위스키", "미국"),
    ("잭 다니", "Jack Daniel's", "테네시위스키", "미국"),
    ("와일드 터키", "Wild Turkey", "버번", "미국"),
    ("코발", "Koval", "싱글몰트", "미국"),
    ("짐빔", "Jim Beam", "버번", "미국"),
    ("진빔", "Jim Beam", "버번", "미국"),
    ("조니워커", "Johnnie Walker", "블렌디드", "스코틀랜드"),
    ("조니어", "Johnnie Walker", "블렌디드", "스코틀랜드"),
    ("시바스", "Chivas Regal", "블렌디드", "스코틀랜드"),
    ("듀어스", "Dewar's", "블렌디드", "스코틀랜드"),
    ("그란츠", "Grant's", "블렌디드", "스코틀랜드"),
    ("제임슨", "Jameson", "블렌디드", "아일랜드"),
    ("윈저", "Windsor", "블렌디드", "스코틀랜드"),
    ("벨즈", "Bell's", "블렌디드", "스코틀랜드"),
    ("커클랜드", "Kirkland", "블렌디드", "(상표:코스트코)"),
    ("스카치 블루", "Scotch Blue", "블렌디드", "스코틀랜드"),
    ("커티", "Cutty Sark", "블렌디드", "스코틀랜드"),
]


def hint(norm):
    for kw, brand, cat, origin in BRAND_HINTS:
        if kw in norm:
            return brand, cat, origin
    return "", "", ""


def age_of(s):
    m = re.search(r"(\d{1,2})\s*년", s)
    return int(m.group(1)) if m else None


def looks_like_whisky(norm):
    """위스키/스카치/버번/싱글몰트 또는 알려진 브랜드 단서가 있으면 True."""
    if any(k in norm for k in ("위스키", "스카치", "버번", "싱글몰트", "싱글 몰트",
                               "블렌디드", "몰트", "버뉴스키", "스컷")):
        return True
    return bool(hint(norm)[0])


def main():
    date = sys.argv[1] if len(sys.argv) >= 2 else "_undated"
    rules = load_rules()
    norm = Normalizer(rules)

    # 정본 로드: (id, name_ko, norm, age)
    canon = []
    with open(os.path.join(ROOT, "assets", "whisky-list.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            nm = (r.get("name_ko") or "").strip()
            if not nm:
                continue
            cn = norm.normalize_text(nm)
            canon.append((r["id"], nm, cn, age_of(cn)))

    # 미매칭 수집·그룹화
    groups = {}
    for path, ncol, pcol in PRICE_SOURCES:
        fp = os.path.join(ROOT, path)
        if not os.path.exists(fp):
            continue
        with open(fp, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                raw = (row.get(ncol) or "").strip()
                if not raw:
                    continue
                r = norm.canonicalize(raw)
                if r["status"] != "unmatched":
                    continue
                key = r["norm"]
                g = groups.setdefault(key, {"raws": {}, "count": 0,
                                            "prices": [], "src": set()})
                g["raws"][raw] = g["raws"].get(raw, 0) + 1
                g["count"] += 1
                g["src"].add(os.path.basename(path))
                try:
                    p = int(float(str(row.get(pcol, "")).replace(",", "").strip()))
                    if p > 0:
                        g["prices"].append(p)
                except (TypeError, ValueError):
                    pass

    out_rows = []
    for key, g in groups.items():
        # 대표 원시표기 = 최빈, 동률이면 최장
        rep = sorted(g["raws"].items(), key=lambda kv: (-kv[1], -len(kv[0])))[0][0]
        ps = g["prices"]
        pmin = min(ps) if ps else ""
        pmax = max(ps) if ps else ""

        # 최근접 정본
        best = max(canon, key=lambda c: difflib.SequenceMatcher(None, key, c[2]).ratio())
        ratio = round(difflib.SequenceMatcher(None, key, best[2]).ratio(), 3)
        cand_age = age_of(key)
        same_age = (cand_age == best[3])

        brand, cat, origin = hint(key)

        # 자동 분류 제안
        if not looks_like_whisky(key):
            cls, conf = "noise", "low"
        elif ratio >= 0.85 and same_age:
            cls, conf = "synonym_of_existing", "high"
        elif ratio >= 0.85 and not same_age:
            # 같은 브랜드·다른 연식 → 진짜 다른 익스프레션
            cls, conf = "new_sku", ("high" if g["count"] >= 2 else "med")
        elif ratio >= 0.72:
            cls, conf = "review", "low"
        else:
            cls, conf = "new_sku", ("high" if g["count"] >= 2 else "med")

        out_rows.append({
            "suggested_class": cls,
            "confidence": conf,
            "norm_key": key,
            "rep_name": rep,
            "freq": g["count"],
            "n_variants": len(g["raws"]),
            "price_min": pmin,
            "price_max": pmax,
            "est_brand": brand,
            "est_category": cat,
            "est_origin": origin,
            "est_age": cand_age if cand_age is not None else "",
            "nearest_canon_id": best[0],
            "nearest_canon_name": best[1],
            "nearest_ratio": ratio,
            "nearest_canon_age": best[3] if best[3] is not None else "",
            "sources": ";".join(sorted(g["src"])),
            "raw_variants": " | ".join(sorted(g["raws"])),
        })

    # 정렬: class(new_sku 먼저) → freq 내림차순
    order = {"new_sku": 0, "review": 1, "synonym_of_existing": 2, "noise": 3}
    out_rows.sort(key=lambda r: (order.get(r["suggested_class"], 9), -r["freq"]))

    out_dir = os.path.join(ROOT, "assets", "_runs")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"whisky-list-candidates_{date}.csv")
    cols = ["suggested_class", "confidence", "norm_key", "rep_name", "freq",
            "n_variants", "price_min", "price_max", "est_brand", "est_category",
            "est_origin", "est_age", "nearest_canon_id", "nearest_canon_name",
            "nearest_ratio", "nearest_canon_age", "sources", "raw_variants"]
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(out_rows)

    from collections import Counter
    by = Counter(r["suggested_class"] for r in out_rows)
    print(f"=== 후보 추출 요약 (distinct 미매칭 그룹 = {len(out_rows)}) ===")
    for k in ("new_sku", "review", "synonym_of_existing", "noise"):
        print(f"  {k:22s}: {by.get(k,0)}")
    print(f"\n출력: assets/_runs/whisky-list-candidates_{date}.csv")
    print("\n=== new_sku 제안 (freq desc) ===")
    for r in out_rows:
        if r["suggested_class"] != "new_sku":
            continue
        pr = f'{r["price_min"]:,}~{r["price_max"]:,}' if r["price_min"] else "?"
        print(f'  [{r["confidence"]:4s}] f={r["freq"]:2d} {r["rep_name"][:34]:34s} '
              f'{pr:20s} ~{r["nearest_canon_name"]}({r["nearest_ratio"]})')


if __name__ == "__main__":
    main()
