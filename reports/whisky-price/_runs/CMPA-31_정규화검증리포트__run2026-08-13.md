# CMPA-31 데이터 정규화·검증 리포트

> `scripts/normalize_dataset.py` 1회 실행 결과. 재실행 가능. 수집 4종(유튜브/마트웹·데일리샷·해외) raw → 정본 위스키 id 정규화·클렌징.

- 입력 raw 행: **2,761**  ·  distinct raw 표기: **1,782**
- 정규화(병합) 후 정본 SKU 수: **138** (whisky-list.csv 89종 중)
- 통합 데이터셋(clean 단품) 행: **1,426**
- 오염행 제거(과거평균 ⅓~3배 밖): **20**

> ⚠️ 신뢰도: 국내(한글) 매칭은 명시적 사전(match/not) 기반 고신뢰. 해외 매칭(24행, reason=`en`)은 name_en 브랜드+년수 토큰 휴리스틱이라 보조(advisory) 신뢰도 — 리포트 본표 반영 전 스팟체크 권장. 모호(후보 2개↑)는 미매칭 처리.

## 소스별 정규화/제외 집계

| 소스 | 입력스킵 | matched | unmatched | 비위스키제외 | 비단품제외 | 가격결측 | 오염제거 |
|---|--:|--:|--:|--:|--:|--:|--:|
| youtube_martweb | 0 | 779 | 38 | 18 | 7 | 0 | 5 |
| dailyshot | 93 | 74 | 1 | 0 | 0 | 0 | 2 |
| overseas | 0 | 36 | 1,178 | 0 | 13 | 0 | 12 |
| **합계** | 93 | 889 | 1,217 | 18 | 20 | 0 | 19 |

## 표기변형 병합 예시 (raw 표기 ≥ 3종 → 1 SKU)

- **[w066] 잭다니엘 No.7** ← 16종: `잭 다니에 700ml`, `잭 다니엘스 200ml`, `잭 다니엘스 테네시 위스키 1L`, `잭다니스 1L`, `잭다니엘 No.7`, `잭다니엘 싱글배럴 잔패키지` …
- **[w065] 짐빔 화이트** ← 13종: `진빈 법원 유스키 1L`, `진빔`, `진빔 1L`, `진빔 700ml`, `진빔 버유스키 1L`, `진빔 법원이스키 1L` …
- **[w053] 조니워커 블루라벨** ← 13종: `조니어커 블루`, `조니워커 블로라 750ml`, `조니워커 블루 500ml`, `조니워커 블루 700ml`, `조니워커 블루 750ml`, `조니워커 블루 750mml` …
- **[w018] 글렌드로낙 12년** ← 12종: `GlenDronach - 12y, Original, 43%`, `글랜드로 12년 700ml`, `글랜드로 오드 to투더 엠버스 700ml`, `글랜드로 오드투더 다크 700ml`, `글랜드로 오드투더 밸리 700ml`, `글랜드로 오드트 더더밸리` …
- **[w067] 잭다니엘 애플** ← 11종: `잭 다니엘스 애플 1L`, `잭 다니엘스 애플 200ml`, `잭 다니엘스 애플 500mml`, `잭다니에스 애플 1L`, `잭다니엘 애플`, `잭다니엘 애플 1L` …
- **[w050] 조니워커 블랙라벨 12년** ← 11종: `조니어커 블랙`, `조니워커 블랙`, `조니워커 블랙 1.75L`, `조니워커 블랙 200ml`, `조니워커 블랙 700ml`, `조니워커 블랙라베 700ml` …
- **[w008] 발베니 12년 더블우드** ← 11종: `발베니 12년`, `발베니 12년 700ml`, `발베니 12년 더블 우드 700ml`, `발베니 12년 더블로드 700ml`, `발베니 12년 더블우드`, `발베니 12년 더블우드 700ml` …
- **[w042] 조니워커 그린라벨 15년** ← 10종: `조니어 그린`, `조니워커 그린`, `조니워커 그린 15년`, `조니워커 그린 700ml`, `조니워커 그린납`, `조니워커 그린납L` …
- **[w088] 탈리스만 9년 포르투기즈 캐스크** ← 8종: `탈리스마 위스키 1L`, `탈리스만 9년`, `탈리스만 9년 포르투기즈 캐스크`, `탈리스만 9년 포르투기즈 캐스크 700ml`, `탈리스만 9년 포르투기즈 캐스크 에디션`, `탈리스만 위스키` …
- **[w084] 카발란 디스틸러리 셀렉트** ← 8종: `카발란 디스틸러 리셀레트 싱글 몰트 700ml`, `카발란 디스틸러리 셀렉트`, `카발란 디스틸러리 셀렉트 700ml`, `카발란 디스틸러리 셀렉트 싱글 700ml`, `카발란 디스틸러리 셀렉트 싱글 몰트`, `카발란 디스틸러리 셀렉트 싱글 몰트 700ml` …
- **[w080] 에반 윌리엄스 블랙** ← 8종: `에반 윌리엄스 블랙`, `에반 윌리엄스 블랙 1.75L`, `에반 윌리엄스 블랙 1750ml`, `에반 윌리엄스 블랙 1L`, `에반 윌리엄스 블랙 1l`, `에반 윌리엄스 블랙 750mml` …
- **[w061] 제임슨** ← 8종: `제임스 나이시 위스키 700ml`, `제임슨`, `제임슨 700ml`, `제임슨 스탠다드`, `제임슨 스탠더드`, `제임슨 스탠더드 700ml` …

