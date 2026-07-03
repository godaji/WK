# youtube_traders — 트레이더스 현장가 수집 루틴 (CMPA-27)

> **⚠️ 라이브 소스 = `@whiskeypick` + `@whiskeykey` 2개입니다. (싼디/@SSanD3 아님)**
> 이 루틴이 실제로 적재하는 유튜브 가격 소스는 **`@whiskeypick`(위스키픽)** 과
> **`@whiskeykey`(위스키키)** 두 채널입니다. 과거 **싼디(@SSanD3)** 도 시도했으나
> ASR 부적합(가격 0행)으로 **건너뜁니다**. 따라서 "싼디에서 가격을 수집한다"는
> 설명은 **틀린 표현**입니다. (CMPA-154 → **CMPA-160 보드 승인 2026-06-07** 로 2채널 확정)
>
> ⚠️ `@whiskeypick`(위스키픽)과 `@whiskeykey`(위스키키)는 **핸들이 비슷하나 다른 채널**입니다.
> ⚠️ **위치는 항상 `트레이더스`** 로만 적습니다(지점명 미표기). 트레이더스는 전국 매장가가
> 동일하므로 `트레이더스 동탄점`처럼 지점을 붙이지 않습니다 (CMPA-160 보드 확정).

이마트 트레이더스 현장 위스키 가격을 유튜브 위스키 채널 **`@whiskeypick`·`@whiskeykey`**(라이브
1차 소스)의 **ko ASR 자막**에서 주기적으로 수집해 월간 CSV(`data/whisky-prices/YYYY-MM.csv`)에
적재한다. `@SSanD3`(싼디)는 코드에 등록만 돼 있고 실제 수집에서는 제외된다(아래 적합성 표 참조).

## 채널별 ASR 적합성 (실측, CMPA-40 2026-05-30 / CMPA-160 2026-06-07)
- **@whiskeypick(위스키픽) — ASR 적합 ✅**: 매주(마트 변동일) 트레이더스 현장가를 진행자가
  또렷이 읽어 줌. ko ASR 로 가격 100+행/영상 추출. 2026-03~05 1차 소스.
- **@whiskeykey(위스키키) — ASR 적합 ✅ (CMPA-160 신규 검증)**: 트레이더스 전 위스키 현장가를
  또렷이 읽어 주며 **거의 주간**으로 날짜 명기 영상 업로드(`discover` 8건, June 1~Apr 13).
  POC 실측 2026-06-01 영상(`dMF5i15ucJQ`): ko ASR → **79행**, 날짜 자동검출 2026-06-01,
  정규화 31/79. **@whiskeypick 이 6월 0행이던 공백을 메움** → `2026-06.csv` 16→94행.
  ⚠️ @whiskeypick(위스키픽)과 핸들이 비슷하나 **다른 채널**이다(혼동 주의).
- **@SSanD3(싼디) — ASR 부적합 ⚠️**: 트레이더스 영상이 와인/명절 위주이고, 위스키 영상
  (`qZelFlIrmQ4`, 2026-04-14)도 ko 자동자막이 **BGM 가사**만 받아써 가격 0행. 진행자가 가격을
  말로 읽지 않음. → 주간 루틴에서 ssand3 fetch 는 **건너뜀**(429 예산 낭비). 포맷이 바뀌면 재평가.

## 왜 ASR 자막인가
- 현장 가격표 OCR 파이프라인은 CMPA-5에서 **NO-GO**(이름 garbled·full-row 55%·재배포 리스크).
- 대신 채널 운영자가 영상에서 또렷이 읽어 주는 가격을 **ko 자동자막(ASR)** 으로 받아쓴다.
  - 가격: `99,800원` 형태로 또렷 → 신뢰도 높음.
  - 이름: 음차/오인 잦음(`발베니`→`발레니` 등) → **마스터 SKU 사전 매칭**으로 보정(아래).

## 파이프라인 (서브커맨드)
`collect_traders_prices.py`

