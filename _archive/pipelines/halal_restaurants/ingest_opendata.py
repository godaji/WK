#!/usr/bin/env python3
"""ingest_opendata.py — 공공 오픈데이터 무슬림친화 음식점 → Tier A 권위 정본 (CMPA-86 item 1).

목적(설계, data/halal-restaurants/README §5): DiningCode 신호(추정·재게시 법무게이트) 의존을 낮추고,
정부 공공 오픈데이터(한국관광공사/경기관광공사/대구푸드/VisitSeoul 무슬림친화 음식점)를
**재게시 가능 라이선스의 Tier A 권위 정본**으로 ingest 한다. KTO 무슬림친화 4분류
(공인/자가인증/프렌들리/포크프리)를 우리 등급 스키마로 매핑한다.

이 모듈은 두 입력 경로를 지원한다:
  (1) `--csv PATH`  : data.go.kr 에서 받은 파일데이터 CSV(헤더 기관별 상이 → 유연 매핑).
  (2) `--service-key KEY` : 한국관광공사 TourAPI(detailIntro/areaBasedList) 라이브 호출.

⚠️ 현재 환경 제약(CMPA-86 heartbeat 확인):
  - `data.go.kr`/`apis.data.go.kr` 로의 네트워크 egress 가 막혀 있고(probe: HTTP 000),
    TourAPI 는 **승인된 serviceKey** 가 있어야 호출된다(probe: "Unexpected errors").
  → 라이브 ingest 는 **CEO 가 (a) data.go.kr serviceKey 발급/승인 + (b) egress 허용** 을
    제공해야 가능. 그 전까지 `--csv` 로 수동 다운로드 파일을 정규화하는 경로가 동작한다.
  본 모듈의 **매핑·정규화 로직은 fixture 테스트(test_ingest_opendata.py)로 검증 완료**.

출력: data/halal-restaurants/{name}_무슬림식당_공공.{csv} (find_halal 과 동일한 CSV_FIELDS
      스키마, `출처`=발급기관명 → Tier A 권위 표시). HTML 카드뷰는 find_halal._render_html 재사용 가능.
"""
import argparse
import csv
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from pipelines.common.dated import snapshot  # noqa: E402
from pipelines.halal_restaurants.find_halal import (  # noqa: E402  (같은 패키지 공유 헬퍼)
    CSV_FIELDS, OUT_DIR, classify_major, naver_map_link,
)

# ── KTO 무슬림친화 4분류 → 우리 등급 매핑 ─────────────────────────────────────
# 공인/자가인증 = 권위 명시(Tier A) · 프렌들리/포크프리 = 부분조건(Tier B, 단 추정이 아닌 공인분류).
# 입력 분류 문자열의 다양한 표기를 정규화해 매칭한다.
KTO_CLASSES = [
    # (매칭 키워드들, 등급코드 A/B, 등급라벨, 근거, 주의)
    (["공인", "certified", "인증레스토랑", "할랄인증", "kmf"], "A", "A·공인할랄",
     "공공데이터: KTO 할랄 공인(인증기관) 레스토랑",
     "공인 인증. 인증 갱신·자바이하 도축 범위는 방문 전 확인 권장"),
    (["자가", "self", "자가인증"], "A", "A·자가인증",
     "공공데이터: KTO 자가인증(업주 전메뉴 할랄 선언)",
     "업주 자가인증(공인 아님). 조리·재료 범위는 매장 확인 권장"),
    (["프렌들리", "friendly", "무슬림프렌들리"], "B", "B·무슬림프렌들리",
     "공공데이터: KTO 무슬림 프렌들리(할랄 메뉴 제공)",
     "할랄 메뉴 제공하나 주류 취급 가능 — 메뉴·조리용 알코올 매장 확인 필수"),
    (["포크프리", "pork", "포크 프리", "돼지", "no pork"], "B", "B·포크프리",
     "공공데이터: KTO 포크프리(돼지 미사용)",
     "돼지 미사용이나 주류·자바이하 비보장 — 매장 확인 필수"),
]


def classify_kto(class_text):
    """KTO 분류 문자열 → (등급코드, 등급라벨, 근거, 주의). 미매칭 시 None."""
    t = (class_text or "").strip().lower().replace(" ", "")
    for kws, code, label, reason, caution in KTO_CLASSES:
        if any(k.replace(" ", "").lower() in t for k in kws):
            return code, label, reason, caution
    return None


