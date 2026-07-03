#!/usr/bin/env python3
"""
find_pet_friendly.py — 지하철역 기준 "반려동물 동반(펫프렌들리) 식당" 탐색기 (CMPA-105, Phase-0 POC)

전략 근거: CMPA-103 니즈 버티컬 리서치 → 펫프렌들리가 TOP1(2026-03 반려동물 동반업소 신법,
반려인 1,500만, 공공 등록부 존재). 보드 승인 confirmation adf6fda2.

핵심 원칙(CMPA-105) — 기존 엔진 재사용, 속성만 교체:
  이 모듈은 `pipelines/halal_restaurants/find_halal.py`(그 자체가 corkage_free 엔진의 fork)의
  검증된 조각(DiningCode isearch `dc_search`, haversine 도보거리, `classify_major`, 날짜
  스냅샷, HTML 카드뷰)을 **복사(fork)** 해 와서, 할랄 2-tier 로직을 **펫프렌들리 신호**로
  교체한 독립 파이프라인이다. (import 가 아니라 복사 — 콜키지/할랄과 동일한 보드 지시.)

2-Tier 분류 (펫프렌들리에 맞춤):
  - Tier A (동반명시): 이름/카테고리/키워드에 `애견동반`·`반려동물동반`·`펫프렌들리`·`반려견 동반`
      등 **동반 가능 명시 신호** → DiningCode 가 실제 'pet OK' 태그로 다는 가장 강한 신호.
  - Tier B (추정·확인필요): 동반 명시는 없지만 **야외/테라스 좌석 신호**(테라스/루프탑/마당/정원/
      옥상/야외)가 있어 동반이 허용될 *가능성*이 있는 곳. 어디까지나 추정 후보.
  - 제외: 위 신호가 전혀 없는 곳.

공공 등록부 교차검증(권위 소스):
  2026-03 신법 '반려동물 동반 가능 업소' 공공 등록부(foodsafetykorea/data.go.kr, 전국 623곳)와
  교차매칭해 **등록=인증 배지**를 단다. 단 라이브 등록부 ingest 는 serviceKey+egress 게이트
  (CMPA-86 할랄과 동일 제약) → `ingest_petkorea.py` + `registry_match.py` 로 분리하고, 본
  finder 의 `등록부매칭` 컬럼은 등록부 CSV 가 주어지면 교차표시, 없으면 '미확인(게이트대기)'.

정직성/변동성(필수 고지):
  반려동물 동반 정책은 **변동성이 매우 크다**(업소 책임부담으로 동반 철회 잦음). 견종·크기·
  내부 동반 여부·테라스 한정·예약 필요 등 세부는 데이터로 확정 불가 → 전 행 `주의` 컬럼에
  "방문 전 매장 확인 필수"를 명시한다. Tier B 는 추정 후보일 뿐이다.

⚠️ 내부 R&D 전용. 외부 공개·배포는 게이트 c7405e7d 계열 + 공공데이터 라이선스·개인정보
   검토 통과 전 금지(CMPA-105 가드레일).

용법:
  python3 pipelines/pet_friendly/find_pet_friendly.py --station 성수역 --radius 700
  python3 pipelines/pet_friendly/find_pet_friendly.py --station 성수역 --registry data/pet-friendly/_등록부.csv
"""
import argparse
import csv
import json
import math
import os
import re
import sys
import time
from html import escape as _esc
from urllib.parse import quote as _quote

import requests

# ── 엔진 조각 (halal/corkage_free 에서 복사 — fork, import 금지) ──────────────
# 출처(검색 신호) 식별: 키 없이 호출 가능한 공개 검색 API. 산출물에는 외부 브랜드 흔적을
# 남기지 않는다(CMPA-102/87 디브랜딩 패턴 — corkage_free 참조). 아래 상수는 법무 감사용
# 코드 주석으로만 출처를 보존하고, CSV/리포트에는 내부 식별자(식당ID, rid)·'공개 검색 신호'
# 표기만 남긴다.
API = "https://im.diningcode.com/API/isearch/"  # 출처(법무감사용): 공개 검색 isearch
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from pipelines.common.dated import snapshot, kst_today  # noqa: E402
# 폴더 미러링(CMPA-86 패턴): 데이터셋(csv)=data/, 사람이 보는 리포트(md/html)=reports/.
OUT_DIR = os.path.join(ROOT, "data", "pet-friendly")
REPORT_DIR = os.path.join(ROOT, "reports", "pet-friendly")

