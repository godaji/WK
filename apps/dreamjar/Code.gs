/**
 * DreamJar — Google Apps Script 백엔드 (dreamjar2에서 승격)
 *
 * 배포 전 아래 SPREADSHEET_ID 를 실제 값으로 교체하세요.
 * (Google Sheets URL에서 /d/ 와 /edit 사이의 문자열)
 */
var SPREADSHEET_ID = '14aUcea8p-LWS9TcscIIryZQXg6JAfwDavttDquKHGHc';

// ─── 시트 이름 상수 ───────────────────────────────────────────────────────────
var SHEET = {
  USERS:        'users',
  JARS:         'jars',
  JAR_MEMBERS:  'jar_members',
  ENTRIES:      'entries',
  DONATION_OUT: 'donation_out',
  DONATION_IN:  'donation_in',
  CONTROLS:     'controls',
};

// ─── 유틸 ─────────────────────────────────────────────────────────────────────

function ss() {
  return SpreadsheetApp.openById(SPREADSHEET_ID);
}

function sheet(name) {
  var s = ss().getSheetByName(name);
  if (!s) throw new Error('시트를 찾을 수 없습니다: ' + name);
  return s;
}

/** 시트의 헤더(1행)를 읽어 컬럼명 배열 반환 */
function headers(sh) {
  var last = sh.getLastColumn();
  if (last === 0) return [];
  return sh.getRange(1, 1, 1, last).getValues()[0];
}

/** 시트 전체 데이터를 [{col: val, …}, …] 배열로 반환 (헤더 제외) */
function readAll(sheetName) {
  var sh = sheet(sheetName);
  var last = sh.getLastRow();
  if (last <= 1) return [];
  var cols = headers(sh);
  var data = sh.getRange(2, 1, last - 1, cols.length).getValues();
  return data.map(function(row) {
    var obj = {};
    cols.forEach(function(c, i) { obj[c] = row[i]; });
    return obj;
  });
}

/** 시트 마지막 행에 row 객체(컬럼 순서대로)를 append */
function appendRow(sheetName, row) {
  var sh = sheet(sheetName);
  var cols = headers(sh);
  var values = cols.map(function(c) { return row[c] !== undefined ? row[c] : ''; });
  sh.appendRow(values);
}

/** UUID 대신 간단한 고유 ID 생성 (타임스탬프 + 랜덤) */
function newId(prefix) {
  return (prefix || 'id') + '_' + Date.now() + '_' + Math.floor(Math.random() * 1e6);
}

function now() {
  return new Date().toISOString();
}

/** JSON 응답 반환 */
function jsonOk(data) {
  return ContentService
    .createTextOutput(JSON.stringify({ ok: true, data: data }))
    .setMimeType(ContentService.MimeType.JSON);
}

function jsonErr(msg) {
  return ContentService
    .createTextOutput(JSON.stringify({ ok: false, error: msg }))
    .setMimeType(ContentService.MimeType.JSON);
}

// ─── doPost ──────────────────────────────────────────────────────────────────

/**
 * POST /exec
 * Body (JSON): { action: string, …params }
 */
function doPost(e) {
  try {
    var payload = JSON.parse(e.postData.contents);
    var action = payload.action;

    if (action === 'registerUser')  return handleRegisterUser(payload);
    if (action === 'createJar')     return handleCreateJar(payload);
    if (action === 'joinJar')       return handleJoinJar(payload);
    if (action === 'setControl')    return handleSetControl(payload);
    if (action === 'createControl') return handleCreateControl(payload);
    if (action === 'addEntry')      return handleAddEntry(payload);
    if (action === 'deleteEntry')   return handleDeleteEntry(payload);
    if (action === 'donate')        return handleDonate(payload);
    if (action === 'archiveJar')   return handleArchiveJar(payload);

    return jsonErr('알 수 없는 action: ' + action);
  } catch (err) {
    return jsonErr(err.message);
  }
}

/** users 시트에 신규 사용자 등록 */
function handleRegisterUser(p) {
  var userId = p.userId || newId('u');
  appendRow(SHEET.USERS, {
    userId:    userId,
    name:      p.name || '',
    email:     p.email || '',
    createdAt: now(),
  });
  return jsonOk({ userId: userId });
}