# ── 유연 헤더 매핑 (기관별 CSV 헤더 상이) ────────────────────────────────────
# 각 표준 필드 → 가능한 원문 헤더 후보(부분일치, 소문자). 한국관광공사/경기/대구/VisitSeoul
# 파일데이터의 흔한 헤더를 포괄한다. 매칭 안 되면 빈 값.
HEADER_ALIASES = {
    "식당명": ["식당명", "업소명", "상호", "название", "name", "restaurant", "title", "음식점명"],
    "분류": ["분류", "구분", "등급", "유형", "category_halal", "halal", "무슬림", "type", "인증"],
    "카테고리": ["카테고리", "업종", "메뉴", "음식종류", "cuisine", "food", "category"],
    "도로명주소": ["도로명주소", "주소", "소재지", "address", "addr", "위치"],
    "전화": ["전화", "전화번호", "연락처", "tel", "phone"],
    "lat": ["lat", "위도", "y좌표", "ycoord", "mapy", "latitude"],
    "lng": ["lng", "lon", "경도", "x좌표", "xcoord", "mapx", "longitude"],
    "대표사진": ["대표사진", "이미지", "사진", "image", "firstimage", "photo"],
}


def _build_colmap(fieldnames):
    """원문 헤더 → 표준 필드 매핑(부분일치, 첫 매치 우선)."""
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
    """공공데이터 원시 행 → CSV_FIELDS 스키마 정본 행 리스트. (분류 미매칭 행은 스킵)"""
    colmap = _build_colmap(fieldnames)
    if "식당명" not in colmap:
        raise ValueError(f"'식당명' 컬럼을 찾지 못함. 원문 헤더={fieldnames}")
    out, skipped = [], 0
    for r in raw_rows:
        name = _get(r, colmap, "식당명")
        if not name:
            continue
        cls = classify_kto(_get(r, colmap, "분류"))
        if not cls:
            skipped += 1
            continue
        code, label, reason, caution = cls
        cat = _get(r, colmap, "카테고리")

        def _f(v):
            try:
                return float(v)
            except (TypeError, ValueError):
                return ""

        out.append({
            "할랄등급": label,
            "식당명": name,
            "카테고리": cat,
            "대분류": classify_major(cat),
            "근거": reason,
            "주의": caution,
            "출처": source,
            "도로명주소": _get(r, colmap, "도로명주소"),
            "전화": _get(r, colmap, "전화"),
            "도보거리_m": "", "도보_분": "",
            "평판점수": "", "user_score": "", "리뷰수": "",
            "대표사진": _get(r, colmap, "대표사진"),
            "네이버지도": naver_map_link(name),
            "식당ID": "",
            "lat": _f(_get(r, colmap, "lat")), "lng": _f(_get(r, colmap, "lng")),
            "_code": code,
        })
    # 정렬: A(공인>자가) 먼저 → 이름. 도보거리 없으므로 이름 안정정렬.
    out.sort(key=lambda x: (0 if x["_code"] == "A" else 1, x["식당명"]))
    for i, x in enumerate(out, 1):
        x["순위"] = i
        x.pop("_code", None)
    return out, skipped


def ingest_csv(path, source, name):
    with open(path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        raw = list(reader)
        fieldnames = reader.fieldnames or []
    rows, skipped = normalize_rows(raw, fieldnames, source)
    na = sum(1 for r in rows if str(r["할랄등급"]).startswith("A"))
    print(f"[ingest] {path} → {len(rows)}곳 (A·공인/자가 {na} · B {len(rows)-na}) · "
          f"분류 미매칭 {skipped}건 스킵")
    os.makedirs(OUT_DIR, exist_ok=True)
    out_path = os.path.join(OUT_DIR, f"{name}_무슬림식당_공공.csv")
    with open(out_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    snapshot(out_path)  # _runs/ 날짜 스냅샷 — 공통 규약(CMPA-38/45)
    print(f"[저장] {out_path}")
    return out_path


def main():
    ap = argparse.ArgumentParser(
        description="공공 오픈데이터 무슬림친화 음식점 ingest → Tier A 정본 (CMPA-86)")
    ap.add_argument("--csv", help="data.go.kr 다운로드 CSV 경로")
    ap.add_argument("--source", default="한국관광공사",
                    help="발급기관명(출처 컬럼) — 예: 한국관광공사/경기관광공사/대구광역시")
    ap.add_argument("--name", default="전국",
                    help="출력 파일 접두(예: 이태원역/전국)")
    ap.add_argument("--service-key", help="(미지원-대기) TourAPI serviceKey — egress+승인 필요")
    a = ap.parse_args()
    if a.service_key:
        print("[blocked] TourAPI 라이브 호출은 data.go.kr egress + 승인 serviceKey 필요 "
              "(현 환경 미충족). CEO 에스컬레이션 대상 — README §5 참조.", file=sys.stderr)
        sys.exit(3)
    if not a.csv:
        ap.error("--csv 경로가 필요합니다(라이브 TourAPI 는 현재 차단 — README §5).")
    ingest_csv(a.csv, a.source, a.name)


if __name__ == "__main__":
    main()
