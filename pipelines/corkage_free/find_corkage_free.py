#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
find_corkage_free.py — 지하철역 기준 "위스키 콜키지프리" 식당 탐색기 (CMPA-55, POC)

목적
----
CEO 요청: "지하철역을 검색하면 그 역에서 걸어갈 수 있을만한 위스키 콜키지프리 식당을
찾아주는 기능". 우리 핵심 자산(가성비 위스키)과 콜키지프리 식당을 잇는 송객(送客) 후크.
1차 대상 = '강남역'.

왜 이 소스인가 (DiningCode)
---------------------------
- 네이버 지도/플레이스 내부 API는 봇 차단(HTTP 429)으로 키 없이 수집 불가(실측).
- 네이버 지역검색 Open API / 카카오 로컬 API 는 클라이언트 키 발급 필요(미보유).
- DiningCode(다이닝코드)는 키 없이 호출 가능한 내부 검색 API 를 제공하고,
  "{역명} 콜키지프리" 같은 자연어 질의를 빅데이터 랭킹으로 정리해 둔다.
  실측: POST https://im.diningcode.com/API/isearch/  → 식당별
  name/road_addr/phone/lat,lng/category/score/리뷰/키워드태그(콜키지프리 mark=1) 반환.
  → 좌표가 있어 역에서의 도보거리 계산이 가능하다.

파이프라인
----------
1) 역 좌표(STATION_COORDS)에서 앵커 좌표를 잡는다.
2) DiningCode isearch 를 콜키지 질의 변형으로 호출(콜키지프리/콜키지무료/위스키 콜키지),
   v_rid 기준 dedup.
3) 각 식당까지 haversine 도보거리(m)·도보분(min) 계산, walk_radius_m 이내만 남긴다.
4) 위스키 신호 점수: 키워드 태그·리뷰 본문의 위스키/하이볼/양주/싱글몰트/스카치/버번 언급,
   '위스키 콜키지' 질의에 등장했는지 여부로 가산.
5) CSV + 마크다운 표로 저장. (콜키지 정책 세부 — 주종 제한/병수/요금 — 는 매장 확인 필요:
   confidence 컬럼에 한계 명시.)

용법
----
  python3 pipelines/corkage_free/find_corkage_free.py                 # 강남역, 800m
  python3 pipelines/corkage_free/find_corkage_free.py --station 강남역 --radius 800
  python3 pipelines/corkage_free/find_corkage_free.py --whisky-only   # 위스키 신호 있는 곳만
  python3 pipelines/corkage_free/find_corkage_free.py --dry-run       # 저장 안 함, 콘솔만

정직성 노트
-----------
- "콜키지프리" 태그가 곧 "위스키 반입 무료"를 보장하지 않는다(와인 한정 매장 다수).
  whisky_signal 은 리뷰/키워드에 위스키류 언급이 있는지의 *간접 신호*다 → confidence 참고.
- 도보거리는 직선(haversine) 기준 근사. 실제 도보경로는 더 길 수 있다.
- 역 좌표는 내장 사전(STATION_COORDS). 미등록 역은 --lat/--lng 로 직접 주거나
  사전을 확장한다(프로덕션: 공공데이터 '서울교통공사 역사 좌표' CSV 권장).
