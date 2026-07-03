#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_webcheck_candidates.py — CMPA-170 board 제안 반영(웹 검증 단계).

board 코멘트(2026-06-07): "새제품인지 아닌지 헷갈리면, 데일리샷/구글 검색 반응을 보라. 앞으로?"

→ 후보 CSV(특히 freq=1 때문에 new_B 로 분류된 '저빈도=불확실' 후보)에 대해
  데일리샷/구글 검색으로 실재 여부를 확인하고, 그 결과를 web_check 컬럼으로 기록한다.
  검증(real)된 new_B 는 new_A(승인 후보)로 승격한다.

이 스크립트는 DataEngineer 가 수동 수행한 검색 결과(아래 WEBCHECK 매핑)를 입력으로,
curated CSV → -webcheck CSV 로 augment 한다. 검색 자체는 사람이 수행(증거 URL 첨부).
"""
import csv, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC = os.path.join(ROOT, "assets/_runs/whisky-list-candidates-curated_2026-06-07.csv")
DST = os.path.join(ROOT, "assets/_runs/whisky-list-candidates-webcheck_2026-06-07.csv")

# name_ko -> (status, evidence). status: real / real_dailyshot / not_found / ambiguous
# 2026-06-07 DataEngineer 가 데일리샷/구글에 직접 검색해 확인한 결과(증거 URL/출처).
WEBCHECK = {
    "칼라일": ("real", "Total Wine/wine-searcher 다수 (Carlyle Blended Scotch). 단 저가블렌드+OCR 변형 노이즈와 중복 주의"),
    "글렌그란트 아보랄리스": ("real", "theglengrant.com/products/arboralis; whiskybase 158117"),
    "듀어스 캐리비안 스무스 8년": ("real", "dewars.com Caribbean Smooth; thewhiskyexchange p/60030 (8yo)"),
    "네이키드 몰트": ("real_dailyshot", "dailyshot.co/m/item/4294 (네이키드 그라우스 리뉴얼)"),
    "라벨 5": ("real_dailyshot", "dailyshot.co/m/item/6429"),
    "발렌타인 싱글몰트 글렌버기 18년": ("real", "ballantines.com glenburgie-18; thewhiskyexchange p/70355"),
    "그란츠 트리플 우드": ("real", "grantswhisky.com/en/triple-wood (Family Reserve 2018 개명)"),
    "스모크헤드 오리지널": ("real", "smokehead.com/smokehead-original; whiskybase 112014"),
    "스카치블루 17년": ("real_dailyshot", "dailyshot.co/m/item/4683 (롯데칠성, 450ml)"),
    "윈저 12년": ("real_dailyshot", "dailyshot.co/m/item/6535 (디아지오, 국내판매1위)"),
    "발렌타인 마스터즈": ("real", "whiskybase 65398; ballantines blenders"),
    "스카치블루 클래식": ("real_dailyshot", "dailyshot.co/m/item/25637 (롯데칠성 엔트리)"),
}

# 미검색이나 명백한 메이저 브랜드 표준 익스프레션 — 루틴에서 자동 검색 권장(과대주장 금지)
BRAND_STANDARD_NOTE = "major-brand standard expr; routine 자동검색 권장(개별 미검색)"


def main():
    with open(SRC, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    cols = list(rows[0].keys())
    # web_check 컬럼을 note 뒤에 삽입
    if "web_check" not in cols:
        idx = cols.index("note") + 1 if "note" in cols else len(cols)
        cols.insert(idx, "web_check")

    promoted = 0
    verified = 0
    for r in rows:
        r.setdefault("web_check", "")
        name = r.get("name_ko", "").strip()
        if r["final_class"] == "new_B":
            if name in WEBCHECK:
                status, ev = WEBCHECK[name]
                r["web_check"] = f"{status}: {ev}"
                verified += 1
                if status.startswith("real"):
                    r["final_class"] = "new_A"   # 검증된 저빈도 후보 → 승인 후보 승격
                    promoted += 1
            else:
                r["web_check"] = f"unsearched: {BRAND_STANDARD_NOTE}"
        elif r["final_class"] == "new_A":
            r["web_check"] = "prior new_A (freq/brand 기반); routine 검색대상"
        elif r["final_class"] == "noise":
            r["web_check"] = "noise (OCR/비위스키) — 검색대상 아님"
        else:  # synonym
            r["web_check"] = "synonym(기존 정본 흡수) — 신규 검증 불필요"

    with open(DST, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    # 요약
    from collections import Counter
    dist = Counter(r["final_class"] for r in rows)
    print(f"입력 {len(rows)}행 → {DST}")
    print(f"web_check 검증(real): {verified}건, new_B→new_A 승격: {promoted}건")
    print("final_class after webcheck:", dict(dist))
    print(f"승인 후보(new_A) 총계: {dist['new_A']}  / new_B 잔여: {dist['new_B']}")


if __name__ == "__main__":
    main()
