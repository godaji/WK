/* DreamJar2 — 단일 화면 앱 로직
   구조: JAR 섹션 + CONTROL 섹션 (탭 없음)
   S4 방식: 즉시 적립 + 되돌리기 5초 타이머 */

(() => {
  'use strict';

  // ── 스토리지 키 ──
  const KEY_USER_ID    = 'dreamjar2.userId';
  const KEY_SCRIPT_URL = 'dreamjar2.scriptUrl';
  const KEY_ACTIVE_JAR = 'dreamjar2.activeJarId';

  // ── 상태 ──
  let userId    = localStorage.getItem(KEY_USER_ID) || '';
  const DEFAULT_SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbzrf9M_9x2m8cA2nvv0b0CWKEGNp5Ym2SLV2rJ7ADx79t1ePRbY0yF4wyLdcDU4_nMS/exec';
  let scriptUrl = localStorage.getItem(KEY_SCRIPT_URL) || DEFAULT_SCRIPT_URL;

  // 캐시
  let cachedJars   = [];   // [{jarId, name, currentAmount, goalAmount, ...}]
  let currentJar   = null; // 현재 선택된 Jar
  let entryRows    = [];   // 현재 Jar 이력 (type === 'entry')

  // S4 적립 상태
  let _pendingItem  = null;
  let _pendingEntry = null;

  // ── Mock 데이터 (Apps Script URL 없을 때) ──
  const MOCK_JARS = [
    { jarId: 'mock-1', name: '제주 여행 경비', description: '2026년 가을 제주 3박 4일', ownerId: '__me__', controlId: 'ctrl_ca', memberId: 'm-mock-1', goalAmount: 500000, currentAmount: 127000, recentSevenDayTotal: 35000, entryCount: 8 },
    { jarId: 'mock-2', name: '새 노트북 구매', description: 'M4 맥북 에어 목표', ownerId: 'friend-id', controlId: '', memberId: 'm-mock-2', goalAmount: 2000000, currentAmount: 450000, recentSevenDayTotal: 0, entryCount: 15 },
  ];
  const MOCK_ENTRIES = {
    'mock-1': [
      { entryId: 'e1', amount: 20000, note: '드라마 정주행 대신 저축', createdAt: '2026-07-09T10:00:00Z' },
      { entryId: 'e2', amount: 15000, note: '점심 도시락 싸온 것', createdAt: '2026-07-08T12:30:00Z' },
    ],
    'mock-2': [
      { entryId: 'e3', amount: 50000, note: '충동구매 참기', createdAt: '2026-07-07T18:00:00Z' },
    ],
  };
  const MOCK_DONATIONS_IN  = [];
  const MOCK_DONATIONS_OUT = [];

  // ── Admin Control 템플릿 ──
  const ADMIN_CONTROLS = [
    {
      controlId: 'ctrl_ca',
      name: 'DaeunControl',
      emoji: '⭐',
      items: [
        { id:'ca_eal',        label:'EAL 졸업',          type:'milestone',   subtype:'tier',
          tiers:[{label:'상위 달성',amount:500000},{label:'달성',amount:300000}], once:true },
        { id:'ca_barracudas', label:'바라쿠다스 합격',   type:'milestone',   subtype:'once',
          amount:200000, once:true },
        { id:'ca_math',       label:'수학 성적',          type:'academic',    subtype:'threshold',
          thresholds:[{min:95,amount:200000},{min:80,amount:100000}] },
        { id:'ca_sci',        label:'과학 성적',          type:'academic',    subtype:'threshold',
          thresholds:[{min:95,amount:200000},{min:80,amount:100000}] },
        { id:'ca_swim_perf',  label:'수영 1초 단축',     type:'performance', subtype:'session',
          amount:50000 },
        { id:'ca_commute',    label:'등하교',             type:'routine', subtype:'per_day', amount:1000 },
        { id:'ca_eng_hw',     label:'영어 과제',          type:'routine', subtype:'per_day', amount:1000 },
        { id:'ca_book',       label:'독후감',             type:'routine', subtype:'per_day', amount:5000 },
        { id:'ca_eng_class',  label:'영어학원',           type:'routine', subtype:'per_day', amount:1000 },
        { id:'ca_math_class', label:'수학학원',           type:'routine', subtype:'per_day', amount:1000 },
        { id:'ca_art_class',  label:'미술학원',           type:'routine', subtype:'per_day', amount:1000 },
        { id:'ca_swim_class', label:'수영학원',           type:'routine', subtype:'per_day', amount:1000 },
        { id:'ca_morn_swim',  label:'아침수영',           type:'routine', subtype:'per_day', amount:1000 },
        { id:'ca_math_test',  label:'수학학원 시험 90↑',  type:'academic', subtype:'threshold',
          thresholds:[{min:90,amount:10000}] },
      ],
    },
    {
      controlId: 'ctrl_cb',
      name: 'DadControl',
      emoji: '💰',
      items: [
        { id:'cb_coffee',   label:'드립커피',     type:'routine', subtype:'per_day', amount:4500 },
        { id:'cb_tumbler',  label:'텀블러',        type:'routine', subtype:'per_day', amount:1200 },
        { id:'cb_transit',  label:'도보/대중교통', type:'routine', subtype:'per_day', amount:5000 },
        { id:'cb_homemeal', label:'집밥',          type:'routine', subtype:'per_day', amount:8000 },
      ],
    },
  ];

  // ── DOM 헬퍼 ──
  const $ = id => document.getElementById(id);
  const KRW = new Intl.NumberFormat('ko-KR');
  const won = n => KRW.format(Math.round(n || 0)) + '원';
  const isMock = () => !scriptUrl;

  function todayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`;
  }
  function fmtDate(iso) {
    if (!iso) return '';
    try { const d = new Date(iso); return `${d.getMonth()+1}/${d.getDate()}`; } catch { return ''; }
  }
  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;').replace(/</g, '&lt;')
      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
  }

  // ── 토스트 ──
  let _toastTimer = null;
  function toast(msg) {
    const el = $('toast');
    el.textContent = msg;
    el.hidden = false;
    el.classList.add('show');
    if (_toastTimer) clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => {
      el.classList.remove('show');
      setTimeout(() => { el.hidden = true; }, 220);
    }, 2000);
  }

  // ── 되돌리기 토스트 ──
  let _undoTimer    = null;
  let _undoCountdown = null;
  let _undoState    = null;  // { jarId, entryId, amount }

  function showUndoToast(jarId, entryId, amount) {
    _undoState = { jarId, entryId, amount };
    const el    = $('undoToast');
    const label = $('undoToastLabel');
    const btn   = $('undoToastBtn');
    let sec = 5;
    label.textContent = `+${won(amount)} 적립`;
    btn.textContent = `되돌리기 (${sec}초)`;
    el.hidden = false;
    el.classList.add('show');
    if (_undoTimer)     clearTimeout(_undoTimer);
    if (_undoCountdown) clearInterval(_undoCountdown);
    _undoCountdown = setInterval(() => {
      sec -= 1;
      if (sec <= 0) { clearInterval(_undoCountdown); _undoCountdown = null; }
      else btn.textContent = `되돌리기 (${sec}초)`;
    }, 1000);
    _undoTimer = setTimeout(() => dismissUndoToast(), 5000);
  }

  function dismissUndoToast() {
    if (_undoTimer)     { clearTimeout(_undoTimer);    _undoTimer    = null; }
    if (_undoCountdown) { clearInterval(_undoCountdown); _undoCountdown = null; }
    _undoState = null;
    const el = $('undoToast');
    if (!el) return;
    el.classList.remove('show');
    setTimeout(() => { el.hidden = true; }, 220);
  }

  $('undoToastBtn').addEventListener('click', async () => {
    const state = _undoState;
    if (!state) return;
    dismissUndoToast();
    try {
      await apiFetch({ action: 'deleteEntry', params: { jarId: state.jarId, entryId: state.entryId } });
      if (currentJar && currentJar.jarId === state.jarId) {
        currentJar.currentAmount = Math.max(0, (currentJar.currentAmount || 0) - state.amount);
        updateJarDisplay(currentJar);
      }
      cachedJars = [];
      toast('적립이 취소되었습니다.');
      await reloadEntries(state.jarId);
    } catch (err) {
      toast('되돌리기 실패: ' + err.message);
    }
  });

  // ── API 레이어 ──
  async function apiFetch({ action, query, params = {} }) {
    if (isMock()) return mockResponse({ action, query, params });
    try {
      if (action) {
        const res = await fetch(scriptUrl, {
          method: 'POST',
          headers: { 'Content-Type': 'text/plain' },
          body: JSON.stringify({ action, ...params }),
        });
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (!json.ok) throw new Error(json.error || '서버 오류');
        return json.data;
      } else {
        const url = new URL(scriptUrl);
        url.searchParams.set('query', query);
        Object.entries(params).forEach(([k, v]) => url.searchParams.set(k, v));
        const res = await fetch(url.toString());
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        const json = await res.json();
        if (!json.ok) throw new Error(json.error || '서버 오류');
        return json.data;
      }
    } catch (err) {
      console.error('[DreamJar2] apiFetch 오류:', err);
      throw err;
    }
  }

  function mockResponse({ action, query, params }) {
    if (query === 'getJarsByUser') {
      return Promise.resolve(MOCK_JARS.map(j => ({
        ...j, ownerId: j.ownerId === '__me__' ? userId : (j.ownerId || userId),
      })));
    }
    if (query === 'getJar') {
      const jar = MOCK_JARS.find(j => j.jarId === params.jarId);
      if (!jar) return Promise.reject(new Error('Jar 없음'));
      const entries  = MOCK_ENTRIES[params.jarId] || [];
      const dIn      = MOCK_DONATIONS_IN.filter(d => d.toJarId === params.jarId);
      const dOut     = MOCK_DONATIONS_OUT.filter(d => d.fromJarId === params.jarId);
      const entrySum = entries.reduce((s, e) => s + (Number(e.amount) || 0), 0);
      const dInSum   = dIn.reduce((s, d) => s + (Number(d.netAmount) || 0), 0);
      const dOutSum  = dOut.reduce((s, d) => s + (Number(d.requestAmount) || 0), 0);
      return Promise.resolve({ ...jar, ownerId: jar.ownerId || userId, currentAmount: entrySum + dInSum - dOutSum });
    }
    if (query === 'getJarHistory') {
      const jarId = params.jarId;
      const entries = MOCK_ENTRIES[jarId] || [];
      const dIn = MOCK_DONATIONS_IN.filter(d => d.toJarId === jarId);
      const history = [
        ...entries.map(e => ({
          type: 'entry', id: e.entryId, date: e.createdAt,
          userId: userId, contributorName: '나',
          label: e.note || '적립', amount: Number(e.amount) || 0, icon: '💰',
        })),
        ...dIn.map(d => ({
          type: 'donation', id: d.donationId, date: d.createdAt,
          userId: '', contributorName: '(기부 Jar)',
          label: '기부', amount: Number(d.netAmount) || 0, icon: '🦝',
        })),
      ].sort((a, b) => (b.date > a.date ? 1 : -1));
      return Promise.resolve({ history, memberSubtotals: [] });
    }
    if (action === 'createJar') {
      const newJar = {
        jarId: 'mock-' + Date.now(), name: params.name,
        description: params.description || '', ownerId: params.ownerId || userId,
        goalAmount: Number(params.goalAmount) || 0, currentAmount: 0,
        recentSevenDayTotal: 0, entryCount: 0, controlId: '', memberId: 'm-' + Date.now(),
      };
      MOCK_JARS.unshift(newJar);
      return Promise.resolve({ jarId: newJar.jarId });
    }
    if (action === 'addEntry') {
      const entry = {
        entryId: 'e-' + Date.now(), jarId: params.jarId,
        amount: Number(params.amount), note: params.note || '',
        createdAt: new Date().toISOString(),
      };
      if (!MOCK_ENTRIES[params.jarId]) MOCK_ENTRIES[params.jarId] = [];
      MOCK_ENTRIES[params.jarId].unshift(entry);
      const jar = MOCK_JARS.find(j => j.jarId === params.jarId);
      if (jar) { jar.currentAmount += entry.amount; jar.recentSevenDayTotal = (jar.recentSevenDayTotal || 0) + entry.amount; jar.entryCount += 1; }
      return Promise.resolve({ entryId: entry.entryId });
    }
    if (action === 'deleteEntry') {
      const { jarId, entryId } = params;
      if (jarId && MOCK_ENTRIES[jarId]) {
        const idx = MOCK_ENTRIES[jarId].findIndex(e => e.entryId === entryId);
        if (idx >= 0) {
          const removed = MOCK_ENTRIES[jarId].splice(idx, 1)[0];
          const jar = MOCK_JARS.find(j => j.jarId === jarId);
          if (jar && removed) { jar.currentAmount = Math.max(0, (jar.currentAmount || 0) - (Number(removed.amount) || 0)); jar.entryCount = Math.max(0, (jar.entryCount || 1) - 1); }
          return Promise.resolve({ deleted: true });
        }
      }
      return Promise.resolve({ deleted: false });
    }
    if (action === 'setControl') {
      let j = params.memberId ? MOCK_JARS.find(m => m.memberId === params.memberId) : null;
      if (!j && params.jarId) j = MOCK_JARS.find(m => m.jarId === params.jarId);
      if (j) j.controlId = params.controlId || '';
      return Promise.resolve({ updated: true });
    }
    if (action === 'joinJar') return Promise.resolve({ memberId: 'm-' + Date.now() });
    if (action === 'registerUser') return Promise.resolve({ userId: params.userId || userId });
    return Promise.resolve({});
  }

  // ── 설정 화면 ──
  function showSetup() {
    $('setupScreen').hidden = false;
    $('mainApp').hidden = true;
    $('setupUserId').value  = userId;
    $('setupScriptUrl').value = scriptUrl;
    $('setupUserId').focus();
  }
  function hideSetup() {
    $('setupScreen').hidden = true;
    $('mainApp').hidden = false;
  }

  $('setupSaveBtn').addEventListener('click', () => {
    const newId = $('setupUserId').value.trim();
    if (!newId) { toast('사용자 ID를 입력하세요.'); $('setupUserId').focus(); return; }
    userId    = newId;
    scriptUrl = $('setupScriptUrl').value.trim();
    localStorage.setItem(KEY_USER_ID, userId);
    localStorage.setItem(KEY_SCRIPT_URL, scriptUrl);
    hideSetup();
    initApp();
  });

  // ── 시트 공통 ──
  function openSheet(id) { $(id).hidden = false; }
  function closeSheet(id) { $(id).hidden = true; }

  document.querySelectorAll('.sheet-close').forEach(btn => {
    btn.addEventListener('click', () => closeSheet(btn.dataset.close));
  });
  document.querySelectorAll('.sheet-backdrop').forEach(bd => {
    bd.addEventListener('click', e => { if (e.target === bd) closeSheet(bd.id); });
  });

  // ── 설정 시트 ──
  $('settingsBtn').addEventListener('click', () => {
    $('settUserId').value    = userId;
    $('settScriptUrl').value = scriptUrl;
    loadSettJarList();
    openSheet('settingsSheet');
  });

  $('settSaveBtn').addEventListener('click', () => {
    const newId  = $('settUserId').value.trim();
    const newUrl = $('settScriptUrl').value.trim();
    if (!newId) { toast('사용자 ID를 입력하세요.'); return; }
    const changed = (newId !== userId) || (newUrl !== scriptUrl);
    userId    = newId;
    scriptUrl = newUrl;
    localStorage.setItem(KEY_USER_ID, userId);
    localStorage.setItem(KEY_SCRIPT_URL, scriptUrl);
    toast('저장됐어요.');
    if (changed) { cachedJars = []; closeSheet('settingsSheet'); initApp(); }
    else { closeSheet('settingsSheet'); }
  });

  async function loadSettJarList() {
    const listEl = $('settJarList');
    listEl.innerHTML = '<p class="sett-jar-loading">불러오는 중…</p>';
    try {
      if (cachedJars.length === 0) {
        cachedJars = await apiFetch({ query: 'getJarsByUser', params: { userId } });
      }
      if (!cachedJars || cachedJars.length === 0) {
        listEl.innerHTML = '<p class="sett-jar-loading">Jar가 없어요.</p>';
        return;
      }
      listEl.innerHTML = cachedJars.map(j => {
        const cur = Number(j.currentAmount) || 0;
        const goal = Number(j.goalAmount) || 0;
        const pct = goal > 0 ? Math.min(100, Math.round(cur / goal * 100)) : 0;
        return `<div class="sett-jar-item">
          <span class="sett-jar-item-name">${escHtml(j.name || '(이름 없음)')}</span>
          <span class="sett-jar-item-amt">${won(cur)}${goal > 0 ? ' · ' + pct + '%' : ''}</span>
        </div>`;
      }).join('');
    } catch (err) {
      listEl.innerHTML = `<p class="sett-jar-loading">불러오기 실패: ${escHtml(err.message)}</p>`;
    }
  }

  // 다른 Jar 참여
  $('joinJarBtn').addEventListener('click', async () => {
    const jarId = $('joinJarId').value.trim();
    if (!jarId) { toast('Jar ID를 입력하세요'); return; }
    $('joinJarBtn').disabled = true;
    try {
      await apiFetch({ action: 'joinJar', params: { jarId, userId } });
      $('joinJarId').value = '';
      toast('참여했습니다!');
      cachedJars = [];
      loadSettJarList();
    } catch (err) {
      toast('참여 실패: ' + err.message);
    } finally {
      $('joinJarBtn').disabled = false;
    }
  });

  // 설정 시트 내 "새 Jar 만들기"
  $('createJarBtnSettings').addEventListener('click', () => {
    closeSheet('settingsSheet');
    openCreateJar();
  });

  // ── Jar 선택 시트 ──
  $('jarChangeBtn').addEventListener('click', openJarPicker);

  function openJarPicker() {
    renderJarPickerList();
    openSheet('jarPickerSheet');
  }

  function renderJarPickerList() {
    const listEl = $('jarPickerList');
    if (!cachedJars || cachedJars.length === 0) {
      listEl.innerHTML = '<p style="color:var(--muted);font-size:14px">Jar가 없어요.</p>';
      return;
    }

    const owned  = cachedJars.filter(j => j.ownerId === userId);
    const joined = cachedJars.filter(j => j.ownerId !== userId);

    let html = '';
    function appendSect(title, list) {
      if (!list.length) return;
      html += `<div class="jar-picker-section-title">${escHtml(title)}</div>`;
      list.forEach(jar => {
        const cur  = Number(jar.currentAmount) || 0;
        const goal = Number(jar.goalAmount)    || 0;
        const pct  = goal > 0 ? Math.min(100, Math.round(cur / goal * 100)) : 0;
        const isActive = currentJar && currentJar.jarId === jar.jarId;
        const progressHtml = goal > 0
          ? `<div class="jpi-progress-wrap"><div class="jpi-progress-bar" style="width:${pct}%"></div></div>`
          : '';
        const goalText = goal > 0 ? won(goal) : '목표 미설정';
        const pctHtml  = goal > 0 ? `<span class="jpi-pct">${pct}%</span>` : '';
        html += `<button class="jar-picker-item${isActive ? ' active' : ''}" data-jar-id="${escHtml(jar.jarId)}" type="button">
          <div class="jpi-name">${escHtml(jar.name || '(이름 없음)')}</div>
          ${progressHtml}
          <div class="jpi-amounts">
            <span class="jpi-cur">${won(cur)}</span>
            <span class="jpi-sep"> / </span>
            <span class="jpi-goal">${goalText}</span>
            ${pctHtml}
          </div>
        </button>`;
      });
    }

    appendSect('내 Jar', owned);
    appendSect('참여 중인 Jar', joined);
    listEl.innerHTML = html;

    listEl.querySelectorAll('.jar-picker-item').forEach(btn => {
      btn.addEventListener('click', () => {
        const jar = cachedJars.find(j => j.jarId === btn.dataset.jarId);
        if (jar) onJarSelect(jar);
      });
    });
  }

  async function onJarSelect(jar) {
    closeSheet('jarPickerSheet');
    currentJar = jar;
    localStorage.setItem(KEY_ACTIVE_JAR, jar.jarId);
    renderJarSection(jar);
    renderControlSection(jar, []);
    // 최신 데이터 + 이력 병렬 로드
    try {
      const [fresh, histData] = await Promise.all([
        apiFetch({ query: 'getJar',        params: { jarId: jar.jarId } }),
        apiFetch({ query: 'getJarHistory', params: { jarId: jar.jarId } }),
      ]);
      currentJar = { ...jar, ...fresh };
      entryRows  = (histData && histData.history || []).filter(r => r.type === 'entry');
      updateJarDisplay(currentJar);
      renderControlSection(currentJar, entryRows);
    } catch (err) {
      toast('Jar 정보 로드 실패: ' + err.message);
    }
  }

  // ── Jar 만들기 ──
  function openCreateJar() {
    $('cjName').value = '';
    $('cjGoal').value = '';
    $('cjDesc').value = '';
    openSheet('createJarSheet');
    setTimeout(() => $('cjName').focus(), 300);
  }

  $('createJarBtnPicker').addEventListener('click', () => {
    closeSheet('jarPickerSheet');
    openCreateJar();
  });

  $('cjSaveBtn').addEventListener('click', async () => {
    const name = $('cjName').value.trim();
    const goal = Number(String($('cjGoal').value).replace(/[^0-9]/g, ''));
    const desc = $('cjDesc').value.trim();
    if (!name) { toast('Jar 이름을 입력하세요.'); $('cjName').focus(); return; }
    if (!goal || goal <= 0) { toast('목표금액을 입력하세요.'); $('cjGoal').focus(); return; }
    $('cjSaveBtn').disabled = true;
    try {
      const res = await apiFetch({ action: 'createJar', params: { name, description: desc, goalAmount: goal, ownerId: userId } });
      closeSheet('createJarSheet');
      toast('Jar를 만들었어요!');
      cachedJars = [];
      // 새 Jar 를 활성화
      const newJar = { jarId: res.jarId, name, description: desc, goalAmount: goal, currentAmount: 0, ownerId: userId, controlId: '', memberId: '' };
      cachedJars = await apiFetch({ query: 'getJarsByUser', params: { userId } });
      const jar = cachedJars.find(j => j.jarId === res.jarId) || newJar;
      onJarSelect(jar);
    } catch (err) {
      toast('Jar 생성 실패: ' + err.message);
    } finally {
      $('cjSaveBtn').disabled = false;
    }
  });

  // "Jar 만들기" 버튼 (Jar 없을 때 표시)
  $('jarCreateBtnEmpty').addEventListener('click', openCreateJar);

  // ── JAR 섹션 렌더 ──
  function renderJarSection(jar) {
    $('jarLoading').hidden = true;
    $('jarEmpty').hidden   = true;
    $('jarDisplay').hidden = false;
    $('mainJarName').textContent = jar.name || '(이름 없음)';
    updateJarDisplay(jar);
  }

  function updateJarDisplay(jar) {
    const cur  = Number(jar.currentAmount) || 0;
    const goal = Number(jar.goalAmount)    || 0;
    $('mainJarCur').textContent  = won(cur);
    $('mainJarGoal').textContent = goal > 0 ? won(goal) : '목표 미설정';
    if (goal > 0) {
      const pct = Math.min(100, Math.round(cur / goal * 100));
      $('mainJarProgressBar').style.width = pct + '%';
      $('mainJarProgressPct').textContent = pct + '%';
      $('mainJarProgressWrap').hidden = false;
      const pred = computePrediction(jar);
      const predEl = $('mainJarPrediction');
      predEl.textContent = pred;
      predEl.className = 'jar-prediction' + (cur >= goal ? ' achieved' : '');
    } else {
      $('mainJarProgressWrap').hidden = true;
      $('mainJarPrediction').textContent = '';
    }
  }

  function computePrediction(jar) {
    const goal = Number(jar.goalAmount)    || 0;
    const cur  = Number(jar.currentAmount) || 0;
    if (goal <= 0) return '';
    if (cur >= goal) return '🎉 목표를 달성했어요!';
    const recentTotal = Number(jar.recentSevenDayTotal) || 0;
    if (recentTotal <= 0) return '아직 적립 내역이 없어요 🪣';
    const dailyAvg   = recentTotal / 7;
    const remaining  = goal - cur;
    const daysNeeded = Math.ceil(remaining / dailyAvg);
    const targetDate = new Date(Date.now() + daysNeeded * 86400000);
    return `📅 ${daysNeeded}일 후 달성 예정 (${targetDate.toISOString().slice(0, 10)})`;
  }

  // ── CONTROL 섹션 렌더 ──
  function renderControlSection(jar, entries) {
    if (!jar) {
      $('controlDisplay').hidden = true;
      $('controlEmpty').hidden   = false;
      return;
    }
    const ctrl = ADMIN_CONTROLS.find(c => c.controlId === jar.controlId);
    $('controlEmpty').hidden   = true;
    $('controlDisplay').hidden = false;

    if (ctrl) {
      $('mainCtrlName').textContent = ctrl.emoji + ' ' + ctrl.name;
      $('mainRewardSection').hidden = false;
      renderRewardButtons(ctrl, entries || [], $('mainRewardList'));
    } else {
      $('mainCtrlName').textContent = '선택 안 됨';
      $('mainRewardSection').hidden = true;
    }
  }

  function renderRewardButtons(ctrl, entries, listEl) {
    // once 아이템 적립 여부 체크
    const claimedIds = new Set();
    (entries || []).forEach(e => {
      const src = e.label || e.note || '';
      const m   = /^\[([\w]+)\]/.exec(src);
      if (m) claimedIds.add(m[1]);
    });

    const ICONS = { milestone: '🏆', academic: '📝', performance: '🏊', routine: '📅' };
    const html = ctrl.items.map(item => {
      const claimed = item.once && claimedIds.has(item.id);
      let amtStr = '';
      if (item.amount) {
        amtStr = won(item.amount);
      } else if (item.tiers) {
        const lo = item.tiers[item.tiers.length - 1].amount;
        amtStr = won(lo) + '~' + won(item.tiers[0].amount);
      } else if (item.thresholds) {
        amtStr = won(item.thresholds[item.thresholds.length - 1].amount) + '+';
      }
      const icon     = ICONS[item.type] || '💰';
      const doneBadge = claimed ? '<span class="rb-done-badge">완료</span>' : '';
      return `<button class="reward-btn${claimed ? ' is-done' : ''}" data-item-id="${escHtml(item.id)}" type="button"${claimed ? ' disabled' : ''}>` +
        `<span class="rb-icon">${icon}</span>` +
        `<span class="rb-label">${escHtml(item.label)}</span>` +
        `<span class="rb-amount">${escHtml(amtStr)}</span>` +
        doneBadge +
        `</button>`;
    }).join('');

    listEl.innerHTML = html;

    listEl.querySelectorAll('.reward-btn:not([disabled])').forEach(btn => {
      const item = ctrl.items.find(i => i.id === btn.dataset.itemId);
      if (!item) return;
      // 탭 → 즉시 적립
      btn.addEventListener('click', () => onRewardTap(item));
      // 길게 누르기 → 상세 옵션 모달
      let _lp = null;
      btn.addEventListener('pointerdown', () => {
        _lp = setTimeout(() => {
          _lp = null;
          if (item.subtype === 'per_day') openRoutineOptions(item);
          else if (item.subtype === 'session') {
            _pendingItem = item;
            $('routinePickerTitle').textContent = item.label;
            $('sessionCount').textContent = '1';
            document.querySelectorAll('.rt-tab-btn').forEach(b => { b.hidden = (b.dataset.rtTab !== 'rt-session'); });
            switchRoutineTab('rt-session');
            openSheet('routineSheet');
          } else onRewardTap(item);
        }, 500);
      });
      const cancelLp = () => { if (_lp) { clearTimeout(_lp); _lp = null; } };
      btn.addEventListener('pointerup',     cancelLp);
      btn.addEventListener('pointercancel', cancelLp);
      btn.addEventListener('pointermove',   cancelLp);
    });
  }

  // Control 변경 버튼
  $('ctrlChangeBtn').addEventListener('click', openControlPicker);

  function openControlPicker() {
    document.querySelectorAll('.cp-item').forEach(el => {
      el.classList.toggle('active', el.dataset.controlId === (currentJar && currentJar.controlId));
    });
    openSheet('controlPickerSheet');
  }

  document.querySelectorAll('.cp-item').forEach(el => {
    el.addEventListener('click', () => onControlSelect(el.dataset.controlId));
  });

  async function onControlSelect(controlId) {
    const jar = currentJar;
    if (!jar) return;
    try {
      await apiFetch({ action: 'setControl', params: { memberId: jar.memberId || '', controlId, jarId: jar.jarId, userId } });
      jar.controlId = controlId;
      const cached = cachedJars.find(j => j.jarId === jar.jarId);
      if (cached) cached.controlId = controlId;
      closeSheet('controlPickerSheet');
      renderControlSection(jar, entryRows);
      toast('Control을 설정했어요.');
    } catch (err) {
      toast('설정 실패: ' + err.message);
    }
  }

  // ── 즉시 적립 (S4) ──
  async function addEntryImmediate(amount, note) {
    const jar = currentJar;
    if (!jar) return;
    try {
      const res = await apiFetch({ action: 'addEntry', params: { jarId: jar.jarId, userId, amount, note } });
      jar.currentAmount = (jar.currentAmount || 0) + amount;
      updateJarDisplay(jar);
      cachedJars = [];
      showUndoToast(jar.jarId, res && res.entryId, amount);
      await reloadEntries(jar.jarId);
    } catch (err) {
      toast('적립 실패: ' + err.message);
    }
  }

  async function reloadEntries(jarId) {
    try {
      const histData = await apiFetch({ query: 'getJarHistory', params: { jarId } });
      entryRows = (histData && histData.history || []).filter(r => r.type === 'entry');
      if (currentJar && currentJar.jarId === jarId) {
        renderControlSection(currentJar, entryRows);
      }
    } catch { /* 무시 */ }
  }

  // per_day 길게 누르기 → 루틴 옵션 시트
  function openRoutineOptions(item) {
    _pendingItem = item;
    $('routinePickerTitle').textContent = item.label;
    $('rtTodayDesc').textContent = won(item.amount) + ' 적립';
    $('routineDateInput').value = todayStr();
    document.querySelectorAll('.rt-tab-btn').forEach(b => { b.hidden = (b.dataset.rtTab === 'rt-session'); });
    switchRoutineTab('rt-today');
    openSheet('routineSheet');
  }

  function onRewardTap(item) {
    _pendingItem = item;
    if (item.subtype === 'tier') {
      $('tierPickerTitle').textContent = item.label;
      renderTierButtons(item);
      openSheet('tierPickerSheet');
    } else if (item.subtype === 'threshold') {
      $('scorePickerTitle').textContent = item.label + ' 점수 입력';
      $('scoreInput').value = '';
      openSheet('scoreInputSheet');
    } else if (item.subtype === 'per_day') {
      addEntryImmediate(item.amount, `[${item.id}] ${item.label} (${todayStr()})`);
    } else if (item.subtype === 'session') {
      addEntryImmediate(item.amount, `[${item.id}] ${item.label} × 1회`);
    } else {
      addEntryImmediate(item.amount, `[${item.id}] ${item.label}`);
    }
  }

  function renderTierButtons(item) {
    const wrap = $('tierBtnList');
    wrap.innerHTML = item.tiers.map(t =>
      `<button class="tier-select-btn" data-amount="${t.amount}" data-label="${escHtml(t.label)}" type="button">` +
        `<span class="tier-btn-label">${escHtml(t.label)}</span>` +
        `<span class="tier-btn-amount">${won(t.amount)}</span>` +
      `</button>`).join('');
    wrap.querySelectorAll('.tier-select-btn').forEach(btn => {
      btn.addEventListener('click', () => onTierSelect(Number(btn.dataset.amount), btn.dataset.label));
    });
  }

  function onTierSelect(amount, label) {
    const item = _pendingItem;
    closeSheet('tierPickerSheet');
    showEntryConfirm(amount, `${item.label} · ${label}`, `[${item.id}] ${item.label} (${label})`);
  }

  $('scoreSubmitBtn').addEventListener('click', () => {
    const item  = _pendingItem;
    const score = Number($('scoreInput').value);
    if (isNaN(score) || score < 0 || score > 100) { toast('0~100 사이 점수를 입력하세요.'); return; }
    let matched = null;
    for (const t of item.thresholds) { if (score >= t.min) { matched = t; break; } }
    if (!matched) { toast(`${score}점은 보상 기준에 해당하지 않습니다.`); return; }
    closeSheet('scoreInputSheet');
    showEntryConfirm(matched.amount, `${item.label} ${score}점`, `[${item.id}] ${item.label} ${score}점`);
  });

  function switchRoutineTab(tabId) {
    document.querySelectorAll('.rt-tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.rtTab === tabId);
    });
    document.querySelectorAll('.rt-tab-content').forEach(el => {
      el.hidden = el.dataset.rtTab !== tabId;
    });
  }
  document.querySelectorAll('.rt-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => { if (!btn.hidden) switchRoutineTab(btn.dataset.rtTab); });
  });

  $('routineTodayBtn').addEventListener('click', () => {
    const item = _pendingItem;
    closeSheet('routineSheet');
    showEntryConfirm(item.amount, `${item.label} (오늘)`, `[${item.id}] ${item.label} (${todayStr()})`);
  });
  $('routineDateConfirm').addEventListener('click', () => {
    const item = _pendingItem;
    const d    = $('routineDateInput').value || todayStr();
    closeSheet('routineSheet');
    showEntryConfirm(item.amount, `${item.label} (${d})`, `[${item.id}] ${item.label} (${d})`);
  });
  $('sessionDecBtn').addEventListener('click', () => {
    const el = $('sessionCount');
    el.textContent = Math.max(1, (Number(el.textContent) || 1) - 1);
  });
  $('sessionIncBtn').addEventListener('click', () => {
    const el = $('sessionCount');
    el.textContent = (Number(el.textContent) || 1) + 1;
  });
  $('sessionConfirmBtn').addEventListener('click', () => {
    const item  = _pendingItem;
    const count = Math.max(1, Number($('sessionCount').textContent) || 1);
    closeSheet('routineSheet');
    showEntryConfirm(item.amount * count, `${item.label} × ${count}회`, `[${item.id}] ${item.label} × ${count}회`);
  });

  function showEntryConfirm(amount, displayLabel, note) {
    _pendingEntry = { amount, note };
    $('confirmLabel').textContent  = displayLabel;
    $('confirmAmount').textContent = won(amount);
    openSheet('entryConfirmSheet');
  }

  $('entryConfirmBtn').addEventListener('click', async () => {
    const pending = _pendingEntry;
    const jar     = currentJar;
    if (!pending || !jar) return;
    const btn = $('entryConfirmBtn');
    btn.disabled = true;
    try {
      await apiFetch({ action: 'addEntry', params: { jarId: jar.jarId, userId, amount: pending.amount, note: pending.note } });
      jar.currentAmount = (jar.currentAmount || 0) + pending.amount;
      updateJarDisplay(jar);
      closeSheet('entryConfirmSheet');
      toast(`+${won(pending.amount)} 적립 완료!`);
      _pendingEntry = null;
      cachedJars    = [];
      await reloadEntries(jar.jarId);
    } catch (err) {
      toast('적립 실패: ' + err.message);
    } finally {
      btn.disabled = false;
    }
  });

  // ── 앱 초기화 ──
  async function initApp() {
    if (isMock()) console.info('[DreamJar2] Apps Script URL 미설정 → 샘플 데이터 모드');

    // Jar 섹션: 로딩 상태
    $('jarLoading').hidden = false;
    $('jarDisplay').hidden = true;
    $('jarEmpty').hidden   = true;
    $('controlDisplay').hidden = true;
    $('controlEmpty').hidden   = false;

    try {
      cachedJars = await apiFetch({ query: 'getJarsByUser', params: { userId } });

      if (!cachedJars || cachedJars.length === 0) {
        $('jarLoading').hidden = true;
        $('jarEmpty').hidden   = false;
        return;
      }

      // 마지막 선택 Jar 복원 (없으면 첫 번째)
      const savedJarId = localStorage.getItem(KEY_ACTIVE_JAR);
      const jar = (savedJarId && cachedJars.find(j => j.jarId === savedJarId))
        || cachedJars[0];

      currentJar = jar;
      renderJarSection(jar);
      renderControlSection(jar, []);

      // 최신 데이터 + 이력 비동기 로드
      const [fresh, histData] = await Promise.all([
        apiFetch({ query: 'getJar',        params: { jarId: jar.jarId } }),
        apiFetch({ query: 'getJarHistory', params: { jarId: jar.jarId } }),
      ]);
      currentJar = { ...jar, ...fresh };
      entryRows  = (histData && histData.history || []).filter(r => r.type === 'entry');
      updateJarDisplay(currentJar);
      renderControlSection(currentJar, entryRows);

    } catch (err) {
      $('jarLoading').hidden = true;
      $('jarEmpty').hidden   = false;
      toast('불러오기 실패: ' + err.message);
    }
  }

  // ── 진입점 ──
  if (!userId) {
    showSetup();
  } else {
    hideSetup();
    initApp();
  }

})();
