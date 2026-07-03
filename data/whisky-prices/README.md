# 위스키 가격 데이터셋 (코스트코 · 이마트 트레이더스)

월간 CSV로 분할 저장. 한 파일에 몰지 않고 `YYYY-MM.csv` 단위로 누적한다.

## 스키마
`술이름, 가격_KRW, 위치, 가져온날짜, 출처, 신뢰도, 비고`
- 인코딩: UTF-8 (BOM) — Excel에서 한글 바로 열림.
- `가져온날짜`가 유효성 기준. 가격은 매주 월요일 변동.
- `신뢰도`: 높음(현장 가격표 2차 출처) / 중(단건 스니펫) / 낮음(추정·재확인 필요).

## 2026년 커버리지 (현재)
| 파일 | 내용 | 신뢰도 |
|---|---|---|
| `2026-03.csv` | 트레이더스 3종(글렌피딕·발베니) — 검색 스니펫 기반 | 낮음(월 추정) |
| `2026-04.csv` | 트레이더스 2개 스냅샷: 04-03(17종, CocoScan/670) + 04-13(약 59종, CocoScan/771) | 높음 |
| `2026-05.csv` | 코스트코 단건(글렌리벳15·발베니12·맥캘란12) | 중~낮음 |
| `2026-06.csv` | 트레이더스 7종(6월 1주차 재소싱): 글렌모렌지 오리지널·발베니12 안정 확인(중); 글렌피딕12/15·페이머스그라우스1L·라가불린8·탈리스커스톰은 무날짜 블로그/과거가 충돌(낮음·재확인 필요) | 중~낮음 |
| `2026-05_hk_whisky_poc.csv` | **[내부 R&D·미적재]** 홍콩 위스키 1,828종(HKD→KRW 환산+한국 반입추정). CMPA-14 POC. Shopify products.json(Caskells·The Rare Malt·Mizunara). 스키마 별도(아래 노트). | 중(공개가) |
| `jp/2026-05_jp_rakuten_poc.csv` | **[내부 R&D·미적재]** 일본 위스키 40종/20브랜드(JPY→KRW 환산+한국 반입추정 ×2.5555). CMPA-12/CMPA-11 POC. Rakuten Ichiba API(20키워드 픽스처-셰입 검증, LIVE 키 주입 대기). 스키마 별도(아래 노트). | 중(공개 소매가·세금추정) |
| `2026-05_tw_whisky_poc.csv` | **[내부 R&D·미적재]** 대만 위스키 818종(TWD→KRW 환산+한국 반입추정). CMPA-13 POC. my9買酒網(Shopify products.json) 789 + 橡木桶 drinks.com.tw(HTML) 29. 噶瑪蘭(Kavalan) 현지 위스키 포함. 스키마 별도(아래 노트). **PChome/momo 종합몰은 菸酒管理法으로 병 미취급→부적합** 발견 기록. | 중(공개가) |

## ⚠️ 데일리샷 과거 데이터 dirty 표식 (CMPA-345, 2026-06-14)
**2026-06-13 면세 셀러 제외 수정(CMPA-321/322) 이전의 데일리샷 스냅샷은 면세가(세금 0)가
국내 최저 floor 에 섞여 일부 제품가를 실제보다 낮게 오염시켰다.** 오염 구간·제품은 비파괴
매니페스트 **`_dailyshot_dirty.json`** 에 표식돼 있다(가격값은 보존, `비고`/매니페스트로만 표시).
- **Clean 기준선**: `2026-06-13` 이후(`2026-06_dailyshot.csv` 정본은 06-13 재수집분, clean).
- **Dirty(주의)**: `_runs/` 의 06-12 이하 모든 데일리샷 스냅샷 + `2026-05_dailyshot.csv` 정본.
  영향 제품 16종(조니워커 블루·듀어스15·버팔로트레이스 등), 런당 10~15셀. `2026-05_dailyshot.csv`
  의 해당 행 `비고` 에 `⚠️DIRTY(면세오염의심,CMPA-345)` 가산.
- **재현/갱신**: `python3 scripts/flag_dailyshot_dirty.py [--annotate-may]`.
- 별도 주의: `2026-06-11` run 은 부분 스냅샷(가격 28건)으로 불완전.

