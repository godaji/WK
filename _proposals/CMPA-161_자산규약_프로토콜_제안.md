# 자산 규약 프로토콜 (Asset Contract Protocol) — 제안

> 작성: CEO · 2026-06-07 · 이슈 CMPA-161 (보드 결정용)
> 보드 요청: "중요 작업의 input/run/output 을 정의하고, 그 **규칙을 바꾸는 것은 CEO 허락**을 받게.
> 특히 input/output **protocol** 을 정의해서 관리하고 싶다."

---

## 1. 문제 — 왜 지금 필요한가

핵심자산이 두 자릿수로 늘었다(위스키 가격 4개국·콜키지/할랄/펫 맵·신라면세·deploy). 그만큼
**입력 소스가 바뀌거나 / 실행 순서가 깨지거나 / 출력 스키마가 조용히 변하면** 품질이 무너진다.
이건 가설이 아니라 우리가 실제로 겪은 사고들이다:

- **CMPA-98** — 실행 순서가 안 지켜져 리포트가 상류(수집·정규화)보다 먼저 돌아 *stale 리포트* 발행.
- **CMPA-116 / 155** — 월 롤오버 게이트가 없으면 국내 행수 급감분이 리포트를 오염(회귀).
- **CMPA-156** — 수집날짜 메타 누락 시 사용자가 "현재가"를 잘못 유추.
- **CMPA-154** — 위스키 가격 라이브 소스를 `@whiskeypick` 아닌 싼디로 오인하는 표현 반복.

**근본 원인:** 이 규칙들이 코드 주석·에이전트 메모리·CLAUDE.md 에 **흩어진 암묵지**다.
누가·언제 input/run/output 을 바꿔도 **막을 게이트가 없고**, 무엇이 "정답 계약"인지
단일 진실 공급원이 없다. 자산이 많아질수록 이 부채는 기하급수로 커진다.

---

## 2. 핵심 아이디어 — 자산마다 '계약(Contract)'을 둔다

각 핵심자산에 대해 **input / run / output 을 명시적이고 버전관리되는 '계약 파일'로 고정**한다.

> **계약 = 그 자산의 헌법.
> 계약을 바꾸는 것 = 헌법 개정 = CEO 승인 필수 (최상위 등급은 보드 게이트).**

계약은 세 개의 프로토콜로 구성된다 — 보드가 요청한 input/output protocol 이 1·3번이다:

| 프로토콜 | 정의하는 것 | 근거 관행 |
|---|---|---|
| **① INPUT 프로토콜** | 허용 소스 목록(화이트리스트), 필수 스키마/필드, **수집날짜 메타 필수**, 신선도·롤오버 게이트 | CMPA-156, CMPA-116/155, CMPA-154 |
| **② RUN 프로토콜** | 단일 진입점(오케스트레이터), 스테이지 순서, 동시성 정책, 성공/실패 규약, 멱등성 | CMPA-98, CMPA-99 |
| **③ OUTPUT 프로토콜** | 출력 스키마(컬럼/키), 필수 메타(리포트작성일), 불변식(회귀=0), 외부발행 게이트 | CMPA-45, CMPA-155, gate c7405e7d |

핵심은 **암묵지를 강제 가능한 계약으로 승격**하는 것이다. 계약은 사람이 읽고(거버넌스),
기계가 검증한다(품질 게이트).

---

## 3. 구조 (승인 시 구현 형태)

```
contracts/
  whisky-price-intelligence.yaml     # 자산별 계약 (기계검증 + 사람읽기 헤더)
  corkage-free-map.yaml
  shilla-dutyfree-report.yaml
  ...
CONTRACTS.md                          # 루트 레지스트리: 자산·버전·등급·소유자·최근승인
scripts/check_contract.py             # 검증기: 산출물이 OUTPUT 스키마 위반 → hard-fail
```

- 각 계약 메타: `version` · `tier` · `owner` · `last_approved_by` · `approved_at` · `change_log`.
- **검증 훅:** 오케스트레이터(예: `run_whisky_price_pipeline.py`) 끝에 `check_contract` 호출.
  출력이 계약 위반이면 배포 차단(회귀=0 불변식을 기계가 지킴).
- `CONTRACTS.md` 는 `핵심자산_인벤토리.md` 의 거버넌스 짝 — 인벤토리는 "무엇이 있나",
  계약은 "그게 어떻게 동작해야 하나(불변)".

---

## 4. 변경관리 — CEO 승인 게이트 (보드 요청의 핵심)

> **에이전트는 `contracts/` 파일을 직접 수정 금지.** 변경이 필요하면 이슈로 **제안만** 한다.
> CEO 가 검토 → 승인 시에만 버전 bump + change_log 기록.

변경을 영향도로 3분류한다:

| 분류 | 예시 | 승인 |
|---|---|---|
| **비파괴(additive)** | 소스 추가, 선택 필드 추가, 신선도 임계 강화 | **CEO 승인** |
| **파괴(breaking)** | 출력 스키마 변경, 소스 제거, 게이트 완화, 실행 순서 변경 | **CEO + 보드 confirmation** |
| **긴급 핫픽스** | 외부 API 장애로 임시 우회 | 선조치 후 **24h 내 CEO 사후 승인** |

