# 일본 위스키 가격 수집 — Rakuten Ichiba API POC (CMPA-12 / CMPA-11)

**상태: 내부 R&D / 측정·비공개 한정.** 공개·상업 게시 전 CEO 가드레일(CMPA-7 프레임) 통과 필수. 이 산출물은 측정용 로컬 데이터셋이며 CMPA-1 운영 트래커에 적재하지 않았다.

## 결과 요약 (2026-05-30)
- **드롭-인-키-앤-고 파이프라인 완성·실측 검증.** 수집(LIVE/픽스처) → 정규식 파서 → 이름 정규화 → JPY→KRW 환산 → 한국 반입세 추정 → CSV 적재.
- 실측 지표(레코드드-셰입 픽스처 20키워드 50 items, 의도적 노이즈 10개 포함; LIVE 키 주입 시 동일 코드로 실데이터 측정):
  | 지표 | 값 |
  |---|---|
  | raw 파서 hit-rate (병/전체 items) | **80.0%** (40/50) |
  | bottle recall (정상 병 중 파싱 성공) | **100%** (40/40) |
  | 브랜드 매칭 정확도 | **100%** (40/40) |
  | 용량 추출 정확도 | **100%** (40/40) |
  | 노이즈 필터 precision/recall | **100% / 100%** |
- 출력: `data/whisky-prices/jp/2026-05_jp_rakuten_poc.csv` (22컬럼, 40행, 20브랜드/≥20종 SKU).
- 환율 JPY→KRW **9.458761** (open.er-api.com 실시간, 2026-05-30).
- 처리시간: 픽스처 전체 <0.1s. LIVE는 키워드당 1req + 1s rate-limit → 20키워드 ≈ 20s.

## go/no-go 권고: **GO (조건부)**
- 일본은 **공식 오픈 JSON API**라 HTML 크롤·OCR 불필요(홍콩 CMPA-14의 Akamai 차단, 싼디 OCR 대비 압도적 저리스크·저비용).
- 파서/정규화 백엔드는 실데이터 형태에서 100% 매칭. 유일한 미충족 = **LIVE applicationId 주입**(보드 승인 완료, 키 전달 대기 — 아래 가드레일).
- 킬 기준 점검: hit-rate 80.0%(>70% ✓), SKU mismatch 없음 ✓, **applicationId 발급 보드 승인 완료**(d840ad9c). 키 전달(env `RAKUTEN_APP_ID`)만 대기 — 에이전트 자력 회원가입·ToS 수락 불가/금지.

## API 키 (필수 후속 — CEO/보드)
- Rakuten Web Service `applicationId`는 무료지만 **Rakuten 회원 계정 + 앱 등록 + ToS 수락**이 선행. 회사 정체성으로 ToS를 수락하는 것은 자격증명/거버넌스 결정 → CEO 보드 승인 건으로 상신.
- 키 발급 후: `RAKUTEN_APP_ID=xxxx python3 rakuten_poc.py` 로 즉시 LIVE 수집(코드 변경 0). 동일 픽스처-셰입을 검증했으므로 드롭인 동작.

## 파이프라인 사용법
```bash
python3 rakuten_poc.py                       # 픽스처 모드(기본): CSV + 지표 산출
RAKUTEN_APP_ID=xxxx python3 rakuten_poc.py   # LIVE 모드: 실 API 호출
FX_JPY_KRW=9.46 python3 rakuten_poc.py       # 환율 오버라이드
```
- stdlib만 사용(외부 의존성 0). LIVE 클라이언트는 `urllib` 기반.
- `fixtures/rakuten_sample.json` = 실 API 응답 **형태**(`Items[].Item.{itemName,itemPrice,shopName,itemUrl,itemCode}`)를 미러. 각 Item의 `_gt`(ground-truth)는 셀프 채점 하니스 전용, 파서는 읽지 않음.

