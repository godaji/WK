# 신라면세(shilla-dutyfree) 위스키 리포트 — 작업 프로세스 & 의존성 정리

> CMPA-139. 오늘(2026-06-06) CMO·엔지니어들이 신라면세 HTML 리포트를 만들기까지
> 수행한 전 과정을, 단계별 input/output/스크립트/의존성으로 정리. **루틴화 설계용 기준 문서.**
> 모든 스크립트는 `pipelines/shilla_dutyfree/` (리포트 빌더 일부는 `scripts/`).
> 날짜 토큰 `<date>` = 수집일 (예: 2026-06-06). 출력 파일명에 날짜가 박혀 덮어쓰기 없음.

---

## 0. 한눈에 보기 — 4단계 파이프라인

```
[1.수집] ──► [2.가공/필터] ──► [3.분석/스코어링] ──► [4.리포트 생성]
  crawl        filter            매력도/비교/추천          MD·HTML·배포
```

데이터 흐름의 **단일 뿌리**는 `crawl_shilla_whisky.py` 한 개. 여기서 나온
`신라면세_위스키_<date>.csv`(656종)를 모든 하류 분석이 소비한다. 분석 단계는
서로 독립적인 3~4개 가지(피트/스타일/국내가교차/예산)로 갈라지고, 리포트 단계에서 다시 합류.

---

## 1. 데이터 소스 분류 — '현재' vs '간헐'  ⭐ (루틴화 핵심)

루틴마다 어떤 데이터를 매번 새로 받아야 하는지가 다르다. 두 부류로 나눈다.

### A. 현재(LIVE) 데이터 — 루틴 실행마다 매번 새로 수집해야 함
가격·재고·할인율·판매량은 시시각각 바뀌므로 **리포트 시점의 라이브 값**이 필수.

| 소스 | 스크립트 | 엔드포인트 | 비고 |
|---|---|---|---|
| 신라면세 PLP(주류 c/1200) | `crawl_shilla_whisky.py` | `POST /estore/kr/ko/ajaxProducts` (+ c/1200 페이지에서 CSRF 토큰) | 키리스. 가격은 **USD**. 전 파이프라인의 뿌리 |
| 신라면세 라이브 재조회 | `score_peated_attractiveness.py` (← `crawl_shilla_whisky` 모듈 재사용) | 동일 AJAX | 구매가능/재고/판매량을 **수집 후 재확인**(delisted·품절 걸러냄) |
| 데일리샷 국내 실시간가 | `enrich_dailyshot.py` / `find_cheaper_than_domestic.py` | `GET api.dailyshot.co/items/search/?q=` | 키리스. 정본 88종 DB 커버리지 보완용 라이브 국내가·vivino |

### B. 간헐(STALE-OK) 데이터 — 따로 갱신되는 정본/스냅샷, 매번 안 받아도 됨
별도 루틴/수동으로 주기 갱신되며, 본 파이프라인은 **읽기만** 한다.

| 소스 파일 | 갱신 주체/주기 | 쓰는 스크립트 |
|---|---|---|
| `data/whisky-prices/fx/fx_latest.json` (USD→KRW 환율) | 환율 수집(일/주) | analyze_attractiveness, budget_top_picks, compare_international, find_cheaper |
| `data/whisky-prices/normalized/normalized_prices.csv` (국내 마트+데일리샷 정규화가) | 주간 가격 파이프라인(CMPA-1) | analyze_attractiveness, find_cheaper |
| `assets/whisky-list.csv` (정본 88종 + 큐레이션 국내가) | 마스터, 수동 | analyze_attractiveness |
| `data/whisky-prices/2026-06.csv`, `2026-05.csv` (코스트코 등 마트 월간) | 월간 수집 | price_krw_bands |
| `data/whisky-prices/2026-06_hk_whisky_poc.csv` (HK) | 해외 소싱 POC, 간헐 | compare_international, compare_hk |
| `data/whisky-prices/jp/2026-06_jp_shopify_poc.csv` (JP) | 해외 소싱 POC, 간헐 | compare_international |
| `data/whisky-prices/2026-05_tw_whisky_poc.csv` (TW) | 해외 소싱 POC, 간헐 | compare_international |

> **루틴 설계 함의:** 본 루틴은 A(신라·데일리샷)만 매 실행 새로 받고, B는 이미 갱신된
> 최신 정본을 참조한다. B가 오래되면 비교 정확도만 떨어질 뿐 파이프라인은 돈다(예: 코스트코
> 미취급이면 매칭 0 → 사실대로 보고). 해외/환율 정본 루틴과는 **느슨하게 결합**.

