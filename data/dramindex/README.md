# DramIndex — 데이터 인덱스

위스키 산업 펀더멘털 데이터. 수집일 2026-06-10. 향후 시계열 분석 및 블로그 소재용.

---

## data/ 파일 목록

### 수급 / 교역량

| 파일 | 내용 | 기간 | 출처 |
|---|---|---|---|
| `comtrade_220830_2026-06-10.csv` | 영국→세계 위스키(HS 220830) 수출 물량·금액 | 2020-2024 | UN Comtrade 무료 API |
| `swa_exports_2026-06-10.csv` | 스카치 위스키 전체 수출 (병 수·GBP) | 2019/2022/2023/2025 | SWA Facts & Figures |
| `korea_whisky_imports_2026-06-10.csv` | 한국 위스키(HS 220830) 수입 물량·금액 | 2016-2024 | UN Comtrade + 관세청 |

**핵심 수치 — 한국 수입:**
- 2020 COVID 저점: 15,923t → 2022 하이볼 붐: 27,038t (+70%) → 2023 역대 최고: 30,586t
- 2024: 27,441t (-10.3%) — 경기 둔화 + 정치 불확실성

### FX

| 파일 | 내용 | 기간 | 출처 |
|---|---|---|---|
| `krw_usd_fx_annual_2026-06-10.csv` | KRW/USD 연간 평균 환율 | 2015-2024 | Frankfurter.dev (ECB 기준) |

**핵심:** 2017 저점 1,067 → 2024 고점 1,475 (+38% 원화 약세)

### 증류소 재고 (Maturing Inventory)

| 파일 | 내용 | 기간 | 출처 |
|---|---|---|---|
| `distillery_inventory_2026-06-10.csv` | Diageo 숙성중 재고 (총계·위스키·스카치 분리) | FY2020-FY2025 | SEC 20-F EDGAR |

**핵심:** FY2020 £4,562M → FY2025 $8,677M (+42% 5년, 통화 GBP→USD 전환 주의)
- 스카치만: FY2025 $5,659M (전체의 65%)

### 상장사 재무제표 (P&L 10년)

| 파일 | 회사 | 기간 | 통화 | 결산월 | 출처 |
|---|---|---|---|---|---|
| `diageo_financials_2026-06-10.csv` | Diageo (DEO) | FY2016-2025 | GBP (FY2024+ USD) | 6월 | SEC 20-F/6-K |
| `diageo_regions_2026-06-10.csv` | Diageo 지역별 매출 | FY2020-2025 | USD | 6월 | SEC 20-F/6-K |
| `brown_forman_financials_2026-06-10.csv` | Brown-Forman (BF.B) | FY2016-2025 | USD | 4월 | SEC 10-K |
| `pernod_ricard_financials_2026-06-10.csv` | Pernod Ricard (RI.PA) | FY2016-2025 | EUR | 6월 | 연결재무/URD |

**3사 공통 패턴 — 위스키 수퍼사이클 종료:**

| 회사 | 고점 연도 | 고점 매출 | FY2025 매출 | 변화 |
|---|---|---|---|---|
| Diageo | FY2023 | £17,113M | $20,245M | 영업이익 -27.8% |
| Brown-Forman | FY2023 | $4,228M | $3,975M | -5.0% |
| Pernod Ricard | FY2023 | €12,137M | €10,959M | 유기적 -3.0% |

---

## report/ 파일 목록

| 파일 | 내용 |
|---|---|
| `dramindex_phase0_2026-06-10.md` | Phase-0 종합 리포트 (한국어, 시계열 분석 포함) |

---

## 분석 시 주의사항

1. **Diageo 통화 전환**: FY2020-2023 = GBP, FY2024-2025 = USD. 직접 비교 시 연도별 GBP/USD FX 적용 필요.
2. **Brown-Forman FY2016**: 소비세 포함 구 정의($4,011M). FY2017+($2,994M)와 직접 비교 불가.
3. **Comtrade 2021 물량 이상값**: 집계 방식 차이로 netWgt 값이 비정상적으로 높음 — 금액(value_usd)으로 분석 권장.
4. **한국 수입 2019**: 물량만 있고 금액 없음 (관세청 원본 미확보).
5. **SWA 2022**: 병 수 미기재, "£6B 이상" 정성적 표현만.
6. **모든 파일 수집일 = 2026-06-10** (CMPA-156 데이터 관리 원칙 준수).

---

## 향후 확장 후보

- Campari (CPR.MI, 이탈리아) — Glen Grant, Wild Turkey
- Rémy Cointreau (RCO.PA, 프랑스) — Bruichladdich, The Westland
- HMRC 영국 위스키 생산량 클리어런스 (연간 통계)
- Korea 관세청 HS 220830 월간 수입 시계열 (가격 선행지표 연구 — CMPA-276)
- Companies House 비상장 스카치 증류소 재무 (Edrington/맥캘란, William Grant/글렌피딕)
