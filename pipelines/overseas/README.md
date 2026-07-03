# 해외 위스키 소매가 + 환율 주기 수집 (CMPA-30)

면세 반입 비교용으로 **해외 소매가 + 환율**을 주기 수집한다. 단일 진입점
`collect_overseas.py` 하나가 환율·홍콩·일본 세 단계를 묶어 돌리고 실행 매니페스트를 남긴다.

## 실행

```bash
python3 pipelines/overseas/collect_overseas.py
```

환경변수(선택):

| 변수 | 기본 | 용도 |
|------|------|------|
| `COLLECT_DATE` | 환율 API 기준일 | 산출 CSV 파일명/asof |
| `FX_SOURCE_URL` | open.er-api.com USD | 환율 소스 override |

> 일본은 CMPA-52/CMPA-53에서 **키 불필요 Shopify `/products.json`** 로 교체됨(상시 LIVE).
> 기존 Rakuten `RAKUTEN_APP_ID` 게이트는 제거(CMPA-47 키 대기는 `cancelled`).

## 단계 / 산출물

| 단계 | 소스 | 산출물 |
|------|------|--------|
| 1. 환율 | open.er-api.com (USD 기준 cross-rate) | `data/whisky-prices/fx/fx_snapshot.csv`(이력, 날짜+통화 upsert), `fx_latest.json` |
| 2. 홍콩 | Caskells·TheRareMalt·Mizunara Shopify `/products.json` (라이브) | `data/whisky-prices/{YYYY-MM}_hk_whisky_poc.csv` |
| 3. 일본 | 일본 주류 Shopify `/products.json` (라이브, 키 불필요) | `data/whisky-prices/jp/{YYYY-MM}_jp_shopify_poc.csv` |
| 매니페스트 | — | `data/whisky-prices/_overseas_last_run.json` (단계별 상태·행수·사용환율) |

환율은 `KRW/USD ÷ ccy/USD` cross-rate 로 `HKD→KRW`, `JPY→KRW` 를 산출하고, 그 라이브
값을 HK/JP 가격 환산 입력으로 그대로 전달한다(스냅샷과 환산이 항상 같은 환율 사용).

각 국가 가격행에는 공통 모듈 `pipelines/common/fx_tax.py` 의 한국 반입세 cascade
(관세20 / 주세72 / 교육세30 / 부가10, 유효배수 ≈ 2.5555x)가 붙는다.

## 종료코드

- `0` — 정상(홍콩 라이브 ≥1행).
- `2` — 홍콩 라이브가 0행이거나 실패(점검 필요). 환율·일본 부분 실패는 매니페스트에 기록하되
  치명으로 보지 않음.

## 상태 / 블로커

- **홍콩**: 라이브 동작(POC 1,828행). Shopify 공개 엔드포인트, robots 비차단. (메모리 `hk-whisky-sourcing`)
- **일본**: 라이브 동작(키 불필요 Shopify `/products.json`, CMPA-52 POC 1,435행). 酒類ドットコム·SAKE
  People·酒庫住田屋 3사. Rakuten API(키 대기)는 superseded. (메모리 `cmpa52-jp-shopify-alternative`)
- **환율**: 라이브 동작(키 불필요).

## 가드레일 (메모리 `ssandi-sourcing-legal` / `dailyshot-crawling-legal` / `cmpa9-overseas-price-sourcing`)

본 수집은 **내부 R&D·측정용**. 공개/상업 표면 재배포는 상위 이슈(CMPA-15 리포트)의 법무·소싱
가드레일 통과 후에만. 스크립트는 측정만 한다.

## 후속 (CMPA-30 의존)

수집 원시명 → 정본 마스터 정규화·검증(동일-SKU 한↔영 매칭)은 `whisky-data-normalization`
스킬 / `scripts/normalize_whisky_name.py` 로 연결한다.

## 루틴

주간(매주 월 09:00 KST) 스케줄 루틴으로 등록. 환율만 더 자주 갱신하려면 `fx_fetch.py`
단독 호출을 별도 트리거로 추가할 수 있다.
