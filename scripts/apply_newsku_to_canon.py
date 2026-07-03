#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_newsku_to_canon.py — CMPA-170: CEO 승인(2026-06-07, accepted confirmation)된
new_A 30종(w089~w118)을 정본에 반영한다.

  1) assets/whisky-list.csv 에 w089~w118 append (기존 id 불변)
  2) assets/whisky-synonyms.yaml products: 에 30 매칭규칙 append (맨 끝 = 기존규칙 우선)
  3) token_synonyms 에 안전한 OCR 변형 흡수(기존 정본과 충돌없는 garbled→정규형)

가드: products append 는 top-down first-match 라 기존 매칭을 회귀시킬 수 없음(맨 끝 추가).
검증: 적용 후 normalize_whisky_name --audit (matched↑) + pytest 로 확인.
재실행 안전: 이미 w089 가 있으면 중단.
"""
import csv, os, sys, io

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST = os.path.join(ROOT, "assets/whisky-list.csv")
YAML = os.path.join(ROOT, "assets/whisky-synonyms.yaml")
CUR = os.path.join(ROOT, "assets/_runs/whisky-list-candidates-curated_2026-06-07.csv")

# proposed_id -> products: 매칭 토큰(소문자 부분일치, AND). 기존 규칙 컨벤션 준수.
MATCH = {
    "w089": "[탈리스커, 와일드]",
    "w090": '[발렌타인, "17년"]',
    "w091": "[잭다니엘, 허니]",
    "w092": '[발렌타인, "16년"]',
    "w093": '[파클라스, "15년"]',
    "w094": '[글렌피딕, "12년", 셰리]',
    "w095": '[러셀, "10년"]',
    "w096": "[라키, 루비]",
    "w097": '[주라, "18년"]',
    "w098": '[커클랜드, "15년"]',
    "w099": "[커클랜드, 스카치]",
    "w100": "[커클랜드, 캐나디안]",
    "w101": '[파클라스, "12년"]',
    "w102": "[라프로익, 셀렉트]",
    "w103": "[린도어스]",
    "w104": "[맥캘란, 셰리]",
    "w105": '[발베니, "16년"]',
    "w106": "[벨즈]",
    "w107": '[부쉬밀, "10년"]',
    "w108": '[부쉬밀, "12년"]',
    "w109": "[블랙보트]",
    "w110": "[에반, 싱글, 배럴]",
    "w111": "[에반, bib]",
    "w112": "[커클랜드, 본드]",
    "w113": "[코발, 밀레]",
    "w114": "[코발, 라이]",
    "w115": '[글렌피딕, "18년"]',
    "w116": '[주라, "10년"]',
    "w117": '[주라, "12년"]',
    "w118": "[탈리스커, 디스틸러스]",
}

# 안전한 OCR 변형 흡수(garbled→정규형). 정규형은 기존 products match 토큰과 일치.
# 각 변형은 현재 '미매칭 OCR'에만 존재 → 기존 매칭 회귀 없음.
TOKEN_SYN_ADD = [
    ("글렌피딕", ["글랜피딕", "글램피닉"]),
    ("그란트",   ["글랜란트"]),
    ("글렌리벳", ["글랜립의"]),
    ("맥캘란",   ["맥켈란"]),
    ("조니워커", ["조니어커", "조니어"]),
    ("클라이넬리시", ["클라인엘리시"]),
    ("글렌드로낙", ["글랜드로"]),
]
# 기존 키 부쉬밀:["부시밀"] 에 부심일 추가
BUSHMILL_EXTEND = ('부쉬밀: ["부시밀"]', '부쉬밀: ["부시밀", "부심일"]')


def vol_from(rep):
    rep = rep.lower()
    if "1.75" in rep or "1750" in rep:
        return "1750"
    if "750" in rep:
        return "750"
    if "1l" in rep or "1000" in rep:
        return "1000"
    return "700"


def channels_from(sources):
    s = sources
    ch = []
    if "dailyshot" in s:
        ch.append("데일리샷")
    if "traders" in s or "whiskeypick" in s:
        ch.append("트레이더스")
    if not ch:
        ch.append("데일리샷")
    return ";".join(ch)


def main():
    rows = list(csv.DictReader(open(CUR, encoding="utf-8-sig")))
    newA = [r for r in rows if r["final_class"] == "new_A"]
    assert len(newA) == 30, f"expected 30 new_A, got {len(newA)}"
    assert set(MATCH) == {r["proposed_id"] for r in newA}, "MATCH 키와 new_A id 불일치"

    # 0) 재실행 가드
    list_txt = open(LIST, encoding="utf-8-sig").read()
    if "w089" in list_txt:
        print("이미 w089 존재 — 중단(재실행 가드)"); sys.exit(1)

    # 1) whisky-list.csv append
    by_id = {r["proposed_id"]: r for r in newA}
    appended = []
    for wid in MATCH:  # w089..w118 순서
        r = by_id[wid]
        appended.append([
            wid, r["name_ko"], r.get("name_en", ""), r["brand"], r["category"],
            r["origin"], r["age"] if r["age"] not in ("NAS", "") else "", "",
            vol_from(r["rep_name"]), r["price_min"], r["price_max"],
            channels_from(r["sources"]), "med",
            "CMPA-170 bottom-up(CEO승인 2026-06-07)",
        ])
    with open(LIST, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        for row in appended:
            w.writerow(row)

    # 2) products: append (w084 라인 뒤)
    y = open(YAML, encoding="utf-8").read()
    anchor = "  - {id: w084, name_ko: 카발란 디스틸러리 셀렉트, match: [카발란], not: [솔리스트]}"
    assert anchor in y, "products anchor(w084) 못 찾음"
    block = ["", "  # ── CMPA-170 bottom-up 확장 (w089~w118, CEO 승인 2026-06-07) ──"]
    for wid in MATCH:
        block.append(f"  - {{id: {wid}, name_ko: {by_id[wid]['name_ko']}, match: {MATCH[wid]}}}")
    y = y.replace(anchor, anchor + "\n" + "\n".join(block))

    # 3) token_synonyms 흡수
    assert BUSHMILL_EXTEND[0] in y, "부쉬밀 토큰 라인 못 찾음"
    y = y.replace(BUSHMILL_EXTEND[0], BUSHMILL_EXTEND[1])
    ins = ["", "  # CMPA-170 OCR 변형 흡수(garbled→정규형, 미매칭 전용)"]
    for canon, vs in TOKEN_SYN_ADD:
        ins.append(f'  {canon}: {vs}'.replace("'", '"'))
    y = y.replace(BUSHMILL_EXTEND[1], BUSHMILL_EXTEND[1] + "\n" + "\n".join(ins))

    open(YAML, "w", encoding="utf-8").write(y)
    print(f"적용 완료: whisky-list.csv +{len(appended)}행 (w089~w118)")
    print(f"products 규칙 +30, token_synonyms +{len(TOKEN_SYN_ADD)}키(+부심일)")


if __name__ == "__main__":
    main()