---

## 2. 단계별 상세 — input / output / 스크립트 / 의존

### 단계 1 — 데이터 수집 (Collection)

| 스크립트 | 입력 | 출력 | 의존 |
|---|---|---|---|
| `crawl_shilla_whisky.py` | 신라면세 AJAX (LIVE) | `data/shilla-dutyfree/신라면세_위스키_<date>.csv` (위스키 656)<br>`신라면세_주류전체_<date>.csv` (주류 1,407, 참고) | **뿌리(없음)** |

### 단계 2 — 데이터 가공·필터 (Processing / Filtering)

| 스크립트 | 입력 | 출력 | 의존 |
|---|---|---|---|
| `filter_peated.py` | 신라면세_위스키_<date>.csv | `신라면세_피트위스키_<date>.csv` (64종, +피트근거/피트분류 컬럼) | ← 1 |

> 스타일(셰리/버번) 분류는 별도 필터 파일을 만들지 않고 단계3의 `score_style_attractiveness.py`
> 안에서 증류소/키워드로 직접 분류한다.

### 단계 3 — 분석·매력도 스코어링 (Analysis) — 4개 독립 가지

**가지 P (피트 매니아):**

| 스크립트 | 입력 | 출력 | 의존 |
|---|---|---|---|
| `score_peated_attractiveness.py` | 신라면세_피트위스키_<date>.csv + **신라 LIVE 재조회** | `신라면세_피트위스키_매력도_<date>.csv`<br>`신라면세_피트위스키_TOP20_<date>.csv` | ← 2 (+ crawl 모듈) |
| `compare_international.py` | 피트위스키_매력도 + HK/JP/TW POC + fx | `신라면세_피트위스키_해외비교_<date>_v2.csv` | ← P.score + B(해외,fx) |
| `price_krw_bands.py` | 피트위스키_매력도 + 마트 월간(코스트코) | `신라면세_피트위스키_원화구간_<date>.csv` | ← P.score + B(마트월간) |

**가지 S (스타일 셰리/버번):**

| `score_style_attractiveness.py` | 신라면세_위스키_<date>.csv (수집 스냅샷) | `신라면세_{셰리|버번}위스키_매력도/TOP_<date>.csv` | ← 1 |

**가지 D (국내가 교차 — 매칭 엔진):**

| 스크립트 | 입력 | 출력 | 의존 |
|---|---|---|---|
| `analyze_attractiveness.py` ⭐엔진 | 신라면세_위스키 + normalized_prices + whisky-list + fx | `면세_매력도_매칭_<date>.csv`<br>`reports/.../면세_가성비_매력도_<date>.md` | ← 1 + B(국내가,fx) |
| `recommend_purchase.py` (CMPA-134) | 신라면세_위스키 + 면세_매력도_매칭 | `구매추천_CMPA134_<date>.csv` + .md | ← 1 + D.analyze |
| `budget_top_picks.py` | 신라면세_위스키 + 면세_매력도_매칭 + fx (+ analyze 엔진 import) | `reports/.../예산대별_TOP_<date>.md` + csv | ← 1 + D.analyze |
| `find_cheaper_than_domestic.py` (CMPA-138) | 신라면세_위스키 + normalized_prices + **데일리샷 LIVE** + fx | `면세_국내최저대비_저렴_<date>.csv` + .md | ← 1 + B(국내가) + LIVE(데일리샷) |

**헬퍼 라이브러리(단독 실행 아님, import 되어 재사용):**
- `enrich_dailyshot.py` — 데일리샷 검색 API 래퍼(LIVE). `find_cheaper`·`build_report`가 import.
- `compare_hk.py` — 신라↔HK 브랜드+숙성 매칭 브릿지. `build_report`가 사용.

### 단계 4 — 리포트 생성 (Report Generation)

| 스크립트 | 입력 | 출력 | 의존 |
|---|---|---|---|
| `build_report.py` | 피트위스키_매력도 + 해외비교_v2 + 데일리샷(국내기준가) | `reports/.../피트위스키_리포트_<date>.md` | ← P.score, P.intl, 데일리샷 |
| `build_report_html.py` | 분석 산출을 큐레이션해 임베드(CMPA-130 초안 + CMPA-137 선물스토리) | `reports/.../면세위스키_리포트_<date>.html` | ← 단계3 산출(수동 큐레이션) |
| `scripts/build_deploy.py` | reports/shilla-dutyfree/ 최신 HTML | `deploy/shilla-dutyfree/index.html` (깔끔 URL) | ← build_report_html |