이 규칙을 **CLAUDE.md 최상단에 영구 고지**(CMPA-156 데이터 3원칙과 동일 방식)해서,
이 리포에서 일하는 모든 에이전트가 첫 줄부터 읽게 한다.

---

## 5. 등급 (Tier) — 모든 자산에 계약을 강제하지 않는다

| 등급 | 자산 | 게이트 |
|---|---|---|
| **T1 (헌법급)** | 위스키 가격 인텔리전스 · 콜키지프리 맵 · 신라면세 리포트 | 파괴변경 = CEO + **보드** |
| **T2 (CEO급)** | 할랄/펫 맵 · deploy 빌더 | 파괴변경 = **CEO** |
| **T3 (권장·비강제)** | POC/실험 (대만, jp_rakuten 등) | 계약 선택, 게이트 없음 |

이렇게 하면 거버넌스 오버헤드가 **가장 중요한 자산에 집중**되고 실험 속도는 안 죽는다.

---

## 6. 샘플 계약 — 위스키 가격 인텔리전스 (실제 코드 기반)

```yaml
asset: whisky-price-intelligence
tier: T1
version: 1.0.0
owner: CTO
last_approved_by: CEO
approved_at: 2026-06-07
entrypoint: scripts/run_whisky_price_pipeline.py

input:
  sources:                                   # 화이트리스트 — 여기 없는 소스는 적재 금지
    - id: overseas        # FX + 홍콩 + 일본 Shopify
      path: pipelines/overseas/collect_overseas.py
      required: true
    - id: dailyshot       # 국내 최저가 핵심 신호
      path: pipelines/dailyshot/crawl_dailyshot.py
      required: true
    - id: costco_web
      path: pipelines/costco_web/collect_costco_web.py
      required: false
    - id: youtube_whiskeypick                # ⚠️ @whiskeypick 하나뿐 (싼디/@SSanD3 아님 — CMPA-154)
      path: pipelines/youtube_traders/collect_traders_prices.py
      required: false
      note: ASR per-IP 429 → ≥60분 페이싱, 자체 cron 유지
  required_fields: [name, price, currency, collected_date]
  collected_date_required: true              # CMPA-156: 수집날짜 메타 누락 금지
  freshness:
    domestic_rollover_gate: "국내 마트 월초 행수 ≥ max(40, 직전월×0.5) 일 때만 월 롤오버 (CMPA-116/155)"

run:
  ordering: [collect, normalize, report]     # CMPA-98 레이스 차단 — 순서 강제
  concurrency_policy: skip_if_active         # 동시 재실행 시 스킵 (CMPA-99 공유집계 충돌 방지)
  failure:
    collect: warn_continue                   # 개별 소스 429/장애가 리포트 재생성을 막지 않음(--strict면 hard-fail)
    normalize: hard_fail
    report: hard_fail
  idempotent: true                           # --skip-crawl 재실행 안전

output:
  artifacts:
    - id: normalized_all
      path: data/whisky-prices/normalized/normalized_all_rows.csv
      schema: [canonical_id, name, source, price_krw, collected_date]
    - id: monthly_report
      path: reports/whisky-prices/<month>.md
      required_meta: [report_date]           # 📅 리포트 작성일 헤더
  invariants:
    - "회귀=0: 기존 행 정규화 매칭 수 비감소(설명 없는 감소 금지)"
    - "totals 토큰 라이브 금지: 1829/1435 하드코딩 유지 (CMPA-155 회귀 방지)"
  publish_gate: c7405e7d                      # 외부 배포는 보드 게이트
```

이 한 파일이 지금 코드·주석·메모리에 흩어진 규칙 전부를 **한 곳에서 강제 가능한 계약**으로 모은다.

---

## 7. 단계적 도입 (승인 후)

- **Phase 0 (이 제안)** — 프로토콜 설계 + 파일럿 계약 1개(위스키 가격) → **보드 승인** ← *지금 여기*
- **Phase 1 (CTO 위임)** — `contracts/whisky-price-intelligence.yaml` + `check_contract.py` 구현,
  `run_whisky_price_pipeline.py` 에 계약검증 훅 추가, 회귀=0 확인.
- **Phase 2 (CTO/DE)** — T1 확장: 콜키지프리 맵 · 신라면세 리포트 계약 작성.
- **Phase 3 (CEO)** — `CONTRACTS.md` 레지스트리 + CLAUDE.md 거버넌스 규칙 영구 고지.

---

## 8. 보드 결정 요청 (이 confirmation 으로 묻는 것)

1. **접근 방식** — 자산별 '계약(input/run/output)' + CEO 승인 게이트 구조로 가도 되나?
2. **파괴변경 게이트** — 파괴적 계약 변경에 **보드 confirmation 필수**로 둬도 되나?
3. **파일럿 자산** — 첫 계약을 **위스키 가격 인텔리전스**로 구현해도 되나?

승인 시 Phase 1 을 CTO 에 위임하고, Phase 0 산출물(이 제안)을 정본화한다.
