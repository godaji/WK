#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
CMPA-66 — 콜키지프리 식당 인당 예상 식사 비용 추정기.

특정 식당에서 한 끼 먹으면 1인당 대략 얼마가 나오는지 추정한다.

데이터 출처(라이브):
  DiningCode 프로필 페이지의 schema.org JSON-LD 메뉴(MenuItem name+price).
  POST 가 아니라 GET https://www.diningcode.com/profile.php?rid=<RID>
  → 정가 메뉴/가격을 그대로 긁어 쓰므로 가격은 항상 최신이다.

추정 모델(투명·결정론):
  "전형적인 2인 방문이 시키는 주문 바구니(basket)"를 식당 업종에 맞춰
  세 단계(아낌/표준/넉넉)로 구성하고, 바구니 합계 ÷ 인원수 = 1인당 비용.
  - 바구니 항목은 메뉴명 부분일치로 라이브 가격을 끌어오므로
    가격이 바뀌어도 자동 반영된다(가정=구성, 숫자=라이브).
  - 콜키지프리(BYOB) 식당이므로 '술값'은 식당 매출에 거의 안 잡힌다.
    → 여기서 내는 1인 비용은 '음식값' 기준. 위스키는 본인 지참분.
    (마담풍천처럼 '1인 1주류 필수' 매장은 음료 최소금액을 별도 가산.)

근거 가정은 모두 BASKETS 에 명시되어 있어 누구나 검증·수정 가능하다.

사용:
  python3 pipelines/corkage_free/estimate_per_person.py
  → data/corkage-free/합정역_인당비용.{csv,md} 생성 + 표준출력 요약