> **주의:** `build_report_html.py`는 현재 분석 CSV를 자동으로 다 읽지 않고, 큐레이션된 추천
> 데이터(TRAP/여행/취향/선물 카드)를 스크립트 내부 테이블로 임베드한다. 루틴화 시 이 부분이
> **수동 큐레이션 게이트** — 자동화하려면 단계3 산출 CSV를 직접 읽도록 리팩토링 필요(아래 권고).

---

## 3. 전체 의존성 그래프 (DAG)

```
                       [신라 AJAX · LIVE]                 [간헐 정본: fx / normalized / whisky-list / 해외POC / 마트월간]
                              │                                              │
                  crawl_shilla_whisky.py ──► 신라면세_위스키_<date>.csv ◄────┤  (분석 가지들이 정본을 함께 읽음)
                              │                         │   │   │            │
              ┌───────────────┘                 ┌───────┘   │   └───────────┐│
              ▼                                 ▼           ▼               ▼▼
        filter_peated.py            score_style_attr.py  analyze_attr.py(엔진)  find_cheaper.py
              │                          (셰리/버번)          │   │   │         (+데일리샷 LIVE)
              ▼                                          ┌────┘   │   └────┐
   score_peated_attr.py(+신라 LIVE 재조회)              ▼        ▼        ▼
        │            │                          recommend_purchase  budget_top_picks
        ▼            ▼                              (CMPA-134)        (예산대별 TOP)
 compare_intl   price_krw_bands
 (해외비교)      (원화구간/코스트코)
        │
        └──────────────┬───────────────►  build_report.py ──► 피트위스키_리포트.md
                        │                  (+데일리샷, compare_hk 브릿지)
                        │
        (단계3 산출 큐레이션) ──► build_report_html.py ──► 면세위스키_리포트.html
                                                              │
                                                  scripts/build_deploy.py ──► deploy/shilla-dutyfree/index.html
```

**핵심 의존 규칙**
- 모든 것은 `신라면세_위스키_<date>.csv` 1개에서 출발 → **수집 1회면 분석 가지는 병렬 가능**.
- 단, `score_peated`·`find_cheaper`는 실행 시점에 **추가 LIVE 호출**을 하므로 같은 `<date>`라도
  값이 수집본과 미세하게 다를 수 있음(라이브 재조회·데일리샷). 페이싱(`--pace`) 필요.
- `compare_international`·`price_krw_bands`는 P가지의 `매력도` CSV에 의존(2단 체인).
- `recommend_purchase`·`budget_top_picks`는 D가지의 `면세_매력도_매칭` CSV에 의존(2단 체인).

---

## 4. 루틴화 권고 (실행 순서 · 병렬 안전성)

권장 실행 순서(같은 `--date` 토큰을 전 단계에 주입):

```
1) crawl_shilla_whisky.py --date <date>            # LIVE, 단독·뿌리
2) filter_peated.py                                # 1 산출 소비
3) (병렬 가능, 모두 1 또는 2 산출 + 간헐정본 소비)
     ├─ score_peated_attractiveness.py   (LIVE 재조회 — 페이싱)
     │     └─ compare_international.py
     │     └─ price_krw_bands.py
     ├─ score_style_attractiveness.py
     └─ analyze_attractiveness.py        (엔진)
           ├─ recommend_purchase.py
           ├─ budget_top_picks.py
           └─ find_cheaper_than_domestic.py  (데일리샷 LIVE — 페이싱)
4) build_report.py  →  build_report_html.py  →  scripts/build_deploy.py
```

병렬 안전성:
- 가지(P/S/D)는 **출력 파일이 겹치지 않아** 동시 실행 안전(파일 격리). 단 LIVE 호출하는
  `score_peated`·`find_cheaper`를 동시에 돌리면 신라/데일리샷에 **동시 요청 폭증(429 위험)** →
  LIVE 가지는 직렬 또는 페이싱 권장(기존 가격 파이프라인 교훈과 동일).
- 단계4는 단계3 **전부 완료 후** 실행(배리어). `build_deploy.py`는 `deploy/`를 통째 재생성하므로
  다른 배포 루틴과 동시 실행 금지(`skip_if_active`).

