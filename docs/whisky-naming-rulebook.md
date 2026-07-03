# 위스키 이름 규칙집 (Whisky Naming Rulebook)

> **버전**: v1.0 — 2026-07-01  
> **작성자**: CEO (CMPA-735)  
> **목적**: 위스키 이름을 파싱·매칭·저장할 때 공통으로 따르는 토큰 정의와 메타데이터 스키마.  
> 이 문서가 코드·데이터·문서에서 상충하는 기준의 정본(source of truth)이 된다.

---

## 1. 왜 규칙집이 필요한가

위스키 이름에는 **브랜드·숙성년수·캐스크 종류·도수 특성·에디션** 등 여러 의미를 가진 토큰이
조합된다. 같은 브랜드라도 이 토큰이 하나라도 다르면 **서로 다른 SKU**다. 규칙 없이 이름을
덩어리째 비교하면 다음 두 가지 오류가 생긴다.

| 오류 유형 | 사례 | 결과 |
|---|---|---|
| 가짜 딜 (오매칭) | '제임슨'(표준)이 '제임슨 18년'에 매칭 | −34만원 가짜 절약 표시 |
| 같은 제품 분리 | '발베니 12 더블우드'와 '발베니 더블우드 12'를 다른 제품 취급 | 가격 분산 |

→ **핵심 토큰을 정의하고, 토큰별로 동치 규칙을 명시한다.**

---

## 2. 이름의 구조

위스키 이름은 다음 필드들의 조합이다. 순서는 제품마다 다를 수 있다.

```
[브랜드] [베이스명] [숙성년수] [캐스크/피니시 종류] [도수 특성] [스타일 특성] [에디션/시리즈] [용량]
```

예시:
```
The Balvenie  DoubleWood  12 Year Old   [double cask]  [40%]  -  -  700ml
발베니         더블우드     12년          [더블캐스크]   40도  -  -  700ml

Glengoyne  -  -  Cask Strength  Batch 171  -  NAS  59%  -  700ml
글렌고인    CS   배치171        NAS         59도                  700ml
```

---

## 3. 토큰 정의 (SKU를 가르는 핵심 토큰)

### 3.1 숙성년수 (`age`)

> **이 토큰의 값이 다르면 서로 다른 SKU다.** 절대 병합 금지.

| 표기 패턴 | 예시 | 정규화값 |
|---|---|---|
| 한국어 `N년` | `12년`, `18년` | `12`, `18` (정수) |
| 영어 `N Year Old` | `12 Year Old`, `12 Years Old` | `12` |
| 영어 `N Year` 단독 | `18 Year`, `15y` | `18` |
| NAS (No Age Statement) | 연도 표기 없음, 일부 NAS 명시 | `NAS` |
| 빈티지 연도 (`YYYY`) | `2005 Vintage`, `1990 31년` | 메타데이터에서 **별도 필드** `vintage_year`로 분리, `age`와 혼동 금지 |

**파서 규칙:**
- 정규식: `r"(\d{1,2})\s*(년|year\s*old|year\s*s?\s*old|years?\s*old|y\b)"` (대소문자 무시)
- 숫자 범위: `1`–`62` (62년 건 살루트 최고령 기준)
- ⚠️ 4자리 숫자는 빈티지 연도일 가능성 → `vintage_year` 필드로 별도 분리
- ⚠️ 숙성년수가 제품명 중간에 붙은 경우(예: `Ballantine's 21 Artist Edition 5`) — `Artist Edition 5`에서 `5`는 시리즈 번호지 숙성년수가 아님 → 앞에 오는 `N Year`/`N년` 패턴만 `age`로 인정

---

### 3.2 캐스크 스트렝스 (`is_cs`)

> **CS 여부가 다르면 다른 SKU다.** 표준 도수(40/43/46%) 제품과 병합 금지.

| 표기 | 예시 |
|---|---|
| 영어 약자 | `CS`, `C/S` |
| 영어 전체 | `Cask Strength`, `Cask-Strength` |
| 한국어 | `캐스크스트렝스`, `캐스크 스트렝스` |
| 고도수 신호 | ABV ≥ 55% — 단독으로는 CS 판정 불가, 명시 표기 필요 |

