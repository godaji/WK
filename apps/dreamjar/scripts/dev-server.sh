#!/usr/bin/env bash
# DreamJar 로컬 개발 서버
# 사용법: ./scripts/dev-server.sh [포트] [--open]
#
# 예시:
#   ./scripts/dev-server.sh          # 8080 포트로 서빙
#   ./scripts/dev-server.sh 3000     # 3000 포트로 서빙
#   ./scripts/dev-server.sh --open   # 8080 포트 + 브라우저 자동 오픈

set -euo pipefail

PORT=8080
OPEN_BROWSER=false

for arg in "$@"; do
  case "$arg" in
    --open) OPEN_BROWSER=true ;;
    [0-9]*) PORT="$arg" ;;
  esac
done

DIR="$(cd "$(dirname "$0")/.." && pwd)"

# 로컬 IP (모바일 테스트용)
LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || echo "127.0.0.1")

echo "=== DreamJar 로컬 개발 서버 ==="
echo ""
echo "  로컬:   http://localhost:${PORT}"
echo "  네트워크: http://${LOCAL_IP}:${PORT}  (모바일 테스트용)"
echo ""
echo "  종료: Ctrl+C"
echo ""

if [ "$OPEN_BROWSER" = true ]; then
  # Linux / macOS 브라우저 오픈
  if command -v xdg-open &>/dev/null; then
    xdg-open "http://localhost:${PORT}" &
  elif command -v open &>/dev/null; then
    open "http://localhost:${PORT}" &
  fi
fi

cd "$DIR"
python3 -m http.server "$PORT" --bind 0.0.0.0