루틴화 전 정리 권고(부채):
1. **하드코딩 날짜 제거** — `score_peated`(`PEATED=...2026-06-06.csv`),
   `score_style`(`SRC=...2026-06-06.csv`), `compare_international`/`price_krw_bands`
   (`DATE="2026-06-06"`), `recommend_purchase`(파일명 고정)이 날짜를 상수로 박아둠.
   루틴은 `--date` 인자로 통일 필요.
2. **build_report_html 자동화** — 현재 수동 큐레이션 임베드. 단계3 CSV를 직접 읽도록 바꿔야
   완전 무인 루틴 가능. (안 바꾸면 '데이터는 자동, 발행 HTML은 사람 검수' 하이브리드로 운용)
3. **단일 오케스트레이터 스크립트** 신설 권장(`run_shilla_pipeline.py`): 위 순서를 강제하고
   LIVE 가지 페이싱·`--date` 전파·정규화 실패 시 리포트 중단(기존
   `run_whisky_price_pipeline.py` 패턴 재사용).

---

## 4-1. 리포트 생성일(날짜) 표기 규약 ⭐ (보드 지시 2026-06-06)

리포트는 **언제 만든 것인지**가 파일명과 본문 양쪽에 보여야 한다. 두 종류의 날짜를 구분:

- **수집일(데이터 기준일)** = 신라/데일리샷을 받은 날 = 분석 CSV 파일명의 `<date>`. 가격·재고의 시점.
- **생성일(리포트 작성일)** = 리포트를 렌더한 날. 같은 날 한 번에 돌리면 둘이 같지만, 과거 수집본으로
  나중에 다시 렌더하면 달라질 수 있으므로 **별개 개념**으로 표기한다(가격 파이프라인 data-month vs run-date 규칙과 동일).

**현황(점검·조치 완료):**

| 리포트 | 파일명 날짜 | 본문 날짜 표기 | 상태 |
|---|---|---|---|
| `면세위스키_리포트_<date>.html` (발행 HTML) | ✅ `_<date>` | ✅ 헤더 `📅 생성일 <date> · 가격·재고는 수시 변동` | **이번에 추가** (`build_report_html.py`) |
| `deploy/shilla-dutyfree/index.html` | (고정 URL) | ✅ 상동 (HTML 복사본) | 재배포로 반영 |
| `피트위스키_리포트_<date>.md` | ✅ | ✅ `- 📅 작성일: <date>` | 기존 OK |
| `면세_가성비_매력도_<date>.md` | ✅ | ✅ `- 분석일: <date> (KST)` | 기존 OK |
| `예산대별_TOP_<date>.md` | ✅ | ✅ `- 분석일 <date> (KST)` | 기존 OK |
| `면세_국내최저대비_저렴_<date>.md` | ✅ | ✅ `- 분석일 <date> (KST)` | 기존 OK |
| `구매추천_CMPA134_<date>.md` | ✅ | ✅ `**기준일** <date>` | 기존 OK |

> 결론: **MD 리포트 전부 이미 본문 날짜 표기 보유**. 유일한 누락이던 **발행 HTML에 `📅 생성일`을 추가**하고
> 재배포했다(deploy/index.html에도 반영). 모든 리포트의 파일명에는 이미 `_<date>`가 박혀 덮어쓰기 없이 이력이 남는다.

**루틴화 시 날짜 일관성 주의:** `build_report_html.py`의 생성일은 현재 `time.strftime`(=실행 당일)을 쓴다.
같은 날 수집→렌더면 수집일과 일치하지만, 루틴에서 과거 수집본을 재렌더하면 어긋난다. 오케스트레이터가
**단일 `--date`(논리 실행일)를 전 단계에 주입**하면 파일명·본문·HTML 생성일이 모두 한 값으로 정렬된다(아래 권고 1과 연결).

---

## 4-2. 루틴화 전 정리 권고 (최종) ⭐

루틴으로 묶기 전에 처리할 항목. 우선순위 순:

1. **[필수] 날짜 인자 통일 (`--date` 단일 주입)**
   - 현재 `score_peated_attractiveness.py`·`score_style_attractiveness.py`(`SRC=...2026-06-06.csv`),
     `compare_international.py`·`price_krw_bands.py`(`DATE="2026-06-06"`), `build_report.py`(`DATE="2026-06-06"`),
     `recommend_purchase.py`(입출력 파일명 고정)이 **2026-06-06을 상수로 하드코딩**.
   - 이대로 루틴을 돌리면 새 수집본(`<오늘>`)을 안 읽고 6/6 파일만 본다 → **반드시 `--date` 인자화**.
   - `build_report_html.py` 생성일도 `--date` 우선(없으면 today)으로 받아 수집일과 일치시킨다(§4-1).