"""
from __future__ import annotations

import csv
import json
import os
import re
import sys
import time

import requests

PROFILE = "https://www.diningcode.com/profile.php?rid="
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

OUT_DIR = os.path.join("data", "corkage-free")

# ─────────────────────────────────────────────────────────────────────────────
# 분석 대상 + 인당비용 바구니 모델.
#   rid      : DiningCode RID (프로필 메뉴 출처)
#   party    : 바구니 기준 인원수
#   baskets  : 아낌(low)/표준(typical)/넉넉(high) — 메뉴명 부분일치 토큰 리스트.
#              각 토큰은 라이브 메뉴에서 가격을 끌어옴(매칭 실패 시 경고).
#   drink_min: 1인당 강제 음료/주류 최소금액(원). 콜키지프리라도 '1인 1주류'
#              규정이 있으면 가산. 없으면 0.
#   note     : 모델 가정 설명(리포트에 노출).
# ─────────────────────────────────────────────────────────────────────────────
BASKETS = [
    {
        "name": "빠넬로",
        "rid": "JSpWFEZBrAsB",
        "category": "화덕피자 / 이탈리안",
        "lat": 37.5494133, "lng": 126.9190158,
        "party": 2,
        "drink_min": 0,
        "note": ("2인 = 피자 1 + 파스타 1 공유 기준. "
                 "나폴리 화덕피자·트러플 라인이라 단가 높은 편."),
        "baskets": {
            "아낌": ["마리나라", "까르보나라"],            # 가장 싼 피자+무난 파스타
            "표준": ["부라따피자", "까르보나라"],
            "넉넉": ["블랙트러플 피자", "파스타 랍스타"],   # 프리미엄 피자+해산물 파스타
        },
    },
    {
        "name": "짚불돈",
        "rid": "4tPbVrNHU2AN",
        "category": "삼겹살 / 고기집",
        "lat": 37.5484344, "lng": 126.9182358,
        "party": 2,
        "drink_min": 0,
        "note": ("2인 기준. 고깃집은 보통 1인 1.5인분 이상 먹으므로 표준은 "
                 "모둠한판(500g≈2.5인분)+계란찜+마무리국수, 넉넉은 고기 추가 1인분. "
                 "아낌은 초벌 2인분만. 점심특선은 별도(저가)."),
        "baskets": {
            "아낌": ["짚불초벌 삼겹살", "짚불 초벌 항정살", "24시간 묵은지 찌개", "마무리 미나리 볶음밥"],
            "표준": ["짚불돈 모둠한판", "퐁실퐁실 계란찜", "감태 뚜껑 들기름 국수"],
            "넉넉": ["짚불돈 모둠한판", "짚불 초벌 통 갈매기살", "퐁실퐁실 계란찜", "감태 뚜껑 들기름 국수"],
        },
    },
    {
        "name": "마담 풍천",
        "rid": "YowFb2ExbhbA",
        "category": "장어 / 오마카세",
        "lat": 37.5476035, "lng": 126.9174021,
        "party": 1,            # 오마카세 = 1인 정찰
        "drink_min": 8000,     # 리뷰상 '1인 1주류 필수' → 음료 최소 가산
        "note": ("장어 오마카세 1인 정찰 가격. 리뷰상 '1인 1주류 필수'라 "
                 "음료 최소 약 8,000원 가산. 콜키지프리라 위스키는 지참 가능."),
        "baskets": {
            "아낌": ["런치 오마카세"],     # 50,000
            "표준": ["디너 오마카세"],     # 70,000
            "넉넉": ["디너 오마카세", "장어덮밥 정식"],  # 든든히
        },
    },
]


def fetch_menu(rid: str) -> list[tuple[str, int]]:
    """프로필 페이지 JSON-LD 에서 (메뉴명, 가격원) 리스트 추출."""
    url = PROFILE + rid
    html = requests.get(url, headers={"User-Agent": UA}, timeout=25).text
    pairs = re.findall(
        r'"name":"([^"]{1,40})","offers":\{"@type":"Offer","price":"([0-9,]+)원"',
        html,
    )
    out = []
    for nm, price in pairs:
        try:
            out.append((nm.strip(), int(price.replace(",", ""))))
        except ValueError:
            continue
    return out


def match_price(menu: list[tuple[str, int]], token: str):
    """바구니 토큰(부분일치)에 해당하는 메뉴 가격 반환. 없으면 None."""
    for nm, price in menu:
        if token in nm:
            return nm, price
    return None, None


def estimate(rest: dict, menu: list[tuple[str, int]]) -> dict:
    """식당 한 곳에 대해 아낌/표준/넉넉 1인당 비용 계산."""
    party = rest["party"]
    drink = rest["drink_min"]
    rows = {}
    for tier, tokens in rest["baskets"].items():
        total, picks, missing = 0, [], []
        for tok in tokens:
            nm, price = match_price(menu, tok)
            if price is None:
                missing.append(tok)
                continue
            total += price
            picks.append((nm, price))
        per_person = round(total / party) + drink
        rows[tier] = {
            "per_person": per_person,
            "basket_total": total,
            "picks": picks,
            "missing": missing,
        }
    return rows


def won(n: int) -> str:
    return f"{n:,}원"


def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    results = []
    for rest in BASKETS:
        menu = fetch_menu(rest["rid"])
        print(f"\n=== {rest['name']} ({rest['category']}) — 메뉴 {len(menu)}개 ===")
        if not menu:
            print("  [warn] 메뉴 추출 실패 — 프로필 구조 변경 가능", file=sys.stderr)
        est = estimate(rest, menu)
        for tier in ("아낌", "표준", "넉넉"):
            r = est[tier]
            picks = ", ".join(f"{nm} {won(p)}" for nm, p in r["picks"])
            miss = (" [미매칭:" + ",".join(r["missing"]) + "]") if r["missing"] else ""
            print(f"  {tier}: 1인 {won(r['per_person'])}  ← {picks}{miss}")
        results.append((rest, est))
        time.sleep(0.5)

    # CSV
    csv_path = os.path.join(OUT_DIR, "합정역_인당비용.csv")
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        # rid/lat/lng = 콜키지프리 finder CSV·지도 마커와 조인하는 키(CMPA-66→지도 활용).
        w.writerow(["식당명", "rid", "카테고리", "기준인원",
                    "1인_아낌", "1인_표준", "1인_넉넉",
                    "lat", "lng", "표준바구니", "가정"])
        for rest, est in results:
            picks = "; ".join(f"{nm}({won(p)})" for nm, p in est["표준"]["picks"])
            w.writerow([
                rest["name"], rest["rid"], rest["category"], f"{rest['party']}인",
                est["아낌"]["per_person"], est["표준"]["per_person"],
                est["넉넉"]["per_person"], rest.get("lat", ""), rest.get("lng", ""),
                picks, rest["note"],
            ])
    print(f"\n[CSV] {csv_path}")

    # Markdown
    md_path = os.path.join(OUT_DIR, "합정역_인당비용.md")
    lines = [
        "# 합정역 콜키지프리 식당 — 인당 예상 식사 비용 (CMPA-66)",
        "",
        "> 추정 기준: DiningCode 라이브 정가 메뉴 + 업종별 '전형적 주문 바구니' "
        "÷ 인원수. **음식값 기준**(콜키지프리=위스키 지참, 술값은 별도/지참분).",
        "> 가정·바구니 구성은 아래 표와 스크립트(`estimate_per_person.py`)에 전부 공개.",
        "",
        "| 식당 | 업종 | 기준 | 아낌 | 표준 | 넉넉 |",
        "|---|---|---|--:|--:|--:|",
    ]
    for rest, est in results:
        lines.append(
            f"| **{rest['name']}** | {rest['category']} | {rest['party']}인 "
            f"| {won(est['아낌']['per_person'])} "
            f"| **{won(est['표준']['per_person'])}** "
            f"| {won(est['넉넉']['per_person'])} |"
        )
    lines += ["", "## 바구니 가정 (표준)", ""]
    for rest, est in results:
        picks = ", ".join(f"{nm} {won(p)}" for nm, p in est["표준"]["picks"])
        lines.append(f"- **{rest['name']}**: {rest['note']}")
        lines.append(f"  - 표준 바구니: {picks} → ÷{rest['party']}인"
                     + (f" + 음료최소 {won(rest['drink_min'])}" if rest['drink_min'] else ""))
    lines += [
        "",
        "## 주의",
        "- 정가 메뉴 기반 추정치이며 실제 객단가는 추가 주문·음료에 따라 달라진다.",
        "- 콜키지프리라 위스키는 본인 지참 → 동급 식당 대비 '술값' 절감이 핵심.",
        "- 마담풍천은 '1인 1주류 필수' 규정으로 음료 최소금액을 1인당 가산했다.",
        "",
        "_출처: DiningCode 프로필 메뉴(라이브). 생성: estimate_per_person.py_",
    ]
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"[MD]  {md_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