"""
import argparse
import csv
import json
import math
import os
import re
import sys
import time

import requests
from html import escape as _esc
from urllib.parse import quote as _quote

_EM = re.compile(r"</?em>", re.I)


def clean(s):
    """DiningCode 검색 하이라이트(<em>) 제거."""
    return _EM.sub("", s or "").strip()

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from pipelines.common.dated import snapshot, kst_today  # noqa: E402
# CMPA-67: 추천 위스키 종류 뱃지 — 분류 체계는 CMPA-61 엔진을 그대로 재사용(복제 금지).
from pipelines.corkage_free.pair_whisky import (  # noqa: E402
    classify as _pw_classify, styles_for as _pw_styles_for,
)


def pair_style_for_category(category):
    """식당 카테고리 → 추천 위스키 종류 뱃지 데이터(1순위+대안 둘 다).

    CMPA-61 `pair_whisky.classify`→`styles_for` 결과를 그대로 사용한다(분류 체계 복제 금지).
    `styles_for` 는 `(1순위 종류, 대안 종류, 근거)` 를 반환하므로 **두 종류 모두** 뱃지로 노출한다
    (보드 요청: 추천이 여러 개면 뱃지도 여러 개). 뱃지 표시는 괄호 앞부분만 쓴 짧은 라벨
    (`재패니즈(하이볼)`→`재패니즈`, `코스탈(해안 몰트)`→`코스탈`).
    CSV/downstream 에는 전체 종류명을 보존한다.

    반환: `(p_short, p_full, a_short, a_full, reason)`
      - p_*: 1순위 종류(짧은/전체)  · a_*: 대안 종류(짧은/전체)  · reason: 근거 한 줄
    """
    prof = _pw_classify(category or "")
    pair_style, alt_style, reason = _pw_styles_for(prof["name"])
    short = lambda s: s.split("(")[0].strip()
    return short(pair_style), pair_style, short(alt_style), alt_style, reason

API = "https://im.diningcode.com/API/isearch/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
OUT_DIR = os.path.join(ROOT, "data", "corkage-free")
# CMPA-88 보드 지시(폴더 정리): 사람이 보는 리포트 산출물(md/html/pdf)은 reports/ 하위로.
# 데이터셋(csv·인당비용·매니페스트)은 파이프라인이 소비하므로 data/corkage-free 에 둔다.
REPORT_DIR = os.path.join(ROOT, "reports", "corkage-free")

# 내장 역 좌표(WGS84). 프로덕션은 공공데이터 역사 좌표 CSV 로 대체/확장 권장.
STATION_COORDS = {
    "강남역": (37.497942, 127.027621),
    "합정역": (37.549463, 126.913739),
    "역삼역": (37.500622, 127.036456),
    "선릉역": (37.504503, 127.049008),
    "삼성역": (37.508844, 127.063160),
    "서울역": (37.554648, 126.972559),
    "홍대입구역": (37.557527, 126.924191),
    "성수역": (37.544581, 127.055961),
    "잠실역": (37.513302, 127.100165),
    "여의도역": (37.521620, 126.924191),
    "판교역": (37.394761, 127.111217),
    "마포역": (37.539669, 126.945905),  # 5호선 마포역 (CMPA-79)
    "신논현역": (37.504658, 127.025127),  # 9호선·신분당선 신논현역, 강남역 북쪽 강남대로 (CMPA-100)
    "명동역": (37.560989, 126.986325),  # 4호선 명동역 (CMPA-120/121)
}

# 위스키 반입 신호 토큰(리뷰/키워드/카테고리에서 탐지)
WHISKY_TOKENS = ["위스키", "위스키바", "하이볼", "양주", "싱글몰트", "스카치", "버번",
                 "발베니", "맥캘란", "글렌피딕", "야마자키", "온더록", "니트"]

# ── 대분류(major category) 분류기 (CMPA-65) ───────────────────────────────
# CEO 결정 taxonomy 7개. DiningCode 원문 카테고리(약 100종 free-text)를 큰 묶음으로
# 정리한다. 결정론적 키워드 매칭 — 같은 입력은 항상 같은 버킷.
#
# 규칙
#   1) 카테고리를 콤마로 쪼갠 뒤, **첫 토큰(대표 토큰)** 을 우선순위대로 매칭 →
#      매칭되면 그 버킷. (예: "한우, 와인" → 첫 토큰 '한우' = 고기, '와인'에 안 끌림)
#   2) 첫 토큰이 어느 버킷에도 안 걸리면 **전체 문자열** 을 같은 우선순위로 재매칭.
#      (예: "퓨전, 뉴욕스타일레스토랑" → 첫 토큰 '퓨전' 미매칭 → 전체에서 '레스토랑'=웨스턴)
#   3) 그래도 없으면 '한식·기타'(폴백).
#
# 우선순위(엣지케이스 해소): 바·주류 > 웨스턴 > 중식 > 물고기·해산물 > 고기 >
#   일식 > 한식·기타(특정 토픽).  CEO 지정 엣지: 스테이크→웨스턴(고기 아님),
#   양꼬치→중식(양갈비/양고기는 고기), 와인바→바·주류(레스토랑보다 우선),
#   한우오마카세→고기(오마카세에 끌려가지 않게 고기를 일식보다 위에).
MAJOR_UNCLASSIFIED = "한식·기타"
# (버킷명, [키워드…]) — 위에서부터 먼저 매칭. 부분 문자열(substring) 매칭.
MAJOR_RULES = [
    ("바·주류", ["와인바", "칵테일", "수제맥주", "샴페인", "위스키바", "맥주바", "술집"]),
    ("웨스턴(양식)", ["스테이크", "파스타", "피자", "양식", "레스토랑", "비스트로",
                  "브런치", "뉴욕", "호주", "화덕", "뇨끼", "라자냐", "투움바",
                  "리조또", "스파게티", "파니니", "라따뚜이", "웨스턴"]),
    ("중식", ["훠궈", "중식", "중국", "짜장", "짬뽕", "양꼬치", "마라", "어향",
            "동파육", "딤섬", "양장피", "마파"]),
    ("물고기·해산물", ["횟집", "생선회", "생선구이", "숙성회", "물회", "방어", "참치",
                  "복어", "복국", "아구", "문어", "매운탕", "지리", "백합", "고등어",
                  "해물", "해산물", "조개", "광어", "낙지", "대게", "장어", "오징어",
                  "새우", "굴요리", "멍게", "해물탕", "조개구이"]),
    # 강한 고기 신호 — 일식(오마카세)보다 위. 단 'XX탕/국밥/육개장' 같은 한식 국물요리는
    # 여기 키워드에 넣지 않는다(bare '갈비' 미사용 → '갈비탕'을 고기로 오분류 방지).
    ("고기", ["한우", "소고기", "삼겹살", "돼지갈비", "소갈비", "생갈비", "왕갈비",
            "마늘갈비", "갈비살", "양갈비", "양고기", "목살", "흑우", "흑돼지", "한돈",
            "이베리코", "곱창", "막창", "대창", "뭉티기", "정육", "닭구이",
            "안창", "특수부위", "항정", "오돌갈비", "꽃삼겹", "꽃살", "차돌", "등심",
            "고깃집", "고기집", "숙성돼지", "숙성삼겹", "부채살", "살치살"]),
    ("일식", ["이자카야", "사시미", "스시", "오마카세", "라멘", "사케", "일식", "우동",
            "돈카츠", "텐동", "야끼", "초밥", "덮밥집"]),
    # 한식·기타 — 특정 토픽(국물/면/분식/기타 에스닉). 폴백과 동일 라벨.
    (MAJOR_UNCLASSIFIED, ["갈비탕", "곰탕", "국밥", "육개장", "냉면", "순대", "족발",
                          "찌개", "솥밥", "막걸리", "백반", "한정식", "보쌈", "비빔밥",
                          "수육", "국수", "쌀국수", "팟타이", "분식", "떡볶이", "한식",
                          "정육식당"]),
]


def classify_major(category):
    """DiningCode 원문 카테고리 → 대분류 7종 중 하나(결정론적)."""
    raw = (category or "").strip()
    primary = raw.split(",")[0].strip()
    for text in (primary, raw):
        if not text:
            continue
        for bucket, kws in MAJOR_RULES:
            if any(kw in text for kw in kws):
                return bucket
    return MAJOR_UNCLASSIFIED


CSV_FIELDS = ["순위", "식당명", "카테고리", "대분류", "도로명주소", "전화",
              "도보거리_m", "도보_분", "콜키지태그", "위스키신호", "평판점수",
              "user_score", "리뷰수", "confidence", "대표사진", "네이버지도",
              "식당ID", "lat", "lng",
              "추천_위스키종류", "대안_위스키종류", "페어링근거"]


def row_rid(r):
    """식당 고유 ID(rid). 신규 CSV는 `식당ID`(rid 단독), 구 CSV는 `다이닝코드링크`(URL)
    둘 다 허용해 무중단 마이그레이션(외부 소스 브랜드 흔적 제거, CMPA-102).
    인당비용·메뉴 캐시의 조인 키로만 쓰이는 내부 식별자다."""
    v = (r.get("식당ID") or r.get("다이닝코드링크") or "").strip()
    return v.split("rid=")[-1].strip()


def naver_map_link(name, addr=None):
    """네이버 지도 검색 딥링크. 상호+주소를 함께 넣으면 지도가 안 뜨는 사례가 있어
    (CMPA-55 피드백) **상호만**으로 검색한다(지점명 포함)."""
    return f"https://map.naver.com/p/search/{_quote(name.strip())}"


def haversine_m(lat1, lng1, lat2, lng2):
    """두 WGS84 좌표 사이 직선거리(m)."""
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def dc_search(query, size=100, pages=1, sleep=0.8):
    """DiningCode isearch 호출 → poi list 반환."""
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


def whisky_score(poi, in_whisky_query):
    """위스키 신호 점수와 매칭 토큰 반환."""
    hay = " ".join([
        poi.get("category", "") or "",
        " ".join(k.get("term", "") for k in (poi.get("keyword") or [])),
        json.dumps(poi.get("display_review") or {}, ensure_ascii=False),
    ])
    hits = sorted({t for t in WHISKY_TOKENS if t in hay})
    score = len(hits) + (2 if in_whisky_query else 0)
    return score, hits


def _is_free_tag(term):
    """'콜키지프리'/'콜키지무료'(띄어쓰기·free 변형 포함)만 무료로 인정.
    바'콜키지'(=콜키지 토픽, 유료일 수 있음)는 무료가 아니다."""
    t = (term or "").replace(" ", "").lower()
    return ("콜키지프리" in t) or ("콜키지무료" in t) or ("콜키지free" in t)


def corkage_tag(poi):
    """명시적 '무료' 콜키지 태그만 반환. mark=1 우선.
    무료 태그가 없으면 "" → 호출부에서 목록 제외(유료/모호 콜키지 걸러냄)."""
    terms = [(k.get("term", ""), k.get("mark")) for k in (poi.get("keyword") or [])]
    for t, m in terms:
        if m and _is_free_tag(t):
            return t
    for t, _ in terms:
        if _is_free_tag(t):
            return t
    return ""


# 유료/조건부 콜키지 증거 패턴(리뷰·키워드에서 탐지). '콜키지 2만원/30,000원',
# '콜키지 비용', '유료 콜키지', '병당', '1병당', '콜키지피' 등.
_PAID_RX = re.compile(
    r"콜키지\s*[\d][\d,]*\s*(?:원|만)|콜키지\s*비용|유료\s*콜키지|콜키지\s*유료|"
    r"콜키지\s*피[^\w]|콜키지비|병\s*당\s*\d|1\s*병\s*당|2\s*인\s*1\s*병|콜키지\s*받"
)
# 위 패턴이 사실은 '무료'를 말하는 경우(콜키지 비용 무료/없음) 오탐 방지용 부정 신호.
_FREE_RX = re.compile(r"콜키지\s*무료|콜키지\s*프리|콜키지프리|콜키지무료|무료\s*콜키지|콜키지\s*free", re.I)


def paid_corkage_suspect(poi):
    """리뷰/키워드에 유료·조건부 콜키지 증거가 있으면 (True, 근거문구) 반환."""
    dr = poi.get("display_review") or {}
    text = " ".join([
        str(dr.get("review_cont", "")),
        " ".join(k.get("term", "") for k in (poi.get("keyword") or [])),
    ])
    m = _PAID_RX.search(text)
    if not m:
        return False, ""
    # 매칭 부위 주변에 무료/없 신호가 바로 붙어있으면 무료로 간주(오탐 방지)
    s = max(0, m.start() - 6)
    around = text[s:m.end() + 8]
    if re.search(r"무료|없|공짜|free", around, re.I):
        return False, ""
    return True, _EM.sub("", m.group(0)).strip()


def find(station, lat, lng, radius_m, whisky_only=False, keep_suspect=False):
    print(f"[조회] {station} ({lat},{lng}) 반경 {radius_m}m")
    # 콜키지 질의 + 위스키 질의로 후보 수집
    corkage_pois, whisky_rids = {}, set()
    for q in [f"{station} 콜키지프리", f"{station} 콜키지무료"]:
        for p in dc_search(q):
            if p.get("v_rid"):
                corkage_pois.setdefault(p["v_rid"], p)
    for p in dc_search(f"{station} 위스키 콜키지"):
        if p.get("v_rid"):
            whisky_rids.add(p["v_rid"])
            corkage_pois.setdefault(p["v_rid"], p)
    print(f"  콜키지 후보 {len(corkage_pois)}곳 / 위스키질의 매칭 {len(whisky_rids)}곳")

    rows = []
    n_no_free_tag = n_paid = 0
    for rid, p in corkage_pois.items():
        try:
            plat, plng = float(p["lat"]), float(p["lng"])
        except (TypeError, ValueError, KeyError):
            continue
        dist = haversine_m(lat, lng, plat, plng)
        if dist > radius_m:
            continue
        tag = corkage_tag(p)
        if not tag:  # 무료 콜키지 태그 없음(바'콜키지'=유료/모호) → 제외
            n_no_free_tag += 1
            continue
        suspect, paid_note = paid_corkage_suspect(p)
        if suspect and not keep_suspect:  # 리뷰에 유료/조건부 콜키지 증거 → 제외
            n_paid += 1
            continue
        in_wq = rid in whisky_rids
        wscore, whits = whisky_score(p, in_wq)
        if whisky_only and wscore == 0:
            continue
        # 위스키 신호를 사람이 읽을 수 있게: 리뷰/키워드 토큰 + '위스키 콜키지' 질의 매칭
        sig = list(whits)
        if in_wq:
            sig.append("위스키검색매칭")
        # confidence: 콜키지 정책 세부 미확인 → 항상 매장확인 권고
        if suspect:
            conf = f"⚠️유료의심({paid_note}) 매장확인"
        elif wscore > 0:
            conf = "위스키신호有(매장확인)"
        else:
            conf = "콜키지프리(주종확인필요)"
        nm = clean(p.get("nm")) + (f" {clean(p['branch'])}" if p.get("branch") else "")
        road = clean(p.get("road_addr")) or clean(p.get("addr"))
        cat = clean(p.get("category"))
        _ps_short, ps_full, _alt_short, alt_full, ps_reason = pair_style_for_category(cat)
        rows.append({
            "식당명": nm,
            "카테고리": cat,
            "대분류": classify_major(cat),
            "도로명주소": road,
            "전화": p.get("phone", ""),
            "도보거리_m": round(dist),
            "도보_분": round(dist / 67),  # 약 4km/h 도보
            "콜키지태그": tag,
            "위스키신호": ",".join(sig) if sig else "",
            "평판점수": p.get("score", ""),  # 인기·평판 종합점수(0–100). 추천순 정렬의 1차 키
            "user_score": p.get("user_score", ""),
            "리뷰수": p.get("review_cnt", ""),
            "confidence": conf,
            "대표사진": "",  # CMPA-102: 외부 소스 CDN 이미지 URL 미저장(브랜드 흔적 제거)
            "네이버지도": naver_map_link(nm),
            "식당ID": rid,  # 내부 조인 키(외부 프로필 URL 미저장, CMPA-102)
            "lat": plat, "lng": plng,
            "추천_위스키종류": ps_full,
            "대안_위스키종류": alt_full,
            "페어링근거": ps_reason,
            "_w": wscore,
        })
    print(f"  필터: 무료태그없음 제외 {n_no_free_tag}곳 · 유료의심 "
          f"{'표시' if keep_suspect else '제외'} {n_paid}곳")
    # 정렬(추천순) = ① 인기·평판 종합점수(평판점수 0–100) 높은 순 → ② 가까운 순.
    # 위스키 신호는 '위스키검색매칭'처럼 노이즈가 있어 순위를 뒤집지 않는다(배지/필터로만 노출).
    # 위스키 중심으로 보려면 --whisky-only 사용.
    def _score(r):
        try:
            return float(r.get("평판점수") or r.get("다코점수") or 0)  # 구 CSV 폴백
        except (TypeError, ValueError):
            return 0.0
    rows.sort(key=lambda r: (-_score(r), r["도보거리_m"]))
    for i, r in enumerate(rows, 1):
        r["순위"] = i
        r.pop("_w", None)
    return rows


# 대분류 표시 순서(보고/정렬 일관성). 분류기 버킷과 1:1.
MAJOR_ORDER = ["고기", "물고기·해산물", "웨스턴(양식)", "일식", "중식",
               "한식·기타", "바·주류"]


def major_counts(rows):
    """대분류별 개수(표시 순서대로). 누락 버킷도 0으로 포함."""
    cnt = {b: 0 for b in MAJOR_ORDER}
    for r in rows:
        b = r.get("대분류") or MAJOR_UNCLASSIFIED
        cnt[b] = cnt.get(b, 0) + 1
    return cnt


def major_distribution_md(rows):
    """대분류 분포표(마크다운)."""
    cnt = major_counts(rows)
    total = max(1, len(rows))
    out = ["### 대분류 분포\n\n", "| 대분류 | 곳 | 비중 |\n", "|--------|----|------|\n"]
    for b in MAJOR_ORDER:
        c = cnt.get(b, 0)
        out.append(f"| {b} | {c} | {round(100*c/total)}% |\n")
    out.append(f"| **합계** | **{len(rows)}** | 100% |\n\n")
    return "".join(out)


def _cost_won_md(rid):
    """rid → '예상 1인 금액'(1인_표준, 주류제외) 포맷. 데이터 없으면 '-'."""
    c = _load_cost_map().get(rid)
    if not c:
        return "-"
    typ = str(c.get("1인_표준", "")).strip()
    if not typ or typ in ("0", "nan"):
        return "-"
    try:
        return f"{int(float(typ)):,}원"
    except (TypeError, ValueError):
        return "-"


def restaurant_table_md(rows):
    """식당 목록 표(마크다운, 상위 30).
    CMPA-88 board 지시: '콜키지'·'위스키신호' 컬럼 제거, '예상 1인 금액'(주류제외
    1인 추정, CMPA-66) 추가. 네이버지도 딥링크는 보존(PDF 링크 클릭 유지)."""
    out = ["| # | 식당 | 대분류 | 카테고리 | 도보 | 예상 1인 금액 | 지도 |\n",
           "|---|------|--------|----------|------|------------:|------|\n"]
    for r in rows[:30]:
        rid = row_rid(r)
        out.append(
            f"| {r['순위']} | {r['식당명']} | {r.get('대분류','')} | {r['카테고리']} | "
            f"{r['도보_분']}분({r['도보거리_m']}m) | {_cost_won_md(rid)} | "
            f"[네이버지도]({r['네이버지도']}) |\n")
    return "".join(out)


_COST_NOTE = (
    "> **예상 1인 금액** = 음식 기준 1인 추정액(주류 제외, CMPA-66 추정). "
    "메뉴 데이터 없으면 '-'. 실제 금액은 메뉴·인원·주문에 따라 다릅니다.\n\n"
)


def save(station, rows, radius_m, lat, lng, run_date=""):
    run_date = run_date or kst_today()  # 리포트 작성일(최신성 판단 기준, CMPA-109)
    os.makedirs(OUT_DIR, exist_ok=True)
    os.makedirs(REPORT_DIR, exist_ok=True)
    base = f"{station}_콜키지프리"
    csv_path = os.path.join(OUT_DIR, base + ".csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    snapshot(csv_path)
    # 마크다운(상위 30) — 네이버지도 링크(사진·외부소스 링크 제외, CMPA-87). reports/ 하위.
    md_path = os.path.join(REPORT_DIR, base + ".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {station} 위스키 콜키지프리 식당 (도보 {radius_m}m 이내)\n\n")
        f.write(f"📅 **리포트 작성일**: {run_date} — 최신성은 이 날짜를 기준으로 판단하세요\n\n")
        f.write(f"총 {len(rows)}곳 · "
                "거리=역 좌표 기준 직선 근사 · 콜키지 정책 세부는 매장 확인 필요\n\n")
        f.write(major_distribution_md(rows))
        f.write(_COST_NOTE)
        f.write(restaurant_table_md(rows))
    snapshot(md_path)
    # 식당별 미니 지도(역↔해당 식당)만 생성. 상단 '역 중심 개요 지도'는 CEO 요청으로 제외.
    map_name, whisky_rows = None, [r for r in rows if r["위스키신호"]][:12]
    map_uri = None  # 개요 지도 미사용 → HTML 상단 임베드 안 함
    try:
        from pipelines.corkage_free.mapshot import render_pair, to_data_uri
        print(f"  식당별 미니지도 {len(rows)}장 생성 중…")
        for r in rows:
            try:
                mp = render_pair(lat, lng, float(r["lat"]), float(r["lng"]), w=600, h=320)
                r["_mapuri"] = to_data_uri(mp)
            except Exception:  # noqa: BLE001
                r["_mapuri"] = None
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 지도 생성 실패(타일 차단 등): {e}", file=sys.stderr)
    # HTML 상세 카드(역 개요지도 + 식당별 미니지도 + 사진/지도링크 — 자가포함)
    html_path = os.path.join(REPORT_DIR, base + ".html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(_render_html(station, rows, radius_m, map_uri, whisky_rows, run_date=run_date))
    snapshot(html_path)
    return csv_path, md_path, html_path


_COST_MAP = None


def _load_cost_map():
    """rid → 인당비용 추정(주류제외) 매핑. estimate_per_person_map.py 산출 CSV에서 읽음.
    카드에 '주류제외 인당 비용' 배지 + hover 근거를 붙이기 위함(CMPA-66 board 지시)."""
    global _COST_MAP
    if _COST_MAP is not None:
        return _COST_MAP
    _COST_MAP = {}
    path = os.path.join(OUT_DIR, "콜키지프리_인당비용_전체.csv")
    try:
        with open(path, encoding="utf-8-sig") as f:
            for r in csv.DictReader(f):
                _COST_MAP[r["rid"]] = r
    except OSError:
        pass  # 비용 CSV 없으면 배지 생략(그레이스풀)
    return _COST_MAP


import base64 as _b64  # noqa: E402

_PHOTO_CACHE = None
_PHOTO_CACHE_PATH = os.path.join(OUT_DIR, "_cache", "photos.json")


def _embed_photo(url):
    """대표사진 URL → base64 data URI(자가포함 HTML). 디스크 캐시(_cache/photos.json)로
    재실행 시 재다운로드 회피. board 요청: 사진을 HTML에 임베딩(모바일/오프라인 자가포함).
    실패 시 원본 URL 폴백."""
    global _PHOTO_CACHE
    if not url:
        return ""
    if _PHOTO_CACHE is None:
        try:
            _PHOTO_CACHE = json.load(open(_PHOTO_CACHE_PATH, encoding="utf-8"))
        except (OSError, ValueError):
            _PHOTO_CACHE = {}
    if url in _PHOTO_CACHE:
        return _PHOTO_CACHE[url]
    try:
        resp = requests.get(url, headers={"User-Agent": UA}, timeout=20)
        resp.raise_for_status()
        ct = resp.headers.get("Content-Type", "image/webp").split(";")[0].strip()
        b64 = _b64.b64encode(resp.content).decode("ascii")
        uri = f"data:{ct};base64,{b64}"
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 사진 임베딩 실패({url[:60]}): {e}", file=sys.stderr)
        return url  # 폴백: 외부 URL 유지
    _PHOTO_CACHE[url] = uri
    os.makedirs(os.path.dirname(_PHOTO_CACHE_PATH), exist_ok=True)
    json.dump(_PHOTO_CACHE, open(_PHOTO_CACHE_PATH, "w", encoding="utf-8"))
    return uri


_MENU_MAP = None


def _load_menu_map():
    """rid → [[메뉴명, 가격], …]. estimate_per_person_map.py 의 메뉴 캐시에서 읽음.
    클릭 모달에 '메뉴 정보'를 보여주기 위함(board 요청)."""
    global _MENU_MAP
    if _MENU_MAP is not None:
        return _MENU_MAP
    _MENU_MAP = {}
    try:
        _MENU_MAP = json.load(open(os.path.join(OUT_DIR, "_cache", "menus.json"),
                                   encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return _MENU_MAP


def _menu_html(rid):
    """모달용 '메뉴' 섹션 HTML(가격 내림차순). 없으면 ''."""
    menu = _load_menu_map().get(rid) or []
    if not menu:
        return ""
    rows = sorted(((n, p) for n, p in menu), key=lambda x: -x[1])
    items = "".join(
        f"<div class=cf-mrow><span>{_esc(n)}</span><b>{p:,}원</b></div>"
        for n, p in rows)
    return (f"<div class=cf-menu><div class=cf-mh>메뉴 ({len(rows)})</div>{items}</div>")


def _cost_detail_html(rid):
    """비용 상세(요약 + 정규화 메뉴별 1인 환산) HTML. hover 툴팁·모달이 공유."""
    c = _load_cost_map().get(rid)
    if not c:
        return ""
    typ = str(c.get("1인_표준", "")).strip()
    if not typ:
        return "<div>🍽 주류제외 인당 <b>추정 보류</b> — 메뉴 데이터 없음</div>"
    try:
        typ_i = int(float(typ))
        lo = int(float(c.get("1인_아낌") or typ_i))
        hi = int(float(c.get("1인_넉넉") or typ_i))
    except ValueError:
        return ""
    basis = c.get("근거", "")
    conf = c.get("confidence", "")
    detail = c.get("정규화내역", "")
    head = (f"<div class=cd-head>🍽 주류제외 인당 <b>{typ_i:,}원</b></div>"
            f"<div>💡 {_esc(basis)}</div>"
            f"<div>범위 {lo:,}~{hi:,}원 · 신뢰도 {_esc(conf)} · 음식값(주류 지참) 기준</div>")
    items = [s for s in detail.split(" | ") if s.strip()]
    if items:
        head += ("<div class=cost-items><div class=cost-ih>정규화에 쓴 메뉴(1인 환산)</div>"
                 + "".join(f"<div>· {_esc(s)}</div>" for s in items) + "</div>")
    return head


def _cost_badge(rid):
    """카드용 '주류제외 인당 비용' 배지 HTML. hover 시 .cost-tip 으로 근거 노출."""
    c = _load_cost_map().get(rid)
    if not c:
        return ""
    typ = c.get("1인_표준", "")
    if not str(typ).strip():   # 메뉴 데이터 없어 추정 보류
        return ("<div class='cost cost-na'>"
                "🍽 주류제외 인당 <b>추정 보류</b></div>")
    try:
        typ_i = int(float(typ))
    except ValueError:
        return ""
    # 배지 본문(가격)만 카드에 노출. 상세 근거는 클릭→모달(모바일 hover 문제 해소, CMPA-66).
    return (f"<div class=cost>🍽 주류제외 인당 <b>{typ_i:,}원</b>"
            "<span class=cost-more>탭하면 상세 ›</span></div>")


# ── 주류제외 인당 비용 필터 버킷 (CMPA-75 board) ──
# board 요청: 3만원미만 / 3만원이상~6만원이하 / 6만원이상. 경계 60,000원은 중간 버킷(이하)에 포함.
PRICE_ORDER = ["3만원 미만", "3만~6만원", "6만원 이상"]


def _cost_bucket(rid):
    """rid → 주류제외 1인 표준비용 버킷 라벨(PRICE_ORDER 중 하나). 데이터 없으면 ''.

    추정 보류(메뉴 데이터 없음)·비용 CSV 미존재 매장은 '' 를 반환해 가격 필터에서 자연히 제외된다
    (위스키 필터의 빈 값과 동일한 동작)."""
    c = _load_cost_map().get(rid)
    if not c:
        return ""
    typ = str(c.get("1인_표준", "")).strip()
    if not typ:
        return ""
    try:
        v = float(typ)
    except ValueError:
        return ""
    if v < 30000:
        return "3만원 미만"
    if v <= 60000:
        return "3만~6만원"
    return "6만원 이상"


def _render_html(station, rows, radius_m, map_uri=None, whisky_rows=None, run_date=""):
    wh = sum(1 for r in rows if r["위스키신호"])
    whisky_rows = whisky_rows if whisky_rows is not None else [r for r in rows if r["위스키신호"]][:12]
    head = (
        "<!doctype html><html lang=ko><head><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{_esc(station)} 위스키 콜키지프리 식당</title><style>"
        "body{font-family:-apple-system,'Apple SD Gothic Neo',sans-serif;margin:0;background:#f6f6f8;color:#222}"
        "header{padding:18px 16px;background:#1b1b2b;color:#fff}"
        "header h1{margin:0 0 4px;font-size:20px}header p{margin:0;font-size:13px;opacity:.85}"
        # CMPA-109: 리포트 작성일(최신성 판단 기준) — halal·pet과 동일 패턴
        ".rundate{margin:7px 0 0;font-size:12px;opacity:.85}"
        ".wrap{display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:14px;padding:16px}"
        # overflow:visible — 카드 밖으로 hover 툴팁(.cost-tip)이 잘리지 않게. 사진 모서리
        # 라운딩은 .photo 로 옮겨 처리(CMPA-66 상세 툴팁).
        ".card{background:#fff;border-radius:12px;overflow:visible;box-shadow:0 1px 4px rgba(0,0,0,.08);display:flex;flex-direction:column}"
        ".card.wh{outline:2px solid #c8941f}"
        ".photo{position:relative;width:100%;height:150px;background:#eee;border-radius:12px 12px 0 0;overflow:hidden}"
        ".thumb{width:100%;height:150px;object-fit:cover;display:block}"
        # 역↔식당 위치 지도를 사진 밴드 전체로 표시(CMPA-102): 빈 회색 밴드 대신 위치 지도.
        ".bandmap{width:100%;height:150px;object-fit:cover;display:block;background:#eee}"
        ".rank{position:absolute;left:7px;top:7px;background:rgba(20,20,30,.78);color:#fff;"
        "font-size:12px;font-weight:700;padding:3px 9px;border-radius:13px}"
        ".pairstyles{position:absolute;left:7px;bottom:7px;display:flex;flex-wrap:wrap;gap:4px;"
        "max-width:calc(100% - 108px)}"
        ".t-pairstyle{background:rgba(138,109,0,.93);color:#fff;"
        "font-size:12px;font-weight:700;padding:3px 9px;border-radius:13px;"
        "box-shadow:0 1px 4px rgba(0,0,0,.4);cursor:default}"
        ".t-pairstyle.alt{background:rgba(138,109,0,.6);font-weight:600}"
        ".body{padding:12px 14px;flex:1;display:flex;flex-direction:column;gap:6px}"
        ".nm{font-size:16px;font-weight:700}.cat{font-size:12px;color:#666}"
        ".major{display:inline-block;background:#1b1b2b;color:#fff;font-size:11px;"
        "font-weight:700;border-radius:9px;padding:1px 7px;margin-right:4px}"
        # ── 주류제외 인당 비용 배지 (CMPA-66) — 상세는 카드 클릭→모달 ──
        ".cost{align-self:flex-start;background:#fdf3e3;color:#8a5a00;"
        "font-size:13px;font-weight:700;border-radius:9px;padding:4px 10px;border:1px solid #f0dcb8}"
        ".cost b{font-weight:800}"
        ".cost .cost-more{font-weight:600;color:#b07b1f;font-size:11px;margin-left:6px}"
        ".cost.cost-na{background:#f0f0f3;color:#999;border-color:#e3e3e8}"
        # 카드 클릭 → 상세 모달 (모바일 hover 대체)
        ".card{cursor:pointer}"
        ".cf-ov{display:none;position:fixed;inset:0;z-index:100;background:rgba(0,0,0,.55);"
        "align-items:center;justify-content:center;padding:16px}"
        ".cf-ov.show{display:flex}"
        ".cf-mc{position:relative;background:#fff;border-radius:14px;max-width:440px;width:100%;"
        "max-height:88vh;overflow:auto;box-shadow:0 8px 40px rgba(0,0,0,.4)}"
        ".cf-x{position:absolute;right:10px;top:8px;font-size:26px;line-height:1;color:#fff;"
        "cursor:pointer;z-index:2;text-shadow:0 1px 4px rgba(0,0,0,.6);width:32px;text-align:center}"
        ".cf-mimg{width:100%;height:220px;object-fit:cover;border-radius:14px 14px 0 0;display:block;background:#eee}"
        ".cf-mc>#cf-mbody{padding:14px 16px 18px}"
        ".cf-nm{font-size:20px;font-weight:800}.cf-cat{font-size:13px;color:#666;margin:2px 0 10px}"
        ".cf-cost{background:#fffaf0;border:1px solid #f0dcb8;border-radius:10px;padding:10px 12px;"
        "font-size:12.5px;line-height:1.55;color:#5b3d00}"
        ".cf-cost .cd-head{font-size:15px;color:#8a5a00;margin-bottom:4px}"
        ".cf-cost .cost-items{margin-top:7px;border-top:1px solid #eadfca;padding-top:7px}"
        ".cf-cost .cost-items>div{margin:1.5px 0}.cf-cost .cost-ih{font-weight:700;color:#b07b1f;margin-bottom:3px}"
        ".cf-tags{margin:10px 0 4px;font-size:12px;color:#1366c2}"
        ".cf-pair{font-size:12px;color:#8a6d00;margin:4px 0}"
        ".cf-meta{font-size:12.5px;color:#444;line-height:1.65;margin-top:8px}"
        ".cf-menu{margin-top:12px;border-top:1px solid #eee;padding-top:8px}"
        ".cf-mh{font-weight:700;font-size:13px;color:#333;margin-bottom:5px}"
        ".cf-mrow{display:flex;justify-content:space-between;gap:10px;font-size:12.5px;"
        "color:#444;padding:3px 0;border-bottom:1px dashed #eee}"
        ".cf-mrow span{flex:1}.cf-mrow b{white-space:nowrap;color:#222}"
        ".cf-links{display:flex;gap:8px;margin-top:12px}"
        ".cf-links a{flex:1;text-align:center;font-size:14px;text-decoration:none;padding:10px 0;border-radius:8px;"
        "background:#03c75a;color:#fff}.cf-links a+a{background:#eee;color:#333}"
        ".tags span{display:inline-block;font-size:11px;border-radius:10px;padding:2px 8px;margin:2px 4px 0 0}"
        ".t-cork{background:#e8f3ff;color:#1366c2}.t-wh{background:#fff2d6;color:#9a6b00}"
        ".meta{font-size:12px;color:#444;line-height:1.6}"
        ".links{margin-top:auto;display:flex;gap:8px;padding-top:8px}"
        ".links a{flex:1;text-align:center;font-size:13px;text-decoration:none;padding:8px 0;border-radius:8px}"
        ".naver{background:#03c75a;color:#fff}"
        ".note{font-size:12px;color:#888;padding:0 16px 24px}"
        ".mapbox{padding:16px;background:#fff;margin:0;border-bottom:1px solid #eee}"
        ".mapbox img{max-width:100%;border-radius:10px;display:block}"
        ".maplegend{font-size:13px;color:#333;margin-top:10px;line-height:1.7}"
        ".maplegend b{display:inline-block;min-width:22px;height:22px;line-height:22px;"
        "text-align:center;border-radius:50%;background:#d62828;color:#fff;margin-right:6px}"
        # ── 필터 바 (CMPA-75) ──
        ".filterbar{position:sticky;top:0;z-index:5;background:#fff;border-bottom:1px solid #e6e6ea;"
        "padding:12px 16px;box-shadow:0 1px 4px rgba(0,0,0,.04)}"
        ".fgroup{display:flex;flex-wrap:wrap;align-items:center;gap:6px;margin:4px 0}"
        ".fglabel{font-size:12px;font-weight:700;color:#555;min-width:78px}"
        ".fbtn{font-size:12px;border:1px solid #ccc;background:#fff;color:#333;border-radius:14px;"
        "padding:5px 11px;cursor:pointer;line-height:1;user-select:none}"
        ".fbtn:hover{border-color:#999}"
        ".fgroup.food .fbtn.on{background:#1b1b2b;border-color:#1b1b2b;color:#fff}"
        ".fgroup.whisky .fbtn.on{background:#8a6d00;border-color:#8a6d00;color:#fff}"
        ".fgroup.price .fbtn.on{background:#1366c2;border-color:#1366c2;color:#fff}"
        ".fmeta{font-size:12px;color:#666;margin-top:6px}"
        ".fmeta .freset{color:#1366c2;cursor:pointer;text-decoration:underline;margin-left:8px}"
        ".card.hide{display:none}"
        "</style></head><body>"
        f"<header><h1>{_esc(station)} 위스키 콜키지프리 식당</h1>"
        f"<p>도보 {radius_m}m(약 {round(radius_m/67)}분) 이내 · 콜키지프리 {len(rows)}곳 · "
        f"위스키 신호 {wh}곳 · 거리=직선 근사</p>"
        + "<p style='margin-top:6px;font-size:12px;opacity:.85'>대분류: "
        + " · ".join(f"{b} {c}" for b, c in major_counts(rows).items() if c)
        + "</p>"
        "<p style='margin-top:6px;font-size:12px;opacity:.8'>순위 기준(추천순): "
        "① 인기·평판 높은 순 → ② 역에서 가까운 순. "
        "위스키 콜키지 가능 매장은 🥃 배지로 표시(순위를 끌어올리진 않음) — 위스키만 보려면 위스키 필터.</p>"
        + (f"<p class=rundate>📅 리포트 작성일 {_esc(run_date)} — 최신성은 이 날짜를 "
           "기준으로 판단하세요</p>" if run_date else "")
        + "</header>"
    )
    # 역 중심 지도 스샷 + 빨간 번호 ↔ 위스키 식당 매칭 범례
    mapsec = ""
    if map_uri:
        legend = "".join(
            f"<div><b>{i}</b>{_esc(r['식당명'])} "
            f"<span style='color:#888'>· {r['도보_분']}분 · {_esc(r['콜키지태그'])}</span></div>"
            for i, r in enumerate(whisky_rows, 1)
        )
        mapsec = (
            f"<div class=mapbox><img src='{map_uri}' "
            f"alt='{_esc(station)} 주변 콜키지프리 식당 지도'>"
            f"<div class=maplegend><b style='background:#1a5ac8'>S</b>{_esc(station)} "
            "· 빨간 번호 = 위스키 콜키지프리(아래 매칭) · 회색 점 = 일반 콜키지프리"
            f"{legend}</div></div>"
        )
    # ── 필터 바 (CMPA-75) — 음식 종류 × 위스키 종류 AND 필터 ──────────────────
    # 버튼 목록은 실제 데이터에 존재하는 값만(빈 버킷 노출 방지). 음식=대분류(고정 순서),
    # 위스키=추천 위스키 종류 짧은 라벨(빈도 desc). 각 버튼에 곳수 표기.
    food_cnt = {}
    whisky_cnt = {}
    price_cnt = {}
    for r in rows:
        mv = r.get("대분류", "") or MAJOR_UNCLASSIFIED
        food_cnt[mv] = food_cnt.get(mv, 0) + 1
        p_s, _pf, a_s, _af, _rs = pair_style_for_category(r.get("카테고리", ""))
        for s in dict.fromkeys([x for x in (p_s, a_s) if x]):
            whisky_cnt[s] = whisky_cnt.get(s, 0) + 1
        pb = _cost_bucket(row_rid(r))
        if pb:
            price_cnt[pb] = price_cnt.get(pb, 0) + 1
    food_btns = [(b, food_cnt[b]) for b in MAJOR_ORDER if food_cnt.get(b)]
    whisky_btns = sorted(whisky_cnt.items(), key=lambda kv: (-kv[1], kv[0]))
    price_btns = [(b, price_cnt[b]) for b in PRICE_ORDER if price_cnt.get(b)]

    def _fbtns(items):
        return "".join(
            f"<span class=fbtn data-val=\"{_esc(v)}\">{_esc(v)} <small>{c}</small></span>"
            for v, c in items
        )

    # 가격 버킷 데이터가 하나도 없으면(비용 CSV 미존재) 가격 그룹은 통째로 생략(그레이스풀).
    price_group = (
        "<div class='fgroup price'><span class=fglabel>인당 비용</span>"
        + _fbtns(price_btns) + "</div>"
    ) if price_btns else ""
    filterbar = (
        "<div class=filterbar>"
        "<div class='fgroup food'><span class=fglabel>음식 종류</span>"
        + _fbtns(food_btns) + "</div>"
        "<div class='fgroup whisky'><span class=fglabel>위스키 종류</span>"
        + _fbtns(whisky_btns) + "</div>"
        + price_group
        + "<div class=fmeta>버튼을 눌러 필터링 — <b>음식 × 위스키 × 인당비용 = AND</b>, "
        "같은 묶음 안에서는 OR. <span id=fcount></span>"
        "<span class=freset id=freset>전체 해제</span></div>"
        "</div>"
    )
    head = head + mapsec + filterbar + "<div class=wrap>"
    cards = []
    details = []   # 모달용 per-card 상세(클릭 시 표시)
    for idx, r in enumerate(rows):
        rid = row_rid(r)
        wh_cls = " wh" if r["위스키신호"] else ""
        # CMPA-87: 외부 소스 대표사진 제거. CMPA-102: 빈 회색 밴드 대신 역↔식당 위치
        # 지도를 사진 밴드 전체로 표시(보드 요청). 지도 없으면 회색 밴드 폴백.
        img = (f"<img class=bandmap loading=lazy src='{r['_mapuri']}' "
               f"alt='{_esc(station)}↔{_esc(r['식당명'])} 위치 지도'>"
               if r.get("_mapuri") else "<div class=thumb></div>")
        wtag = (f"<span class=t-wh>🥃 {_esc(r['위스키신호'])}</span>" if r["위스키신호"] else "")
        phone = f"☎ {_esc(r['전화'])}<br>" if r["전화"] else ""
        p_short, p_full, a_short, a_full, ps_reason = pair_style_for_category(r.get("카테고리", ""))
        # CMPA-75 필터용 data 속성: 음식=대분류 1개, 위스키=추천 종류(1순위+대안) 짧은 라벨들.
        major_v = r.get("대분류", "") or MAJOR_UNCLASSIFIED
        whisky_v = "|".join(dict.fromkeys([s for s in (p_short, a_short) if s]))
        price_v = _cost_bucket(row_rid(r))
        # 추천이 여러 개(1순위+대안)면 뱃지도 여러 개(보드 요청). 1순위=진한 골드, 대안=연한 골드.
        pairbadge = (
            "<span class=pairstyles>"
            f"<span class=t-pairstyle title='1순위 추천 위스키종류: {_esc(p_full)} — {_esc(ps_reason)}'>"
            f"🥃 {_esc(p_short)}</span>"
            f"<span class='t-pairstyle alt' title='대안 위스키종류: {_esc(a_full)}'>"
            f"🥃 {_esc(a_short)}</span>"
            "</span>"
        )
        cards.append(
            f"<div class='card{wh_cls}' data-idx=\"{idx}\" data-major=\"{_esc(major_v)}\" "
            f"data-whisky=\"{_esc(whisky_v)}\" data-price=\"{_esc(price_v)}\">"
            f"<div class=photo>{img}<span class=rank>추천 {r['순위']}위</span>{pairbadge}</div>"
            f"<div class=body>"
            f"<div class=nm>{_esc(r['식당명'])}</div>"
            f"<div class=cat><span class=major>{_esc(r.get('대분류',''))}</span> "
            f"{_esc(r['카테고리'])}</div>"
            f"{_cost_badge(rid)}"
            f"<div class=tags><span class=t-cork>📦 {_esc(r['콜키지태그'])}</span>{wtag}</div>"
            f"<div class=meta>🚶 {r['도보_분']}분 ({r['도보거리_m']}m)<br>"
            f"📍 {_esc(r['도로명주소'])}<br>{phone}"
            f"<small style='color:#999'>{_esc(r['confidence'])}</small></div>"
            f"<div class=links><a class=naver href='{_esc(r['네이버지도'])}' target=_blank>네이버지도</a></div>"
            "</div></div>"
        )
        # 모달 상세: 사진은 카드 썸네일을 JS로 재사용(중복 임베딩 회피).
        meta_html = (
            f"🚶 {_esc(str(r['도보_분']))}분 ({_esc(str(r['도보거리_m']))}m)<br>"
            f"📍 {_esc(r['도로명주소'])}<br>"
            + (f"☎ {_esc(r['전화'])}<br>" if r['전화'] else "")
            + f"<small style='color:#999'>{_esc(r['confidence'])}</small>"
        )
        details.append({
            "nm": r["식당명"],
            "cat": (r.get("대분류", "") + " · " + r["카테고리"]).strip(" ·"),
            "cost": _cost_detail_html(rid),
            "tags": f"📦 {r['콜키지태그']}" + (f" · 🥃 {r['위스키신호']}" if r["위스키신호"] else ""),
            "pair": f"🥃 추천 위스키: {p_full}" + (f" · 대안: {a_full}" if a_short else "")
                    + (f"<br><span style='color:#888'>{ps_reason}</span>" if ps_reason else ""),
            "meta": meta_html,
            "menu": _menu_html(rid),
            "naver": r["네이버지도"],
        })
    note = ("<div class=note>※ 카드 상단 지도 = 파란 S(역) ↔ 빨간 핀(해당 식당) 위치(직선 근사). "
            "'콜키지프리' 태그가 곧 '위스키 무료 반입'을 보장하지 않습니다"
            "(와인 한정·병수·요일 제한 등 매장별 상이). 위스키신호는 간접 신호이며 방문 전 매장 확인 권장. "
            "지도=OSM/CARTO.</div>")
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
    var food=active('food'), whisky=active('whisky'), price=active('price');
    var shown=0;
    cards.forEach(function(c){
      var mj=c.getAttribute('data-major')||'';
      var ws=(c.getAttribute('data-whisky')||'').split('|').filter(Boolean);
      var pr=c.getAttribute('data-price')||'';
      var okFood = food.length===0 || food.indexOf(mj)>=0;            // 묶음 내 OR
      var okWh   = whisky.length===0 || ws.some(function(w){return whisky.indexOf(w)>=0;});
      var okPr   = price.length===0 || (pr!=='' && price.indexOf(pr)>=0);
      var ok = okFood && okWh && okPr;                                 // 묶음 간 AND
      c.classList.toggle('hide', !ok);
      if(ok) shown++;
    });
    countEl.textContent = '표시 '+shown+' / '+cards.length+'곳';
  }
  btns.forEach(function(b){ b.addEventListener('click', function(){
    b.classList.toggle('on'); apply();
  });});
  document.getElementById('freset').addEventListener('click', function(){
    btns.forEach(function(b){b.classList.remove('on');}); apply();
  });
  apply();
})();
</script>"""
    # ── 상세 모달(카드/사진 클릭 시) — 모바일 hover 대체(CMPA-66 board) ──
    modal_html = (
        "<div id=cf-ov class=cf-ov><div class=cf-mc>"
        "<span class=cf-x>×</span><img id=cf-mimg class=cf-mimg alt=''>"
        "<div id=cf-mbody></div></div></div>"
    )
    modal_js = (
        "<script>var DETAIL=" + json.dumps(details, ensure_ascii=False) + ";\n"
        "(function(){var ov=document.getElementById('cf-ov');"
        "var mb=document.getElementById('cf-mbody'),mi=document.getElementById('cf-mimg');"
        "function open(i){var d=DETAIL[i];if(!d)return;"
        "var card=document.querySelector('.card[data-idx=\"'+i+'\"]');"
        "var t=card?card.querySelector('.thumb'):null;"
        "if(t&&t.getAttribute('src')){mi.src=t.getAttribute('src');mi.style.display='block';}else{mi.style.display='none';}"
        "mb.innerHTML='<div class=cf-nm>'+d.nm+'</div><div class=cf-cat>'+d.cat+'</div>'"
        "+'<div class=cf-cost>'+d.cost+'</div><div class=cf-tags>'+d.tags+'</div>'"
        "+(d.pair?'<div class=cf-pair>'+d.pair+'</div>':'')"
        "+'<div class=cf-meta>'+d.meta+'</div>'"
        "+(d.menu||'')"
        "+'<div class=cf-links><a href=\"'+d.naver+'\" target=_blank>네이버지도</a></div>';"
        "ov.classList.add('show');document.body.style.overflow='hidden';}"
        "function close(){ov.classList.remove('show');document.body.style.overflow='';}"
        "[].slice.call(document.querySelectorAll('.card')).forEach(function(c){"
        "c.addEventListener('click',function(e){if(e.target.closest('a'))return;open(c.getAttribute('data-idx'));});});"
        "ov.addEventListener('click',function(e){if(e.target===ov||e.target.classList.contains('cf-x'))close();});"
        "document.addEventListener('keydown',function(e){if(e.key==='Escape')close();});})();</script>"
    )
    return (head + "".join(cards) + "</div>" + note + modal_html
            + script + modal_js + "</body></html>")


