# DreamJar 배포 매뉴얼

DreamJar 앱을 배포할 때 반드시 이 체크리스트를 따른다.

## 배포 경로

```
apps/dreamjar/  (소스 정본)
    ↓  파일 복사
deploy/dreamjar/  (WK 리포 배포 사본)
    ↓  파일 복사
~/work/caskcode-publish/dreamjar/  (CaskCode Pages 배포)
    ↓  git push
https://godaji.github.io/CaskCode/dreamjar/  (라이브 사이트)
```

## 배포 체크리스트

### 1. 캐시 버스팅 업데이트
- [ ] `apps/dreamjar/index.html`의 CSS/JS 버전 쿼리 업데이트
  - `style.css?v=YYYYMMDD{a-z}`
  - `supabase/supabase.js?v=YYYYMMDD{a-z}`
  - `app.js?v=YYYYMMDD{a-z}`
- [ ] 같은 날 여러 배포 시 suffix 증가 (a→b→c…)

### 2. apps/ → deploy/ 동기화
- [ ] `apps/dreamjar/index.html` → `deploy/dreamjar/index.html`
- [ ] `apps/dreamjar/app.js` → `deploy/dreamjar/app.js`
- [ ] `apps/dreamjar/style.css` → `deploy/dreamjar/style.css`
- [ ] `apps/dreamjar/supabase/supabase.js` → `deploy/dreamjar/supabase/supabase.js`
- [ ] 새 파일이 있으면 함께 복사 (SQL, 이미지 등)
- [ ] diff로 apps/ vs deploy/ 동일 확인

### 3. WK 리포 커밋 & 푸시
- [ ] 변경 파일 `git add`
- [ ] 커밋 메시지: `feat(dreamjar): ... (CMPA-xxx)`
- [ ] `git push origin main` → `godaji/WK`

### 4. CaskCode Pages 배포 (이것이 실제 라이브 배포!)
- [ ] `deploy/dreamjar/` → `~/work/caskcode-publish/dreamjar/` 파일 복사
  ```bash
  cp deploy/dreamjar/index.html ~/work/caskcode-publish/dreamjar/
  cp deploy/dreamjar/app.js ~/work/caskcode-publish/dreamjar/
  cp deploy/dreamjar/style.css ~/work/caskcode-publish/dreamjar/
  cp deploy/dreamjar/supabase/supabase.js ~/work/caskcode-publish/dreamjar/supabase/
  # 새 파일도 복사
  ```
- [ ] caskcode-publish에서 `git add`, `git commit`
- [ ] deploy key로 push:
  ```bash
  cd ~/work/caskcode-publish
  GIT_SSH_COMMAND="ssh -i ~/.ssh/caskcode_deploy_key" git push origin main
  ```

### 5. 배포 확인
- [ ] `https://godaji.github.io/CaskCode/dreamjar/` 접속 (1~2분 후)
- [ ] 캐시 버전이 새 버전인지 확인 (개발자 도구 → Network)
- [ ] 변경 사항이 반영되었는지 확인
- [ ] 필요시 강제 새로고침 (Ctrl+Shift+R / Cmd+Shift+R)

## 자주 하는 실수

| 실수 | 증상 | 해결 |
|---|---|---|
| CaskCode push 누락 | WK에만 push, 라이브 사이트 안 바뀜 | caskcode-publish에 복사 + push |
| 캐시 버스팅 안 함 | iOS PWA에서 옛 버전 표시 | index.html의 v= 쿼리 업데이트 |
| deploy/ 동기화 누락 | apps/와 deploy/가 다름 | diff 확인 후 복사 |
| apps/만 수정 | deploy/에 반영 안 됨 | 양쪽 모두 동기화 |

## 요약

**"배포" = CaskCode Pages push까지 해야 완료.**
WK push만으로는 라이브 사이트에 반영되지 않는다.