## 파서 / 정규화 (CMPA-6 재사용 후단부)
- **브랜드 사전**(`BRANDS`): 캐논키 → 한글표시명 + 별칭 substring(일본어+로마자). 20브랜드(山崎/白州/響/竹鶴/余市/宮城峡/Nikka FtB·Session·CoffeyGrain·Days/知多/富士/Ichiro's/駒ヶ岳/厚岸/角瓶/季TOKI/倉吉/明石/津貫).
- **노이즈 필터**: グラス·空瓶·コースター·ぬいぐるみ·Tシャツ·세트(本セット)·ケース·缶 등 비-병 품목 제거.
- **추출**: 용량(`\d+ml`/`\d+L`), 숙성(`\d+年`/`\d+ year`), 가격(itemPrice, JPY·세포함).
- 소용량(<500ml) 병은 보존하되 비고에 "직접비교 주의" 플래그(50/180/200/350ml 미니어처).

## KRW 환산 + 한국 반입 추정가 (국가 공통 컴포넌트 `import_landed_cost`)
누적식 (과세가격=CIF):
- 관세 = CIF × **20%**
- 주세 = (CIF + 관세) × **72%**
- 교육세 = 주세 × **30%**
- 부가세 = (CIF + 관세 + 주세 + 교육세) × **10%**
- 합 = CIF + 관세 + 주세 + 교육세 + 부가세 → **배수 ≈ ×2.5555**
- 워크드 예시 — 야마자키 NV ¥13,800 → CIF 130,531 / 관세 26,106 / 주세 112,779 / 교육세 33,834 / 부가세 30,325 → **반입추정 333,574 KRW**.
- `import_landed_cost(cif_krw, tax)` 는 세율 딕셔너리만 주입하면 됨 → **CMPA-13(대만)·CMPA-14(홍콩)** 재사용 가능하게 분리(요청 사항 충족).

### 일본 특이사항 — FTA 미적용 (소싱 인사이트)
- 홍콩 POC의 스카치(한·EU/한·英 FTA 0% 관세, ×2.13)와 달리 **일본산 위스키는 한·일 FTA 부재 → 일반 WTO 관세 20% 그대로 적용**(RCEP의 주류 양허도 제한적). 따라서 단일 배수 ×2.5555만 제시(FTA 0% 컬럼 없음).
- **시사점:** 동일 면세가라도 일본 위스키의 정식 반입 세부담이 스카치보다 구조적으로 높다 → "가성비" 비교 시 반드시 반입세 포함가로 봐야 함.

## ⚠️ CIF 프록시 한계 (정직성 노트)
- Rakuten `itemPrice`는 **일본 소매가(소비세·리테일 마진 포함)**. 이를 과세가격(CIF) 프록시로 쓰면 실제 수입원가보다 **과대추정**(반입추정가는 상한선). 실 CIF는 도매/수출가로 더 낮음. 배송·보험·수수료 제외.
- 한국 개인반입 면세한도(2병·2L·USD400)는 별도. 추정가는 초과 과세분 가늠용.
- 신뢰도 컬럼 "중": 공개 소매가 기반·세금은 추정.

## 백업 소스 — Yahoo!ショッピング API (설계됨, 동일 키 게이트)
- Yahoo! Shopping `itemSearch` 도 공개 JSON API(별도 Client ID 필요). `collect()` 의 클라이언트 추상화에 동형으로 추가 가능 — 교차검증/커버리지 보완용. applicationId 발급과 함께 CEO 승인 시 동시 진행.
- (선택) 価格.com·dekanta(USD)는 비교 참고용, ToS상 크롤 리스크 높아 보류.

## ToS / 사용범위 확인 메모
- **Rakuten Web Service**: 비제휴(non-affiliate)도 API 사용 가능. 단 표시·재배포 가이드라인 존재(상품정보 출처표기, 가격 캐싱 제한 등). **상업적 가격 재게시**는 ToS·IP 리스크 → 내부 측정 보관까지만. 공개/상업 surface 적재는 **CMPA-7 게이트(CEO)**.
- Yahoo! Shopping API도 유사(제휴/비제휴 구분, 표시 가이드라인). 정식 사용 전 각 ToS 명문 재확인 필요.
