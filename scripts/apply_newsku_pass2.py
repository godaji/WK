#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_newsku_pass2.py — CMPA-170 pass-2: board 웹검증으로 실재 확인된 new_B 12종을
정본에 반영. CEO 승인(confirmation cmpa170-newsku-pass2, accepted 2026-06-07T07:15).

  w119~w130, confidence=high(데일리샷/구글 직접확인). pass-1(apply_newsku_to_canon.py) 다음.
가드: products 규칙 맨 끝 append → 기존 매칭 무회귀. token_synonyms 는 미매칭 OCR 전용.
재실행 가드: w119 이미 있으면 중단.
"""
import csv, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST = os.path.join(ROOT, "assets/whisky-list.csv")
YAML = os.path.join(ROOT, "assets/whisky-synonyms.yaml")
CUR = os.path.join(ROOT, "assets/_runs/whisky-list-candidates-curated_2026-06-07.csv")

# 순서 = w119..w130 (confirmation 표와 동일)
ORDER = [
    ("w119", "그란츠 트리플 우드", "[그란츠, 트리플]"),
    ("w120", "글렌그란트 아보랄리스", "[그란트, 아보랄리스]"),
    ("w121", "네이키드 몰트", "[네이키드]"),
    ("w122", "듀어스 캐리비안 스무스 8년", "[듀어스, 캐리비안]"),
    ("w123", "라벨 5", '[라벨, "5"]'),
    ("w124", "발렌타인 싱글몰트 글렌버기 18년", '[발렌타인, "18년"]'),
    ("w125", "발렌타인 마스터즈", "[발렌타인, 마스터]"),
    ("w126", "스모크헤드 오리지널", "[스모크헤드]"),
    ("w127", "스카치블루 17년", '[스카치블루, "17년"]'),
    ("w128", "스카치블루 클래식", "[스카치블루, 클래식]"),
    ("w129", "윈저 12년", '[윈저, "12년"]'),
    ("w130", "칼라일", "[칼라일]"),
]
TOKEN_SYN_ADD = [
    ("스카치블루", ["스카치 블루", "스카치 블로", "스카치블로"]),
]


def vol_from(rep):
    rep = rep.lower()
    for k, v in (("1.75", "1750"), ("1750", "1750"), ("450", "450"),
                 ("500", "500"), ("750", "750"), ("1l", "1000")):
        if k in rep:
            return v
    return "700"


def channels_from(s):
    ch = []
    if "dailyshot" in s:
        ch.append("데일리샷")
    if "traders" in s or "whiskeypick" in s:
        ch.append("트레이더스")
    return ";".join(ch) if ch else "데일리샷"


def main():
    rows = {r["name_ko"]: r for r in csv.DictReader(open(CUR, encoding="utf-8-sig"))}
    if "w119" in open(LIST, encoding="utf-8-sig").read():
        print("이미 w119 존재 — 중단(재실행 가드)"); sys.exit(1)

    # 1) whisky-list.csv append (confidence=high: web검증)
    out = []
    for wid, name, _ in ORDER:
        r = rows[name]
        out.append([
            wid, name, r.get("name_en", ""), r["brand"], r["category"], r["origin"],
            r["age"] if r["age"] not in ("NAS", "") else "", "",
            vol_from(r["rep_name"]), r["price_min"], r["price_max"],
            channels_from(r["sources"]), "high",
            "CMPA-170 pass-2 web검증(CEO승인 2026-06-07)",
        ])
    with open(LIST, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        for row in out:
            w.writerow(row)

    # 2) products: append (pass-1 블록 다음, 파일 끝의 products 마지막=w130 직전)
    y = open(YAML, encoding="utf-8").read()
    anchor = "  - {id: w118, name_ko: 탈리스커 디스틸러스 에디션, match: [탈리스커, 디스틸러스]}"
    assert anchor in y, "pass-1 anchor(w118) 못 찾음 — pass-1 먼저 적용 필요"
    block = ["", "  # ── CMPA-170 pass-2 web검증 확장 (w119~w130, CEO 승인 2026-06-07) ──"]
    for wid, name, m in ORDER:
        block.append(f"  - {{id: {wid}, name_ko: {name}, match: {m}}}")
    y = y.replace(anchor, anchor + "\n" + "\n".join(block))

    # 3) token_synonyms (스카치블루 spaced/OCR 흡수)
    bm = '부쉬밀: ["부시밀", "부심일"]'
    assert bm in y, "부쉬밀 라인(pass-1) 못 찾음"
    ins = ["", "  # CMPA-170 pass-2 OCR/공백 흡수"]
    for canon, vs in TOKEN_SYN_ADD:
        ins.append(f'  {canon}: {vs}'.replace("'", '"'))
    y = y.replace(bm, bm + "\n" + "\n".join(ins))

    open(YAML, "w", encoding="utf-8").write(y)
    print(f"pass-2 적용: whisky-list.csv +{len(out)}행 (w119~w130), products +12, token_synonyms +1")


if __name__ == "__main__":
    main()