**파서 규칙:**
- 정규식: `r"\b(CS|C/S|cask\s*strength)\b"` (대소문자 무시)
- `is_cs` = `True` / `False`
- 도수(ABV) 필드는 별도 `abv` 컬럼에 수치로 저장 (예: `59.2`)

---

### 3.3 피티드 (`is_peated`)

> **피티드 여부가 다르면 다른 SKU다.** 비피티드 표준 릴리즈와 병합 금지.

| 표기 | 예시 |
|---|---|
| 영어 | `Peated`, `Heavily Peated`, `Lightly Peated` |
| 한국어 | `피티드` |
| 특수 에디션명 | `Week of Peat`(발베니), `Sweet Peat`(라가불린 오퍼맨) |
| 간접 표기 | 증류소 자체가 피트 스타일 (아드벡·라프로익·탈리스커)이면 별도 표기 없어도 is_peated=True로 사전 등록 |

**파서 규칙:**
- 정규식: `r"\b(peated|lightly\s*peated|heavily\s*peated|피티드|peat)\b"` (대소문자 무시)
- `is_peated` = `True` / `False`
- ⚠️ '피트 스타일 증류소' 목록은 `INHERENTLY_PEATED_DISTILLERIES`로 별도 관리:
  `{Ardbeg, Laphroaig, Lagavulin, Talisker, Port Charlotte, Octomore, Kilchoman, Caol Ila, ...}`

---

### 3.4 캐스크/피니시 종류 (`cask_type`)

> **캐스크 종류가 다르면 다른 SKU다.** 특히 같은 브랜드·같은 년수라도 캐스크가 다르면 분리.

| 캐스크 유형 | 영문 표기 | 한국어 표기 |
|---|---|---|
| 셰리 캐스크 | Sherry Cask / Sherry Oak / Oloroso | 셰리 캐스크, 셰리캐스크 |
| 버번 배럴 | Bourbon Barrel / Bourbon Cask / American Oak | 버번 배럴, 버번캐스크 |
| 포트 캐스크 | Port Cask / Port Wood / Port Pipe / Ruby Port | 포트 캐스크 |
| PX (Pedro Ximenez) | PX / Pedro Ximenez | PX, 페드로 히메네스 |
| 럼 캐스크 | Rum Cask | 럼 캐스크 |
| 와인 피니시 | Wine Cask / Wine Finish | 와인 캐스크 |
| 미즈나라 | Mizunara | 미즈나라 |
| 더블 캐스크/우드 | Double Cask / Double Wood | 더블캐스크, 더블우드 |
| 트리플 캐스크/우드 | Triple Cask / Triple Wood | 트리플캐스크 |
| 쿼터 캐스크 | Quarter Cask | 쿼터 캐스크 |
| 캐리비안 캐스크 | Caribbean Cask | 캐리비안 캐스크 |
| 프렌치 오크 | French Oak | 프렌치 오크 |
| 마데이라 캐스크 | Madeira Cask | 마데이라 캐스크 |
| 소비뇽 블랑 | Sauvignon Blanc | 소비뇽블랑 |
| 헝가리안 오크 | Hungarian Cask | 헝가리안 캐스크 |
| 포르투기즈 | Portuguese Cask | 포르투기즈 캐스크 |

**파서 규칙:**
- `cask_type` 필드는 문자열 리스트 (여러 캐스크를 거칠 수 있음)
- 주요 정규식 패턴 (예시): `r"(sherry|셰리|bourbon|버번|port|포트|PX|rum|럼|double\s*(cask|wood)|triple\s*(cask|wood)|quarter\s*cask|쿼터\s*캐스크|madeira|미즈나라)"`
- "Double Wood"와 "Double Cask"는 동의어 취급 (예: 발베니 더블우드 = 더블캐스크)

---

### 3.5 색상/라벨 등급 (`label_color`)

> 조니워커처럼 **라벨 색상이 제품 등급을 의미하는 브랜드**에서 사용. 다른 브랜드에서 색상이 나오면 단순 제품명 일부.

| 색상 토큰 | 브랜드 | 설명 |
|---|---|---|
| Red | 조니워커 | Red Label (NAS, 저가) |
| Black | 조니워커 | Black Label (12년) |
| Green | 조니워커 | Green Label (15년, 블렌디드몰트) |
| Gold | 조니워커 | Gold Label Reserve |
| Blue | 조니워커 | Blue Label (최고급) |
| Double Black | 조니워커 | 스모키 강화 버전 |
| Black | 에반 윌리엄스, 제임슨 | 별도 브랜드 제품명 일부 |