/** jars 시트에 신규 Jar 생성 + 소유자 jar_members 자동 추가 */
function handleCreateJar(p) {
  var jarId = p.jarId || newId('jar');
  var ts    = now();
  appendRow(SHEET.JARS, {
    jarId:       jarId,
    name:        p.name || '',
    description: p.description || '',
    ownerId:     p.ownerId || '',
    goalAmount:  Number(p.goalAmount) || 0,
    controlId:   p.controlId || '',
    createdAt:   ts,
  });
  // 소유자를 jar_members 에 자동 추가 (role=owner)
  if (p.ownerId) {
    appendRow(SHEET.JAR_MEMBERS, {
      memberId:  newId('m'),
      jarId:     jarId,
      userId:    p.ownerId,
      role:      'owner',
      controlId: p.controlId || '',
      joinedAt:  ts,
    });
  }
  return jsonOk({ jarId: jarId });
}

/** jar_members 에 멤버 추가 (role=member) — jarId 또는 jar 이름으로 검색 */
function handleJoinJar(p) {
  var input = (p.jarId || '').trim();
  if (!input) return jsonErr('Jar ID 또는 이름을 입력하세요');
  var allJars = readAll(SHEET.JARS);
  // 1차: jarId 정확 매칭
  var jar = allJars.find(function(j) { return j.jarId === input; });
  // 2차: jar 이름 정확 매칭 (jarId로 못 찾은 경우)
  if (!jar) {
    jar = allJars.find(function(j) { return j.name === input; });
  }
  if (!jar) return jsonErr('존재하지 않는 Jar입니다: ' + input);
  if (jar.archived === true || jar.archived === 'TRUE' || jar.archived === 'true') {
    return jsonErr('삭제된 Jar입니다');
  }
  var members = readAll(SHEET.JAR_MEMBERS);
  var existing = members.find(function(m) { return m.jarId === jar.jarId && m.userId === (p.userId || ''); });
  if (existing) return jsonErr('이미 참여 중인 Jar입니다');

  var memberId = newId('m');
  appendRow(SHEET.JAR_MEMBERS, {
    memberId:  memberId,
    jarId:     jar.jarId,
    userId:    p.userId || '',
    role:      'member',
    controlId: '',
    joinedAt:  now(),
  });
  return jsonOk({ memberId: memberId, jarName: jar.name || '' });
}

/** jar_members 에서 특정 멤버의 controlId 갱신
 *  1) memberId 있으면 memberId로 탐색
 *  2) memberId 없으면 jarId + userId로 탐색 (구형 Jar 하위 호환)
 *  3) 행이 없으면 자동 추가 (owner 역할) */
function handleSetControl(p) {
  var sh = sheet(SHEET.JAR_MEMBERS);
  var cols = headers(sh);
  var memberIdx = cols.indexOf('memberId');
  var controlIdx = cols.indexOf('controlId');
  var jarIdx = cols.indexOf('jarId');
  var userIdx = cols.indexOf('userId');
  if (memberIdx < 0 || controlIdx < 0) return jsonErr('jar_members 헤더 오류');

  var last = sh.getLastRow();
  var data = last > 1 ? sh.getRange(2, 1, last - 1, cols.length).getValues() : [];

  // 1. memberId로 찾기
  if (p.memberId) {
    for (var i = 0; i < data.length; i++) {
      if (data[i][memberIdx] === p.memberId) {
        sh.getRange(i + 2, controlIdx + 1).setValue(p.controlId || '');
        return jsonOk({ updated: true });
      }
    }
  }

  // 2. jarId + userId 폴백 (memberId 없는 구형 Jar)
  if (p.jarId && p.userId && jarIdx >= 0 && userIdx >= 0) {
    for (var j = 0; j < data.length; j++) {
      if (data[j][jarIdx] === p.jarId && data[j][userIdx] === p.userId) {
        sh.getRange(j + 2, controlIdx + 1).setValue(p.controlId || '');
        return jsonOk({ updated: true });
      }
    }
    // 행이 없으면 owner 행 자동 생성
    appendRow(SHEET.JAR_MEMBERS, {
      memberId:  newId('m'),
      jarId:     p.jarId,
      userId:    p.userId,
      role:      'owner',
      controlId: p.controlId || '',
      joinedAt:  now(),
    });
    return jsonOk({ updated: true });
  }

  return jsonErr('멤버를 찾을 수 없습니다: ' + (p.memberId || p.jarId || ''));
}

