# CMPA-52 — 일본 위스키 데이터 수집: Rakuten 대안 (검증 완료)

- 작성: CMO · 날짜: 2026-05-31 (KST) · 분류: 내부 R&D / 측정·비공개 (메모리 ssandi/dailyshot/cmpa9 가드레일 유지)
- 결론 한 줄: **API 키가 필요 없는 일본 주류 리테일러의 Shopify `/products.json` 공개 엔드포인트**로
  전환 권고. 홍콩(CMPA-14)에서 검증된 패턴을 그대로 적용 → 오늘 라이브로 **1,435종** 수집 성공.
  Rakuten 의 셀프발급 불가 `RAKUTEN_APP_ID` 블로커(메모리 cmpa11/cmpa47)를 **완전히 우회**.

---

## 1. 왜 Rakuten 이 막혔나 (배경)

Rakuten Ichiba API 자체는 동작하지만, 호출에 필요한 `applicationId` 를 **에이전트가 셀프
발급할 수 없다**(개발자 등록 = 사람/board 작업). 그래서 `pipelines/jp_rakuten/rakuten_poc.py`
는 fixture 모드로만 검증되고 LIVE 가 board 의 키 입력에 무기한 대기 중이었다(CMPA-47 blocked).
→ "Rakuten 으로는 어렵다"는 사용자 판단과 일치. **키 의존을 없애는 것**이 핵심.

## 2. 검토한 대안 (4종)

| 대안 | 키/등록 | 에이전트 단독 실행 | 커버리지 | 판정 |
|---|---|---|---|---|
| **A. JP 리테일러 Shopify `/products.json`** | **불필요** | **가능(즉시)** | 위스키 500+종/사이트 | ✅ **채택** |
| B. Yahoo! Shopping API v3 (일본) | 필요 (Client ID, Yahoo Japan ID) | 불가 — board 등록 필요 | Rakuten급 대형 | 🟡 폴백(Rakuten 과 동일 블로커 클래스) |
| C. 価格.com (kakaku.com) 스크레이프 | 불필요 | 가능하나 봇차단/robots 리스크 | 가격비교 집계 | 🟠 보조 신호만 |
| D. Amazon JP PA-API | 필요 (어필리에이트 승인) | 불가 | 대형 | ❌ 진입장벽 높음 |

핵심 인사이트: **B·D 는 Rakuten 과 똑같은 "사람이 키를 발급해야 함" 블로커**를 가진다.
이 이슈가 요구하는 건 *그 블로커를 없애는* 방법이므로, **A(키 불필요)**가 정답.

## 3. 채택안 A — 검증 결과 (2026-05-31 라이브)

검증된 소스(모두 정식 주류 소매, Shopify):

| 출처 | 도메인 | `/products.json` | 위스키 행 |
|---|---|---|---|
| 酒類ドットコム | `www.syurui.co.jp` | HTTP 200 | **601** |
| SAKE People | `sake-people.com` | HTTP 200 | **506** |
| 酒庫住田屋 | `shop.sumidaya.co.jp` | HTTP 200 | **328** |
| **합계** | | | **1,435** |

- 플래그십 전 종류 확인됨: 山崎(12년/리미티드/25년), 白州(12년/700ml/스토리), 響, 余市 10년,
  厚岸(절기 시리즈), イチローズモルト(MWR/DD/와인우드), 知多, 角 등.
- 가격 필드: `variant.price`=현재 판매가(기준가), `compare_at_price`>price 면 **할인중**으로 기록(17건).
  700/750ml 표준 우선, 없으면 최저가 variant.
- 각 행에 **JPY → KRW 환산 → 한국 개인반입 추정가(관세20/주세72/교육세30/부가10, 배수≈2.5555x)**
  를 부착 — CMPA-11에서 추출한 국가무관 `pipelines/common/fx_tax` 재사용.

### 법무·robots (홍콩과 동일 포지션)
3개 사이트 robots.txt 모두 `/collections/*sort_by*` 등 **필터 변형만 Disallow**하고
**`/products.json` 은 차단하지 않음**(공개 스토어프론트 엔드포인트). 수집은 **내부 R&D·측정용**
이며, 공개/상업 재배포는 CMPA-15 상위 가드레일(법무) 통과 후에만 — 메모리 dailyshot/ssandi 일관.
예의상 1 req/s rate-limit 적용.

## 4. 산출물 (이번 heartbeat 에서 생성)

- 수집기: `pipelines/jp_shopify/collect_jp_shopify.py` — 키 불필요, 즉시 실행 가능.
- 데이터: `data/whisky-prices/jp/2026-05_jp_shopify_poc.csv` (1,435행) +
  날짜 스냅샷 `_runs/2026-05_jp_shopify_poc__run2026-05-31.csv` (CMPA-38 규칙).
- 스키마: 술이름·기준가_JPY·정가_JPY·환율·기준가_KRW·한국반입추정가_KRW·반입배수·재고·출처·날짜·URL·비고.

## 5. 한계 / 캐비엇

- 이름 정규화: 현재 원문 제목 그대로. CMPA-22 `normalize_whisky_name.py`/alias 자산에 태워
  canonical id 매칭하면 한국·홍콩·일본 가격을 **동일 병 기준으로 교차비교** 가능(다음 단계).
- 소매가 ≠ 정가(점포별 상이), 재고변동·가격변동 큼 → 수집일 명시(데이터에 포함).
- 1,435종은 3개 사이트 기준. 소스 추가로 확장 가능(동일 패턴, 코드 변경 최소).

## 6. 권고 / 다음 액션

1. **Rakuten LIVE 추진 중단(또는 선택적 보류)** — 키 블로커 해소 전까지 가치 없음. CMPA-47 을
   "Shopify 대안으로 대체(superseded)"로 정리하고 board 키 대기 해제 권고.
2. 본 수집기를 **CMPA-30 overseas 오케스트레이터/주간 루틴(f709eab4)** 의 JP 단계로 승격
   (현재 Rakuten fixture 자리 → Shopify 라이브). 별도 child 이슈로 배선.
3. CMPA-22 정규화 연결로 KR/HK/JP 3국 교차비교 테이블 완성.

> 외부 공개/상업화는 여전히 CMPA-15/board gate(c7405e7d) 대상. 본 산출물은 데이터-소싱 *방법* 의
> 해결이며 측정·비공개 한정.
