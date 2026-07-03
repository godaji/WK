#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""CMPA-321 가드레일 회귀 테스트 — 데일리샷 수집은 면세/해외 리스팅을 제외한다.

보드 지시(2026-06-13): "면세점은 제외하라". 면세점(신라면세 svc5)·해외가가 데일리샷
마켓플레이스 검색에 KRW 로 섞여 들어와 '국내 최저가' floor 를 오염시킨 사건의 재발 방지.

검증 포인트(2중 신호 — 셀러 API 가용성과 무관해야 함):
  1) price_usd / net_price_usd > 0  → 면세/해외 (1차 신호, 자가완결)
  2) service_type == 5 (면세점)       → 백스톱(셀러 해소된 경우)
  - 둘 중 하나라도 걸리면 floor 후보·listings 동반셋 양쪽에서 제외돼야 한다.

실행: python3 scripts/test_dailyshot_dutyfree_guard.py   (네트워크 불필요)
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, ROOT)
from pipelines.dailyshot import crawl_dailyshot as C  # noqa: E402


def test_is_dutyfree_listing():
    # 1차 신호: price_usd>0
    assert C.is_dutyfree_listing({"price_usd": 32.0, "net_price_usd": 0}) is True
    assert C.is_dutyfree_listing({"price_usd": 0, "net_price_usd": 64.0}) is True
    # 백스톱: service_type==5 (price_usd 누락이어도)
    assert C.is_dutyfree_listing({"price_usd": 0, "service_type": 5}) is True
    # 순수 국내가: 모두 0/비면세 → 제외 안 함
    assert C.is_dutyfree_listing({"price_usd": 0, "net_price_usd": 0, "service_type": 1}) is False
    assert C.is_dutyfree_listing({"price": 68000}) is False
    print("  ✓ is_dutyfree_listing 2중 신호 동작")


def test_floor_excludes_dutyfree():
    """match_lowest 의 floor 는 면세가를 채택하지 않는다(국내 최저만)."""
    products = [
        {"name": "듀어스 15년", "price": 48864, "disc": 0, "tid": 1,
         "price_usd": 32.0, "net_price_usd": 64.0, "service_type": 5},   # 면세 (가장 쌈)
        {"name": "듀어스 15년", "price": 68000, "disc": 0, "tid": 1,
         "price_usd": 0, "net_price_usd": 0, "service_type": 1},          # 국내 최저
        {"name": "듀어스 15년", "price": 113000, "disc": 0, "tid": 1,
         "price_usd": 0, "net_price_usd": 0, "service_type": 2},          # 국내
    ]
    m = C.match_lowest("듀어스 15년", products)
    assert m is not None, "국내 리스팅이 있으면 매칭돼야 함"
    assert m["price"] == 68000, f"floor 는 국내 최저 68000 이어야 하는데 {m['price']}"
    # sellers(동반 listings 후보)에도 면세가가 floor 로 새지 않았는지: 최저가 != 면세가
    assert m["price"] != 48864, "면세가가 floor 로 새면 안 됨"
    print("  ✓ floor 가 면세가(48,864) 대신 국내최저(68,000) 채택")


def test_floor_miss_when_only_dutyfree():
    """국내 리스팅이 하나도 없고 면세만 있으면 floor MISS (면세가를 국내로 둔갑 금지)."""
    products = [
        {"name": "샘플 위스키", "price": 10000, "disc": 0, "tid": 9,
         "price_usd": 9.0, "net_price_usd": 9.0, "service_type": 5},
    ]
    m = C.match_lowest("샘플 위스키", products)
    assert m is None, "면세만 있으면 국내 floor 는 MISS 여야 함"
    print("  ✓ 면세만 존재 시 floor MISS (둔갑 방지)")


def test_page_parser_excludes_dutyfree():
    """CMPA-352: floor 정본이 검색 셀러 min → 제품 페이지 최저가로 바뀌어도
    면세/해외(price_usd>0) 제외는 페이지 파서(_walk_page_price)에서도 유지돼야 한다."""
    from pipelines.shilla_dutyfree import enrich_dailyshot as E
    state = {"queries": [{"state": {"data": {"sellers": [
        # 면세(price_usd>0) — 가장 싸지만 페이지 floor 에서 제외돼야 함
        {"name": "듀어스 15년", "price": 48864, "price_usd": 32.0,
         "seller": {"name": "신라면세"}},
        # 국내 최저
        {"name": "듀어스 15년", "price": 68000, "seller": {"name": "데일리샷셀러"}},
        {"name": "듀어스 15년", "price": 113000, "seller": {"name": "타셀러"}},
    ]}}}]}
    price, seller = E._walk_page_price(state)
    assert price == 68000, f"페이지 floor 는 국내최저 68000 이어야 하는데 {price}"
    assert seller == "데일리샷셀러", f"셀러는 데일리샷셀러 여야 하는데 {seller}"
    print("  ✓ 페이지 파서가 면세(price_usd>0) 제외하고 국내 최저(68,000) 채택")


def test_page_floor_fallback_safe():
    """CMPA-352: tid 가 없거나 캐시에 None 이어도 page_floor 는 안전(폴백 신호)."""
    cache = {}
    assert C.page_floor(None, cache) is None, "tid 없으면 None(검색가 폴백)"
    cache[123] = None
    assert C.page_floor(123, cache) is None, "캐시된 None 그대로 반환(재조회 없음)"
    cache[456] = {"price": 329000, "seller": "피보"}
    assert C.page_floor(456, cache)["price"] == 329000, "캐시 hit 반환"
    print("  ✓ page_floor tid 캐시·폴백 안전")


if __name__ == "__main__":
    test_is_dutyfree_listing()
    test_floor_excludes_dutyfree()
    test_floor_miss_when_only_dutyfree()
    test_page_parser_excludes_dutyfree()
    test_page_floor_fallback_safe()
    print("ALL PASS ✓  (CMPA-321 면세 제외 + CMPA-352 페이지 floor 가드레일)")