2. **[필수] 단일 오케스트레이터 `run_shilla_pipeline.py` 신설**
   - §4 실행 순서를 강제(수집→필터→분석 가지→리포트→배포), `--date`를 전 단계 전파.
   - LIVE 가지(`score_peated`·`find_cheaper`)는 **직렬 또는 페이싱**(신라·데일리샷 429 방지).
   - 수집/정규화 실패 시 리포트 단계 중단(부분·stale 발행 차단). 기존 `scripts/run_whisky_price_pipeline.py` 패턴 재사용.
   - 루틴 등록 시 `concurrencyPolicy=skip_if_active`(배포 폴더 통째 재생성 레이스 차단).

3. **[권장] `build_report_html.py` 데이터 자동화**
   - 현재 추천 카드(TRAP/여행/취향/선물)를 스크립트 내부 테이블로 **수동 큐레이션 임베드** →
     완전 무인 루틴 불가. 단계3 산출 CSV(`면세_국내최저대비_저렴`·`매력도` 등)를 직접 읽도록 리팩터.
   - 미적용 시 운용 방식: **데이터·MD는 자동, 발행 HTML은 사람 검수** 하이브리드(생성일 표기는 이미 자동).

4. **[권장] 간헐 정본 신선도 가드**
   - `fx_latest.json`·`normalized_prices.csv`·해외 POC가 너무 오래되면 비교 정확도 저하.
   - 오케스트레이터 시작 시 정본 파일들의 수정일을 로그로 찍어 **stale 경고**(중단은 아님 — 파이프라인은 계속 돈다).

> 위 1·2가 루틴화의 **선결 조건**(블로커), 3·4는 품질 개선(후속 가능). 별도 실행 이슈로 위임 가능.

---

## 4-3. 루틴 구현 (DONE — 보드 지시 2026-06-06) ⭐

오케스트레이터 `scripts/run_shilla_pipeline.py` 신설 + 6개 스크립트 하드코딩 날짜 제거(`SHILLA_DATE` 주입).
보드 지시대로 **200번대 단계 루틴 4개 + 전체 통합 루틴 1개** 등록(모두 assignee=DataEngineer, 수동 api 트리거, `skip_if_active`).

| 루틴 | 명령 | 입력→출력 | 데이터 성격 |
|---|---|---|---|
| **200** 수집 | `run_shilla_pipeline.py --stage collect` | 신라 AJAX → 신라면세_위스키_<date>.csv | **현재/LIVE** |
| **201** 가공/필터 | `--stage process` | 위스키.csv → 피트위스키.csv | 순수 가공 |
| **202** 분석·매력도 | `--stage analyze --skip-crawl` | 위스키/피트 + 간헐정본 → 매력도/비교/추천 8종 | 일부 LIVE(재조회·데일리샷) + 간헐정본 읽기 |
| **203** 리포트·배포 | `--stage report` | 분석 CSV → md·HTML(📅생성일)·deploy | 산출 |
| **All-in-one** 통합 | `--stage all` | 200→201→202→203 순서 강제 | 전체 |

오케스트레이터 핵심:
- `--date` 1개를 환경변수 `SHILLA_DATE`로 전 스텝에 주입 → 수집·분석·리포트·생성일이 한 값으로 정렬(§4-1 날짜 일관성 해결).
- LIVE 스텝(수집·score_peated·find_cheaper)은 직렬 + `--pace`(기본 3s)로 429 회피.
- 수집 실패=뿌리 → hard-fail. 분석 비핵심 스텝 실패=경고 후 계속(`--strict`로 hard-fail). 리포트 빌드 실패=hard-fail.
- `--smoke`(컴파일 점검·라이브 없음), `--skip-crawl`(기존 수집본 재사용).

검증: `--smoke` 13/13 GREEN · `--stage report --date 2026-06-06` 실런 GREEN(📅생성일 반영·재배포) · `SHILLA_DATE=2099` 음성테스트로 override 활성 확인 · 기본값 2026-06-06 폴백 보존.

남은 부채(품질, 후속): build_report_html 수동 큐레이션 임베드 → 단계3 CSV 직접 읽기로 리팩터해야 203 완전 무인화(현재는 데이터·MD 자동 / 발행 HTML 사람 검수 하이브리드). 정기 cron 은 미설정(수동 api) — 자동 스케줄은 board 지시 시 추가.

