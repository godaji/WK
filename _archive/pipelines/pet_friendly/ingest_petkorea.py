#!/usr/bin/env python3
"""ingest_petkorea.py — 공공 '반려동물 동반 가능 업소' 등록부 → 권위 정본 (CMPA-105).

목적: 2026-03 신법 시행 '반려동물 동반 가능 업소' 공공 등록부(foodsafetykorea.go.kr /
data.go.kr, 전국 약 623곳)를 ingest 해 **재게시 가능 라이선스의 권위 정본**으로 만든다.
DiningCode 추정 신호와 달리 등록부는 **법정 등록 사실** → `registry_match.py` 의 교차검증
입력이 되고, 그 자체로 '등록(인증)' 권위 행이다.

두 입력 경로(할랄 ingest_opendata 패턴 재사용):
  (1) `--csv PATH`        : data.go.kr/foodsafetykorea 다운로드 파일데이터 CSV(헤더 유연 매핑).
  (2) `--service-key KEY` : foodsafetykorea OpenAPI 라이브 호출.

⚠️ 환경 제약(CMPA-105 heartbeat probe 확인 · 할랄 CMPA-86 과 동일):
  - `data.go.kr` egress 차단(probe: ConnectionReset), `apis.data.go.kr` HTTP 500,
    foodsafetykorea OpenAPI 는 **승인된 serviceKey** 필요.
  → 라이브 ingest 는 **CEO 게이트**(serviceKey 발급/승인 + egress 허용) 필요.
    그 전까지 `--csv` 로 수동 다운로드 파일을 정규화하는 경로가 동작하며,
    매핑·정규화 로직은 fixture 테스트로 검증한다.

출력: data/pet-friendly/{name}_반려동물동반_공공.csv (find_pet_friendly 와 동일 CSV_FIELDS,
      `출처`=발급기관명, `등록부매칭`=등록(인증)). registry_match 의 등록부 입력으로도 사용 가능.
"""
import argparse
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from pipelines.common.dated import snapshot  # noqa: E402
from pipelines.pet_friendly.find_pet_friendly import (  # noqa: E402
    CSV_FIELDS, OUT_DIR, classify_major, naver_map_link,
)

# 등록부 CSV 헤더는 기관별 상이 → 유연 매핑(부분일치, 소문자).
HEADER_ALIASES = {
    "식당명": ["업소명", "상호", "식당명", "사업장명", "업체명", "name", "title", "음식점명"],
    "카테고리": ["업종", "분류", "카테고리", "category", "유형", "구분"],
    "도로명주소": ["도로명주소", "주소", "소재지", "address", "addr", "위치"],
    "전화": ["전화", "전화번호", "연락처", "tel", "phone"],
    "lat": ["lat", "위도", "y좌표", "ycoord", "mapy", "latitude"],
    "lng": ["lng", "lon", "경도", "x좌표", "xcoord", "mapx", "longitude"],
}


def _build_colmap(fieldnames):
    colmap = {}
    lowered = {fn: (fn or "").strip().lower() for fn in fieldnames}
    for std, aliases in HEADER_ALIASES.items():
        for fn, low in lowered.items():
            if any(a in low for a in aliases):
                colmap[std] = fn
                break
    return colmap


def _get(row, colmap, std):
    col = colmap.get(std)
    return (row.get(col, "") or "").strip() if col else ""


def normalize_rows(raw_rows, fieldnames, source):
    """공공 등록부 원시 행 → CSV_FIELDS 스키마 정본 행. 전 행 등록(인증) 권위."""
    colmap = _build_colmap(fieldnames)
    if "식당명" not in colmap:
        raise ValueError(f"'식당명/업소명' 컬럼을 찾지 못함. 원문 헤더={fieldnames}")
    out = []
    for r in raw_rows:
        name = _get(r, colmap, "식당명")
        if not name:
            continue
        cat = _get(r, colmap, "카테고리")

        def _f(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return ""

        out.append({
            "동반등급": "A·동반명시",
            "등록부매칭": "등록(인증)",
            "식당명": name,
            "카테고리": cat,
            "대분류": classify_major(cat),
            "근거": "공공 등록부: 2026-03 반려동물 동반 가능 업소 법정 등록",
            "주의": "법정 등록 업소. 단 견종·크기·내부동반/테라스한정·예약 조건은 방문 전 확인 권장",
            "출처": source,
            "도로명주소": _get(r, colmap, "도로명주소"),
            "전화": _get(r, colmap, "전화"),
            "도보거리_m": "", "도보_분": "",
            "평판점수": "", "user_score": "", "리뷰수": "",
            "대표사진": "",
            "네이버지도": naver_map_link(name),
            "식당ID": "",
            "lat": _f(_get(r, colmap, "lat")), "lng": _f(_get(r, colmap, "lng")),
        })
    out.sort(key=lambda x: x["식당명"])
    for i, x in enumerate(out, 1):
        x["순위"] = i
    return out


def ingest_csv(path, source, name):
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        raw = list(reader)
        fieldnames = reader.fieldnames or []
    rows = normalize_rows(raw, fieldnames, source)
    print(f"[ingest] {path} → {len(rows)}곳 (전 행 등록(인증) 권위)")
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{name}_반려동물동반_공공.csv")
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    snapshot(out_path)
    print(f"[저장] {out_path}")
    return out_path


def main():
    ap = argparse.ArgumentParser(
        description="공공 '반려동물 동반 가능 업소' 등록부 ingest → 권위 정본 (CMPA-105)")
    ap.add_argument("--csv", help="data.go.kr/foodsafetykorea 다운로드 CSV 경로")
    ap.add_argument("--source", default="식품의약품안전처",
                    help="발급기관명(출처 컬럼)")
    ap.add_argument("--name", default="전국", help="출력 파일 접두(예: 성수역/전국)")
    ap.add_argument("--service-key", help="(미지원-대기) foodsafetykorea OpenAPI serviceKey — egress+승인 필요")
    a = ap.parse_args()
    if a.service_key:
        print("[blocked] foodsafetykorea/data.go.kr 라이브 호출은 egress + 승인 serviceKey 필요 "
              "(현 환경 미충족). CEO 에스컬레이션 대상 — README 참조.", file=sys.stderr)
        sys.exit(3)
    if not a.csv:
        ap.error("--csv 경로가 필요합니다(라이브 OpenAPI 는 현재 게이트 — README 참조).")
    ingest_csv(a.csv, a.source, a.name)


if __name__ == "__main__":
    main()
