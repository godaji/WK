/* DreamJar — 프론트엔드 앱 로직
   CMPA-842: S2 Static HTML 앱 셸 + 설정 화면
   저장 = localStorage. 서버 = Apps Script URL (선택, 없으면 Mock 데이터).  */

(() => {
  'use strict';

  // ── 스토리지 키 ──
  const KEY_USER_ID   = 'dreamjar.userId';
  const KEY_SCRIPT_URL = 'dreamjar.scriptUrl';
  const KEY_EARN_JAR   = 'dreamjar.earnJarId';

  // ── 상태 ──
  let userId    = localStorage.getItem(KEY_USER_ID) || '';
  const DEFAULT_SCRIPT_URL = 'https://script.google.com/macros/s/AKfycbzrf9M_9x2m8cA2nvv0b0CWKEGNp5Ym2SLV2rJ7ADx79t1ePRbY0yF4wyLdcDU4_nMS/exec';
  let scriptUrl = localStorage.getItem(KEY_SCRIPT_URL) || DEFAULT_SCRIPT_URL;

  // 로컬 캐시 (오프라인·미연결 상태 대비)
  let cachedJars    = [];    // [{jarId, name, description, currentAmount, entryCount}]
  let cachedEntries = {};    // {jarId: [{entryId, amount, note, createdAt}]}

  // S5: 기부 — 현재 열린 Jar 추적
  let currentJar = null;

  // S4: 보상 적립 상태
  let _pendingItem  = null;  // 현재 모달 진행 중인 보상 항목
  let _pendingEntry = null;  // 확인 대기 적립 {amount, note}

  // ── Mock 데이터 (Apps Script URL 없을 때 샘플) ──
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

  // ── S4: Admin Control 하드코딩 템플릿 ──────────────────────────────────────
  const ADMIN_CONTROLS = [
    {
      controlId: 'ctrl_ca',
      name: 'DaeunControl',
      emoji: '⭐',
      isDefault: true,
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
      isDefault: true,
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

  // ── 날짜 포맷 ──
  function fmtDate(iso) {
    if (!iso) return '';
    try {
      const d = new Date(iso);
      return `${d.getMonth() + 1}/${d.getDate()}`;
    } catch { return ''; }
  }

  // ── 토스트 ──
  let _toastTimer = null;
  function toast(msg) {
    const el = $('toast');
    el.textContent = msg;
    el.hidden = false;
    el.classList.add('show');
    if (_toastTimer) clearTimeout(_toastTimer);
    _toastTimer = setTimeout(() => { el.classList.remove('show'); setTimeout(() => { el.hidden = true; }, 220); }, 2000);
  }

  // ── 되돌리기 토스트 ──
  let _undoTimer   = null;
  let _undoCountdown = null;
  let _undoState   = null;  // { jarId, entryId, amount }

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
    if (_undoTimer)    clearTimeout(_undoTimer);
    if (_undoCountdown) clearInterval(_undoCountdown);
    _undoCountdown = setInterval(() => {
      sec -= 1;
      if (sec <= 0) { clearInterval(_undoCountdown); _undoCountdown = null; }
      else btn.textContent = `되돌리기 (${sec}초)`;
    }, 1000);
    _undoTimer = setTimeout(() => { dismissUndoToast(); }, 5000);
  }

  function dismissUndoToast() {
    if (_undoTimer)    { clearTimeout(_undoTimer); _undoTimer = null; }
    if (_undoCountdown){ clearInterval(_undoCountdown); _undoCountdown = null; }
    _undoState = null;
    const el = $('undoToast');
    if (!el) return;
    el.classList.remove('show');
    setTimeout(() => { el.hidden = true; }, 220);
  }

  if ($('undoToastBtn')) {
    $('undoToastBtn').addEventListener('click', async () => {
      const state = _undoState;
      if (!state) return;
      dismissUndoToast();
      try {
        await apiFetch({ action: 'deleteEntry', params: { jarId: state.jarId, entryId: state.entryId } });
        // 잔액 롤백
        if (currentJar && currentJar.jarId === state.jarId) {
          currentJar.currentAmount = Math.max(0, (currentJar.currentAmount || 0) - state.amount);
          $('jarDetailAmount').textContent = won(currentJar.currentAmount);
        }
        cachedJars = [];
        toast('적립이 취소되었습니다.');
        // 이력 재로드
        try {
          const histData = await apiFetch({ query: 'getJarHistory', params: { jarId: state.jarId } });
          renderJarHistory((histData && histData.history) || []);
          const _undoRows = (histData && histData.history || []).filter(r => r.type === 'entry');
          renderControlSection(currentJar, _undoRows);
          renderEarnControlSection(currentJar, _undoRows);
        } catch { /* 무시 */ }
      } catch (err) {
        toast('되돌리기 실패: ' + err.message);
      }
    });
  }

  // ── API 레이어 ──

  /**
   * Apps Script URL 이 없으면 mock 응답을 반환한다.
   * action: POST action 문자열 ('createJar', 'addEntry', …)
   * query:  GET query 문자열 ('getJarsByUser', 'getEntries', …)
   * params: 추가 파라미터 객체
   */
  async function apiFetch({ action, query, params = {} }) {
    if (isMock()) {
      return mockResponse({ action, query, params });
    }

    try {
      if (action) {
        // POST
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
        // GET
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

  // S5: Mock 기부 데이터
  const MOCK_DONATIONS_IN  = [];  // {donationId, toJarId, fromJarId, netAmount, createdAt}
  const MOCK_DONATIONS_OUT = [];  // {donationId, fromJarId, toJarId, requestAmount, feeRate, feeAmount, netAmount, createdAt}

  // Mock 응답 (Apps Script URL 미설정 시)
  function mockResponse({ action, query, params }) {
    if (query === 'getJarsByUser') {
      // __me__ 자리에 실제 userId 주입
      return Promise.resolve(MOCK_JARS.map(j => ({
        ...j,
        ownerId: j.ownerId === '__me__' ? userId : (j.ownerId || userId),
      })));
    }
    if (query === 'getEntries')    return Promise.resolve(MOCK_ENTRIES[params.jarId] || []);
    if (query === 'getJar') {
      const jar = MOCK_JARS.find(j => j.jarId === params.jarId);
      if (!jar) return Promise.reject(new Error('Jar 없음'));
      const entries  = MOCK_ENTRIES[params.jarId] || [];
      const dIn      = MOCK_DONATIONS_IN.filter(d => d.toJarId === params.jarId);
      const dOut     = MOCK_DONATIONS_OUT.filter(d => d.fromJarId === params.jarId);
      const entrySum = entries.reduce((s, e) => s + (Number(e.amount) || 0), 0);
      const dInSum   = dIn.reduce((s, d) => s + (Number(d.netAmount) || 0), 0);
      const dOutSum  = dOut.reduce((s, d) => s + (Number(d.requestAmount) || 0), 0);
      return Promise.resolve({
        ...jar,
        ownerId: jar.ownerId || userId,
        currentAmount: entrySum + dInSum - dOutSum,
        entryCount: entries.length + dIn.length,
      });
    }

    // S6: getJarHistory — 기여자 이름 포함 타임라인 + 멤버별 소계
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

      const entryTotal = entries.reduce((s, e) => s + (Number(e.amount) || 0), 0);
      const memberSubtotals = entryTotal > 0
        ? [{ userId: userId, name: '나', total: entryTotal }]
        : [];

      return Promise.resolve({ history, memberSubtotals });
    }

    // S5: getHistory — entries + donation_in/out 통합
    if (query === 'getHistory') {
      const jarId = params.jarId;
      const rows = [];
      (MOCK_ENTRIES[jarId] || []).forEach(e => {
        rows.push({ type: 'entry', id: e.entryId, amount: e.amount, note: e.note, createdAt: e.createdAt });
      });
      MOCK_DONATIONS_IN.filter(d => d.toJarId === jarId).forEach(d => {
        rows.push({ type: 'donation_in', id: d.donationId, amount: d.netAmount, note: '🦝 너구리 공제 후 수령', createdAt: d.createdAt });
      });
      MOCK_DONATIONS_OUT.filter(d => d.fromJarId === jarId).forEach(d => {
        rows.push({ type: 'donation_out', id: d.donationId, amount: -d.requestAmount, note: '↗️ 기부 발신 (수수료 ' + Math.round(d.feeRate * 100) + '%)', createdAt: d.createdAt });
      });
      rows.sort((a, b) => (b.createdAt > a.createdAt ? 1 : -1));
      return Promise.resolve(rows);
    }

    if (action === 'createJar') {
      const newJar = {
        jarId: 'mock-' + Date.now(),
        name: params.name,
        description: params.description || '',
        ownerId: params.ownerId || userId,
        goalAmount: Number(params.goalAmount) || 0,
        currentAmount: 0,
        recentSevenDayTotal: 0,
        entryCount: 0,
        controlId: '',
        memberId: 'm-' + Date.now(),
      };
      MOCK_JARS.unshift(newJar);
      return Promise.resolve({ jarId: newJar.jarId });
    }
    if (action === 'addEntry') {
      const entry = {
        entryId: 'e-' + Date.now(),
        jarId: params.jarId,
        amount: Number(params.amount),
        note: params.note || '',
        createdAt: new Date().toISOString(),
      };
      if (!MOCK_ENTRIES[params.jarId]) MOCK_ENTRIES[params.jarId] = [];
      MOCK_ENTRIES[params.jarId].unshift(entry);
      const jar = MOCK_JARS.find(j => j.jarId === params.jarId);
      if (jar) { jar.currentAmount += entry.amount; jar.recentSevenDayTotal = (jar.recentSevenDayTotal || 0) + entry.amount; jar.entryCount += 1; }
      return Promise.resolve({ entryId: entry.entryId });
    }

    // S5: donate — 랜덤 너구리 수수료
    if (action === 'donate') {
      const feeRate   = Math.random() * 0.5;
      const feeAmount = Math.round(params.amount * feeRate);
      const netAmount = params.amount - feeAmount;
      const donId     = 'don-' + Date.now();
      const ts        = new Date().toISOString();
      MOCK_DONATIONS_OUT.push({ donationId: donId, fromJarId: params.fromJarId, toJarId: params.toJarId, requestAmount: params.amount, feeRate, feeAmount, netAmount, createdAt: ts });
      MOCK_DONATIONS_IN.push({ donationId: donId, toJarId: params.toJarId, fromJarId: params.fromJarId, netAmount, createdAt: ts });
      return Promise.resolve({ donationId: donId, feeRate, feeAmount, netAmount });
    }

    // S4: deleteEntry — 적립 되돌리기
    if (action === 'deleteEntry') {
      const { jarId, entryId } = params;
      if (jarId && MOCK_ENTRIES[jarId]) {
        const idx = MOCK_ENTRIES[jarId].findIndex(e => e.entryId === entryId);
        if (idx >= 0) {
          const removed = MOCK_ENTRIES[jarId].splice(idx, 1)[0];
          const jar = MOCK_JARS.find(j => j.jarId === jarId);
          if (jar && removed) {
            jar.currentAmount = Math.max(0, (jar.currentAmount || 0) - (Number(removed.amount) || 0));
            jar.entryCount = Math.max(0, (jar.entryCount || 1) - 1);
          }
          return Promise.resolve({ deleted: true });
        }
      }
      return Promise.resolve({ deleted: false });
    }

    // S4: setControl — 멤버의 Control 설정 (memberId 없으면 jarId로 폴백)
    if (action === 'setControl') {
      let j = params.memberId ? MOCK_JARS.find(m => m.memberId === params.memberId) : null;
      if (!j && params.jarId) j = MOCK_JARS.find(m => m.jarId === params.jarId);
      if (j) j.controlId = params.controlId || '';
      return Promise.resolve({ updated: true });
    }

    if (action === 'registerUser') return Promise.resolve({ userId: params.userId || userId });
    return Promise.resolve({});
  }

  // ── 설정 화면 ──
  function showSetup() {
    $('setupScreen').hidden = false;
    $('mainApp').hidden = true;
    $('setupUserId').value = userId;
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
    userId = newId;
    scriptUrl = $('setupScriptUrl').value.trim();
    localStorage.setItem(KEY_USER_ID, userId);
    localStorage.setItem(KEY_SCRIPT_URL, scriptUrl);
    hideSetup();
    initApp();
  });

  // ── 탭 네비게이션 ──
  let activeTab = 'tabHome';

  function switchTab(tabId) {
    if (activeTab === tabId) return;
    document.querySelectorAll('.tab-content').forEach(el => { el.hidden = true; });
    document.querySelectorAll('.tab-btn').forEach(btn => { btn.classList.remove('active'); });
    $(tabId).hidden = false;
    document.querySelector(`.tab-btn[data-tab="${tabId}"]`).classList.add('active');
    activeTab = tabId;
    if (tabId === 'tabHome')     loadJarList();
    if (tabId === 'tabEarn')     populateEarnSelect();
    if (tabId === 'tabSettings') loadSettingsForm();
  }

  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.addEventListener('click', () => switchTab(btn.dataset.tab));
  });

  // ── 홈 탭: Jar 목록 ──
  async function loadJarList() {
    const listEl = $('jarList');
    const emptyEl = $('jarEmpty');
    listEl.innerHTML = '<div style="color:var(--muted);font-size:14px;padding:20px 0">불러오는 중…</div>';
    emptyEl.hidden = true;

    try {
      const jars = await apiFetch({ query: 'getJarsByUser', params: { userId } });
      cachedJars = jars;
      renderJarList(jars);
    } catch (err) {
      listEl.innerHTML = `<div style="color:var(--muted);font-size:14px;padding:20px 0">불러오기 실패: ${err.message}</div>`;
    }
  }

  function renderJarList(jars) {
    const listEl  = $('jarList');
    const emptyEl = $('jarEmpty');
    listEl.innerHTML = '';

    if (!jars || jars.length === 0) {
      emptyEl.hidden = false;
      return;
    }
    emptyEl.hidden = true;

    const owned  = jars.filter(j => j.ownerId === userId);
    const joined = jars.filter(j => j.ownerId !== userId);

    function appendSection(title, list) {
      if (!list.length) return;
      const hdr = document.createElement('div');
      hdr.className = 'jar-section-title';
      hdr.textContent = title;
      listEl.appendChild(hdr);
      list.forEach(jar => {
        const el = document.createElement('div');
        el.className = 'jar-card';
        el.dataset.jarId = jar.jarId;
        el.innerHTML = jarCardInner(jar);
        el.addEventListener('click', () => openJarDetail(jar));
        listEl.appendChild(el);
      });
    }

    appendSection('내 Jar', owned);
    appendSection('참여 중인 Jar', joined);
  }

  function jarCardInner(jar) {
    const goal = Number(jar.goalAmount) || 0;
    const cur  = Number(jar.currentAmount) || 0;
    const pct  = goal > 0 ? Math.min(100, Math.round(cur / goal * 100)) : 0;
    const pred = computePrediction(jar);
    const progressHtml = goal > 0
      ? `<div class="jc-progress-wrap"><div class="jc-progress-bar" style="width:${pct}%"></div></div>`
      : '';
    const pctHtml = goal > 0 ? `<span class="jc-pct">${pct}%</span>` : '';
    const goalText = goal > 0 ? won(goal) : '목표 미설정';
    const predHtml = pred ? `<div class="jc-pred">${escHtml(pred)}</div>` : '';
    return `
<div class="jc-name">${escHtml(jar.name || '(이름 없음)')}</div>
${progressHtml}
<div class="jc-amounts">
  <span class="jc-cur">${won(cur)}</span><span class="jc-sep"> / </span><span class="jc-goal">${goalText}</span>${pctHtml}
</div>
${predHtml}`;
  }

  function computePrediction(jar) {
    const goal = Number(jar.goalAmount) || 0;
    const cur  = Number(jar.currentAmount) || 0;
    if (goal <= 0) return '';
    if (cur >= goal) return '목표 달성!';
    const recentTotal = Number(jar.recentSevenDayTotal) || 0;
    if (recentTotal <= 0) return '아직 적립 내역이 없어요';
    const dailyAvg   = recentTotal / 7;
    const remaining  = goal - cur;
    const daysNeeded = Math.ceil(remaining / dailyAvg);
    const targetDate = new Date(Date.now() + daysNeeded * 86400000);
    return `이 속도면 ${targetDate.toISOString().slice(0, 10)} 달성 · ${daysNeeded}일 남음`;
  }

  // ── Jar 상세 시트 ──
  async function openJarDetail(jar) {
    currentJar = jar;

    // 초기화
    $('jarDetailName').textContent        = jar.name;
    $('jarDetailAmount').textContent      = won(jar.currentAmount);
    $('jarDetailGoal').textContent        = '…';
    $('jarDetailProgressWrap').hidden     = true;
    $('jarDetailPrediction').textContent  = '';
    $('jarDetailPrediction').className    = 'jd-prediction';
    $('jarDetailDesc').textContent        = jar.description || '';
    $('jarDetailSubtotalHead').hidden     = true;
    $('jarDetailSubtotals').innerHTML     = '';
    $('jarDetailEntries').innerHTML       = '<div style="color:var(--muted);font-size:13px">이력 불러오는 중…</div>';
    $('donateBtn').hidden                 = !jar.ownerId || jar.ownerId === userId;

    // S4: Control 섹션 초기 렌더 (entries 로드 전)
    renderControlSection(currentJar, []);

    openSheet('jarDetailSheet');

    // 최신 Jar 정보 + S6 이력 타임라인 병렬 로드
    try {
      const [fresh, histData] = await Promise.all([
        apiFetch({ query: 'getJar',        params: { jarId: jar.jarId } }),
        apiFetch({ query: 'getJarHistory', params: { jarId: jar.jarId } }),
      ]);
      currentJar = fresh;

      // 금액 + 목표
      const cur  = Number(fresh.currentAmount) || 0;
      const goal = Number(fresh.goalAmount)    || 0;
      $('jarDetailAmount').textContent = won(cur);
      $('donateBtn').hidden = !fresh.ownerId || fresh.ownerId === userId;

      if (goal > 0) {
        $('jarDetailGoal').textContent = won(goal);
        const pct = Math.min(100, Math.round(cur / goal * 100));
        $('jarDetailProgressBar').style.width = pct + '%';
        $('jarDetailProgressPct').textContent = pct + '%';
        $('jarDetailProgressWrap').hidden = false;

        // S6: 달성 예측
        const history = (histData && histData.history) || [];
        const pred    = computeDetailPrediction(history, cur, goal);
        $('jarDetailPrediction').textContent = formatDetailPrediction(pred);
        $('jarDetailPrediction').className   =
          'jd-prediction' + (pred && pred.achieved ? ' achieved' : '');
      } else {
        $('jarDetailGoal').textContent = '미설정';
      }

      // S6: 멤버별 기여 소계 (2명 이상일 때)
      const subtotals = (histData && histData.memberSubtotals) || [];
      if (subtotals.length > 1) {
        $('jarDetailSubtotalHead').hidden = false;
        $('jarDetailSubtotals').innerHTML = subtotals.map(s =>
          `<div class="jd-subtotal-row">` +
            `<span class="jd-sub-name">${escHtml(s.name)}</span>` +
            `<span class="jd-sub-amt">${won(s.total)}</span>` +
          `</div>`
        ).join('');
      }

      // S6: 이력 타임라인
      renderJarHistory((histData && histData.history) || []);
      // S4: once 상태 반영
      renderControlSection(currentJar, (histData && histData.history || []).filter(r => r.type === 'entry'));

    } catch (err) {
      $('jarDetailEntries').innerHTML =
        `<div class="jd-entries-empty">불러오기 실패: ${escHtml(err.message)}</div>`;
    }
  }

  // S6: 이력 타임라인 렌더 (역순, 기여자 이름 포함)
  function renderJarHistory(items) {
    const container = $('jarDetailEntries');
    if (!items || items.length === 0) {
      container.innerHTML = '<div class="jd-entries-empty">아직 적립 내역이 없어요 🪣</div>';
      return;
    }
    container.innerHTML = items.map(item => {
      // 기부: "🦝 (기부자명)이 기부"  /  적립: "💰 보상명"
      const label = item.type === 'donation'
        ? `${item.icon || '🦝'} ${escHtml(item.contributorName || '')}이 기부`
        : `${item.icon || '💰'} ${escHtml(item.label || '적립')}`;

      // 적립 항목만 기여자명 별도 노출 (기부는 label에 이미 포함)
      const contributor = (item.type === 'entry' && item.contributorName)
        ? `<span class="jde-contributor">${escHtml(item.contributorName)}</span>`
        : '';

      return `<div class="jd-entry-row">` +
        `<div class="jde-left">` +
          `<span class="jde-label">${label}</span>` +
          contributor +
          `<span class="jde-date">${fmtDate(item.date || item.createdAt)}</span>` +
        `</div>` +
        `<span class="jde-amount">+${won(item.amount)}</span>` +
      `</div>`;
    }).join('');
  }

  // S6: 달성 예측 계산
  function computeDetailPrediction(history, currentAmount, goalAmount) {
    if (!goalAmount || goalAmount <= 0) return null;
    if (currentAmount >= goalAmount)   return { achieved: true };

    const remaining    = goalAmount - currentAmount;
    const nowMs        = Date.now();
    const sevenDaysAgo = nowMs - 7 * 86400000;

    // 최근 7일 이내 항목
    const recentItems = history.filter(h => new Date(h.date || h.createdAt).getTime() >= sevenDaysAgo);

    let dailyAvg;
    if (recentItems.length > 0) {
      const recentTotal = recentItems.reduce((s, h) => s + (Number(h.amount) || 0), 0);
      dailyAvg = recentTotal / 7;
    } else if (history.length > 0) {
      // 전체 기간 평균 (역순 정렬 → 마지막이 가장 오래된 것)
      const oldest      = history[history.length - 1];
      const oldestMs    = new Date(oldest.date || oldest.createdAt).getTime();
      const totalAmt    = history.reduce((s, h) => s + (Number(h.amount) || 0), 0);
      const elapsedDays = Math.max(1, (nowMs - oldestMs) / 86400000);
      dailyAvg = totalAmt / elapsedDays;
    } else {
      dailyAvg = 0;
    }

    if (dailyAvg <= 0) return { noActivity: true };

    const daysNeeded = Math.ceil(remaining / dailyAvg);
    const targetDate = new Date(nowMs + daysNeeded * 86400000);
    return { daysNeeded, targetDate };
  }

  function formatDetailPrediction(pred) {
    if (!pred) return '';
    if (pred.achieved)    return '🎉 목표를 달성했어요!';
    if (pred.noActivity)  return '아직 적립 내역이 없어요 🪣';
    const d       = pred.targetDate;
    const dateStr = `${d.getFullYear()}년 ${d.getMonth() + 1}월 ${d.getDate()}일`;
    return `📅 ${pred.daysNeeded}일 후 달성 예정 (${dateStr})`;
  }

  function renderEntries(entries) {
    renderJarHistory((entries || []).map(e => ({ type: 'entry', ...e, label: e.note, icon: '💰', contributorName: '' })));
  }

  // ── Jar 만들기 시트 ──
  function openCreateJar() {
    $('cjName').value = '';
    $('cjGoal').value = '';
    $('cjDesc').value = '';
    openSheet('createJarSheet');
    setTimeout(() => $('cjName').focus(), 300);
  }

  $('createJarBtn').addEventListener('click', openCreateJar);
  $('createJarBtnEmpty').addEventListener('click', openCreateJar);

  $('cjSaveBtn').addEventListener('click', async () => {
    const name = $('cjName').value.trim();
    const goal = Number(String($('cjGoal').value).replace(/[^0-9]/g, ''));
    const desc = $('cjDesc').value.trim();

    if (!name) { toast('Jar 이름을 입력하세요.'); $('cjName').focus(); return; }
    if (!goal || goal <= 0) { toast('목표금액을 입력하세요.'); $('cjGoal').focus(); return; }

    $('cjSaveBtn').disabled = true;
    try {
      await apiFetch({
        action: 'createJar',
        params: { name, description: desc, goalAmount: goal, ownerId: userId },
      });
      closeSheet('createJarSheet');
      toast('Jar를 만들었어요!');
      loadJarList();
    } catch (err) {
      toast('Jar 생성 실패: ' + err.message);
    } finally {
      $('cjSaveBtn').disabled = false;
    }
  });

  // ── 적립 탭 ──
  async function populateEarnSelect() {
    // 캐시가 비어 있으면 서버에서 로드 (탭 전환 시 홈을 방문하지 않은 경우 대비)
    if (cachedJars.length === 0) {
      try {
        const jars = await apiFetch({ query: 'getJarsByUser', params: { userId } });
        cachedJars = jars;
      } catch { /* 무시 */ }
    }
    const sel = $('earnJarSelect');
    const prev = sel.value || localStorage.getItem(KEY_EARN_JAR) || '';
    sel.innerHTML = '<option value="">— Jar를 선택하세요 —</option>';
    cachedJars.forEach(jar => {
      const opt = document.createElement('option');
      opt.value = jar.jarId;
      opt.textContent = jar.name;
      sel.appendChild(opt);
    });
    if (prev) sel.value = prev;
    onEarnJarChange(sel.value);
  }

  // Jar 선택 변경 시: localStorage 저장 + 컨트롤 섹션 갱신
  $('earnJarSelect').addEventListener('change', () => {
    onEarnJarChange($('earnJarSelect').value);
  });

  function onEarnJarChange(jarId) {
    if (jarId) {
      localStorage.setItem(KEY_EARN_JAR, jarId);
      const jar = cachedJars.find(j => j.jarId === jarId);
      if (jar) {
        currentJar = jar;
        $('earnControlSection').hidden = false;
        renderEarnControlSection(jar, []);
      }
    } else {
      $('earnControlSection').hidden = true;
    }
  }

  // 적립 탭 컨트롤 섹션 렌더 (earn tab 전용 DOM 타깃)
  function renderEarnControlSection(jar, entries) {
    if (!jar) return;
    const ctrl    = ADMIN_CONTROLS.find(c => c.controlId === jar.controlId);
    const nameEl  = $('earnCtrlName');
    const rewardSec = $('earnCtrlRewardSection');
    if (!nameEl) return;
    if (ctrl) {
      nameEl.textContent = ctrl.emoji + ' ' + ctrl.name;
      if (rewardSec) rewardSec.hidden = false;
      renderRewardButtons(ctrl, entries || [], $('earnCtrlRewardList'));
    } else {
      nameEl.textContent = '선택 안 됨';
      if (rewardSec) rewardSec.hidden = true;
    }
  }

  if ($('earnCtrlChangeBtn')) {
    $('earnCtrlChangeBtn').addEventListener('click', openControlPicker);
  }

  $('earnSubmitBtn').addEventListener('click', async () => {
    const jarId  = $('earnJarSelect').value;
    const amount = Number($('earnAmount').value);
    const note   = $('earnNote').value.trim();

    if (!jarId)       { toast('Jar를 선택하세요.');     return; }
    if (!amount || amount < 1) { toast('금액을 입력하세요.'); return; }

    $('earnSubmitBtn').disabled = true;
    try {
      await apiFetch({
        action: 'addEntry',
        params: { jarId, userId, amount, note },
      });
      $('earnAmount').value = '';
      $('earnNote').value   = '';
      toast('적립 완료!');
      // 홈 탭 캐시 무효화
      cachedJars = [];
    } catch (err) {
      toast('적립 실패: ' + err.message);
    } finally {
      $('earnSubmitBtn').disabled = false;
    }
  });

  // ── 설정 탭 ──
  function loadSettingsForm() {
    $('settUserId').value    = userId;
    $('settScriptUrl').value = scriptUrl;
  }

  $('settSaveBtn').addEventListener('click', () => {
    const newId  = $('settUserId').value.trim();
    const newUrl = $('settScriptUrl').value.trim();
    if (!newId) { toast('사용자 ID를 입력하세요.'); return; }
    userId    = newId;
    scriptUrl = newUrl;
    localStorage.setItem(KEY_USER_ID, userId);
    localStorage.setItem(KEY_SCRIPT_URL, scriptUrl);
    toast('저장됐어요.');
    cachedJars = [];
  });

  // ── 시트 공통 ──
  function openSheet(id) { $(id).hidden = false; }
  function closeSheet(id) { $(id).hidden = true; }

  document.querySelectorAll('.sheet-close').forEach(btn => {
    btn.addEventListener('click', () => closeSheet(btn.dataset.close));
  });

  document.querySelectorAll('.sheet-backdrop').forEach(backdrop => {
    backdrop.addEventListener('click', e => {
      if (e.target === backdrop) closeSheet(backdrop.id);
    });
  });

  // ── 다른 Jar 참여 ──
  if ($('joinJarBtn')) {
    $('joinJarBtn').addEventListener('click', async () => {
      const jarId = $('joinJarId').value.trim();
      if (!jarId) { toast('Jar ID를 입력하세요'); return; }
      $('joinJarBtn').disabled = true;
      try {
        await apiFetch({ action: 'joinJar', params: { jarId, userId } });
        $('joinJarId').value = '';
        toast('참여했습니다!');
        cachedJars = [];
        loadJarList();
      } catch (err) {
        toast('참여 실패: ' + err.message);
      } finally {
        $('joinJarBtn').disabled = false;
      }
    });
  }

  // ── S5: 기부 흐름 ─────────────────────────────────────────────────────────

  // 기부 버튼 클릭 → 기부 시트 열기
  if ($('donateBtn')) {
    $('donateBtn').addEventListener('click', openDonateSheet);
  }

  function openDonateSheet() {
    if (!currentJar) return;

    // 단계 초기화
    $('donateStep1').hidden = false;
    $('donateStep2').hidden = true;
    $('donateConfirmBtn').disabled = false;
    $('donateConfirmBtn').textContent = '기부 확정';
    $('donateAmount').value = '';

    // 대상 Jar 이름
    $('donateTargetLabel').textContent = '「' + currentJar.name + '」에게 기부합니다';

    // 출금 소스: 내 소유 Jar 목록 (대상 제외)
    const sel = $('donateSourceJar');
    while (sel.options.length > 1) sel.remove(1);
    cachedJars
      .filter(j => (!j.ownerId || j.ownerId === userId) && j.jarId !== currentJar.jarId)
      .forEach(j => sel.add(new Option(j.name, j.jarId)));

    openSheet('donateSheet');
  }

  // 기부 확정 버튼
  if ($('donateConfirmBtn')) {
    $('donateConfirmBtn').addEventListener('click', async () => {
      const fromJarId = $('donateSourceJar').value;
      const amount    = Number($('donateAmount').value);
      const toJarId   = currentJar && currentJar.jarId;

      if (!fromJarId)              { toast('출금할 Jar를 선택하세요'); return; }
      if (!amount || amount < 100) { toast('100원 이상 입력하세요'); return; }
      if (!toJarId)                return;

      const btn = $('donateConfirmBtn');
      btn.disabled = true;
      btn.textContent = '처리 중…';

      try {
        const d   = await apiFetch({ action: 'donate', params: { fromJarId, toJarId, amount, userId } });
        const pct = Math.round((d.feeRate || 0) * 100);

        // 결과 팝업
        $('raccoonHeadline').textContent = '🦝 너구리사장이 ' + pct + '% 이자로 뗴어갔다!';
        $('raccoonDetail').innerHTML =
          '요청 금액: <strong>' + won(amount) + '</strong><br>' +
          '너구리 수수료 (' + pct + '%): <strong>−' + won(d.feeAmount) + '</strong>';
        $('raccoonNet').textContent = won(d.netAmount) + ' 전달됐어요 🎉';

        $('donateStep1').hidden = true;
        $('donateStep2').hidden = false;

        // 캐시 무효화 (잔액이 바뀌므로)
        cachedJars = [];
      } catch (err) {
        toast('기부 실패: ' + err.message);
        btn.disabled = false;
        btn.textContent = '기부 확정';
      }
    });
  }

  // 기부 결과 확인
  if ($('donateResultOkBtn')) {
    $('donateResultOkBtn').addEventListener('click', () => {
      closeSheet('donateSheet');
      // Jar 상세 새로고침
      if (currentJar) openJarDetail(currentJar);
    });
  }

  // ── S4: Control 섹션 ──────────────────────────────────────────────────────

  function renderControlSection(jar, entries) {
    if (!jar) return;
    const ctrl        = ADMIN_CONTROLS.find(c => c.controlId === jar.controlId);
    const nameEl      = $('jdControlName');
    const rewardSec   = $('jdRewardSection');
    if (!nameEl) return;  // DOM 아직 없을 수 있음

    if (ctrl) {
      nameEl.textContent = ctrl.emoji + ' ' + ctrl.name;
      if (rewardSec) rewardSec.hidden = false;
      renderRewardButtons(ctrl, entries || []);
    } else {
      nameEl.textContent = '선택 안 됨';
      if (rewardSec) rewardSec.hidden = true;
    }
  }

  function renderRewardButtons(ctrl, entries, listEl) {
    // [item_id] 패턴으로 once 아이템 적립 여부 판단
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
      const icon = ICONS[item.type] || '💰';
      const doneBadge = claimed ? '<span class="rb-done-badge">완료</span>' : '';
      return `<button class="reward-btn${claimed ? ' is-done' : ''}" data-item-id="${escHtml(item.id)}" type="button"${claimed ? ' disabled' : ''}>` +
        `<span class="rb-icon">${icon}</span>` +
        `<span class="rb-label">${escHtml(item.label)}</span>` +
        `<span class="rb-amount">${escHtml(amtStr)}</span>` +
        doneBadge +
        `</button>`;
    }).join('');

    if (!listEl) listEl = $('jdRewardList');
    if (!listEl) return;
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

  if ($('jdControlChangeBtn')) {
    $('jdControlChangeBtn').addEventListener('click', openControlPicker);
  }

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
    const memberId = jar.memberId || '';
    try {
      // memberId가 비어 있는 구형 Jar 대비: jarId + userId를 같이 전달해 백엔드가 자동 처리
      await apiFetch({ action: 'setControl', params: { memberId, controlId, jarId: jar.jarId, userId } });
      jar.controlId = controlId;
      const cached = cachedJars.find(j => j.jarId === jar.jarId);
      if (cached) cached.controlId = controlId;
      closeSheet('controlPickerSheet');
      const rows = cachedEntries[jar.jarId] || [];
      const entryRows = rows.filter(r => r.type === 'entry');
      renderControlSection(jar, entryRows);
      renderEarnControlSection(jar, entryRows);
      toast('Control을 설정했어요.');
    } catch (err) {
      toast('설정 실패: ' + err.message);
    }
  }

  // 즉시 적립 (확인 모달 없이) + 되돌리기 토스트
  async function addEntryImmediate(amount, note) {
    const jar = currentJar;
    if (!jar) return;
    try {
      const res = await apiFetch({ action: 'addEntry', params: { jarId: jar.jarId, userId, amount, note } });
      jar.currentAmount = (jar.currentAmount || 0) + amount;
      $('jarDetailAmount').textContent = won(jar.currentAmount);
      cachedJars = [];
      showUndoToast(jar.jarId, res && res.entryId, amount);
      // 이력 재로드
      try {
        const histData = await apiFetch({ query: 'getJarHistory', params: { jarId: jar.jarId } });
        renderJarHistory((histData && histData.history) || []);
        const _entryRows = (histData && histData.history || []).filter(r => r.type === 'entry');
        renderControlSection(jar, _entryRows);
        renderEarnControlSection(jar, _entryRows);
        cachedEntries[jar.jarId] = (histData && histData.history) || [];
      } catch { /* 무시 */ }
    } catch (err) {
      toast('적립 실패: ' + err.message);
    }
  }

  // per_day 길게 누르기 → 날짜/금액 옵션 시트 열기
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
      // 티어 선택 필요 → 모달 유지
      $('tierPickerTitle').textContent = item.label;
      renderTierButtons(item);
      openSheet('tierPickerSheet');
    } else if (item.subtype === 'threshold') {
      // 점수 입력 필요 → 모달 유지
      $('scorePickerTitle').textContent = item.label + ' 점수 입력';
      $('scoreInput').value = '';
      openSheet('scoreInputSheet');
    } else if (item.subtype === 'per_day') {
      // 탭 → 오늘 즉시 적립 (길게 누르기로 날짜/금액 변경)
      addEntryImmediate(item.amount, `[${item.id}] ${item.label} (${todayStr()})`);
    } else if (item.subtype === 'session') {
      // 탭 → 1세션 즉시 적립 (길게 누르기로 세션 수 변경)
      addEntryImmediate(item.amount, `[${item.id}] ${item.label} × 1회`);
    } else {
      // milestone.once 등 → 즉시 적립
      addEntryImmediate(item.amount, `[${item.id}] ${item.label}`);
    }
  }

  function renderTierButtons(item) {
    const wrap = $('tierBtnList');
    if (!wrap) return;
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

  if ($('scoreSubmitBtn')) {
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
  }

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

  if ($('routineTodayBtn')) {
    $('routineTodayBtn').addEventListener('click', () => {
      const item = _pendingItem;
      closeSheet('routineSheet');
      showEntryConfirm(item.amount, `${item.label} (오늘)`, `[${item.id}] ${item.label} (${todayStr()})`);
    });
  }
  if ($('routineDateConfirm')) {
    $('routineDateConfirm').addEventListener('click', () => {
      const item = _pendingItem;
      const d    = $('routineDateInput').value || todayStr();
      closeSheet('routineSheet');
      showEntryConfirm(item.amount, `${item.label} (${d})`, `[${item.id}] ${item.label} (${d})`);
    });
  }
  if ($('sessionDecBtn')) {
    $('sessionDecBtn').addEventListener('click', () => {
      const el = $('sessionCount');
      el.textContent = Math.max(1, (Number(el.textContent) || 1) - 1);
    });
  }
  if ($('sessionIncBtn')) {
    $('sessionIncBtn').addEventListener('click', () => {
      const el = $('sessionCount');
      el.textContent = (Number(el.textContent) || 1) + 1;
    });
  }
  if ($('sessionConfirmBtn')) {
    $('sessionConfirmBtn').addEventListener('click', () => {
      const item  = _pendingItem;
      const count = Math.max(1, Number($('sessionCount').textContent) || 1);
      closeSheet('routineSheet');
      showEntryConfirm(item.amount * count, `${item.label} × ${count}회`, `[${item.id}] ${item.label} × ${count}회`);
    });
  }

  function showEntryConfirm(amount, displayLabel, note) {
    _pendingEntry = { amount, note };
    $('confirmLabel').textContent  = displayLabel;
    $('confirmAmount').textContent = won(amount);
    openSheet('entryConfirmSheet');
  }

  if ($('entryConfirmBtn')) {
    $('entryConfirmBtn').addEventListener('click', async () => {
      const pending = _pendingEntry;
      const jar     = currentJar;
      if (!pending || !jar) return;
      const btn = $('entryConfirmBtn');
      btn.disabled = true;
      try {
        await apiFetch({ action: 'addEntry', params: { jarId: jar.jarId, userId, amount: pending.amount, note: pending.note } });
        jar.currentAmount = (jar.currentAmount || 0) + pending.amount;
        $('jarDetailAmount').textContent = won(jar.currentAmount);
        closeSheet('entryConfirmSheet');
        toast(`+${won(pending.amount)} 적립 완료!`);
        _pendingEntry = null;
        cachedJars    = [];
        // 이력 재로드
        try {
          const histData = await apiFetch({ query: 'getJarHistory', params: { jarId: jar.jarId } });
          renderJarHistory((histData && histData.history) || []);
          const _confirmRows = (histData && histData.history || []).filter(r => r.type === 'entry');
          renderControlSection(jar, _confirmRows);
          renderEarnControlSection(jar, _confirmRows);
          cachedEntries[jar.jarId] = (histData && histData.history) || [];
        } catch { /* 실패 무시 */ }
      } catch (err) {
        toast('적립 실패: ' + err.message);
      } finally {
        btn.disabled = false;
      }
    });
  }

  function todayStr() {
    const d = new Date();
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
  }

  // ── XSS 방어 ──
  function escHtml(str) {
    return String(str)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ── 앱 초기화 ──
  function initApp() {
    if (isMock()) {
      console.info('[DreamJar] Apps Script URL 미설정 → 샘플 데이터 모드');
    }
    // activeTab 초기값이 'tabHome'이면 switchTab이 early return하여 loadJarList를 건너뜀 — 리셋 후 호출
    activeTab = '';
    switchTab('tabHome');
  }

  // ── 진입점 ──
  if (!userId) {
    showSetup();
  } else {
    hideSetup();
    initApp();
  }

})();
