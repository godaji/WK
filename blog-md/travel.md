---
layout: "default"
title: "✈️ Travel — 여행"
description: "CaskCode의 여행 기록 — 위스키 증류소 투어·맛집·일정."
permalink: "/travel/"
robots: "index,follow"
---

<span id="travel"></span>
## ✈️ Travel — 여행
*CaskCode의 여행 기록 — 위스키 증류소 투어·맛집·일정.*

{% assign items = site.posts | where_exp: "p", "p.categories contains 'travel'" | sort: "date" | reverse %}
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
