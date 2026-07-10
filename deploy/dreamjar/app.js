/* DreamJar — 단일 화면 앱 로직
   구조: JAR 섹션 + CONTROL 섹션 + HISTORY 섹션 (탭 없음)
   localStorage-first: 모든 데이터는 로컬에 저장. 서버 동기화는 명시적 버튼으로만. */

(() => {
  'use strict';

  // ── 스토리지 키 ──
  const KEY_USER_ID    = 'dreamjar.userId';
  const KEY_SCRIPT_URL = 'dreamjar.scriptUrl';
  const KEY_ACTIVE_JAR = 'dreamjar.activeJarId';
  const KEY_JARS       = 'dreamjar.jars';       // JSON: [{jarId, name, goalAmount, currentAmount, ...}]
  const KEY_ENTRIES    = 'dreamjar.entries';     // JSON: {jarId: [{entryId, amount, note, createdAt, synced}]}
  const KEY_PENDING_DEL = 'dreamjar.pendingDel'; // JSON: [{entryId, jarId}]
  const KEY_PENDING_CTRL = 'dreamjar.pendingCtrl'; // JSON: [{jarId, memberId, controlId}]
  const KEY_PENDING_ARCHIVE = 'dreamjar.pendingArchive'; // JSON: [{jarId}]
  const KEY_LAST_SYNC  = 'dreamjar.lastSync';    // ISO timestamp string

  // ── localStorage 헬퍼 ──
  function localJars() { return JSON.parse(localStorage.getItem(KEY_JARS) || '[]'); }
  function saveLocalJars(jars) { localStorage.setItem(KEY_JARS, JSON.stringify(jars)); }
  function localEntries(jarId) {
    const all = JSON.parse(localStorage.getItem(KEY_ENTRIES) || '{}');
    return all[jarId] || [];
  }
  function saveLocalEntries(jarId, entries) {
    const all = JSON.parse(localStorage.getItem(KEY_ENTRIES) || '{}');
    all[jarId] = entries;
    localStorage.setItem(KEY_ENTRIES, JSON.stringify(all));
  }
  function localPendingDel() { return JSON.parse(localStorage.getItem(KEY_PENDING_DEL) || '[]'); }
  function savePendingDel(list) { localStorage.setItem(KEY_PENDING_DEL, JSON.stringify(list)); }
  function localPendingCtrl() { return JSON.parse(localStorage.getItem(KEY_PENDING_CTRL) || '[]'); }
  function savePendingCtrl(list) { localStorage.setItem(KEY_PENDING_CTRL, JSON.stringify(list)); }
  function localPendingArchive() { return JSON.parse(localStorage.getItem(KEY_PENDING_ARCHIVE) || '[]'); }
  function savePendingArchive(list) { localStorage.setItem(KEY_PENDING_ARCHIVE, JSON.stringify(list)); }

  /** 활성(아카이브되지 않은) Jar만 반환 */
  function activeJars(jars) { return jars.filter(j => !j.archived); }

  // ── 상태 ──
  let userId    = localStorage.getItem(KEY_USER_ID) || '';
  const DEFAULT_SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbx1SF3djcB9kEnpbI_MltdPvtYS7p7ADZ1tnXVKoVTqUtsEgFFy2l11Qxo1TQc0DuSc/exec';
  let scriptUrl = localStorage.getItem(KEY_SCRIPT_URL) || DEFAULT_SCRIPT_URL;

  // 캐시
  let cachedJars   = [];   // [{jarId, name, currentAmount, goalAmount, ...}]
  let currentJar   = null; // 현재 선택된 Jar
  let entryRows    = [];   // 현재 Jar 이력

  // 적립 확인 pending
  let _pendingItem  = null;
  let _pendingEntry = null;

  // 탭 상태 (DaeunControl 이벤트/루틴 탭)
  let _activeRewardTab = 'routine'; // 'routine' | 'event'

  // ── Mock 데이터 (Apps Script URL 없을 때) ──
  const MOCK_JARS = [
    { jarId: 'mock-1', name: '제주 여행 경비', description: '2026년 가을 제주 3박 4일', ownerId: '__me__', controlId: 'ctrl_ca', memberId: 'm-mock-1', goalAmount: 500000, currentAmount: 127000, recentSevenDayTotal: 35000, entryCount: 8 },
    { jarId: 'mock-2', name: '새 노트북 구매', description: 'M4 맥북 에어 목표', ownerId: 'friend-id', controlId: '', memberId: 'm-mock-2', goalAmount: 2000000, currentAmount: 450000, recentSevenDayTotal: 0, entryCount: 15 },
  ];
  const MOCK_ENTRIES = {
    'mock-1': [
      { entryId: 'e1', amount: 20000, note: '드라마 정주행 대신 저축', createdAt: '2026-07-09T10:00:00Z', synced: true },
      { entryId: 'e2', amount: 15000, note: '점심 도시락 싸온 것', createdAt: '2026-07-08T12:30:00Z', synced: true },
    ],
    'mock-2': [
      { entryId: 'e3', amount: 50000, note: '충동구매 참기', createdAt: '2026-07-07T18:00:00Z', synced: true },
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
          tiers:[{label:'상위 달성',amount:500000},{label:'달성',amount:300000}], once:true, tab:'event' },
        { id:'ca_barracudas', label:'바라쿠다스 합격',   type:'milestone',   subtype:'once',
          amount:200000, once:true, tab:'event' },
        { id:'ca_math',       label:'수학 성적',          type:'academic',    subtype:'threshold',
          thresholds:[{min:95,amount:200000},{min:80,amount:100000}], tab:'event' },
        { id:'ca_sci',        label:'과학 성적',          type:'academic',    subtype:'threshold',
          thresholds:[{min:95,amount:200000},{min:80,amount:100000}], tab:'event' },
        { id:'ca_swim_perf',  label:'수영 1초 단축',     type:'performance', subtype:'session',
          amount:50000, tab:'event' },
        { id:'ca_commute',    label:'등하교',             type:'routine', subtype:'per_day', amount:1000, tab:'routine' },
        { id:'ca_eng_hw',     label:'영어 과제',          type:'routine', subtype:'per_day', amount:1000, tab:'routine' },
        { id:'ca_book',       label:'독후감',             type:'routine', subtype:'per_day', amount:5000, tab:'routine' },
        { id:'ca_eng_class',  label:'영어학원',           type:'routine', subtype:'per_day', amount:1000, tab:'routine' },
        { id:'ca_math_class', label:'수학학원',           type:'routine', subtype:'per_day', amount:1000, tab:'routine' },
        { id:'ca_art_class',  label:'미술학원',           type:'routine', subtype:'per_day', amount:1000, tab:'routine' },
        { id:'ca_swim_class', label:'수영학원',           type:'routine', subtype:'per_day', amount:1000, tab:'routine' },
        { id:'ca_morn_swim',  label:'아침수영',           type:'routine', subtype:'per_day', amount:1000, tab:'routine' },
        { id:'ca_math_test',  label:'수학학원 시험 90↑',  type:'academic', subtype:'threshold',
          thresholds:[{min:90,amount:10000}], tab:'routine' },
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

  $('undoToastBtn').addEventListener('click', () => {
    const state = _undoState;
    if (!state) return;
    dismissUndoToast();
    deleteEntryLocal(state.jarId, state.entryId);
  });

  // ── API 레이어 ──
  async function apiFetch({ action, query, params = {} }) {
    if (isMock()) return mockResponse({ action, query, params });
    return apiFetchReal({ action, query, params });
  }

  async function apiFetchReal({ action, query, params = {} }) {
    if (!scriptUrl) throw new Error('Apps Script URL이 설정되지 않았어요.');
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
      console.error('[DreamJar] apiFetch 오류:', err);
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
      const dOut = MOCK_DONATIONS_OUT.filter(d => d.fromJarId === jarId);
      const history = [
        ...entries.map(e => ({
          type: 'entry', id: e.entryId, date: e.createdAt,
          userId: userId, contributorName: '나',
          label: e.note || '적립', amount: Number(e.amount) || 0, icon: '💰',
        })),
        ...dIn.map(d => ({
          type: 'donation_in', id: d.donationId, date: d.createdAt,
          userId: '', contributorName: '(기부 Jar)',
          label: '기부', amount: Number(d.netAmount) || 0, icon: '🦝',
          requestAmount: Number(d.requestAmount) || 0, feeRate: d.feeRate || 0, feeAmount: Number(d.feeAmount) || 0,
        })),
        ...dOut.map(d => {
          const toJar = MOCK_JARS.find(j => j.jarId === d.toJarId);
          return {
            type: 'donation_out', id: d.donationId, date: d.createdAt,
            userId: '', contributorName: (toJar && toJar.name) || d.toJarId || '(알 수 없음)',
            label: '기부 발신 (수수료 ' + Math.round((d.feeRate || 0) * 100) + '%)',
            amount: -(Number(d.requestAmount) || 0), icon: '↗️',
          };
        }),
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
        createdAt: new Date().toISOString(), synced: true,
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
    if (action === 'donate') {
      const requestAmt = Number(params.amount) || 0;
      const feeRate = Math.random() * 0.5;
      const feeAmount = Math.round(requestAmt * feeRate);
      const netAmount = requestAmt - feeAmount;
      const donation = {
        donationId: 'don-' + Date.now(),
        fromJarId: params.fromJarId, toJarId: params.toJarId,
        requestAmount: requestAmt, feeRate, feeAmount, netAmount,
        createdAt: new Date().toISOString(),
      };
      MOCK_DONATIONS_OUT.push(donation);
      MOCK_DONATIONS_IN.push(donation);
      // Update mock jar amounts
      const fromJar = MOCK_JARS.find(j => j.jarId === params.fromJarId);
      if (fromJar) fromJar.currentAmount = Math.max(0, (fromJar.currentAmount || 0) - requestAmt);
      const toJar = MOCK_JARS.find(j => j.jarId === params.toJarId);
      if (toJar) toJar.currentAmount = (toJar.currentAmount || 0) + netAmount;
      return Promise.resolve({ donationId: donation.donationId, feeRate, feeAmount, netAmount });
    }
    if (action === 'archiveJar') {
      const mj = MOCK_JARS.find(j => j.jarId === params.jarId);
      if (mj) { mj.archived = true; mj.archivedAt = new Date().toISOString(); }
      return Promise.resolve({ archived: true });
    }
    if (action === 'joinJar') {
      const input = params.jarId || '';
      const jar = MOCK_JARS.find(j => j.jarId === input) || MOCK_JARS.find(j => j.name === input);
      if (!jar) return Promise.reject(new Error('존재하지 않는 Jar입니다: ' + input));
      return Promise.resolve({ memberId: 'm-' + Date.now(), jarName: jar.name || '' });
    }
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
    updateLastSyncDisplay();
    openSheet('settingsSheet');
  });

  $('logoutBtn').addEventListener('click', () => {
    if (!confirm('로그아웃하시겠습니까?\n로컬 데이터가 모두 삭제됩니다.')) return;
    // localStorage에서 dreamjar 관련 키 모두 삭제
    [KEY_USER_ID, KEY_SCRIPT_URL, KEY_ACTIVE_JAR, KEY_JARS, KEY_ENTRIES,
     KEY_PENDING_DEL, KEY_PENDING_CTRL, KEY_PENDING_ARCHIVE, KEY_LAST_SYNC
    ].forEach(k => localStorage.removeItem(k));
    // 캐시 초기화
    cachedJars = [];
    currentJar = null;
    entryRows  = [];
    userId     = '';
    scriptUrl  = DEFAULT_SCRIPT_URL;
    // 설정 시트 닫고 초기 설정 화면으로
    closeSheet('settingsSheet');
    showSetup();
    toast('로그아웃했어요.');
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

  // 동기화 버튼
  $('syncBtn').addEventListener('click', () => syncWithServer(false));
  $('headerSyncBtn').addEventListener('click', () => syncWithServer(false));

  function updateLastSyncDisplay() {
    const el = $('lastSyncText');
    if (!el) return;
    const ts = localStorage.getItem(KEY_LAST_SYNC);
    if (!ts) { el.textContent = '동기화 안 함'; return; }
    try {
      const d = new Date(ts);
      el.textContent = `마지막 동기화: ${d.getMonth()+1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`;
    } catch { el.textContent = ''; }
  }

  function loadSettJarList() {
    const listEl = $('settJarList');
    const jars = activeJars(localJars());
    if (!jars || jars.length === 0) {
      listEl.innerHTML = '<p class="sett-jar-loading">Jar가 없어요.</p>';
      return;
    }
    listEl.innerHTML = jars.map(j => {
      const cur = Number(j.currentAmount) || 0;
      const goal = Number(j.goalAmount) || 0;
      const pct = goal > 0 ? Math.min(100, Math.round(cur / goal * 100)) : 0;
      return `<div class="sett-jar-item">
        <span class="sett-jar-item-name">${escHtml(j.name || '(이름 없음)')}</span>
        <span class="sett-jar-item-amt">${won(cur)}${goal > 0 ? ' · ' + pct + '%' : ''}</span>
      </div>`;
    }).join('');
  }

  // 다른 Jar 참여
  $('joinJarBtn').addEventListener('click', async () => {
    const jarId = $('joinJarId').value.trim();
    if (!jarId) { toast('Jar ID를 입력하세요'); return; }
    $('joinJarBtn').disabled = true;
    try {
      await apiFetch({ action: 'joinJar', params: { jarId, userId } });
      $('joinJarId').value = '';
      toast('참여 완료! 데이터를 불러옵니다…');
      await syncWithServer(true);
      toast('참여했습니다!');
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

  // ── 서버 동기화 ──
  async function syncWithServer(silent = false) {
    if (isMock()) {
      if (!silent) toast('샘플 데이터 모드에서는 동기화가 지원되지 않습니다.');
      return;
    }
    if (!scriptUrl) {
      if (!silent) toast('Apps Script URL이 설정되지 않았어요.');
      return;
    }

    const syncBtn = $('syncBtn');
    if (syncBtn) { syncBtn.disabled = true; syncBtn.textContent = '동기화 중…'; }
    const hdrSync = $('headerSyncBtn');
    if (hdrSync) { hdrSync.classList.add('syncing'); hdrSync.disabled = true; }

    try {
      // 1. Push all unsynced entries
      const allEntriesMap = JSON.parse(localStorage.getItem(KEY_ENTRIES) || '{}');
      for (const jarId of Object.keys(allEntriesMap)) {
        const entries = allEntriesMap[jarId];
        let changed = false;
        for (let i = 0; i < entries.length; i++) {
          if (!entries[i].synced) {
            try {
              const res = await apiFetchReal({
                action: 'addEntry',
                params: { jarId, userId, amount: entries[i].amount, note: entries[i].note },
              });
              entries[i] = { ...entries[i], entryId: (res && res.entryId) || entries[i].entryId, synced: true };
              changed = true;
            } catch { /* keep as unsynced */ }
          }
        }
        if (changed) allEntriesMap[jarId] = entries;
      }
      localStorage.setItem(KEY_ENTRIES, JSON.stringify(allEntriesMap));

      // 1b. Push pending control changes
      const pendingCtrl = localPendingCtrl();
      const remainingCtrl = [];
      for (const pc of pendingCtrl) {
        try {
          await apiFetchReal({ action: 'setControl', params: { memberId: pc.memberId, controlId: pc.controlId, jarId: pc.jarId, userId } });
        } catch { remainingCtrl.push(pc); }
      }
      savePendingCtrl(remainingCtrl);

      // 1c. Push pending archive (jar deletions)
      const pendingArchive = localPendingArchive();
      const remainingArchive = [];
      for (const pa of pendingArchive) {
        try {
          await apiFetchReal({ action: 'archiveJar', params: { jarId: pa.jarId } });
        } catch { remainingArchive.push(pa); }
      }
      savePendingArchive(remainingArchive);

      // 2. Execute pending deletes
      const pendingDel = localPendingDel();
      const remainingDel = [];
      for (const { entryId, jarId } of pendingDel) {
        try { await apiFetchReal({ action: 'deleteEntry', params: { jarId, entryId } }); }
        catch { remainingDel.push({ entryId, jarId }); }
      }
      savePendingDel(remainingDel);

      // 3. Pull fresh jars from server & merge with local state
      const freshJars = await apiFetchReal({ query: 'getJarsByUser', params: { userId } }) || [];

      // Re-apply pending archive flags: if a jar was locally deleted but
      // the server hasn't processed it yet, keep it archived locally.
      const stillPendingArchive = localPendingArchive();
      const pendingArchiveIds = new Set(stillPendingArchive.map(p => p.jarId));

      // Merge: preserve local archived state for jars with pending archive,
      // and preserve pending control changes not yet pushed.
      const prevLocal = localJars();
      const mergedJars = freshJars.map(sj => {
        if (pendingArchiveIds.has(sj.jarId)) {
          const localJ = prevLocal.find(l => l.jarId === sj.jarId);
          return { ...sj, archived: true, archivedAt: (localJ && localJ.archivedAt) || new Date().toISOString() };
        }
        const pendingCtrlForJar = localPendingCtrl().find(p => p.jarId === sj.jarId);
        if (pendingCtrlForJar) {
          return { ...sj, controlId: pendingCtrlForJar.controlId };
        }
        return sj;
      });

      saveLocalJars(mergedJars);
      cachedJars = activeJars(mergedJars);

      // 4. For active jar, pull server history and merge
      if (currentJar) {
        try {
          // Snapshot existing donation IDs before pull (to detect new ones)
          const localE = allEntriesMap[currentJar.jarId] || [];
          const prevDonationIds = new Set(
            localE.filter(e => e.type === 'donation_in' || e.type === 'donation').map(e => e.entryId)
          );

          const histData = await apiFetchReal({ query: 'getJarHistory', params: { jarId: currentJar.jarId } });
          const serverEntries = (histData.history || [])
            .map(e => ({
              entryId: e.id, amount: e.amount, note: e.label, createdAt: e.date, synced: true,
              type: e.type || 'entry', icon: e.icon || '💰', contributorName: e.contributorName || '',
              requestAmount: e.requestAmount || 0, feeRate: e.feeRate || 0, feeAmount: e.feeAmount || 0,
            }));
          // Filter out entries that are pending local deletion (not yet confirmed by server)
          const stillPendingDel = localPendingDel();
          const pendingDelIds = new Set(stillPendingDel.map(p => p.entryId));
          const filteredServerEntries = serverEntries.filter(e => !pendingDelIds.has(e.entryId));
          // Merge: filtered server entries + still-unsynced local entries (not yet pushed)
          const stillUnsynced = localE.filter(e => !e.synced);
          const merged = [...filteredServerEntries, ...stillUnsynced].sort((a, b) => (b.createdAt > a.createdAt ? 1 : -1));
          saveLocalEntries(currentJar.jarId, merged);
          entryRows = merged;

          // Detect new donation_in entries and show fun popup
          const newDonations = filteredServerEntries.filter(
            e => (e.type === 'donation_in' || e.type === 'donation') && !prevDonationIds.has(e.entryId)
          );
          if (newDonations.length > 0) {
            showDonationReceivedPopup(newDonations);
          }
        } catch { /* use existing local */ }

        // Update currentJar from merged data
        const fresh = mergedJars.find(j => j.jarId === currentJar.jarId);
        if (fresh && !fresh.archived) {
          const unsyncedSum = localEntries(currentJar.jarId)
            .filter(e => !e.synced)
            .reduce((s, e) => s + (Number(e.amount) || 0), 0);
          currentJar = { ...currentJar, ...fresh, currentAmount: (Number(fresh.currentAmount) || 0) + unsyncedSum };
          updateJarDisplay(currentJar);
          renderControlSection(currentJar, entryRows);
          renderHistorySection(currentJar.jarId);
        }
      }

      const now = new Date().toISOString();
      localStorage.setItem(KEY_LAST_SYNC, now);
      updateLastSyncDisplay();
      if (!silent) toast('동기화 완료!');

      // If we were in empty state, now we have data — re-init
      if (!currentJar && cachedJars.length > 0) {
        await initApp();
      } else if (!currentJar && cachedJars.length === 0) {
        // 서버에도 jar가 없음 — 빈 상태 표시
        $('jarLoading').hidden = true;
        $('jarEmpty').hidden   = false;
      }
    } catch (err) {
      if (!silent) toast('동기화 실패: ' + err.message);
      throw err;
    } finally {
      if (syncBtn) { syncBtn.disabled = false; syncBtn.textContent = '서버 동기화'; }
      if (hdrSync) { hdrSync.classList.remove('syncing'); hdrSync.disabled = false; }
    }
  }

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
    function appendSect(title, list, showDel) {
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
        const delHtml  = showDel
          ? `<button class="jar-picker-del-btn" data-del-jar-id="${escHtml(jar.jarId)}" type="button" aria-label="삭제">🗑️</button>`
          : '';
        html += `<div class="jar-picker-row">
          <button class="jar-picker-item${isActive ? ' active' : ''}" data-jar-id="${escHtml(jar.jarId)}" type="button">
            <div class="jpi-name">${escHtml(jar.name || '(이름 없음)')}</div>
            ${progressHtml}
            <div class="jpi-amounts">
              <span class="jpi-cur">${won(cur)}</span>
              <span class="jpi-sep"> / </span>
              <span class="jpi-goal">${goalText}</span>
              ${pctHtml}
            </div>
          </button>
          ${delHtml}
        </div>`;
      });
    }

    appendSect('내 Jar', owned, true);
    appendSect('참여 중인 Jar', joined, false);
    listEl.innerHTML = html;

    listEl.querySelectorAll('.jar-picker-item').forEach(btn => {
      btn.addEventListener('click', () => {
        const jar = cachedJars.find(j => j.jarId === btn.dataset.jarId);
        if (jar) onJarSelect(jar);
      });
    });

    listEl.querySelectorAll('.jar-picker-del-btn').forEach(btn => {
      btn.addEventListener('click', (e) => {
        e.stopPropagation();
        openDeleteJarConfirm(btn.dataset.delJarId);
      });
    });
  }

  async function onJarSelect(jar) {
    closeSheet('jarPickerSheet');
    currentJar = jar;
    localStorage.setItem(KEY_ACTIVE_JAR, jar.jarId);
    renderJarSection(jar);

    entryRows = localEntries(jar.jarId);
    renderControlSection(jar, entryRows);
    renderHistorySection(jar.jarId);

    // Pull server history for selected jar (merge with local unsynced)
    if (scriptUrl && !isMock()) {
      try {
        const histData = await apiFetchReal({ query: 'getJarHistory', params: { jarId: jar.jarId } });
        const serverEntries = (histData.history || [])
          .map(e => ({
            entryId: e.id, amount: e.amount, note: e.label, createdAt: e.date, synced: true,
            type: e.type || 'entry', icon: e.icon || '💰', contributorName: e.contributorName || '',
            requestAmount: e.requestAmount || 0, feeRate: e.feeRate || 0, feeAmount: e.feeAmount || 0,
          }));
        const stillUnsynced = entryRows.filter(e => !e.synced);
        const merged = [...serverEntries, ...stillUnsynced].sort((a, b) => (b.createdAt > a.createdAt ? 1 : -1));
        saveLocalEntries(jar.jarId, merged);
        entryRows = merged;
        renderControlSection(jar, entryRows);
        renderHistorySection(jar.jarId);
      } catch { /* use existing local */ }
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
      // 새 Jar를 로컬에 추가
      const newJar = { jarId: res.jarId, name, description: desc, goalAmount: goal, currentAmount: 0, ownerId: userId, controlId: '', memberId: '' };
      const jars = localJars();
      jars.unshift(newJar);
      saveLocalJars(jars);
      cachedJars = jars;
      // 새 Jar 활성화
      await onJarSelect(newJar);
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

    const isOwned = jar.ownerId === userId;
    $('historyBtn').hidden = false;
    $('donateBtn').hidden  = isOwned;

    // Show sync info for joined jars
    const syncInfo = $('jarSyncInfo');
    if (!isOwned) {
      const ts = localStorage.getItem(KEY_LAST_SYNC);
      if (ts) {
        try {
          const d = new Date(ts);
          syncInfo.textContent = `마지막 동기화: ${d.getMonth()+1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2,'0')}`;
        } catch { syncInfo.textContent = ''; }
      } else {
        syncInfo.textContent = '아직 동기화하지 않음';
      }
      syncInfo.hidden = false;
    } else {
      syncInfo.hidden = true;
    }
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
      renderGaugeGrid(jar);
      // 예상 달성일은 gauge-pred에서 표시하므로 jar-prediction 숨김
      $('mainJarPrediction').textContent = '';
      $('mainJarPrediction').className = 'jar-prediction';
    } else {
      $('mainJarProgressWrap').hidden = true;
      $('mainJarGaugeGrid').innerHTML = '';
      $('mainJarPrediction').textContent = '';
    }
  }

  /** 이번주/이번달/전체 적립 게이지 + 예상 달성일 렌더 */
  function renderGaugeGrid(jar) {
    const entries = localEntries(jar.jarId);
    const now = new Date();

    // 이번주 (월~일) 시작
    const dayOfWeek = now.getDay(); // 0=Sun
    const mondayOffset = dayOfWeek === 0 ? 6 : dayOfWeek - 1;
    const weekStart = new Date(now.getFullYear(), now.getMonth(), now.getDate() - mondayOffset);

    // 이번달 시작
    const monthStart = new Date(now.getFullYear(), now.getMonth(), 1);

    let weekTotal = 0, monthTotal = 0, allTotal = 0;
    for (const e of entries) {
      const amt = Number(e.amount) || 0;
      allTotal += amt;
      if (!e.createdAt) continue;
      const d = new Date(e.createdAt);
      if (d >= monthStart) monthTotal += amt;
      if (d >= weekStart)  weekTotal  += amt;
    }

    const goal = Number(jar.goalAmount) || 0;
    const cur  = Number(jar.currentAmount) || 0;

    // 예상 달성일 계산 (최근 7일 기반)
    let predHtml = '';
    if (cur < goal) {
      const recentTotal = Number(jar.recentSevenDayTotal) || 0;
      if (recentTotal > 0) {
        const dailyAvg = recentTotal / 7;
        const remaining = goal - cur;
        const daysNeeded = Math.ceil(remaining / dailyAvg);
        const targetDate = new Date(Date.now() + daysNeeded * 86400000);
        const dateStr = `${targetDate.getFullYear()}-${String(targetDate.getMonth()+1).padStart(2,'0')}-${String(targetDate.getDate()).padStart(2,'0')}`;
        predHtml = `<div class="gauge-pred">` +
          `<span class="gauge-pred-date">${dateStr}</span>` +
          `<span class="gauge-pred-days">${daysNeeded}일 남음</span>` +
          `</div>`;
      }
    } else {
      predHtml = `<div class="gauge-pred achieved"><span class="gauge-pred-date">달성 완료!</span></div>`;
    }

    const gaugeItem = (label, amount, pctOfGoal) => {
      const pct = goal > 0 ? Math.min(100, Math.round(pctOfGoal / goal * 100)) : 0;
      return `<div class="gauge-item">` +
        `<div class="gauge-label">${label}</div>` +
        `<div class="gauge-amount">${won(amount)}</div>` +
        `<div class="gauge-bar-wrap"><div class="gauge-bar" style="width:${pct}%"></div></div>` +
        `</div>`;
    };

    $('mainJarGaugeGrid').innerHTML =
      `<div class="gauge-grid">` +
        gaugeItem('이번주', weekTotal, weekTotal) +
        gaugeItem('이번달', monthTotal, monthTotal) +
        gaugeItem('전체', allTotal, allTotal) +
      `</div>` +
      predHtml;
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
      const emptyMsg0 = $('controlEmpty').querySelector('.ctrl-empty-msg');
      if (emptyMsg0) emptyMsg0.textContent = '먼저 Jar를 선택하세요.';
      return;
    }

    // Joined jar: hide controls, show message
    if (jar.ownerId !== userId) {
      $('controlDisplay').hidden = true;
      $('controlEmpty').hidden   = false;
      const emptyMsg = $('controlEmpty').querySelector('.ctrl-empty-msg');
      if (emptyMsg) emptyMsg.textContent = '참여 중인 Jar입니다.';
      return;
    }

    // Reset message for own jars
    const emptyMsg2 = $('controlEmpty').querySelector('.ctrl-empty-msg');
    if (emptyMsg2) emptyMsg2.textContent = '먼저 Jar를 선택하세요.';

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

    // 탭이 있는 control인지 확인
    const hasTabs = ctrl.items.some(i => i.tab);
    const visibleItems = hasTabs
      ? ctrl.items.filter(i => i.tab === _activeRewardTab)
      : ctrl.items;

    const ICONS = { milestone: '🏆', academic: '📝', performance: '🏊', routine: '📅' };

    let tabBarHtml = '';
    if (hasTabs) {
      tabBarHtml = `<div class="reward-tab-bar">` +
        `<button class="reward-tab-btn${_activeRewardTab === 'routine' ? ' active' : ''}" data-reward-tab="routine" type="button">루틴</button>` +
        `<button class="reward-tab-btn${_activeRewardTab === 'event' ? ' active' : ''}" data-reward-tab="event" type="button">이벤트</button>` +
        `</div>`;
    }

    const buttonsHtml = visibleItems.map(item => {
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
      const icon      = ICONS[item.type] || '💰';
      const doneBadge = claimed ? '<span class="rb-done-badge">완료</span>' : '';
      return `<button class="reward-btn${claimed ? ' is-done' : ''}" data-item-id="${escHtml(item.id)}" type="button"${claimed ? ' disabled' : ''}>` +
        `<span class="rb-icon">${icon}</span>` +
        `<span class="rb-label">${escHtml(item.label)}</span>` +
        `<span class="rb-amount">${escHtml(amtStr)}</span>` +
        doneBadge +
        `</button>`;
    }).join('');

    listEl.innerHTML = tabBarHtml + `<div class="reward-grid">${buttonsHtml}</div>`;

    // 탭 버튼 클릭 핸들러
    listEl.querySelectorAll('.reward-tab-btn').forEach(tbtn => {
      tbtn.addEventListener('click', () => {
        _activeRewardTab = tbtn.dataset.rewardTab;
        renderRewardButtons(ctrl, entries, listEl);
      });
    });

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

  function onControlSelect(controlId) {
    const jar = currentJar;
    if (!jar) return;
    // localStorage-first: 로컬만 수정, 동기화 때 서버에 push
    jar.controlId = controlId;
    const cached = cachedJars.find(j => j.jarId === jar.jarId);
    if (cached) cached.controlId = controlId;
    const jars = localJars();
    const lj = jars.find(j => j.jarId === jar.jarId);
    if (lj) { lj.controlId = controlId; saveLocalJars(jars); }
    // pending control change 큐에 추가 (같은 jar 중복 제거)
    const pending = localPendingCtrl().filter(p => p.jarId !== jar.jarId);
    pending.push({ jarId: jar.jarId, memberId: jar.memberId || '', controlId });
    savePendingCtrl(pending);
    closeSheet('controlPickerSheet');
    renderControlSection(jar, entryRows);
    toast('Control을 설정했어요.');
  }

  // ── localStorage-first 적립 ──
  function addEntryLocal(amount, note) {
    const jar = currentJar;
    if (!jar) return;

    const entry = {
      entryId: 'local_' + Date.now() + '_' + Math.floor(Math.random() * 1e6),
      amount, note,
      createdAt: new Date().toISOString(),
      synced: false,
    };

    // Mock 모드에서는 synced: true로 처리 (서버 없이 동작)
    if (isMock()) {
      entry.synced = true;
      // mock 서버에도 반영
      mockResponse({ action: 'addEntry', params: { jarId: jar.jarId, userId, amount, note } });
    }

    // Save to localStorage
    const entries = localEntries(jar.jarId);
    entries.unshift(entry);
    saveLocalEntries(jar.jarId, entries);

    // Update jar amount in localStorage
    const jars = localJars();
    const j = jars.find(j => j.jarId === jar.jarId);
    if (j) {
      j.currentAmount = (Number(j.currentAmount) || 0) + amount;
      j.recentSevenDayTotal = (Number(j.recentSevenDayTotal) || 0) + amount;
      saveLocalJars(jars);
    }

    // Update in-memory state
    jar.currentAmount = (Number(jar.currentAmount) || 0) + amount;
    jar.recentSevenDayTotal = (Number(jar.recentSevenDayTotal) || 0) + amount;
    updateJarDisplay(jar);

    entryRows = localEntries(jar.jarId);
    renderControlSection(jar, entryRows);
    renderHistorySection(jar.jarId);

    showUndoToast(jar.jarId, entry.entryId, amount);
  }

  function deleteEntryLocal(jarId, entryId) {
    const entries = localEntries(jarId);
    const idx = entries.findIndex(e => e.entryId === entryId);
    if (idx < 0) return;
    const removed = entries.splice(idx, 1)[0];
    saveLocalEntries(jarId, entries);

    // If it was synced to server, queue for deletion on next sync
    if (removed.synced && !isMock()) {
      const pending = localPendingDel();
      pending.push({ entryId, jarId });
      savePendingDel(pending);
    }

    // Update jar amount in localStorage
    const amount = Number(removed.amount) || 0;
    const jars = localJars();
    const j = jars.find(j => j.jarId === jarId);
    if (j) {
      j.currentAmount = Math.max(0, (Number(j.currentAmount) || 0) - amount);
      saveLocalJars(jars);
    }

    // Update in-memory state
    if (currentJar && currentJar.jarId === jarId) {
      currentJar.currentAmount = Math.max(0, (Number(currentJar.currentAmount) || 0) - amount);
      updateJarDisplay(currentJar);
      entryRows = localEntries(jarId);
      renderControlSection(currentJar, entryRows);
      renderHistorySection(jarId);
    }

    toast('삭제됐어요.');
  }

  // ── Jar 아카이브 (삭제) ──
  function archiveJarLocal(jarId) {
    const jars = localJars();
    const j = jars.find(j => j.jarId === jarId);
    if (!j) return;
    j.archived = true;
    j.archivedAt = new Date().toISOString();
    saveLocalJars(jars);

    // Mock 모드에서도 플래그 설정
    if (isMock()) {
      const mj = MOCK_JARS.find(m => m.jarId === jarId);
      if (mj) { mj.archived = true; mj.archivedAt = j.archivedAt; }
    }

    // pending archive 큐에 추가 (중복 제거)
    const pending = localPendingArchive().filter(p => p.jarId !== jarId);
    pending.push({ jarId });
    savePendingArchive(pending);

    // 캐시 갱신
    cachedJars = activeJars(localJars());

    // 다른 Jar로 전환
    if (currentJar && currentJar.jarId === jarId) {
      if (cachedJars.length > 0) {
        onJarSelect(cachedJars[0]);
      } else {
        currentJar = null;
        localStorage.removeItem(KEY_ACTIVE_JAR);
        $('jarDisplay').hidden = true;
        $('jarEmpty').hidden   = false;
        $('controlDisplay').hidden = true;
        $('controlEmpty').hidden   = false;
      }
    }

    toast('Jar를 삭제했어요.');
  }

  // 삭제 확인 시트 핸들러
  let _deleteTargetJarId = null;

  function openDeleteJarConfirm(jarId) {
    const jar = localJars().find(j => j.jarId === jarId);
    if (!jar) return;
    _deleteTargetJarId = jarId;
    $('delJarName').textContent = jar.name || '(이름 없음)';
    openSheet('deleteJarConfirmSheet');
  }

  $('delJarConfirmBtn').addEventListener('click', () => {
    if (!_deleteTargetJarId) return;
    closeSheet('deleteJarConfirmSheet');
    closeSheet('jarPickerSheet');
    archiveJarLocal(_deleteTargetJarId);
    _deleteTargetJarId = null;
  });

  // ── 내역 섹션 렌더 ──
  function displayNote(note) {
    if (!note) return '적립';
    return note.replace(/^\[[\w]+\]\s*/, '');
  }

  // ── 직접 입력 ──
  $('manualEntryBtn').addEventListener('click', () => {
    $('meNote').value = '';
    $('meAmount').value = '';
    openSheet('manualEntrySheet');
    setTimeout(() => $('meNote').focus(), 300);
  });

  $('meSubmitBtn').addEventListener('click', () => {
    const note = $('meNote').value.trim();
    const amount = Number(String($('meAmount').value).replace(/[^0-9]/g, ''));
    if (!note) { toast('항목 이름을 입력하세요.'); $('meNote').focus(); return; }
    if (!amount || amount <= 0) { toast('금액을 입력하세요.'); $('meAmount').focus(); return; }
    closeSheet('manualEntrySheet');
    addEntryLocal(amount, note);
  });

  // ── 내역 시트 ──
  $('historyBtn').addEventListener('click', () => {
    if (!currentJar) return;
    renderHistoryList(currentJar.jarId);
    openSheet('historySheet');
  });

  // ── 기부 수신 팝업 (동기화 시 새 기부가 감지되면 표시) ──
  let _donationQueue = [];
  function showDonationReceivedPopup(donations) {
    _donationQueue = donations.slice();
    _showNextDonation();
  }
  function _showNextDonation() {
    if (_donationQueue.length === 0) return;
    const d = _donationQueue.shift();
    const net = Number(d.amount) || 0;
    const req = Number(d.requestAmount) || 0;
    const fee = Number(d.feeAmount) || 0;
    const feePct = Math.round((Number(d.feeRate) || 0) * 100);
    const from = d.contributorName || '(알 수 없음)';
    // If we have requestAmount info, show the full breakdown
    const hasDetail = req > 0;
    let html = `<div class="dr-recv-img"><img src="./raccoon_boss.jpg" alt="너구리사장"></div>`;
    html += `<div class="dr-recv-from">💌 <strong>${from}</strong> 에서 기부가 왔어요!</div>`;
    if (hasDetail) {
      html += `<div class="dr-row"><span>보낸 금액</span><span>${won(req)}</span></div>`;
      html += `<div class="dr-row dr-fee"><span>🦝 너구리사장 수수료 (${feePct}%)</span><span>-${won(fee)}</span></div>`;
      html += `<div class="dr-row dr-net"><span>내 Jar에 도착한 금액</span><span>${won(net)}</span></div>`;
    } else {
      html += `<div class="dr-row dr-net"><span>받은 금액</span><span>${won(net)}</span></div>`;
    }
    const remaining = _donationQueue.length;
    if (remaining > 0) {
      html += `<p class="dr-remaining">${remaining}건의 기부가 더 있어요!</p>`;
    }
    $('donateReceivedBody').innerHTML = html;
    openSheet('donateReceivedSheet');
  }
  $('donateReceivedNextBtn').addEventListener('click', () => {
    closeSheet('donateReceivedSheet');
    setTimeout(_showNextDonation, 300);
  });

  // ── 기부 버튼 ──
  $('donateBtn').addEventListener('click', () => {
    if (!currentJar) return;
    const myJar = cachedJars.find(j => j.ownerId === userId);
    if (!myJar) { toast('내 Jar가 없어 기부할 수 없어요.'); return; }
    $('donateFrom').textContent = myJar.name;
    $('donateTo').textContent = currentJar.name;
    $('donateAmount').value = '';
    openSheet('donateSheet');
    setTimeout(() => $('donateAmount').focus(), 300);
  });

  $('donateSubmitBtn').addEventListener('click', async () => {
    const amount = Number(String($('donateAmount').value).replace(/[^0-9]/g, ''));
    if (!amount || amount <= 0) { toast('금액을 입력하세요.'); return; }
    const myJar = cachedJars.find(j => j.ownerId === userId);
    if (!myJar) return;
    $('donateSubmitBtn').disabled = true;
    try {
      const res = await apiFetch({ action: 'donate', params: {
        fromJarId: myJar.jarId,
        toJarId: currentJar.jarId,
        amount,
      }});
      closeSheet('donateSheet');
      // Show result
      const feePct = Math.round((res.feeRate || 0) * 100);
      $('donateResultBody').innerHTML =
        `<div class="dr-row"><span>기부 요청</span><span>${won(amount)}</span></div>` +
        `<div class="dr-row dr-fee"><span>🦝 너구리사장 수수료 (${feePct}%)</span><span>-${won(res.feeAmount)}</span></div>` +
        `<div class="dr-row dr-net"><span>실제 전달 금액</span><span>${won(res.netAmount)}</span></div>`;
      openSheet('donateResultSheet');
      // Add donation_out to sender's local history
      const donOutEntry = {
        entryId: res.donationId, amount: -amount, note: '기부 발신 (수수료 ' + feePct + '%)',
        createdAt: new Date().toISOString(), synced: true,
        type: 'donation_out', icon: '↗️', contributorName: currentJar.name || '',
      };
      const myEntries = localEntries(myJar.jarId);
      myEntries.unshift(donOutEntry);
      saveLocalEntries(myJar.jarId, myEntries);
      // Add donation_in to receiver's local history
      const donInEntry = {
        entryId: res.donationId + '_in', amount: res.netAmount,
        note: `기부(${won(amount)}, 수수료${Math.round((res.feeRate || 0) * 100)}%)`,
        createdAt: new Date().toISOString(), synced: true,
        type: 'donation_in', icon: '🦝', contributorName: myJar.name || '',
        requestAmount: amount, feeRate: res.feeRate || 0, feeAmount: res.feeAmount || 0,
      };
      const toEntries = localEntries(currentJar.jarId);
      toEntries.unshift(donInEntry);
      saveLocalEntries(currentJar.jarId, toEntries);
      // Update my jar's local amount
      myJar.currentAmount = Math.max(0, (Number(myJar.currentAmount) || 0) - amount);
      const jars = localJars();
      const lj = jars.find(j => j.jarId === myJar.jarId);
      if (lj) { lj.currentAmount = myJar.currentAmount; saveLocalJars(jars); }
      if (currentJar.jarId === myJar.jarId) updateJarDisplay(myJar);
      cachedJars = activeJars(localJars());
    } catch (err) {
      toast('기부 실패: ' + err.message);
    } finally {
      $('donateSubmitBtn').disabled = false;
    }
  });

  function renderHistoryList(jarId) {
    const listEl = $('historyList');
    const entries = localEntries(jarId);

    if (!entries || entries.length === 0) {
      listEl.innerHTML = '<p class="hist-empty">내역이 없어요.</p>';
      return;
    }

    listEl.innerHTML = entries.map(e => {
      const type = e.type || 'entry';
      const isDonation = type === 'donation' || type === 'donation_in' || type === 'donation_out';
      const isDonationIn = type === 'donation' || type === 'donation_in';
      const icon = e.icon || (type === 'donation_out' ? '↗️' : isDonationIn ? '🦝' : '💰');
      const amt = Number(e.amount) || 0;
      const amtSign = amt >= 0 ? '+' : '';
      const amtClass = amt < 0 ? ' hist-amount-neg' : '';
      const isOwnedJar = currentJar && currentJar.ownerId === userId;
      const delBtn = !isDonation && isOwnedJar
        ? `<button class="hist-del-btn" data-entry-id="${escHtml(e.entryId)}" data-jar-id="${escHtml(jarId)}" type="button" aria-label="삭제">🗑️</button>`
        : '';
      // 기부 수신 내역: "기부(원래금액, 수수료N%)" 형식으로 표시
      let noteDisplay = displayNote(e.note);
      if (isDonationIn) {
        const reqAmt = Number(e.requestAmount) || 0;
        const feePct = Math.round((Number(e.feeRate) || 0) * 100);
        if (reqAmt > 0) {
          noteDisplay = `기부(${won(reqAmt)}, 수수료${feePct}%)`;
        }
      }
      return `<div class="hist-row${isDonation ? ' hist-donation' : ''}">
        <div class="hist-left">
          <div class="hist-label">${icon} ${escHtml(noteDisplay)}</div>
          <div class="hist-date">${fmtDate(e.createdAt)}${!e.synced ? ' <span class="hist-pending">●</span>' : ''}${e.contributorName ? ' · ' + escHtml(e.contributorName) : ''}</div>
        </div>
        <div class="hist-right">
          <div class="hist-amount${amtClass}">${amtSign}${won(Math.abs(amt))}</div>
          ${delBtn}
        </div>
      </div>`;
    }).join('');

    listEl.querySelectorAll('.hist-del-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        deleteEntryLocal(btn.dataset.jarId, btn.dataset.entryId);
        renderHistoryList(btn.dataset.jarId);
      });
    });
  }

  function renderHistorySection(jarId) {
    // no-op: history is now in a sheet, not a section
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
      addEntryLocal(item.amount, `[${item.id}] ${item.label} (${todayStr()})`);
    } else if (item.subtype === 'session') {
      addEntryLocal(item.amount, `[${item.id}] ${item.label} × 1회`);
    } else {
      addEntryLocal(item.amount, `[${item.id}] ${item.label}`);
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

  $('entryConfirmBtn').addEventListener('click', () => {
    const pending = _pendingEntry;
    const jar     = currentJar;
    if (!pending || !jar) return;
    const btn = $('entryConfirmBtn');
    btn.disabled = true;
    try {
      addEntryLocal(pending.amount, pending.note);
      closeSheet('entryConfirmSheet');
      _pendingEntry = null;
    } finally {
      btn.disabled = false;
    }
  });

  // ── 앱 초기화 (localStorage-first) ──
  async function initApp() {
    if (isMock()) console.info('[DreamJar] Apps Script URL 미설정 → 샘플 데이터 모드');

    $('jarLoading').hidden = false;
    $('jarDisplay').hidden = true;
    $('jarEmpty').hidden   = true;
    $('controlDisplay').hidden = true;
    $('controlEmpty').hidden   = false;
    // historySection removed (history is now in a sheet)

    cachedJars = activeJars(localJars());

    if (!cachedJars || cachedJars.length === 0) {
      if (isMock()) {
        // Mock 모드: 샘플 데이터를 로컬에 초기화
        const mockJars = MOCK_JARS.map(j => ({
          ...j, ownerId: j.ownerId === '__me__' ? userId : (j.ownerId || userId),
        }));
        saveLocalJars(mockJars);
        // Mock 내역도 로컬에 저장
        Object.entries(MOCK_ENTRIES).forEach(([jarId, entries]) => {
          saveLocalEntries(jarId, entries);
        });
        cachedJars = activeJars(mockJars);
      } else if (scriptUrl) {
        // 로컬 데이터 없음 — 서버에서 한 번 자동 로드
        toast('로컬 데이터 없음. 서버에서 불러오는 중…');
        try { await syncWithServer(true); return; } catch { /* fall through to empty */ }
      }

      if (!cachedJars || cachedJars.length === 0) {
        $('jarLoading').hidden = true;
        $('jarEmpty').hidden   = false;
        return;
      }
    }

    $('jarLoading').hidden = true;

    const savedJarId = localStorage.getItem(KEY_ACTIVE_JAR);
    const jar = (savedJarId && cachedJars.find(j => j.jarId === savedJarId)) || cachedJars[0];

    currentJar = jar;
    localStorage.setItem(KEY_ACTIVE_JAR, jar.jarId);
    renderJarSection(jar);

    entryRows = localEntries(jar.jarId);
    renderControlSection(jar, entryRows);
    renderHistorySection(jar.jarId);

    updateLastSyncDisplay();
  }

  // ── 홈 화면에 추가 (A2HS / PWA install) — CMPA-872 ──
  const isStandalone = () =>
    (window.matchMedia && window.matchMedia('(display-mode: standalone)').matches) ||
    window.navigator.standalone === true;
  const isIOS = () =>
    /iphone|ipad|ipod/i.test(navigator.userAgent) && !window.MSStream;

  let deferredPrompt = null;
  function showInstallBtn(show){
    const btn = $('installBtn'); const div = $('settInstallDivider'); const sec = $('settInstallSection');
    if (btn) btn.hidden = !show;
    if (div) div.hidden = !show;
    if (sec) sec.hidden = !show;
  }
  (function setupInstall(){
    const btn = $('installBtn');
    if (!btn) return;
    if (isStandalone()) { showInstallBtn(false); return; }

    window.addEventListener('beforeinstallprompt', e => {
      e.preventDefault();
      deferredPrompt = e;
      showInstallBtn(true);
    });

    if (isIOS()) showInstallBtn(true);

    btn.addEventListener('click', async () => {
      if (deferredPrompt){
        deferredPrompt.prompt();
        let outcome = 'dismissed';
        try { ({ outcome } = await deferredPrompt.userChoice); } catch(e){}
        deferredPrompt = null;
        showInstallBtn(false);
        if (outcome === 'accepted') toast('홈 화면에 추가했어요');
      } else if (isIOS()){
        openSheet('iosInstallSheet');
      }
    });

    window.addEventListener('appinstalled', () => {
      deferredPrompt = null;
      showInstallBtn(false);
      closeSheet('iosInstallSheet');
      toast('홈 화면에 추가됐어요');
    });
  })();

  // ── 진입점 ──
  if (!userId) {
    showSetup();
  } else {
    hideSetup();
    initApp();
  }

})();
