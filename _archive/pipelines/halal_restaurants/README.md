# halal — 지하철역 기준 무슬림(할랄) 식당 탐색기 (CMPA-81)

무슬림(이슬람교도)이 먹을 수 있는 식당을 지하철역 도보권에서 찾아 **2-tier**로 분류한다.
콜키지프리맵과 **별도의 독립 폴더**다(CEO 지시: 위스키 폴더와 분리, 필요한 코드는 복사해 사용).

> 설계 배경·리서치 전문: CMPA-81 plan 문서. 데이터 핸드오프: [`data/halal-restaurants/README.md`](../../data/halal-restaurants/README.md)

## 왜 별도 폴더 / fork 인가
CEO 승인 피드백: *"폴더를 아얘 다르게 해서 … 위스키쪽에서 쓰고 싶은 코드나 산출물이 있으면 복사해서 사용."*
→ `pipelines/corkage_free/find_corkage_free.py` 의 검증된 엔진 조각(**`dc_search`**, **`haversine_m`**,
`classify_major`, `clean`, `STATION_COORDS`, 날짜 스냅샷)을 **복사**해 와서 콜키지/위스키 로직만
**할랄 2-tier 분류**로 교체했다. `import`로 묶지 않으므로 콜키지맵 변경과 독립적으로 진화한다.

## 2-Tier 분류

| 등급 | 정의 | CEO 요청 매핑 |
|------|------|----------------|
| **A · 명시할랄** | 이름/카테고리/키워드에 `할랄·halal·무슬림·이슬람·모스크` 신호 | "할랄이라고 나온 식당" |
| **B · 추정(확인필요)** | 명시는 없지만 **할랄친화 cuisine**(인도/중동/터키/말레이/인니/파키스탄…) 또는 **해산물·생선 업종** 또는 **채식**, 그리고 돼지·술 중심이 아닌 곳 | "생선 등 가능한데 할랄 표기 없는 곳" |
| 제외 | 돼지(삼겹·족발·보쌈·돈까스·순대·곱창류)·술 중심, 신호 없음 | — |

`PORK_RX`/`BOOZE_RX` 가 A/B 후보에서 돼지·술 중심 매장을 걷어낸다(POC에서 고기뷔페가 '회'에
걸려 B로 잘못 들어가던 오탐을 차단 — plan §5).

## 정직성 / 한계 (종교 식이 — 콜키지맵보다 강한 고지)
- 우리는 어떤 식당도 **"할랄이다"라고 단정하지 않는다.** Tier B 는 *추정 후보*.
- 자바이하(이슬람식 도축)·숨은 돼지파생물(라드/젤라틴/육수)·조리용 알코올은 데이터로 확인 불가
  → 전 행 `주의` 컬럼에 "매장 확인 필수" 명시. 정식 인증은 KMF(한국이슬람교중앙회) 기준.
- 도보거리는 직선 근사(haversine). DiningCode 데이터의 공개/상업 재게시는 **CEO 법무 게이트** 대상.

## Tier B 오탐 정제 (CMPA-86 item 3, 완료)
부분문자열 매칭 노이즈를 다음으로 제거(`test_halal_tier.py` 17/17 통과):
1. **cuisine 신호는 이름+카테고리(catname)에서만** 찾는다 — 메뉴 키워드(`두바이초콜릿`)
   오탐 차단. `두바이` 토큰은 디저트 트렌드 노이즈라 목록에서 제거.
2. **STRONG/WEAK 분리** — 신뢰 에스닉 토큰(인도/케밥/터키/중앙아시아…)은 STRONG,
   다른 요리권에 섞이는 `커리/카레/난`은 WEAK.
3. **NOISE_RX 베토** — 디저트·카페·태국·일식 컨텍스트면 WEAK cuisine·해산물·채식 추정 무효
   (예: 태국요리↔커리, 일본식 카레, 와플대학↔두바이초콜릿 → 모두 제외).
→ 이태원역 B 33→28곳(오탐 5건 제거), A 25 유지.

## 공공 오픈데이터 ingest (CMPA-86 item 1, `ingest_opendata.py`)
KTO 무슬림친화 4분류(공인/자가인증/프렌들리/포크프리)를 우리 등급으로 매핑하는
**Tier A 권위 정본** 파이프라인. `출처` 컬럼=발급기관명(재게시 가능 라이선스 표시).
- 매핑·정규화·유연 헤더 로직은 `test_ingest_opendata.py`(fixture, 무네트워크) **검증 완료**.
- ⚠️ **라이브 ingest 는 차단**: `data.go.kr`/`apis.data.go.kr` egress 차단(probe HTTP 000) +
  TourAPI 승인 serviceKey 필요. → **CEO 가 serviceKey 발급/승인 + egress 허용** 제공해야 가동.
  그 전까지 `--csv <수동다운로드>` 경로로 정규화 가능.
```bash
python3 pipelines/halal_restaurants/ingest_opendata.py --csv <data.go.kr.csv> --source 한국관광공사 --name 전국
```

## 용법
```bash
python3 pipelines/halal_restaurants/find_halal.py --station 이태원역 --radius 800
python3 pipelines/halal_restaurants/find_halal.py --station 안산역 --radius 1000
python3 pipelines/halal_restaurants/find_halal.py --station 신촌역 --lat 37.555 --lng 126.936   # 미등록 역
```
산출물(폴더 분리, corkage-free 동일): **데이터셋 csv** → `data/halal-restaurants/`,
**사람이 보는 리포트 md/html** → `reports/halal-restaurants/`. 각 디렉터리 `_runs/` 날짜 스냅샷.
(스키마 = data README §2.)
**HTML 카드뷰(CMPA-86 item 2)**: 등급(A/B) 배지·근거·주의·면책 고지 배너 + 등급×음식 필터.
`find_corkage_free` HTML 라이터를 fork·적응(위스키/비용 제거, 종교 식이 고지 강화).

## 결과 (2026-05-31)
- **이태원역** (800m): 후보 208 → A·명시 **25** · B·추정 **28**(정제 후) · 제외 155.
- **안산역** (원곡동 다문화, 1000m): 후보 133 → A·명시 **2** · B·추정 **14** · 제외 40.

## 테스트
```bash
python3 pipelines/halal_restaurants/test_halal_tier.py        # Tier 분류 오탐 정제 (17 케이스)
python3 pipelines/halal_restaurants/test_ingest_opendata.py   # 공공데이터 KTO 매핑·헤더 정규화
```
