#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rank_evening_stations.py — 서울 지하철역 "저녁 약속 활성도" 랭킹 (CMPA-60)

목적
----
보드 요청(CMPA-59): "저녁 약속이 많은 지하철역"을 데이터로 랭킹해 두면,
콜키지프리 식당 finder([CMPA-55] pipelines/corkage_free)를 **어느 역부터 돌릴지**
정하는 입력값으로 쓸 수 있다. 송객(送客) 후크 가치가 큰 역부터 finder를 돌린다.

프록시 (왜 이 신호인가)
-----------------------
"저녁 약속(회식·술자리·저녁 외식)이 많다"를 직접 세는 공개 지표는 없다. 대신
DiningCode isearch(키 불필요, finder와 동일 소스)의 역별 질의 **결과 건수(total_cnt)**
를 간접 프록시로 쓴다. 각 질의는 "그 역세권에 해당 업종/상황의 식당이 몇 곳 잡히나"를
DiningCode 빅데이터 기준으로 돌려준다(실측: poi_section.total_cnt).

  질의            의미                                   가중치  근거
  {역} 회식        직장 회식·단체 저녁자리                  1.5    '저녁 약속'에 가장 직접
  {역} 술집        술 마시는 저녁 자리 전반                 1.0    저녁활성도 기본 신호
  {역} 이자카야    사케/하이볼/위스키 친화 술집             1.2    위스키 후크와 직결
  {역} 와인바      콜키지 수요가 큰 업종                    1.3    finder(콜키지)와 직결
  {역} 포차        2차·심야 술자리                         0.8    저녁→심야 연장 신호

저녁활성도 점수 = Σ(가중치 × 질의별 total_cnt). 0~100 정규화 점수(score_norm)는
풀 내 최대값 대비 비율. rank 는 raw 가중합 기준 내림차순.

정직성/한계
-----------
- total_cnt 는 "저녁 약속 건수"가 아니라 "그 역세권 해당 업종 등록 식당 수"의 간접 신호.
  대형 상권일수록 모든 업종 수가 커지므로 '상권 규모'와 '저녁 특화도'가 섞여 있다.
- DiningCode 커버리지 편향(등록·리뷰 많은 지역 과대) 존재.
- 역 좌표는 내장 사전(STATION_COORDS_POOL, WGS84). finder STATION_COORDS 와 동일 스키마.
- 내부 R&D(수집→측정) 산출물. 이 데이터를 공개/배포 surface에 재게시하려면
  별도 CEO 법무 승인 필요(데일리샷·싼디 건과 동일 가드레일).

용법
----
  python3 pipelines/evening_stations/rank_evening_stations.py            # 전체 풀, 저장
  python3 pipelines/evening_stations/rank_evening_stations.py --dry-run  # 저장 안 함
  python3 pipelines/evening_stations/rank_evening_stations.py --top 10   # 콘솔 상위 N