## 알려진 공백 / 정직성 노트
- `jp/2026-05_jp_rakuten_poc.csv` 는 **별도 스키마**(22컬럼: 술이름·브랜드·숙성년수·용량·JPY·KRW·관세/주세/교육세/부가세·한국반입추정가·반입배수·국가·셀러·URL 등)이며 국내 월간 트래커와 합치지 않는다. 방법론: `pipelines/jp_rakuten/README.md`. **Rakuten 소매가를 CIF 프록시로 쓴 상한 추정**이고, LIVE applicationId 발급 전까지 픽스처-셰입 검증 단계. 공개/상업 게시·CMPA-1 적재는 CMPA-7 게이트(CEO 승인) 전까지 보류.
- `2026-05_hk_whisky_poc.csv` 는 **별도 스키마**(`술이름,기준가_HKD,정가_HKD,환율_HKDKRW,기준가_KRW,반입추정가_KRW_관세20,반입추정가_KRW_FTA0,재고,출처,가져온날짜,URL,비고`)이며 국내 월간 트래커와 합치지 않는다. 방법론: `pipelines/hk-whisky/README.md`. 공개/상업 게시·CMPA-1 적재는 CMPA-7 게이트(CEO 승인) 전까지 보류.
- `2026-05_tw_whisky_poc.csv` 는 홍콩과 **동형 스키마**(통화만 TWD: `술이름,기준가_TWD,정가_TWD,환율_TWDKRW,기준가_KRW,반입추정가_KRW_관세20,반입추정가_KRW_FTA0,재고,출처,가져온날짜,URL,비고`). 방법론·robots/ToS·파서 hit-rate: `pipelines/tw_whisky/README.md`. 메트릭: `tw/_poc_metrics.json`. 환산만 TWD 이고 한국 반입세 cascade 는 홍콩·일본과 공통 자산. 원산지 주의: 대만(Kavalan)·일본 위스키는 무FTA 20%, 스카치만 FTA0. 공개/상업 게시·CMPA-1 적재는 CMPA-7 게이트(CEO 승인) 전까지 보류.
- **2026년 1~2월 월간 스냅샷은 색인된 웹에서 신뢰성 있게 확보 불가** (블로그가 단일 페이지를 덮어쓰며 갱신 + US-region WebSearch 한계). 임의 채우기 안 함.
- 완전한 과거 백필은 **싼디(@SSanD3) 영상 아카이브 자막 파싱**이 필요 → 엔지니어링(별도 CEO 라우팅).
- 03월·05월 일부 행은 단건/추정. `신뢰도`·`비고` 참조.

## 파일명 / 실행일 스냅샷 규칙 (CMPA-38)
루틴은 **주간(1주)~격주(2주)** 로 돈다. 그러나 정본 파일명은 데이터의 **'월'(`YYYY-MM`)** 을
유지한다 — 이 정본 파일이 **항상 최신(latest 포인터)** 이라 다운스트림(normalize→report→
distribute)이 별도 수정 없이 늘 최신 입력을 집어간다.

매 실행 시점의 사본은 같은 폴더의 **`_runs/`** 아래에 **실행일(KST)** 을 박아 누적한다:
```
data/whisky-prices/2026-05_dailyshot.csv                  # 정본 = 최신 (다운스트림 입력)
data/whisky-prices/_runs/2026-05_dailyshot__run2026-06-03.csv   # 5월 데이터를 6월 1주차에 수집
```
- 규칙: `<정본파일명stem>__run<YYYY-MM-DD><ext>` → **데이터'월' + 실행'일' 둘 다** 파일명에 노출.
- 같은 달에 여러 번 돌려도 실행일이 다르면 **덮어쓰지 않고** `_runs/` 에 쌓인다. 같은 날 재실행은 멱등.
- 공통 구현: `pipelines/common/dated.py` (`snapshot()`, `kst_today()`, `latest_snapshot()`).
- 적용 지점: 데일리샷·홍콩·일본·대만 수집기, 코스트코/트레이더스 월간 적재(월 파일 시점 스냅샷),
  `normalize_dataset.py`(정규화 산출물·검증리포트), `generate_report.py`(생성일 스냅샷), `md_to_html.py`.
- 누적형(append) 월간 파일(`2026-05.csv`)은 행마다 `가져온날짜` 로 일 단위 추적이 이미 가능하고,
  `_runs/` 스냅샷은 그 '실행 시점의 월 파일 상태' 를 보존한다.

## 갱신 루틴
주간 Paperclip 루틴(매주 월 10:00 KST)이 깨어나 **해당 월 CSV(`YYYY-MM.csv`)에 신규/변동 행을 append**한다.
상세: CMPA-1 `price-tracker` 문서 참조.

수집 소스별 루틴:
- 데일리샷 스마트오더 최저가 — `pipelines/dailyshot` (CMPA-19/29).
- **코스트코 매장 웹 가격 — `pipelines/costco_web` (CMPA-28).** `출처=WebScrape(costcome.com(코스트컴))`.
  공식몰(costco.co.kr 등)은 주류 통신판매 금지로 위스키 미노출 → 매장가 추적 2차 소스 사용. 방법론: `pipelines/costco_web/README.md`.
