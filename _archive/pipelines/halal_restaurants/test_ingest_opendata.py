#!/usr/bin/env python3
"""test_ingest_opendata.py — 공공데이터 ingest 정규화 회귀 테스트 (CMPA-86 item 1).

네트워크 없이 합성 fixture(한국관광공사 무슬림친화 음식점 파일데이터 형태)로
KTO 4분류 매핑·유연 헤더 정규화를 검증한다. 실데이터(data.go.kr)는 egress+serviceKey
승인 후 동일 매핑으로 흐른다.

실행:  python3 pipelines/halal_restaurants/test_ingest_opendata.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pipelines.halal_restaurants.ingest_opendata import classify_kto, normalize_rows  # noqa: E402

# 합성 fixture: 기관별 헤더가 다른 상황을 모사(업소명/할랄구분/메뉴/소재지/위도/경도).
FIELDNAMES = ["업소명", "할랄구분", "메뉴", "소재지도로명주소", "전화번호", "위도", "경도"]
RAW = [
    {"업소명": "이태원 할랄 키친", "할랄구분": "할랄 공인", "메뉴": "인도음식",
     "소재지도로명주소": "서울 용산구 우사단로 10", "전화번호": "02-111-1111",
     "위도": "37.5345", "경도": "126.9944"},
    {"업소명": "케밥 하우스", "할랄구분": "자가인증", "메뉴": "케밥,터키음식",
     "소재지도로명주소": "서울 용산구 이태원로 20", "전화번호": "", "위도": "37.534", "경도": "126.995"},
    {"업소명": "스파이스 가든", "할랄구분": "무슬림 프렌들리", "메뉴": "태국음식",
     "소재지도로명주소": "서울 용산구 이태원로 30", "전화번호": "", "위도": "", "경도": ""},
    {"업소명": "노포크 비스트로", "할랄구분": "포크프리", "메뉴": "양식",
     "소재지도로명주소": "서울 용산구 이태원로 40", "전화번호": "", "위도": "", "경도": ""},
    # 분류 미매칭(일반 식당) → 스킵되어야 함
    {"업소명": "김밥나라", "할랄구분": "", "메뉴": "분식",
     "소재지도로명주소": "서울 용산구 이태원로 50", "전화번호": "", "위도": "", "경도": ""},
]


def test_classify():
    cases = [
        ("할랄 공인", "A", "A·공인할랄"),
        ("자가인증", "A", "A·자가인증"),
        ("무슬림 프렌들리", "B", "B·무슬림프렌들리"),
        ("포크프리", "B", "B·포크프리"),
        ("Halal Certified", "A", "A·공인할랄"),
        ("Muslim Friendly", "B", "B·무슬림프렌들리"),
        ("", None, None),
        ("일반식당", None, None),
    ]
    fails = 0
    for txt, code, label in cases:
        res = classify_kto(txt)
        got_code = res[0] if res else None
        got_label = res[1] if res else None
        ok = got_code == code and got_label == label
        if not ok:
            fails += 1
        print(f"  [{'PASS' if ok else 'FAIL'}] classify_kto('{txt}') → "
              f"{got_code}/{got_label} (기대 {code}/{label})")
    return fails


def test_normalize():
    rows, skipped = normalize_rows(RAW, FIELDNAMES, "한국관광공사")
    fails = 0

    def check(cond, desc):
        nonlocal fails
        if not cond:
            fails += 1
        print(f"  [{'PASS' if cond else 'FAIL'}] {desc}")

    check(len(rows) == 4, f"분류 매칭 4곳 정규화 (실제 {len(rows)})")
    check(skipped == 1, f"미매칭 1건 스킵 (실제 {skipped})")
    # 정렬: A(공인/자가) 먼저
    check(rows[0]["할랄등급"].startswith("A"), "A등급이 상위 정렬")
    # 유연 헤더 매핑: 업소명→식당명, 소재지도로명주소→도로명주소
    name0 = rows[0]["식당명"]
    check(name0 == "이태원 할랄 키친", f"업소명→식당명 매핑 (실제 '{name0}')")
    addrs = [r for r in rows if r["식당명"] == "이태원 할랄 키친"][0]["도로명주소"]
    check(addrs == "서울 용산구 우사단로 10", f"소재지도로명주소→도로명주소 매핑 (실제 '{addrs}')")
    # 좌표 float 변환
    kebab = [r for r in rows if r["식당명"] == "케밥 하우스"][0]
    check(isinstance(kebab["lat"], float) and abs(kebab["lat"] - 37.534) < 1e-6,
          f"위도→lat float (실제 {kebab['lat']!r})")
    # 출처 = 권위기관
    check(all(r["출처"] == "한국관광공사" for r in rows), "출처=발급기관명(Tier A 권위 표시)")
    # 대분류 분류기 연동
    halal_kitchen = rows[0]
    check(halal_kitchen["대분류"] == "중동·인도(할랄친화)",
          f"인도음식→대분류 매핑 (실제 '{halal_kitchen['대분류']}')")
    # 스키마 키 일치(CSV_FIELDS 의 핵심 조인키 존재)
    for k in ("순위", "할랄등급", "근거", "주의", "출처", "lat", "lng"):
        check(k in rows[0], f"스키마 키 '{k}' 존재")
    return fails


def run():
    print("── classify_kto ──")
    f1 = test_classify()
    print("── normalize_rows ──")
    f2 = test_normalize()
    total_fail = f1 + f2
    print(f"\n{'전부 OK ✅' if not total_fail else str(total_fail) + ' 실패 ❌'}")
    return 1 if total_fail else 0


if __name__ == "__main__":
    sys.exit(run())
