# 위스키 마스터리스트 후보 확장 워크플로 (CMPA-170)

bottom-up 으로 정본 `assets/whisky-list.csv` 를 확장하는 표준 절차.
정본 반영은 **항상 CEO 독립 검증 후**(CMPA-125 교훈: DE done ≠ 정본 반영).

## 단계

1. **후보 추출** — `python3 scripts/extract_whisky_candidates.py <date>`
   - `normalize_whisky_name --audit` 미매칭을 정규화 키로 묶어 distinct 후보 생성.
   - 산출: `assets/_runs/whisky-list-candidates_<date>.csv`
   - 자동 1차 분류: new_sku / synonym_of_existing / review / noise (freq·유사도 기반, 보조용).

2. **사람 큐레이션** — `...-candidates-curated_<date>.csv`
   - final_class 확정: `new_A`(승인후보·확실) / `new_B`(저빈도 등 불확실) / `synonym`(정본 흡수) / `noise`.

3. **웹 검증(board 제안, 2026-06-07)** — `...-candidates-webcheck_<date>.csv`
   - **새 제품인지 헷갈리는 후보(주로 new_B)는 데일리샷·구글에 검색해 실재 여부를 확인한다.**
   - 검색 신호 해석:
     - **데일리샷 상품 페이지 존재**(`dailyshot.co/m/item/...`) → 국내 유통 실재, 강한 양성. (예: 라벨5 6429, 윈저12년 6535, 스카치블루17 4683)
     - 공식 브랜드/위스키 DB(whiskybase, thewhiskyexchange, 브랜드 공식몰) 히트 → 실재 제품.
     - 어떤 리테일/DB 에도 없음 + 표기 깨짐 → OCR 가비지/노이즈로 확정.
   - 결과를 `web_check` 컬럼에 `상태: 증거URL` 형식으로 기록(상태: real / real_dailyshot / not_found / ambiguous).
   - **검증(real)된 new_B → new_A 로 승격.** `scripts/apply_webcheck_candidates.py` 가 WEBCHECK 매핑을 받아 자동 augment+승격.
   - over-merge 가드 유지: 정본과 중복/혼동되면 신규 id 대신 synonym 흡수.

4. **CEO 승인 1패스** — webcheck CSV 의 new_A 목록을 CEO 가 독립 검증/승인.

5. **정본 반영(승인분만)** — `whisky-list.csv` 에 w089~ append(기존 id 불변) + `whisky-synonyms.yaml` products 규칙 추가.

6. **검수** — `run_whisky_price_pipeline.py --skip-crawl` GREEN, `pytest scripts/test_whisky_report_rollover.py`, 매칭률 before/after.

## 왜 웹 검증인가 (board 제안 근거)
freq=1(딱 한 번 관측)이라는 이유만으로 "불확실"로 깎는 것은 **표본 부족 아티팩트**이지
제품이 가짜라는 신호가 아니다. 2026-06-07 표본 검증에서 freq=1 new_B 12/12 가 모두
실재 제품(데일리샷 상품 6건 직접 확인)으로 나왔다. 따라서 freq 단독으로 후보를 버리지 말고
웹 반응을 tiebreaker 로 쓴다.

## 향후 자동화(선택, CMPA-170 5단계)
분기 라우틴: 추출 → 큐레이션 → (web_check 반자동) → CEO 승인 → 정본 반영.
web_check 는 현재 사람이 검색해 WEBCHECK 매핑을 채우는 반자동 단계이며, 데일리샷 검색
엔드포인트가 안정적이면 후속 이슈에서 `dailyshot.co/m/item` 존재 확인을 스크립트화할 수 있다.
