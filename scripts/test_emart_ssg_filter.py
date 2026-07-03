#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""test_emart_ssg_filter.py — 이마트(SSG) 술병 필터 회귀 가드 (CMPA-420/422)

`collect_emart_ssg.is_bottle` 가 **진짜 위스키 술병만 통과**시키고, 검색에 대량으로
섞여 드는 마켓플레이스 노이즈(잔/디캔터/잡화/의류/잡지/액세서리)·비위스키 카테고리를
기각하는지 잠근다. 실측(2026-06-16) 표본 기반.

  python3 scripts/test_emart_ssg_filter.py   # exit 0 = PASS
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from pipelines.emart_ssg import collect_emart_ssg as m  # noqa: E402


def o(name, site=None, shpp="22"):
    return {"itemName": name, "siteName": site, "shppTypeDtlCd": shpp,
            "finalPrice": "39,800", "itemId": str(abs(hash(name)) % 10**9)}


# (dict, 기대 is_bottle) — 실측 표본
CASES = [
    # ✅ 진짜 술병 — 카테고리 prefix 1차 신호
    (o("[위스키] 산토리 가쿠빈 700ml", "이마트", "31"), True),
    (o("[매장픽업/양주] 조니워커 블루라벨 750ml", "이마트", "31"), True),
    (o("[위스키] 블랙 앤 화이트 700ml", "이마트", "31"), True),   # 저가 블렌디드도 통과
    # ✅ prefix 없어도 이마트몰 + 위스키 토큰이면 보수적 인정
    (o("더 글렌그란트 15년 싱글몰트 위스키 700ml", "이마트", "31"), True),
    # ❌ 마켓플레이스 액세서리/잡화 노이즈(검색 대부분) — 기각
    (o("로얄리프 발베니 위스키 풀세트 (위스키잔/홈바세트)"), False),   # 잔
    (o("로얄리프 발베니 하이볼&맥주잔 2p세트"), False),               # 잔
    (o("위스키 노징글라스_230ml", "이마트", "11"), False),           # 글라스
    (o("오션글라스 빅토리아 언더락잔_325ml", "이마트", "11"), False),  # 잔
    (o("매거진 B (Magazine B) Vol. 93 - The Balvenie (한글판)"), False),  # 잡지
    (o("25AW 바버 x 빔스 보이 발베니 자켓 BALVENIE Barbour"), False),     # 의류
    (o("위스카스키튼참치 80g", "이마트", "11"), False),               # 고양이밥(우연 토큰)
    # ❌ 비위스키 카테고리 prefix
    (o("[스파클링와인] 모엣 샹동 700ml", "이마트", "31"), False),
    (o("[와인] 1865 까베르네 750ml", "이마트", "31"), False),
    # ❌ prefix 없고 이마트몰도 아니면(마켓플레이스) 위스키 토큰 있어도 보류
    (o("발베니 위스키 디켄터 양주병 (마켓)"), False),
    (o("", "이마트", "31"), False),                                  # 빈 이름
]


def main():
    fails = []
    for item, expect in CASES:
        got = m.is_bottle(item)
        flag = "OK " if got == expect else "FAIL"
        if got != expect:
            fails.append((item["itemName"], expect, got))
        print(f"  [{flag}] is_bottle={got!s:5s} expect={expect!s:5s} :: {item['itemName'][:50]}")
    print(f"\n{len(CASES) - len(fails)}/{len(CASES)} PASS")
    if fails:
        print("FAILURES:")
        for n, e, g in fails:
            print(f"  expected {e}, got {g}: {n}")
        return 1
    print("PASS ✅ — 이마트(SSG) 술병 필터 회귀 가드 통과")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
