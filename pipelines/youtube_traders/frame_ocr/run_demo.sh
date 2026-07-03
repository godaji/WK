#!/usr/bin/env bash
# run_demo.sh — CMPA-423 E2E 데모: 유튜브 가격영상 1개 → 정지프레임 → crop → OCR(제품명·가격)
#
# ffmpeg 없음 → yt-dlp 는 progressive(muxed) mp4 단일 포맷만 받는다(merge 금지).
# 영상은 임시폴더(처리 후 삭제), 산출(프레임/crop/CSV)만 _demo/ 에 보존.
#
# 용법: bash run_demo.sh VIDEO_ID TEMPLATE   (예: bash run_demo.sh k3GQq_-rD1k whiskeypick)
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VID="${1:?video_id 필요}"
TPL="${2:-whiskeypick}"
DEMO="$HERE/_demo/$VID"
FRAMES="$DEMO/frames"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$FRAMES"

echo "[demo] 1) 저해상 mp4 다운로드(yt-dlp, ≤480p progressive, ffmpeg 불필요)"
# 18=360p muxed, 그 외 480p 이하 muxed 폴백. merge 가 필요한 포맷은 피한다.
yt-dlp -f "18/best[height<=480][vcodec!=none][acodec!=none]/best[height<=480]" \
  --no-playlist -o "$TMP/$VID.%(ext)s" "https://www.youtube.com/watch?v=$VID" 2>&1 | tail -3
MP4="$(ls "$TMP/$VID".* 2>/dev/null | head -1)"
[ -z "$MP4" ] && { echo "[demo] 다운로드 실패"; exit 2; }
echo "[demo]   받음: $MP4 ($(du -h "$MP4" | cut -f1))"

echo "[demo] 2) 정지프레임 추출"
# 채널별 수집 방식:
#   @whiskeypick = 진행자가 종이 가격표를 들고 정지 → 전역 stillness(--mode still, 기본)
#   @whiskeykey  = 슬라이드형 오버레이 — 우측 상단 흰 패널 텍스트 변화 감지(--mode change)
#                  ROI 안에서 diff 가 change_thresh 이상 뛰면 전환, 0.5s 후 안정 프레임 저장.
if [ "$TPL" = "whiskeykey" ]; then
  python3 "$HERE/extract_still_frames.py" "$MP4" "--video-id=$VID" --out-dir "$FRAMES" \
    --mode change --roi "0.55,0.0,1.0,0.42" --change-thresh 4.0 --settle-sec 0.5
else
  python3 "$HERE/extract_still_frames.py" "$MP4" "--video-id=$VID" --out-dir "$FRAMES"
fi

echo "[demo] 3) 가격표 crop (template=$TPL)"
python3 "$HERE/crop_price_tag.py" "$FRAMES" --template "$TPL" --out-dir "$DEMO/crops"

echo "[demo] 4) OCR 추출(제품명·가격)"
python3 "$HERE/extract_price_ocr.py" "$DEMO/crops" --out "$DEMO/result.csv"

echo "[demo] 완료. 산출: $DEMO (frames/, crops/, result.csv)"
