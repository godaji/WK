/**
 * DreamJar — Supabase Client Module
 * CMPA-893: Replaces Apps Script (Code.gs) backend
 *
 * Usage in index.html:
 *   <script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
 *   <script src="./supabase/supabase.js"></script>
 *   <script src="./app.js"></script>
 *
 * Configure SUPABASE_URL and SUPABASE_ANON_KEY before use.
 */
(() => {
  'use strict';

  // ── Configuration ──────────────────────────────────────────
  const SUPABASE_URL      = 'https://odtivpszffoufyiufqwy.supabase.co';
  const SUPABASE_ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9kdGl2cHN6ZmZvdWZ5aXVmcXd5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM2ODkzMTYsImV4cCI6MjA5OTI2NTMxNn0.XrXsMLtRCUbAJvFdWz_JMZ3VwFWwGBsP2YqQ0NO7m7I';

  const supabase = window.supabase.createClient(SUPABASE_URL, SUPABASE_ANON_KEY);

  // ── Auth helpers (CMPA-913: userId+password login) ─────────

  /**
   * Sign in with userId + password.
   * Internally maps userId → {userId}@dreamjar.io for Supabase Auth email/password.
   */
  async function signInWithPassword(userId, password) {
    const email = userId + '@dreamjar.io';
    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    if (error) throw error;
    return data;
  }

  async function signOut() {
    const { error } = await supabase.auth.signOut();
    if (error) throw error;
  }

  /** Get current auth session (null if not logged in) */
  async function getSession() {
    const { data: { session } } = await supabase.auth.getSession();
    return session;
  }

  /** Get the app-level userId from the current session */
  async function getAuthUserId() {
    const session = await getSession();
    if (!session) return null;
    // user_id is stored in users table; extract from user_metadata or query
    const meta = session.user?.user_metadata;
    if (meta?.user_id) return meta.user_id;
    // Fallback: derive from email ({userId}@dreamjar.io)
    const email = session.user?.email || '';
    if (email.endsWith('@dreamjar.io')) return email.replace('@dreamjar.io', '');
    return null;
  }

  /** Listen to auth state changes */
  function onAuthStateChange(callback) {
    return supabase.auth.onAuthStateChange(callback);
  }

  // ── ID generation (matches Code.gs pattern) ────────────────
  function newId(prefix) {
    return (prefix || 'id') + '_' + Date.now() + '_' + Math.floor(Math.random() * 1e6);
  }

  // ── API layer (drop-in replacement for apiFetchReal) ───────

  /**
   * Unified API function matching existing action/query interface.
   * Returns the same data shapes as Code.gs so app.js works with minimal changes.
   */
  async function supabaseApi({ action, query, params = {} }) {
    // POST actions
    if (action === 'registerUser')   return await registerUser(params);
    if (action === 'createJar')      return await createJar(params);
    if (action === 'joinJar')        return await joinJar(params);
    if (action === 'setControl')     return await setControl(params);
    if (action === 'createControl')  return await createControl(params);
    if (action === 'updateControl')  return await updateControl(params);
    if (action === 'deleteControl')  return await deleteControl(params);
    if (action === 'addEntry')       return await addEntry(params);
    if (action === 'deleteEntry')    return await deleteEntry(params);
    if (action === 'donate')         return await donateSingle(params);
    if (action === 'donateBulk')     return await donateBulk(params);
    if (action === 'archiveJar')     return await archiveJar(params);
    if (action === 'updateJarImage') return await updateJarImage(params.jarId, params.imageUrl);
    if (action === 'updateJarName')  return await updateJarName(params.jarId, params.name);

    // GET queries
    if (query === 'version')          return { version: 'supabase-v1.0' };
    if (query === 'checkSync')        return await checkSync(params);
    if (query === 'getJarsByUser')    return await getJarsByUser(params);
    if (query === 'getFullSync')      return await getFullSync(params);
    if (query === 'getEntries')       return await getEntries(params);
    if (query === 'getAdminControls') return await getAdminControls();
    if (query === 'getCustomControls') return await getCustomControls(params);
    if (query === 'getJar')           return await getJar(params);
    if (query === 'getHistory')       return await getHistory(params);
    if (query === 'getJarHistory')    return await getJarHistory(params);
    if (query === 'getAllJars')        return await getAllJars();
    if (query === 'searchJars')       return await searchJars(params);

    throw new Error('알 수 없는 action/query: ' + (action || query));
  }

  // ── Auto-ensure user exists (avoids FK violations) ─────────
  async function ensureUser(userId) {
    if (!userId) return;
    const { error } = await supabase.from('users').upsert({
      user_id:    userId,
      name:       '',
      email:      '',
      created_at: new Date().toISOString(),
    }, { onConflict: 'user_id', ignoreDuplicates: true });
    if (error) console.warn('[DreamJar] ensureUser:', error.message);
  }

  // ── POST actions ───────────────────────────────────────────

  async function registerUser(p) {
    const userId = p.userId || newId('u');
    const session = await getSession();
    const { error } = await supabase.from('users').upsert({
      user_id:    userId,
      name:       p.name || '',
      email:      p.email || '',
      auth_uid:   session?.user?.id || null,
      created_at: new Date().toISOString(),
    }, { onConflict: 'user_id' });
    if (error) throw error;
    return { userId };
  }

  async function createJar(p) {
    const jarId = p.jarId || newId('jar');
    const ts = new Date().toISOString();

    // Ensure owner exists in users table (FK constraint)
    await ensureUser(p.ownerId);

    const { error: jarErr } = await supabase.from('jars').insert({
      jar_id:      jarId,
      name:        p.name || '',
      description: p.description || '',
      owner_id:    p.ownerId || '',
      goal_amount: Number(p.goalAmount) || 0,
      control_id:  p.controlId || '',
      image_url:   p.imageUrl || null,
      created_at:  ts,
    });
    if (jarErr) throw jarErr;

    // Auto-add owner as member
    if (p.ownerId) {
      await supabase.from('jar_members').insert({
        member_id:  newId('m'),
        jar_id:     jarId,
        user_id:    p.ownerId,
        role:       'owner',
        control_id: p.controlId || '',
        joined_at:  ts,
      });
    }

    return { jarId };
  }

  async function joinJar(p) {
    const input = (p.jarId || '').trim();
    if (!input) throw new Error('Jar ID 또는 이름을 입력하세요');
    await ensureUser(p.userId);

    // Find jar by ID or name
    let { data: jar } = await supabase
      .from('jars').select('*')
      .or(`jar_id.eq.${input},name.eq.${input}`)
      .eq('archived', false)
      .limit(1).single();

    if (!jar) throw new Error('존재하지 않는 Jar입니다: ' + input);

    // Check existing membership
    const { data: existing } = await supabase
      .from('jar_members').select('member_id')
      .eq('jar_id', jar.jar_id).eq('user_id', p.userId || '')
      .limit(1);

    if (existing && existing.length > 0) {
      // Already a member — return success silently instead of error
      return { memberId: existing[0].member_id, jarName: jar.name || '', alreadyJoined: true };
    }

    const memberId = newId('m');
    const { error } = await supabase.from('jar_members').insert({
      member_id: memberId,
      jar_id:    jar.jar_id,
      user_id:   p.userId || '',
      role:      'member',
      joined_at: new Date().toISOString(),
    });
    if (error) throw error;

    return { memberId, jarName: jar.name || '' };
  }

  async function setControl(p) {
    if (p.memberId) {
      const { error } = await supabase
        .from('jar_members')
        .update({ control_id: p.controlId || '' })
        .eq('member_id', p.memberId);
      if (error) throw error;
      return { updated: true };
    }

    if (p.jarId && p.userId) {
      const { data: existing } = await supabase
        .from('jar_members').select('member_id')
        .eq('jar_id', p.jarId).eq('user_id', p.userId)
        .limit(1);

      if (existing && existing.length > 0) {
        const { error } = await supabase
          .from('jar_members')
          .update({ control_id: p.controlId || '' })
          .eq('member_id', existing[0].member_id);
        if (error) throw error;
      } else {
        // Auto-create owner row
        const { error } = await supabase.from('jar_members').insert({
          member_id:  newId('m'),
          jar_id:     p.jarId,
          user_id:    p.userId,
          role:       'owner',
          control_id: p.controlId || '',
          joined_at:  new Date().toISOString(),
        });
        if (error) throw error;
      }
      return { updated: true };
    }

    throw new Error('멤버를 찾을 수 없습니다: ' + (p.memberId || p.jarId || ''));
  }

  async function createControl(p) {
    const controlId = p.controlId || newId('ctrl');
    const { error } = await supabase.from('controls').insert({
      control_id:  controlId,
      name:        p.name || '',
      description: p.description || '',
      emoji:       p.emoji || '',
      owner_id:    p.ownerId || '',
      type:        p.type || '',
      items:       p.items || [],
      created_at:  new Date().toISOString(),
      updated_at:  new Date().toISOString(),
    });
    if (error) throw error;
    return { controlId };
  }

  async function updateControl(p) {
    if (!p.controlId) throw new Error('controlId 필요');
    const updates = { updated_at: new Date().toISOString() };
    if (p.name !== undefined)        updates.name        = p.name;
    if (p.description !== undefined) updates.description = p.description;
    if (p.emoji !== undefined)       updates.emoji       = p.emoji;
    if (p.items !== undefined)       updates.items       = p.items;
    const { error } = await supabase.from('controls')
      .update(updates).eq('control_id', p.controlId);
    if (error) throw error;
    return { updated: true };
  }

  async function deleteControl(p) {
    if (!p.controlId) throw new Error('controlId 필요');
    const { error } = await supabase.from('controls')
      .delete().eq('control_id', p.controlId);
    if (error) throw error;
    return { deleted: true };
  }

  async function addEntry(p) {
    await ensureUser(p.userId);
    const entryId = newId('ent');
    const { error } = await supabase.from('entries').insert({
      entry_id:   entryId,
      jar_id:     p.jarId || '',
      user_id:    p.userId || '',
      amount:     Number(p.amount) || 0,
      note:       p.note || '',
      created_at: new Date().toISOString(),
    });
    if (error) throw error;
    return { entryId };
  }

  async function deleteEntry(p) {
    const { data, error } = await supabase
      .from('entries')
      .delete()
      .eq('entry_id', p.entryId)
      .select();
    if (error) throw error;
    return { deleted: data && data.length > 0 };
  }

  async function donateSingle(p) {
    const { data, error } = await supabase.rpc('donate', {
      p_from_jar_id: p.fromJarId || '',
      p_to_jar_id:   p.toJarId || '',
      p_amount:      Number(p.amount) || 0,
    });
    if (error) throw error;
    return data;
  }

  async function donateBulk(p) {
    const { data, error } = await supabase.rpc('donate_bulk', {
      p_from_jar_id: p.fromJarId || '',
      p_to_jar_id:   p.toJarId || '',
      p_items:       p.items || [],
    });
    if (error) throw error;
    return data;
  }

  async function uploadJarImage(jarId, file) {
    const ext = file.name.split('.').pop() || 'jpg';
    const path = `${jarId}/${Date.now()}.${ext}`;
    const { error } = await supabase.storage
      .from('jar-images')
      .upload(path, file, { cacheControl: '3600', upsert: false });
    if (error) throw error;
    const { data: { publicUrl } } = supabase.storage
      .from('jar-images')
      .getPublicUrl(path);
    return publicUrl;
  }

  async function updateJarImage(jarId, imageUrl) {
    const { error } = await supabase
      .from('jars')
      .update({ image_url: imageUrl })
      .eq('jar_id', jarId);
    if (error) throw error;
    return { updated: true };
  }

  async function updateJarName(jarId, name) {
    if (!jarId) throw new Error('jarId 필요');
    if (!name || !name.trim()) throw new Error('이름을 입력하세요');
    const { error } = await supabase
      .from('jars')
      .update({ name: name.trim() })
      .eq('jar_id', jarId);
    if (error) throw error;
    return { updated: true };
  }

  async function archiveJar(p) {
    const { error } = await supabase
      .from('jars')
      .update({ archived: true, archived_at: new Date().toISOString() })
      .eq('jar_id', p.jarId);
    if (error) throw error;
    return { archived: true };
  }

  // ── GET queries ────────────────────────────────────────────

  async function checkSync(p) {
    const jarIdsStr = p.jarIds || '';
    if (!jarIdsStr) return { jarModified: {} };
    const jarIds = jarIdsStr.split(',').filter(Boolean);

    const { data, error } = await supabase
      .from('jars').select('jar_id, updated_at')
      .in('jar_id', jarIds);
    if (error) throw error;

    const jarModified = {};
    for (const row of (data || [])) {
      jarModified[row.jar_id] = row.updated_at || 'init';
    }
    // Fill missing with 'init'
    for (const id of jarIds) {
      if (!jarModified[id]) jarModified[id] = 'init';
    }
    return { jarModified };
  }

  async function getJarsByUser(p) {
    const userId = p.userId;
    if (!userId) throw new Error('userId 필요');

    // Get memberships
    const { data: memberships } = await supabase
      .from('jar_members').select('*')
      .eq('user_id', userId);

    const memberJarIds = (memberships || []).map(m => m.jar_id);

    // Also include owned jars not in memberships
    const { data: ownedJars } = await supabase
      .from('jars').select('*')
      .eq('owner_id', userId).eq('archived', false);

    const allJarIds = [...new Set([
      ...memberJarIds,
      ...(ownedJars || []).map(j => j.jar_id),
    ])];

    if (allJarIds.length === 0) return [];

    // Fetch jars
    const { data: jars } = await supabase
      .from('jars').select('*')
      .in('jar_id', allJarIds).eq('archived', false);

    // Fetch entries + donations for amount calc
    const { data: entries } = await supabase
      .from('entries').select('jar_id, amount')
      .in('jar_id', allJarIds);
    const { data: dIn } = await supabase
      .from('donation_in').select('to_jar_id, net_amount')
      .in('to_jar_id', allJarIds);
    const { data: dOut } = await supabase
      .from('donation_out').select('from_jar_id, request_amount')
      .in('from_jar_id', allJarIds);

    const membershipMap = {};
    for (const m of (memberships || [])) membershipMap[m.jar_id] = m;

    const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString();

    return (jars || []).map(j => {
      const jarEntries = (entries || []).filter(e => e.jar_id === j.jar_id);
      const entriesSum = jarEntries.reduce((s, e) => s + (Number(e.amount) || 0), 0);
      const dInSum = (dIn || []).filter(d => d.to_jar_id === j.jar_id)
        .reduce((s, d) => s + (Number(d.net_amount) || 0), 0);
      const dOutSum = (dOut || []).filter(d => d.from_jar_id === j.jar_id)
        .reduce((s, d) => s + (Number(d.request_amount) || 0), 0);
      const m = membershipMap[j.jar_id] || {};
      return {
        jarId:               j.jar_id,
        name:                j.name,
        description:         j.description,
        ownerId:             j.owner_id,
        goalAmount:          j.goal_amount,
        controlId:           m.control_id || j.control_id || '',
        createdAt:           j.created_at,
        role:                m.role || 'owner',
        memberId:            m.member_id || '',
        imageUrl:            j.image_url || '',
        currentAmount:       entriesSum + dInSum - dOutSum,
        recentSevenDayTotal: 0, // simplified for PoC
      };
    });
  }

  async function getFullSync(p) {
    // Reuse getJarsByUser for jar list
    const jars = await getJarsByUser(p);
    const jarIds = jars.map(j => j.jarId);
    if (jarIds.length === 0) return { jars, histories: {}, jarModified: {} };

    // Fetch all data for histories
    const [
      { data: allUsers },
      { data: allEntries },
      { data: allDonIn },
      { data: allDonOut },
      { data: allJarsRaw },
    ] = await Promise.all([
      supabase.from('users').select('user_id, name'),
      supabase.from('entries').select('*').in('jar_id', jarIds),
      supabase.from('donation_in').select('*').in('to_jar_id', jarIds),
      supabase.from('donation_out').select('*').in('from_jar_id', jarIds),
      supabase.from('jars').select('jar_id, name, owner_id, updated_at').in('jar_id', jarIds),
    ]);

    const usersMap = {};
    for (const u of (allUsers || [])) usersMap[u.user_id] = u;
    const jarsMap = {};
    for (const j of jars) jarsMap[j.jarId] = j;
    // Fetch foreign jar names (from donation senders/receivers not in user's jars)
    const foreignJarIds = new Set();
    for (const d of (allDonIn || [])) { if (d.from_jar_id && !jarsMap[d.from_jar_id]) foreignJarIds.add(d.from_jar_id); }
    for (const d of (allDonOut || [])) { if (d.to_jar_id && !jarsMap[d.to_jar_id]) foreignJarIds.add(d.to_jar_id); }
    if (foreignJarIds.size > 0) {
      const { data: foreignJars } = await supabase.from('jars').select('jar_id, name, owner_id').in('jar_id', [...foreignJarIds]);
      for (const fj of (foreignJars || [])) jarsMap[fj.jar_id] = { jarId: fj.jar_id, name: fj.name, ownerId: fj.owner_id };
    }
    const donOutMap = {};
    for (const d of (allDonOut || [])) donOutMap[d.donation_id] = d;

    const histories = {};
    for (const jarInfo of jars) {
      const jarId = jarInfo.jarId;

      const entryItems = (allEntries || []).filter(e => e.jar_id === jarId).map(e => {
        const user = usersMap[e.user_id] || {};
        return {
          type: 'entry', id: e.entry_id, date: e.created_at,
          userId: e.user_id, contributorName: user.name || e.user_id || '(알 수 없음)',
          label: e.note || '적립', amount: Number(e.amount) || 0, icon: '💰',
        };
      });

      const donationItems = (allDonIn || []).filter(d => d.to_jar_id === jarId).map(d => {
        const fromJar = jarsMap[d.from_jar_id] || {};
        const dOut = donOutMap[d.donation_id] || {};
        const reqAmt = Number(dOut.request_amount || d.request_amount) || 0;
        const fRate = Number(dOut.fee_rate || d.fee_rate) || 0;
        return {
          type: 'donation', id: d.donation_id, date: d.created_at,
          userId: fromJar.ownerId || '', contributorName: fromJar.name || d.from_jar_id || '(알 수 없음)',
          label: reqAmt > 0 ? `기부(${reqAmt.toLocaleString()}원, 수수료${Math.round(fRate * 100)}%)` : '기부',
          amount: Number(d.net_amount) || 0, icon: '🦝',
          requestAmount: reqAmt, feeRate: fRate,
          feeAmount: Number(dOut.fee_amount || d.fee_amount) || 0,
          sourceNotes: d.source_notes || dOut.source_notes || '',
        };
      });

      const donOutItems = (allDonOut || []).filter(d => d.from_jar_id === jarId).map(d => {
        const toJar = jarsMap[d.to_jar_id] || {};
        return {
          type: 'donation_out', id: d.donation_id, date: d.created_at,
          userId: '', contributorName: toJar.name || d.to_jar_id || '(알 수 없음)',
          label: '기부 발신 (수수료 ' + Math.round((Number(d.fee_rate) || 0) * 100) + '%)',
          amount: -(Number(d.request_amount) || 0), icon: '↗️',
          sourceNotes: d.source_notes || '',
        };
      });

      const history = [...entryItems, ...donationItems, ...donOutItems]
        .sort((a, b) => (b.date > a.date ? 1 : b.date < a.date ? -1 : 0));

      const subtotalMap = {};
      entryItems.forEach(e => {
        if (!subtotalMap[e.userId]) subtotalMap[e.userId] = { userId: e.userId, name: e.contributorName, total: 0 };
        subtotalMap[e.userId].total += e.amount;
      });

      histories[jarId] = {
        history,
        memberSubtotals: Object.values(subtotalMap).sort((a, b) => b.total - a.total),
      };
    }

    const jarModified = {};
    for (const j of (allJarsRaw || [])) jarModified[j.jar_id] = j.updated_at || 'init';

    return { jars, histories, jarModified };
  }

  async function getEntries(p) {
    if (!p.jarId) throw new Error('jarId 필요');
    const { data, error } = await supabase
      .from('entries').select('*')
      .eq('jar_id', p.jarId)
      .order('created_at', { ascending: false });
    if (error) throw error;
    return (data || []).map(e => ({
      entryId: e.entry_id, jarId: e.jar_id, userId: e.user_id,
      amount: e.amount, note: e.note, createdAt: e.created_at,
    }));
  }

  async function getAdminControls() {
    const { data, error } = await supabase
      .from('controls').select('*')
      .eq('owner_id', 'admin');
    if (error) throw error;
    return (data || []).map(c => ({
      controlId: c.control_id, name: c.name, description: c.description,
      ownerId: c.owner_id, type: c.type, createdAt: c.created_at,
    }));
  }

  async function getCustomControls(p) {
    if (!p.userId) throw new Error('userId 필요');
    const { data, error } = await supabase
      .from('controls').select('*')
      .eq('owner_id', p.userId)
      .order('created_at', { ascending: false });
    if (error) throw error;
    return (data || []).map(c => ({
      controlId: c.control_id, name: c.name, description: c.description,
      emoji: c.emoji || '', ownerId: c.owner_id, type: c.type || 'custom',
      items: c.items || [], createdAt: c.created_at,
    }));
  }

  async function getJar(p) {
    if (!p.jarId) throw new Error('jarId 필요');
    const { data: jar, error } = await supabase
      .from('jars').select('*')
      .eq('jar_id', p.jarId).single();
    if (error) throw error;

    const [{ data: entries }, { data: dIn }, { data: dOut }] = await Promise.all([
      supabase.from('entries').select('amount').eq('jar_id', p.jarId),
      supabase.from('donation_in').select('net_amount').eq('to_jar_id', p.jarId),
      supabase.from('donation_out').select('request_amount').eq('from_jar_id', p.jarId),
    ]);

    const entriesSum = (entries || []).reduce((s, e) => s + (Number(e.amount) || 0), 0);
    const dInSum = (dIn || []).reduce((s, d) => s + (Number(d.net_amount) || 0), 0);
    const dOutSum = (dOut || []).reduce((s, d) => s + (Number(d.request_amount) || 0), 0);

    return {
      jarId: jar.jar_id, name: jar.name, description: jar.description,
      ownerId: jar.owner_id, goalAmount: jar.goal_amount,
      controlId: jar.control_id, createdAt: jar.created_at,
      imageUrl: jar.image_url || '',
      currentAmount: entriesSum + dInSum - dOutSum,
      entryCount: (entries || []).length + (dIn || []).length,
    };
  }

  async function getHistory(p) {
    if (!p.jarId) throw new Error('jarId 필요');

    const [{ data: entries }, { data: dIn }, { data: dOut }] = await Promise.all([
      supabase.from('entries').select('*').eq('jar_id', p.jarId),
      supabase.from('donation_in').select('*').eq('to_jar_id', p.jarId),
      supabase.from('donation_out').select('*').eq('from_jar_id', p.jarId),
    ]);

    const rows = [
      ...(entries || []).map(e => ({
        type: 'entry', id: e.entry_id, amount: Number(e.amount) || 0,
        note: e.note || '', createdAt: e.created_at,
      })),
      ...(dIn || []).map(d => ({
        type: 'donation_in', id: d.donation_id, amount: Number(d.net_amount) || 0,
        note: '🦝 너구리 공제 후 수령', fromJarId: d.from_jar_id, createdAt: d.created_at,
      })),
      ...(dOut || []).map(d => ({
        type: 'donation_out', id: d.donation_id, amount: -(Number(d.request_amount) || 0),
        note: '↗️ 기부 발신 (수수료 ' + Math.round((Number(d.fee_rate) || 0) * 100) + '%)',
        toJarId: d.to_jar_id, createdAt: d.created_at,
      })),
    ].sort((a, b) => (b.createdAt > a.createdAt ? 1 : -1));

    return rows;
  }

  async function getJarHistory(p) {
    if (!p.jarId) throw new Error('jarId 필요');
    const jarId = p.jarId;

    const [{ data: users }, { data: jarsData }, { data: entries }, { data: dIn }, { data: dOut }] = await Promise.all([
      supabase.from('users').select('user_id, name'),
      supabase.from('jars').select('jar_id, name, owner_id'),
      supabase.from('entries').select('*').eq('jar_id', jarId),
      supabase.from('donation_in').select('*').eq('to_jar_id', jarId),
      supabase.from('donation_out').select('*'),
    ]);

    const usersMap = {};
    for (const u of (users || [])) usersMap[u.user_id] = u;
    const jarsMap = {};
    for (const j of (jarsData || [])) jarsMap[j.jar_id] = j;
    // Fetch foreign jar names (donation senders/receivers not yet in jarsMap)
    const foreignJarIds = new Set();
    for (const d of (dIn || [])) { if (d.from_jar_id && !jarsMap[d.from_jar_id]) foreignJarIds.add(d.from_jar_id); }
    for (const d of (dOut || [])) { if (d.to_jar_id && !jarsMap[d.to_jar_id]) foreignJarIds.add(d.to_jar_id); }
    if (foreignJarIds.size > 0) {
      const { data: foreignJars } = await supabase.from('jars').select('jar_id, name, owner_id').in('jar_id', [...foreignJarIds]);
      for (const fj of (foreignJars || [])) jarsMap[fj.jar_id] = fj;
    }
    const donOutMap = {};
    for (const d of (dOut || [])) donOutMap[d.donation_id] = d;

    const entryItems = (entries || []).map(e => {
      const user = usersMap[e.user_id] || {};
      return {
        type: 'entry', id: e.entry_id, date: e.created_at,
        userId: e.user_id, contributorName: user.name || e.user_id || '(알 수 없음)',
        label: e.note || '적립', amount: Number(e.amount) || 0, icon: '💰',
      };
    });

    const donationItems = (dIn || []).map(d => {
      const fromJar = jarsMap[d.from_jar_id] || {};
      const dOutRec = donOutMap[d.donation_id] || {};
      const reqAmt = Number(dOutRec.request_amount || d.request_amount) || 0;
      const fRate = Number(dOutRec.fee_rate || d.fee_rate) || 0;
      return {
        type: 'donation', id: d.donation_id, date: d.created_at,
        userId: fromJar.owner_id || '', contributorName: fromJar.name || d.from_jar_id || '(알 수 없음)',
        label: reqAmt > 0 ? `기부(${reqAmt.toLocaleString()}원, 수수료${Math.round(fRate * 100)}%)` : '기부',
        amount: Number(d.net_amount) || 0, icon: '🦝',
        requestAmount: reqAmt, feeRate: fRate,
        feeAmount: Number(dOutRec.fee_amount || d.fee_amount) || 0,
        sourceNotes: d.source_notes || dOutRec.source_notes || '',
      };
    });

    const donOutItems = (dOut || []).filter(d => d.from_jar_id === jarId).map(d => {
      const toJar = jarsMap[d.to_jar_id] || {};
      return {
        type: 'donation_out', id: d.donation_id, date: d.created_at,
        userId: '', contributorName: toJar.name || d.to_jar_id || '(알 수 없음)',
        label: '기부 발신 (수수료 ' + Math.round((Number(d.fee_rate) || 0) * 100) + '%)',
        amount: -(Number(d.request_amount) || 0), icon: '↗️',
        sourceNotes: d.source_notes || '',
      };
    });

    const history = [...entryItems, ...donationItems, ...donOutItems]
      .sort((a, b) => (b.date > a.date ? 1 : b.date < a.date ? -1 : 0));

    const subtotalMap = {};
    entryItems.forEach(e => {
      if (!subtotalMap[e.userId]) subtotalMap[e.userId] = { userId: e.userId, name: e.contributorName, total: 0 };
      subtotalMap[e.userId].total += e.amount;
    });

    return {
      history,
      memberSubtotals: Object.values(subtotalMap).sort((a, b) => b.total - a.total),
    };
  }

  async function searchJars(p) {
    const q = (p.query || '').trim();
    if (!q) return [];

    // Search unarchived jars whose name contains the query (case-insensitive)
    const { data: jars, error } = await supabase
      .from('jars').select('jar_id, name, owner_id')
      .eq('archived', false)
      .ilike('name', `%${q}%`)
      .limit(20);
    if (error) throw error;
    if (!jars || jars.length === 0) return [];

    // Fetch owner names for display
    const ownerIds = [...new Set(jars.map(j => j.owner_id).filter(Boolean))];
    let ownersMap = {};
    if (ownerIds.length > 0) {
      const { data: users } = await supabase
        .from('users').select('user_id, name')
        .in('user_id', ownerIds);
      for (const u of (users || [])) ownersMap[u.user_id] = u.name || u.user_id;
    }

    // Check which jars the current user already joined
    const userId = p.userId || '';
    let joinedSet = new Set();
    if (userId) {
      const jarIds = jars.map(j => j.jar_id);
      const { data: members } = await supabase
        .from('jar_members').select('jar_id')
        .eq('user_id', userId)
        .in('jar_id', jarIds);
      for (const m of (members || [])) joinedSet.add(m.jar_id);
    }

    return jars.map(j => ({
      jarId: j.jar_id,
      name: j.name,
      ownerName: ownersMap[j.owner_id] || j.owner_id || '',
      alreadyJoined: joinedSet.has(j.jar_id),
    }));
  }

  async function getAllJars() {
    const { data, error } = await supabase.from('jars').select('*');
    if (error) throw error;
    return (data || []).map(j => ({
      jarId: j.jar_id, name: j.name, description: j.description,
      ownerId: j.owner_id, goalAmount: j.goal_amount,
      controlId: j.control_id, createdAt: j.created_at,
      imageUrl: j.image_url || '',
      archived: j.archived, archivedAt: j.archived_at,
    }));
  }

  // ── Expose to global scope ─────────────────────────────────
  window.DreamJarSupabase = {
    supabase,
    api:       supabaseApi,
    uploadJarImage,
    auth: {
      signInWithPassword,
      signOut,
      getSession,
      getAuthUserId,
      onAuthStateChange,
    },
  };
})();
