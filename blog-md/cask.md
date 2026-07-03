---
layout: "default"
title: "🥃 Cask — 위스키 전부"
description: "구매/시음/숙성 노트 · 면세 가성비 자동 리포트 · 위스키 가격정보."
permalink: "/cask/"
robots: "index,follow"
---

<span id="cask"></span>
## 🥃 Cask — 위스키 전부
*구매/시음/숙성 노트 · 면세 가성비 자동 리포트 · 위스키 가격정보.*


### 🥃 구매/시음/숙성 노트
*사서 마셔본 기록 — 구매 노트 + 시음 (오크통 숙성 실험은 `#숙성` 태그)*

{% assign items = site.posts | where_exp: "p", "p.categories contains 'tasting'" | sort: "date" | reverse %}
{% if items.size > 0 %}
<ul class="archive">
{% for p in items %}
  <li><span class="when">{{ p.date | date: "%Y-%m-%d" }}</span>
  <a href="{{ p.url | relative_url }}">{{ p.title }}</a></li>
{% endfor %}
</ul>
{% else %}
<div class="empty">아직 글이 없습니다.</div>
{% endif %}


### 🏷️ 신라면세 위스키 정보
*면세 가성비 본편 + 주간 리포트 + 가격 패치 — 국내최저 돌파 (자동 생성)*

{% assign _bases = site.posts | where_exp: "p", "p.kind == 'base'" %}
{% assign _patches = site.posts | where_exp: "p", "p.kind == 'patch'" %}
{% assign _weeklies = site.posts | where_exp: "p", "p.kind == 'weekly'" %}
{% assign shilla_posts = _bases | concat: _weeklies | concat: _patches | sort: "date" | reverse %}
{% if shilla_posts.size > 0 %}
<ul class="archive">
{% for p in shilla_posts %}
  {% if p.kind == 'base' %}
  <li><span class="when">{{ p.base_date | default: p.date | date: "%Y-%m-%d" }}</span>
  <a href="{{ p.url | relative_url }}">{{ p.title }}</a></li>
  {% elsif p.kind == 'weekly' %}
  <li><span class="when">{{ p.weekly_end | default: p.date | date: "%Y-%m-%d" }}</span>
  <a href="{{ p.url | relative_url }}">{{ p.title }}</a>
  <span class="badge digest">📅 주간</span></li>
  {% elsif p.cadence == 'weekly' %}
  <li><span class="when">{{ p.latest_date | default: p.date | date: "%Y-%m-%d" }}</span>
  <a href="{{ p.url | relative_url }}">{{ p.title }}</a>
  <span class="badge digest">📅 주간 로그</span>
  {% if p.days %}<span class="sub">· {{ p.days }}일치 누적</span>{% endif %}</li>
  {% else %}
  <li><span class="when">{{ p.latest_date | default: p.date | date: "%Y-%m-%d" }}</span>
  <a href="{{ p.url | relative_url }}">{{ p.title }}</a>
  {% if p.cadence == 'instant' %}<span class="badge instant">⚡ 돌파</span>{% else %}<span class="badge digest">다이제스트</span>{% endif %}
  {% if p.breakthroughs > 0 %}<span class="sub">· 국내최저 돌파 {{ p.breakthroughs }}건</span>{% endif %}</li>
  {% endif %}
{% endfor %}
</ul>
{% else %}
<div class="empty">아직 글이 없습니다.</div>
{% endif %}


### 💰 위스키 가격정보
*국내·해외 위스키 시세 — 트레이더스·코스트코·데일리샷·홍콩·일본 비교*

{% assign items = site.posts | where_exp: "p", "p.categories contains 'wprice'" | sort: "date" | reverse %}
{% if items.size > 0 %}
<ul class="archive">
{% for p in items %}
  <li><span class="when">{{ p.date | date: "%Y-%m-%d" }}</span>
  <a href="{{ p.url | relative_url }}">{{ p.title }}</a></li>
{% endfor %}
</ul>
{% else %}
<div class="empty">아직 글이 없습니다.</div>
{% endif %}


{% assign known = "price,wprice,tasting,data,dev" | split: "," %}
{% capture _extras %}{% for cat in site.categories %}{% unless known contains cat[0] %}{{ cat[0] }},{% endunless %}{% endfor %}{% endcapture %}
{% if _extras != "" %}
## 🗂️ 기타 카테고리
{% for cat in site.categories %}{% unless known contains cat[0] %}
### {{ cat[0] }}
<ul class="archive">
{% for p in cat[1] %}
  <li><span class="when">{{ p.date | date: "%Y-%m-%d" }}</span>
  <a href="{{ p.url | relative_url }}">{{ p.title }}</a></li>
{% endfor %}
</ul>
{% endunless %}{% endfor %}
{% endif %}
