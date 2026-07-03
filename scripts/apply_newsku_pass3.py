#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
apply_newsku_pass3.py — CMPA-175 pass-3: web검증으로 실재 확인된 잔여 new_B 15종
(전부 메이저 표준 익스프레션, CMPA-170 freq=1 로 보류됐던 것)을 정본에 반영.

  w131~w145. pass-1(apply_newsku_to_canon)·pass-2(apply_newsku_pass2) 다음.
  데이터 소스: assets/_runs/whisky-list-candidates-webcheck-pass3_2026-06-07.csv
  (proposed_id·match·confidence·web_check 증거 포함)

가드:
  - products 규칙 맨 끝 append → 기존 매칭 무회귀(top-down first-match).
  - 신규 token_synonyms 불필요: 글랜고인→글렌고인, 진빔→짐빔, 베럴→배럴,
    잭 다니엘스→잭다니엘 모두 기존 token_synonyms 로 이미 정규화됨.
  - 재실행 가드: w131 이미 있으면 중단.
  - CEO 승인 후에만 실행(정본 반영은 CEO 독립검증 후).
"""
import csv, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LIST = os.path.join(ROOT, "assets/whisky-list.csv")
YAML = os.path.join(ROOT, "assets/whisky-synonyms.yaml")
WC = os.path.join(ROOT, "assets/_runs/whisky-list-candidates-webcheck-pass3_2026-06-07.csv")

NOTE = "CMPA-175 pass-3 web검증(CEO승인 2026-06-07)"


def vol_from(rep):
    rep = (rep or "").lower()
    for k, v in (("1.75", "1750"), ("1750", "1750"), ("450", "450"),
                 ("500", "500"), ("750", "750"), ("1l", "1000")):
        if k in rep:
            return v
    return "700"


def main(list_path=LIST, yaml_path=YAML):
    rows = list(csv.DictReader(open(WC, encoding="utf-8-sig")))
    assert len(rows) == 15, f"expected 15 new_B, got {len(rows)}"

    if "w131" in open(list_path, encoding="utf-8-sig").read():
        print("이미 w131 존재 — 중단(재실행 가드)"); sys.exit(1)

    # 1) whisky-list.csv append
    out = []
    for r in rows:
        out.append([
            r["proposed_id"], r["name_ko"], r.get("name_en", ""), r["brand"],
            r["category"], r["origin"],
            r["age"] if r["age"] not in ("NAS", "") else "", "",
            vol_from(r["raw_variants"]), r["price_min"], r["price_max"],
            "데일리샷", r["confidence"], NOTE,
        ])
    with open(list_path, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        for row in out:
            w.writerow(row)

    # 2) products: append (pass-2 마지막 앵커 w130 직후)
    y = open(yaml_path, encoding="utf-8").read()
    anchor = "  - {id: w130, name_ko: 칼라일, match: [칼라일]}"
    assert anchor in y, "pass-2 anchor(w130) 못 찾음 — pass-2 먼저 적용 필요"
    block = ["", "  # ── CMPA-175 pass-3 web검증 확장 (w131~w145, 잔여 new_B 메이저 표준, CEO 승인 2026-06-07) ──"]
    for r in rows:
        block.append(f"  - {{id: {r['proposed_id']}, name_ko: {r['name_ko']}, match: {r['match']}}}")
    y = y.replace(anchor, anchor + "\n" + "\n".join(block))
    open(yaml_path, "w", encoding="utf-8").write(y)

    print(f"pass-3 적용: whisky-list.csv +{len(out)}행 (w131~w145), products +15, token_synonyms +0")


if __name__ == "__main__":
    main()
