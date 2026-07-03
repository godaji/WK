#!/usr/bin/env bash
# 위스키 적금 PWA(Dram Jar) 발행 + floor 일/주 갱신 (CMPA-351 T3)
#
# 배포 경로 = /CaskCode/dj/ (CMPA-365 보드 확정 — 앱 이름 Dram Jar → 짧은 슬러그 dj).
#   구 경로 /CaskCode/frugal/ 는 리다이렉트 스텁(메타 새로고침 + 자가해제 sw)으로 유지해
#   기존 북마크·블로그 링크·설치된 PWA 가 새 경로로 넘어가게 한다.
# 앱 셸은 전부 상대경로(manifest start_url/scope='./', sw.js './…')라 디렉터리만 옮기면
#   앱 내부는 무수정으로 동작한다.
#
# apps/frugal/ 은 발행 SYNC 스코프 밖(CMPA-284: apps/ 미러 폐지)이라 surgical push 가 필요.
# 이 스크립트가 그 단일 진입점이다. 기존 일일 발행 루틴
# (run_shilla_price_change.py --publish-blog)에서 호출돼 매일 cadence 를 탄다.
#
# 동작:
#   1) 앱 셸(index.html/style.css/app.js/sw.js/manifest.json/icons)을 발행 레포 /dj/ 에 미러.
#   2) (기본) T1(CMPA-349) build_whisky_floor_json.py 로 whisky_floor.json 을
#      발행 레포에 **직접 재생성**(국내 floor=min KR/KR-DS, 면세/dirty 제외, 결정론).
#      → WK 정본 apps/frugal/whisky_floor.json(시드/스키마 레퍼런스)은 건드리지 않아
#        WK 워킹트리가 더러워지지 않는다. 라이브만 매일 신선.
#      --no-build 면 WK 정본 JSON 을 그대로 복사(초기 배포/오프라인용).
#   3) 구 /frugal/ 경로에 리다이렉트 스텁을 깐다(멱등).
#   4) 변경 있으면 commit + push(라이브). --dry-run 이면 push 없이 미리보기.
set -euo pipefail

WK="${WK_ROOT:-/mnt/c/Users/shhon/Desktop/WK}"
PUB="${CASKCODE_PUBLISH:-/mnt/c/Users/shhon/Desktop/caskcode-publish}"
SRC="$WK/apps/frugal"
APP="dj"          # 배포 슬러그 — /CaskCode/$APP/ (CMPA-365). 바꾸려면 이 한 줄 + 블로그 링크.
OLD="frugal"      # 구 경로(리다이렉트 유지)
DEPLOY_KEY="${CASKCODE_DEPLOY_KEY:-$HOME/.ssh/caskcode_deploy_key}"
BUILD=1; DRY=0
for a in "$@"; do
  case "$a" in
    --no-build) BUILD=0;;
    --dry-run)  DRY=1;;
  esac
done

[ -d "$SRC" ] || { echo "ERR: source $SRC 없음"; exit 1; }
[ -d "$PUB/.git" ] || { echo "ERR: publish repo $PUB 없음"; exit 1; }

# 0) 발행 클론 자가치유(CMPA-674): 순수 배포 미러이므로 파일 생성 전에 origin/main 으로
#    fetch+reset 해 갈라짐(ahead/behind)을 폐기한다. 다른 발행 경로가 push 해 이 클론이
#    뒤처지면 'fetch first' 로 거부되는 상습 실패를 막는다. fetch 실패 시 폴백(그대로 진행).
if [ "$DRY" != "1" ]; then
  if GIT_SSH_COMMAND="ssh -i $DEPLOY_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
       git -C "$PUB" fetch origin main; then
    git -C "$PUB" reset --hard origin/main
  else
    echo "  ⚠️ fetch 실패 → reset 생략, 기존 클론 상태로 진행(폴백)."
  fi
fi

# 1) 앱 셸 미러(정적 — floor JSON 제외하고 전체 교체)
rm -rf "$PUB/$APP"
mkdir -p "$PUB/$APP/icons"
cp -f "$SRC"/index.html "$SRC"/style.css "$SRC"/app.js "$SRC"/manifest.json "$SRC"/sw.js "$PUB/$APP/"
cp -f "$SRC"/icons/* "$PUB/$APP/icons/"

# 2) floor JSON
if [ "$BUILD" = "1" ] && [ -f "$WK/scripts/build_whisky_floor_json.py" ]; then
  python3 "$WK/scripts/build_whisky_floor_json.py" --out "$PUB/$APP/whisky_floor.json"
else
  cp -f "$SRC"/whisky_floor.json "$PUB/$APP/whisky_floor.json"
fi

# 3) 구 /frugal/ → /dj/ 리다이렉트 스텁(멱등). 앱 셸이 아니라 forwarder 만 남긴다.
rm -rf "$PUB/$OLD"
mkdir -p "$PUB/$OLD"
cat > "$PUB/$OLD/index.html" <<HTML
<!doctype html><html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Dram Jar — 이동</title>
<link rel="canonical" href="https://godaji.github.io/CaskCode/$APP/">
<meta http-equiv="refresh" content="0; url=../$APP/">
<script>location.replace('../$APP/');</script>
</head><body style="font-family:system-ui;background:#1a130c;color:#eee;padding:2rem">
앱이 <a href="../$APP/" style="color:#e6b25a">/$APP/</a> 으로 이동했습니다…
</body></html>
HTML
# 설치된 구 PWA 자가해제: 구 sw 를 비-캐시 forwarder 로 교체 → 캐시 비우고 등록 해제.
cat > "$PUB/$OLD/sw.js" <<'SW'
// 구 /frugal/ PWA 자가해제 — 캐시 전체 삭제 후 등록 해제(새 /dj/ 로 이동 유도).
self.addEventListener('install', e => self.skipWaiting());
self.addEventListener('activate', e => e.waitUntil((async () => {
  for (const k of await caches.keys()) await caches.delete(k);
  await self.registration.unregister();
  for (const c of await self.clients.matchAll()) c.navigate(c.url);
})()));
SW

cd "$PUB"
git add "$APP"/ "$OLD"/
if git diff --cached --quiet; then
  echo "변경 없음 — push 생략(멱등)."
  exit 0
fi
COLLECTED=$(python3 -c "import json;d=json.load(open('$APP/whisky_floor.json'));print(d[0]['collected_at'] if isinstance(d,list) and d else '')" 2>/dev/null || echo "")
if [ "$DRY" = "1" ]; then
  echo "[dry-run] 발행 대기 변경:"; git diff --cached --stat
  exit 0
fi
git commit -q -m "deploy(dj): Dram Jar PWA + floor 갱신 (latest ${COLLECTED}) (CMPA-351)

Co-Authored-By: Paperclip <noreply@paperclip.ing>"
GIT_SSH_COMMAND="ssh -i $DEPLOY_KEY -o IdentitiesOnly=yes -o StrictHostKeyChecking=accept-new" \
  git push origin main
echo "발행 완료. 검증: curl -s https://godaji.github.io/CaskCode/$APP/whisky_floor.json | python3 -c 'import json,sys;print(json.load(sys.stdin)[0])'"
