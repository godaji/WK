#!/usr/bin/env bash
set -uo pipefail
HERE="/mnt/c/Users/shhon/Desktop/WK/pipelines/youtube_traders/frame_ocr"
VID="dMF5i15ucJQ"; DEMO="$HERE/_demo/$VID"
echo "[resume] OCR on existing crops"
python3 "$HERE/extract_price_ocr.py" "$DEMO/crops" --out "$DEMO/result.csv"
ROWS=$(($(wc -l < "$DEMO/result.csv")-1)); echo "[resume] result rows: $ROWS"
TITLE="$(yt-dlp --no-warnings --print '%(title)s' "https://www.youtube.com/watch?v=$VID" 2>/dev/null | head -1)"
DESC="$(yt-dlp --no-warnings --print '%(description)s' "https://www.youtube.com/watch?v=$VID" 2>/dev/null)"
python3 "$HERE/ingest_ocr.py" --result "$DEMO/result.csv" --video "$VID" \
  --channel-label "@whiskeykey" --title "$TITLE" \
  --upload-date "2026-06-01" --description "$DESC" --force
echo "[resume] === done dMF5i15ucJQ ==="
