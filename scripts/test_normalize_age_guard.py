#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
test_normalize_age_guard.py — CMPA-444 정규화 매처 숙성년수(N년) 비대칭 가드 회귀.

배경(CMPA-443 후속): whisky-synonyms.yaml 의 다수 규칙이 브랜드 토큰만으로 매칭한다
(예: {match:[글렌드로낙]} → 글렌드로낙 12년). 그래서 'N년' 값이 다른 변형이 정본 다른
SKU 로 오병합됐다(글렌드로낙 18년·라가불린 8년 → w018/w036). CLAUDE.md CMPA-177:
N년 토큰이 다르면 다른 제품 → 병합 금지. Normalizer.canonicalize 에 ingest_ocr.match 와
동일한 최종 age 가드를 넣어, 변형·정본 양쪽에 N년이 있고 값이 다르면 매칭을 거절한다.

핵심 불변식(어기면 가짜 딜·floor 오염 위험):
  · 변형 년수 ≠ 정본 년수 → unmatched (오매칭 0).
  · 둘 중 하나라도 년수가 없으면(무연수 정본·큐레이트 별칭) 보수적 통과(현행 보존).
  · 같은 년수/같은 제품은 그대로 matched (무회귀).
실행: python3 scripts/test_normalize_age_guard.py   (exit 0=통과)
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from normalize_whisky_name import Normalizer, load_rules  # noqa: E402

norm = Normalizer(load_rules())

# (raw, 거절돼야 할 정본 id) — 년수 비대칭이라 이 id 로 매칭되면 안 됨.
REJECT = [
    ("글렌드로낙 18년", "w018"),          # 정본 글렌드로낙 12년 (18≠12)
    ("글랜드로낙15년(신청)", "w018"),      # 오자+년수 비대칭 (15≠12)
    ("라가불린 8년 700ml", "w036"),       # 정본 라가불린 11년 (8≠11)
    ("라가불린 16년", "w036"),            # 별개 제품, 11년 정본으로 끌려가면 안 됨
]

# (raw, 매칭돼야 할 정본 id) — 같은 년수/무연수 보존. 무회귀 가드.
ACCEPT = [
    ("글렌드로낙 12년", "w018"),
    ("라가불린 11년 오퍼맨", "w036"),
    ("글렌피딕 12년", "w005"),
    ("맥캘란 12년 더블캐스크", "w012"),
    ("발렌타인 17년", "w090"),
]

fails = []
for raw, bad_id in REJECT:
    r = norm.canonicalize(raw)
    # 년수 비대칭이면 그 정본으로 matched 되면 안 된다(unmatched 또는 다른 적합 id 만 허용).
    if r["status"] == "matched" and r["id"] == bad_id:
        fails.append(f"REJECT 실패: {raw!r} → matched {bad_id} {r['name_ko']} (거절돼야 함)")

for raw, want_id in ACCEPT:
    r = norm.canonicalize(raw)
    if not (r["status"] == "matched" and r["id"] == want_id):
        fails.append(f"ACCEPT 회귀: {raw!r} → {r['status']} {r['id']} (기대 matched {want_id})")

if fails:
    print("FAIL — CMPA-444 age 가드 회귀:")
    for f in fails:
        print("  -", f)
    sys.exit(1)
print(f"PASS — REJECT {len(REJECT)}건 거절 + ACCEPT {len(ACCEPT)}건 무회귀 (CMPA-444 age 가드)")
