# 대만 위스키 가격 크롤링 — CMPA-13 POC

**상태: 내부 R&D / 측정·비공개 한정.** 공개·상업 게시 전 CEO 가드레일(CMPA-7 프레임) 통과 필수. 측정용 로컬 데이터셋이며 CMPA-1 운영 트래커에 적재하지 않았다. (홍콩 CMPA-14 와 동일 가드)

## 결과 요약 (2026-05-30)
- 위스키 **818종** 가격 수집 (병 단위, 액세서리/잔/제빙기 제외).
- 소스 2곳(둘 다 주류 전문 라이선스 리테일러): **my9買酒網 789** · **橡木桶 drinks.com.tw 29**.
- 환율 **1 TWD = 47.9489 KRW** (open.er-api.com 실시간, 2026-05-30).
- 출력: `data/whisky-prices/2026-05_tw_whisky_poc.csv` (12컬럼, 818행). 메트릭: `data/whisky-prices/tw/_poc_metrics.json`.

## 핵심 발견 — 일반 마켓플레이스(PChome/momo)는 위스키 '병' 소스가 아니다
대만 **菸酒管理法(담배주류관리법) 제30조**: 신원·연령 확인이 안 되는 통신판매(인터넷·우편·자판기)로 주류 판매 금지.
→ PChome 24h·momo購物網 같은 종합몰은 **위스키 잔·제빙기·가구·서적만 노출하고 실제 병은 안 판다.**

검증 기록:
- **PChome**: 공개 검색 API `ecshweb.pchome.com.tw/search/v3.3/all/results?q=…` (robots.txt 허용)로 `麥卡倫(Macallan)` 질의 시 결과 9건 전부 위스키 잔·가구·往生紙紮(제수용품). `格蘭菲迪(Glenfiddich)` 은 1건(제수용품). 병 0건 → **소스 부적합**.
- **momo**: robots.txt 가 `/api/*`, `/ajax/*` Disallow → XHR JSON 자동수집은 ToS 상 불가. 종합몰이라 병 미취급 가정과도 일치 → 수집 보류.
- 결론: 대만 위스키 '병' 가격은 **연령확인·라이선스를 갖춘 주류 전문 EC** 에만 존재. 그쪽을 소스로 채택.

## 소스 A — my9買酒網 (Shopify 공개 storefront API)
- 엔드포인트: `https://www.my9.com.tw/products.json?limit=250&page=N` (CMPA-14 홍콩과 동일 패턴, 어댑터 재사용).
- **`product_type == "威士忌"` 로 위스키가 깔끔히 분류**됨(1페이지 250개 중 92개). 페이지당 250개 일괄.
- robots.txt: 표준 Shopify. `products.json` **미차단**(차단은 cart/checkout/account/`collections/*sort_by*` 뿐).
- 가격 필드: variant `price`(現價) / `compare_at_price`(정가). 할인중(compare_at>price) 비고 표기.
- 0원/품절가 variant·미니어처 외 액세서리 제외 필터.

## 소스 B — 橡木桶 drinks.com.tw (ASP.NET 서버렌더 HTML — 본 POC의 HTML 파서 실증)
- 공식 API 없음 → HTML 파싱. `product.aspx?Id=N` 페이지에서:
  - `og:title` = 상품명(마케팅 접미사 `｜…` 제거).
  - `<!--Recommend_SalePrice S-->` 블록 내 `<li data-type="price">N 元</li>` = **建議售價(정가)**.
  - `會員價 N 元` = 비로그인도 HTML 에 노출되는 공개 회원가(現價로 사용).
- 브랜드 페이지 `brand.aspx?Id=B` 가 product Id 목록을 서버렌더 → 위스키 브랜드만 타깃 크롤.
  - 사용 브랜드: **320 噶瑪蘭(Kavalan, 대만 현지 위스키)** · 3 百富 · 66 格蘭菲迪 · 89.
  - robots.txt 없음(404, big5). 보수적 0.5s rate-limit·식별 가능 UA. **상업 재게시는 ToS/IP 리스크 → 내부 측정까지만.**

### HTML 파서 hit-rate (측정값)
| 방식 | 위스키행/후보 | hit-rate |
|---|---|---|
| **브랜드 타깃 크롤** | 29 / 31 | **93.5%** |
| 블라인드 최근 ID 스윕(23430–23470) | 0 / 41 | 0% |
| 가격추출(이름파싱 성공분 중) | 32 / 72 | 44.4% |

→ **생산 권고: 브랜드 인덱스 기반 타깃 크롤**(블라인드 ID 스윕은 비효율). my9(Shopify)는 구조화 JSON 이라 사실상 100% 추출.

## KRW 환산 + 한국 반입 추정가 (pipelines/common/fx_tax.py 재사용)
- `기준가_KRW = 기준가_TWD × 47.9489`.
- `import_landed_cost()` 누적 cascade: 관세20 / 주세72 / 교육세30 / 부가세10.
  - 관세 20%(일반 WTO) → 유효배수 ≈ **×2.556** → 컬럼 `반입추정가_KRW_관세20`.
  - 관세 0%(한·EU/한·英 FTA, 스카치 원산지) → ≈ **×2.130** → 컬럼 `반입추정가_KRW_FTA0`.
  - **원산지 주의**: 대만(Kavalan)·일본 위스키는 한국과 FTA 없음 → 실제 관세 20% 적용. 스카치만 FTA0 해당. 원산지 불확실 → 두 컬럼으로 범위 제시.
- 면세한도(2병·2L·USD400)는 별도. 추정가는 초과 과세분 상한 가늠용(CIF proxy=現地價 KRW, 배송·수수료 제외).

## 출력 스키마 (홍콩 POC 와 동형, 통화만 TWD)
`술이름, 기준가_TWD, 정가_TWD, 환율_TWDKRW, 기준가_KRW, 반입추정가_KRW_관세20, 반입추정가_KRW_FTA0, 재고, 출처, 가져온날짜, URL, 비고`
국내 월간 트래커(`YYYY-MM.csv`)와 **합치지 않는다**(별도 스키마·미적재).

## 재현
```bash
python3 pipelines/tw_whisky/crawl_tw_whisky.py [환율] [날짜] [출력경로]
# 기본: 라이브 TWD→KRW(open.er-api.com)  FX기준일  data/whisky-prices/2026-05_tw_whisky_poc.csv
```
파서·정규화 후단부(CMPA-6)와 적재(CMPA-1)는 CMPA-7 게이트(CEO 승인) 통과 후 연결.