/** controls 시트에 신규 Control 생성 */
function handleCreateControl(p) {
  var controlId = p.controlId || newId('ctrl');
  appendRow(SHEET.CONTROLS, {
    controlId:   controlId,
    name:        p.name || '',
    description: p.description || '',
    ownerId:     p.ownerId || '',
    type:        p.type || '',
    createdAt:   now(),
  });
  return jsonOk({ controlId: controlId });
}

/** entries 시트에 리워드 적립 엔트리 추가 */
function handleAddEntry(p) {
  var entryId = newId('ent');
  appendRow(SHEET.ENTRIES, {
    entryId:   entryId,
    jarId:     p.jarId || '',
    userId:    p.userId || '',
    amount:    Number(p.amount) || 0,
    note:      p.note || '',
    createdAt: now(),
  });
  return jsonOk({ entryId: entryId });
}

/** 적립 항목 삭제 (되돌리기용) — entryId로 entries 시트에서 해당 행 제거 */
function handleDeleteEntry(p) {
  var sh   = sheet(SHEET.ENTRIES);
  var cols = headers(sh);
  var idIdx = cols.indexOf('entryId');
  if (idIdx < 0) return jsonErr('entryId 컬럼 없음');
  var last = sh.getLastRow();
  for (var r = 2; r <= last; r++) {
    if (sh.getRange(r, idIdx + 1).getValue() === p.entryId) {
      sh.deleteRow(r);
      return jsonOk({ deleted: true });
    }
  }
  return jsonOk({ deleted: false });
}

/**
 * 기부 처리 (너구리 수수료 로직)
 * - 수수료율: 서버사이드 Math.random() 으로 0~50% 랜덤 계산
 * - donation_out 1행 + donation_in 1행 동시 추가
 */
function handleDonate(p) {
  var donationId  = newId('don');
  var requestAmt  = Number(p.amount) || 0;
  var feeRate     = Math.random() * 0.5;           // 0.0 ~ 0.5
  var feeAmount   = Math.round(requestAmt * feeRate);
  var netAmount   = requestAmt - feeAmount;
  var ts          = now();

  appendRow(SHEET.DONATION_OUT, {
    donationId:    donationId,
    fromJarId:     p.fromJarId || '',
    toJarId:       p.toJarId || '',
    requestAmount: requestAmt,
    feeRate:       feeRate,
    feeAmount:     feeAmount,
    netAmount:     netAmount,
    createdAt:     ts,
  });

  appendRow(SHEET.DONATION_IN, {
    donationId:    donationId,
    toJarId:       p.toJarId || '',
    fromJarId:     p.fromJarId || '',
    requestAmount: requestAmt,
    feeRate:       feeRate,
    feeAmount:     feeAmount,
    netAmount:     netAmount,
    createdAt:     ts,
  });

  return jsonOk({
    donationId: donationId,
    feeRate:    feeRate,
    feeAmount:  feeAmount,
    netAmount:  netAmount,
  });
}

/**
 * Jar 아카이브 (soft delete)
 * jars 시트에서 jarId에 해당하는 행의 archived, archivedAt 컬럼 갱신
 */
