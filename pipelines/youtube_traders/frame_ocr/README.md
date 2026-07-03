# frame_ocr — 유튜브 가격영상 → 정지프레임 → 가격표 crop → OCR (ASR 우회) · CMPA-423

ASR 자막은 429·BGM 으로 불안정하다. 진행자가 **가격표가 또렷한 지점에서 ≥0.5초 화면을
정지**시키는 점을 이용해, 영상 프레임을 직접 분석해 가격을 뽑는다.

> ⚠️ 이 환경엔 **ffmpeg 가 없다** → 영상 디코딩은 전부 `cv2.VideoCapture`(opencv) 로 한다.

## 3단계 스크립트

| 단계 | 스크립트 | 입력 → 산출 |
|---|---|---|
| 1 | `extract_still_frames.py` | mp4 → 정지구간 대표프레임 `{video_id}_{HHMMSS}.jpg` + `manifest.csv` |
| 2 | `crop_price_tag.py` | 정지프레임 → 가격표 영역 crop (전역 흰사각형 탐색 + 약한 위치 prior) |
| 3 | `extract_price_ocr.py` | crop → `(제품명, 가격_KRW, 용량_ml)` 구조화 row (PaddleOCR 한글) |

- **(1)** N fps(기본 5) 샘플 → 인접 프레임 절대평균차 `diff<thresh` 가 `≥min_still_sec`
  연속 유지되는 구간 = 정지. 구간 가운데 1장 저장, 인접 중복 정지구간 dedup.
- **(2)** 보드 지시: 가격표가 upper-center 라고 **확신하지 않는다**. 하드 ROI 로 자르지 않고
  프레임 전역에서 '밝은 가격표 사각형'을 면적·형상으로 찾고, 위치 prior 는 동점만 가르는
  약한 가중치(≤35%). 못 찾으면 넉넉한 밴드로 폴백. 채널 템플릿: `whiskeypick`(종이
  가격표·흰사각형 refine), `whiskeykey`(합성 오버레이·refine off·우측 밴드).
- **(3)** OCR 엔진 = **PaddleOCR `lang=korean`** (det/rec 모두 **mobile** 모델 — CPU 전용
  환경에서 server det 은 분 단위로 느려 부적합; 가격표의 큰 글자엔 mobile 로 충분).
  제품명 = 한글 포함 최상단 라인, 가격 = 가장 큰 폰트(박스 높이)의 정상가 숫자,
  **용량(`volume_ml`) = 700/750/1000/1750ml 등**(제품명 라인 우선, 없으면 가격표 내 용량
  토큰). OCR 이 끝의 `l` 을 자주 떨어뜨려(`750ml`→`750m`) **`<숫자>m` 은 그 값이 표준 소매
  용량일 때만 ml 로 인정**(오인 방어). 회사 공통 게이트 `is_bundle_noise`(잔세트)·
  `is_sane_price`(15,000원 하한) 재사용.

## E2E 데모 (트레이더스 영상 1개)

```bash
bash run_demo.sh k3GQq_-rD1k whiskeypick   # @whiskeypick 06-08 트레이더스 구월점 (462s)
```

다운로드(yt-dlp, 360p progressive·ffmpeg 불필요) → 정지프레임 **103장** → crop **103장**
(흰사각형 refine 94 / 폴백 9) → OCR **제품 23종**(용량 채워진 위스키행 15/23). 산출
evidence: `_demo/k3GQq_-rD1k/` (`result.csv`, `frames/manifest.csv`, `crops/manifest.csv`,
`sample_crops/` 3장).

추출 샘플(정상, `가격 | 용량`): 글렌피딕15년 99,800/700ml · 포로지스 싱글배럴 82,800/750ml ·
메이커스마크 49,980/1000ml · 조니워커블랙 54,800/700ml · 글렌리벳15년 94,800/700ml ·
발모어12년 99,800/700ml.
OCR 오자(예: 글렌피딕→'글랜피티', 발모어→'날모어')와 매대 안내문 잡힘(해산물·과일채소·
19세경고)은 **후속 어댑터의 위스키 정규화(whisky-data-normalization) 단계에서 매칭 실패로
탈락**한다 — 본 태스크 스코프(함수/스크립트 + 1영상 E2E 실증) 밖.

