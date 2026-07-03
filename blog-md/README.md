# CaskCode — 블로그 (Jekyll / GitHub Pages)

이 폴더는 **블로그 전용 self-contained Jekyll 사이트**입니다(CMPA-178). 생성기 코드·원천
데이터(`data/`·`pipelines/`·스크랩 CSV)는 **포함하지 않습니다** — 이 폴더만 별도 public
리포로 push 하면 됩니다. 생성기는 메인 리포 `pipelines/shilla_dutyfree/build_blog_md.py`.

## 로컬에서 띄워보기 (3가지 — 위에서부터 추천)

### A. 즉시 미리보기 (설치 0, Python만) — 추천
Ruby 설치 없이 바로 본다. 메인 리포 루트에서:
```bash
python3 pipelines/shilla_dutyfree/preview_blog_md.py
# → http://127.0.0.1:4000 자동 안내. Ctrl+C 로 종료.
```
빌드(`build_blog_md.py`)를 먼저 돌려 최신 md 를 만들고, CaskCode·Satellite-스타일
레이아웃(좌측 프로필 사이드바·터미널 윈도우 카드·별 배경)으로 렌더해 로컬 서버로
띄운다. (Liquid/kramdown 근사 — 콘텐츠 확인용. 최종 픽셀은 B/C 로.)

### B. 진짜 Jekyll, 설치 없이 (Docker)
GitHub Pages 와 동일한 Jekyll 결과. **반드시 `blog-md/` 안에서** 실행:
```bash
cd blog-md   # ← 중요: 이 폴더에서 실행해야 _config.yml 이 잡힌다
docker run --rm -v "$PWD":/srv/jekyll -v ccc_bundle:/usr/local/bundle   -p 4000:4000 jekyll/jekyll:4 jekyll serve --host 0.0.0.0 --no-watch
# → http://localhost:4000  (홈에서 글 링크 클릭)
```
- **첫 실행은 1~2분** 걸린다(gem 98개 설치). `Installing ...` 가 멈춘 게 아니라 진행 중.
  `Server address: http://0.0.0.0:4000` 가 뜨면 준비 완료 → 브라우저에서 접속.
- `-v ccc_bundle:...` 로 gem 을 캐시 → **다음 실행부터는 빠름**.
- `--no-watch` 는 Windows/WSL 자동재생성 경고·불안정을 피한다(글 바꾸면 컨테이너 재시작).
- 그래도 안 뜨면 → **방법 A(파이썬 미리보기)** 를 쓰면 설치·대기 없이 즉시 보인다.

### C. 네이티브 Ruby/Jekyll
```bash
# WSL/Ubuntu: sudo apt install -y ruby-full build-essential
gem install jekyll bundler   # 또는 bundle install (Gemfile=github-pages)
bundle exec jekyll serve
```

## 카테고리(섹션)와 글 쓰기
홈은 **브랜드 2기둥(Code / Cask)** 으로 묶여 나옵니다(CMPA-182 리브랜드):
- **🥃 Cask — 위스키 전부**: 구매/시음/숙성 노트(`tasting`), 면세 가성비(`price`), 위스키 가격정보(`wprice`)
- **💻 Code — 직접 만든 것**: 개발(`dev`), 데이터 분석(`data`)

> 📓 **일기**·🛢️ **숙성**은 별도 칸이 아니라 **태그**입니다 — 위스키 산 이야기·여정·느낀점은
> **`#일기`**, 오크통 숙성·블렌딩 실험은 **`#숙성`** 태그로 Cask 글에 답니다(`tags: [일기]`).

새 글은 front matter 의 `categories: [<key>]` 로 스트림을 정합니다(`dev`/`data`=Code, `price`/`wprice`/`tasting`=Cask).
**새 key 를 쓰면 '기타 카테고리'에 자동으로 나타납니다**(설정 변경 불필요).

### 직접 글 쓰는 법 (개발·데이터·가격정보·시음 등)
1. 기존 글(예: `_posts/*-monthly-base.md`)의 front matter 구조를 참고해 새 파일을 만든다.
2. 내용·front matter(`title`/`date`/`categories`/`tags`) 채우기.
3. **`_posts/YYYY-MM-DD-제목.md`** 로 저장(파일명 날짜 = 발행일).
4. 미리보기: `python3 pipelines/shilla_dutyfree/preview_blog_md.py`
   (`_drafts` 만 보려면 `--drafts`). 또는 `jekyll serve` 재시작.

> ⚠️ `build_blog_md.py` 는 **자동 생성 포스트(`*-monthly-base.md`/`*-price-patch.md`)만**
> 다시 만듭니다. 손으로 쓴 글은 건드리지 않으니 안심하고 `_posts/` 에 두세요.
> **`_drafts/` 에 두면 라이브에 안 나옵니다**(프로덕션 빌드는 `--drafts` 미사용) — 발행하려면 `_posts/`.
> 사진은 **VSCode 에서 그냥 스크린샷을 붙여넣으면 됩니다**(보드 결정 에디터 — CMPA-223).
> `.vscode/settings.json` 의 `markdown.copyFiles.destination` 가 `assets/img/<글파일명>/` 에 저장하고
> `![](../assets/img/<글파일명>/x.png)` 같은 상대경로를 삽입합니다. `assets/img/` 에 직접 넣고
> `![설명](assets/img/파일.jpg)`·`![설명](/assets/img/파일.jpg)` 로 써도 됩니다.
> ✅ 사이트가 `baseurl: /CaskCode` 아래 있지만, 이제 `build_blog_md.py` 가 발행 시 절대·베어·`../` 상대 경로를
> **자동으로 `{{ '...' | relative_url }}` 로 래핑**(CMPA-224)하므로 직접 감쌀 필요가 없습니다.
> 이미 `relative_url` 로 감쌌거나 외부 URL(`http(s)://`)·스킴-상대(`//cdn`)는 그대로 둡니다.
> (Obsidian 위키링크 `![[파일.png]]` 는 범위 밖 — 에디터에서 '위키링크' 옵션을 끄고 일반 마크다운으로 붙여넣으세요.)

## 발행 게이트
외부 발행은 보드 게이트(c7405e7d) 승인 후에만. 그 전까지 모든 페이지 `robots: noindex`.
콘텐츠는 가공·에디토리얼(랭킹·요약)이며 원천 스크랩 표는 덤프하지 않습니다.
가격은 각 스냅샷 **수집일 기준값**(CMPA-156).
