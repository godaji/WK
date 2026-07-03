#!/usr/bin/env bash
set -uo pipefail
HERE="/mnt/c/Users/shhon/Desktop/WK/pipelines/youtube_traders/frame_ocr"
VID="mBH4Xqtr1YU"; DEMO="$HERE/_demo/$VID"
echo "[resume] OCR on existing crops ($(ls $DEMO/crops/|grep -c jpg))"
python3 "$HERE/extract_price_ocr.py" "$DEMO/crops" --out "$DEMO/result.csv"
[ -s "$DEMO/result.csv" ] || { echo "[resume] result.csv 비어있음 — 중단"; exit 3; }
ROWS=$(($(wc -l < "$DEMO/result.csv")-1)); echo "[resume] result rows: $ROWS"
[ "$ROWS" -le 0 ] && { echo "[resume] 0행 — 중단(상태보존)"; exit 4; }
TITLE="$(yt-dlp --no-warnings --print '%(title)s' "https://www.youtube.com/watch?v=$VID" 2>/dev/null | head -1)"
DESC="$(yt-dlp --no-warnings --print '%(description)s' "https://www.youtube.com/watch?v=$VID" 2>/dev/null)"
python3 "$HERE/ingest_ocr.py" --result "$DEMO/result.csv" --video "$VID" \
  --channel-label "@whiskeykey" --title "$TITLE" \
  --upload-date "2026-04-07" --description "$DESC" --force
echo "[resume] === done mBH4Xqtr1YU ==="
