#!/usr/bin/env python3
"""test_registry_match.py — 공공 등록부 교차검증 조인 로직 fixture 테스트 (CMPA-105).

라이브 등록부 ingest 는 게이트(serviceKey+egress) → 합성 fixture 로 매칭 로직만 검증한다.
fabricated fixture(실존 업소 아님)로, 등록/미등록 분기·동명이점 구분·좌표근접을 확인.
"""
import csv
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from pipelines.pet_friendly.registry_match import norm_name, match_registry  # noqa: E402

# 합성 등록부(FIXTURE — 실존 업소 아님). 기관 CSV 헤더 변형도 섞어 유연매핑 검증.
FIXTURE_REGISTRY = [
    {"업소명": "테스트카페 성수점", "소재지": "서울 성동구 성수동2가 1-1",
     "위도": "37.5445", "경도": "127.0560"},
    {"업소명": "샘플브런치", "소재지": "서울 성동구 성수동1가 2-2", "위도": "", "경도": ""},
    {"업소명": "동명이점", "소재지": "부산 해운대구 우동 3-3", "위도": "", "경도": ""},
]

# DiningCode 결과 모사 행
SAMPLE_ROWS = [
    {"식당명": "테스트카페", "도로명주소": "서울 성동구 성수동2가 1-1",
     "lat": 37.5446, "lng": 127.0561, "등록부매칭": "미확인"},   # 상호 일치 → 등록
    {"식당명": "샘플브런치 성수점", "도로명주소": "서울 성동구 성수동1가",
     "lat": 37.54, "lng": 127.05, "등록부매칭": "미확인"},        # 지점 접미 무시 → 등록
    {"식당명": "동명이점", "도로명주소": "서울 강남구 역삼동",
     "lat": 37.50, "lng": 127.03, "등록부매칭": "미확인"},        # 동 불일치 → 미등록
    {"식당명": "등록안된집", "도로명주소": "서울 성동구 성수동2가",
     "lat": 37.5447, "lng": 127.0562, "등록부매칭": "미확인"},     # 등록부에 없음 → 미확인
]

EXPECT = ["등록(인증)", "등록(인증)", "미확인", "미확인"]


def run():
    fails = 0
    # norm_name 동작: 본점/N호점 접미·공백·구두점 정규화
    assert norm_name("테스트카페 본점") == norm_name("테스트카페"), "본점 접미 정규화 실패"
    assert norm_name("테스트카페 2호점") == norm_name("테스트카페"), "N호점 접미 정규화 실패"
    assert norm_name("A&B (성수)") == "ab", f"괄호/구두점 정규화 실패: {norm_name('A&B (성수)')}"
    # '성수점' 처럼 지역+점 접미는 startswith 로 매칭에서 흡수(norm 동일성 아님)
    assert norm_name("샘플브런치 성수점").startswith(norm_name("샘플브런치")), "접두 매칭 전제 실패"

    with tempfile.TemporaryDirectory() as d:
        regpath = os.path.join(d, "reg.csv")
        with open(regpath, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=["업소명", "소재지", "위도", "경도"])
            w.writeheader()
            w.writerows(FIXTURE_REGISTRY)
        n = match_registry(SAMPLE_ROWS, regpath)
        print(f"  등록부 로드: {n}건")
        for r, want in zip(SAMPLE_ROWS, EXPECT):
            got = r["등록부매칭"]
            ok = got == want
            fails += not ok
            print(f"  [{'OK' if ok else 'FAIL'}] {r['식당명']!r} → {got!r} (기대 {want!r})")
        if n != len(FIXTURE_REGISTRY):
            print(f"  [FAIL] 등록부 건수 {n} != {len(FIXTURE_REGISTRY)}")
            fails += 1
    print(f"\n{'PASS' if fails == 0 else 'FAIL'}: {fails} 실패")
    return fails


if __name__ == "__main__":
    sys.exit(1 if run() else 0)
