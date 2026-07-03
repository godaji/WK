#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""신라면세 위스키 CSV에서 피트(peated) 위스키만 골라 새 CSV로 리스트업.

피트 판정 근거(2가지):
  1) 상품명에 명시적 피트 키워드 (피트/피티드/peated/smoky/big peat 등)
  2) 항상 피트로 만드는 증류소(아일라 등)명이 상품명·브랜드에 등장
     - 인디 보틀러(고든앤맥패일/시그나토리/더글라스랭 등)는 증류소명으로 잡힘

각 행에 '피트근거'(왜 골랐는지)와 '피트분류'(A=강한피트 / B=스모키섬몰트) 컬럼 추가.
UNPEATED 명시 상품은 제외.
"""
import csv
import sys
from pathlib import Path

# --- 판정 사전 -------------------------------------------------------------
# 상품명 내 명시적 피트 키워드 (소문자 비교)
PEAT_NAME_KW = [
    "피트", "피티", "피티드", "peated", "peat", "스모키", "스모크", "스모킨",
    "smoky", "smoke", "big peat", "peat monster",
]
# 아일라/피트 산지 신호 (인디 보틀러 상품명에 산지가 박혀 있는 경우)
ISLAY_KW = ["아일라", "islay"]

# 항상 피트로 증류하는 증류소 (브랜드 또는 상품명 어디든 등장하면 피트) -> 분류 A
ALWAYS_PEATED = [
    "라프로익", "laphroaig",
    "라가불린", "lagavulin",
    "아드벡", "아드베그", "ardbeg",
    "보모어", "bowmore",
    "쿨일라", "카올일라", "코일라", "caol ila",
    "킬호만", "kilchoman",
    "옥토모어", "octomore",
    "포트샬롯", "포트 샬롯", "포트샬럿", "port charlotte",
]
# 일반적으로 스모키/피트로 분류되는 섬 몰트 -> 분류 B
SMOKY_ISLAND = ["탈리스커", "talisker"]


def classify(name: str, brand: str):
    """피트 여부와 근거를 판정. (is_peated, tier, reason) 반환."""
    name_l = name.lower()
    hay = f"{name} {brand}".lower()

    # 오탐 방지용 마스킹:
    #  - 'unpeated/언피티드' 안의 'peat/peated' 매칭 차단
    #  - '스트라스아일라'(Strathisla, 스페이사이드 비피트) 안의 '아일라' 매칭 차단
    masked = (
        hay.replace("unpeated", "________")
        .replace("언피티드", "_____")
        .replace("논피트", "____")
        .replace("스트라스아일라", "____________")
        .replace("strathisla", "__________")
    )

    reasons = []
    tier = None

    # 1) 항상 피트 증류소 (브랜드·상품명 어디든)
    for d in ALWAYS_PEATED:
        if d in masked:
            reasons.append(f"증류소:{d}")
            tier = "A"
            break

    # 2) 명시적 피트 키워드
    for kw in PEAT_NAME_KW:
        if kw in masked:
            reasons.append(f"키워드:{kw}")
            if tier is None:
                tier = "A"
            break

    # 3) 아일라 산지 신호
    for kw in ISLAY_KW:
        if kw in masked:
            reasons.append(f"산지:{kw}")
            if tier is None:
                tier = "A"
            break

    # 4) 스모키 섬 몰트 — 브랜드 오기재 방지를 위해 상품명에서만 매칭
    if tier is None:
        for d in SMOKY_ISLAND:
            if d in name_l:
                reasons.append(f"스모키섬몰트:{d}")
                tier = "B"
                break

    return bool(reasons), tier, "; ".join(reasons)


def main():
    base = Path(__file__).resolve().parents[2] / "data" / "shilla-dutyfree"
    src = base / "신라면세_위스키_2026-06-06.csv"
    if len(sys.argv) > 1:
        src = Path(sys.argv[1])
    out = src.with_name(src.stem.replace("위스키", "피트위스키") + ".csv")
    if "피트위스키" not in out.name:
        out = src.with_name("신라면세_피트위스키_" + src.stem.split("_")[-1] + ".csv")

    with open(src, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    out_rows = []
    for x in rows:
        ok, tier, reason = classify(x.get("위스키명", ""), x.get("브랜드", ""))
        if ok:
            x2 = dict(x)
            x2["피트분류"] = tier or ""
            x2["피트근거"] = reason
            out_rows.append(x2)

    # 분류 A 먼저, 그 안에서 브랜드/이름 정렬
    out_rows.sort(key=lambda r: (r["피트분류"], r["브랜드"], r["위스키명"]))

    fieldnames = list(rows[0].keys()) + ["피트분류", "피트근거"]
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(out_rows)

    a = sum(1 for r in out_rows if r["피트분류"] == "A")
    b = sum(1 for r in out_rows if r["피트분류"] == "B")
    print(f"입력 {len(rows)}행 -> 피트 {len(out_rows)}행 (A={a}, B={b})")
    print(f"출력: {out}")
    return out, out_rows


if __name__ == "__main__":
    main()