---

## 4-4. 리포트↔수집 의존성 & 수집-선행 가드레일 (CMPA-235 / 보드 지시) ⭐

**의존성(명시):** 리포트 생성은 요청 `<date>`(기본 오늘 KST)의 **신라 오늘자 raw CSV**
`data/shilla-dutyfree/신라면세_위스키_<date>.csv` 와, 그로부터 파생된 분석 CSV
(`신라면세_피트위스키_매력도_<date>.csv` 등)·`리포트_가격_<date>.json` 에 의존한다.
**오늘자 raw 가 없으면 → 신라를 먼저 수집한 뒤 리포트를 생성**한다.

> **일반 위스키가격리포트는 신라 데이터와 무관하다.** `scripts/run_whisky_price_pipeline.py`
> → `scripts/generate_report.py` / `scripts/whisky_report_tables.py` 의 입력은 `data/whisky-prices/`
> 이며 신라 CSV/JSON 을 읽지 않는다. **여기엔 신라 수집 가드를 넣지 않는다**(오해 방지). 의존
> 방향이 실재하는 곳은 신라면세 리포트 파이프라인뿐이다.

**가드레일 구현(`scripts/run_shilla_pipeline.py`, report 스테이지 진입 전):**

| 상황 | 동작 |
|---|---|
| report 스텝이 **선행 collect 포함**(`--stage all`, `--stage collect`) | 검사 생략 — collect 가 raw 를 만든다(회귀 0). |
| `--stage report` 단독 + raw `<date>.csv` **있음** | 그대로 report 진행(기존 동작 유지, 회귀 0). |
| `--stage report` 단독 + raw **없음** | **collect→process→analyze 를 report 앞에 선행 보강** 후 진행(자동 수집). |
| `… --skip-crawl` + raw **없음** | **hard-fail**(`[GUARD-FAIL]`, exit 2) — 자동 수집 불가 → 조용한 stale-date 리포트 금지. |
| `--skip-crawl` + raw **있음** | 기존 수집본 재사용(의도된 경로, 회귀 0). |

- 재사용 패턴: `pipelines/shilla_dutyfree/refresh_report_prices.py` L113–122 의 "CSV 없으면
  `crawl_shilla_whisky.py <date>` 자동 실행"을 report 스테이지 전반으로 끌어올린 것.
- **stale-date 폴백 차단:** `build_report_html.latest_date()` 는 이제 **raw CSV 가 실재하는**
  가장 최신 날짜만 고른다(이전: `리포트_가격_*.json` 우선 → JSON 만 잔존하는 날짜로 폴백 가능했음).
  오케스트레이터는 항상 `SHILLA_DATE=<date>` 를 주입하므로 렌더 날짜는 요청 date 로 고정된다.
- docstring 명시: `run_shilla_pipeline.py`·`build_report.py`·`build_report_html.py` 에 위 의존성 1줄씩.

**검증(CMPA-235):**
- `python3 scripts/run_shilla_pipeline.py --smoke` GREEN.
- 없는 날짜로 `--stage report --skip-crawl` → `[GUARD-FAIL]` hard-fail(리포트 미생성).
- 없는 날짜로 `--stage report`(no skip) → collect→process→analyze 선행 보강 후 report(stale 아님).
- raw 있는 날짜는 회귀 0(기존 동작 유지). `data/whisky-prices/` 일반 리포트 무손상.

---

## 5. 산출물 인벤토리 (2026-06-06 기준, 정상 생성 확인)

- **CSV**(`data/shilla-dutyfree/`): 신라면세_위스키/주류전체, 피트위스키(+매력도/TOP20/100불이하/원화구간/해외비교_v2),
  셰리·버번(매력도/TOP), 면세_매력도_매칭, 구매추천_CMPA134, 예산대별_TOP, 면세_국내최저대비_저렴, 면세_vs_데일리샷
- **MD**(`reports/shilla-dutyfree/`): 피트위스키_리포트, 면세_가성비_매력도, 예산대별_TOP, 구매추천_CMPA134,
  면세_국내최저대비_저렴, 콘텐츠초안/draft
- **HTML/배포**: `reports/shilla-dutyfree/면세위스키_리포트_<date>.html` → `deploy/shilla-dutyfree/index.html`

> ⚠️ 외부 공개는 법무/소싱 가드레일(게이트) CEO 승인 전까지 내부 스테이징만. (본 문서는 프로세스 정리이며 발행 아님)
