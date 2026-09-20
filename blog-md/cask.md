---
layout: "default"
title: "🥃 Cask — 위스키 전부"
description: "구매·시음·숙성 노트와 위스키 이야기."
permalink: "/cask/"
robots: "index,follow"
---

<span id="cask"></span>
## 🥃 Cask — 위스키 전부
*구매·시음·숙성 노트와 위스키 이야기.*


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