function handleArchiveJar(p) {
  var jarId = p.jarId;
  if (!jarId) return jsonErr('jarId 필요');

  var sh = sheet(SHEET.JARS);
  var cols = headers(sh);
  var jarIdx = cols.indexOf('jarId');
  var archIdx = cols.indexOf('archived');
  var archAtIdx = cols.indexOf('archivedAt');

  if (jarIdx < 0) return jsonErr('jars 시트에 jarId 컬럼 없음');
  // archived/archivedAt 컬럼이 없으면 자동 추가
  if (archIdx < 0) {
    archIdx = cols.length;
    sh.getRange(1, archIdx + 1).setValue('archived');
  }
  if (archAtIdx < 0) {
    archAtIdx = archIdx + 1;
    if (cols.length <= archAtIdx) {
      sh.getRange(1, archAtIdx + 1).setValue('archivedAt');
    }
  }

  var last = sh.getLastRow();
  for (var r = 2; r <= last; r++) {
    if (sh.getRange(r, jarIdx + 1).getValue() === jarId) {
      sh.getRange(r, archIdx + 1).setValue(true);
      sh.getRange(r, archAtIdx + 1).setValue(now());
      return jsonOk({ archived: true });
    }
  }
  return jsonErr('Jar를 찾을 수 없습니다: ' + jarId);
}

// ─── doGet ───────────────────────────────────────────────────────────────────

/**
 * GET /exec?query=…&param=…
 */
function doGet(e) {
  try {
    var p = e.parameter;
    var query = p.query;

    if (query === 'getJarsByUser')   return handleGetJarsByUser(p);
    if (query === 'getEntries')      return handleGetEntries(p);
    if (query === 'getAdminControls') return handleGetAdminControls(p);
    if (query === 'getJar')          return handleGetJar(p);
    if (query === 'getHistory')      return handleGetHistory(p);
    if (query === 'getJarHistory')   return handleGetJarHistory(p);
    if (query === 'getAllJars')       return handleGetAllJars(p);

    return jsonErr('알 수 없는 query: ' + query);
  } catch (err) {
    return jsonErr(err.message);
  }
}

/**
 * userId 기준으로 참여 중인 Jar 목록 반환
 * jar_members JOIN jars + entries 집계(currentAmount, recentSevenDayTotal)
 */
function handleGetJarsByUser(p) {
  var userId = p.userId;
  if (!userId) return jsonErr('userId 필요');

  var allJars = readAll(SHEET.JARS).filter(function(j) {
    return j.archived !== true && j.archived !== 'TRUE' && j.archived !== 'true';
  });
  var jarsMap = {};
  allJars.forEach(function(j) { jarsMap[j.jarId] = j; });

  // entries 를 jarId 별로 그룹핑
  var allEntries = readAll(SHEET.ENTRIES);
  var entriesByJar = {};
  allEntries.forEach(function(e) {
    if (!entriesByJar[e.jarId]) entriesByJar[e.jarId] = [];
    entriesByJar[e.jarId].push(e);
  });

  // donation_in/donation_out 을 jarId 별로 그룹핑
  var allDonationsIn = readAll(SHEET.DONATION_IN);
  var donationsInByJar = {};
  allDonationsIn.forEach(function(d) {
    if (!donationsInByJar[d.toJarId]) donationsInByJar[d.toJarId] = [];
    donationsInByJar[d.toJarId].push(d);
  });
  var allDonationsOut = readAll(SHEET.DONATION_OUT);
  var donationsOutByJar = {};
  allDonationsOut.forEach(function(d) {
    if (!donationsOutByJar[d.fromJarId]) donationsOutByJar[d.fromJarId] = [];
    donationsOutByJar[d.fromJarId].push(d);
  });

  // jar_members 에서 사용자 멤버십 조회
  var members = readAll(SHEET.JAR_MEMBERS).filter(function(m) {
    return m.userId === userId;
  });
  var memberJarIds = {};
  members.forEach(function(m) { memberJarIds[m.jarId] = true; });

  // ownerId=userId 인데 jar_members 에 없는 Jar 도 포함 (하위 호환)
  allJars.forEach(function(j) {
    if (j.ownerId === userId && !memberJarIds[j.jarId]) {
      members.push({
        memberId: '', jarId: j.jarId, userId: userId,
        role: 'owner', controlId: '', joinedAt: j.createdAt || '',
      });
    }
  });

  var sevenDaysAgo = new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString();

  // 존재하지 않는 jar를 가리키는 고아 멤버 레코드 제외
  members = members.filter(function(m) { return !!jarsMap[m.jarId]; });

  var result = members.map(function(m) {
    var jar = jarsMap[m.jarId];
    var jarEntries = entriesByJar[m.jarId] || [];
    var entriesSum = jarEntries.reduce(function(s, e) {
      return s + (Number(e.amount) || 0);
    }, 0);
    var dInSum = (donationsInByJar[m.jarId] || []).reduce(function(s, d) {
      return s + (Number(d.netAmount) || 0);
    }, 0);
    var dOutSum = (donationsOutByJar[m.jarId] || []).reduce(function(s, d) {
      return s + (Number(d.requestAmount) || 0);
    }, 0);
    var currentAmount = entriesSum + dInSum - dOutSum;
    var recentSevenDayTotal = jarEntries
      .filter(function(e) { return String(e.createdAt || '') >= sevenDaysAgo; })
      .reduce(function(s, e) { return s + (Number(e.amount) || 0); }, 0);
    return Object.assign({}, jar, {
      role:                m.role,
      controlId:           m.controlId,
      memberId:            m.memberId,
      currentAmount:       currentAmount,
      recentSevenDayTotal: recentSevenDayTotal,
    });
  });

  return jsonOk(result);
}