_EM = re.compile(r"</?em>", re.I)


def clean(s):
    """DiningCode 검색 하이라이트(<em>) 제거."""
    return _EM.sub("", s or "").strip()


# 내장 역 좌표(WGS84). 콜키지/할랄 사전 + 펫 핫스팟 역 추가(CMPA-105).
# 성수역(2호선)=서울 대표 펫프렌들리 핫스팟(카페·브런치·테라스 밀집) → Phase-0 1호 역.
STATION_COORDS = {
    "성수역": (37.544577, 127.055961),     # 2호선, 카페거리·테라스 밀집 — 펫프렌들리 밀도 최고
    "강남역": (37.497942, 127.027621),
    "연남동": (37.561980, 126.925350),     # 홍대입구역 인근(연남동) — 펫 핫스팟 후보
    "한남역": (37.529849, 127.009250),
    "합정역": (37.549513, 126.913708),
    "홍대입구역": (37.557527, 126.924191),
}


def haversine_m(lat1, lng1, lat2, lng2):
    """두 WGS84 좌표 사이 직선거리(m)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def dc_search(query, size=100, pages=1, sleep=0.8):
    """DiningCode isearch 호출 → poi list 반환. (corkage_free/halal 에서 복사)"""
    out = []
    for page in range(pages):
        body = {
            "query": query, "addr": "", "keyword": query,
            "order": "r_score", "from": page * size, "size": size,
        }
        try:
            resp = requests.post(API, data=body,
                                 headers={"User-Agent": UA,
                                          "Content-Type": "application/x-www-form-urlencoded"},
                                 timeout=25)
            resp.raise_for_status()
            rd = resp.json().get("result_data", {})
            lst = rd.get("poi_section", {}).get("list", []) or []
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] '{query}' page{page} 실패: {e}", file=sys.stderr)
            break
        out.extend(lst)
        if len(lst) < size:
            break
        time.sleep(sleep)
    return out


# ── 대분류(major) — classify_major 복사 + '카페·브런치' bucket 을 최상위로 ─────
# 펫프렌들리는 카페·브런치·디저트 업종이 압도적이라(테라스 동반) 콜키지 7종 앞에 별도 버킷.
MAJOR_UNCLASSIFIED = "기타"
MAJOR_RULES = [
    ("카페·브런치", ["커피", "카페", "베이커리", "브런치", "디저트", "제과", "빵집", "빵", "라떼",
                "팬케이크", "와플", "도넛", "케이크", "샌드위치", "샐러드", "아이스크림",
                "빙수", "티룸", "차", "스무디", "에스프레소", "로스터리"]),
    ("물고기·해산물", ["횟집", "생선회", "생선구이", "숙성회", "물회", "방어", "참치",
                  "복어", "복국", "아구", "문어", "매운탕", "지리", "백합", "고등어",
                  "해물", "해산물", "조개", "광어", "낙지", "대게", "장어", "오징어",
                  "새우", "굴요리", "멍게", "해물탕", "조개구이", "전복", "꽃게"]),
    ("바·주류", ["와인바", "칵테일", "수제맥주", "샴페인", "위스키바", "맥주바", "술집",
              "이자카야", "포차", "호프", "펍", "pub", "와인"]),
    ("웨스턴(양식)", ["스테이크", "파스타", "피자", "양식", "레스토랑", "비스트로",
                  "뉴욕", "화덕", "리조또", "스파게티", "파니니", "웨스턴", "버거",
                  "이탈리안", "프렌치", "타코", "멕시칸"]),
    ("중식", ["훠궈", "중식", "중국", "짜장", "짬뽕", "양꼬치", "마라", "딤섬", "양장피"]),
    ("일식", ["사시미", "스시", "오마카세", "라멘", "사케", "일식", "우동",
            "돈카츠", "텐동", "초밥", "덮밥집"]),
    ("고기·구이", ["삼겹", "족발", "보쌈", "돈까스", "돈가스", "곱창", "막창", "대창",
               "돼지", "한돈", "흑돼지", "한우", "소고기", "갈비", "양고기", "양갈비",
               "닭", "치킨", "고기"]),
    ("한식·기타", ["국밥", "냉면", "찌개", "백반", "한정식", "비빔밥", "국수", "쌀국수",
                "분식", "떡볶이", "한식", "베트남"]),
]


def classify_major(category):
    """DiningCode 원문 카테고리 → 대분류(결정론적, 첫 토큰 우선)."""
    raw = (category or "").strip()
    primary = raw.split(",")[0].strip()
    for text in (primary, raw):
        if not text:
            continue
        for bucket, kws in MAJOR_RULES:
            if any(kw in text for kw in kws):
                return bucket
    return MAJOR_UNCLASSIFIED


# ── 펫프렌들리 2-tier 분류기 (CMPA-105 핵심 로직) ────────────────────────────
# 동반 명시(Tier A): DiningCode 가 'pet OK' 로 다는 신호. 띄어쓰기·표기 변형 포괄.
#   '애견동반/반려동물동반/펫동반/반려견동반/강아지동반/펫프렌들리/pet|dog friendly'.
EXPLICIT_RX = re.compile(
    r"애견\s*동반|반려\s*동물\s*동반|반려\s*견\s*동반|반려동물동반|반려견동반|"
    r"펫\s*동반|강아지\s*동반|애완\s*동반|펫\s*프렌들리|펫프렌들리|"
    r"(?:pet|dog)\s*friendly", re.I)

# Tier B(추정) 신호: 야외/테라스 좌석 — 동반 허용 *가능성* 있으나 보장 아님.
PATIO_RX = re.compile(r"테라스|루프탑|루프 ?탑|옥상|마당|정원|가든|garden|야외|툇마루|"
                      r"펫|애견|반려", re.I)


def pet_tier(nm, cat, kw):
    """(등급, 근거) 반환. 등급 ∈ {'A','B',''}. ''=제외.

    nm=식당명, cat=DiningCode 원문 카테고리, kw=메뉴/키워드 합본.
    동반 명시·테라스 신호는 이름+카테고리+키워드(hay) 전체에서 찾는다(DiningCode 의 동반
    태그가 keyword 필드에 들어오므로 hay 전체를 봐야 한다).
    """
    hay = f"{nm} {cat} {kw}"
    if EXPLICIT_RX.search(hay):
        return "A", "동반 가능 명시(애견/반려동물 동반 태그)"
    if PATIO_RX.search(hay):
        # 테라스/야외 등 — 동반 가능성 있는 추정 후보
        m = PATIO_RX.search(hay)
        return "B", f"야외·테라스 좌석 신호('{m.group(0).strip()}') — 동반 허용 가능성(확인필요)"
    return "", ""


# 출처 = 데이터 권위 구분(외부 브랜드 흔적 없이, CMPA-102/87). '공개 검색 신호(추정)'=
# 내부 R&D 추정 · 공공 등록부 매칭 행은 `등록부매칭`=등록(인증) → 권위 교차검증.
# 보드 지시: 다코점수(평판점수)·별점(user_score)·리뷰수는 외부 브랜드 신호라 CSV에서도 제외.
#   점수는 find() 정렬 시 행 dict 의 transient 키로만 쓰고 CSV에는 쓰지 않는다(아래 미포함).
# 식별자는 외부 프로필 URL 대신 내부 rid(`식당ID`) 만 저장한다(CMPA-102).
CSV_FIELDS = ["순위", "동반등급", "등록부매칭", "식당명", "카테고리", "대분류", "근거", "주의",
              "출처", "도로명주소", "전화", "도보거리_m", "도보_분",
              "대표사진", "네이버지도", "식당ID", "lat", "lng"]

QUERY_SUFFIXES = ["반려동물동반", "애견동반", "펫프렌들리", "반려동물", "애견", "강아지",
                  "펫", "테라스", "루프탑", "마당"]


def row_rid(r):
    """식당 고유 ID(rid). 신규 CSV는 `식당ID`(rid 단독), 구 CSV는 `다이닝코드링크`(URL)
    둘 다 허용해 무중단 마이그레이션(외부 소스 브랜드 흔적 제거, CMPA-102). 등록부 매칭·
    캐시의 조인 키로만 쓰이는 내부 식별자."""
    v = (r.get("식당ID") or r.get("다이닝코드링크") or "").strip()
    return v.split("rid=")[-1].strip()


def naver_map_link(name):
    return f"https://map.naver.com/p/search/{_quote(name.strip())}"


def find(station, lat, lng, radius_m):
    print(f"[조회] {station} ({lat},{lng}) 반경 {radius_m}m")
    pois = {}
    for suf in QUERY_SUFFIXES:
        for p in dc_search(f"{station} {suf}"):
            if p.get("v_rid"):
                pois.setdefault(p["v_rid"], p)
    print(f"  후보 {len(pois)}곳 수집")

    rows = []
    n_excl = 0
    for rid, p in pois.items():
        try:
            plat, plng = float(p["lat"]), float(p["lng"])
        except (TypeError, ValueError, KeyError):
            continue
        dist = haversine_m(lat, lng, plat, plng)
        if dist > radius_m:
            continue
        nm = clean(p.get("nm")) + (f" {clean(p['branch'])}" if p.get("branch") else "")
        cat = clean(p.get("category"))
        kw = " ".join(k.get("term", "") for k in (p.get("keyword") or []))
        tier, reason = pet_tier(nm, cat, kw)
        if not tier:
            n_excl += 1
            continue
        if tier == "A":
            grade = "A·동반명시"
            caution = ("동반 가능 표기. 단 견종·크기·내부동반/테라스한정·예약 여부는 정책 변동 잦아 "
                       "방문 전 매장 확인 권장")
        else:
            grade = "B·추정(확인필요)"
            caution = ("추정 후보(야외·테라스 신호) — 반려동물 동반 가능 여부·조건은 방문 전 매장 "
                       "확인 필수")
        rows.append({
            "동반등급": grade,
            "등록부매칭": "미확인",  # 공공 등록부 cross-match 전 기본값(registry_match 가 갱신)
            "식당명": nm,
            "카테고리": cat,
            "대분류": classify_major(cat),
            "근거": reason,
            "주의": caution,
            "출처": "공개 검색 신호(추정)",  # CMPA-102: 외부 브랜드명 미표기(법무감사용은 코드 주석)
            "도로명주소": clean(p.get("road_addr")) or clean(p.get("addr")),
            "전화": p.get("phone", ""),
            "도보거리_m": round(dist),
            "도보_분": round(dist / 67),
            "평판점수": p.get("score", ""),  # 내부 데이터(정렬용) — 리포트 미렌더(CMPA-87)
            "user_score": p.get("user_score", ""),
            "리뷰수": p.get("review_cnt", ""),
            "대표사진": "",  # CMPA-102: 외부 소스 CDN 이미지 URL 미저장(브랜드 흔적 제거)
            "네이버지도": naver_map_link(nm),
            "식당ID": rid,  # 내부 조인 키(외부 프로필 URL 미저장, CMPA-102)
            "lat": plat, "lng": plng,
            "_t": 0 if tier == "A" else 1,
        })
    # 정렬: Tier A 먼저 → 평판점수 desc → 가까운 순
    def _score(r):
        try:
            return float(r.get("평판점수") or 0)
        except (TypeError, ValueError):
            return 0.0
    rows.sort(key=lambda r: (r["_t"], -_score(r), r["도보거리_m"]))
    na = sum(1 for r in rows if r["_t"] == 0)
    for i, r in enumerate(rows, 1):
        r["순위"] = i
        r.pop("_t", None)
    print(f"  결과: 동반명시 A={na} · 추정 B={len(rows)-na} · 제외 {n_excl}곳")
    return rows, na


MAJOR_ORDER = ["카페·브런치", "웨스턴(양식)", "물고기·해산물", "고기·구이", "한식·기타",
               "일식", "중식", "바·주류", "기타"]


def major_distribution_md(rows):
    cnt = {b: 0 for b in MAJOR_ORDER}
    for r in rows:
        cnt[r["대분류"]] = cnt.get(r["대분류"], 0) + 1
    total = max(1, len(rows))
    out = ["### 대분류 분포\n\n", "| 대분류 | 곳 | 비중 |\n", "|---|---:|---:|\n"]
    for b in MAJOR_ORDER:
        if cnt.get(b):
            out.append(f"| {b} | {cnt[b]} | {round(100*cnt[b]/total)}% |\n")
    out.append(f"| **합계** | **{len(rows)}** | 100% |\n\n")
    return "".join(out)


# ── HTML 카드뷰 — halal find_halal._render_html 을 fork·적응 ──────────────────
# 펫 테마(보라/민트), 동반등급(A/B) + 공공등록부 인증 배지.
# CMPA-109: 상단 노란색 면책 고지 배너 제거 → 대신 헤더에 **리포트 작성일**을 노출해
# 사용자가 최신성(동반 정책 변동성)을 직접 판단하도록 한다(고지 문구는 각 카드 ⚠️주의·MD
# 리포트 신선도 노트에 유지).
MAJOR_ORDER_HTML = MAJOR_ORDER


def _render_html(station, rows, na, radius_m, registry_n=0, run_date=""):
    nb = len(rows) - na
    n_reg = sum(1 for r in rows if str(r.get("등록부매칭", "")).startswith("등록"))
    reg_line = (f" · 🏅등록부 인증 {n_reg}곳" if registry_n else
                " · 🏅등록부 교차검증 대기(공공데이터 게이트)")
    head = (
        "<!doctype html><html lang=ko><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{_esc(station)} 반려동물 동반(펫프렌들리) 식당</title><style>"
        "body{font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;margin:0;background:#f6f6f8;color:#222}"
        "header{padding:18px 16px;background:#5b3f9e;color:#fff}"
        "header h1{margin:0 0 4px;font-size:20px}header p{margin:0;font-size:13px;opacity:.92}"
        # CMPA-109: 리포트 작성일(최신성 판단 기준) — 노란 고지 배너 대체
        ".rundate{margin:7px 0 0;font-size:12px;opacity:.85}"
        ".filterbar{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid #e6e6ea;"
        "padding:10px 16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}"
        ".fgroup{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:4px 0}"
        ".fglabel{font-size:12px;font-weight:700;color:#555;min-width:64px}"
        ".fbtn{font-size:12px;border:1px solid #ccc;background:#fff;color:#333;border-radius:14px;"
        "padding:5px 11px;cursor:pointer;line-height:1;user-select:none}"
        ".fbtn:hover{border-color:#999}"
        ".fgroup.grade .fbtn.on{background:#5b3f9e;border-color:#5b3f9e;color:#fff}"
        ".fgroup.food .fbtn.on{background:#1b1b2b;border-color:#1b1b2b;color:#fff}"
        ".fmeta{font-size:12px;color:#666;margin-top:6px}"
        ".fmeta .freset{color:#5b3f9e;cursor:pointer;text-decoration:underline;margin-left:8px}"
        ".wrap{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;padding:16px}"
        ".card{background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08);"
        "display:flex;flex-direction:column}"
        ".card.ga{outline:2px solid #5b3f9e}"
        ".card.hide{display:none}"
        ".photo{position:relative;width:100%;height:150px;background:#eee;overflow:hidden}"
        ".thumb{width:100%;height:150px;object-fit:cover;display:block}"
        # 역↔식당 위치 지도를 사진 밴드 전체로 표시(CMPA-102 패턴): 빈 회색 밴드 대신 위치 지도.
        ".bandmap{width:100%;height:150px;object-fit:cover;display:block;background:#eee}"
        ".rank{position:absolute;left:7px;top:7px;background:rgba(20,20,30,.78);color:#fff;"
        "font-size:12px;font-weight:700;padding:3px 9px;border-radius:13px}"
        ".grade{position:absolute;right:7px;top:7px;font-size:12px;font-weight:700;"
        "padding:3px 9px;border-radius:13px;box-shadow:0 1px 4px rgba(0,0,0,.4)}"
        ".grade.A{background:#5b3f9e;color:#fff}.grade.B{background:#fd7e14;color:#fff}"
        ".body{padding:12px 14px;flex:1;display:flex;flex-direction:column;gap:6px}"
        ".nm{font-size:16px;font-weight:700}.cat{font-size:12px;color:#666}"
        ".reg{display:inline-block;background:#0f8a5f;color:#fff;font-size:11px;font-weight:700;"
        "border-radius:9px;padding:1px 7px;margin-left:4px}"
        ".major{display:inline-block;background:#5b3f9e;color:#fff;font-size:11px;"
        "font-weight:700;border-radius:9px;padding:1px 7px;margin-right:4px}"
        ".reason{font-size:12px;color:#4a3185;background:#efe9fb;border-radius:8px;padding:4px 9px;"
        "align-self:flex-start}"
        ".caution{font-size:11.5px;color:#842029;background:#fbeaec;border-radius:8px;padding:5px 9px;"
        "line-height:1.45}"
        ".meta{font-size:12px;color:#444;line-height:1.6}"
        ".links{margin-top:auto;display:flex;gap:8px;padding-top:8px}"
        ".links a{flex:1;text-align:center;font-size:13px;text-decoration:none;padding:8px 0;border-radius:8px}"
        ".naver{background:#03c75a;color:#fff}"
        ".note{font-size:12px;color:#888;padding:0 16px 24px}"
        "</style></head><body>"
        f"<header><h1>🐶 {_esc(station)} 반려동물 동반(펫프렌들리) 식당</h1>"
        f"<p>도보 {radius_m}m(약 {round(radius_m/67)}분) 이내 · "
        f"A·동반명시 {na}곳 · B·추정 {nb}곳{reg_line} · 거리=직선 근사</p>"
        + (f"<p class=rundate>📅 리포트 작성일 {_esc(run_date)} — 동반 정책은 변동이 잦으니 "
           "최신성은 이 날짜를 기준으로 판단하세요</p>" if run_date else "")
        + "</header>"
    )
    grade_cnt = {"A": na, "B": nb}
    food_cnt = {}
    for r in rows:
        mv = r.get("대분류", "") or MAJOR_UNCLASSIFIED
        food_cnt[mv] = food_cnt.get(mv, 0) + 1
    food_btns = [(b, food_cnt[b]) for b in MAJOR_ORDER_HTML if food_cnt.get(b)]

    def _fbtns(items):
        return "".join(
            f"<span class=fbtn data-val=\"{_esc(str(v))}\">{_esc(lbl)} <small>{c}</small></span>"
            for v, lbl, c in items
        )

    grade_items = [(g, ("A·동반명시" if g == "A" else "B·추정"), grade_cnt[g])
                   for g in ("A", "B") if grade_cnt[g]]
    filterbar = (
        "<div class=filterbar>"
        "<div class='fgroup grade'><span class=fglabel>동반등급</span>"
        + _fbtns(grade_items) + "</div>"
        "<div class='fgroup food'><span class=fglabel>음식 종류</span>"
        + _fbtns([(b, b, c) for b, c in food_btns]) + "</div>"
        "<div class=fmeta>버튼을 눌러 필터링 — <b>등급 × 음식 = AND</b>, 같은 묶음 안에서는 OR. "
        "<span id=fcount></span><span class=freset id=freset>전체 해제</span></div>"
        "</div><div class=wrap>"
    )
    cards = []
    for r in rows:
        g = "A" if str(r["동반등급"]).startswith("A") else "B"
        # 사진 밴드 자리 = 역↔식당 위치 지도(CMPA-102, corkage_free 참조). 지도 없으면 회색 폴백.
        img = (f"<img class=bandmap loading=lazy src='{r['_mapuri']}' "
               f"alt='{_esc(station)}↔{_esc(str(r['식당명']))} 위치 지도'>"
               if r.get("_mapuri") else "<div class=thumb></div>")
        phone = f"☎ {_esc(str(r['전화']))}<br>" if r.get("전화") else ""
        major_v = r.get("대분류", "") or MAJOR_UNCLASSIFIED
        reg = ("<span class=reg>🏅등록</span>"
               if str(r.get("등록부매칭", "")).startswith("등록") else "")
        cards.append(
            f"<div class='card g{g}' data-grade=\"{g}\" data-major=\"{_esc(major_v)}\">"
            f"<div class=photo>{img}<span class=rank>{r['순위']}위</span>"
            f"<span class='grade {g}'>{'A·동반명시' if g=='A' else 'B·추정'}</span></div>"
            f"<div class=body>"
            f"<div class=nm>{_esc(str(r['식당명']))}{reg}</div>"
            f"<div class=cat><span class=major>{_esc(major_v)}</span> {_esc(str(r['카테고리']))}</div>"
            f"<div class=reason>{_esc(str(r['근거']))}</div>"
            f"<div class=caution>⚠️ {_esc(str(r['주의']))}</div>"
            f"<div class=meta>🚶 {r['도보_분']}분 ({r['도보거리_m']}m)<br>"
            f"📍 {_esc(str(r['도로명주소']))}<br>{phone}</div>"
            f"<div class=links><a class=naver href='{_esc(str(r['네이버지도']))}' target=_blank>네이버지도</a></div>"
            "</div></div>"
        )
    note = ("<div class=note>※ 카드 상단 지도 = 파란 S(역) ↔ 빨간 핀(해당 식당) 위치(직선 근사, 지도=OSM/CARTO). "
            "A·동반명시 = 이름/카테고리/키워드에 애견·반려동물 동반 명시 · "
            "B·추정 = 야외·테라스 좌석 신호로 동반 가능성 추론(보장 아님). 🏅등록 = 공공 "
            "등록부(2026-03 반려동물 동반 가능 업소) 교차매칭. 내부 R&D.</div>")
    script = """<script>
