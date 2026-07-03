# 저녁 약속 활성도 역 랭킹 (evening-hotspot-stations)

서울 지하철역을 **저녁 약속(회식·술자리·저녁 외식) 활성도** 기준으로 랭킹한 내부 데이터셋.
콜키지프리 식당 finder([CMPA-55], `pipelines/corkage_free`)를 **어느 역부터 돌릴지** 정하는 입력값.

- 생성: `python3 pipelines/evening_stations/rank_evening_stations.py`
- 산출: `evening-hotspot-stations.csv` (정본/최신) + `evening-hotspot-stations.md` (사람용 표)
  - 일자별 스냅샷은 `_runs/…__run<날짜>.csv` (CMPA-38 dated.py 규칙)
- 기준일: 2026-05-31 · 대상 역: 35개 (finder 기존 11역 + 저녁 상권 24역)

## 컬럼

| 컬럼 | 의미 |
|---|---|
| `rank` | 저녁활성도 점수 내림차순 순위 |
| `station` | 역명 (finder `STATION_COORDS` 키와 동일 표기) |
| `lat`,`lng` | WGS84 좌표 — **finder `STATION_COORDS` 스키마와 동일** |
| `score` | 가중합 점수 (아래 프록시) |
| `score_norm` | 풀 내 최대값(강남역) 대비 0~100 정규화 |
| `cnt_회식`/`cnt_술집`/`cnt_이자카야`/`cnt_와인바`/`cnt_포차` | 점수 근거 raw 지표 (질의별 검색 건수) |
| `source`,`as_of` | 출처·기준일 |

## 방법론 (프록시)

"저녁 약속이 많다"를 직접 세는 공개 지표는 없다. DiningCode isearch(키 불필요, finder와 동일 소스)의
역별 질의 **결과 건수 `total_cnt`** 를 간접 프록시로 사용한다. `total_cnt` = "그 역세권에 해당 업종/상황의
식당이 몇 곳 잡히나"(DiningCode 빅데이터 기준).

| 질의 | 의미 | 가중치 |
|---|---|---|
| `{역} 회식` | 직장 회식·단체 저녁 | 1.5 (저녁 약속에 가장 직접) |
| `{역} 와인바` | 콜키지 수요 큰 업종 | 1.3 (finder와 직결) |
| `{역} 이자카야` | 사케/하이볼/위스키 친화 | 1.2 (위스키 후크) |
| `{역} 술집` | 저녁 술자리 전반 | 1.0 |
| `{역} 포차` | 2차·심야 술자리 | 0.8 |

`score = Σ(가중치 × total_cnt)`.

## ⚠️ 한계 (정직성)

- `total_cnt` 는 "저녁 약속 건수"가 아니라 **역세권 해당 업종 등록 식당 수**의 간접 신호.
  대형 상권일수록 모든 업종 수가 커져 '상권 규모'와 '저녁 특화도'가 섞여 있다.
- DiningCode 커버리지 편향(등록·리뷰 많은 지역 과대) 존재. 환승 허브(예: 서울역)는 dining 밀도가
  낮아 낮게 잡힘 — 의도된 결과(저녁 약속 상권 ≠ 교통 허브).
- 역 좌표는 내장 사전(`STATION_COORDS_POOL`). 정밀 도보권 분석엔 서울교통공사 역사 좌표 공공데이터 권장.
- **내부 R&D(수집→측정) 산출물.** 이 데이터/DiningCode 큐레이션을 공개·배포 surface에 재게시하려면
  별도 CEO 법무 승인 필요(데일리샷·싼디 건과 동일 가드레일).

## finder에 흘려보내기 (검증됨)

상위 N개 역을 그대로 finder에 투입할 수 있다. 좌표가 `STATION_COORDS` 스키마와 동일하므로,
finder 내장 사전에 없는 역도 CSV의 `lat`/`lng` 로 바로 호출된다:

```bash
python3 pipelines/corkage_free/find_corkage_free.py \
  --station 을지로3가역 --lat 37.566295 --lng 126.991053 --radius 800
```

검증: 위 명령(랭킹 3위, finder 사전 미등록 역)으로 콜키지프리 36곳·위스키신호 5곳 정상 반환 확인.
```

[CMPA-55]: ../../pipelines/corkage_free/README.md