/** jarId 기준 entries 목록 반환 */
function handleGetEntries(p) {
  var jarId = p.jarId;
  if (!jarId) return jsonErr('jarId 필요');

  var entries = readAll(SHEET.ENTRIES).filter(function(e) {
    return e.jarId === jarId;
  });
  return jsonOk(entries);
}

/** ownerId='admin' 인 controls 목록 반환 */
function handleGetAdminControls(p) {
  var controls = readAll(SHEET.CONTROLS).filter(function(c) {
    return c.ownerId === 'admin';
  });
  return jsonOk(controls);
}

/**
 * 단일 Jar 상세 반환
 * currentAmount = entries.amount 합계 + donation_in netAmount 합계
 */
function handleGetJar(p) {
  var jarId = p.jarId;
  if (!jarId) return jsonErr('jarId 필요');

  var jars = readAll(SHEET.JARS).filter(function(j) { return j.jarId === jarId; });
  if (jars.length === 0) return jsonErr('Jar를 찾을 수 없습니다: ' + jarId);

  var jar = jars[0];
  var entries = readAll(SHEET.ENTRIES).filter(function(e) { return e.jarId === jarId; });
  var entriesSum = entries.reduce(function(sum, e) { return sum + (Number(e.amount) || 0); }, 0);

  // donation_in 합계 반영
  var donationsIn = readAll(SHEET.DONATION_IN).filter(function(d) { return d.toJarId === jarId; });
  var donationsInSum = donationsIn.reduce(function(sum, d) { return sum + (Number(d.netAmount) || 0); }, 0);

  // donation_out 합계 반영
  var donationsOut = readAll(SHEET.DONATION_OUT).filter(function(d) { return d.fromJarId === jarId; });
  var donationsOutSum = donationsOut.reduce(function(sum, d) { return sum + (Number(d.requestAmount) || 0); }, 0);

  var currentAmount = entriesSum + donationsInSum - donationsOutSum;

  return jsonOk(Object.assign({}, jar, {
    currentAmount: currentAmount,
    entryCount: entries.length + donationsIn.length,
  }));
}

/**
 * jarId 기준 전체 이력 반환 (entries + donation_in + donation_out 통합)
 * type: 'entry' | 'donation_in' | 'donation_out'
 */
