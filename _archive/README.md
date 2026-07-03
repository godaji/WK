# _archive — 루틴 미사용 파일 보관함 (CMPA-46)

작성: DataEngineer · 2026-05-30 · 이슈 CMPA-46 "archive unused files"

> 요청: "루틴에서 활용하지 않는 파일들을 리스트업 후 `_archive` 폴더로 **이동**(삭제 금지). 리뷰 예정."
> (이슈 본문의 `\_arvhive` 는 오타로 보고 `_archive` 로 생성)

여기 있는 파일은 **삭제하지 않았고**, 원래 경로 구조를 그대로 미러링해 옮겼습니다.
되돌리려면 같은 상대경로로 다시 `mv` 하면 됩니다. 예:
`mv _archive/assets/build_whisky_list.py assets/build_whisky_list.py`

## 판정 방법
회사의 **활성 루틴 8종**의 진입 스크립트와, 그 스크립트가 (정적 import + 동적
`subprocess`/importlib 호출로) 실제로 읽고/실행하는 파일을 추적해 "사용 집합"을 만든 뒤,
거기에 들지 않고 전수 grep 으로 다른 코드/리포트에서도 참조되지 않는 파일만 골랐습니다.

루틴 파이프라인: 수집(유튜브 트레이더스·코스트코웹·데일리샷·해외[FX+HK+JP]) →
정규화(`scripts/normalize_dataset.py`) → 리포트생성(`scripts/generate_report.py` +
`reports/md_to_html.py`) → 배포(`reports/make_distribution.py`).

## 옮긴 파일 목록 (9)

| 원래 경로 | 사유 |
|---|---|
| `pipelines/tw_whisky/crawl_tw_whisky.py` | 대만(TW) 수집기. 어떤 루틴도 호출 안 함(해외 루틴은 FX+HK+JP만). |
| `pipelines/tw_whisky/README.md` | 위 수집기 문서. |
| `pipelines/youtube_traders/sample_output_nYUtBO0v7vI.csv` | 개발용 샘플 출력. 코드 참조 없음. |
| `assets/build_whisky_list.py` | `whisky-list.csv` **일회성 빌더**. 루틴 미사용. ⚠ 아래 주의 참고. |
| `reports/2026-05_위스키가격리포트_초안.md` | 수동 초안. 정식 출력(`_위스키가격리포트.md`/`_배포본`)으로 대체됨. |
| `reports/260530_위스키가격리포트.html` | 구 YYMMDD 파일명 리포트. 현 명명규칙(CMPA-38/45) 이전 산출물. |
| `reports/CMPA-15_2표_최저가표.md` | CMPA-15 일회성 표. 루틴 산출물 아님. |
| `data/whisky-prices/ssand3_videos_2026.csv` | 구 영상 발견 덤프. 수집기는 `.state/discover_ssand3.csv` 사용. |
| `data/whisky-prices/tw/_poc_metrics.json` | TW POC 메트릭. TW가 루틴에서 빠지며 미사용. |

## 보관(이동 안 함)한 헷갈리는 파일 — 실제로는 사용 중
- `pipelines/hk-whisky/`, `pipelines/jp_rakuten/` → 해외 루틴 `collect_overseas.py`가
  `subprocess`로 **동적 실행**(라인 102~113). 사용 중이라 그대로 둠.
- `data/whisky-prices/2026-05_tw_whisky_poc.csv` → 수집기는 archive 했지만 이 CSV는
  `normalize_dataset.py`가 입력으로 **여전히 읽음**(SOURCES 라인 149). 그래서 데이터는 유지.
  (TW 수집기를 영구 폐기하더라도 이 CSV는 동결 POC 입력으로 남음.)
- `data/whisky-prices/jp/_poc_metrics.json` → `rakuten_poc.py`(해외 루틴 JP단계)가 기록.

## ⚠ 리뷰 시 주의
- `assets/build_whisky_list.py` 는 핵심 자산 `whisky-list.csv` 의 유일한 빌더입니다.
  루틴은 안 쓰지만, 마스터 목록을 재생성할 유일한 스크립트이므로 폐기 전 보관 권장.
- `__pycache__`/`.pyc` 빌드 산출물은 건드리지 않았습니다(자동 재생성).
  `pipelines/tw_whisky/` 의 stale `.pyc` 는 그대로 남아 있어도 무해합니다.

---

## CMPA-206 — 할랄·펫 프로젝트 제외 (DataEngineer2 · 2026-06-07)

> 보드 지시(CMPA-205 코멘트 2026-06-07): **할랄(halal-restaurants)·펫(pet-friendly)을
> 앞으로 프로젝트에서 제외.** 하드 삭제 아님 — 아카이브 우선(되돌림 가능), git 이력 보존.
> 콜키지(corkage-free)는 별개 자산이라 **건드리지 않음**.

`git mv` 로 원래 경로 구조를 미러링해 옮겼습니다. 되돌리려면 같은 상대경로로 `git mv` 역방향.

| 원래 경로 | → 아카이브 경로 | 무엇·왜·언제 |
|---|---|---|
| `pipelines/halal_restaurants/` | `_archive/pipelines/halal_restaurants/` | 할랄 식당 파이프라인. 프로젝트 제외(CMPA-206, 2026-06-07). |
| `pipelines/pet_friendly/` | `_archive/pipelines/pet_friendly/` | 반려동물 동반 파이프라인. 프로젝트 제외(CMPA-206, 2026-06-07). |
| `data/halal-restaurants/` | `_archive/data/halal-restaurants/` | 할랄 식당 데이터. 프로젝트 제외(CMPA-206, 2026-06-07). |
| `data/pet-friendly/` | `_archive/data/pet-friendly/` | 반려동물 동반 데이터. 프로젝트 제외(CMPA-206, 2026-06-07). |
| `reports/halal-restaurants/` | `_archive/reports/halal-restaurants/` | 할랄 식당 리포트 HTML. 프로젝트 제외(CMPA-206, 2026-06-07). |
| `reports/pet-friendly/` | `_archive/reports/pet-friendly/` | 반려동물 동반 리포트 HTML. 프로젝트 제외(CMPA-206, 2026-06-07). |

**빌드 제거:** `scripts/build_deploy.py` 의 `CATEGORY_TITLES` 에서 `halal-restaurants`·
`pet-friendly` 항목 삭제(구 라인 90-91) + 리빙맵 주석의 `halal/pet` 표현 정리. 카테고리
산출은 `collect()` 가 `reports/` 폴더를 스캔해 결정하므로, `reports/halal*`·`reports/pet*`
아카이브로 `deploy/halal-restaurants/`·`deploy/pet-friendly/` 는 더 이상 생성되지 않고
다음 재빌드의 rmtree 로 기존 `deploy/` 폴더도 정리됩니다.

**루틴:** 할랄·펫 전용 루틴은 **없음**(활성 루틴은 유튜브트레이더스·위스키가격·콜키지·신라
면세 등) → disable 대상 없음(스킵).

**참고:** `pipelines/corkage_free/find_corkage_free.py:662` 의 주석
`# CMPA-109: ... halal·pet과 동일 패턴` 은 **콜키지 코드 내부 주석**이라 가드(콜키지 불가침)에
따라 그대로 둡니다(빌드 경로 아님).
