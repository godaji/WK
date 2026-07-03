# 국내 마트(코스트코) 웹 가격 수집기 (CMPA-28)

유튜브(싼디)로 안 잡히는 **국내 마트 온라인/웹 가격**(코스트코 우선)을 주간 수집한다.
기존 "코스트코 단건 수동 WebSearch"를 반복 가능한 스크립트로 자동화한 것.

## 실행

```bash
python3 pipelines/costco_web/collect_costco_web.py            # 수집 + 해당월 CSV append
python3 pipelines/costco_web/collect_costco_web.py --dry-run  # 콘솔만, 파일 미수정
python3 pipelines/costco_web/collect_costco_web.py --limit 8  # 기사 N건 스모크
python3 pipelines/costco_web/collect_costco_web.py --month 2026-05
```

- 산출: `data/whisky-prices/YYYY-MM.csv` 에 `위치=코스트코` 행 append (정본 7컬럼 스키마, UTF-8 BOM)
- 메트릭: `data/whisky-prices/_costco_web_metrics.json`
- 같은 달 재실행은 `(술이름,가격)` 기준 멱등(중복 미append)

## 왜 공식몰이 아니라 2차 소스인가 (핵심 제약)

한국은 **주류 통신판매(온라인 판매) 금지**다. 그래서 코스트코·이마트·롯데마트의 공식
e-commerce 에는 **위스키 상품 자체가 노출되지 않는다.**

- 실측: `costco.co.kr` 의 Hybris REST
  `GET /rest/v2/korea/products/search?query=위스키` → 하이볼잔·토닉워터·김치냉장고만 반환,
  **위스키 0건.** (alcohol online-sales ban)

따라서 "마트 웹 가격"은 공식몰 크롤이 불가능하고, **매장 가격표를 추적·게시하는 2차 웹
소스**에서 얻어야 한다. 1차 소스로 **costcome.com(코스트컴)** 채택:

- 코스트코 매장 위스키 가격/할인 이력을 상품별 기사로 정리·자동 갱신하는 가격추적 블로그.
- 수집 경로: 위스키 카테고리(`/category/item/whiskey/`)에서 상품 기사 URL 열거 →
  각 기사 본문의 "코스트코 … 정상 판매 가격은 X원" 현재가 추출.
- 위스키 관련성 게이트(위스키 토큰/브랜드 allowlist + 비위스키 denylist)로 추천·관련 글
  (커피머신 등) 누수 차단.

## 데일리샷 수집기(CMPA-19)와의 분담

- `pipelines/dailyshot` = 데일리샷 **스마트오더 마켓플레이스 최저가**(이마트/트레이더스/코스트코
  공통, 채널 비특정).
- 본 수집기 = **코스트코 매장가 특정**(점포단위 가격표 기반 2차 소스). 코스트코 우선 과업.
- 두 소스의 코스트코 행은 후속 정규화(CMPA-29)에서 정본 id 로 병합·교차검증된다.

## 정직성 / 한계

- costcome 가격은 "포스팅 갱신 시점" 코스트코 매장가 → **실시간 아닐 수 있어 신뢰도=중.**
- 코스트코는 점포·시기별 가격 편차가 있어 **단일 대표가**로 본다(비고에 점포미상 명시).
- 가격은 **수집 등급(중)** 이며 후속 검증(CMPA-30)에서 스팟체크 대상.
  특히 1L/1.75L·잔패키지·번들은 병당가 왜곡 가능(비고/용량 표기 유지) → 정규화 단계서 분리.
- 이마트·롯데마트는 동급 2차 추적 소스 확보 시 동일 패턴으로 확장(현재 코스트코 한정).
- 비고에 `정본=<id>(<name_ko>)` 힌트는 `scripts/normalize_whisky_name.py` best-effort 매칭
  (실패해도 raw 표기로 수집 진행). 정본 dedup 의 책임 소스는 `assets/whisky-synonyms.yaml`.

## 주간 루틴

매주 월 10:00 KST Paperclip 루틴이 DataEngineer 를 깨워 본 스크립트를 실행 →
해당 월 CSV 에 신규/변동 코스트코 행 append. 상세: CMPA-1 `price-tracker` 문서.
costcome 가 못 잡는 추적대상은 에이전트가 WebSearch(`코스트코 <위스키명> 가격`)로 보강 가능.
