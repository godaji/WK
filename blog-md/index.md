---
layout: "default"
title: "CaskCode — 블로그"
description: "CaskCode(사람)와 Dram(AI)이 함께 쓰는 블로그. 위스키·여행 등을 다룹니다. #CaskCode"
robots: "index,follow"
---
{% assign _gc = site.posts | where_exp: "p","p.url contains 'dutyfree-whisky-compare'" | sort: "date" | reverse %}
{% if _gc.size > 0 and _gc[0].carousel and _gc[0].carousel.size > 0 %}{% assign _g = _gc[0] %}
<div class="gapc-wrap"><div class="gapc-head"><span class="gapc-title">💱 면세점 vs 국내, 어디가 더 쌀까</span><span class="gapc-when">{{ _g.carousel_date }} 기준</span></div><ul class="gapc-track">{% for it in _g.carousel %}<li class="gapc-item"><a class="gapc-lnk" href="{{ it.url | relative_url }}"><span class="gapc-txt">{{ it.text }}</span></a></li>{% endfor %}</ul><a class="gapc-more" href="{{ _g.url | relative_url }}">면세 vs 국내 전체 비교 보기 →</a></div>
<script>(function(){var R=window.matchMedia&&window.matchMedia('(prefers-reduced-motion: reduce)').matches;if(R){return;}var ts=document.querySelectorAll('.gapc-track');for(var k=0;k<ts.length;k++){(function(tr){var items=tr.querySelectorAll('.gapc-item');if(items.length<2){return;}var cur=0,timer=null,paused=false;tr.classList.add('gapc-on');function measure(li){var t=li.querySelector('.gapc-txt');li.classList.remove('gapc-marq');li.style.removeProperty('--marq-shift');li.style.removeProperty('--marq-dur');if(!t){return false;}var over=t.scrollWidth-li.clientWidth;if(over>4){li.style.setProperty('--marq-shift',(-(over+8))+'px');li.style.setProperty('--marq-dur',Math.max(5,(over+8)/35).toFixed(1)+'s');li.classList.add('gapc-marq');return true;}return false;}function schedule(m){timer=setTimeout(next,m?9000:4000);}function next(){items[cur].classList.remove('gapc-cur');cur=(cur+1)%items.length;var li=items[cur];li.classList.add('gapc-cur');var m=measure(li);if(!paused){schedule(m);}}items[0].classList.add('gapc-cur');schedule(measure(items[0]));function pause(){paused=true;if(timer){clearTimeout(timer);timer=null;}}function play(){if(paused){paused=false;if(!timer){schedule(items[cur].classList.contains('gapc-marq'));}}}var w=tr.closest('.gapc-wrap')||tr;w.addEventListener('mouseenter',pause);w.addEventListener('mouseleave',play);w.addEventListener('focusin',pause);w.addEventListener('focusout',play);})(ts[k]);}})();</script>
{% endif %}

<section class="buy-section df">
<div class="bs-head"><span class="bs-ic">🛫</span><div class="bs-txt"><div class="bs-title">면세점에서 구매할 때</div><div class="bs-sub">출국·입국 예정이라면 — 신라·롯데·신세계 면세 가격 비교</div></div></div>
{% assign _cmp = site.posts | where_exp: "p","p.url contains 'dutyfree-whisky-compare'" | sort: "date" | reverse %}
{% if _cmp.size > 0 %}<a class="dash-cta" href="{{ _cmp[0].url | relative_url }}">🥃 신라-롯데-신세계 면세점 가격 비교 →<span class="dash-sub">세 면세점 100ml당 최저가 비교</span></a>
{% endif %}

{% assign _wl = site.posts | where_exp: "p","p.kind == 'patch' and p.cadence == 'weekly'" | sort: "date" | reverse %}
{% if _wl.size > 0 and _wl[0].rare_drops_count > 0 %}{% assign _r = _wl[0] %}
<div class="sec-head">🕰️ 신라면세 오랜만의 큰 인하 — 거의 정상가였다가 모처럼 큰 폭 인하</div>
<div class="rare-wrap"><a class="rare-card" href="{{ _r.url | relative_url }}"><div class="rare-head"><span class="rare-title">이번 주 {{ _r.rare_drops_count }}종 인하</span><span class="rare-when">{{ _r.latest_date | default: _r.weekly_end }} 기준</span></div><ul class="rare-list">{% for d in _r.rare_drops %}<li><span class="rare-mark">🕰️</span><span>{{ d }}</span></li>{% endfor %}</ul><span class="rare-more">자세히 보기 →</span></a></div>
{% endif %}

{% assign _wlogs = site.posts | where_exp: "p","p.kind == 'patch' and p.cadence == 'weekly'" | sort: "date" | reverse %}
{% if _wlogs.size > 0 %}{% assign _w = _wlogs[0] %}
<div class="sec-head">🔥 이번주 핫딜 — 면세가가 국내최저보다 싼 위스키</div>
<div class="hotdeal-wrap"><a class="hotdeal-card" href="{{ _w.url | relative_url }}"><div class="hd-head"><span class="hd-title">{{ _w.title }}</span><span class="hd-when">{{ _w.latest_date | default: _w.weekly_end }} 기준</span></div>{% if _w.hotdeals and _w.hotdeals.size > 0 %}<ul class="hotdeal-list">{% for d in _w.hotdeals %}<li><span class="hd-fire">🔥</span><span>{{ d }}</span></li>{% endfor %}</ul>{% assign _rest = _w.hotdeals_count | minus: _w.hotdeals.size %}<span class="hd-more">{% if _rest > 0 %}+ {{ _rest }}종 더 · {% endif %}주간 로그 전체 보기 →</span>{% else %}<span class="hd-more">이번 주 가격 변동 로그 보기 →</span>{% endif %}</a></div>
{% endif %}

</section>

<section class="buy-section mart">
<div class="bs-head"><span class="bs-ic">🛒</span><div class="bs-txt"><div class="bs-title">마트에서 구매할 때</div><div class="bs-sub">트레이더스·코스트코·이마트 등 국내 소매가</div></div></div>
<a class="dash-cta" href="{{ '/dashboard/' | relative_url }}">📊 위스키 가격 대시보드 →<span class="dash-sub">소매가 · 면세가 · 해외가 비교</span></a>
{% assign _mart = site.posts | where_exp: "p","p.url contains 'mart-cheaper-whisky'" | sort: "date" | reverse %}
{% if _mart.size > 0 %}<a class="dash-cta" href="{{ _mart[0].url | relative_url }}">🥃 면세점보다 싸거나 비슷한 위스키 →<span class="dash-sub">마트·국내가가 면세가 이하인 위스키</span></a>
{% endif %}

</section>

<div class="sec-head">🆕 읽을거리</div>
<a class="dash-cta" href="{{ '/dashboard/brands/' | relative_url }}">🥃 위스키 브랜드별 구매 팁 →<span class="dash-sub">브랜드별 가치 추천 · 등급 사다리</span></a>
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
    <p class="pc-desc">구매/시음/숙성 노트 · 면세 가성비 자동 리포트 · 위스키 가격정보.</p>
    {% assign posts_cask = site.posts | where_exp: "p", "p.categories contains 'tasting' or p.categories contains 'price' or p.categories contains 'wprice'" %}
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
  <li><span class="chip">🚌</span><a href="{{ '/bus6004' | relative_url }}">6004번 공항버스 시간표</a></li>
  <li><span class="chip">🇻🇳</span><a href="{{ '/vietnam-prearrival' | relative_url }}">베트남 사전입국신고 — 한국인 작성 요령</a></li>
</ul>

