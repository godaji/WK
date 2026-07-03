# -*- coding: utf-8 -*-
"""CMPA-65 대분류 분류기 검증 — 티켓 명시 엣지케이스 self-test.

    python3 pipelines/corkage_free/test_category_classifier.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from pipelines.corkage_free.category_classifier import classify_category, category_bucket

# (원문, 기대 버킷)
CASES = [
    ("한우, 소고기", "고기"),
    ("삼겹살, 고기집", "고기"),
    ("곱창, 대창, 막창", "고기"),
    ("이베리코, 정육식당", "고기"),
    ("횟집, 생선회", "물고기·해산물"),
    ("장어, 민물장어", "물고기·해산물"),
    ("아구찜, 방어", "물고기·해산물"),
    ("파스타, 피자", "웨스턴(양식)"),
    ("비스트로, 브런치", "웨스턴(양식)"),
    ("화덕피자, 뇨끼", "웨스턴(양식)"),
    ("스시, 오마카세", "일식"),
    ("라멘, 사케", "일식"),
    ("중식당, 짜장면", "중식"),
    ("어향가지, 동파육", "중식"),
    ("국밥, 곰탕", "한식·기타"),
    ("평양냉면, 막걸리", "한식·기타"),
    ("족발, 보쌈", "한식·기타"),
    # 엣지케이스 (티켓 명시)
    ("스테이크", "웨스턴(양식)"),
    ("드라이에이징스테이크, 한우", "고기"),
    ("생갈비, 스테이크", "고기"),
    ("양꼬치, 양갈비", "고기"),
    ("양꼬치, 훠궈", "중식"),
    ("한우, 와인", "고기"),
    ("와인바, 생면파스타", "웨스턴(양식)"),
    ("이자카야, 사시미", "일식"),
    ("와인바", "바·주류"),
    ("수제맥주, 칵테일", "바·주류"),
]


def main():
    failed = []
    for raw, expected in CASES:
        got = category_bucket(raw)
        mark = "OK " if got == expected else "FAIL"
        if got != expected:
            failed.append((raw, expected, got))
        print(f"  [{mark}] {raw:<28s} → {got:<14s} (기대: {expected})")
    print(f"\n결과: {len(CASES) - len(failed)}/{len(CASES)} 통과")
    if failed:
        for raw, exp, got in failed:
            c = classify_category(raw)
            print(f"  - {raw!r}: 기대 {exp}, 실제 {got}; matched={c.matched}")
        raise SystemExit(1)
    print("모든 엣지케이스 통과 ✅")


if __name__ == "__main__":
    main()
