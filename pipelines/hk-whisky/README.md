# 홍콩 위스키 가격 크롤링 — CMPA-14 POC

**상태: 내부 R&D / 측정·비공개 한정.** 공개·상업 게시 전 CEO 가드레일(CMPA-7 프레임) 통과 필수. 이 산출물은 측정용 로컬 데이터셋이며 CMPA-1 운영 트래커에 적재하지 않았다.

## 결과 요약 (2026-05-30)
- 위스키 **1,828종** 가격 수집 (병 단위, 액세서리/세트 제외).
- 소스 3곳: Caskells 401 · The Rare Malt 600 · Mizunara 827.
- 할인중(정가>판매가) 76종 → 다중 가격 필드 처리 검증됨.
- 환율 HKD→KRW **192.27** (open.er-api.com 실시간, 2026-05-30).
- 출력: `data/whisky-prices/2026-05_hk_whisky_poc.csv` (12컬럼, 1,828행).

## 주 소스(Watson's Wine) — 차단 기록
`watsonswine.com` 은 **Akamai 봇 차단** 뒤에 있어 데이터센터 IP의 단순 HTTP 요청은 `robots.txt` 포함 전 경로 **403 Access Denied**(`errors.edgesuite.net` 참조). curl(브라우저 UA 포함) · WebFetch 모두 403.
→ 단순 HTML 크롤 불가. 운영 수집하려면 **헤드리스 브라우저(Playwright) + 거주용(residential) 프록시** 필요 = 별도 인프라/비용 항목 → CEO 라우팅 대상. POC 단계에서는 동일 시장(홍콩·영어·HKD)의 보조 전문 리테일러로 대체 달성.

## 보조 소스 — Shopify 공개 storefront API
3곳 모두 Shopify 기반으로 표준 공개 엔드포인트 `/<domain>/products.json?limit=250&page=N` 제공. HTML 파싱 불필요, 구조화 JSON(이름·variant 가격·정가·재고·handle→URL).

### robots.txt / ToS 확인 기록
- 세 도메인 모두 표준 Shopify robots.txt. `products.json` 은 **Disallow 대상 아님** (차단은 `/recommendations/products` 와 계정/체크아웃 경로뿐).
- 요청 시 예의상 1초 rate-limit, 식별 가능한 UA 사용, 페이지당 250개 일괄 — 서버 부하 최소.
- Watson's: robots.txt 자체가 403이라 ToS 명문 확인 불가 → **수집 보류**가 안전.
- 공통 ToS 리스크: 가격의 **상업적 재게시**는 각 사 ToS·IP 리스크 → 측정용 내부 보관까지만 진행. 공개/상업 surface 적재는 CMPA-7 게이트.

## 다중 가격 필드 처리 정책
Shopify variant 는 `price`(현재 판매가)·`compare_at_price`(정가/할인 전) 보유. Watson's 의 regular/offer/online-exclusive/member 다중가와 동형 문제.
- **비교 기준가(`기준가_HKD`) := `price`** — 실제 현재 판매가. Watson's 'offer'(실판매가) 개념에 대응. 마트 현장가와 일관된 "지금 사면 내는 값" 기준.
- **`정가_HKD` := `compare_at_price`** — 할인 중일 때(`compare_at_price > price`)만 기록, 비고에 "할인중" 표시.
- **다중 용량 variant**: 700/750ml 표준 병(grams 650–800) 우선, 없으면 최저가 variant.
- **member/online-exclusive 가**: Shopify 공개 JSON엔 비로그인 공개가만 노출 → 회원가는 비수집(비공개 가격은 R&D 범위 밖). Watson's 운영 수집 시 별도 정책 필요.

## KRW 환산 + 한국 반입 추정가
- `기준가_KRW = 기준가_HKD × 192.27`.
- 반입 추정가(개인수입, 면세한도 초과분 과세 가정. 신고가 proxy = 기준가_KRW, 배송·수수료 제외):
  - 관세 = V × 관세율 / 주세 = (V+관세)×72% / 교육세 = 주세×30% / 부가세 = (V+관세+주세+교육세)×10%
  - 합 = V+관세+주세+교육세+부가세
  - 관세율 20%(일반 WTO) → 배수 ≈ **×2.556**, FTA 0%(한·EU/한·英, 스카치 원산지) → ≈ **×2.130**.
  - CSV에 `반입추정가_KRW_관세20` · `반입추정가_KRW_FTA0` 두 컬럼 병기(원산지 불확실 → 범위 제시).
- 한국 개인 반입 면세한도(2병·2L·USD400 이하)는 별도. 추정가는 초과 과세분 상한 가늠용.

## 재현
```bash
python3 pipelines/hk-whisky/crawl_hk_whisky.py [환율] [날짜] [출력경로]
# 기본: 192.27  2026-05-30  data/whisky-prices/2026-05_hk_whisky_poc.csv
```
파서·정규화 후단부(CMPA-6)와 적재(CMPA-1)는 게이트 통과 후 연결.
