#!/usr/bin/env python3
"""registry_match.py — DiningCode 후보 ∩ 공공 '반려동물 동반 가능 업소' 등록부 교차검증 (CMPA-105).

목적: DiningCode 신호(추정·내부 R&D)에 **권위 있는 공공 등록부**(2026-03 신법, 전국 623곳,
foodsafetykorea/data.go.kr)를 교차매칭해 등록 업소에 '등록(인증)' 배지를 단다. 등록부와
일치하면 단순 검색신호가 아닌 **법정 등록 사실** → 신뢰도가 질적으로 다르다.

라이브 등록부 ingest 는 serviceKey+egress 게이트(`ingest_petkorea.py` 참조)라, 본 모듈은
**등록부 CSV 가 주어졌을 때의 조인 로직**을 담당한다(게이트 해제 후 즉시 동작). 매칭 로직은
fixture 테스트(test_registry_match.py)로 검증한다.

매칭 규칙(보수적 — 오탐보다 미탐 선호):
  1) 상호명 정규화(공백·괄호·지점/점 접미 제거) 완전일치, 또는
  2) 정규화 상호 + 주소 동(洞) 토큰 일치(동명이점 구분), 또는
  3) 좌표가 있으면 150m 이내 + 상호 부분일치.
일치 행의 `등록부매칭` 을 '등록(인증)' 으로 갱신. 반환=로드한 등록부 건수.
"""
import csv
import math
import os
import re

_PAREN = re.compile(r"\(.*?\)|\[.*?\]")
_BRANCH = re.compile(r"(본점|지점|\d+호점|점)$")
_NONWORD = re.compile(r"[^0-9a-zA-Z가-힣]+")


def norm_name(s):
    """상호명 정규화: 괄호/공백/구두점/특수문자/지점 접미 제거, 소문자.
    (영숫자·한글만 유지 → 기관별 표기 차이·기호를 흡수)."""
    t = _PAREN.sub("", s or "")
    t = _NONWORD.sub("", t)
    t = _BRANCH.sub("", t)
    return t.strip().lower()


def _dong(addr):
    """주소에서 동/읍/면/가 토큰 추출(동명이점 구분용)."""
    if not addr:
        return ""
    m = re.search(r"([가-힣]+(?:동|읍|면|가|로|길))", addr)
    return m.group(1) if m else ""


def haversine_m(lat1, lng1, lat2, lng2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


# 등록부 CSV 의 컬럼명은 기관별 상이 → 유연 매핑(부분일치, 소문자).
NAME_ALIASES = ["업소명", "상호", "식당명", "사업장명", "업체명", "name", "title"]
ADDR_ALIASES = ["주소", "소재지", "도로명주소", "address", "addr", "위치"]
LAT_ALIASES = ["lat", "위도", "y", "latitude", "ycoord"]
LNG_ALIASES = ["lng", "lon", "경도", "x", "longitude", "xcoord"]


def _pick(fieldnames, aliases):
    low = {fn: (fn or "").strip().lower() for fn in fieldnames}
    for fn, l in low.items():
        if any(a in l for a in aliases):
            return fn
    return None


def load_registry(path):
    """등록부 CSV → [{name_norm, dong, lat, lng, raw_name}] 리스트."""
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
        fns = reader.fieldnames or []
    nc = _pick(fns, NAME_ALIASES)
    ac = _pick(fns, ADDR_ALIASES)
    latc = _pick(fns, LAT_ALIASES)
    lngc = _pick(fns, LNG_ALIASES)
    if not nc:
        raise ValueError(f"등록부에서 상호 컬럼을 찾지 못함. 헤더={fns}")
    out = []
    for r in rows:
        nm = (r.get(nc) or "").strip()
        if not nm:
            continue
        addr = (r.get(ac) or "").strip() if ac else ""

        def _f(col):
            try:
                return float(r.get(col) or "")
            except (TypeError, ValueError):
                return None

        out.append({
            "name_norm": norm_name(nm),
            "dong": _dong(addr),
            "lat": _f(latc) if latc else None,
            "lng": _f(lngc) if lngc else None,
            "raw_name": nm,
        })
    return out


def match_registry(rows, registry_path, radius_m=150):
    """rows(DiningCode 결과) 의 `등록부매칭` 을 등록부와 교차해 '등록(인증)' 으로 갱신.

    반환: 로드한 등록부 건수(매칭 여부와 무관, 신선도 표기용)."""
    if not os.path.exists(registry_path):
        return 0
    reg = load_registry(registry_path)
    for r in rows:
        rn = norm_name(str(r.get("식당명", "")))
        if not rn or len(rn) < 2:
            continue
        r_dong = _dong(str(r.get("도로명주소", "")))
        matched = False
        for e in reg:
            en = e["name_norm"]
            if len(en) < 2:
                continue
            # 상호 관계: 완전일치 또는 한쪽이 다른쪽의 접두(지점 접미 차이 흡수)
            if not (rn == en or rn.startswith(en) or en.startswith(rn)):
                continue
            # 1) 동 토큰 일치 or 한쪽이 동 정보 없음 → 상호 매칭으로 인정
            if not r_dong or not e["dong"] or r_dong == e["dong"]:
                matched = True
                break
            # 2) 좌표 근접(동이 다르면 좌표로 동명이점 구분)
            try:
                if e["lat"] and r.get("lat"):
                    if haversine_m(float(r["lat"]), float(r["lng"]),
                                   e["lat"], e["lng"]) <= radius_m:
                        matched = True
                        break
            except (TypeError, ValueError):
                pass
        if matched:
            r["등록부매칭"] = "등록(인증)"
    return len(reg)