**파서 규칙:**
- `label_color` 필드는 브랜드 컨텍스트에서만 의미 있음
- 조니워커 한정: `Red|Black|Green|Gold|Blue|Double Black` → 독립 SKU
- 다른 브랜드의 색상 토큰은 단순 제품명(`name_ko`/`name_en`)의 일부로 보존

---

### 3.6 에디션/시리즈 (`edition`)

> 에디션/시리즈 차이 = 다른 SKU. 단, 배치 번호(배치 N)는 같은 에디션의 로트 번호 → 별도 `batch` 필드.

| 토큰 유형 | 예시 | 필드 |
|---|---|---|
| 에디션명 | `Distillers Edition`, `Special Release` | `edition` |
| 배치 번호 | `Batch 171`, `Batch No.12` | `batch` |
| 시리즈 번호 | `No.1`, `No.7`, `Vat 1`, `Vat 3` | `series_no` |
| 리미티드/한정 | `Limited Edition`, `Special Release FY24` | `is_limited=True` |
| 컬렉션명 | `Perpetual Collection`, `Groundbreaker Collection` | `collection` |
| 협업 에디션 | `Aston Martin F1`, `Harris Reed Edition` | `edition` |

**파서 규칙:**
- `edition` = 자유 문자열 (정규화보다 보존 우선)
- `is_limited` = `True` / `False` (limited·special·리미티드·한정 키워드)
- ⚠️ 에디션명만 다른 SKU는 같은 병에 다른 박스/라벨이 붙은 경우도 있음 → 보드 판단 필요 시 confidence = low

---

### 3.7 스타일 특성 (`style`)

> 같은 브랜드·년수라도 스타일이 다르면 다른 SKU.

| 스타일 토큰 | 예시 | 설명 |
|---|---|---|
| 싱글배럴 | `Single Barrel`, `Single Cask` | 단일 캐스크 |
| 스몰배치 | `Small Batch` | 소규모 배치 |
| 스몰배치 셀렉트 | `Small Batch Select` | 선별 소규모 배치 (스몰배치와 다른 SKU) |
| 바틀드인본드 | `Bottled-in-Bond`, `BIB` | 미국 BIB 규정 (100 proof, 4년+) |
| 싱글포트스틸 | `Single Pot Still` | 아일랜드 전통 스타일 |
| 솔레라 | `Solera` | 글렌피딕 15 솔레라 방식 |
| 스모키/스모크 | `Heavily Peated`, `Smoke` | 별도 스모키 버전 |

---

## 4. 매칭 시 SKU 동치 규칙

SKU 매칭 (오매칭 방지)에서 아래 규칙을 **항상** 적용한다 (CMPA-177 보드 확정).

### 4.1 반드시 다른 SKU (병합 금지)

| 조건 | 예시 |
|---|---|
| `age` 값이 다름 | 제임슨 ≠ 제임슨 18년 |
| `is_cs` 값이 다름 | 글렌피딕 15년 ≠ 글렌피딕 15년 CS |
| `is_peated` 값이 다름 | 카퍼도닉 18년 ≠ 카퍼도닉 18년 피티드 |
| `cask_type` 이 다름 | 글렌피딕 12년 ≠ 글렌피딕 12년 셰리캐스크 |
| `label_color` 이 다름 | 조니워커 블랙 ≠ 조니워커 블루 |
| `edition` 이 다름 | 탈리스커 10년 ≠ 탈리스커 디스틸러스 에디션 |

### 4.2 같은 SKU로 취급 (동의어)

| 패턴 | 동의어 그룹 |
|---|---|
| 용량 변형 | 700ml / 750ml / 1L / 1.75L → 같은 제품, `volume_ml`만 다름 |
| 자연어 변형 | `Year Old` / `Years Old` / `년` |
| 영문 / 한글 | `Balvenie` = `발베니`, `Laphroaig` = `라프로익` |
| 관사 | `The Glenlivet` = `Glenlivet` |
| 배치 번호 | 글렌고인 CS 배치 170 = 글렌고인 CS 배치 171 (같은 에디션, 배치만 다름) |
| "스트렝스" 스펠 변형 | `Cask Strength` = `Cask-Strength` = `캐스크스트렝스` |