## production화 — 품질게이트 적재 + 자동수집 루틴 (CMPA-424)

frame_ocr 산출(`result.csv`)을 **품질게이트→정본 매핑→월별 CSV→정규화 floor** 로 흘린다.

| 스크립트 | 역할 |
|---|---|
| `ingest_ocr.py` | `result.csv` → 품질게이트 → `{YM}_youtube_ocr.csv`(통과분) + `{YM}_youtube_ocr_quarantine.csv`(격리분). 멱등(`.state/ocr_processed.json`). |
| `run_ocr_collection.py` | @whiskeypick·@whiskeykey 신규 영상 discover → frame_ocr → ingest 오케스트레이터. 동시성 1·pace·`--max`. |

**품질게이트(통과해야 floor 반영, `ingest_ocr.gate_rows`)**
1. **노이즈 blocklist**(`noise_reason`) — 19세 경고·매대 카테고리(해산물/과일/채소…)·숫자뭉치 격리.
2. **가격 상식**(`is_sane_price` 15,000원↑) + **번들**(`is_bundle_noise` 잔세트) 격리.
3. **브랜드-앵커 퍼지매처**(`SkuMatcher`) — `master-sku.csv` 로 OCR 오자 보정.
   - 브랜드부를 정본 브랜드 그룹과 fuzzy(difflib≥0.62) 매칭 → 후보 SKU.
   - **숙성년수(N년) 비대칭이면 다른 제품**(CMPA-177) → 거절. 잔여(서브라벨)로 disambiguate.
   - 단편/모호/미매칭은 **격리**. 보수적: 오매칭(가짜 딜) 0 이 1순위, 격리(미수집) 허용.
   - 통과분 `술이름`=정본 `name_ko`(+용량) 라 정규화기가 동일 id 로 재매칭, `비고`에 `id=`·raw 보존.

데모(트레이더스 k3GQq 23행) 게이트 결과: **적재 8 / 격리 15**(노이즈 4·브랜드저신뢰 7·년수비대칭 2·단편 1).
적재 8종(글렌피딕15년 99,800·포로지스 싱글배럴 82,800·이글레어10년 69,800·메이커스마크 49,980·
조니워커블랙루비 54,800·커티삭프로히비션 39,980·달모어12년 99,800·달모어2005빈티지 678,000) 전부
정본 id 보정 적재 → `normalize_dataset` clean floor 후보 8건 반영(예: 메이커스마크 06-08 트레이더스
49,980 이 기존 트레이더스가 교차검증·롯데마트 55,900 보다 저렴해 floor 합류).

```bash
# 적재(품질게이트). 위치=제목 판별, 날짜=업로드일/제목 폴백
python3 ingest_ocr.py --result _demo/k3GQq_-rD1k/result.csv --video k3GQq_-rD1k \
  --channel-label @whiskeypick --title "트레이더스 ... (2026.06.08 구월점)" --upload-date 20260608
# 자동수집(신규 1영상, 멱등·pace 12h)
python3 run_ocr_collection.py                 # 신규 1영상 처리
python3 run_ocr_collection.py --discover-only  # 신규 후보만(다운로드 X)
```

**정규화 통합**: `scripts/normalize_dataset.py` SOURCES 에 `{m}_youtube_ocr.csv`(source_family
`youtube_ocr`, `adapt_domestic`) 등록 — 통과분만 KR 국내 후보로 floor 에 합류. 격리분은 미등록.

**가드**: `scripts/test_youtube_ocr_gate.py`(데모 23행 회귀 — 노이즈 격리·오자 정본보정·**오매칭 0**
고정). 게이트/매처 변경 시 반드시 통과시킬 것.

**자동화 루틴**: `run_ocr_collection.py` 를 일 1~2회 cron 으로. discover 는 가벼운 flat-playlist,
처리는 오래된 미처리 영상부터 1편(동시성 1·`--max`). 이미 처리한 video_id 는 skip(멱등).
muxed 영상 다운로드라 ASR timedtext 429 와 무관하나 과도 다운로드는 자제(pace 12h 가드).
