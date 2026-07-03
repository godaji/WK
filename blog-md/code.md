---
layout: "default"
title: "💻 Code — 직접 만든 것"
description: "CaskCode가 직접 개발한 소프트웨어·사이드프로젝트·코드 이야기와 위스키 데이터 분석."
permalink: "/code/"
robots: "index,follow"
---

<span id="code"></span>
## 💻 Code — 직접 만든 것
*CaskCode가 직접 개발한 소프트웨어·사이드프로젝트·코드 이야기와 위스키 데이터 분석.*


### 💻 개발
*직접 만든 소프트웨어·사이드프로젝트·코드 이야기*

{% assign items = site.posts | where_exp: "p", "p.categories contains 'dev'" | sort: "date" | reverse %}
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


### 📊 데이터 분석
*방법론·파이프라인 등 '어떻게 만들었나' (위스키 시세 비교는 wprice→Cask)*

{% assign items = site.posts | where_exp: "p", "p.categories contains 'data'" | sort: "date" | reverse %}
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