### 4.3 매칭 위험 패턴 (CMPA-177 사건 교훈)

모델 숫자(40/46/101)가 제품명에 붙을 때 숙성년수로 오인 금지:

| 위험 토큰 | 의미 | 올바른 처리 |
|---|---|---|
| `46` | 메이커스 마크 46 (제품명) | `age` 아님 → 제품명 일부 |
| `101` | 와일드터키 101 (Proof, 도수) | `age` 아님 → `proof` 또는 제품명 일부 |
| `No.7` | 잭다니엘 올드 No.7 | `age` 아님 → 시리즈명 |
| `1794` / `MCDXCIV` | 린도어스 설립연도 사용 | `age` 아님 → 에디션명 |

---

## 5. 용량 처리 규칙

용량은 **제품명 토큰이 아니라 별도 메타데이터**이다.

| 용량 패턴 | 정규화 | 메모 |
|---|---|---|
| `700ml`, `700 ml` | `volume_ml = 700` | 스코치·아이리시·버번 표준 |
| `750ml` | `volume_ml = 750` | 미국 시장 표준 |
| `1L`, `1000ml` | `volume_ml = 1000` | 대용량 소매 |
| `1.75L`, `1750ml` | `volume_ml = 1750` | 더블 대용량 |
| `500ml` 미만 | **수집 금지** (CMPA-733) | 미니어처/하프보틀 |
| `450ml` | `volume_ml = 450` | 국산 기타재제주(골든블루 등) 예외 허용 |

**파서 규칙:**
- 정규식: `r"(\d+(?:\.\d+)?)\s*(ml|l(?![a-z]))"` (대소문자 무시)
- `volume_ml`을 추출한 뒤 **이름 문자열에서 용량 표기를 제거**해 순수 제품명만 남긴다
- 제품명에서 제거할 토큰: `700ml`, `1L`, `1.75L` 등 용량 표기 전체

---

## 6. NAS (No Age Statement) 처리

`age = NAS`인 경우는 숙성년수 표기가 없는 제품이다.

- NAS 제품은 `age = NAS` 또는 `age = None`으로 저장
- NAS + 캐스크 종류 → 여전히 캐스크가 다르면 다른 SKU
- NAS ≠ 숙성년수 있음 (NAS 제품과 12년짜리를 병합 금지)
- **빈티지 연도**(`1990`, `2005` 등)는 NAS 처리하지 말고 `vintage_year`에 별도 저장

---

## 7. 메타데이터 스키마

위스키 SKU 한 개에 대한 표준 메타데이터:

```python
{
  # === 식별자 ===
  "canonical_id": "w008",          # WK 내부 ID (whisky-list.csv 기준)
  
  # === 이름 ===
  "name_ko": "발베니 12년 더블우드",
  "name_en": "The Balvenie DoubleWood 12 Year Old",
  "brand": "Balvenie",
  
  # === 카테고리 ===
  "category": "싱글몰트",           # 싱글몰트/블렌디드몰트/블렌디드/버번/아이리시/라이/그레인/기타
  "origin": "스코틀랜드-스페이사이드",
  
  # === SKU 구분 핵심 토큰 ===
  "age": 12,                        # int | "NAS" | None
  "vintage_year": None,             # int | None  (4자리 빈티지 연도)
  "is_cs": False,                   # 캐스크 스트렝스 여부
  "is_peated": False,               # 피티드 여부
  "cask_type": ["double_wood"],     # list[str] — 여러 캐스크 가능
  "label_color": None,              # "Red"|"Black"|"Green"|"Gold"|"Blue"|None
  
  # === 에디션/시리즈 ===
  "edition": None,                  # str | None
  "batch": None,                    # str | None (배치 번호)
  "series_no": None,                # str | None
  "collection": None,               # str | None
  "is_limited": False,
  
  # === 스타일 ===
  "style": None,                    # "single_barrel"|"small_batch"|"bottled_in_bond"|None
  
  # === 물리 특성 ===
  "abv": 40.0,                      # float | None (도수 %)
  "volume_ml": 700,                 # int | None
  
  # === 데이터 품질 ===
  "confidence": "high",             # "high"|"med"|"low"
  "notes": "셰리캐스크 마감 명작",
}
```

---

## 8. 이름 정규화 순서 (파서 적용 순서)

