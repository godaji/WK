# pet_friendly — 반려동물 동반(펫프렌들리) 식당 맵 (CMPA-105, Phase-0 POC)

콜키지프리/할랄 맵 엔진을 **포크(복사)** 해 속성만 "반려동물 동반"으로 교체한 파이프라인.
전략 근거: [CMPA-103](../../) 니즈 버티컬 리서치 TOP1(2026-03 동반업소 신법·반려인 1,500만·
공공 등록부 존재) · 보드 승인 confirmation `adf6fda2`.

> ⚠️ **내부 R&D 전용.** 외부 공개·배포는 게이트 `c7405e7d` 계열 + 공공데이터 라이선스·
> 개인정보 검토 통과 전 금지. 무비용(keyless DiningCode + 공공 등록부)만 사용.

## 폴더 구조 (CMPA-86 미러링)
- `pipelines/pet_friendly/` — 엔진(이 폴더)
- `data/pet-friendly/{역}_반려동물동반.csv` + `_runs/` 날짜 스냅샷 — 데이터셋
- `reports/pet-friendly/{역}_반려동물동반.{md,html}` + `_runs/` — 사람이 보는 리포트

## 데이터원 (둘 다 keyless·무비용)
1. **DiningCode** keyless isearch — `애견동반`/`반려동물동반` 키워드 태그가 가장 강한 신호.
   (콜키지/할랄 finder 와 동일한 `dc_search`.)
2. **공공 등록부** — 2026-03 신법 '반려동물 동반 가능 업소'(foodsafetykorea/data.go.kr,
   전국 ~623곳). 법정 등록 = **권위 교차검증**(등록=인증 배지).

## 2-Tier 분류 (`pet_tier`)
- **A·동반명시**: 이름/카테고리/키워드에 애견동반·반려동물동반·펫프렌들리·반려견 동반 등 명시.
- **B·추정(확인필요)**: 동반 명시는 없으나 야외/테라스/루프탑/마당/정원 신호 → 동반 가능성.
- 제외: 신호 없음.

전 행 `주의` 컬럼에 "방문 전 매장 확인 필수" — 정책 변동성이 크다(동반 철회 빈번).

## 사용법
```bash
# 1) DiningCode 기반 맵 생성(라이브)
python3 pipelines/pet_friendly/find_pet_friendly.py --station 성수역 --radius 700 --run-date 2026-05-31

# 2) 공공 등록부 교차검증(등록부 CSV 가 있을 때 — 등록 배지)
python3 pipelines/pet_friendly/find_pet_friendly.py --station 성수역 --registry data/pet-friendly/전국_반려동물동반_공공.csv

# 3) 공공 등록부 ingest(파일데이터 CSV → 권위 정본)
python3 pipelines/pet_friendly/ingest_petkorea.py --csv <다운로드.csv> --source 식품의약품안전처 --name 전국

# 신규 역 추가: STATION_COORDS 에 좌표 등록 또는 --lat/--lng 주입
```

## 공공 등록부 라이브 ingest — CEO 게이트 (CMPA-86 할랄과 동일 제약)
현 환경 probe(2026-05-31): `data.go.kr` egress 차단(ConnectionReset), `apis.data.go.kr`
HTTP 500, foodsafetykorea OpenAPI 는 승인 serviceKey 필요. → **라이브 등록부 ingest 는
(a) serviceKey 발급/승인 + (b) egress 허용** 이 있어야 가능(CEO 에스컬레이션).
그 전까지 `--csv` 수동 다운로드 경로 + `registry_match.py` 조인이 동작하며, 매핑·조인 로직은
`test_registry_match.py`(fixture) 로 검증 완료. 등록부 미연결 시 맵의 `등록부매칭`=`미확인`.

## 테스트 (네트워크 불필요)
```bash
python3 pipelines/pet_friendly/test_pet_friendly.py      # 2-tier 분류기 + 대분류
python3 pipelines/pet_friendly/test_registry_match.py    # 등록부 교차매칭 조인(fixture)
```

## Phase-0 산출물(성수역, 2026-05-31)
도보 700m, 140곳 = A·동반명시 53 + B·추정 87. 카페·브런치 65%. 등록부 교차검증 대기.
다음 역 후보: 연남동(홍대입구), 한남, 강남(콜키지 자산 재사용).
