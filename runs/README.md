# `runs/` — 런 단위(run-centric) 산출물 아카이브 (CMPA-151)

이 폴더는 **위스키 가격 통합 실행 한 번**이 만든 모든 산출물 사본을 날짜별로 모은다.
정본(`data/`·`reports/`·`deploy/`)은 항상 **latest 포인터**로 그대로 두고, 여기에는
**추가로** 사본을 누적한다(복사이지 이동이 아님 → 다운스트림 latest 경로 불변).

```
runs/<run_date>/
  marts/       data/whisky-prices/<월>.csv (국내 마트 + 코스트코)
  dailyshot/   <월>_dailyshot.csv
  overseas/    <월>_hk_whisky_poc.csv, <월>_jp_shopify_poc.csv, fx_snapshot.csv, fx_latest.json
  normalized/  normalized_prices.csv, normalized_all_rows.csv, master-sku.csv, whisky-aliases.csv
  reports/     <월>_위스키가격리포트_<run_date>.md, CMPA-31_정규화검증리포트.md
  deploy/      배포 스테이징 트리 통째(cross-asset, build_deploy.py 가 채움)
  _manifest.json  이 런이 무엇을 모았는지 요약(asset→파일목록, copied, missing)
```

## 누가 채우나
- `scripts/run_whisky_price_pipeline.py` (통합 실행) — stage 5 가 자산 폴더들을 채운다.
  내부적으로 `pipelines/common/run_archive.py` 의 `collect_run_outputs()` 호출.
- `scripts/build_deploy.py` (분리된 배포 게이트) — `runs/<run_date>/deploy/` 를 채운다.

## 날짜는 단일 출처
`<run_date>` = `pipelines/common/run_dates.run_date()` (우선순위 `COLLECT_DATE` >
`RUN_DATE` > `FX_ASOF` > 오늘[로컬]). 통합 실행이 한 run_date 를 모든 스테이지에 넘겨
스테이지 간 날짜 표류를 막는다. 같은 run_date 재실행은 그 날 폴더를 **갱신**(날짜 단위 멱등).

## 두 누적 뷰
- **세로(자산별 시간축)**: 각 정본 옆 `_runs/<stem>__run<date>.<ext>` (`pipelines/common/dated.py`).
- **가로(런별 묶음)**: 이 `runs/<run_date>/` 폴더 — "이 한 번의 실행이 뭘 만들었나".

데이터 관리 3원칙(CMPA-156: 스냅샷 아닌 '수집 날짜 찍힌 누적 기록')과 같은 철학이다.
