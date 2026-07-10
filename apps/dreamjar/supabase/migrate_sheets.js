#!/usr/bin/env node
/**
 * DreamJar — Google Sheets → Supabase Migration Script
 * CMPA-893 Phase 2
 *
 * Prerequisites:
 *   npm install @supabase/supabase-js googleapis
 *
 * Usage:
 *   SUPABASE_URL=https://xxx.supabase.co \
 *   SUPABASE_SERVICE_KEY=eyJ... \
 *   SPREADSHEET_ID=14aUcea8p-LWS9TcscIIryZQXg6JAfwDavttDquKHGHc \
 *   node migrate_sheets.js
 *
 * The script uses the Supabase service-role key (bypasses RLS) for bulk import.
 * Google Sheets access uses API key or Application Default Credentials.
 */

const { createClient } = require('@supabase/supabase-js');
const { google } = require('googleapis');

// ── Config ──────────────────────────────────────────────────
const SUPABASE_URL         = process.env.SUPABASE_URL;
const SUPABASE_SERVICE_KEY = process.env.SUPABASE_SERVICE_KEY;
const SPREADSHEET_ID       = process.env.SPREADSHEET_ID || '14aUcea8p-LWS9TcscIIryZQXg6JAfwDavttDquKHGHc';
const GOOGLE_API_KEY       = process.env.GOOGLE_API_KEY || '';

if (!SUPABASE_URL || !SUPABASE_SERVICE_KEY) {
  console.error('❌ SUPABASE_URL and SUPABASE_SERVICE_KEY are required');
  process.exit(1);
}

const supabase = createClient(SUPABASE_URL, SUPABASE_SERVICE_KEY);

// ── Google Sheets reader ────────────────────────────────────
async function readSheet(sheetName) {
  const sheets = google.sheets({ version: 'v4', auth: GOOGLE_API_KEY || undefined });
  const range = `${sheetName}!A1:ZZ`;

  const res = await sheets.spreadsheets.values.get({
    spreadsheetId: SPREADSHEET_ID,
    range,
  });

  const rows = res.data.values;
  if (!rows || rows.length < 2) {
    console.log(`  ⚠ ${sheetName}: empty or header-only`);
    return [];
  }

  const headers = rows[0];
  return rows.slice(1).map(row => {
    const obj = {};
    headers.forEach((h, i) => { obj[h] = row[i] !== undefined ? row[i] : ''; });
    return obj;
  });
}

// ── Helpers ──────────────────────────────────────────────────
function toSnake(camelStr) {
  return camelStr.replace(/([A-Z])/g, '_$1').toLowerCase();
}

/** Convert sheet row keys from camelCase to snake_case */
function snakeKeys(obj) {
  const out = {};
  for (const [k, v] of Object.entries(obj)) {
    out[toSnake(k)] = v;
  }
  return out;
}

function parseNum(v) {
  const n = Number(v);
  return isNaN(n) ? 0 : n;
}

function parseBool(v) {
  return v === true || v === 'TRUE' || v === 'true';
}

function parseTs(v) {
  if (!v) return new Date().toISOString();
  try {
    const d = new Date(v);
    return isNaN(d.getTime()) ? new Date().toISOString() : d.toISOString();
  } catch {
    return new Date().toISOString();
  }
}

// ── Migration functions ─────────────────────────────────────

async function migrateUsers() {
  const rows = await readSheet('users');
  if (rows.length === 0) return;

  const records = rows.map(r => ({
    user_id:    r.userId || '',
    name:       r.name || '',
    email:      r.email || '',
    created_at: parseTs(r.createdAt),
  })).filter(r => r.user_id);

  const { error } = await supabase.from('users').upsert(records, { onConflict: 'user_id' });
  if (error) throw new Error(`users: ${error.message}`);
  console.log(`  ✅ users: ${records.length} rows`);
}

async function migrateJars() {
  const rows = await readSheet('jars');
  if (rows.length === 0) return;

  const records = rows.map(r => ({
    jar_id:      r.jarId || '',
    name:        r.name || '',
    description: r.description || '',
    owner_id:    r.ownerId || '',
    goal_amount: parseNum(r.goalAmount),
    control_id:  r.controlId || '',
    created_at:  parseTs(r.createdAt),
    archived:    parseBool(r.archived),
    archived_at: r.archivedAt ? parseTs(r.archivedAt) : null,
  })).filter(r => r.jar_id);

  const { error } = await supabase.from('jars').upsert(records, { onConflict: 'jar_id' });
  if (error) throw new Error(`jars: ${error.message}`);
  console.log(`  ✅ jars: ${records.length} rows`);
}

