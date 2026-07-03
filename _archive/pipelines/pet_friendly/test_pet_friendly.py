#!/usr/bin/env python3
"""test_pet_friendly.py — 펫프렌들리 2-tier 분류기 단위 테스트 (CMPA-105, 네트워크 불필요)."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from pipelines.pet_friendly.find_pet_friendly import pet_tier, classify_major  # noqa: E402

# (이름, 카테고리, 키워드, 기대등급) — ''=제외
TIER_CASES = [
    # Tier A: 동반 명시 신호(주로 keyword 필드)
    ("맥코이", "커피, 카페", "데이트 예쁜 테라스 애견동반", "A"),
    ("프렌즈앤야드", "브런치", "반려동물동반 마당", "A"),
    ("멍카페", "카페", "강아지 동반 가능", "A"),
    ("도그앤캣", "레스토랑", "펫프렌들리", "A"),
    ("로우키", "커피", "pet friendly terrace", "A"),
    # Tier B: 야외/테라스 신호만(동반 명시 없음)
    ("어느루프탑", "브런치", "데이트 루프탑 뷰맛집", "B"),
    ("정원카페", "카페", "예쁜 정원 야외 좌석", "B"),
    # 제외: 신호 전혀 없음
    ("평범국밥", "국밥, 한식", "혼밥 빠른 가성비", ""),
    ("그냥스시", "스시, 일식", "오마카세 데이트", ""),
]

MAJOR_CASES = [
    ("커피, 카페", "카페·브런치"),
    ("베이커리, 카페", "카페·브런치"),
    ("브런치, 팬케이크", "카페·브런치"),
    ("스테이크, 양식", "웨스턴(양식)"),
    ("삼겹살", "고기·구이"),
    ("횟집", "물고기·해산물"),
    ("국밥, 한식", "한식·기타"),
    ("와인바", "바·주류"),
]


def run():
    fails = 0
    for nm, cat, kw, want in TIER_CASES:
        got, reason = pet_tier(nm, cat, kw)
        ok = got == want
        fails += not ok
        print(f"  [{'OK' if ok else 'FAIL'}] tier({nm!r}) = {got!r} (기대 {want!r}) · {reason}")
    for cat, want in MAJOR_CASES:
        got = classify_major(cat)
        ok = got == want
        fails += not ok
        print(f"  [{'OK' if ok else 'FAIL'}] classify_major({cat!r}) = {got!r} (기대 {want!r})")
    print(f"\n{'PASS' if fails == 0 else 'FAIL'}: {fails} 실패")
    return fails


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
