# xcheck — 자막↔OCR 교차검증 (CMPA-229, 보드 추가지시)

> **결론: 0:24 `1792 스몰 배치 39,980원` 이 자막·OCR 양쪽에서 일치 확정(CONFIRMED).**
> ASR 미사용 원칙 유지 — 자막은 "값"이 아니라 "시점(타임코드)" 확보용으로만 쓰고,
> 가격 "값"은 화면 오버레이 OCR 로 읽어 교차검증한다.

내부 R&D 측정용. 원본 영상(`vid.mp4`, 51MB)은 측정 후 삭제(미커밋, ToS/용량). 증거 프레임만 보존.

## 흐름 (보드가 지정한 순서)
1. **자막 추출** → 가격 언급 **타임코드** 확보
   - `1792 스몰 배치 39,980원` = caption `tStartMs=24,600ms` (0:24.60)
2. **OCR 교차** → 그 타임코드 프레임의 화면값 읽기
   - frames/t24.6~28.5.jpg (오버레이 지속 구간) → 최종가 39,980 (5/5 프레임, 최대폰트)
3. **비교·결정** → 일치 시 확정 / 불일치 시 **화면 OCR 우선 + needs_human 플래그**

## 재현
```bash
ID=dMF5i15ucJQ
# 1) 자막(json3, 정밀 타임코드) — 자동자막만 존재(수동 캡션 없음 = caption==ASR)
yt-dlp --skip-download --write-auto-subs --sub-langs ko --sub-format json3 -o cap "https://www.youtube.com/watch?v=$ID"
# 2) 영상 720p + 타임코드 프레임 추출 (ffmpeg 없으면 imageio_ffmpeg 번들)
yt-dlp -f 136 -o vid.mp4 "https://www.youtube.com/watch?v=$ID"
FF=$(python3 -c "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())")
for t in 24.6 25.5 26.5 27.5 28.5; do "$FF" -ss $t -i vid.mp4 -frames:v 1 -q:v 2 frames/t$t.jpg -y; done
# 3) 교차검증
python3 caption_ocr_xcheck.py cap.ko.json3 frames 24.6
```

## 결과 (하드 넘버)
| 소스 | 값 | 증거 |
|---|---|---|
| 자막(caption) | `1792 스몰 배치 39,980원` @ 0:24.60 | `cap.ko.json3` / `cap.ko.vtt` |
| OCR (화면 오버레이) | 39,980 (최대폰트, h≈69px), 정상가 44,980·할인 -5,000·100ml당 5,997 동시 추출 | `frames/t26.5.jpg` |
| 다수결 | 39,980 (5/5 프레임 동일) | 위 |
| **MATCH** | **True → CONFIRMED, adopt 39,980** | |

## 채택 규칙 (불일치 시)
- 일치 → **confirmed**, 그대로 적재.
- 불일치 → **화면 OCR 우선**(합성 오버레이가 가장 신뢰도 높음) + `needs_human=True` 로 사람확인 큐.
  (근거: 자막=ASR이라 자릿수 누락/오인 가능 / 오버레이 숫자는 1.00 신뢰도 또렷)

## 핵심 발견
- 이 채널은 **자동자막만** 존재(수동 캡션 트랙 없음) → "진짜 자막 대신 ASR" 구도가 성립 안 함.
  자막의 진짜 가치는 **값이 아니라 타임코드**다 → 타임코드로 프레임을 정확히 떠 OCR 로 값 확정.
- 이번 누락의 근본원인은 소스가 아니라 **파서 버그**(인트로 할인문구 `5,000원`이
  '첫 위스키 인트로 제거' 일회성 플래그를 소진 → 1792·잭다니엘 통째 드롭). 별도 수정 완료(2026-06.csv 95행).