1. **용량 추출 & 제거**: 이름에서 `700ml`, `1L` 등 추출 → `volume_ml` 저장 → 이름에서 제거
2. **번들 노이즈 차단**: `is_bundle_noise()` 통과 못 하면 격리 (잔세트/기프트세트)
3. **관사 정규화**: `The `, `더 ` 제거 (matching용, 원문은 보존)
4. **숙성년수 추출**: `age` 패턴 매칭 → 정수 또는 NAS
5. **CS 추출**: `is_cs` 플래그
6. **피티드 추출**: `is_peated` 플래그
7. **캐스크 유형 추출**: `cask_type` 리스트
8. **색상 라벨 추출**: 브랜드 컨텍스트에서 `label_color`
9. **에디션/배치 추출**: `edition`, `batch`, `series_no`
10. **나머지** → `name_ko`/`name_en`의 순수 제품명으로 정리

---

## 9. 실수 방지 체크리스트

- [ ] 숙성년수 단독으로 매칭하지 않는다 — 브랜드 + 년수 + 캐스크 조합으로 매칭
- [ ] NAS 제품과 년수 있는 제품을 병합하지 않는다
- [ ] 4자리 연도(2005, 1990)를 `age`로 파싱하지 않는다
- [ ] 모델 번호(46, 101)와 Proof(100 Proof)를 `age`로 파싱하지 않는다
- [ ] `is_cs`가 다른 제품끼리 가격 비교 라인에 넣지 않는다
- [ ] 피티드/비피티드 같은 브랜드·같은 년수를 동일 SKU 취급하지 않는다
- [ ] 용량(700ml ≠ 1L)이 다른 제품의 병당 단가를 직접 비교하지 않는다 — 100ml당으로 환산
- [ ] 번들(잔세트/기프트) 리스팅을 단품 가격으로 사용하지 않는다

---

## 10. 자주 혼동되는 제품 쌍

| 제품 A | 제품 B | 구분 포인트 |
|---|---|---|
| 글렌피딕 12년 | 글렌피딕 12년 셰리캐스크 | `cask_type` 다름 |
| 발베니 12년 더블우드 | 발베니 12년 몬틸라 | `cask_type` 다름 |
| 아벨라워 12년 | 아벨라워 아부나흐 | NAS + CS ≠ 12년 |
| 조니워커 블랙라벨 12년 | 조니워커 더블블랙 | 에디션+스타일 다름 |
| 와일드터키 8년 | 와일드터키 레어브리드 | NAS+CS ≠ 8년 |
| 와일드터키 켄터키스피릿 | 와일드터키 101 | 스타일 다름 (싱글배럴 vs 고도수 블렌드) |
| 포 로지스 버번 | 포 로지스 스몰배치 | `style` 다름 |
| 포 로지스 스몰배치 | 포 로지스 스몰배치 셀렉트 | 다른 레시피 = 다른 SKU |
| 맥캘란 더블캐스크 12년 | 맥캘란 셰리오크 12년 | `cask_type` 다름 |
| 카퍼도닉 18년 | 카퍼도닉 18년 피티드 | `is_peated` 다름 |
| 듀어스 더블더블 21년 | 듀어스 더블더블 21년 스톤토스티드 | `edition` 다름 |
| 듀어스 더블더블 21년 | 듀어스 더블더블 21년 미즈나라캐스크 | `cask_type` 다름 |

---

## 11. 관련 정책 참조

- **CMPA-177**: SKU 구분 토큰 정의 (숙성년수/CS/피티드 = 다른 제품, 용량 = 같은 제품 변형)
- **CMPA-733**: 500ml 미만 수집 금지 (`is_undersized_volume`, `is_undersized_by_name`)
- **CMPA-177 오매칭 가드**: `_model_nums`(40–129, 용량·도수·나이·서수·연도 제외) — `pipelines/shilla_dutyfree/analyze_attractiveness.py`
- **`pipelines/common/whisky_quality.py`**: `is_bundle_noise`, `is_collectible`, `is_quarantined` 공통 게이트
- **`assets/whisky-list.csv`**: canonical SKU 목록 (정본)
- **`assets/whisky-aliases.csv`**: 동의어 목록

---

*이 문서는 위스키 데이터 관련 모든 작업의 공통 레퍼런스다. 변경 시 CMPA 이슈로 보드 확정 후 갱신.*