| 단계 | 명령 | 네트워크 | 설명 |
|---|---|---|---|
| discover | `discover --channel whiskeypick` | yt-dlp | 채널 영상 목록에서 제목에 `트레이더스` 포함 영상 필터 → 인덱스 |
| fetch | `fetch --video <ID>` | yt-dlp | ko ASR 자막(json3) 다운로드. **≥60분 페이싱 가드** |
| parse | `parse --sub <json3> --video <ID>` | 없음 | 자막 → 행. 위치·촬영일자 자동 추출, 타임스탬프 앵커, 정규화 주석 |
| load | `load --sub <json3> --video <ID>` | 없음 | parse → 월간 CSV에 **dedup append** (7컬럼 스키마) |

스키마: `술이름, 가격_KRW, 위치, 가져온날짜, 출처, 신뢰도, 비고`

## 429 페이싱 (중요)
ko ASR 자막은 per-IP **429가 심하다**(메모리 `ytdlp-timedtext-429-pacing`: ~8–9영상 후 차단).
`fetch` 는 `.state/last_fetch.json` 에 마지막 호출 시각을 기록하고 **60분 이내 재호출을 거부**한다
(`--force` 로 무시). 주간 루틴은 1회 1영상이라 페이싱과 충돌하지 않는다.

> **2채널 운영 시(CMPA-160):** 이제 active 채널이 @whiskeypick·@whiskeykey 2개다.
> 한 번의 루틴 실행에서 두 채널 영상을 fetch 하면 ≥60분 페이싱 가드에 걸린다.
> → **채널당 별도 요일/실행으로 분리**하거나 페이싱 만료 후 순차 fetch 한다(429 회피).
> @whiskeykey 가 거의 주간 업로드이므로, @whiskeykey 를 1차로 두고 @whiskeypick 를
> 백업/교차검증으로 운용하는 것을 권장(아래 CMPA-160 권장안).

## 정규화 연계 (CMPA-22)
`parse`/`load` 는 `scripts/normalize_whisky_name.py` 의 `Normalizer.canonicalize()` 로
raw 이름을 정본 `whisky-list.csv` id 로 매칭해 **비고에 `id=...` 주석**을 단다.
매칭 실패해도 raw 이름은 보존(후속 정규화·검증 루틴 CMPA-31의 입력).

## 신뢰도 규칙
- `중` (기본): ASR 단건 가격.
- `낮음`: 가격 < 19,000원 → ASR 자릿수 누락 의심(`비고: ASR 자릿수 누락/오인 추정-재확인`).
- 후속 검증 루틴에서 마스터 가격대와 교차 검증 권장.

## 거버넌스
- 월간 CSV **내부 R&D 적재는 OK**.
- **공개 재배포는 CMPA-7 게이트** — 배포 루틴(CMPA-33)에서 별도 체크. 본 수집 루틴은 적재까지만.

## 재현 실행 (예)
```bash
# 자막 1회 다운로드(페이싱 가드)
python3 pipelines/youtube_traders/collect_traders_prices.py fetch --video nYUtBO0v7vI

# 파싱(네트워크 없이 재현 가능) — 76행, 위치/촬영일 자동, 정규화 48/76 매칭
python3 pipelines/youtube_traders/collect_traders_prices.py parse \
    --sub pipelines/youtube_traders/.state/subs/nYUtBO0v7vI.ko.json3 --video nYUtBO0v7vI

# 월간 적재(중복 자동 skip)
python3 pipelines/youtube_traders/collect_traders_prices.py load \
    --sub <json3> --video nYUtBO0v7vI --month 2026-05
```

`sample_output_nYUtBO0v7vI.csv` — 위 parse 의 실제 산출(76행) 동봉.

## 주간 루틴
매주 월요일(마트 가격 변동일) Paperclip 루틴이 깨어나 discover→fetch→load 를 실행.
상세는 CMPA-27 참조.