async function migrateJarMembers() {
  const rows = await readSheet('jar_members');
  if (rows.length === 0) return;

  const records = rows.map(r => ({
    member_id:  r.memberId || '',
    jar_id:     r.jarId || '',
    user_id:    r.userId || '',
    role:       r.role || 'member',
    control_id: r.controlId || '',
    joined_at:  parseTs(r.joinedAt),
  })).filter(r => r.member_id && r.jar_id);

  const { error } = await supabase.from('jar_members').upsert(records, { onConflict: 'member_id' });
  if (error) throw new Error(`jar_members: ${error.message}`);
  console.log(`  ✅ jar_members: ${records.length} rows`);
}

async function migrateEntries() {
  const rows = await readSheet('entries');
  if (rows.length === 0) return;

  const records = rows.map(r => ({
    entry_id:   r.entryId || '',
    jar_id:     r.jarId || '',
    user_id:    r.userId || '',
    amount:     parseNum(r.amount),
    note:       r.note || '',
    created_at: parseTs(r.createdAt),
  })).filter(r => r.entry_id);

  // Batch in chunks of 500
  for (let i = 0; i < records.length; i += 500) {
    const batch = records.slice(i, i + 500);
    const { error } = await supabase.from('entries').upsert(batch, { onConflict: 'entry_id' });
    if (error) throw new Error(`entries batch ${i}: ${error.message}`);
  }
  console.log(`  ✅ entries: ${records.length} rows`);
}

async function migrateDonationOut() {
  const rows = await readSheet('donation_out');
  if (rows.length === 0) return;

  const records = rows.map(r => ({
    donation_id:    r.donationId || '',
    from_jar_id:    r.fromJarId || '',
    to_jar_id:      r.toJarId || '',
    request_amount: parseNum(r.requestAmount),
    fee_rate:       parseNum(r.feeRate),
    fee_amount:     parseNum(r.feeAmount),
    net_amount:     parseNum(r.netAmount),
    source_notes:   r.sourceNotes || '',
    created_at:     parseTs(r.createdAt),
  })).filter(r => r.donation_id);

  const { error } = await supabase.from('donation_out').upsert(records, { onConflict: 'donation_id' });
  if (error) throw new Error(`donation_out: ${error.message}`);
  console.log(`  ✅ donation_out: ${records.length} rows`);
}

async function migrateDonationIn() {
  const rows = await readSheet('donation_in');
  if (rows.length === 0) return;

  const records = rows.map(r => ({
    donation_id:    r.donationId || '',
    to_jar_id:      r.toJarId || '',
    from_jar_id:    r.fromJarId || '',
    request_amount: parseNum(r.requestAmount),
    fee_rate:       parseNum(r.feeRate),
    fee_amount:     parseNum(r.feeAmount),
    net_amount:     parseNum(r.netAmount),
    source_notes:   r.sourceNotes || '',
    created_at:     parseTs(r.createdAt),
  })).filter(r => r.donation_id);

  const { error } = await supabase.from('donation_in').upsert(records, { onConflict: 'donation_id' });
  if (error) throw new Error(`donation_in: ${error.message}`);
  console.log(`  ✅ donation_in: ${records.length} rows`);
}

async function migrateControls() {
  const rows = await readSheet('controls');
  if (rows.length === 0) return;

  const records = rows.map(r => ({
    control_id:  r.controlId || '',
    name:        r.name || '',
    description: r.description || '',
    owner_id:    r.ownerId || '',
    type:        r.type || '',
    created_at:  parseTs(r.createdAt),
  })).filter(r => r.control_id);

  const { error } = await supabase.from('controls').upsert(records, { onConflict: 'control_id' });
  if (error) throw new Error(`controls: ${error.message}`);
  console.log(`  ✅ controls: ${records.length} rows`);
}

// ── Verification ─────────────────────────────────────────────

async function verify() {
  console.log('\n📊 Verification — row counts:');
  const tables = ['users', 'jars', 'jar_members', 'entries', 'donation_out', 'donation_in', 'controls'];
  for (const t of tables) {
    const { count, error } = await supabase.from(t).select('*', { count: 'exact', head: true });
    console.log(`  ${t}: ${error ? 'ERROR' : count} rows`);
  }
}

// ── Main ─────────────────────────────────────────────────────

async function main() {
  console.log('🚀 DreamJar Sheets → Supabase Migration');
  console.log(`  Spreadsheet: ${SPREADSHEET_ID}`);
  console.log(`  Supabase:    ${SUPABASE_URL}\n`);

  // Order matters: users → jars → jar_members → entries → donations → controls
  await migrateUsers();
  await migrateJars();
  await migrateJarMembers();
  await migrateEntries();
  await migrateDonationOut();
  await migrateDonationIn();
  await migrateControls();

  await verify();
  console.log('\n✅ Migration complete!');
}

main().catch(err => {
  console.error('❌ Migration failed:', err.message);
  process.exit(1);
});
