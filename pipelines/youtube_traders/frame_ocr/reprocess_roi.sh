#!/usr/bin/env bash
# reprocess_roi.sh — CMPA-489: @whiskeykey 과거 walking-tour 영상 ROI 재처리 백필.
# whole-frame 방식으로 과소수집된 영상을 ROI(우상단 가격표) 추출로 재처리해 풀 인벤토리 적재.
#
# 용법: bash reprocess_roi.sh VIDEO_ID FILMING_DATE(YYYY-MM-DD)
#   - run_demo.sh(=ROI 자동) 으로 프레임→crop→OCR
#   - ingest_ocr --force --description(촬영 장소→지점) --upload-date(촬영일=관측일)
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
VID="${1:?video_id 필요}"
FILMDATE="${2:?촬영일 YYYY-MM-DD 필요}"
DEMO="$HERE/_demo/$VID"

echo "[roi] === $VID (filming $FILMDATE) ==="
# 1) 이전 whole-frame 산출 제거(stale frames 가 crop 에 섞이지 않게)
rm -rf "$DEMO/frames" "$DEMO/crops" "$DEMO/result.csv"

# 2) 제목/설명 조회(설명의 '촬영 장소'에서 지점 추출)
META="$(yt-dlp --no-warnings --print "%(title)s" "https://www.youtube.com/watch?v=$VID" 2>/dev/null | head -1)"
DESC="$(yt-dlp --no-warnings --print "%(description)s" "https://www.youtube.com/watch?v=$VID" 2>/dev/null)"
echo "[roi] title: $META"
echo "[roi] desc 촬영장소: $(echo "$DESC" | grep -m1 '촬영 장소' || echo '(없음)')"

# 3) ROI 데모(다운로드→정지프레임→crop→OCR)
if ! bash "$HERE/run_demo.sh" "$VID" whiskeykey; then
  echo "[roi] run_demo 실패(다운로드/추출) — ingest 건너뜀(상태 보존)"; exit 2
fi
if [ ! -s "$DEMO/result.csv" ]; then
  echo "[roi] result.csv 없음/빈파일 — ingest 건너뜀(상태 보존)"; exit 3
fi
ROWS=$(($(wc -l < "$DEMO/result.csv")-1))
echo "[roi] OCR result rows: $ROWS"
if [ "$ROWS" -le 0 ]; then
  echo "[roi] OCR 0행 — ingest 건너뜀(상태 보존)"; exit 4
fi

# 4) 적재(force 재처리, 지점=설명 폴백, 관측일=촬영일)
python3 "$HERE/ingest_ocr.py" \
  --result "$DEMO/result.csv" --video "$VID" \
  --channel-label "@whiskeykey" --title "$META" \
  --upload-date "$FILMDATE" --description "$DESC" --force

echo "[roi] === done $VID ==="
