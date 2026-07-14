/* DreamJar — 단일 화면 앱 로직
   구조: JAR 섹션 + CONTROL 섹션 + HISTORY 섹션 (탭 없음)
   localStorage-first: 모든 데이터는 로컬에 저장. 서버 동기화는 명시적 버튼으로만. */

(() => {
  'use strict';

  // ── 스토리지 키 ──
  const KEY_USER_ID    = 'dreamjar.userId';
  const KEY_ACTIVE_JAR = 'dreamjar.activeJarId';
  const KEY_JARS       = 'dreamjar.jars';       // JSON: [{jarId, name, goalAmount, currentAmount, ...}]
  const KEY_ENTRIES    = 'dreamjar.entries';     // JSON: {jarId: [{entryId, amount, note, createdAt, synced}]}
  const KEY_PENDING_DEL = 'dreamjar.pendingDel'; // JSON: [{entryId, jarId}]
  const KEY_PENDING_CTRL = 'dreamjar.pendingCtrl'; // JSON: [{jarId, memberId, controlId}]
  const KEY_PENDING_ARCHIVE = 'dreamjar.pendingArchive'; // JSON: [{jarId}]
  const KEY_LAST_SYNC  = 'dreamjar.lastSync';    // ISO timestamp string
  const KEY_SERVER_MODIFIED = 'dreamjar.serverModified'; // 서버 lastModified (CMPA-888)
  const KEY_CUSTOM_CTRLS   = 'dreamjar.customControls'; // JSON: [{controlId, name, emoji, description, items}]
  const KEY_PENDING_CTRL_SYNC = 'dreamjar.pendingCtrlSync'; // JSON: [{controlId, action:'create'|'update'|'delete', data}]

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
  function localCustomControls() { return JSON.parse(localStorage.getItem(KEY_CUSTOM_CTRLS) || '[]'); }
  function saveCustomControls(list) { localStorage.setItem(KEY_CUSTOM_CTRLS, JSON.stringify(list)); }
  function localPendingCtrlSync() { return JSON.parse(localStorage.getItem(KEY_PENDING_CTRL_SYNC) || '[]'); }
  function savePendingCtrlSync(list) { localStorage.setItem(KEY_PENDING_CTRL_SYNC, JSON.stringify(list)); }

  /** 활성(아카이브되지 않은) Jar만 반환 */
  function activeJars(jars) { return jars.filter(j => !j.archived); }

  // ── 상태 ──
  let userId    = localStorage.getItem(KEY_USER_ID) || '';

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
      name: 'JieunControl',
      emoji: '🌈',
      description: '건강 습관 — 대신 하기 보상',
      type: 'default',
      items: [
        // 루틴 탭
        { id:'cb_swap_water', label:'💧 음료수 대신 물 마시기',              type:'routine',     subtype:'per_day',  amount:1500,  tab:'routine' },
        { id:'cb_swap_meat',  label:'🍖 가공육/튀김 대신 고기 먹기',        type:'routine',     subtype:'per_day',  amount:1500,  tab:'routine' },
        { id:'cb_swap_grain', label:'🍚 빵/흰밥 대신 갈색밥 먹기',          type:'routine',     subtype:'per_day',  amount:1500,  tab:'routine' },
        { id:'cb_swap_sweet', label:'🍇 사탕/아이스크림 대신 얼린 과일 먹기', type:'routine',     subtype:'per_day',  amount:1500,  tab:'routine' },
        { id:'cb_outdoor',    label:'🏃 바깥 놀이 30분',                    type:'routine',     subtype:'per_day',  amount:2000,  tab:'routine' },
        { id:'cb_earlybed',   label:'🌙 일찍 자기 (10시 전)',               type:'routine',     subtype:'per_day',  amount:500,   tab:'routine' },
        // 이벤트 탭
        { id:'cb_newplay',      label:'🆕 새 운동 도전',           type:'performance', subtype:'session', amount:5000,  tab:'event' },
        { id:'cb_cook',         label:'👩‍🍳 건강 간식 만들기',       type:'performance', subtype:'session', amount:3000,  tab:'event' },
        { id:'cb_walk_family',  label:'🚶‍♂️ 가족 산책',              type:'performance', subtype:'session', amount:2000,  tab:'event' },
        { id:'cb_streak_week',  label:'🔥 1주 연속 바깥놀이',      type:'performance', subtype:'session', amount:10000, tab:'event' },
        { id:'cb_swap_streak',  label:'⭐ 1주 4종 swap 올클리어',  type:'performance', subtype:'session', amount:15000, tab:'event' },
        { id:'cb_weight_check', label:'⚖️ 월간 체중 유지',         type:'milestone',   subtype:'once',    amount:20000, once:true, tab:'event' },
      ],
    },
    {
      controlId: 'ctrl_cd',
      name: 'FrugalControl',
      emoji: '💰',
      description: '일상 절약 행동 보상',
      type: 'default',
      items: [
        { id:'cd_coffee',   label:'드립커피',     type:'routine', subtype:'per_day', amount:4500 },
        { id:'cd_tumbler',  label:'텀블러',        type:'routine', subtype:'per_day', amount:1200 },
        { id:'cd_transit',  label:'도보/대중교통', type:'routine', subtype:'per_day', amount:5000 },
        { id:'cd_homemeal', label:'집밥',          type:'routine', subtype:'per_day', amount:8000 },
      ],
    },
    {
      controlId: 'ctrl_cc',
      name: 'EemControl',
      emoji: '📚',
      items: [
        { id:'cc_english',  label:'영어공부',     type:'routine', subtype:'per_day', amount:1000, tab:'routine' },
        { id:'cc_coffee',   label:'드립커피',     type:'routine', subtype:'per_day', amount:3000, tab:'routine' },
        { id:'cc_tumbler',  label:'텀블러',        type:'routine', subtype:'per_day', amount:1200, tab:'routine' },
        { id:'cc_transit',  label:'도보/대중교통', type:'routine', subtype:'per_day', amount:5000, tab:'routine' },
        { id:'cc_homemeal', label:'집밥',          type:'routine', subtype:'per_day', amount:5000, tab:'routine' },
        { id:'cc_kr_read',  label:'한국책읽기30분', type:'routine', subtype:'per_day', amount:1000, tab:'routine' },
        { id:'cc_en_read',  label:'영어책읽기30분', type:'routine', subtype:'per_day', amount:1000, tab:'routine' },
        { id:'cc_ielts',    label:'IELTS',         type:'academic', subtype:'threshold',
          thresholds:[{min:7.0,amount:2000000},{min:6.5,amount:1000000}], once:true, tab:'event' },
      ],
    },
  ];

  /** All controls = built-in + custom */
  function allControls() {
    return [...ADMIN_CONTROLS, ...localCustomControls()];
  }

  function findControl(controlId) {
    return allControls().find(c => c.controlId === controlId) || null;
  }

  // ── 커스텀 컨트롤 CRUD (localStorage-first) ──
  let _editingCtrlId = null; // null = create, string = edit
  let _editingCtrlItems = []; // temp items array for create/edit sheet

  function saveCustomControl(ctrl) {
    const list = localCustomControls();
    const idx = list.findIndex(c => c.controlId === ctrl.controlId);
    if (idx >= 0) list[idx] = ctrl;
    else list.push(ctrl);
    saveCustomControls(list);
    // Queue sync
    const pending = localPendingCtrlSync().filter(p => p.controlId !== ctrl.controlId);
    pending.push({ controlId: ctrl.controlId, action: idx >= 0 ? 'update' : 'create', data: ctrl });
    savePendingCtrlSync(pending);
  }

  function deleteCustomControl(controlId) {
    const list = localCustomControls().filter(c => c.controlId !== controlId);
    saveCustomControls(list);
    const pending = localPendingCtrlSync().filter(p => p.controlId !== controlId);
    pending.push({ controlId, action: 'delete', data: null });
    savePendingCtrlSync(pending);
  }

  // ── DOM 헬퍼 ──
  const $ = id => document.getElementById(id);
  const KRW = new Intl.NumberFormat('ko-KR');
  const won = n => KRW.format(Math.round(n || 0)) + '원';
  const hasSupabase = () => typeof window.DreamJarSupabase !== 'undefined';
  const isMock = () => !hasSupabase();

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
    // CMPA-893: Supabase backend
    if (!hasSupabase()) throw new Error('Supabase가 로드되지 않았어요.');
    try {
      return await DreamJarSupabase.api({ action, query, params });
    } catch (err) {
      console.error('[DreamJar] Supabase 오류:', err);
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
          sourceNotes: d.sourceNotes || '',
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
    if (action === 'donateBulk') {
      const items = params.items || [];
      let totalRequest = 0, totalFee = 0, totalNet = 0;
      const results = items.map(item => {
        const requestAmt = Number(item.amount) || 0;
        const feeRate = Math.random() * 0.5;
        const feeAmount = Math.round(requestAmt * feeRate);
        const netAmount = requestAmt - feeAmount;
        totalRequest += requestAmt;
        totalFee += feeAmount;
        totalNet += netAmount;
        const donation = {
          donationId: 'don-' + Date.now() + '-' + Math.floor(Math.random() * 1e6),
          fromJarId: params.fromJarId, toJarId: params.toJarId,
          requestAmount: requestAmt, feeRate, feeAmount, netAmount,
          sourceNotes: item.note || '',
          createdAt: new Date().toISOString(),
        };
        MOCK_DONATIONS_OUT.push(donation);
        MOCK_DONATIONS_IN.push(donation);
        return { donationId: donation.donationId, note: item.note || '', amount: requestAmt, feeRate, feeAmount, netAmount };
      });
      const fromJar = MOCK_JARS.find(j => j.jarId === params.fromJarId);
      if (fromJar) fromJar.currentAmount = Math.max(0, (fromJar.currentAmount || 0) - totalRequest);
      const toJar = MOCK_JARS.find(j => j.jarId === params.toJarId);
      if (toJar) toJar.currentAmount = (toJar.currentAmount || 0) + totalNet;
      return Promise.resolve({ items: results, totalRequest, totalFee, totalNet });
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
    if (query === 'searchJars') {
      const q = (params.query || '').toLowerCase();
      const results = MOCK_JARS.filter(j => !j.archived && j.name && j.name.toLowerCase().includes(q));
      return Promise.resolve(results.map(j => ({ jarId: j.jarId, name: j.name, ownerName: j.ownerId || '', alreadyJoined: false })));
    }
    if (action === 'updateJarName') {
      const mj = MOCK_JARS.find(j => j.jarId === params.jarId);
      if (mj) mj.name = params.name;
      return Promise.resolve({ updated: true });
    }
    if (action === 'registerUser') return Promise.resolve({ userId: params.userId || userId });
    if (action === 'createControl') return Promise.resolve({ controlId: params.controlId || 'ctrl_mock_' + Date.now() });
    if (action === 'updateControl') return Promise.resolve({ updated: true });
    if (action === 'deleteControl') return Promise.resolve({ deleted: true });
    if (query === 'getCustomControls') return Promise.resolve([]);
    return Promise.resolve({});
  }

  // ── 설정 화면 ──
  // ── 로그인 화면 (CMPA-913) ──
  function showLogin() {
    $('loginScreen').hidden = false;
    $('mainApp').hidden = true;
    $('loginError').hidden = true;
    $('loginUserId').value = '';
    $('loginPassword').value = '';
    $('loginUserId').focus();
  }
  function hideLogin() {
    $('loginScreen').hidden = true;
    $('mainApp').hidden = false;
  }

  $('loginBtn').addEventListener('click', async () => {
    const inputUserId = $('loginUserId').value.trim();
    const password = $('loginPassword').value;
    if (!inputUserId) { $('loginUserId').focus(); return; }
    if (!password) { $('loginPassword').focus(); return; }

    const btn = $('loginBtn');
    btn.disabled = true;
    btn.textContent = '로그인 중…';
    $('loginError').hidden = true;

    try {
      if (!hasSupabase()) throw new Error('서버에 연결할 수 없습니다.');
      await DreamJarSupabase.auth.signInWithPassword(inputUserId, password);
      const authUserId = await DreamJarSupabase.auth.getAuthUserId();
      userId = authUserId || inputUserId;
      localStorage.setItem(KEY_USER_ID, userId);
      hideLogin();
      initApp();
    } catch (err) {
      console.error('[DreamJar] 로그인 실패:', err);
      const errMsg = err?.message || err?.error_description || err?.msg || (typeof err === 'string' ? err : JSON.stringify(err));
      const errEl = $('loginError');
      errEl.textContent = (errMsg === 'Invalid login credentials' || errMsg === 'invalid_grant')
        ? '사용자 ID 또는 비밀번호가 올바르지 않습니다.'
        : '로그인 실패: ' + errMsg;
      errEl.hidden = false;
    } finally {
      btn.disabled = false;
      btn.textContent = '로그인';
    }
  });

  // Enter key submits login
  $('loginPassword').addEventListener('keydown', e => {
    if (e.key === 'Enter') $('loginBtn').click();
  });
  $('loginUserId').addEventListener('keydown', e => {
    if (e.key === 'Enter') $('loginPassword').focus();
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
    $('settUserId').value = userId;
    loadSettJarList();
    updateLastSyncDisplay();
    openSheet('settingsSheet');
  });

  $('logoutBtn').addEventListener('click', async () => {
    if (!confirm('로그아웃하시겠습니까?\n로컬 데이터가 모두 삭제됩니다.')) return;
    // Supabase Auth 로그아웃
    try { if (hasSupabase()) await DreamJarSupabase.auth.signOut(); } catch {}
    // localStorage에서 dreamjar 관련 키 모두 삭제
    [KEY_USER_ID, KEY_ACTIVE_JAR, KEY_JARS, KEY_ENTRIES,
     KEY_PENDING_DEL, KEY_PENDING_CTRL, KEY_PENDING_ARCHIVE, KEY_LAST_SYNC,
     KEY_SERVER_MODIFIED, KEY_CUSTOM_CTRLS, KEY_PENDING_CTRL_SYNC
    ].forEach(k => localStorage.removeItem(k));
    // 캐시 초기화
    cachedJars = [];
    currentJar = null;
    entryRows  = [];
    userId     = '';
    // 설정 시트 닫고 로그인 화면으로
    closeSheet('settingsSheet');
    showLogin();
    toast('로그아웃했어요.');
  });

  $('settSaveBtn').addEventListener('click', () => {
    const newId  = $('settUserId').value.trim();
    if (!newId) { toast('사용자 ID를 입력하세요.'); return; }
    const changed = (newId !== userId);
    userId    = newId;
    localStorage.setItem(KEY_USER_ID, userId);
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

  // 다른 Jar 참여 — 검색 → 리스트 → 선택
  const joinResultsEl = $('joinSearchResults');

  // Detect jar_id format (prefix + underscore + digits)
  function looksLikeJarId(s) { return /^jar_\d+/.test(s); }

  // Direct join by jar_id
  async function directJoinJar(jarId) {
    try {
      const result = await apiFetch({ action: 'joinJar', params: { jarId, userId } });
      $('joinJarId').value = '';
      joinResultsEl.hidden = true;
      toast(result.alreadyJoined ? '이미 참여 중! 데이터를 새로고침합니다…' : '참여 완료! 데이터를 불러옵니다…');
      localStorage.removeItem(KEY_SERVER_MODIFIED);
      await syncWithServer(true);
      const joinedJar = cachedJars.find(j =>
        j.jarId === jarId || (result.jarName && j.name === result.jarName)
      );
      if (joinedJar) {
        currentJar = joinedJar;
        localStorage.setItem(KEY_ACTIVE_JAR, joinedJar.jarId);
        renderJarSection(joinedJar);
        entryRows = localEntries(joinedJar.jarId);
        renderControlSection(joinedJar, entryRows);
        renderHistorySection(joinedJar.jarId);
        renderPostsSection(joinedJar); // CMPA-933
      }
      closeSheet('settingsSheet');
      toast(result.alreadyJoined ? '이미 참여 중인 Jar입니다.' : '참여했습니다!');
    } catch (err) {
      toast('참여 실패: ' + err.message);
    }
  }

  $('joinJarBtn').addEventListener('click', async () => {
    const input = $('joinJarId').value.trim();
    if (!input) { toast('검색어를 입력하세요'); return; }

    // If it looks like a jar_id, join directly
    if (looksLikeJarId(input)) {
      $('joinJarBtn').disabled = true;
      await directJoinJar(input);
      $('joinJarBtn').disabled = false;
      return;
    }

    // Otherwise, search
    $('joinJarBtn').disabled = true;
    try {
      const results = await apiFetch({ query: 'searchJars', params: { query: input, userId } });
      if (!results || results.length === 0) {
        joinResultsEl.innerHTML = '<p class="join-no-result">검색 결과 없음</p>';
        joinResultsEl.hidden = false;
        return;
      }
      joinResultsEl.innerHTML = results.map(r => {
        const badge = r.alreadyJoined ? '<span class="join-badge-joined">참여중</span>' : '';
        return `<div class="join-result-item" data-jar-id="${r.jarId}">
          <div class="join-result-info">
            <span class="join-result-name">${r.name}</span>
            <span class="join-result-owner">소유자: ${r.ownerName || '—'}</span>
          </div>
          <div class="join-result-action">
            ${badge}
            <button class="btn-join-select" type="button" data-jar-id="${r.jarId}"${r.alreadyJoined ? ' disabled' : ''}>
              ${r.alreadyJoined ? '참여중' : '참여'}
            </button>
          </div>
        </div>`;
      }).join('');
      joinResultsEl.hidden = false;
    } catch (err) {
      toast('검색 실패: ' + err.message);
    } finally {
      $('joinJarBtn').disabled = false;
    }
  });

  // Delegate click on search result "참여" buttons
  joinResultsEl.addEventListener('click', async (e) => {
    const btn = e.target.closest('.btn-join-select');
    if (!btn || btn.disabled) return;
    const jarId = btn.dataset.jarId;
    btn.disabled = true;
    btn.textContent = '…';
    await directJoinJar(jarId);
    btn.disabled = false;
  });

  // 설정 시트 내 "새 Jar 만들기"
  $('createJarBtnSettings').addEventListener('click', () => {
    closeSheet('settingsSheet');
    openCreateJar();
  });

  // ── 서버 동기화 ──
  let _bgSyncTimer = null;
  let _syncInProgress = false;

  async function syncWithServer(silent = false) {
    if (isMock()) {
      if (!silent) toast('샘플 데이터 모드에서는 동기화가 지원되지 않습니다.');
      return;
    }
    // Guard against re-entrancy (background sync + manual sync overlap)
    if (_syncInProgress && silent) return;
    _syncInProgress = true;

    const syncBtn = $('syncBtn');
    if (syncBtn) { syncBtn.disabled = true; syncBtn.textContent = '동기화 중…'; }
    const hdrSync = $('headerSyncBtn');
    if (hdrSync) { hdrSync.classList.add('syncing'); hdrSync.disabled = true; }

    try {
      // 0. Check if there are any pending local changes
      const allEntriesMap = JSON.parse(localStorage.getItem(KEY_ENTRIES) || '{}');
      const pendingCtrl = localPendingCtrl();
      const pendingArchive = localPendingArchive();
      const pendingDel = localPendingDel();

      const pendingCtrlSync = localPendingCtrlSync();
      const hasUnsynced = Object.values(allEntriesMap).some(entries => entries.some(e => !e.synced));
      const hasPending = hasUnsynced || pendingCtrl.length > 0 || pendingArchive.length > 0 || pendingDel.length > 0 || pendingCtrlSync.length > 0;

      // If no local changes, check per-jar dirty bits (lightweight — sync_meta only)
      if (!hasPending) {
        try {
          // 로컬에 알고 있는 jarIds를 보내서 sync_meta만 조회 (jar_members/jars 안 읽음)
          const localJarMod = JSON.parse(localStorage.getItem(KEY_SERVER_MODIFIED) || '{}');
          const knownJarIds = Object.keys(localJarMod);
          if (knownJarIds.length > 0) {
            const checkResult = await apiFetchReal({ query: 'checkSync', params: { jarIds: knownJarIds.join(',') } });
            const serverJarMod = (checkResult && checkResult.jarModified) || {};
            const serverKeys = Object.keys(serverJarMod);
            const allClean = serverKeys.length === knownJarIds.length &&
              knownJarIds.every(k => serverJarMod[k] === localJarMod[k]);
            if (allClean) {
              if (!silent) toast('이미 최신 상태예요!');
              return;
            }
          }
        } catch { /* checkSync 실패 시 full pull 진행 */ }
      }

      // 1. Push all pending mutations in PARALLEL (was sequential)

      // Collect all push promises
      const pushPromises = [];

      // 1a. Unsynced entries — all in parallel
      const unsyncedRefs = []; // [{jarId, idx}] to mark synced after
      for (const jarId of Object.keys(allEntriesMap)) {
        const entries = allEntriesMap[jarId];
        for (let i = 0; i < entries.length; i++) {
          if (!entries[i].synced) {
            const ref = { jarId, idx: i };
            unsyncedRefs.push(ref);
            pushPromises.push(
              apiFetchReal({ action: 'addEntry', params: { jarId, userId, amount: entries[i].amount, note: entries[i].note } })
                .then(res => { ref.result = res; ref.ok = true; })
                .catch(() => { ref.ok = false; })
            );
          }
        }
      }

      // 1b. Pending control changes — parallel
      const ctrlResults = pendingCtrl.map(pc =>
        apiFetchReal({ action: 'setControl', params: { memberId: pc.memberId, controlId: pc.controlId, jarId: pc.jarId, userId } })
          .then(() => ({ pc, ok: true }))
          .catch(() => ({ pc, ok: false }))
      );
      pushPromises.push(...ctrlResults);

      // 1c. Pending archives — parallel
      const archResults = pendingArchive.map(pa =>
        apiFetchReal({ action: 'archiveJar', params: { jarId: pa.jarId } })
          .then(() => ({ pa, ok: true }))
          .catch(() => ({ pa, ok: false }))
      );
      pushPromises.push(...archResults);

      // 1d. Pending deletes — parallel
      const delResults = pendingDel.map(pd =>
        apiFetchReal({ action: 'deleteEntry', params: { jarId: pd.jarId, entryId: pd.entryId } })
          .then(() => ({ pd, ok: true }))
          .catch(() => ({ pd, ok: false }))
      );
      pushPromises.push(...delResults);

      // 1e. Pending custom control sync — parallel
      const ctrlSyncResults = pendingCtrlSync.map(pcs => {
        if (pcs.action === 'create' && pcs.data) {
          return apiFetchReal({ action: 'createControl', params: { controlId: pcs.controlId, name: pcs.data.name, emoji: pcs.data.emoji, description: pcs.data.description, ownerId: userId, type: 'custom', items: pcs.data.items } })
            .then(() => ({ pcs, ok: true })).catch(() => ({ pcs, ok: false }));
        } else if (pcs.action === 'update' && pcs.data) {
          return apiFetchReal({ action: 'updateControl', params: { controlId: pcs.controlId, name: pcs.data.name, emoji: pcs.data.emoji, description: pcs.data.description, items: pcs.data.items } })
            .then(() => ({ pcs, ok: true })).catch(() => ({ pcs, ok: false }));
        } else if (pcs.action === 'delete') {
          return apiFetchReal({ action: 'deleteControl', params: { controlId: pcs.controlId } })
            .then(() => ({ pcs, ok: true })).catch(() => ({ pcs, ok: false }));
        }
        return Promise.resolve({ pcs, ok: true });
      });
      pushPromises.push(...ctrlSyncResults);

      // Wait for ALL push operations at once
      await Promise.all(pushPromises);

      // Process results: mark synced entries
      for (const ref of unsyncedRefs) {
        if (ref.ok) {
          const entry = allEntriesMap[ref.jarId][ref.idx];
          allEntriesMap[ref.jarId][ref.idx] = { ...entry, entryId: (ref.result && ref.result.entryId) || entry.entryId, synced: true };
        }
      }
      localStorage.setItem(KEY_ENTRIES, JSON.stringify(allEntriesMap));

      // Process ctrl/archive/del results
      const remainingCtrl = (await Promise.all(ctrlResults)).filter(r => !r.ok).map(r => r.pc);
      savePendingCtrl(remainingCtrl);
      const remainingArchive = (await Promise.all(archResults)).filter(r => !r.ok).map(r => r.pa);
      savePendingArchive(remainingArchive);
      const remainingDel = (await Promise.all(delResults)).filter(r => !r.ok).map(r => r.pd);
      savePendingDel(remainingDel);
      const remainingCtrlSync = (await Promise.all(ctrlSyncResults)).filter(r => !r.ok).map(r => r.pcs);
      savePendingCtrlSync(remainingCtrlSync);

      // 2. Pull ALL data in ONE call (was getJarsByUser + getJarHistory = 2 calls × 5-6 readAll each)
      const [fullSync, serverCustomCtrls] = await Promise.all([
        apiFetchReal({ query: 'getFullSync', params: { userId } }).then(r => r || {}),
        apiFetchReal({ query: 'getCustomControls', params: { userId } }).catch(() => []),
      ]);
      const freshJars = fullSync.jars || [];
      const serverHistories = fullSync.histories || {};

      // Merge custom controls from server (server wins unless pending local sync)
      const pendingCtrlSyncIds = new Set(localPendingCtrlSync().map(p => p.controlId));
      const localCtrls = localCustomControls();
      const mergedCtrls = serverCustomCtrls.filter(sc => !pendingCtrlSyncIds.has(sc.controlId));
      // Keep local-only controls that are pending create
      localCtrls.forEach(lc => {
        if (pendingCtrlSyncIds.has(lc.controlId) && !mergedCtrls.find(m => m.controlId === lc.controlId)) {
          mergedCtrls.push(lc);
        }
      });
      saveCustomControls(mergedCtrls);

      // Save per-jar lastModified for future checkSync comparison
      // If server returned empty jarModified (no mutations yet), generate defaults
      // so checkSync has jarIds to send next time (prevents infinite getFullSync loop)
      let jarMod = fullSync.jarModified || {};
      if (Object.keys(jarMod).length === 0 && freshJars.length > 0) {
        freshJars.forEach(j => { jarMod[j.jarId] = 'init'; });
      }
      localStorage.setItem(KEY_SERVER_MODIFIED, JSON.stringify(jarMod));

      // Re-apply pending archive flags
      const stillPendingArchive = localPendingArchive();
      const pendingArchiveIds = new Set(stillPendingArchive.map(p => p.jarId));

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

      // 3. Merge server histories for ALL jars (no extra getJarHistory call needed)
      const stillPendingDelIds = new Set(localPendingDel().map(p => p.entryId));

      for (const jarInfo of mergedJars) {
        const jarId = jarInfo.jarId;
        const histData = serverHistories[jarId];
        if (!histData) continue;

        const serverEntries = (histData.history || []).map(e => ({
          entryId: e.id, amount: e.amount, note: e.label, createdAt: e.date, synced: true,
          type: e.type || 'entry', icon: e.icon || '💰', contributorName: e.contributorName || '',
          requestAmount: e.requestAmount || 0, feeRate: e.feeRate || 0, feeAmount: e.feeAmount || 0,
          sourceNotes: e.sourceNotes || '',
        }));
        const filteredServerEntries = serverEntries.filter(e => !stillPendingDelIds.has(e.entryId));
        const localE = allEntriesMap[jarId] || [];
        const stillUnsynced = localE.filter(e => !e.synced);
        // 기부 완료 플래그 보존: 로컬에 donated=true였던 entryId 집합
        const localDonatedIds = new Set(localE.filter(e => e.donated).map(e => e.entryId));
        const merged = [...filteredServerEntries, ...stillUnsynced].sort((a, b) => (b.createdAt > a.createdAt ? 1 : -1));
        // 기부 완료 플래그 복원
        if (localDonatedIds.size > 0) {
          merged.forEach(e => { if (localDonatedIds.has(e.entryId)) e.donated = true; });
        }
        saveLocalEntries(jarId, merged);

        // Active jar: update display + detect new donations
        if (currentJar && currentJar.jarId === jarId) {
          const prevDonationIds = new Set(
            localE.filter(e => e.type === 'donation_in' || e.type === 'donation').map(e => e.entryId)
          );
          entryRows = merged;

          const newDonations = filteredServerEntries.filter(
            e => (e.type === 'donation_in' || e.type === 'donation') && !prevDonationIds.has(e.entryId)
          );
          if (newDonations.length > 0 && currentJar.ownerId === userId) {
            showDonationReceivedPopup(newDonations);
          }
        }
      }

      // Update currentJar display
      if (currentJar) {
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
        $('jarLoading').hidden = true;
        $('jarEmpty').hidden   = false;
      }
    } catch (err) {
      if (!silent) toast('동기화 실패: ' + err.message);
      throw err;
    } finally {
      _syncInProgress = false;
      if (syncBtn) { syncBtn.disabled = false; syncBtn.textContent = '서버 동기화'; }
      if (hdrSync) { hdrSync.classList.remove('syncing'); hdrSync.disabled = false; }
    }
  }

  // ── Background Sync ──

  /** Debounced background sync — call after any local mutation that creates divergence. */
  function scheduleBackgroundSync() {
    if (isMock()) return;
    if (_bgSyncTimer) clearTimeout(_bgSyncTimer);
    _bgSyncTimer = setTimeout(async () => {
      _bgSyncTimer = null;
      if (_syncInProgress) return;
      try { await syncWithServer(true); }
      catch { /* silent — manual sync still works */ }
    }, 1500);
  }

  // Sync on visibility change (app comes back to foreground)
  document.addEventListener('visibilitychange', () => {
    if (document.visibilityState !== 'visible') return;
    if (isMock()) return;
    // Check if there are pending local changes
    const allE = JSON.parse(localStorage.getItem(KEY_ENTRIES) || '{}');
    const hasUnsynced = Object.values(allE).some(entries => entries.some(e => !e.synced));
    const hasPending = hasUnsynced ||
      localPendingDel().length > 0 ||
      localPendingCtrl().length > 0 ||
      localPendingArchive().length > 0 ||
      localPendingCtrlSync().length > 0;
    if (hasPending) { scheduleBackgroundSync(); return; }
    // If no pending changes, sync if stale (>5 min since last sync)
    const lastSync = localStorage.getItem(KEY_LAST_SYNC);
    const staleMs = 5 * 60 * 1000;
    if (!lastSync || (Date.now() - new Date(lastSync).getTime()) > staleMs) {
      scheduleBackgroundSync();
    }
  });

  // ── Jar 순환 / picker (CMPA-915, CMPA-926) ──
  $('jarChangeBtn').addEventListener('click', () => {
    const jars = activeJars(cachedJars);
    if (jars.length <= 1) { openJarPicker(); return; }
    const curIdx = currentJar ? jars.findIndex(j => j.jarId === currentJar.jarId) : -1;
    const nextIdx = (curIdx + 1) % jars.length;
    onJarSelect(jars[nextIdx]);
  });

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
    renderPostsSection(jar); // CMPA-933

    // Pull server history for selected jar (merge with local unsynced)
    if (!isMock()) {
      try {
        const histData = await apiFetchReal({ query: 'getJarHistory', params: { jarId: jar.jarId } });
        const serverEntries = (histData.history || [])
          .map(e => ({
            entryId: e.id, amount: e.amount, note: e.label, createdAt: e.date, synced: true,
            type: e.type || 'entry', icon: e.icon || '💰', contributorName: e.contributorName || '',
            requestAmount: e.requestAmount || 0, feeRate: e.feeRate || 0, feeAmount: e.feeAmount || 0,
            sourceNotes: e.sourceNotes || '',
          }));
        const stillUnsynced = entryRows.filter(e => !e.synced);
        // 기부 완료 플래그 보존
        const localDonatedIds = new Set(entryRows.filter(e => e.donated).map(e => e.entryId));
        const merged = [...serverEntries, ...stillUnsynced].sort((a, b) => (b.createdAt > a.createdAt ? 1 : -1));
        if (localDonatedIds.size > 0) {
          merged.forEach(e => { if (localDonatedIds.has(e.entryId)) e.donated = true; });
        }
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
    $('cjImagePreview').hidden = true;
    $('cjImagePreviewImg').src = '';
    $('cjImageAddBtn').hidden = false;
    $('cjImageFile').value = '';
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
    const existingJars = cachedJars || localJars();
    if (existingJars.some(j => j.name === name)) {
      if (!confirm('이미 같은 이름의 Jar가 있습니다. 계속 만드시겠습니까?')) return;
    }
    $('cjSaveBtn').disabled = true;
    try {
      const res = await apiFetch({ action: 'createJar', params: { name, description: desc, goalAmount: goal, ownerId: userId } });
      // Upload jar image if selected
      let imageUrl = '';
      const imageFile = $('cjImageFile').files[0];
      if (imageFile && hasSupabase()) {
        try {
          imageUrl = await window.DreamJarSupabase.uploadJarImage(res.jarId, imageFile);
          await apiFetch({ action: 'updateJarImage', params: { jarId: res.jarId, imageUrl } });
        } catch (imgErr) {
          console.warn('[DreamJar] Image upload failed:', imgErr);
        }
      }
      closeSheet('createJarSheet');
      toast('Jar를 만들었어요!');
      // 새 Jar를 로컬에 추가
      const newJar = { jarId: res.jarId, name, description: desc, goalAmount: goal, currentAmount: 0, ownerId: userId, controlId: '', memberId: '', imageUrl };
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

  // ── Jar 사진 업로드 (만들기) ──
  $('cjImageAddBtn').addEventListener('click', () => $('cjImageFile').click());
  $('cjImageFile').addEventListener('change', (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { toast('사진은 5MB 이하만 가능합니다.'); return; }
    const reader = new FileReader();
    reader.onload = () => {
      $('cjImagePreviewImg').src = reader.result;
      $('cjImagePreview').hidden = false;
      $('cjImageAddBtn').hidden = true;
    };
    reader.readAsDataURL(file);
  });
  $('cjImageRemoveBtn').addEventListener('click', () => {
    $('cjImagePreview').hidden = true;
    $('cjImagePreviewImg').src = '';
    $('cjImageAddBtn').hidden = false;
    $('cjImageFile').value = '';
  });

  // ── Jar 사진 변경 (기존 Jar) ──
  $('jarImageEditBtn').addEventListener('click', () => $('jarImageFileEdit').click());
  $('jarImageFileEdit').addEventListener('change', async (e) => {
    const file = e.target.files[0];
    if (!file) return;
    if (file.size > 5 * 1024 * 1024) { toast('사진은 5MB 이하만 가능합니다.'); return; }
    if (!currentJar || !hasSupabase()) return;
    toast('사진 업로드 중…');
    try {
      const imageUrl = await window.DreamJarSupabase.uploadJarImage(currentJar.jarId, file);
      await apiFetch({ action: 'updateJarImage', params: { jarId: currentJar.jarId, imageUrl } });
      currentJar.imageUrl = imageUrl;
      // Update local cache
      const jars = localJars();
      const idx = jars.findIndex(j => j.jarId === currentJar.jarId);
      if (idx >= 0) { jars[idx].imageUrl = imageUrl; saveLocalJars(jars); }
      renderJarSection(currentJar);
      toast('사진이 변경되었어요!');
    } catch (err) {
      toast('사진 업로드 실패: ' + err.message);
    }
    $('jarImageFileEdit').value = '';
  });

  // ── Jar 이름 변경 (CMPA-915) ──
  $('jarNameEditBtn').addEventListener('click', async () => {
    if (!currentJar) return;
    const newName = prompt('Jar 이름 변경', currentJar.name || '');
    if (newName === null || !newName.trim() || newName.trim() === currentJar.name) return;
    try {
      await apiFetch({ action: 'updateJarName', params: { jarId: currentJar.jarId, name: newName.trim() } });
      currentJar.name = newName.trim();
      const jars = localJars();
      const idx = jars.findIndex(j => j.jarId === currentJar.jarId);
      if (idx >= 0) { jars[idx].name = newName.trim(); saveLocalJars(jars); }
      renderJarSection(currentJar);
      toast('이름이 변경되었어요!');
    } catch (err) {
      toast('이름 변경 실패: ' + err.message);
    }
  });

  // ── Jar 사진 추가 (사진 없을 때, CMPA-915) ──
  $('jarImageAddBtn').addEventListener('click', () => $('jarImageFileEdit').click());

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

    // Show name edit button for owner (CMPA-915)
    $('jarNameEditBtn').hidden = !isOwned;

    // Always show jar change button (CMPA-926: picker fallback for 1 jar)
    $('jarChangeBtn').hidden = false;

    // Show jar image or add-photo button (CMPA-915)
    const imgDisplay = $('mainJarImage');
    const imgEl = $('mainJarImageImg');
    if (jar.imageUrl) {
      imgEl.src = jar.imageUrl;
      imgEl.loading = 'lazy'; // CMPA-919
      imgDisplay.hidden = false;
      $('jarImageEditBtn').hidden = !isOwned;
      $('jarImageAddBtn').hidden = true;
    } else {
      imgDisplay.hidden = true;
      imgEl.src = '';
      $('jarImageAddBtn').hidden = !isOwned;
    }

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
      $('openControlBtn').textContent = '🎯 적립하기';
      return;
    }

    // Joined jar: hide controls, show message
    if (jar.ownerId !== userId) {
      $('controlDisplay').hidden = true;
      $('controlEmpty').hidden   = false;
      const emptyMsg = $('controlEmpty').querySelector('.ctrl-empty-msg');
      if (emptyMsg) emptyMsg.textContent = '참여 중인 Jar입니다.';
      $('openControlBtn').textContent = '🎯 적립하기';
      return;
    }

    // Reset message for own jars
    const emptyMsg2 = $('controlEmpty').querySelector('.ctrl-empty-msg');
    if (emptyMsg2) emptyMsg2.textContent = 'Control을 먼저 선택하세요.';

    const ctrl = findControl(jar.controlId);
    $('controlEmpty').hidden   = true;
    $('controlDisplay').hidden = false;

    if (ctrl) {
      $('mainCtrlName').textContent = ctrl.emoji + ' ' + ctrl.name;
      $('mainRewardSection').hidden = false;
      renderRewardButtons(ctrl, entries || [], $('mainRewardList'));
      // CMPA-947: 메인 버튼에 Control 이름 표시
      $('openControlBtn').textContent = ctrl.emoji + ' 적립하기';
      $('controlActionTitle').textContent = ctrl.emoji + ' ' + ctrl.name;
    } else {
      $('mainCtrlName').textContent = '선택 안 됨';
      $('mainRewardSection').hidden = true;
      $('openControlBtn').textContent = '🎯 적립하기';
      $('controlActionTitle').textContent = '적립하기';
      // No control selected: show empty state
      $('controlEmpty').hidden   = false;
      $('controlDisplay').hidden = true;
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

  // CMPA-947: 적립하기 버튼 → Control 시트 열기
  $('openControlBtn').addEventListener('click', () => {
    if (!currentJar) { toast('먼저 Jar를 선택하세요.'); return; }
    renderControlSection(currentJar, localEntries(currentJar.jarId));
    openSheet('controlActionSheet');
  });

  // Control 미선택 시 시트 내 "Control 선택" 버튼
  $('pickControlFromActionBtn').addEventListener('click', () => {
    openControlPicker();
  });

  // Control 변경 버튼
  $('ctrlChangeBtn').addEventListener('click', openControlPicker);

  function openControlPicker() {
    renderControlPickerList();
    openSheet('controlPickerSheet');
  }

  function renderControlPickerList() {
    const listEl = $('controlPickerList');
    const activeCtrlId = currentJar && currentJar.controlId;
    const builtIn = ADMIN_CONTROLS;
    const custom = localCustomControls();

    let html = '';
    // Built-in controls
    builtIn.forEach(c => {
      const isActive = c.controlId === activeCtrlId;
      const desc = c.description || (c.controlId === 'ctrl_ca' ? '학업·루틴·마일스톤 달성 보상' : '');
      html += `<div class="cp-custom-row">
        <button class="cp-item${isActive ? ' active' : ''}" data-control-id="${escHtml(c.controlId)}" type="button">
          <span class="cp-emoji">${c.emoji}</span>
          <span class="cp-body">
            <span class="cp-name">${escHtml(c.name)}</span>
            <span class="cp-desc">${escHtml(desc)}</span>
          </span>
        </button>
        <button class="cp-fork-btn" data-fork-ctrl-id="${escHtml(c.controlId)}" type="button" title="복제하여 내 컨트롤 만들기">📋</button>
      </div>`;
    });

    // Custom controls
    if (custom.length > 0) {
      html += '<div class="cp-section-title">내 컨트롤</div>';
      custom.forEach(c => {
        const isActive = c.controlId === activeCtrlId;
        html += `<div class="cp-custom-row">
          <button class="cp-item${isActive ? ' active' : ''}" data-control-id="${escHtml(c.controlId)}" type="button">
            <span class="cp-emoji">${escHtml(c.emoji || '🎯')}</span>
            <span class="cp-body">
              <span class="cp-name">${escHtml(c.name)}</span>
              <span class="cp-desc">${escHtml(c.description || '')}</span>
            </span>
          </button>
          <button class="cp-edit-btn" data-edit-ctrl-id="${escHtml(c.controlId)}" type="button" title="편집">✏️</button>
        </div>`;
      });
    }

    listEl.innerHTML = html;

    // Bind select
    listEl.querySelectorAll('.cp-item').forEach(el => {
      el.addEventListener('click', () => onControlSelect(el.dataset.controlId));
    });
    // Bind edit
    listEl.querySelectorAll('.cp-edit-btn').forEach(el => {
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        closeSheet('controlPickerSheet');
        openCustomCtrlEditor(el.dataset.editCtrlId);
      });
    });
    // Bind fork (clone built-in template as new custom control)
    listEl.querySelectorAll('.cp-fork-btn').forEach(el => {
      el.addEventListener('click', (e) => {
        e.stopPropagation();
        closeSheet('controlPickerSheet');
        forkControlAsCustom(el.dataset.forkCtrlId);
      });
    });
  }

  // "내 컨트롤 만들기" 버튼
  $('createCustomCtrlBtn').addEventListener('click', () => {
    closeSheet('controlPickerSheet');
    openCustomCtrlEditor(null);
  });

  // Fork: 기존 템플릿을 복제하여 내 컨트롤로 만들기
  function forkControlAsCustom(controlId) {
    const src = allControls().find(c => c.controlId === controlId);
    if (!src) return;
    _editingCtrlId = null; // create mode
    $('customCtrlSheetTitle').textContent = '템플릿에서 만들기';
    $('ccName').value = src.name + ' (내 버전)';
    setPickedEmoji(src.emoji || '🎯');
    $('ccDesc').value = src.description || '';
    // Deep-clone items with new IDs to avoid conflicts
    _editingCtrlItems = (src.items || []).map(item => ({
      ...item,
      id: 'ci_' + Date.now() + '_' + Math.floor(Math.random() * 1e6),
    }));
    $('ccDeleteBtn').hidden = true;
    $('ccSaveBtn').textContent = '만들기';
    renderCCItemList();
    closeEmojiPicker();
    openSheet('customCtrlSheet');
  }

  // ── 커스텀 컨트롤 에디터 ──
  function openCustomCtrlEditor(controlId) {
    if (controlId) {
      // Edit mode
      _editingCtrlId = controlId;
      const ctrl = localCustomControls().find(c => c.controlId === controlId);
      if (!ctrl) return;
      $('customCtrlSheetTitle').textContent = '컨트롤 편집';
      $('ccName').value = ctrl.name || '';
      setPickedEmoji(ctrl.emoji || '🎯');
      $('ccDesc').value = ctrl.description || '';
      _editingCtrlItems = (ctrl.items || []).map(i => ({ ...i }));
      $('ccDeleteBtn').hidden = false;
      $('ccSaveBtn').textContent = '저장';
    } else {
      // Create mode
      _editingCtrlId = null;
      $('customCtrlSheetTitle').textContent = '내 컨트롤 만들기';
      $('ccName').value = '';
      setPickedEmoji('🎯');
      $('ccDesc').value = '';
      _editingCtrlItems = [];
      $('ccDeleteBtn').hidden = true;
      $('ccSaveBtn').textContent = '만들기';
    }
    renderCCItemList();
    closeEmojiPicker();
    openSheet('customCtrlSheet');
  }

  // ── 이모지 피커 ──
  const EMOJI_CATEGORIES = [
    { icon: '😀', label: '표정', emojis: '😀😃😄😁😆😅🤣😂🙂😊😇🥰😍🤩😘😗😚😋😛😝😜🤪🤨🧐🤓😎🥳🤗🤔😐😑😶🙄😏😣😥😮😯😲😳🥺😦😧😨😰😢😭😤😠😡🤬🥱😴💀👻👽🤖😺😸😻' },
    { icon: '👋', label: '손·사람', emojis: '👋🤚🖐✋🖖👌🤌🤏✌🤞🤟🤘🤙👈👉👆👇☝👍👎✊👊🤛🤜👏🙌👐🤝🙏💪🦵🦶👶👧🧒👦👩🧑👨🧓👴👵' },
    { icon: '🐶', label: '동물', emojis: '🐶🐱🐭🐹🐰🦊🐻🐼🐨🐯🦁🐮🐷🐸🐵🙈🙉🙊🐒🐔🐧🐦🐤🦆🦅🦉🦇🐺🐗🐴🦄🐝🐛🦋🐌🐞🐜🪲🐢🐍🦎🦖🦕🐙🦑🦐🦞🦀🐡🐠🐟🐬🐳🐋🦈🐊🐅🐆🦓🦍' },
    { icon: '🍎', label: '음식', emojis: '🍎🍐🍊🍋🍌🍉🍇🍓🫐🍈🍒🍑🥭🍍🥥🥝🍅🥑🥦🥬🥒🌶🫑🌽🥕🧄🧅🥔🍠🥐🥯🍞🥖🥨🧀🥚🍳🥞🧇🥓🥩🍗🍖🌭🍔🍟🍕🫓🥪🌮🌯🫔🥗🥘🫕🍝🍜🍲🍛🍣🍱🥟🍤🍙🍚🍘🍥🥮🍢🍡🍧🍨🍦🥧🧁🍰🎂🍮🍭🍬🍫🍿🍩🍪🌰🥜☕🍵🧋🍺🍻🥂🍷🍸🍹🧃🥤🧊' },
    { icon: '⚽', label: '활동', emojis: '⚽🏀🏈⚾🥎🎾🏐🏉🥏🎱🏓🏸🏒🥅⛳🏹🎣🤿🥊🥋🎽🛹🛼🛷⛸🥌🎿⛷🏂🪂🏋🤼🤸🤺⛹🏌🏇🧘🏄🏊🤽🚣🧗🚵🚴🏆🥇🥈🥉🏅🎖🏵🎗🎫🎪🎭🎨🎬🎤🎧🎼🎹🥁🎷🎺🎸🪕🎻🎲♟🎯🎳🎮🎰🧩' },
    { icon: '🚗', label: '여행', emojis: '🚗🚕🚙🚌🚎🏎🚓🚑🚒🚐🛻🚚🚛🚜🛵🏍🚲🛴🚏🛣🛤🛞⛽🚨🚥🚦🛑🚧⚓⛵🛶🚤🛳⛴🛥🚢✈🛩🛫🛬🪂💺🚁🚟🚠🚡🛰🚀🛸🌍🌎🌏🗺🧭🏔⛰🌋🗻🏕🏖🏜🏝🏞🏟🏛🏗🧱🪨🪵🛖🏘🏚🏠🏡🏢🏣🏤🏥🏦🏨🏩🏪🏫🏬🏭🏯🏰💒🗼🗽⛪🕌🛕🕍⛩🕋⛲⛺🌁🌃🏙🌄🌅🌆🌇🌉♨🎠🎡🎢💈🎪' },
    { icon: '💡', label: '사물', emojis: '💡🔦🕯🪔🧯🛢💰💳💎⚖🪜🧲🪄🧪🧫🔬🔭📡🛡🪚🔧🪛🔩⚙🗜⚖🔗⛓🪝🧰🧲💊💉🩸🩹🩺🌡🪥🪒🚿🛁🧹🧺🧻🪣🧽📱💻⌨🖥🖨🖱🖲💽💾💿📀🎥📷📸📹📼🔍🔎📚📖📝📅📌📎📏📐✂🗑🔒🔑🗝' },
    { icon: '❤', label: '기호', emojis: '❤🧡💛💚💙💜🖤🤍🤎💔❣💕💞💓💗💖💘💝⭐🌟✨⚡🔥💥☀🌈☁🌧⛈🌩🌨❄☃⛄🌬💨🌊💧💦☔⛱🌀🌪🌤⛅🌥🌦🎄🎆🎇🧨✨🎈🎉🎊🎋🎍🎎🎏🎐🎑🧧🎀🎁🎗🎟🎫♻💯🔴🟠🟡🟢🔵🟣⚫⚪🟤✅❌❓❗‼⁉⬆↗➡↘⬇↙⬅↖↕↔' },
  ];

  function setPickedEmoji(emoji) {
    $('ccEmoji').value = emoji;
    $('ccEmojiPreview').textContent = emoji;
  }

  function closeEmojiPicker() {
    $('emojiPickerPopup').hidden = true;
  }

  (function initEmojiPicker() {
    const tabsEl = $('emojiPickerTabs');
    const gridEl = $('emojiPickerGrid');
    let activeIdx = 0;

    EMOJI_CATEGORIES.forEach((cat, i) => {
      const tab = document.createElement('span');
      tab.className = 'emoji-tab' + (i === 0 ? ' active' : '');
      tab.textContent = cat.icon;
      tab.title = cat.label;
      tab.addEventListener('click', () => showCategory(i));
      tabsEl.appendChild(tab);
    });

    function showCategory(idx) {
      activeIdx = idx;
      tabsEl.querySelectorAll('.emoji-tab').forEach((t, i) => t.classList.toggle('active', i === idx));
      const emojis = [...EMOJI_CATEGORIES[idx].emojis];
      gridEl.innerHTML = '';
      emojis.forEach(em => {
        const cell = document.createElement('span');
        cell.className = 'emoji-cell';
        cell.textContent = em;
        cell.addEventListener('click', () => {
          setPickedEmoji(em);
          closeEmojiPicker();
        });
        gridEl.appendChild(cell);
      });
      gridEl.scrollTop = 0;
    }

    $('ccEmojiBtn').addEventListener('click', (e) => {
      e.stopPropagation();
      const popup = $('emojiPickerPopup');
      if (!popup.hidden) { popup.hidden = true; return; }
      showCategory(activeIdx);
      popup.hidden = false;
    });

    document.addEventListener('click', (e) => {
      const popup = $('emojiPickerPopup');
      if (!popup.hidden && !popup.contains(e.target) && e.target !== $('ccEmojiBtn')) {
        popup.hidden = true;
      }
    });

    showCategory(0);
  })();

  function renderCCItemList() {
    const listEl = $('ccItemList');
    if (_editingCtrlItems.length === 0) {
      listEl.innerHTML = '<p class="cc-item-empty">아이템이 없어요. 추가해 보세요.</p>';
      return;
    }
    listEl.innerHTML = _editingCtrlItems.map((item, idx) => {
      const typeLabel = item.type === 'milestone' ? '마일스톤' : '루틴';
      return `<div class="cc-item-row">
        <div class="cc-item-info">
          <span class="cc-item-name">${escHtml(item.label)}</span>
          <span class="cc-item-meta">${typeLabel} · ${won(item.amount)}</span>
        </div>
        <button class="cc-item-edit-btn" data-cc-idx="${idx}" type="button">✏️</button>
        <button class="cc-item-del-btn" data-cc-idx="${idx}" type="button">🗑️</button>
      </div>`;
    }).join('');
    listEl.querySelectorAll('.cc-item-edit-btn').forEach(btn => {
      btn.addEventListener('click', () => openCCItemEditor(Number(btn.dataset.ccIdx)));
    });
    listEl.querySelectorAll('.cc-item-del-btn').forEach(btn => {
      btn.addEventListener('click', () => {
        _editingCtrlItems.splice(Number(btn.dataset.ccIdx), 1);
        renderCCItemList();
      });
    });
  }

  // Add item button
  $('ccAddItemBtn').addEventListener('click', () => openCCItemEditor(-1));

  let _editingItemIdx = -1; // -1 = new, >= 0 = editing existing
  function openCCItemEditor(idx) {
    _editingItemIdx = idx;
    if (idx >= 0 && _editingCtrlItems[idx]) {
      const item = _editingCtrlItems[idx];
      $('ccItemSheetTitle').textContent = '아이템 편집';
      $('cciLabel').value = item.label || '';
      $('cciAmount').value = item.amount || '';
      $('cciType').value = item.type === 'milestone' ? 'milestone' : 'routine';
      $('cciSaveBtn').textContent = '저장';
    } else {
      $('ccItemSheetTitle').textContent = '아이템 추가';
      $('cciLabel').value = '';
      $('cciAmount').value = '';
      $('cciType').value = 'routine';
      $('cciSaveBtn').textContent = '추가';
    }
    openSheet('ccItemSheet');
    setTimeout(() => $('cciLabel').focus(), 300);
  }

  $('cciSaveBtn').addEventListener('click', () => {
    const label = $('cciLabel').value.trim();
    const amount = Number(String($('cciAmount').value).replace(/[^0-9]/g, ''));
    const type = $('cciType').value;
    if (!label) { toast('이름을 입력하세요.'); return; }
    if (!amount || amount <= 0) { toast('금액을 입력하세요.'); return; }
    const item = {
      id: (_editingItemIdx >= 0 && _editingCtrlItems[_editingItemIdx])
        ? _editingCtrlItems[_editingItemIdx].id
        : 'ci_' + Date.now() + '_' + Math.floor(Math.random() * 1e4),
      label,
      amount,
      type,
      subtype: type === 'milestone' ? 'once' : 'per_day',
      once: type === 'milestone',
    };
    if (_editingItemIdx >= 0) {
      _editingCtrlItems[_editingItemIdx] = item;
    } else {
      _editingCtrlItems.push(item);
    }
    closeSheet('ccItemSheet');
    renderCCItemList();
  });

  // Save custom control
  $('ccSaveBtn').addEventListener('click', () => {
    const name = $('ccName').value.trim();
    const emoji = $('ccEmoji').value.trim() || '🎯';
    const desc = $('ccDesc').value.trim();
    if (!name) { toast('이름을 입력하세요.'); $('ccName').focus(); return; }
    if (_editingCtrlItems.length === 0) { toast('아이템을 하나 이상 추가하세요.'); return; }

    const controlId = _editingCtrlId || ('ctrl_' + Date.now() + '_' + Math.floor(Math.random() * 1e6));
    const ctrl = { controlId, name, emoji, description: desc, items: _editingCtrlItems, type: 'custom' };
    saveCustomControl(ctrl);
    closeSheet('customCtrlSheet');
    toast(_editingCtrlId ? '컨트롤을 수정했어요.' : '컨트롤을 만들었어요.');
    // If this control is active on current jar, re-render
    if (currentJar && currentJar.controlId === controlId) {
      renderControlSection(currentJar, entryRows);
    }
    scheduleBackgroundSync();
  });

  // Delete custom control
  $('ccDeleteBtn').addEventListener('click', () => {
    if (!_editingCtrlId) return;
    if (!confirm('이 컨트롤을 삭제할까요?')) return;
    deleteCustomControl(_editingCtrlId);
    // If active on current jar, clear it
    if (currentJar && currentJar.controlId === _editingCtrlId) {
      currentJar.controlId = '';
      const jars = localJars();
      const lj = jars.find(j => j.jarId === currentJar.jarId);
      if (lj) { lj.controlId = ''; saveLocalJars(jars); }
      renderControlSection(currentJar, entryRows);
    }
    closeSheet('customCtrlSheet');
    toast('컨트롤을 삭제했어요.');
    scheduleBackgroundSync();
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
    scheduleBackgroundSync();
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
    scheduleBackgroundSync();
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
    scheduleBackgroundSync();
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
    scheduleBackgroundSync();
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

  // CMPA-934: Share public jar link
  $('shareJarBtn').addEventListener('click', () => {
    if (!currentJar) return;
    const url = window.location.origin + window.location.pathname + '?jar=' + encodeURIComponent(currentJar.jarId);
    if (navigator.share) {
      navigator.share({ title: currentJar.name + ' — DreamJar', url }).catch(() => {});
    } else if (navigator.clipboard) {
      navigator.clipboard.writeText(url).then(() => toast('링크가 복사되었어요!')).catch(() => toast(url));
    } else {
      prompt('공유 링크:', url);
    }
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
    const sourceNote = d.sourceNotes || '';
    const bossImg = feePct >= 25 ? './raccoon_boss_angry.gif' : './raccoon_boss.jpg';
    let html = `<div class="dr-recv-img"><img src="${bossImg}" alt="너구리사장"></div>`;
    html += `<div class="dr-recv-from">💌 <strong>${from}</strong> 에서 기부가 왔어요!</div>`;
    if (sourceNote) {
      html += `<div class="dr-source-note">💡 "${escHtml(displayNote(sourceNote))}" 에서 기부</div>`;
    }
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

  // ── 기부 탭 전환 ──
  let _activeDonateTab = 'amount';

  function switchDonateTab(tab) {
    _activeDonateTab = tab;
    document.querySelectorAll('.donate-tab-btn').forEach(btn => {
      btn.classList.toggle('active', btn.dataset.donateTab === tab);
    });
    document.querySelectorAll('.donate-tab-content').forEach(el => {
      el.hidden = el.dataset.donateTab !== tab;
    });
  }

  document.querySelectorAll('.donate-tab-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      switchDonateTab(btn.dataset.donateTab);
      if (btn.dataset.donateTab === 'entries') renderDonateBulkList();
    });
  });

  // ── 기부 내역 선택 (벌크) ──
  let _donateBulkSelected = new Set(); // entryIds

  function renderDonateBulkList() {
    const listEl = $('donateBulkList');
    const myJar = cachedJars.find(j => j.ownerId === userId);
    if (!myJar) { listEl.innerHTML = '<p class="hist-empty">내 Jar가 없어요.</p>'; return; }

    const allMyEntries = localEntries(myJar.jarId);
    // donation_out의 sourceNotes로 이미 기부된 항목 식별 (서버 동기화 후에도 유지)
    const donatedNotes = new Set();
    allMyEntries.forEach(e => {
      if (e.type === 'donation_out' && e.sourceNotes) donatedNotes.add(e.sourceNotes);
    });
    const entries = allMyEntries.filter(e => {
      const type = e.type || 'entry';
      if (type !== 'entry' || (Number(e.amount) || 0) <= 0) return false;
      if (e.donated) return false;
      // sourceNotes 매칭: 기부 발신 기록에 이 항목의 note가 있으면 이미 기부됨
      if (e.note && donatedNotes.has(e.note)) return false;
      return true;
    });

    if (entries.length === 0) {
      listEl.innerHTML = '<p class="hist-empty">기부할 적립 내역이 없어요.</p>';
      return;
    }

    _donateBulkSelected = new Set();
    listEl.innerHTML = entries.map(e => {
      const amt = Number(e.amount) || 0;
      const note = displayNote(e.note) || '적립';
      return `<label class="donate-bulk-item">
        <input type="checkbox" class="donate-bulk-cb" data-entry-id="${escHtml(e.entryId)}" data-amount="${amt}" data-note="${escHtml(e.note || '')}">
        <span class="donate-bulk-label">${escHtml(note)}</span>
        <span class="donate-bulk-date">${fmtDate(e.createdAt)}</span>
        <span class="donate-bulk-amt">${won(amt)}</span>
      </label>`;
    }).join('');

    listEl.querySelectorAll('.donate-bulk-cb').forEach(cb => {
      cb.addEventListener('change', () => {
        if (cb.checked) _donateBulkSelected.add(cb.dataset.entryId);
        else _donateBulkSelected.delete(cb.dataset.entryId);
        updateDonateBulkSummary();
      });
    });

    updateDonateBulkSummary();
  }

  function updateDonateBulkSummary() {
    const sumEl = $('donateBulkSummary');
    if (_donateBulkSelected.size === 0) {
      sumEl.hidden = true;
      return;
    }
    let total = 0;
    document.querySelectorAll('.donate-bulk-cb:checked').forEach(cb => {
      total += Number(cb.dataset.amount) || 0;
    });
    $('donateBulkCount').textContent = _donateBulkSelected.size + '건';
    $('donateBulkTotal').textContent = won(total);
    sumEl.hidden = false;
  }

  // ── 벌크 기부 제출 ──
  $('donateBulkSubmitBtn').addEventListener('click', async () => {
    if (_donateBulkSelected.size === 0) { toast('기부할 항목을 선택하세요.'); return; }
    const myJar = cachedJars.find(j => j.ownerId === userId);
    if (!myJar) return;

    const items = [];
    document.querySelectorAll('.donate-bulk-cb:checked').forEach(cb => {
      items.push({
        entryId: cb.dataset.entryId,
        amount: Number(cb.dataset.amount) || 0,
        note: cb.dataset.note || '',
      });
    });

    // 잔액 체크: 기부 총액이 잔액을 초과하면 차단
    const totalDonateAmt = items.reduce((s, i) => s + i.amount, 0);
    const curBalance = Number(myJar.currentAmount) || 0;
    if (totalDonateAmt > curBalance) {
      toast(`잔액 부족! 잔액 ${won(curBalance)}, 기부 ${won(totalDonateAmt)}`);
      return;
    }

    $('donateBulkSubmitBtn').disabled = true;
    try {
      const res = await apiFetch({ action: 'donateBulk', params: {
        fromJarId: myJar.jarId,
        toJarId: currentJar.jarId,
        items,
      }});
      const bulkMsg = ($('donateBulkMessage').value || '').trim();
      closeSheet('donateSheet');
      // Auto-post cheer message to recipient jar's board
      if (bulkMsg && hasSupabase()) {
        try {
          await DreamJarSupabase.api({ action: 'createPost', params: {
            jarId: currentJar.jarId,
            authorId: userId,
            guestName: '',
            content: '💝 ' + bulkMsg + '\n💰 기부 ' + won(res.totalRequest) + ' → 🦝 너구리사장 수수료 ' + won(res.totalFee) + ' → 실제 도착 ' + won(res.totalNet),
          }});
        } catch (e) { console.warn('[DreamJar] 응원 메시지 게시 실패:', e.message); }
      }

      // Show bulk result
      let html = '';
      (res.items || []).forEach(item => {
        const feePct = Math.round((item.feeRate || 0) * 100);
        const note = displayNote(item.note) || '적립';
        html += `<div class="dr-bulk-item">
          <div class="dr-bulk-note">${escHtml(note)}</div>
          <div class="dr-row"><span>금액</span><span>${won(item.amount)}</span></div>
          <div class="dr-row dr-fee"><span>🦝 수수료 (${feePct}%)</span><span>-${won(item.feeAmount)}</span></div>
          <div class="dr-row dr-net"><span>전달</span><span>${won(item.netAmount)}</span></div>
        </div>`;
      });
      html += `<div class="dr-bulk-total">
        <div class="dr-row"><span>총 기부</span><span>${won(res.totalRequest)}</span></div>
        <div class="dr-row dr-fee"><span>🦝 총 수수료</span><span>-${won(res.totalFee)}</span></div>
        <div class="dr-row dr-net"><span>총 전달 금액</span><span>${won(res.totalNet)}</span></div>
      </div>`;
      $('donateResultBody').innerHTML = '';
      $('donateResultBulk').innerHTML = html;
      $('donateResultBulk').hidden = false;
      openSheet('donateResultSheet');

      // Update local data — add donation_out entries for sender
      const ts = new Date().toISOString();
      const myEntries = localEntries(myJar.jarId);
      const toEntries = localEntries(currentJar.jarId);
      let totalReq = 0;
      (res.items || []).forEach(item => {
        totalReq += item.amount;
        const feePct = Math.round((item.feeRate || 0) * 100);
        myEntries.unshift({
          entryId: item.donationId, amount: -item.amount,
          note: '기부 발신 (수수료 ' + feePct + '%)',
          createdAt: ts, synced: true,
          type: 'donation_out', icon: '↗️', contributorName: currentJar.name || '',
          sourceNotes: item.note || '',
        });
        toEntries.unshift({
          entryId: item.donationId + '_in', amount: item.netAmount,
          note: `기부(${won(item.amount)}, 수수료${feePct}%)`,
          createdAt: ts, synced: true,
          type: 'donation_in', icon: '🦝', contributorName: myJar.name || '',
          requestAmount: item.amount, feeRate: item.feeRate || 0, feeAmount: item.feeAmount || 0,
          sourceNotes: item.note || '',
        });
      });
      // 기부한 원본 항목을 donated로 마킹 (재기부 방지)
      const donatedIds = new Set(items.map(i => i.entryId));
      myEntries.forEach(e => { if (donatedIds.has(e.entryId)) e.donated = true; });
      saveLocalEntries(myJar.jarId, myEntries);
      saveLocalEntries(currentJar.jarId, toEntries);
      // Update my jar amount
      myJar.currentAmount = Math.max(0, (Number(myJar.currentAmount) || 0) - totalReq);
      const jars = localJars();
      const lj = jars.find(j => j.jarId === myJar.jarId);
      if (lj) { lj.currentAmount = myJar.currentAmount; saveLocalJars(jars); }
      if (currentJar.jarId === myJar.jarId) updateJarDisplay(myJar);
      cachedJars = activeJars(localJars());
      scheduleBackgroundSync();
    } catch (err) {
      toast('기부 실패: ' + err.message);
    } finally {
      $('donateBulkSubmitBtn').disabled = false;
    }
  });

  // ── 기부 버튼 ──
  $('donateBtn').addEventListener('click', () => {
    if (!currentJar) return;
    const myJar = cachedJars.find(j => j.ownerId === userId);
    if (!myJar) { toast('내 Jar가 없어 기부할 수 없어요.'); return; }
    $('donateFrom').textContent = myJar.name;
    $('donateTo').textContent = currentJar.name;
    const bal = Number(myJar.currentAmount) || 0;
    $('donateBalance').textContent = `잔액: ${won(bal)}`;
    $('donateAmount').value = '';
    $('donateAmount').max = bal;
    $('donateMessage').value = '';
    $('donateBulkMessage').value = '';
    _donateBulkSelected = new Set();
    switchDonateTab('amount');
    openSheet('donateSheet');
    setTimeout(() => $('donateAmount').focus(), 300);
  });

  $('donateSubmitBtn').addEventListener('click', async () => {
    const amount = Number(String($('donateAmount').value).replace(/[^0-9]/g, ''));
    if (!amount || amount <= 0) { toast('금액을 입력하세요.'); return; }
    const myJar = cachedJars.find(j => j.ownerId === userId);
    if (myJar && amount > (Number(myJar.currentAmount) || 0)) {
      toast(`잔액 부족! 잔액 ${won(Number(myJar.currentAmount) || 0)}`);
      return;
    }
    if (!myJar) return;
    $('donateSubmitBtn').disabled = true;
    try {
      const res = await apiFetch({ action: 'donate', params: {
        fromJarId: myJar.jarId,
        toJarId: currentJar.jarId,
        amount,
      }});
      const donateMsg = ($('donateMessage').value || '').trim();
      closeSheet('donateSheet');
      // Auto-post cheer message to recipient jar's board
      if (donateMsg && hasSupabase()) {
        try {
          await DreamJarSupabase.api({ action: 'createPost', params: {
            jarId: currentJar.jarId,
            authorId: userId,
            guestName: '',
            content: '💝 ' + donateMsg + '\n💰 기부 ' + won(amount) + ' → 🦝 너구리사장 수수료 ' + won(res.feeAmount) + ' (' + Math.round((res.feeRate || 0) * 100) + '%) → 실제 도착 ' + won(res.netAmount),
          }});
        } catch (e) { console.warn('[DreamJar] 응원 메시지 게시 실패:', e.message); }
      }
      // Show result
      const feePct = Math.round((res.feeRate || 0) * 100);
      $('donateResultBody').innerHTML =
        `<div class="dr-row"><span>기부 요청</span><span>${won(amount)}</span></div>` +
        `<div class="dr-row dr-fee"><span>🦝 너구리사장 수수료 (${feePct}%)</span><span>-${won(res.feeAmount)}</span></div>` +
        `<div class="dr-row dr-net"><span>실제 전달 금액</span><span>${won(res.netAmount)}</span></div>`;
      $('donateResultBulk').innerHTML = '';
      $('donateResultBulk').hidden = true;
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
      scheduleBackgroundSync();
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
      // 기부 수신 내역: "기부(원래금액, 수수료N%)" 형식 + sourceNotes
      let noteDisplay = displayNote(e.note);
      if (isDonationIn) {
        const reqAmt = Number(e.requestAmount) || 0;
        const feePct = Math.round((Number(e.feeRate) || 0) * 100);
        if (reqAmt > 0) {
          noteDisplay = `기부(${won(reqAmt)}, 수수료${feePct}%)`;
        }
      }
      const srcNote = e.sourceNotes ? displayNote(e.sourceNotes) : '';
      const srcNoteHtml = srcNote
        ? `<div class="hist-src-note">📎 ${escHtml(srcNote)}</div>`
        : '';
      return `<div class="hist-row${isDonation ? ' hist-donation' : ''}">
        <div class="hist-left">
          <div class="hist-label">${icon} ${escHtml(noteDisplay)}</div>
          ${srcNoteHtml}
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
    if (hasSupabase()) console.info('[DreamJar] Supabase 백엔드 연동됨');
    else console.info('[DreamJar] Supabase 미로드 → 샘플 데이터 모드');

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
      } else if (hasSupabase()) {
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
    renderPostsSection(jar); // CMPA-933

    updateLastSyncDisplay();
  }

  // ── CMPA-933: 게시판(Posts) + 댓글(Comments) + 응원(Cheers) ──

  let _postsCache = [];       // 현재 jar 게시글 캐시
  let _cheersCache = [];      // 현재 jar 응원 캐시
  let _currentPostId = null;  // 상세 보기 중인 게시글

  /** 현재 사용자가 이 jar의 멤버인지 확인 */
  function isMemberOfJar(jar) {
    if (!jar || !userId) return false;
    return jar.ownerId === userId || jar.role === 'member' || jar.role === 'owner';
  }

  /** 게시판 섹션 렌더링 (CMPA-951: jarDisplay 내부로 이동) */
  async function renderPostsSection(jar) {
    const section = $('postsHeader');
    if (!jar) { if (section) section.hidden = true; return; }
    if (section) section.hidden = false;

    // 멤버가 아닌 경우 guest 닉네임 필드 표시 (글쓰기 시트에서)
    const isMember = isMemberOfJar(jar);

    // 서버에서 불러오기
    if (hasSupabase()) {
      try {
        _postsCache = await DreamJarSupabase.api({ query: 'getPosts', params: { jarId: jar.jarId } });
        _cheersCache = await DreamJarSupabase.api({ query: 'getCheers', params: { jarId: jar.jarId } });
      } catch (err) {
        console.warn('[DreamJar] 게시글 로드 실패:', err.message);
        _postsCache = [];
        _cheersCache = [];
      }
    }

    renderCheerSummary();
    renderPostsList();
  }

  function renderCheerSummary() {
    const el = $('cheerSummary');
    if (!_cheersCache || _cheersCache.length === 0) { el.hidden = true; return; }

    // 이모지별 카운트
    const counts = {};
    _cheersCache.forEach(c => { counts[c.emoji] = (counts[c.emoji] || 0) + 1; });

    el.innerHTML = Object.entries(counts)
      .sort((a, b) => b[1] - a[1])
      .map(([emoji, cnt]) =>
        `<span class="cheer-badge">${emoji} <span class="cheer-badge-count">${cnt}</span></span>`
      ).join('');
    el.hidden = false;
  }

  function renderPostsList() {
    // CMPA-944: 게시판 전체화면에서 날짜별 그룹핑으로 렌더
    renderBoardPostsList();
  }

  /** CMPA-944: 게시판 전체화면 열기 */
  function openBoardScreen() {
    renderBoardPostsList();
    $('boardScreen').hidden = false;
  }

  /** CMPA-944: 게시판 전체화면 닫기 */
  function closeBoardScreen() {
    $('boardScreen').hidden = true;
  }

  /** CMPA-944: 날짜별 그룹핑 렌더 */
  function renderBoardPostsList() {
    const listEl = $('boardPostsList');
    if (!_postsCache || _postsCache.length === 0) {
      listEl.innerHTML = '<p class="posts-empty">아직 글이 없어요.</p>';
      return;
    }

    // 날짜별 그룹핑
    const groups = {};
    _postsCache.forEach(p => {
      const dateKey = p.createdAt ? p.createdAt.slice(0, 10) : 'unknown';
      if (!groups[dateKey]) groups[dateKey] = [];
      groups[dateKey].push(p);
    });

    // 날짜 내림차순 정렬
    const sortedKeys = Object.keys(groups).sort((a, b) => b.localeCompare(a));

    let html = '';
    sortedKeys.forEach(dateKey => {
      const d = new Date(dateKey + 'T00:00:00');
      const label = isNaN(d.getTime()) ? dateKey : `${d.getMonth() + 1}월 ${d.getDate()}일`;
      html += `<div class="board-date-header">${label}</div>`;
      groups[dateKey].forEach(p => {
        const authorLabel = p.authorId
          ? `<span class="post-author">${escHtml(p.authorName || p.authorId)}</span>`
          : `<span class="post-author-guest">${escHtml(p.guestName || '익명')}</span>`;
        const cmtCount = (p.comments || []).length;
        const rxnHtml = renderReactionBadges(p.reactions || []);
        html += `<div class="board-post-card" data-post-id="${escHtml(p.postId)}">
          ${authorLabel}
          <div class="post-body">${escHtml(p.content || '')}</div>
          ${rxnHtml}
          <div class="post-meta">
            ${cmtCount > 0 ? `<span class="post-comment-count">💬 ${cmtCount}</span>` : ''}
          </div>
        </div>`;
      });
    });

    listEl.innerHTML = html;
    listEl.querySelectorAll('.board-post-card').forEach(card => {
      card.addEventListener('click', () => openPostDetail(card.dataset.postId));
    });
  }

  // CMPA-982: reaction badge renderer (compact emoji counts)
  function renderReactionBadges(reactions) {
    if (!reactions || reactions.length === 0) return '';
    const counts = {};
    reactions.forEach(r => { counts[r.emoji] = (counts[r.emoji] || 0) + 1; });
    return '<div class="post-reactions">' +
      Object.entries(counts).map(([emoji, cnt]) =>
        `<span class="post-reaction-badge">${emoji}${cnt > 1 ? ' <span class="post-reaction-cnt">' + cnt + '</span>' : ''}</span>`
      ).join('') + '</div>';
  }

  // CMPA-982: reaction picker for post detail (jar owner only)
  const POST_REACTION_EMOJIS = ['👍', '❤️', '😂', '🎉', '🔥', '👏'];

  function renderPostReactionPicker(post) {
    const isOwner = currentJar && currentJar.ownerId === userId;
    const reactions = post.reactions || [];

    // Always show existing reaction badges
    let html = renderReactionBadges(reactions);

    // Owner-only reaction picker
    if (isOwner) {
      const myReactions = reactions.filter(r => r.authorId === userId).map(r => r.emoji);
      html += '<div class="post-reaction-picker">';
      POST_REACTION_EMOJIS.forEach(emoji => {
        const active = myReactions.includes(emoji) ? ' active' : '';
        html += `<button class="post-reaction-toggle${active}" data-emoji="${emoji}" type="button">${emoji}</button>`;
      });
      html += '</div>';
    }
    return html;
  }

  /** 게시글 상세 시트 열기 */
  function openPostDetail(postId) {
    const post = _postsCache.find(p => p.postId === postId);
    if (!post) return;
    _currentPostId = postId;

    const isMember = isMemberOfJar(currentJar);

    // 게시글 본문
    const authorLabel = post.authorId
      ? `<span class="post-author">${escHtml(post.authorName || post.authorId)}</span>`
      : `<span class="post-author-guest">${escHtml(post.guestName || '익명')}</span>`;
    $('postDetailContent').innerHTML =
      `${authorLabel}
       <div class="post-body">${escHtml(post.content)}</div>
       <div class="post-meta"><span>${fmtDate(post.createdAt)}</span></div>
       ${renderPostReactionPicker(post)}`;

    // CMPA-982: bind reaction toggle buttons (jar owner only)
    $('postDetailContent').querySelectorAll('.post-reaction-toggle').forEach(btn => {
      btn.addEventListener('click', async (e) => {
        e.stopPropagation();
        const emoji = btn.dataset.emoji;
        const isActive = btn.classList.contains('active');
        btn.disabled = true;
        try {
          if (hasSupabase()) {
            if (isActive) {
              await DreamJarSupabase.api({ action: 'removePostReaction', params: { postId, authorId: userId, emoji } });
            } else {
              await DreamJarSupabase.api({ action: 'addPostReaction', params: { postId, authorId: userId, emoji } });
            }
          }
          await renderPostsSection(currentJar);
          openPostDetail(postId);
        } catch (err) {
          toast('반응 실패: ' + err.message);
        } finally {
          btn.disabled = false;
        }
      });
    });

    // 댓글 목록
    renderCommentsList(post.comments || []);

    // guest 닉네임 필드
    $('commentGuestField').hidden = isMember;
    $('commentInput').value = '';

    openSheet('postDetailSheet');
  }

  function renderCommentsList(comments) {
    const listEl = $('postCommentsList');
    if (!comments || comments.length === 0) {
      listEl.innerHTML = '<p class="posts-empty" style="padding:8px 0">댓글이 없어요.</p>';
      return;
    }
    listEl.innerHTML = comments.map(c => {
      const authorLabel = c.authorId
        ? `<span class="comment-author">${escHtml(c.authorName || c.authorId)}</span>`
        : `<span class="comment-author-guest">${escHtml(c.guestName || '익명')}</span>`;
      return `<div class="comment-row">
        ${authorLabel}
        <div class="comment-body">${escHtml(c.content)}</div>
        <div class="comment-date">${fmtDate(c.createdAt)}</div>
      </div>`;
    }).join('');
  }

  // ── CMPA-944: 게시판 전체화면 열기/닫기 ──
  $('openBoardBtn').addEventListener('click', () => openBoardScreen());
  $('boardBackBtn').addEventListener('click', () => closeBoardScreen());

  // ── 글쓰기 ──
  function openWritePostSheet() {
    const isMember = isMemberOfJar(currentJar);
    $('postGuestField').hidden = isMember;
    $('postGuestName').value = '';
    $('postContent').value = '';
    openSheet('writePostSheet');
  }
  $('boardWriteBtn').addEventListener('click', () => openWritePostSheet());

  $('postSubmitBtn').addEventListener('click', async () => {
    if (!currentJar) return;
    const content = $('postContent').value.trim();
    if (!content) { toast('내용을 입력하세요.'); return; }

    const isMember = isMemberOfJar(currentJar);
    const guestName = isMember ? '' : $('postGuestName').value.trim();
    if (!isMember && !guestName) { toast('닉네임을 입력하세요.'); return; }

    $('postSubmitBtn').disabled = true;
    try {
      if (hasSupabase()) {
        await DreamJarSupabase.api({ action: 'createPost', params: {
          jarId: currentJar.jarId,
          authorId: isMember ? userId : null,
          guestName: guestName,
          content: content,
        }});
      }
      closeSheet('writePostSheet');
      toast('게시글을 올렸어요.');
      await renderPostsSection(currentJar);
    } catch (err) {
      toast('게시 실패: ' + err.message);
    } finally {
      $('postSubmitBtn').disabled = false;
    }
  });

  // ── 댓글 ──
  $('commentSubmitBtn').addEventListener('click', async () => {
    if (!currentJar || !_currentPostId) return;
    const content = $('commentInput').value.trim();
    if (!content) return;

    const isMember = isMemberOfJar(currentJar);
    const guestName = isMember ? '' : $('commentGuestName').value.trim();
    if (!isMember && !guestName) { toast('닉네임을 입력하세요.'); return; }

    $('commentSubmitBtn').disabled = true;
    try {
      if (hasSupabase()) {
        await DreamJarSupabase.api({ action: 'createComment', params: {
          postId: _currentPostId,
          jarId: currentJar.jarId,
          authorId: isMember ? userId : null,
          guestName: guestName,
          content: content,
        }});
      }
      $('commentInput').value = '';
      toast('댓글을 달았어요.');
      // 새로고침
      await renderPostsSection(currentJar);
      // 상세 시트 다시 열기
      openPostDetail(_currentPostId);
    } catch (err) {
      toast('댓글 실패: ' + err.message);
    } finally {
      $('commentSubmitBtn').disabled = false;
    }
  });

  // ── 응원 ──
  let _selectedCheerEmoji = '👏';

  $('cheerBtn').addEventListener('click', () => {
    const isMember = isMemberOfJar(currentJar);
    $('cheerGuestField').hidden = isMember;
    $('cheerGuestName').value = '';
    _selectedCheerEmoji = '👏';
    document.querySelectorAll('.cheer-emoji-btn').forEach(b => {
      b.classList.toggle('active', b.dataset.emoji === '👏');
    });
    openSheet('cheerSheet');
  });

  document.querySelectorAll('.cheer-emoji-btn').forEach(btn => {
    btn.addEventListener('click', () => {
      _selectedCheerEmoji = btn.dataset.emoji;
      document.querySelectorAll('.cheer-emoji-btn').forEach(b => {
        b.classList.toggle('active', b.dataset.emoji === _selectedCheerEmoji);
      });
    });
  });

  $('cheerSubmitBtn').addEventListener('click', async () => {
    if (!currentJar) return;
    const isMember = isMemberOfJar(currentJar);
    const guestName = isMember ? '' : $('cheerGuestName').value.trim();
    if (!isMember && !guestName) { toast('닉네임을 입력하세요.'); return; }

    $('cheerSubmitBtn').disabled = true;
    try {
      if (hasSupabase()) {
        await DreamJarSupabase.api({ action: 'addCheer', params: {
          jarId: currentJar.jarId,
          authorId: isMember ? userId : null,
          guestName: guestName,
          emoji: _selectedCheerEmoji,
        }});
      }
      closeSheet('cheerSheet');
      toast(_selectedCheerEmoji + ' 응원을 보냈어요!');
      await renderPostsSection(currentJar);
    } catch (err) {
      toast('응원 실패: ' + err.message);
    } finally {
      $('cheerSubmitBtn').disabled = false;
    }
  });

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

  // ── 진입점 (CMPA-913: auth session 확인) ──
  // ── CMPA-934: Public Jar View ──
  function getPublicJarId() {
    const params = new URLSearchParams(window.location.search);
    return params.get('jar') || '';
  }

  // Remember donor nickname in localStorage
  const KEY_DONOR_NAME = 'dreamjar.donorName';
  function getSavedDonorName() { return localStorage.getItem(KEY_DONOR_NAME) || ''; }
  function saveDonorName(name) { if (name) localStorage.setItem(KEY_DONOR_NAME, name); }

  async function initPublicJar(jarId) {
    const screen = $('publicJarScreen');
    screen.hidden = false;
    $('loginScreen').hidden = true;
    $('mainApp').hidden = true;

    // Pre-fill saved donor nickname
    const savedName = getSavedDonorName();
    if (savedName) {
      $('publicDonorName').value = savedName;
    }

    try {
      const jar = await DreamJarSupabase.api({ query: 'getPublicJar', params: { jarId } });
      $('publicJarName').textContent = jar.name;
      $('publicJarDesc').textContent = jar.description;
      if (jar.imageUrl) {
        $('publicJarImage').hidden = false;
        $('publicJarImageImg').src = jar.imageUrl;
      }
      const cur = Number(jar.currentAmount) || 0;
      const goal = Number(jar.goalAmount) || 0;
      $('publicJarCur').textContent = cur.toLocaleString() + '원';
      $('publicJarGoal').textContent = goal ? goal.toLocaleString() + '원' : '—';
      if (goal > 0) {
        const pct = Math.min(100, Math.round((cur / goal) * 100));
        $('publicJarProgressBar').style.width = pct + '%';
        $('publicJarProgressPct').textContent = pct + '%';
      }

      // Load posts
      const posts = await DreamJarSupabase.api({ query: 'getPosts', params: { jarId } });
      renderPublicPosts(posts);

      // Donate button → triggers ad gate first
      $('publicDonateBtn').onclick = () => showAdGate(jarId);
    } catch (err) {
      $('publicJarName').textContent = 'Jar를 찾을 수 없습니다';
      $('publicJarDesc').textContent = err.message || '';
    }
  }

  // ── CMPA-950 Ad Gate: Pseudo-rewarded ad (AdSense display in modal) ──
  const AD_GATE_SECONDS = 5;
  let _adGateUnlocked = false;
  let _adGateInterval = null;

  function showAdGate(jarId) {
    const nameEl = $('publicDonorName');
    const errEl = $('publicDonateError');
    errEl.hidden = true;

    const guestName = (nameEl.value || '').trim();
    if (!guestName) {
      errEl.textContent = '닉네임을 입력해주세요.';
      errEl.hidden = false;
      nameEl.focus();
      return;
    }

    // If already unlocked (within same session after watching ad), skip
    if (_adGateUnlocked) {
      handlePublicDonate(jarId);
      return;
    }

    showCountdownGate(jarId);
  }

  function showCountdownGate(jarId) {
    const overlay = $('adGateOverlay');
    const countEl = $('adGateCount');
    const skipBtn = $('adGateSkipBtn');
    const adIns = $('adGateIns');
    overlay.hidden = false;
    skipBtn.hidden = true;
    skipBtn.disabled = true;

    // Show ad content (CMPA-948: 쭉심 자체 광고 iframe)
    var adIframe = $('adGateIframe');
    if (adIframe) {
      adIframe.src = adIframe.src; // reload to restart animation
    }

    let remaining = AD_GATE_SECONDS;
    countEl.textContent = remaining;

    if (_adGateInterval) clearInterval(_adGateInterval);
    _adGateInterval = setInterval(() => {
      remaining--;
      countEl.textContent = remaining;
      if (remaining <= 0) {
        clearInterval(_adGateInterval);
        _adGateInterval = null;
        skipBtn.hidden = false;
        skipBtn.disabled = false;
        skipBtn.textContent = '✅ 응원하기로 이동';
        skipBtn.onclick = () => {
          overlay.hidden = true;
          _adGateUnlocked = true;
          handlePublicDonate(jarId);
        };
      }
    }, 1000);
  }

  function renderPublicPosts(posts) {
    const list = $('publicPostsList');
    if (!posts || !posts.length) {
      list.innerHTML = '<p style="color:var(--muted);font-size:.85rem;">아직 응원 메시지가 없습니다.</p>';
      return;
    }
    list.innerHTML = posts.slice(0, 20).map(p => {
      const name = p.guestName || p.authorName || '익명';
      const date = p.createdAt ? new Date(p.createdAt).toLocaleDateString('ko-KR') : '';
      const content = (p.content || '').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '<br>');
      return '<div class="public-post-card">'
        + '<div class="public-post-author">' + name + '</div>'
        + '<div class="public-post-content">' + content + '</div>'
        + '<div class="public-post-date">' + date + '</div>'
        + '</div>';
    }).join('');
  }

  async function handlePublicDonate(jarId) {
    const nameEl = $('publicDonorName');
    const msgEl = $('publicDonorMessage');
    const errEl = $('publicDonateError');
    const successEl = $('publicDonateSuccess');
    const btn = $('publicDonateBtn');

    errEl.hidden = true;
    successEl.hidden = true;

    const guestName = (nameEl.value || '').trim();
    if (!guestName) {
      errEl.textContent = '닉네임을 입력해주세요.';
      errEl.hidden = false;
      nameEl.focus();
      return;
    }

    btn.disabled = true;
    btn.textContent = '전송 중…';

    try {
      const result = await DreamJarSupabase.api({
        action: 'addPublicDonation',
        params: {
          jarId,
          guestName,
          message: (msgEl.value || '').trim(),
        },
      });
      // Save donor name for next time
      saveDonorName(guestName);
      // Show raccoon stealing message
      successEl.innerHTML = '🦝 너구리 사장이 ' + (result.raccoonFee || 2) + '원을 수수료로 가져갔습니다...<br>'
        + '✅ Jar에 ' + (result.netAmount || 3) + '원이 전달됐어요!';
      successEl.hidden = false;
      btn.textContent = '✅ 응원 완료!';
      msgEl.value = '';

      // Refresh jar info + posts
      const jar = await DreamJarSupabase.api({ query: 'getPublicJar', params: { jarId } });
      const cur = Number(jar.currentAmount) || 0;
      const goal = Number(jar.goalAmount) || 0;
      $('publicJarCur').textContent = cur.toLocaleString() + '원';
      if (goal > 0) {
        const pct = Math.min(100, Math.round((cur / goal) * 100));
        $('publicJarProgressBar').style.width = pct + '%';
        $('publicJarProgressPct').textContent = pct + '%';
      }
      const posts = await DreamJarSupabase.api({ query: 'getPosts', params: { jarId } });
      renderPublicPosts(posts);

      // Re-enable after a delay
      setTimeout(() => {
        btn.disabled = false;
        btn.textContent = '📺 광고 보고 5원 응원하기';
      }, 3000);
    } catch (err) {
      errEl.textContent = '오류: ' + (err.message || '전송 실패');
      errEl.hidden = false;
      btn.disabled = false;
      btn.textContent = '📺 광고 보고 5원 응원하기';
    }
  }

  (async function boot() {
    // CMPA-934: Public jar link check (?jar=xxx)
    const publicJarId = getPublicJarId();
    if (publicJarId && hasSupabase()) {
      await initPublicJar(publicJarId);
      return;
    }

    if (hasSupabase()) {
      try {
        const session = await DreamJarSupabase.auth.getSession();
        if (session && session.user) {
          // 유효한 세션이 있으면 userId 복원 후 앱 진입
          const authUserId = await DreamJarSupabase.auth.getAuthUserId();
          if (authUserId) {
            userId = authUserId;
            localStorage.setItem(KEY_USER_ID, userId);
          }
          hideLogin();
          initApp();

          // 세션 변경 감지 (토큰 만료 → 자동 갱신, 로그아웃 감지)
          DreamJarSupabase.auth.onAuthStateChange((event) => {
            if (event === 'SIGNED_OUT') {
              // 세션 만료 등으로 로그아웃됨
              userId = '';
              localStorage.removeItem(KEY_USER_ID);
              showLogin();
            }
          });
          return;
        }
      } catch {}
    }
    // 세션 없음 → 로그인 화면
    showLogin();
  })();

})();
