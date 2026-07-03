/* 캐스크 적금 (Dram Jar) — 핵심 로직
   CMPA-350 / 정본 CMPA-347 plan §2~§6,§9 · CMPA-351 보드 피드백 반영
   ── 목표 = '적금통(jar) 인스턴스'. 적립은 활성 적금통 안에 쌓인다.
      목표 달성 → '구매 완료' 로 캐비닛에 보관하고 다음 목표(새 적금통)를 시작.
   저장 = localStorage 단일 소스(가계부형, 서버/계정 0). floor = whisky_floor.json fetch. */

(() => {
  'use strict';

  const STORE_KEY = 'dramjar.v2';
  const OLD_KEY = 'dramjar.v1';
  const KRW = new Intl.NumberFormat('ko-KR');
  const won = n => KRW.format(Math.round(n)) + '원';
  const uid = () => 'j' + Date.now().toString(36) + Math.floor(performance.now()).toString(36);

  // ── 절약 항목 시드 (plan §6). amount=0 인 항목(impulse)은 탭 시 금액 입력형. ──
  const SEED_ITEMS = [
    { id:'coffee',   emoji:'☕', label:'드립커피',     rate:4500  },
    { id:'tumbler',  emoji:'💧', label:'텀블러·물병',   rate:1200  },
    { id:'latenight',emoji:'🌙', label:'야식 거름',     rate:18000 },
    { id:'homebar',  emoji:'🥃', label:'홈술',         rate:30000 },
    { id:'lunchbox', emoji:'🍱', label:'도시락·집밥',   rate:8000  },
    { id:'transit',  emoji:'🚶', label:'도보·대중교통', rate:9000  },
    { id:'subcancel',emoji:'📺', label:'구독 해지',     rate:13500 },
    { id:'mvno',     emoji:'📱', label:'알뜰폰(월)',    rate:30000 },
    { id:'bulk',     emoji:'🛒', label:'대용량 구매',   rate:3000  },
    { id:'impulse',  emoji:'🧊', label:'충동구매 참기', rate:0, prompt:true },
  ];

  // ── 상태 ──
  // state = { activeJar:{id,productId,name,createdAt,savings:[{ts,itemId,amount}]}|null,
  //           cabinet:[{id,productId,name,createdAt,redeemedAt,savedTotal,floorAtRedeem}],
  //           itemRates:{} }
  let state = load();
  let floors = [];     // whisky_floor.json
  let rateEdit = null; // {itemId, value}
  let celebrated = false;

  function load() {
    try {
      const raw = localStorage.getItem(STORE_KEY);
      if (raw) {
        const s = JSON.parse(raw);
        s.activeJar = normJar(s.activeJar);
        s.cabinet = Array.isArray(s.cabinet) ? s.cabinet : [];
        s.itemRates = s.itemRates || {};
        return s;
      }
      // v1 → v2 마이그레이션(기존 사용자 데이터 보존)
      const old = JSON.parse(localStorage.getItem(OLD_KEY) || 'null');
      if (old) {
        const jar = old.goal
          ? { id: uid(), productId: old.goal.productId, name: old.goal.name,
              createdAt: Date.now(), savings: Array.isArray(old.savings) ? old.savings : [] }
          : null;
        return { activeJar: jar, cabinet: [], itemRates: old.itemRates || {} };
      }
    } catch (e) { /* 손상 시 초기화 */ }
    return { activeJar: null, cabinet: [], itemRates: {} };
  }
  function normJar(j) {
    if (!j || !j.productId) return null;
    j.savings = Array.isArray(j.savings) ? j.savings : [];
    if (!j.id) j.id = uid();
    return j;
  }
  function save() { localStorage.setItem(STORE_KEY, JSON.stringify(state)); }

  const $ = id => document.getElementById(id);
  const rateOf = item => (state.itemRates[item.id] != null ? state.itemRates[item.id] : item.rate);
  const jar = () => state.activeJar;
  const jarTotal = () => (jar() ? jar().savings.reduce((s, e) => s + e.amount, 0) : 0);
  const floorOf = pid => floors.find(f => String(f.product_id) === String(pid)) || null;

  function vibrate(ms){ try { navigator.vibrate && navigator.vibrate(ms); } catch(e){} }

  // ── 토스트 ──
  let toastTimer;
  function toast(msg){
    const t = $('toast');
    t.textContent = msg; t.hidden = false;
    requestAnimationFrame(() => t.classList.add('show'));
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => {
      t.classList.remove('show');
      setTimeout(() => { t.hidden = true; }, 220);
    }, 1600);
  }

  // ── 숫자 카운트업 ──
  function countUp(el, from, to){
    const dur = 420, t0 = performance.now();
    function frame(now){
      const p = Math.min(1, (now - t0) / dur);
      const eased = 1 - Math.pow(1 - p, 3);
      el.textContent = KRW.format(Math.round(from + (to - from) * eased));
      if (p < 1) requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);
  }

  // ── 기간 합계(활성 적금통 기준) ──
  function weekStart(){ const d=new Date(); const day=(d.getDay()+6)%7; d.setHours(0,0,0,0); d.setDate(d.getDate()-day); return d.getTime(); }
  function monthStart(){ const d=new Date(); return new Date(d.getFullYear(), d.getMonth(), 1).getTime(); }
  const sumSince = ts => (jar() ? jar().savings.filter(e => e.ts >= ts).reduce((s,e)=>s+e.amount,0) : 0);

  // ── 렌더: 합계 ──
  function renderTotal(animateFrom){
    const tot = jarTotal();
    if (animateFrom != null) countUp($('totalAmount'), animateFrom, tot);
    else $('totalAmount').textContent = KRW.format(tot);
    $('weekAmount').textContent = won(sumSince(weekStart()));
    $('monthAmount').textContent = won(sumSince(monthStart()));
    $('undoLast').hidden = !(jar() && jar().savings.length);
    $('totalLabel').textContent = jar() ? '이 적금통에 모은 돈' : '적금통을 만들어 시작하세요';
    // 캐비닛 배지
    const co = $('cabinetOpen');
    co.hidden = state.cabinet.length === 0;
    $('cabinetCount').textContent = state.cabinet.length;
  }

  // ── 렌더: 목표(적금통) 카드 ──
  function renderGoal(){
    const j = jar();
    if (!j){
      $('goalBody').hidden = true;
      $('goalCreate').hidden = false;
      const hint = $('gcCabinetHint');
      if (state.cabinet.length){
        hint.hidden = false;
        hint.innerHTML = `지금까지 <b>${state.cabinet.length}병</b> 적금 완료 🏆`;
      } else hint.hidden = true;
      return;
    }
    $('goalCreate').hidden = true;
    $('goalBody').hidden = false;
    $('goalName').textContent = j.name;
    const floor = floorOf(j.productId);
    const tot = jarTotal();
    const target = floor ? floor.floor_krw : 0;
    const pct = Math.min(100, target > 0 ? (tot / target) * 100 : 0);
    const fill = $('progressFill');
    fill.style.width = pct.toFixed(1) + '%';
    $('goalPct').textContent = Math.floor(pct) + '%';
    $('goalFloor').textContent = floor ? won(target) : '가격 정보 없음';
    $('goalCollected').textContent = floor && floor.collected_at ? `· ${floor.collected_at} 수집 기준값` : '';
    const remain = Math.max(0, target - tot);
    const done = target > 0 && remain <= 0;
    $('goalRemain').textContent = !floor ? '—' : (done ? '달성! 🎉' : won(remain));
    fill.classList.toggle('done', done);
    // 달성 → 사러가기 + 구매완료(다음 목표)
    const row = $('goalAchieved');
    row.hidden = !done;
    const cta = $('ctaBuy');
    if (done && floor && floor.dailyshot_url){ cta.hidden = false; cta.href = floor.dailyshot_url; }
    else cta.hidden = true;
  }

  // ── 렌더: 항목 그리드 ──
  function renderGrid(){
    const grid = $('itemGrid');
    grid.innerHTML = '';
    SEED_ITEMS.forEach(item => {
      const r = rateOf(item);
      const tile = document.createElement('button');
      tile.type = 'button';
      tile.className = 'tile';
      tile.dataset.id = item.id;
      tile.innerHTML =
        `<span class="emoji">${item.emoji}</span>` +
        `<span class="label">${item.label}</span>` +
        `<span class="rate">${item.prompt ? '금액 입력' : '+' + won(r)}</span>`;
      grid.appendChild(tile);
    });
  }

  // ── 적립 로그(활성 적금통에) ──
  function logSaving(item, amount){
    if (!amount || amount <= 0) return;
    if (!jar()){ // 목표 없으면 먼저 정하게
      toast('먼저 목표를 정해 주세요');
      openSheet('goalSheet'); renderGoalList();
      return;
    }
    const before = jarTotal();
    jar().savings.push({ ts: Date.now(), itemId: item.id, amount });
    save();
    renderTotal(before);
    renderGoal();
    vibrate(15);
    toast(`${item.emoji} ${item.label} +${won(amount)}`);
    const tile = document.querySelector(`.tile[data-id="${item.id}"]`);
    if (tile){ tile.classList.remove('pulse'); void tile.offsetWidth; tile.classList.add('pulse'); }
    maybeCelebrate();
  }

  function maybeCelebrate(){
    const j = jar(); if (!j) return;
    const floor = floorOf(j.productId);
    if (floor && jarTotal() >= floor.floor_krw && floor.floor_krw > 0){
      if (!celebrated){ celebrated = true; vibrate([20,40,20]); toast('🎉 목표 달성! 사러 가거나 다음 목표로'); }
    } else celebrated = false;
  }

  // ── 되돌리기(활성 적금통) ──
  function undoEntry(ts){
    if (!jar()) return;
    const before = jarTotal();
    jar().savings = jar().savings.filter(e => e.ts !== ts);
    celebrated = false; save();
    renderTotal(before); renderGoal(); renderHistory();
    vibrate(10); toast('↺ 되돌렸어요');
  }
  function undoLast(){
    if (!jar() || !jar().savings.length) return;
    undoEntry(jar().savings[jar().savings.length - 1].ts);
  }

  // ── 목표 설정 / 변경 (적금통 retarget — 적립금 유지) ──
  function setGoal(f){
    if (jar()){
      jar().productId = f.product_id; jar().name = f.name;
    } else {
      state.activeJar = { id: uid(), productId: f.product_id, name: f.name, createdAt: Date.now(), savings: [] };
    }
    celebrated = false; save();
    renderGoal(); renderTotal();
    closeSheet('goalSheet'); vibrate(12); toast(`목표: ${f.name}`); maybeCelebrate();
  }

  // ── 구매 완료 → 캐비닛 보관 + 새 적금통(다음 목표) ──
  function redeem(){
    const j = jar(); if (!j) return;
    const floor = floorOf(j.productId);
    if (!window.confirm(`${j.name} 구매 완료로 처리할까요?\n이 적금통은 캐비닛에 보관되고, 새 목표를 시작합니다.`)) return;
    state.cabinet.unshift({
      id: j.id, productId: j.productId, name: j.name,
      createdAt: j.createdAt, redeemedAt: Date.now(),
      savedTotal: jarTotal(), floorAtRedeem: floor ? floor.floor_krw : null,
    });
    state.activeJar = null; celebrated = false; save();
    renderGoal(); renderTotal();
    vibrate([15,30,15]); toast('🏆 캐비닛에 보관! 다음 목표를 정하세요');
    openSheet('goalSheet'); renderGoalList();
  }

  // ── 시트 헬퍼 ──
  const openSheet = id => { $(id).hidden = false; };
  const closeSheet = id => { $(id).hidden = true; };

  // ── 홈 화면에 추가 (A2HS / PWA install) — CMPA-357 ──
  const isStandalone = () =>
    (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
    window.navigator.standalone === true;            // iOS Safari standalone
  const isIOS = () =>
    /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;

  let deferredPrompt = null;                          // beforeinstallprompt 보관
  function setupInstall(){
    const btn = $('installBtn');
    if (!btn) return;
    if (isStandalone()) { btn.hidden = true; return; } // 이미 설치/실행 → 버튼 불필요

    // Android/Chrome: 설치 가능 신호가 오면 버튼 노출
    window.addEventListener('beforeinstallprompt', e => {
      e.preventDefault();
      deferredPrompt = e;
      btn.hidden = false;
    });

    // iOS Safari: beforeinstallprompt 미발생 → 수동 안내 버튼 노출
    if (isIOS()) btn.hidden = false;

    btn.addEventListener('click', async () => {
      vibrate(8);
      if (deferredPrompt){
        deferredPrompt.prompt();
        let outcome = 'dismissed';
        try { ({ outcome } = await deferredPrompt.userChoice); } catch(e){}
        deferredPrompt = null;
        btn.hidden = true;                            // 프롬프트는 1회성
        if (outcome === 'accepted') toast('홈 화면에 추가했어요');
      } else if (isIOS()){
        openSheet('iosInstallSheet');                 // 수동 안내 모달
      }
    });

    // 설치 완료 → 버튼/안내 정리 + 토스트
    window.addEventListener('appinstalled', () => {
      deferredPrompt = null;
      btn.hidden = true;
      closeSheet('iosInstallSheet');
      vibrate([20,40,20]);
      toast('홈 화면에 추가됐어요');
    });
  }

  // ── 목표 선택 시트 ──
  function renderGoalList(){
    const box = $('goalList');
    box.innerHTML = '';
    if (!floors.length){ box.innerHTML = '<p class="hist-empty">floor 데이터를 불러오지 못했습니다.</p>'; return; }
    const curId = jar() ? jar().productId : null;
    floors.forEach(f => {
      const row = document.createElement('button');
      row.type = 'button';
      row.className = 'pick-row' + (String(curId)===String(f.product_id) ? ' sel' : '');
      row.innerHTML =
        `<span><span class="pr-name">${f.name}</span><br><span class="pr-date">${f.collected_at||''} 기준</span></span>` +
        `<span class="pr-floor">${won(f.floor_krw)}</span>`;
      row.addEventListener('click', () => setGoal(f));
      box.appendChild(row);
    });
  }

  // ── 캐비닛(완료한 목표) 시트 ──
  function renderCabinet(){
    const box = $('cabinetList');
    box.innerHTML = '';
    if (!state.cabinet.length){ box.innerHTML = '<p class="hist-empty">아직 완료한 목표가 없어요.<br>첫 한 병을 채워보세요 🥃</p>'; return; }
    state.cabinet.forEach(c => {
      const d = new Date(c.redeemedAt);
      const date = `${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,'0')}.${String(d.getDate()).padStart(2,'0')}`;
      const row = document.createElement('div'); row.className = 'cab-row';
      row.innerHTML =
        `<span class="cab-emoji">🥃</span>` +
        `<span class="cab-main"><span class="cab-name">${c.name}</span>` +
        `<span class="cab-meta">${date} 완료 · ${won(c.savedTotal)} 모음</span></span>`;
      box.appendChild(row);
    });
  }

  // ── 단가 편집 ──
  function openRateEdit(item){
    rateEdit = { itemId:item.id, value: rateOf(item) };
    $('rateTitle').textContent = `${item.emoji} ${item.label} 단가`;
    $('rateVal').textContent = KRW.format(rateEdit.value);
    openSheet('rateSheet');
  }
  function stepRate(delta){
    if (!rateEdit) return;
    rateEdit.value = Math.max(0, rateEdit.value + delta);
    $('rateVal').textContent = KRW.format(rateEdit.value);
    vibrate(8);
  }
  function saveRate(){
    if (!rateEdit) return;
    state.itemRates[rateEdit.itemId] = rateEdit.value;
    save(); renderGrid(); closeSheet('rateSheet');
    toast('단가 저장됨');
  }

  // ── 히스토리(활성 적금통) ──
  function renderHistory(){
    const box = $('historyList');
    box.innerHTML = '';
    const list = jar() ? jar().savings : [];
    if (!list.length){ box.innerHTML = '<p class="hist-empty">아직 적립 내역이 없어요.<br>아래 버튼을 눌러 시작하세요.</p>'; return; }
    const byDay = {};
    [...list].reverse().forEach(e => {
      const d = new Date(e.ts);
      const key = `${d.getFullYear()}.${String(d.getMonth()+1).padStart(2,'0')}.${String(d.getDate()).padStart(2,'0')}`;
      (byDay[key] = byDay[key] || []).push(e);
    });
    Object.keys(byDay).forEach(day => {
      const h = document.createElement('div'); h.className='hist-day'; h.textContent = day; box.appendChild(h);
      byDay[day].forEach(e => {
        const item = SEED_ITEMS.find(i => i.id === e.itemId) || {emoji:'•', label:e.itemId};
        const row = document.createElement('div'); row.className='hist-row';
        row.innerHTML = `<span class="he">${item.emoji}</span><span class="hl">${item.label}</span><span class="ha">+${won(e.amount)}</span>`;
        const ub = document.createElement('button'); ub.className='hu'; ub.type='button'; ub.setAttribute('aria-label','되돌리기'); ub.textContent='↺';
        ub.addEventListener('click', () => undoEntry(e.ts));
        row.appendChild(ub); box.appendChild(row);
      });
    });
  }

  // ── 금액 입력형 항목(충동구매 참기) ──
  function promptAmount(item){
    const v = window.prompt('아낀 금액(원)을 입력하세요', '');
    if (v == null) return;
    const n = parseInt(String(v).replace(/[^0-9]/g,''), 10);
    if (!isNaN(n) && n > 0) logSaving(item, n);
  }

  // ── 이벤트 바인딩 ──
  function bindGridGestures(){
    const grid = $('itemGrid');
    const MOVE_TOL = 10;   // px — 이보다 손가락이 움직이면 '탭'이 아니라 '스크롤'로 본다
    let pressTimer, longFired = false, moved = false, pressing = false, sx = 0, sy = 0;
    // CMPA-408: 터치스크린은 touch* 이벤트 처리 직후 호환용 합성 마우스 이벤트(mousedown/mouseup)를
    // ~300ms 뒤에 또 쏜다. 가드 없이는 한 번 탭에 endPress 가 2회 발화 → 적립 2건(보드 신고 CMPA-407).
    // 최근 터치 타임스탬프를 기록하고, 마우스 계열 핸들러는 직후(700ms 내)면 무시한다.
    let lastTouchTs = 0;
    const TOUCH_GUARD_MS = 700;
    const isSyntheticMouse = e => e.type.startsWith('mouse') && (Date.now() - lastTouchTs) < TOUCH_GUARD_MS;
    const itemFromEvt = e => {
      const tile = e.target.closest('.tile'); if (!tile) return null;
      return SEED_ITEMS.find(i => i.id === tile.dataset.id) || null;
    };
    const pt = e => (e.touches && e.touches[0]) || (e.changedTouches && e.changedTouches[0]) || e;
    const startPress = e => {
      if (e.type.startsWith('touch')) lastTouchTs = Date.now();
      else if (isSyntheticMouse(e)) return;             // 합성 마우스 → 터치가 이미 처리함
      const item = itemFromEvt(e); if (!item) return;
      longFired = false; moved = false; pressing = true;
      const p = pt(e); sx = p.clientX; sy = p.clientY;
      pressTimer = setTimeout(() => {
        if (moved) return;                              // 스크롤 중이면 길게누름 발동 안 함
        longFired = true; vibrate(20); openRateEdit(item);
      }, 450);
    };
    const movePress = e => {                            // 임계치 넘으면 스크롤로 간주 → 탭 취소
      if (isSyntheticMouse(e)) return;
      if (!pressing) return;
      const p = pt(e);
      if (Math.abs(p.clientX - sx) > MOVE_TOL || Math.abs(p.clientY - sy) > MOVE_TOL){
        moved = true; clearTimeout(pressTimer);
      }
    };
    const endPress = e => {
      if (isSyntheticMouse(e)) return;                  // 합성 마우스 mouseup → 중복 적립 방지
      clearTimeout(pressTimer); pressing = false;
      const item = itemFromEvt(e); if (!item) return;
      if (moved){ moved = false; return; }             // 스크롤 → 탭(적립/목표팝업) 무시
      if (longFired){ longFired = false; return; }     // 길게 누름 → 단가편집만
      if (item.prompt) promptAmount(item);
      else logSaving(item, rateOf(item));
    };
    const cancelPress = e => {
      if (e && isSyntheticMouse(e)) return;
      clearTimeout(pressTimer); pressing = false; moved = false;
    };
    grid.addEventListener('touchstart', startPress, {passive:true});
    grid.addEventListener('touchmove', movePress, {passive:true});
    grid.addEventListener('touchend', endPress);
    grid.addEventListener('touchcancel', cancelPress);
    grid.addEventListener('mousedown', startPress);
    grid.addEventListener('mousemove', movePress);
    grid.addEventListener('mouseup', endPress);
    grid.addEventListener('mouseleave', cancelPress);
    grid.addEventListener('contextmenu', e => e.preventDefault());
  }

  function bind(){
    bindGridGestures();
    $('createGoalBtn').addEventListener('click', () => { renderGoalList(); openSheet('goalSheet'); });
    $('goalPick').addEventListener('click', () => { renderGoalList(); openSheet('goalSheet'); });
    $('ctaRedeem').addEventListener('click', redeem);
    $('undoLast').addEventListener('click', undoLast);
    $('historyOpen').addEventListener('click', () => { renderHistory(); openSheet('historySheet'); });
    $('cabinetOpen').addEventListener('click', () => { renderCabinet(); openSheet('cabinetSheet'); });
    $('rateMinus').addEventListener('click', () => stepRate(-500));
    $('ratePlus').addEventListener('click', () => stepRate(500));
    $('rateSave').addEventListener('click', saveRate);
    document.querySelectorAll('[data-close]').forEach(b =>
      b.addEventListener('click', () => closeSheet(b.dataset.close)));
    document.querySelectorAll('.sheet-backdrop').forEach(bd =>
      bd.addEventListener('click', e => { if (e.target === bd) bd.hidden = true; }));
  }

  // ── floor 데이터 로드 ──
  async function loadFloors(){
    try {
      const res = await fetch('./whisky_floor.json', { cache:'no-store' });
      const data = await res.json();
      floors = Array.isArray(data) ? data : (data.items || data.floors || data.whiskies || []);
    } catch (e) {
      floors = [];
      toast('floor 데이터를 불러오지 못했어요');
    }
    renderGoal();
  }

  // ── 초기화 ──
  function init(){
    renderGrid();
    renderTotal();
    renderGoal();
    bind();
    setupInstall();
    loadFloors();
    if ('serviceWorker' in navigator){
      navigator.serviceWorker.register('./sw.js').catch(() => {});
    }
  }
  init();
})();
