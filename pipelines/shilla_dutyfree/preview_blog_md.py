#!/usr/bin/env python3
"""CaskCode 블로그 — 로컬 즉시 미리보기 서버 (CMPA-178/182).

목적: Ruby/Jekyll 설치 없이 **로컬에서 블로그를 바로 띄워보기**(보드 요청).
build_blog_md.py 가 만든 self-contained Jekyll 사이트(blog-md/)의 md 를
python-markdown 으로 렌더 + CaskCode 레이아웃(brand.py)으로 감싸 임시 _site 에 만든 뒤
stdlib http.server 로 서빙한다.

  python3 pipelines/shilla_dutyfree/preview_blog_md.py            # 빌드+렌더+서빙(:4000)
  python3 pipelines/shilla_dutyfree/preview_blog_md.py --port 8080
  python3 pipelines/shilla_dutyfree/preview_blog_md.py --no-build # 현재 blog-md/ 그대로
  python3 pipelines/shilla_dutyfree/preview_blog_md.py --render-only --site DIR  # 서빙 없이 정적 _site 출력

주의: 이건 **콘텐츠 확인용 근사 렌더**다(Liquid/kramdown 완전호환 아님 — 홈 목록은
build_blog_md 와 동일 메타로 직접 구성). GitHub Pages 와 픽셀 동일 결과는 Docker/네이티브
Jekyll(README 참조). 이 스크립트는 메인 리포 도구이며 blog-md/(발행 폴더)엔 넣지 않는다.
"""
from __future__ import annotations

import argparse
import functools
import glob
import http.server
import os
import re
import shutil
import sys
import tempfile

import markdown  # python-markdown (stdlib 아님이나 환경에 존재)
import yaml

import brand
import build_blog_md as bm

MD_EXTS = ["tables", "fenced_code", "sane_lists", "attr_list"]


def _split_front_matter(text):
    if not text.startswith("---"):
        return {}, text
    parts = text.split("---", 2)
    if len(parts) < 3:
        return {}, text
    return (yaml.safe_load(parts[1]) or {}), parts[2].lstrip("\n")


def _md_html(body):
    return markdown.markdown(body, extensions=MD_EXTS, output_format="html5")


_POST_FN = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-(.+)\.md$")


def _post_url(md_basename):
    """`YYYY-MM-DD-slug.md` → Jekyll permalink `/YYYY/MM/DD/slug/`(_config 와 동일).
    timezone: Asia/Seoul 설정 시 파일명 날짜 = permalink 날짜라 그대로 매칭."""
    m = _POST_FN.match(md_basename)
    if not m:
        return "/" + os.path.splitext(md_basename)[0] + "/"
    y, mo, d, slug = m.groups()
    return f"/{y}/{mo}/{d}/{slug}/"


def _page(title, desc, robots, content_html, is_home):
    """_layouts/default.html(Satellite-스타일 스킨)과 동일 골격을 Python 으로 채운
    단일 페이지(미리보기). 사이드바·터미널 윈도우·별 배경 구조를 그대로 반영."""
    e = brand.html.escape
    back = ("" if is_home
            else '<a class="back" href="/">← 블로그 홈</a>')
    # HANDLE 제거(CMPA-194/195) — 빈 값이면 _layouts/default.html 과 동일하게
    # 사이드바 handle div·푸터 ' · 핸들' 꼬리를 렌더하지 않는다(라이브 레이아웃 패리티).
    handle_div = f'<div class="handle">{e(brand.HANDLE)}</div>' if brand.HANDLE else ""
    foot_name = (f"{e(brand.NAME_EN)} · {e(brand.HANDLE)}"
                 if brand.HANDLE else e(brand.NAME_EN))
    # Jekyll dev 서버(baseurl 없음)와 동일하게 루트 절대경로 사용 → URL 스킴 일치.
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="description" content="{e(desc)}">
<meta name="robots" content="{e(robots)}">
<title>{e(title)} — {e(brand.NAME_EN)}</title>
<link rel="stylesheet" href="/assets/css/style.css">
</head>
<body>
<div class="stars" aria-hidden="true"></div>
<div class="app">
<aside class="sidebar">
  <a class="avatar" href="/" aria-label="홈">🥃</a>
  <a href="/" style="text-decoration:none">{brand.flap_html()}</a>
  {handle_div}
  <ul class="snav">
    <li><a href="/">🏠 홈</a></li>
    <li><a href="/cask/">🥃 Cask</a></li>
    <li><a href="/code/">💻 Code</a></li>
    <li><a href="/apps/">🧰 앱</a></li>
  </ul>
  <div class="side-foot">
    <div class="about">{e(brand.ABOUT)}</div>
  </div>