"""
import argparse
import csv
import os
import sys
import time

import requests

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, ROOT)
from pipelines.common.dated import snapshot  # noqa: E402

API = "https://im.diningcode.com/API/isearch/"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")
OUT_DIR = os.path.join(ROOT, "data", "stations")
SOURCE = "DiningCode isearch total_cnt (키 불필요 내부검색 API)"
AS_OF = "2026-05-31"

# 역 좌표(WGS84). finder STATION_COORDS 와 동일 스키마(역명→(lat,lng)).
# 기존 finder 11개 역 + 저녁 상권으로 알려진 서울 주요 역 확장.
STATION_COORDS_POOL = {
    # --- finder 기존 사전과 동일 ---
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
    # --- 저녁 약속 상권 확장 ---
    "신논현역": (37.504598, 127.025116),
    "교대역": (37.493415, 127.014277),
    "사당역": (37.476559, 126.981633),
    "신촌역": (37.555134, 126.936893),
    "이태원역": (37.534520, 126.994374),
    "종각역": (37.570420, 126.982998),
    "종로3가역": (37.571607, 126.991806),
    "을지로입구역": (37.565989, 126.982624),
    "을지로3가역": (37.566295, 126.991053),
    "건대입구역": (37.540505, 127.069126),
    "압구정역": (37.527075, 127.028642),
    "압구정로데오역": (37.527341, 127.040283),
    "신사역": (37.516382, 127.020029),
    "강남구청역": (37.517186, 127.041011),
    "수유역": (37.638146, 127.025518),
    "노원역": (37.655128, 127.061368),
    "영등포역": (37.515496, 126.907499),
    "왕십리역": (37.561533, 127.037684),
    "구로디지털단지역": (37.485266, 126.901401),
    "혜화역": (37.582336, 127.001834),
    "강변역": (37.535095, 127.094681),
    "문래역": (37.518072, 126.894651),
    "신림역": (37.484201, 126.929715),
    "시청역": (37.564718, 126.977108),
}

# (질의 키워드, 가중치) — 위 docstring 표와 일치
EVENING_QUERIES = [
    ("회식", 1.5),
    ("술집", 1.0),
    ("이자카야", 1.2),
    ("와인바", 1.3),
    ("포차", 0.8),
]

CSV_FIELDS = (["rank", "station", "lat", "lng", "score", "score_norm"]
              + [f"cnt_{kw}" for kw, _ in EVENING_QUERIES]
              + ["source", "as_of"])


def query_total_cnt(query, sleep=0.35, retries=2):
    """DiningCode isearch 호출 → poi_section.total_cnt 반환(없으면 0).
    size=1 로 페이로드 최소화(우린 건수만 필요)."""
    body = {"query": query, "addr": "", "keyword": query,
            "order": "r_score", "from": 0, "size": 1}
    for attempt in range(retries + 1):
        try:
            resp = requests.post(
                API, data=body,
                headers={"User-Agent": UA,
                         "Content-Type": "application/x-www-form-urlencoded"},
                timeout=25)
            resp.raise_for_status()
            ps = resp.json().get("result_data", {}).get("poi_section", {})
            return int(ps.get("total_cnt") or 0)
        except Exception as e:  # noqa: BLE001
            if attempt < retries:
                time.sleep(1.0 + attempt)
                continue
            print(f"  [warn] '{query}' 실패: {e}", file=sys.stderr)
            return 0
        finally:
            time.sleep(sleep)
    return 0


def rank(stations):
    rows = []
    for station in stations:
        lat, lng = STATION_COORDS_POOL[station]
        counts, score = {}, 0.0
        for kw, weight in EVENING_QUERIES:
            c = query_total_cnt(f"{station} {kw}")
            counts[kw] = c
            score += weight * c
        row = {"station": station, "lat": lat, "lng": lng,
               "score": round(score), "source": SOURCE, "as_of": AS_OF}
        for kw, _ in EVENING_QUERIES:
            row[f"cnt_{kw}"] = counts[kw]
        rows.append(row)
        print(f"  {station:<10} score={row['score']:>6}  "
              + " ".join(f"{kw}:{counts[kw]}" for kw, _ in EVENING_QUERIES),
              file=sys.stderr)
    rows.sort(key=lambda r: -r["score"])
    max_score = rows[0]["score"] if rows and rows[0]["score"] else 1
    for i, r in enumerate(rows, 1):
        r["rank"] = i
        r["score_norm"] = round(100 * r["score"] / max_score, 1)
    return rows


def save(rows):
    os.makedirs(OUT_DIR, exist_ok=True)
    csv_path = os.path.join(OUT_DIR, "evening-hotspot-stations.csv")
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    snapshot(csv_path)

    md_path = os.path.join(OUT_DIR, "evening-hotspot-stations.md")
    qcols = " | ".join(kw for kw, _ in EVENING_QUERIES)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write("# 서울 지하철역 저녁 약속 활성도 랭킹\n\n")
        f.write(f"- 출처: {SOURCE}\n- 기준일: {AS_OF}\n")
        f.write("- 프록시: 역별 `{역} 회식/술집/이자카야/와인바/포차` 검색 결과 건수"
                "(total_cnt)의 가중합. 가중치 회식1.5·이자카야1.2·와인바1.3·술집1.0·포차0.8\n")
        f.write("- 용도: 콜키지프리 finder([CMPA-55](/CMPA/issues/CMPA-55)) 대상 역 선정 입력값. "
                "좌표는 finder `STATION_COORDS` 스키마와 동일.\n")
        f.write("- ⚠️ 한계: total_cnt 는 '저녁 약속 건수'가 아니라 역세권 해당 업종 등록 식당 수의 "
                "간접 신호. 상권 규모와 저녁 특화도가 섞임. DiningCode 커버리지 편향 존재. 내부 R&D용.\n\n")
        f.write(f"| rank | 역 | score | norm | {qcols} |\n")
        f.write("|---|---|---|---|" + "---|" * len(EVENING_QUERIES) + "\n")
        for r in rows:
            cnts = " | ".join(str(r[f"cnt_{kw}"]) for kw, _ in EVENING_QUERIES)
            f.write(f"| {r['rank']} | {r['station']} | {r['score']} | "
                    f"{r['score_norm']} | {cnts} |\n")
    snapshot(md_path)
    return csv_path, md_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--top", type=int, default=15, help="콘솔 미리보기 상위 N")
    ap.add_argument("--stations", nargs="*", default=None,
                    help="특정 역만(기본=내장 풀 전체)")
    a = ap.parse_args()

    stations = a.stations or list(STATION_COORDS_POOL)
    bad = [s for s in stations if s not in STATION_COORDS_POOL]
    if bad:
        print(f"[오류] 좌표 미등록 역: {bad}", file=sys.stderr)
        sys.exit(2)

    print(f"[조회] {len(stations)}개 역 × {len(EVENING_QUERIES)}개 질의 "
          f"= {len(stations)*len(EVENING_QUERIES)} 요청", file=sys.stderr)
    rows = rank(stations)

    print(f"\n[랭킹] 저녁 약속 활성도 상위 {a.top}개 역")
    for r in rows[:a.top]:
        print(f"  {r['rank']:>2}. {r['station']:<10} score={r['score']:>6} "
              f"(norm {r['score_norm']:>5})  "
              + " ".join(f"{kw}={r[f'cnt_{kw}']}" for kw, _ in EVENING_QUERIES))

    if a.dry_run:
        print("\n[dry-run] 저장 생략")
        return
    csv_path, md_path = save(rows)
    print(f"\n[저장] {csv_path}\n       {md_path}")


if __name__ == "__main__":
    main()
