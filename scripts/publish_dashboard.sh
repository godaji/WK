#!/usr/bin/env bash
# 위스키 가격 대시보드 빌드 + 라이브 배포 (CMPA-505)
#
# 배포 경로: /CaskCode/dashboard/ (godaji.github.io/CaskCode/dashboard/)
# noindex 유지 — 검색 노출은 보드 별도 결정.
#
# 동작:
#   1) build_dashboard.py 로 deploy/dashboard/index.html 생성
#   2) caskcode-publish/dashboard/ 에 미러 (surgical push)
#   3) 변경 있으면 commit + push (라이브).
#   --dry-run 이면 push 없이 미리보기.

set -euo pipefail

WK="${WK_ROOT:-/mnt/c/Users/shhon/Desktop/WK}"
PUB="${CASKCODE_PUBLISH:-/mnt/c/Users/shhon/Desktop/caskcode-publish}"
SRC="$WK/deploy/dashboard"
DEST="$PUB/dashboard"
DEPLOY_KEY="${CASKCODE_DEPLOY_KEY:-$HOME/.ssh/caskcode_deploy_key}"
DRY=0
SKIP_BUILD=0
for a in "$@"; do
  case "$a" in
    --dry-run)    DRY=1;;
    --skip-build) SKIP_BUILD=1;;
  esac
done

[ -d "$WK" ]         || { echo "ERR: WK=$WK 없음"; exit 1; }
[ -d "$PUB/.git" ]   || { echo "ERR: publish repo $PUB 없음"; exit 1; }

# 1) 대시보드 빌드 (평면 + 브랜드 가치 추천 deep-dive)
if [ "$SKIP_BUILD" -eq 0 ]; then
  echo "[1/3] 대시보드 빌드..."
  cd "$WK"
  python3 -m pipelines.dashboard.build_dashboard
  python3 -m pipelines.dashboard.build_brand_value   # CMPA-521: /dashboard/brands/
else
  echo "[1/3] 빌드 스킵 (--skip-build)"
fi

# 2) caskcode-publish/dashboard/ 에 미러
echo "[2/3] caskcode-publish/dashboard/ 미러..."
# 발행 클론 자가치유 (CMPA-674): 순수 배포 미러이므로 origin/main 으로 정렬한 뒤 그 위에 미러.
# 클론이 remote 보다 뒤처져 push 'fetch first' 거부되는 상습 트랩 방지.
( cd "$PUB" \
  && GIT_SSH_COMMAND="ssh -i $DEPLOY_KEY -o StrictHostKeyChecking=no" git fetch origin main \
  && git reset --hard origin/main )
mkdir -p "$DEST"
cp "$SRC/index.html" "$DEST/index.html"

# 브랜드 가치 추천 deep-dive 서브페이지 (/dashboard/brands/) — CMPA-521
if [ -f "$SRC/brands/index.html" ]; then
  mkdir -p "$DEST/brands"
  cp "$SRC/brands/index.html" "$DEST/brands/index.html"
fi

# 스냅샷 날짜별 폴더도 동기 (선택적 — dashboard/YYMMDD/)
LATEST_SNAP=$(ls -t "$WK/deploy/dashboard/"[0-9]*/index.html 2>/dev/null | head -1 || true)
if [ -n "$LATEST_SNAP" ]; then
  SNAP_DIR=$(dirname "$LATEST_SNAP")
  SNAP_SLUG=$(basename "$SNAP_DIR")
  mkdir -p "$DEST/$SNAP_SLUG"
  cp "$LATEST_SNAP" "$DEST/$SNAP_SLUG/index.html"
fi

# 3) commit + push
cd "$PUB"
git add dashboard/
if git diff --cached --quiet; then
  echo "[3/3] 변경 없음 — push 불필요"
  exit 0
fi

TODAY=$(date "+%Y-%m-%d")
MSG="data(dashboard): $TODAY 가격 대시보드 갱신 (CMPA-505)"
git commit -m "$MSG"$'\n\nCo-Authored-By: Paperclip <noreply@paperclip.ing>'

if [ "$DRY" -eq 1 ]; then
  echo "[3/3] DRY-RUN — push 생략"
  git reset --soft HEAD~1
else
  echo "[3/3] push 중..."
  GIT_SSH_COMMAND="ssh -i $DEPLOY_KEY -o StrictHostKeyChecking=no" git push origin HEAD
  echo "라이브 배포 완료: https://godaji.github.io/CaskCode/dashboard/"
fi