</aside>
<main class="content">
{back}
<div class="window">
  <div class="titlebar"><span class="tdot r"></span><span class="tdot y"></span><span class="tdot g"></span><span class="name">{e(brand.NAME_EN)}</span></div>
  <div class="post">
{content_html}
  </div>
</div>
<div class="foot">
  <div>{foot_name}</div>
  <div class="about">{e(brand.ABOUT)}</div>
</div>
</main>
</div>
</body>
</html>
"""


def _li(p, badge=""):
    when = (p.get("latest_date") or p.get("base_date") or p["date"][:10])
    return (f'<li><span class="when">{when}</span> '
            f'<a href="{p["url"]}">{brand.html.escape(p["title"])}</a>{badge}</li>')


def _d10(s):
    """날짜 문자열 앞 10자(YYYY-MM-DD). front matter date 는 '+0900' 꼬리 포함."""
    return (str(s) or "")[:10]


def _chip(p):
    """홈 통합 피드 기둥 칩 — Code(dev)=💻, 그 외(Cask)=🥃 (index.md 와 동일)."""
    return "💻" if "dev" in (p.get("categories") or []) else "🥃"


def _bases_patches(posts):
    bases = sorted((p for p in posts if p.get("kind") == "base"),
                   key=lambda p: p.get("base_date") or p["date"], reverse=True)
    patches = sorted((p for p in posts if p.get("kind") == "patch"),
                     key=lambda p: p.get("latest_date") or p["date"], reverse=True)
    return bases, patches


def _home_html(posts):
    """홈 = build_blog_md._index_md(Option A, CMPA-196)와 동일 구조를 미리보기에서 재현:
    히어로(.sub) → ①🏆 시그니처 핀(최신 본편) → ②⚡ 최신 가격 패치 띠 →
    ③🆕 최신 글 통합 피드(5편·기둥 칩) → ④2기둥 카드(💻 Code / 🥃 Cask, /code/·/cask/ 링크).
    구 '온페이지'(모든 섹션을 홈에 펼치던) 레이아웃 폐기 — 기둥 목록은 /code/·/cask/ 가 소유."""
    e = brand.html.escape
    bases, patches = _bases_patches(posts)
    by_date = sorted(posts, key=lambda p: p.get("date") or "", reverse=True)

    out = [f'<p class="sub">{e(brand.ABOUT)}</p>']

    # ① 🏆 시그니처 핀 — 최신 본편 1편 큰 카드.
    if bases:
        b = bases[0]
        out += ['<div class="pin">',
                '  <span class="badge pin-badge">🏆 이번 달 면세 가성비</span>',
                f'  <a class="pin-title" href="{b["url"]}">{e(b["title"])}</a>',
                f'  <span class="pin-date">{_d10(b.get("base_date") or b["date"])}</span>',
                '</div>']

    # ② ⚡ 최신 가격 패치 띠 — 최신 패치 1건 얇은 줄.
    if patches:
        pt = patches[0]
        bk = pt.get("breakthroughs") or 0
        flag = (f'⚡ 국내최저 돌파 {bk}건' if bk and int(bk) > 0 else '⚡ 다이제스트')
        out += ['<div class="patch-strip">',
                f'  <span class="ps-flag">{flag}</span>',
                f'  <span class="ps-date">· {pt.get("latest_date") or _d10(pt["date"])}</span>',
                f'  <a class="ps-title" href="{pt["url"]}">{e(pt["title"])}</a>',
                '</div>']

    # ③ 🆕 최신 글(양 기둥 통합) — 날짜 desc 5편 + 기둥 칩.
    if by_date:
        out.append('<ul class="latest-feed">')
        for p in by_date[:5]:
            out.append(f'  <li><span class="chip">{_chip(p)}</span> '
                       f'<span class="when">{_d10(p["date"])}</span> '
                       f'<a href="{p["url"]}">{e(p["title"])}</a></li>')
        out.append('</ul>')

    # ④ 2기둥 카드 — 기둥 페이지로 링크 + 최신 미리보기(카운트·3편).
    out.append('<div class="hub">')
    for pil in bm.PILLARS:
        items = sorted((p for p in posts
                        if any(k in p["categories"] for k in pil["streams"])),
                       key=lambda p: p["date"], reverse=True)
        out += [f'  <a class="pillar-card" href="{pil["path"]}">',
                f'    <div class="pc-emoji">{pil["emoji"]}</div>',
                f'    <div class="pc-head"><span class="pc-title">{e(pil["label"])}</span>'
                f'<span class="pc-tag">{e(pil["tagline"])}</span></div>',
                f'    <p class="pc-desc">{e(pil["desc"].replace("`", ""))}</p>',
                f'    <div class="pc-count">글 {len(items)}편</div>',
                '    <ul class="pc-prev">']
        for p in items[:3]:
            out.append(f'      <li><span class="when">{_d10(p["date"])}</span> '
                       f'{e(p["title"])}</li>')
        out += ['    </ul>',
                '    <span class="pc-go">목록 보기 →</span>',
                '  </a>']
    out.append('</div>')
    return "\n".join(out)


def _pillar_html(pil, posts):
    """기둥 독립 목록 페이지(/code/·/cask/) — build_blog_md._pillar_body 와 동일 구조.
    머리말(h2) + 스트림(h3 + archive). Cask 엔 일기/숙성 안내 + '기타' 카테고리 폴백."""
    e = brand.html.escape
    out = [f'<h2>{pil["emoji"]} {e(pil["label"])} — {e(pil["tagline"])}</h2>',
           f'<p class="sub">{e(pil["desc"].replace("`", ""))}</p>']
    for key in pil["streams"]:
        if key == "price":
            # 보드 CMPA-197: '이달의 면세 가성비'+'가격 패치 아카이브' → 한 칸 '신라면세 위스키 정보'.
            bases, patches = _bases_patches(posts)
            lis = [_li(p) for p in bases]
            for p in patches:
                badge = (' <span class="badge instant">⚡ 돌파</span>'
                         if p.get("cadence") == "instant"
                         else ' <span class="badge digest">다이제스트</span>')
                if p.get("breakthroughs"):
                    badge += (' <span class="sub">· 국내최저 돌파 '
                              f'{p["breakthroughs"]}건</span>')
                lis.append(_li(p, badge))
            out += ['<h3>🏷️ 신라면세 위스키 정보</h3>',
                    '<p class="sub">면세 가성비 본편 + 가격 패치 — 국내최저 돌파 (자동 생성)</p>',
                    ('<ul class="archive">' + "".join(lis) + "</ul>"
                     if lis else '<div class="empty">아직 글이 없습니다.</div>')]
        else:
            s = bm.STREAMS[key]
            items = sorted((p for p in posts if key in p["categories"]),
                           key=lambda p: p["date"], reverse=True)
            out += [f'<h3>{s["emoji"]} {e(s["label"])}</h3>',
                    f'<p class="sub">{e(s["desc"].replace("`", ""))}</p>',
                    ('<ul class="archive">' + "".join(_li(p) for p in items) + "</ul>"
                     if items else '<div class="empty">아직 글이 없습니다.</div>')]
    if pil["label"] == "Cask":
        out.append('<blockquote>📓 <strong>일기</strong>·🛢️ <strong>숙성</strong>은 따로 '
                   '칸을 두지 않습니다 — 위스키 산 이야기·여정·느낀점은 <strong>#일기</strong>, '
                   '오크통 숙성·블렌딩 실험은 <strong>#숙성</strong> 태그로 Cask 글에 답니다.</blockquote>')
        extra = sorted({c for p in posts for c in p["categories"]
                        if c not in bm.SECTION_KEYS})
        if extra:
            out.append('<h2>🗂️ 기타 카테고리</h2>')
            for key in extra:
                items = sorted((p for p in posts if key in p["categories"]),
                               key=lambda p: p["date"], reverse=True)
                out.append(f'<h3>{e(key)}</h3>')
                out.append('<ul class="archive">'
                           + "".join(_li(p) for p in items) + "</ul>")
    return "\n".join(out)


def render_site(blog_dir, site_dir, drafts=False):
    """blog_dir(Jekyll 소스) → site_dir(정적 미리보기 트리)."""
    if os.path.isdir(site_dir):
        shutil.rmtree(site_dir)
    os.makedirs(os.path.join(site_dir, "assets", "css"), exist_ok=True)

    # CSS: blog-md 의 것을 그대로 복사(brand 단일 소스 결과).
    css_src = os.path.join(blog_dir, "assets", "css", "style.css")
    css_dst = os.path.join(site_dir, "assets", "css", "style.css")
    shutil.copyfile(css_src, css_dst)

    # 이미지: assets/img 가 있으면 통째 복사 → 글 본문 스크린샷(/assets/img/*.png)이
    # 미리보기에서 깨지지 않게(라이브 GitHub Pages 와 동일하게 보이도록).
    img_src = os.path.join(blog_dir, "assets", "img")
    if os.path.isdir(img_src):
        shutil.copytree(img_src, os.path.join(site_dir, "assets", "img"))

    # /apps/ (CMPA-208): deploy 정적 패스스루 미러. 있으면 통째 복사 → 사이드바
    # '🧰 앱' 링크가 미리보기에서도 동작(라이브 default.html nav 와 동일).
    apps_src = os.path.join(blog_dir, "apps")
    if os.path.isdir(apps_src):
        shutil.copytree(apps_src, os.path.join(site_dir, "apps"))

    # 포스트 소스: _posts + (옵션) _drafts. drafts 는 날짜 없는 파일명이라
    # front matter date 로 URL 을 만든다.
    srcs = sorted(glob.glob(os.path.join(blog_dir, "_posts", "*.md")))
    if drafts:
        srcs += sorted(glob.glob(os.path.join(blog_dir, "_drafts", "*.md")))

    posts = []
    for md_path in srcs:
        fm, body = _split_front_matter(open(md_path, encoding="utf-8").read())
        base = os.path.basename(md_path)
        slug = os.path.splitext(base)[0]
        title = fm.get("title", slug)
        desc = fm.get("description", brand.ABOUT)
        robots = fm.get("robots", "noindex,nofollow")
        if _POST_FN.match(base):            # _posts: 파일명에 날짜
            url = _post_url(base)
        else:                                # _drafts: front matter date 로 permalink
            d = str(fm.get("date", "2026-01-01"))[:10]
            y, mo, dd = (d.split("-") + ["01", "01"])[:3]
            url = f"/{y}/{mo}/{dd}/{slug}/"
        html_body = _md_html(body)
        page = _page(title, desc, robots, html_body, is_home=False)
        # 디스크 경로 = url + index.html (Jekyll _site 와 동일 구조).
        dest = os.path.join(site_dir, url.strip("/"), "index.html")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(page)
        posts.append({
            "slug": slug, "title": title, "date": str(fm.get("date", slug)),
            "url": url, "categories": fm.get("categories") or [],
            "kind": fm.get("kind"),
            "cadence": fm.get("cadence"), "breakthroughs": fm.get("breakthroughs"),
            "base_date": fm.get("base_date"), "latest_date": fm.get("latest_date"),
        })

    # 기둥 독립 목록 페이지(/code/·/cask/) — CMPA-192. 홈은 허브 카드로만 링크하고
    # 실제 글 목록은 이 페이지들이 소유한다(라이브 build_blog_md._pillar_page 패리티).
    for pil in bm.PILLARS:
        page = _page(f'{pil["emoji"]} {pil["label"]} — {pil["tagline"]}',
                     pil["desc"], "noindex,nofollow",
                     _pillar_html(pil, posts), is_home=False)
        dest = os.path.join(site_dir, pil["path"].strip("/"), "index.html")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(page)

    # 홈 — Option A(핀/패치 띠/최신 피드/허브). _home_html 는 완성형 HTML 이라
    # markdown 재변환 없이 그대로 .post 안에 넣는다(라이브 index.md 패리티).
    cfg = {}
    cfg_path = os.path.join(blog_dir, "_config.yml")
    if os.path.isfile(cfg_path):
        cfg = yaml.safe_load(open(cfg_path, encoding="utf-8")) or {}
    home = _page(cfg.get("title", brand.NAME_EN + " — 블로그"),
                 cfg.get("description", brand.ABOUT), "noindex,nofollow",
                 _home_html(posts), is_home=True)
    with open(os.path.join(site_dir, "index.html"), "w", encoding="utf-8") as fh:
        fh.write(home)
    return {"site": site_dir, "posts": len(posts)}


class _Utf8Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        if self.path.endswith((".html", "/")):
            self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def guess_type(self, path):
        t = super().guess_type(path)
        if path.endswith((".html", ".css")):
            return t + "; charset=utf-8"
        return t

    def log_message(self, *a):  # 조용히
        pass


def serve(site_dir, port):
    handler = functools.partial(_Utf8Handler, directory=site_dir)
    last = None
    for p in range(port, port + 10):
        try:
            httpd = http.server.ThreadingHTTPServer(("127.0.0.1", p), handler)
        except OSError as ex:
            last = ex
            continue
        url = f"http://127.0.0.1:{p}"
        print(f"\n  {brand.NAME_EN} 미리보기 — {url}", flush=True)
        print(f"  (정적 트리: {site_dir})", flush=True)
        print("  Ctrl+C 로 종료.\n", flush=True)
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\n  종료.")
            httpd.server_close()
        return 0
    print(f"  포트 {port}~{port+9} 모두 사용 중: {last}", file=sys.stderr)
    return 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=4000)
    ap.add_argument("--blog", default=bm.DEFAULT_OUT, help="Jekyll 소스(blog-md) 경로")
    ap.add_argument("--site", default=None, help="정적 미리보기 출력 경로(기본 임시)")
    ap.add_argument("--no-build", action="store_true",
                    help="build_blog_md 를 다시 돌리지 않고 현재 blog-md 그대로")
    ap.add_argument("--render-only", action="store_true",
                    help="서빙 없이 정적 _site 만 생성(--site 권장)")
    ap.add_argument("--drafts", action="store_true",
                    help="_drafts/ 템플릿도 함께 렌더(카테고리 채워진 모습 미리보기)")
    args = ap.parse_args()

    if not args.no_build:
        res = bm.build(out_dir=args.blog)
        nb = len(res["patches"])
        print(f"빌드 OK → {args.blog} (본편 "
              + (res["base"]["date"] if res["base"] else "없음")
              + f", 패치 {nb}개)")

    site_dir = args.site or tempfile.mkdtemp(prefix="ccc_preview_")
    r = render_site(args.blog, site_dir, drafts=args.drafts)
    print(f"렌더 OK → {r['posts']}개 포스트{' (+_drafts)' if args.drafts else ''} + 홈 → {site_dir}")

    if args.render_only:
        return 0
    return serve(site_dir, args.port)


if __name__ == "__main__":
    sys.exit(main())
