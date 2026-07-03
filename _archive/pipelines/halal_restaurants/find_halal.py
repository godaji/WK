#!/usr/bin/env python3
"""
find_halal.py — 지하철역 기준 "무슬림(할랄) 식당" 탐색기 (CMPA-81, Phase 1)

CEO 요청(CMPA-81): 콜키지프리맵처럼 무슬림용 식당 맵을 만든다. ①"할랄"로 명시된 곳은 당연히,
②생선 등으로 먹을 수 있는데 할랄 표기가 없어 검색이 어려운 곳도 알려준다.
승인 피드백: **위스키 폴더와 분리한 새 폴더에서 진행**하고, 위스키쪽 코드는 복사해서 사용.

→ 이 모듈은 `pipelines/corkage_free/find_corkage_free.py` 의 검증된 엔진 조각
   (DiningCode isearch 호출 `dc_search`, haversine 도보거리, `classify_major` 대분류,
   `clean`, `STATION_COORDS`, 날짜 스냅샷)을 **복사(fork)** 해 와서, 콜키지/위스키 로직을
   **할랄 2-tier 분류**로 교체한 독립 파이프라인이다. (import 가 아니라 복사 — CEO 지시)

2-Tier 분류 (CMPA-81 설계, plan 문서):
  - Tier A (명시): 이름/카테고리/키워드에 할랄·무슬림·이슬람·halal·모스크 신호 → "할랄이라 나온 곳"
  - Tier B (추정·확인필요): 명시는 없지만 **할랄친화 cuisine**(인도/중동/터키/말레이/인니/파키스탄 등)
      또는 **해산물 업종**(생선·해물 — 다수 학파 할랄) 또는 **채식** 이고, 돼지·술 중심이 아닌 곳.
  - 제외: 돼지(삼겹·족발·보쌈·돈까스·순대·곱창류)·술 중심 매장, 신호 없는 곳.

정직성(종교 식이 — 콜키지맵보다 강한 고지):
  우리는 어떤 식당도 "할랄이다"라고 **단정하지 않는다**. 인증 범위·자바이하(이슬람식 도축)·
  숨은 돼지파생물(라드/젤라틴/육수)·조리용 알코올은 데이터로 확인 불가 → 전 행 `주의` 컬럼에
  "매장 확인 필수" 를 명시한다. Tier B 는 어디까지나 **추정 후보**.

용법:
  python3 pipelines/halal_restaurants/find_halal.py --station 이태원역 --radius 800
  python3 pipelines/halal_restaurants/find_halal.py --station 안산역 --radius 1000 --dry-run
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

# ── 엔진 조각 (corkage_free 에서 복사 — CEO 지시: import 금지, fork) ──────────
API = "https://im.diningcode.com/API/isearch/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
# 날짜 스냅샷(_runs/) — 가격·콜키지 제품라인과 동일한 공통 규약(CMPA-38/45). 정본을 쓴
# 직후 snapshot() 으로 각 디렉터리의 `_runs/` 에 실행일 사본을 남긴다(보드 폴더구조 통일).
from pipelines.common.dated import snapshot, kst_today  # noqa: E402
# 역↔식당 미니지도 렌더는 corkage 의 검증된 mapshot 유틸을 재사용한다(순수 렌더 헬퍼라
# fork 대상 아님 — CMPA-102: 사진 대신 위치 지도를 사진 밴드 전체로 표시).
from pipelines.corkage_free.mapshot import render_pair, to_data_uri  # noqa: E402
# 폴더 정리(보드 지시, corkage-free 와 동일): **데이터셋(csv)** 은 파이프라인 소비용이라
# `data/halal-restaurants/` 에, **사람이 보는 리포트(md/html)** 는 `reports/halal-restaurants/` 에 둔다.
OUT_DIR = os.path.join(ROOT, "data", "halal-restaurants")
REPORT_DIR = os.path.join(ROOT, "reports", "halal-restaurants")

_EM = re.compile(r"</?em>", re.I)


def clean(s):
    """검색 하이라이트(<em>) 제거."""
    return _EM.sub("", s or "").strip()


def row_rid(r):
    """식당 고유 ID(rid). 신규 CSV는 `식당ID`(rid 단독), 구 CSV는 `다이닝코드링크`(URL)
    둘 다 허용해 무중단 마이그레이션(외부 소스 브랜드 흔적 제거, CMPA-102)."""
    v = (r.get("식당ID") or r.get("다이닝코드링크") or "").strip()
    return v.split("rid=")[-1].strip()


# 내장 역 좌표(WGS84). 콜키지맵 사전 + 무슬림 핫스팟 역 추가(CMPA-81).
STATION_COORDS = {
    "이태원역": (37.534508, 126.994401),   # 6호선, 서울중앙성원(모스크) 인접 — 할랄 밀도 최고
    "안산역": (37.321787, 126.788218),     # 1호선, 다문화/외국인 밀집(원곡동 인근)
    "강남역": (37.497942, 127.027621),
    "홍대입구역": (37.557527, 126.924191),
    "서울역": (37.554648, 126.972559),
    "동대문역사문화공원역": (37.565178, 127.007896),
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
    """DiningCode isearch 호출 → poi list 반환. (corkage_free 에서 복사)"""
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


# ── 대분류(major) — corkage_free.classify_major 복사 + 할랄친화 에스닉 bucket 추가 ──
# 콜키지맵 7종에 '중동·인도(할랄친화)' 버킷을 추가한다(케밥/중동/인도가 콜키지맵에선
# 전부 '한식·기타'로 떨어지는 문제를 해소 — plan §5).
MAJOR_UNCLASSIFIED = "기타"
MAJOR_RULES = [
    ("중동·인도(할랄친화)", ["인도음식", "중동", "케밥", "kebab", "터키", "튀르키예", "아랍",
                       "할랄", "halal", "팔라펠", "비리야니", "탄두리", "사모사", "난",
                       "파키스탄", "방글라", "우즈벡", "카자흐", "위구르", "샤와르마",
                       "말레이", "인도네시아", "쿠스쿠스", "두바이", "페르시아"]),
    ("물고기·해산물", ["횟집", "생선회", "생선구이", "숙성회", "물회", "방어", "참치",
                  "복어", "복국", "아구", "문어", "매운탕", "지리", "백합", "고등어",
                  "해물", "해산물", "조개", "광어", "낙지", "대게", "장어", "오징어",
                  "새우", "굴요리", "멍게", "해물탕", "조개구이", "전복", "꽃게"]),
    ("채식", ["채식", "비건", "vegan", "사찰음식", "베지테리언", "샐러드"]),
    ("바·주류", ["와인바", "칵테일", "수제맥주", "샴페인", "위스키바", "맥주바", "술집",
              "이자카야", "포차", "호프", "펍", "pub"]),
    ("웨스턴(양식)", ["스테이크", "파스타", "피자", "양식", "레스토랑", "비스트로",
                  "브런치", "뉴욕", "화덕", "리조또", "스파게티", "파니니", "웨스턴",
                  "버거", "샌드위치", "랩샌드위치"]),
    ("중식", ["훠궈", "중식", "중국", "짜장", "짬뽕", "양꼬치", "마라", "딤섬", "양장피"]),
    ("고기(돼지위험)", ["삼겹", "족발", "보쌈", "돈까스", "돈가스", "순대", "수육", "곱창",
                   "막창", "대창", "포크", "돼지", "한돈", "흑돼지", "정육식당",
                   "고기무한리필", "한우", "소고기", "갈비", "양고기", "양갈비", "닭"]),
    ("일식", ["이자카야", "사시미", "스시", "오마카세", "라멘", "사케", "일식", "우동",
            "돈카츠", "텐동", "초밥", "덮밥집"]),
    ("한식·기타", ["국밥", "냉면", "찌개", "백반", "한정식", "비빔밥", "국수", "쌀국수",
                "분식", "떡볶이", "한식", "베트남", "쌀국수"]),
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


# ── 할랄 2-tier 분류기 (CMPA-81 핵심 로직 · CMPA-86 오탐 정제) ────────────────
# 명시 신호: 이름/카테고리/키워드에 등장하면 Tier A.
EXPLICIT_RX = re.compile(r"할랄|halal|무슬림|muslim|이슬람|islam|모스크|mosque|清真", re.I)

# 할랄친화 cuisine 신호를 **강(STRONG)/약(WEAK)** 으로 분리(CMPA-86 item 3).
#   STRONG = 그 자체로 에스닉 cuisine 을 특정하는 신뢰 토큰. cuisine 필드(이름·카테고리)에
#            등장하면 노이즈 컨텍스트와 무관하게 Tier B 후보로 인정.
#   WEAK   = 메뉴명에도 흔히 섞여 다른 요리권에서 오탐을 내는 토큰(커리/카레/난).
#            노이즈 컨텍스트(디저트·태국·일식 등)가 없을 때만 인정.
# 핵심 변경: cuisine 매칭을 **이름+카테고리(catname)** 에 한정한다. 기존엔 메뉴 키워드까지
# 포함한 hay 전체에 매칭해 '와플대학'이 메뉴 '두바이초콜릿'의 `두바이` 에 걸리는 오탐이 났다
# (plan §5 / README 알려진 오탐). '두바이' 토큰은 디저트 트렌드 노이즈라 목록에서 제거.
STRONG_CUISINE = ["인도", "케밥", "kebab", "터키", "튀르", "튀르키예", "아랍", "중동",
                  "팔라펠", "비리야니", "탄두리", "사모사", "파키스탄", "방글라", "우즈베",
                  "카자흐", "중앙아시아", "위구르", "샤와르마", "말레이", "인도네시아",
                  "페르시아", "할랄"]
# '난'(naan)은 1음절이라 식당명/메뉴(난포 등)에 과매칭 → WEAK 에서 제외(실데이터 오탐).
WEAK_CUISINE = ["커리", "카레"]

# 노이즈 컨텍스트: 이 신호가 있으면 WEAK cuisine·해산물·채식 추정을 무효화한다.
#   - 디저트/카페: '두바이초콜릿' 류 메뉴 트렌드(에스닉 cuisine 아님)
#   - 태국/타이: 피시소스·돼지 사용 가능 → 커리 매칭돼도 할랄친화로 보기 어려움(plan §5)
#   - 일식 카레/돈카츠/라멘: 일본식 카레는 할랄 무관
NOISE_RX = re.compile(r"와플|디저트|초콜릿|베이커리|제과|빵집|카페|빙수|케이크|도넛|"
                      r"아이스크림|마카롱|쿠키|태국|타이|팟타이|쏨땀|일식|돈카츠|돈가스|"
                      r"라멘|스시|초밥|텐동|규동|가라아게|가라아케|이자카야", re.I)

# 하드 제외: 돼지/돼지부산물·술 중심. 이 신호가 있으면 A/B 어디에도 넣지 않는다.
# (naive '회' 매칭이 고기뷔페를 B로 넣던 POC 오탐을 차단 — plan §5)
PORK_RX = re.compile(r"삼겹|족발|보쌈|돈까스|돈가스|순대|수육|곱창|막창|대창|포크|돼지|"
                     r"한돈|흑돼지|고기무한리필|정육식당|부대찌개|스팸|소시지|런천", re.I)
BOOZE_RX = re.compile(r"이자카야|와인바|포차|호프집|맥주바|술집|칵테일바|위스키바", re.I)


def halal_tier(nm, cat, kw):
    """(등급, 근거) 반환. 등급 ∈ {'A','B',''}. ''=제외.

    nm  = 식당명, cat = DiningCode 원문 카테고리, kw = 메뉴/키워드 합본.
    cuisine 신호는 **이름+카테고리(catname)** 에서만 찾는다(메뉴 키워드 오탐 차단, CMPA-86).
    명시(Tier A)·돼지·술 신호는 메뉴 키워드까지 본다(놓치면 위험한 쪽이라 보수적).
    """
    catname = f"{nm} {cat}"
    hay = f"{nm} {cat} {kw}"
    major = classify_major(cat)
    pork = bool(PORK_RX.search(hay))
    booze = bool(BOOZE_RX.search(hay))
    explicit = bool(EXPLICIT_RX.search(hay))

    # 명시 신호가 있으면 Tier A (돼지·술 토큰이 함께 있으면 모순 → 제외하여 안전).
    if explicit and not pork:
        return "A", "명시 할랄/무슬림 신호"
    # 이하 Tier B 후보 — 돼지·술 중심이면 제외.
    if pork or booze:
        return "", ""
    noise = bool(NOISE_RX.search(hay))
    # STRONG cuisine: 신뢰 토큰 → 노이즈와 무관하게 인정(단 이름/카테고리에 한함).
    strong = [w for w in STRONG_CUISINE if w in catname]
    if strong:
        return "B", f"할랄친화 cuisine({'/'.join(sorted(set(strong))[:3])})"
    # WEAK cuisine·해산물·채식: 노이즈 컨텍스트가 있으면 추정하지 않는다(오탐 차단).
    if noise:
        return "", ""
    weak = [w for w in WEAK_CUISINE if w in catname]
    if weak:
        return "B", f"할랄친화 cuisine({'/'.join(sorted(set(weak))[:3])})"
    if major == "물고기·해산물":
        return "B", "해산물·생선 업종(다수 학파 할랄)"
    if major == "채식":
        return "B", "채식·비건(육류 없음)"
    return "", ""


# 출처 = 데이터 권위 구분(CMPA-86 item 1). "공개검색 추정" = 공개 검색 신호 기반 *추정*(내부 R&D),
# 공공 오픈데이터 ingest 행은 발급기관명(예: "한국관광공사")이 들어가 **Tier A 권위·재게시 가능**.
# CMPA-102: 외부 소스 브랜드 흔적 제거 — 다코점수→평판점수, 다이닝코드링크→식당ID(rid 단독).
CSV_FIELDS = ["순위", "할랄등급", "식당명", "카테고리", "대분류", "근거", "주의", "출처",
              "도로명주소", "전화", "도보거리_m", "도보_분", "평판점수", "user_score",
              "리뷰수", "대표사진", "네이버지도", "식당ID", "lat", "lng"]

QUERY_SUFFIXES = ["할랄", "무슬림", "이슬람", "halal", "케밥", "인도음식", "터키음식",
                  "중동음식", "해산물", "생선구이", "채식"]


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
        tier, reason = halal_tier(nm, cat, kw)
        if not tier:
            n_excl += 1
            continue
        if tier == "A":
            grade = "A·명시할랄"
            caution = "표기 신뢰. 단 인증 범위·갱신·자바이하 도축은 매장 확인 권장"
        else:
            grade = "B·추정(확인필요)"
            caution = "추정 후보 — 돼지파생물(라드/젤라틴/육수)·조리용 알코올·도축방식 매장 확인 필수"
        rows.append({
            "할랄등급": grade,
            "식당명": nm,
            "카테고리": cat,
            "대분류": classify_major(cat),
            "근거": reason,
            "주의": caution,
            "출처": "공개검색 추정",
            "도로명주소": clean(p.get("road_addr")) or clean(p.get("addr")),
            "전화": p.get("phone", ""),
            "도보거리_m": round(dist),
            "도보_분": round(dist / 67),
            "평판점수": p.get("score", ""),  # 인기·평판 종합점수(0–100). 추천순 정렬 2차 키
            "user_score": p.get("user_score", ""),
            "리뷰수": p.get("review_cnt", ""),
            "대표사진": "",  # CMPA-102: 외부 소스 사진 미저장(밴드는 역↔식당 위치 지도로 대체)
            "네이버지도": naver_map_link(nm),
            "식당ID": rid,  # 내부 조인 키(외부 프로필 URL 미저장, CMPA-102)
            "lat": plat, "lng": plng,
            "_t": 0 if tier == "A" else 1,
        })
    # 정렬: Tier A 먼저 → 평판점수 desc → 가까운 순
    def _score(r):
        try:
            return float(r.get("평판점수") or r.get("다코점수") or 0)  # 구 CSV 폴백
        except (TypeError, ValueError):
            return 0.0
    rows.sort(key=lambda r: (r["_t"], -_score(r), r["도보거리_m"]))
    na = sum(1 for r in rows if r["_t"] == 0)
    for i, r in enumerate(rows, 1):
        r["순위"] = i
        r.pop("_t", None)
    print(f"  결과: 명시 A={na} · 추정 B={len(rows)-na} · 제외 {n_excl}곳")
    return rows, na


def major_distribution_md(rows):
    order = ["중동·인도(할랄친화)", "물고기·해산물", "채식", "웨스턴(양식)",
             "중식", "일식", "한식·기타", "기타"]
    cnt = {b: 0 for b in order}
    for r in rows:
        cnt[r["대분류"]] = cnt.get(r["대분류"], 0) + 1
    total = max(1, len(rows))
    out = ["### 대분류 분포\n\n", "| 대분류 | 곳 | 비중 |\n", "|---|---:|---:|\n"]
    for b in order:
        if cnt.get(b):
            out.append(f"| {b} | {cnt[b]} | {round(100*cnt[b]/total)}% |\n")
    out.append(f"| **합계** | **{len(rows)}** | 100% |\n\n")
    return "".join(out)


# ── HTML 카드뷰 (CMPA-86 item 2) — corkage find_corkage_free 라이터를 fork·적응 ──
# 콜키지맵 대비 차이: 위스키/콜키지/비용 차원 제거, 대신 **할랄등급(A/B) 배지·근거·주의**
# 를 1급 요소로 올린다. 자가포함 임베딩(base64) 대신 사진/지도 URL 을 직접 참조해
# 의존성 0(내부 R&D 미리보기용).
# CMPA-109: 상단 노란색 면책 고지 배너 제거 → 대신 헤더에 **리포트 작성일**을 노출해
# 사용자가 최신성을 직접 판단하도록 한다(고지 문구는 각 카드 ⚠️주의·MD 리포트에 유지).
MAJOR_ORDER_HTML = ["중동·인도(할랄친화)", "물고기·해산물", "채식", "웨스턴(양식)",
                    "중식", "일식", "한식·기타", "기타"]


def _render_html(station, rows, na, radius_m, run_date=""):
    nb = len(rows) - na
    head = (
        "<!doctype html><html lang=ko><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{_esc(station)} 무슬림(할랄) 식당</title><style>"
        "body{font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;margin:0;background:#f6f6f8;color:#222}"
        "header{padding:18px 16px;background:#0f5132;color:#fff}"
        "header h1{margin:0 0 4px;font-size:20px}header p{margin:0;font-size:13px;opacity:.9}"
        # CMPA-109: 리포트 작성일(최신성 판단 기준) — 노란 고지 배너 대체
        ".rundate{margin:7px 0 0;font-size:12px;opacity:.85}"
        ".filterbar{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid #e6e6ea;"
        "padding:10px 16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}"
        ".fgroup{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:4px 0}"
        ".fglabel{font-size:12px;font-weight:700;color:#555;min-width:64px}"
        ".fbtn{font-size:12px;border:1px solid #ccc;background:#fff;color:#333;border-radius:14px;"
        "padding:5px 11px;cursor:pointer;line-height:1;user-select:none}"
        ".fbtn:hover{border-color:#999}"
        ".fgroup.grade .fbtn.on{background:#0f5132;border-color:#0f5132;color:#fff}"
        ".fgroup.food .fbtn.on{background:#1b1b2b;border-color:#1b1b2b;color:#fff}"
        ".fmeta{font-size:12px;color:#666;margin-top:6px}"
        ".fmeta .freset{color:#0f5132;cursor:pointer;text-decoration:underline;margin-left:8px}"
        ".wrap{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;padding:16px}"
        ".card{background:#fff;border-radius:12px;overflow:hidden;box-shadow:0 1px 4px rgba(0,0,0,.08);"
        "display:flex;flex-direction:column}"
        ".card.ga{outline:2px solid #0f5132}"
        ".card.hide{display:none}"
        ".photo{position:relative;width:100%;height:150px;background:#eee;overflow:hidden}"
        ".thumb{width:100%;height:150px;object-fit:cover;display:block}"
        # 역↔식당 위치 지도를 사진 밴드 전체로 표시(CMPA-102): 외부 사진 대신 위치 지도.
        ".bandmap{width:100%;height:150px;object-fit:cover;display:block;background:#eee}"
        ".rank{position:absolute;left:7px;top:7px;background:rgba(20,20,30,.78);color:#fff;"
        "font-size:12px;font-weight:700;padding:3px 9px;border-radius:13px}"
        ".grade{position:absolute;right:7px;top:7px;font-size:12px;font-weight:700;"
        "padding:3px 9px;border-radius:13px;box-shadow:0 1px 4px rgba(0,0,0,.4)}"
        ".grade.A{background:#0f5132;color:#fff}.grade.B{background:#fd7e14;color:#fff}"
        ".body{padding:12px 14px;flex:1;display:flex;flex-direction:column;gap:6px}"
        ".nm{font-size:16px;font-weight:700}.cat{font-size:12px;color:#666}"
        ".major{display:inline-block;background:#0f5132;color:#fff;font-size:11px;"
        "font-weight:700;border-radius:9px;padding:1px 7px;margin-right:4px}"
        ".reason{font-size:12px;color:#0f5132;background:#e7f1ec;border-radius:8px;padding:4px 9px;"
        "align-self:flex-start}"
        ".caution{font-size:11.5px;color:#842029;background:#fbeaec;border-radius:8px;padding:5px 9px;"
        "line-height:1.45}"
        ".meta{font-size:12px;color:#444;line-height:1.6}"
        ".links{margin-top:auto;display:flex;gap:8px;padding-top:8px}"
        ".links a{flex:1;text-align:center;font-size:13px;text-decoration:none;padding:8px 0;border-radius:8px}"
        ".naver{background:#03c75a;color:#fff}"
        ".note{font-size:12px;color:#888;padding:0 16px 24px}"
        "</style></head><body>"
        f"<header><h1>🕌 {_esc(station)} 무슬림(할랄) 식당</h1>"
        f"<p>도보 {radius_m}m(약 {round(radius_m/67)}분) 이내 · "
        f"A·명시 {na}곳 · B·추정 {nb}곳 · 출처 공개검색 추정 · 거리=직선 근사</p>"
        + (f"<p class=rundate>📅 리포트 작성일 {_esc(run_date)} — 최신성은 이 날짜를 "
           "기준으로 판단하세요</p>" if run_date else "")
        + "</header>"
    )
    # 필터 바: 할랄등급(A/B) × 대분류(존재하는 값만, 곳수 표기) AND 필터
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

    grade_items = [(g, ("A·명시" if g == "A" else "B·추정"), grade_cnt[g])
                   for g in ("A", "B") if grade_cnt[g]]
    filterbar = (
        "<div class=filterbar>"
        "<div class='fgroup grade'><span class=fglabel>할랄등급</span>"
        + _fbtns(grade_items) + "</div>"
        "<div class='fgroup food'><span class=fglabel>음식 종류</span>"
        + _fbtns([(b, b, c) for b, c in food_btns]) + "</div>"
        "<div class=fmeta>버튼을 눌러 필터링 — <b>등급 × 음식 = AND</b>, 같은 묶음 안에서는 OR. "
        "<span id=fcount></span><span class=freset id=freset>전체 해제</span></div>"
        "</div><div class=wrap>"
    )
    cards = []
    for r in rows:
        g = "A" if str(r["할랄등급"]).startswith("A") else "B"
        # CMPA-102: 외부 사진 제거 → 역↔식당 위치 지도를 밴드 전체로 표시(지도 없으면 회색 폴백).
        img = (f"<img class=bandmap loading=lazy src='{r['_mapuri']}' "
               f"alt='{_esc(station)}↔{_esc(str(r['식당명']))} 위치 지도'>"
               if r.get("_mapuri") else "<div class=thumb></div>")
        phone = f"☎ {_esc(str(r['전화']))}<br>" if r.get("전화") else ""
        major_v = r.get("대분류", "") or MAJOR_UNCLASSIFIED
        cards.append(
            f"<div class='card g{g}' data-grade=\"{g}\" data-major=\"{_esc(major_v)}\">"
            f"<div class=photo>{img}<span class=rank>{r['순위']}위</span>"
            f"<span class='grade {g}'>{'A·명시' if g=='A' else 'B·추정'}</span></div>"
            f"<div class=body>"
            f"<div class=nm>{_esc(str(r['식당명']))}</div>"
            f"<div class=cat><span class=major>{_esc(major_v)}</span> {_esc(str(r['카테고리']))}</div>"
            f"<div class=reason>{_esc(str(r['근거']))}</div>"
            f"<div class=caution>⚠️ {_esc(str(r['주의']))}</div>"
            f"<div class=meta>🚶 {r['도보_분']}분 ({r['도보거리_m']}m)<br>"
            f"📍 {_esc(str(r['도로명주소']))}<br>{phone}</div>"
            f"<div class=links><a class=naver href='{_esc(str(r['네이버지도']))}' target=_blank>네이버지도</a></div>"
            "</div></div>"
        )
    note = ("<div class=note>※ 카드 상단 지도 = 파란 S(역) ↔ 빨간 핀(해당 식당) 위치(직선 근사). "
            "A·명시 = 이름/카테고리에 할랄·무슬림 명시(그래도 인증범위·갱신·도축은 확인 권장) · "
            "B·추정 = 할랄친화 cuisine 또는 해산물·채식 업종 추론(할랄 보증 아님). 지도=OSM/CARTO.</div>")
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


def _render_minimaps(slat, slng, rows):
    """각 행에 역↔식당 미니지도 data URI(_mapuri)를 채운다(CMPA-102, 사진 밴드 대체).
    좌표 미등록·타일 차단 시 None → 카드는 회색 밴드로 폴백."""
    if slat is None or slng is None:
        for r in rows:
            r["_mapuri"] = None
        print("  [warn] 역 좌표 미등록 → 미니지도 생략(회색 밴드)", file=sys.stderr)
        return
    try:
        for r in rows:
            try:
                mp = render_pair(slat, slng, float(r["lat"]), float(r["lng"]), w=600, h=320)
                r["_mapuri"] = to_data_uri(mp)
            except Exception:  # noqa: BLE001
                r["_mapuri"] = None
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 지도 생성 실패(타일 차단 등): {e}", file=sys.stderr)


def save(station, rows, na, radius_m, lat, lng, run_date=""):
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    run_date = run_date or kst_today()  # 리포트 작성일(최신성 판단 기준, CMPA-109)
    base = f"{station}_무슬림식당"
    # CSV(데이터셋) → data/halal-restaurants/
    csv_path = os.path.join(OUT_DIR, base + ".csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    snapshot(csv_path)
    # MD(사람이 보는 리포트) → reports/halal-restaurants/
    md_path = os.path.join(REPORT_DIR, base + ".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {station} 무슬림(할랄) 식당 — 도보 {radius_m}m 이내\n\n")
        f.write(f"- **리포트 작성일**: {run_date}\n")
        f.write(f"- **A·명시 할랄**: {na}곳 · **B·추정(확인필요)**: {len(rows)-na}곳\n")
        f.write("- ⚠️ **고지**: 본 목록은 공개 검색 신호 기반 *추정*입니다. "
                "어떤 식당도 할랄임을 보증하지 않습니다. 돼지 파생물·조리용 알코올·"
                "이슬람식 도축(자바이하)은 **반드시 매장에 확인**하세요. "
                "정식 인증은 KMF(한국이슬람교중앙회) 등 인증기관 기준을 따릅니다.\n\n")
        f.write(major_distribution_md(rows))
        f.write("| # | 등급 | 식당 | 대분류 | 카테고리 | 근거 | 도보 | 지도 |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['순위']} | {r['할랄등급']} | {r['식당명']} | {r['대분류']} | "
                    f"{r['카테고리']} | {r['근거']} | {r['도보_분']}분 | "
                    f"[네이버]({r['네이버지도']}) |\n")
        f.write("\n> 등급 A=이름/카테고리에 할랄·무슬림 명시 · B=할랄친화 cuisine 또는 해산물·채식 업종 추정.\n")
    snapshot(md_path)
    # 역↔식당 미니지도(사진 밴드 대체, CMPA-102) — 좌표로 렌더 후 카드에 임베드.
    _render_minimaps(lat, lng, rows)
    # HTML 카드뷰 (CMPA-86 item 2) → reports/halal-restaurants/
    html_path = os.path.join(REPORT_DIR, base + ".html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(_render_html(station, rows, na, radius_m, run_date=run_date))
    snapshot(html_path)
    print(f"[저장] {csv_path}\n        {md_path}\n        {html_path}")
    return csv_path, md_path, html_path


def backfill(station, radius_m=800):
    """라이브 재크롤 없이 기존 CSV를 읽어 외부 소스 브랜드 흔적을 제거하고(식당ID·평판점수·
    출처 디브랜딩·사진 비움) CSV/MD/HTML 을 재생성한다. 사진 밴드는 역↔식당 위치 지도로
    대체(CMPA-102). corkage find_corkage_free.backfill 과 동일 패턴."""
    base = f"{station}_무슬림식당"
    csv_path = os.path.join(OUT_DIR, base + ".csv")
    if not os.path.exists(csv_path):
        print(f"  [skip] {csv_path} 없음", file=sys.stderr)
        return None
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        # CMPA-102 마이그레이션: 외부 소스 브랜드 흔적 제거(값·등급·순위는 그대로 유지).
        r["식당ID"] = row_rid(r)
        r["대표사진"] = ""
        if r.get("평판점수") in (None, "") and r.get("다코점수") not in (None, ""):
            r["평판점수"] = r.get("다코점수")
        if (r.get("출처") or "").strip() == "DiningCode":
            r["출처"] = "공개검색 추정"
    na = sum(1 for r in rows if str(r.get("할랄등급", "")).startswith("A"))
    lat, lng = STATION_COORDS.get(station, (None, None))
    save(station, rows, na, radius_m, lat, lng)
    print(f"[backfill] {station}: {len(rows)}곳 (A·명시 {na} / B·추정 {len(rows)-na}) 재생성")
    return csv_path


def main():
    ap = argparse.ArgumentParser(description="지하철역 기준 무슬림(할랄) 식당 탐색기 (CMPA-81)")
    ap.add_argument("--station", default="이태원역")
    ap.add_argument("--radius", type=int, default=800)
    ap.add_argument("--lat", type=float)
    ap.add_argument("--lng", type=float)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backfill", action="store_true",
                    help="라이브 재크롤 없이 기존 CSV 흔적 제거 + 위치지도로 재생성(CMPA-102)")
    a = ap.parse_args()
    if a.backfill:
        backfill(a.station, a.radius)
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
    if a.dry_run:
        for r in rows[:20]:
            print(f"  {r['순위']:>2} [{r['할랄등급']}] {r['식당명']} | {r['대분류']} | "
                  f"{r['근거']} | {r['도보_분']}분")
        print(f"[dry-run] {len(rows)}곳 (저장 생략)")
        return
    save(a.station, rows, na, a.radius, lat, lng)


if __name__ == "__main__":
    main()