(function(){
  var cards=[].slice.call(document.querySelectorAll('.card'));
  var btns=[].slice.call(document.querySelectorAll('.fbtn'));
  var countEl=document.getElementById('fcount');
  function active(group){
    return [].slice.call(document.querySelectorAll('.fgroup.'+group+' .fbtn.on'))
             .map(function(b){return b.getAttribute('data-val');});
  }
  function apply(){
    var grade=active('grade'), food=active('food'), shown=0;
    cards.forEach(function(c){
      var g=c.getAttribute('data-grade')||'', mj=c.getAttribute('data-major')||'';
      var okG = grade.length===0 || grade.indexOf(g)>=0;
      var okF = food.length===0 || food.indexOf(mj)>=0;
      var ok = okG && okF;
      c.classList.toggle('hide', !ok);
      if(ok) shown++;
    });
    countEl.textContent = '표시 '+shown+' / '+cards.length+'곳';
  }
  btns.forEach(function(b){ b.addEventListener('click', function(){ b.classList.toggle('on'); apply(); }); });
  document.getElementById('freset').addEventListener('click', function(){
    btns.forEach(function(b){b.classList.remove('on');}); apply();
  });
  apply();
})();
</script>"""
    return head + filterbar + "".join(cards) + "</div>" + note + script + "</body></html>"


FRESH_NOTE = ("> ⚠️ **신선도/변동성**: 반려동물 동반 정책은 변동이 잦습니다(업소 책임부담으로 동반 "
              "철회 빈번). 본 데이터는 실행일 기준 스냅샷이며 분기 갱신을 전제로 합니다. 견종·크기·"
              "내부동반/테라스한정·예약·추가요금은 방문 전 매장 확인 필수.\n")


def save(station, rows, na, radius_m, lat=None, lng=None, run_date="", registry_n=0):
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    run_date = run_date or kst_today()  # 리포트 작성일(최신성 판단 기준, CMPA-109)
    base = f"{station}_반려동물동반"
    n_reg = sum(1 for r in rows if str(r.get("등록부매칭", "")).startswith("등록"))
    # 식당별 미니 지도(역↔해당 식당)를 사진 밴드 자리에 표시(CMPA-102 패턴, corkage_free 참조).
    # mapshot 은 키 없이 OSM/CARTO 타일을 합성하는 범용 렌더러 → 재사용(import, 새 로직 0).
    # 타일 egress 차단 시 회색 폴백(graceful). 자가포함 data URI 라 외부 의존 0.
    if lat is not None and lng is not None:
        try:
            from pipelines.corkage_free.mapshot import render_pair, to_data_uri
            print(f"  식당별 역↔식당 미니지도 {len(rows)}장 생성 중…")
            for r in rows:
                try:
                    mp = render_pair(lat, lng, float(r["lat"]), float(r["lng"]), w=600, h=320)
                    r["_mapuri"] = to_data_uri(mp)
                except Exception:  # noqa: BLE001
                    r["_mapuri"] = None
        except Exception as e:  # noqa: BLE001
            print(f"  [warn] 지도 생성 실패(타일 차단 등): {e}", file=sys.stderr)
    # CSV(데이터셋) → data/pet-friendly/
    csv_path = os.path.join(OUT_DIR, base + ".csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    snapshot(csv_path)
    # MD(사람이 보는 리포트) → reports/pet-friendly/
    md_path = os.path.join(REPORT_DIR, base + ".md")
    reg_line = (f" · 🏅공공등록부 인증 {n_reg}곳" if registry_n
                else " · 🏅공공등록부 교차검증 **대기**(serviceKey+egress 게이트)")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {station} 반려동물 동반(펫프렌들리) 식당 — 도보 {radius_m}m 이내\n\n")
        if run_date:
            f.write(f"- **데이터 기준일(실행일)**: {run_date}\n")
        f.write(f"- **A·동반명시**: {na}곳 · **B·추정(확인필요)**: {len(rows)-na}곳{reg_line}\n")
        f.write("- ⚠️ **고지**: 공개 검색 신호 기반 *추정*(내부 R&D). 어떤 식당도 "
                "동반 가능을 보증하지 않습니다. 견종·크기·내부동반/테라스한정·예약·추가요금은 "
                "**반드시 방문 전 매장에 확인**하세요.\n")
        f.write(FRESH_NOTE + "\n")
        f.write(major_distribution_md(rows))
        f.write("| # | 등급 | 등록부 | 식당 | 대분류 | 카테고리 | 근거 | 도보 | 지도 |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            reg = "🏅등록" if str(r.get("등록부매칭", "")).startswith("등록") else "—"
            f.write(f"| {r['순위']} | {r['동반등급']} | {reg} | {r['식당명']} | {r['대분류']} | "
                    f"{r['카테고리']} | {r['근거']} | {r['도보_분']}분 | "
                    f"[네이버]({r['네이버지도']}) |\n")
        f.write("\n> 등급 A=동반 명시 신호 · B=야외·테라스 신호로 동반 가능성 추정. "
                "🏅등록=공공 등록부 교차매칭(권위 인증).\n")
    snapshot(md_path)
    # HTML 카드뷰 → reports/pet-friendly/
    html_path = os.path.join(REPORT_DIR, base + ".html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(_render_html(station, rows, na, radius_m, registry_n=registry_n,
                             run_date=run_date))
    snapshot(html_path)
    print(f"[저장] {csv_path}\n        {md_path}\n        {html_path}")
    return csv_path, md_path, html_path


def backfill(station, radius_m=700, run_date=""):
    """라이브 재크롤 없이 기존 CSV를 읽어 CSV/MD/HTML 을 재생성한다(halal.backfill·
    corkage CMPA-102 와 동일 패턴). 노란 고지 배너 제거 + 리포트 작성일 노출(CMPA-109)
    같은 렌더 변경을 라이브 의존 없이 반영하는 경로."""
    base = f"{station}_반려동물동반"
    csv_path = os.path.join(OUT_DIR, base + ".csv")
    if not os.path.exists(csv_path):
        print(f"  [skip] {csv_path} 없음", file=sys.stderr)
        return None
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    na = sum(1 for r in rows if str(r.get("동반등급", "")).startswith("A"))
    registry_n = sum(1 for r in rows if str(r.get("등록부매칭", "")).startswith("등록"))
    lat, lng = STATION_COORDS.get(station, (None, None))
    save(station, rows, na, radius_m, lat=lat, lng=lng,
         run_date=run_date, registry_n=registry_n)
    print(f"[backfill] {station}: {len(rows)}곳 (A·동반명시 {na} / B·추정 {len(rows)-na}) 재생성")
    return csv_path


def main():
    ap = argparse.ArgumentParser(
        description="지하철역 기준 반려동물 동반(펫프렌들리) 식당 탐색기 (CMPA-105)")
    ap.add_argument("--station", default="성수역")
    ap.add_argument("--radius", type=int, default=700)
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lng", type=float)
    ap.add_argument("--registry", help="공공 등록부 CSV(반려동물 동반 가능 업소) — 교차검증 배지")
    ap.add_argument("--run-date", default="", help="데이터 기준일 표기(YYYY-MM-DD)")
    ap.add_argument("--backfill", action="store_true",
                    help="라이브 재크롤 없이 기존 CSV 읽어 CSV/MD/HTML 재생성(CMPA-109)")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.backfill:
        backfill(a.station, a.radius, run_date=a.run_date)
        return
    if a.lat is not None and a.lng is not None:
        lat, lng = a.lat, a.lng
    elif a.station in STATION_COORDS:
        lat, lng = STATION_COORDS[a.station]
    else:
        print(f"[오류] '{a.station}' 좌표 미등록. --lat/--lng 주거나 STATION_COORDS 확장.",
              file=sys.stderr)
        sys.exit(2)
    rows, na = find(a.station, lat, lng, a.radius)
    registry_n = 0
    if a.registry:
        # 지연 import(선택적 의존) — 등록부 교차검증
        from pipelines.pet_friendly.registry_match import match_registry  # noqa: E402
        registry_n = match_registry(rows, a.registry)
        print(f"  공공 등록부 교차매칭: {sum(1 for r in rows if str(r['등록부매칭']).startswith('등록'))}곳 등록 "
              f"(등록부 {registry_n}건 로드)")
    if a.dry_run:
        for r in rows[:20]:
            print(f"  {r['순위']:>2} [{r['동반등급']}] {r['식당명']} | {r['대분류']} | "
                  f"{r['근거']} | {r['도보_분']}분")
        print(f"[dry-run] {len(rows)}곳 (저장 생략)")
        return
    save(a.station, rows, na, a.radius, lat=lat, lng=lng,
         run_date=a.run_date, registry_n=registry_n)


if __name__ == "__main__":
    main()
