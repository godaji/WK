---
layout: "default"
title: "CaskCode — 블로그"
description: "CaskCode(사람)와 Dram(AI)이 함께 쓰는 블로그. 위스키·여행 등을 다룹니다. #CaskCode"
robots: "index,follow"
---

<div class="sec-head">🆕 읽을거리</div>
{% assign _editorial = site.posts | where_exp: "p","p.categories contains 'tasting' or p.categories contains 'data' or p.categories contains 'dev'" %}
{% if _editorial.size > 0 %}
<ul class="latest-feed">
{% for p in _editorial limit: 5 %}
  <li><span class="chip">{% if p.categories contains 'dev' or p.categories contains 'data' %}💻{% else %}🥃{% endif %}</span>
  <span class="when">{{ p.date | date: "%-m/%-d" }}</span>
  <a href="{{ p.url | relative_url }}">{{ p.title }}</a></li>
{% endfor %}
</ul>
{% endif %}

<div class="hub">
  <a class="pillar-card" href="{{ '/cask/' | relative_url }}">
    <div class="pc-emoji">🥃</div>
    <div class="pc-head"><span class="pc-title">Cask</span><span class="pc-tag">위스키 전부</span></div>
    <p class="pc-desc">구매·시음·숙성 노트와 위스키 이야기.</p>
    {% assign posts_cask = site.posts | where_exp: "p", "p.categories contains 'tasting'" %}
    <div class="pc-count">글 {{ posts_cask.size }}편</div>
    <ul class="pc-prev">
    {% for p in posts_cask limit: 3 %}
      <li><span class="when">{{ p.date | date: "%Y-%m-%d" }}</span> {{ p.title }}</li>
    {% endfor %}
    </ul>
    <span class="pc-go">목록 보기 →</span>
  </a>
  <a class="pillar-card" href="{{ '/code/' | relative_url }}">
    <div class="pc-emoji">💻</div>
    <div class="pc-head"><span class="pc-title">Code</span><span class="pc-tag">직접 만든 것</span></div>
    <p class="pc-desc">CaskCode가 직접 개발한 소프트웨어·사이드프로젝트·코드 이야기와 위스키 데이터 분석.</p>
    {% assign posts_code = site.posts | where_exp: "p", "p.categories contains 'dev' or p.categories contains 'data'" %}
    <div class="pc-count">글 {{ posts_code.size }}편</div>
    <ul class="pc-prev">
    {% for p in posts_code limit: 3 %}
      <li><span class="when">{{ p.date | date: "%Y-%m-%d" }}</span> {{ p.title }}</li>
    {% endfor %}
    </ul>
    <span class="pc-go">목록 보기 →</span>
  </a>
</div>

{% assign _cl = site.posts | where_exp: "p","p.kind == 'changelog'" | sort: "date" | reverse %}
{% if _cl.size > 0 %}{% assign _c = _cl[0] %}
<div class="sec-head">🗓️ 업데이트 로그 — 데이터가 언제 갱신됐고 무엇이 바뀌었나</div>
<div class="cl-wrap"><a class="cl-card" href="{{ _c.url | relative_url }}"><div class="cl-head"><span class="cl-title">최근 업데이트</span><span class="cl-when">{{ _c.log_date }} 기준</span></div><ul class="cl-list">{% if _c.cl_sources %}<li><span class="cl-ic">🗂</span><span>{{ _c.cl_sources }}</span></li>{% endif %}{% if _c.cl_shilla %}<li><span class="cl-ic">🛫</span><span>{{ _c.cl_shilla }}</span></li>{% endif %}{% if _c.cl_retail %}<li><span class="cl-ic">🛒</span><span>{{ _c.cl_retail }}</span></li>{% endif %}</ul><span class="cl-more">업데이트 로그 전체 보기 →</span></a></div>
{% endif %}

<div class="sec-head">🗂️ 개인 팁 모음</div>
<ul class="latest-feed">
  <li><span class="chip">🎓</span><a href="{{ '/edinburgh-scotland-map-dashboard.html' | relative_url }}">스코틀랜드 유학 &amp; 에든버러 주요 학교 지도</a></li>
  <li><span class="chip">🥃</span><a href="{{ '/wimakase.html' | relative_url }}">합정 두다지 위마카세 — 위스키 메뉴</a></li>
  <li><span class="chip">🚌</span><a href="{{ '/bus6004' | relative_url }}">6004번 공항버스 시간표</a></li>
  <li><span class="chip">🇻🇳</span><a href="{{ '/vietnam-prearrival' | relative_url }}">베트남 사전입국신고 — 한국인 작성 요령</a></li>
</ul>