## 미매칭 raw 표기 (1245종) — 마스터 SKU 확장 후보

> 정본 미등록이거나 해외(영문/중문) 매칭 규칙 밖. 무리한 병합 대신 미매칭으로 남김(서로 다른 제품 오병합 방지 원칙).

- `*PRE-ORDER 預訂* Kowloon Spirits  - Single Malt Whiskey Exclusive Barrel, 750ml`
- `1776 波本威士忌`
- `1776 裸麥威士忌`
- `Aberfeldy - Single Malt Scotch Whisky 12y, 40%, 75cl`
- `Adelphi - Islay (Caol Ila) 10y, Single Malt Whisky, 46%,70cl, 1800B`
- `Adelphi - Loyal Old Mature Private Stock, Blended Scotch Whisky, 40%, 70cl`
- `Adelphi - Private Stock Reserve 8y, Peated blend, 46%, 70cl, 1800B`
- `Adelphi - Speyside (Glen Elgin) 10y, Single Malt Whisky, 46%,70cl, 1800B`
- `Adelphi - The Kincardine, Single Malt Scotch + Indian Whisky 7y, 52.9%, 820b`
- `Adelphi Limited - Benrinnes 33y, 1984, 57.3%, 395b`
- `Adelphi Limited - Breath of Speyside 30y, 1992, 50.3%, 194b`
- `Adelphi Limited - Bunnahabhain 23y, 1998, 53.5%, 587b, IB Single Malt Scotch Whisky`
- `Adelphi Limited - Glen Grant 22y, 1985, 62.1%, 64b, IB Single Malt Scotch Whisky`
- `Adelphi Limited - Glen Grant 28y, 1992, 52.5%, 185b`
- `Adelphi Limited - Miltonduff 36y, 1981, 51.8%, 138b`
- `Adelphi Limited - Mortlach 25y, 1993, 56.1%, 385b`
- `Adelphi Limited - Mortlach 36y, 1986, 51.4%, 176b`
- `Adelphi Limited - Teaninich 34y, 1983, 44%, 190b`
- `Adelphi Selection - Ardmore 8y Refill Oloroso Butt, 2016, 59.7%, 632b`
- `Adelphi Selection - Arran 11y Refill Oloroso HHD Unpeated , 2014, 57.6%, 318b`
- `Adelphi Selection - Ben Nevis 11y Refill Oloroso Butt 2013, 59.9%, 624b`
- `Adelphi Selection - Benrinnes 11y, 2011, 56.2%, 341b`
- `Adelphi Selection - Benrinnes 14y Refill Oloroso HHD 2011, 56.2%, 282b`
- `Adelphi Selection - Caol Ila 10y 2014, 55.4%, 310b`
- `Adelphi Selection - Chichibu 7y, 2013, 57.8%, 210b`
- `Adelphi Selection - Clynelish 9y, Refill Oloroso Butt, 2015-2024, 54.5%, 477b`
- `Adelphi Selection - Dailuaine 10y, 2015, 57.9%, 311b`
- `Adelphi Selection - Dailuaine 12y Refill Oloroso HHD 2013, 53.5%, 265b`
- `Adelphi Selection - Fascadale Batch 10 Highland Park 14y, 46%`
- `Adelphi Selection - Glen Garioch 13y 1st Fill ASB , 2011, 57%, 231b`
- `Adelphi Selection - Glen Garioch 9y, 2011, 58.5%, 462b`
- `Adelphi Selection - Glen Keith, 23y, 1995, 60.5%, 137b`
- `Adelphi Selection - Glenrothes 15y, 2007, 59.6%, 389b`
- `Adelphi Selection - Inchgower 14y, 2010, 57.7%, 542b`
- `Adelphi Selection - Linkwood 10y Refill Oloroso HHD 2015, 56.4%, 238b`
- `Adelphi Selection - Linkwood 11y, 2011, 59.1%, 255b`
- `Adelphi Selection - Linkwood 14y, 2008, 1st Fill Olo Sherry HHD, 50.9%, 267b`
- `Adelphi Selection - Lochranza, Isle of Arran 10y, 1st Fill Bourbon (Peated) 2014, 57.1%, 230b`
- `Adelphi Selection - Mortlach 17y, 2003, 56.6%, 228b`
- `Adelphi Selection - Teaninch 16y, Refill Oloroso Sherry Cask, 56.4%, 207b`
- … 외 1205종 (전체는 `assets/whisky-aliases.csv` status=unmatched)

## 산출물

- `data/whisky-prices/normalized/normalized_prices.csv` — 정규화된 통합 데이터셋(clean 단품)
- `data/whisky-prices/normalized/normalized_all_rows.csv` — 전수 행(제외/오염 사유 포함, 감사용)
- `assets/master-sku.csv` — 마스터 SKU 사전(정본 id별 별칭수·행수·마켓·가격대)
- `assets/whisky-aliases.csv` — 별칭 사전(raw→정본 id, 전 소스 전수)