function handleGetHistory(p) {
  var jarId = p.jarId;
  if (!jarId) return jsonErr('jarId 필요');

  var rows = [];

  // 일반 적립 entries
  readAll(SHEET.ENTRIES).filter(function(e) { return e.jarId === jarId; }).forEach(function(e) {
    rows.push({
      type: 'entry',
      id: e.entryId,
      amount: Number(e.amount) || 0,
      note: e.note || '',
      createdAt: e.createdAt || '',
    });
  });

  // 기부 수신 donation_in
  readAll(SHEET.DONATION_IN).filter(function(d) { return d.toJarId === jarId; }).forEach(function(d) {
    rows.push({
      type: 'donation_in',
      id: d.donationId,
      amount: Number(d.netAmount) || 0,
      note: '🦝 너구리 공제 후 수령',
      fromJarId: d.fromJarId || '',
      createdAt: d.createdAt || '',
    });
  });

  // 기부 발신 donation_out
  readAll(SHEET.DONATION_OUT).filter(function(d) { return d.fromJarId === jarId; }).forEach(function(d) {
    rows.push({
      type: 'donation_out',
      id: d.donationId,
      amount: -(Number(d.requestAmount) || 0),
      note: '↗️ 기부 발신 (수수료 ' + Math.round((Number(d.feeRate) || 0) * 100) + '%)',
      toJarId: d.toJarId || '',
      createdAt: d.createdAt || '',
    });
  });

  // 날짜 내림차순 정렬
  rows.sort(function(a, b) {
    return (b.createdAt || '') > (a.createdAt || '') ? 1 : -1;
  });

  return jsonOk(rows);
}

/**
 * S6: 이력 타임라인 + 멤버 기여 소계
 * - entries + donation_in + donation_out 통합, 역순 정렬
 * - 기여자 이름은 users 시트 조인
 * - donation 발신 Jar 이름은 jars 시트 조인
 * - memberSubtotals: entries 기준, userId별 합산
 */
function handleGetJarHistory(p) {
  var jarId = p.jarId;
  if (!jarId) return jsonErr('jarId 필요');

  // 보조 맵 로드
  var usersMap = {};
  readAll(SHEET.USERS).forEach(function(u) { usersMap[u.userId] = u; });

  var jarsMap = {};
  readAll(SHEET.JARS).forEach(function(j) { jarsMap[j.jarId] = j; });

  // entries → 이력 항목 변환
  var entryItems = readAll(SHEET.ENTRIES)
    .filter(function(e) { return e.jarId === jarId; })
    .map(function(e) {
      var user = usersMap[e.userId] || {};
      return {
        type:            'entry',
        id:              e.entryId,
        date:            String(e.createdAt || ''),
        userId:          e.userId || '',
        contributorName: user.name || e.userId || '(알 수 없음)',
        label:           e.note || '적립',
        amount:          Number(e.amount) || 0,
        icon:            '💰',
      };
    });

  // donation_in → 이력 항목 변환
  var donationItems = readAll(SHEET.DONATION_IN)
    .filter(function(d) { return d.toJarId === jarId; })
    .map(function(d) {
      var fromJar = jarsMap[d.fromJarId] || {};
      return {
        type:            'donation',
        id:              d.donationId,
        date:            String(d.createdAt || ''),
        userId:          fromJar.ownerId || '',
        contributorName: fromJar.name || d.fromJarId || '(알 수 없음)',
        label:           '기부',
        amount:          Number(d.netAmount) || 0,
        icon:            '🦝',
        requestAmount:   Number(d.requestAmount) || 0,
        feeRate:         Number(d.feeRate) || 0,
        feeAmount:       Number(d.feeAmount) || 0,
      };
    });

  // donation_out → 이력 항목 변환
  var donationOutItems = readAll(SHEET.DONATION_OUT)
    .filter(function(d) { return d.fromJarId === jarId; })
    .map(function(d) {
      var toJar = jarsMap[d.toJarId] || {};
      return {
        type:            'donation_out',
        id:              d.donationId,
        date:            String(d.createdAt || ''),
        userId:          '',
        contributorName: toJar.name || d.toJarId || '(알 수 없음)',
        label:           '기부 발신 (수수료 ' + Math.round((Number(d.feeRate) || 0) * 100) + '%)',
        amount:          -(Number(d.requestAmount) || 0),
        icon:            '↗️',
      };
    });

  // 통합 후 날짜 역순 정렬
  var history = entryItems.concat(donationItems).concat(donationOutItems);
  history.sort(function(a, b) {
    return (b.date > a.date) ? 1 : (b.date < a.date) ? -1 : 0;
  });

  // 멤버별 기여 소계 (entries 기준)
  var subtotalMap = {};
  entryItems.forEach(function(e) {
    if (!subtotalMap[e.userId]) {
      subtotalMap[e.userId] = { userId: e.userId, name: e.contributorName, total: 0 };
    }
    subtotalMap[e.userId].total += e.amount;
  });
  var memberSubtotals = [];
  Object.keys(subtotalMap).forEach(function(k) { memberSubtotals.push(subtotalMap[k]); });
  memberSubtotals.sort(function(a, b) { return b.total - a.total; });

  return jsonOk({ history: history, memberSubtotals: memberSubtotals });
}