def backfill(station, radius_m=800, run_date=""):
    """라이브 재크롤 없이 기존 CSV에 대분류를 추가하고 CSV/MD/HTML 재생성(CMPA-65).

    기존 산출물(강남/합정)에는 분류기가 없던 시절 데이터가 들어 있으므로, DiningCode
    재호출 없이 디스크의 CSV만 읽어 `대분류`를 채우고 산출물을 다시 쓴다.
    HTML 역지도는 기존 *_map.png 를 재사용하고, 미니지도만 CSV 좌표로 재렌더한다.
    """
    run_date = run_date or kst_today()  # 리포트 작성일(최신성 판단 기준, CMPA-109)
    base = f"{station}_콜키지프리"
    csv_path = os.path.join(OUT_DIR, base + ".csv")
    if not os.path.exists(csv_path):
        print(f"  [skip] {csv_path} 없음", file=sys.stderr)
        return None
    with open(csv_path, encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))
    for r in rows:
        r["대분류"] = classify_major(r.get("카테고리", ""))
        _ps_short, ps_full, _alt_short, alt_full, ps_reason = pair_style_for_category(r.get("카테고리", ""))
        r["추천_위스키종류"] = ps_full
        r["대안_위스키종류"] = alt_full
        r["페어링근거"] = ps_reason
        # CMPA-102 마이그레이션: 외부 소스 브랜드 흔적 제거 — 프로필 URL 컬럼을
        # 내부 식별자(식당ID, rid 단독)로 바꾸고, 외부 CDN 사진 URL은 비운다.
        # 다코점수(다이닝코드 약칭) → 평판점수 로 디브랜딩(값·추천순 정렬은 그대로 유지).
        r["식당ID"] = row_rid(r)
        r["대표사진"] = ""
        if r.get("평판점수") in (None, "") and r.get("다코점수") not in (None, ""):
            r["평판점수"] = r.get("다코점수")
    lat, lng = STATION_COORDS.get(station, (None, None))
    # CSV 재기록(대분류 컬럼 포함, 원문 카테고리 유지)
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    snapshot(csv_path)
    os.makedirs(REPORT_DIR, exist_ok=True)
    # MD 재기록(분포표 + 대분류 컬럼) — reports/ 하위
    md_path = os.path.join(REPORT_DIR, base + ".md")
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(f"# {station} 위스키 콜키지프리 식당 (도보 {radius_m}m 이내)\n\n")
        f.write(f"📅 **리포트 작성일**: {run_date} — 최신성은 이 날짜를 기준으로 판단하세요\n\n")
        f.write(f"총 {len(rows)}곳 · "
                "거리=역 좌표 기준 직선 근사 · 콜키지 정책 세부는 매장 확인 필요\n\n")
        f.write(major_distribution_md(rows))
        f.write(_COST_NOTE)
        f.write(restaurant_table_md(rows))
    snapshot(md_path)
    # HTML 재기록 — 역지도는 기존 PNG 재사용, 미니지도는 CSV 좌표로 재렌더(재크롤 아님)
    map_uri = None
    try:
        from pipelines.corkage_free.mapshot import render_pair, to_data_uri
        from PIL import Image as _I
        png = os.path.join(OUT_DIR, base + "_map.png")
        if os.path.exists(png):
            map_uri = to_data_uri(_I.open(png))
        for r in rows:
            try:
                mp = render_pair(lat, lng, float(r["lat"]), float(r["lng"]), w=600, h=320)
                r["_mapuri"] = to_data_uri(mp)
            except Exception:  # noqa: BLE001
                r["_mapuri"] = None
    except Exception as e:  # noqa: BLE001
        print(f"  [warn] 지도 재사용/렌더 실패: {e}", file=sys.stderr)
    whisky_rows = [r for r in rows if r.get("위스키신호")][:12]
    html_path = os.path.join(REPORT_DIR, base + ".html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(_render_html(station, rows, radius_m, map_uri, whisky_rows, run_date=run_date))
    snapshot(html_path)
    cnt = major_counts(rows)
    print(f"[backfill] {station}: {len(rows)}곳 · " +
          " / ".join(f"{b} {c}" for b, c in cnt.items() if c))
    unc = sum(1 for r in rows
              if r["대분류"] == MAJOR_UNCLASSIFIED and
              classify_major(r.get("카테고리", "")) == MAJOR_UNCLASSIFIED and
              not any(kw in (r.get("카테고리") or "")
                      for _, kws in MAJOR_RULES for kw in kws))
    print(f"           미분류(폴백, 키워드 0매칭) {unc}곳 "
          f"= {round(100*unc/max(1,len(rows)))}%")
    return csv_path, md_path, html_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--station", default="강남역")
    ap.add_argument("--radius", type=int, default=800, help="도보 반경(m), 기본 800≈12분")
    ap.add_argument("--lat", type=float, default=None)
    ap.add_argument("--lng", type=float, default=None)
    ap.add_argument("--whisky-only", action="store_true")
    ap.add_argument("--keep-suspect", action="store_true",
                    help="유료의심 매장도 제외하지 않고 ⚠️ 표시만(기본=제외)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--backfill", action="store_true",
                    help="라이브 재크롤 없이 기존 CSV에 대분류 추가 후 산출물 재생성")
    a = ap.parse_args()

    if a.backfill:
        targets = [a.station] if a.station != "강남역" or "--station" in sys.argv \
            else ["강남역", "합정역"]
        for st in targets:
            backfill(st, a.radius)
        return

    if a.lat is not None and a.lng is not None:
        lat, lng = a.lat, a.lng
    elif a.station in STATION_COORDS:
        lat, lng = STATION_COORDS[a.station]
    else:
        print(f"[오류] '{a.station}' 좌표 미등록. --lat/--lng 로 지정하거나 "
              "STATION_COORDS 확장.", file=sys.stderr)
        sys.exit(2)

    rows = find(a.station, lat, lng, a.radius, a.whisky_only, a.keep_suspect)
    print(f"[결과] {a.station} 도보 {a.radius}m 이내 콜키지프리 {len(rows)}곳 "
          f"(위스키신호 {sum(1 for r in rows if r['위스키신호'])}곳)")
    for r in rows[:12]:
        print(f"  {r['순위']:>2}. {r['식당명']}  {r['도보_분']}분  "
              f"[{r['콜키지태그']}] 위스키:{r['위스키신호'] or '-'}  "
              f"{r.get('평판점수') or r.get('다코점수') or ''}/{r['user_score']}")
    if a.dry_run:
        print("[dry-run] 저장 생략")
        return
    csv_path, md_path, html_path = save(a.station, rows, a.radius, lat, lng)
    print(f"[저장] {csv_path}\n       {md_path}\n       {html_path}")


if __name__ == "__main__":
    main()