/**
 * 전체 Jar 목록 반환 (탐색용)
 */
function handleGetAllJars(p) {
  return jsonOk(readAll(SHEET.JARS));
}

// ─── 초기화 헬퍼 (수동 실행 — 배포 전 1회) ───────────────────────────────────

/**
 * Apps Script 에디터에서 직접 실행하여 필요한 시트와 헤더를 생성합니다.
 * 이미 시트가 있으면 건너뜁니다.
 */
function initSheets() {
  var spreadsheet = ss();

  var schemas = [
    {
      name: SHEET.USERS,
      cols: ['userId', 'name', 'email', 'createdAt'],
    },
    {
      name: SHEET.JARS,
      cols: ['jarId', 'name', 'description', 'ownerId', 'goalAmount', 'controlId', 'createdAt', 'archived', 'archivedAt'],
    },
    {
      name: SHEET.JAR_MEMBERS,
      cols: ['memberId', 'jarId', 'userId', 'role', 'controlId', 'joinedAt'],
    },
    {
      name: SHEET.ENTRIES,
      cols: ['entryId', 'jarId', 'userId', 'amount', 'note', 'createdAt'],
    },
    {
      name: SHEET.DONATION_OUT,
      cols: ['donationId', 'fromJarId', 'toJarId', 'requestAmount', 'feeRate', 'feeAmount', 'netAmount', 'createdAt'],
    },
    {
      name: SHEET.DONATION_IN,
      cols: ['donationId', 'toJarId', 'fromJarId', 'requestAmount', 'feeRate', 'feeAmount', 'netAmount', 'createdAt'],
    },
    {
      name: SHEET.CONTROLS,
      cols: ['controlId', 'name', 'description', 'ownerId', 'type', 'createdAt'],
    },
  ];

  schemas.forEach(function(s) {
    var existing = spreadsheet.getSheetByName(s.name);
    if (!existing) {
      var newSheet = spreadsheet.insertSheet(s.name);
      newSheet.appendRow(s.cols);
      Logger.log('시트 생성: ' + s.name);
    } else {
      // 기존 시트에 새 컬럼이 추가됐으면 헤더 행에 append
      var hdr = existing.getRange(1, 1, 1, existing.getLastColumn()).getValues()[0];
      var added = [];
      s.cols.forEach(function(col) {
        if (hdr.indexOf(col) === -1) {
          var nextCol = hdr.length + added.length + 1;
          existing.getRange(1, nextCol).setValue(col);
          added.push(col);
        }
      });
      if (added.length > 0) {
        Logger.log('컬럼 추가: ' + s.name + ' → ' + added.join(', '));
      } else {
        Logger.log('이미 존재: ' + s.name + ' (건너뜀)');
      }
    }
  });

  Logger.log('initSheets 완료');
}

/**
 * 모든 시트의 데이터를 삭제합니다 (헤더 행은 유지).
 * Apps Script 에디터에서 직접 실행하세요.
 * v1.0.0 출시용 — 테스트 데이터 정리.
 */
function clearAllData() {
  var spreadsheet = ss();
  var names = [SHEET.USERS, SHEET.JARS, SHEET.JAR_MEMBERS, SHEET.ENTRIES,
               SHEET.DONATION_OUT, SHEET.DONATION_IN, SHEET.CONTROLS];
  names.forEach(function(name) {
    var sh = spreadsheet.getSheetByName(name);
    if (!sh) return;
    var last = sh.getLastRow();
    if (last > 1) {
      sh.deleteRows(2, last - 1);
      Logger.log('삭제 완료: ' + name + ' (' + (last - 1) + '행)');
    } else {
      Logger.log('데이터 없음: ' + name);
    }
  });
  Logger.log('clearAllData 완료 — 모든 시트 초기화됨');
}
