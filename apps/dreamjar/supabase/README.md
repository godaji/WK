# DreamJar Supabase Migration (CMPA-893)

## Overview

Code.gs (Google Apps Script) → Supabase PostgreSQL + supabase-js + Google OAuth.

## Files

| File | Purpose |
|---|---|
| `schema.sql` | PostgreSQL DDL — 7 tables + RLS policies + donate RPCs + triggers |
| `supabase.js` | Browser-side Supabase client — drop-in replacement for `apiFetchReal()` |
| `migrate_sheets.js` | Node.js script — reads Sheets API, upserts into Supabase |

## Setup Steps

### 1. Create Supabase Project
- Go to supabase.com → New Project
- Note the **Project URL** and **anon key**

### 2. Run Schema
- SQL Editor → paste `schema.sql` → Run
- This creates all 7 tables, indexes, RLS policies, triggers, and donate RPCs

### 3. Enable Google OAuth
- Supabase Dashboard → Authentication → Providers → Google
- Add your Google OAuth Client ID and Secret
- Set redirect URL in Google Console: `https://<project>.supabase.co/auth/v1/callback`

### 4. Configure Client
Edit `supabase.js`:
```js
const SUPABASE_URL      = 'https://xxx.supabase.co';
const SUPABASE_ANON_KEY = 'eyJ...';
```

### 5. Update index.html
Add before `app.js`:
```html
<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>
<script src="./supabase/supabase.js"></script>
```

### 6. Wire app.js
Replace `apiFetchReal` in app.js (1-line change):
```js
async function apiFetchReal({ action, query, params = {} }) {
  return DreamJarSupabase.api({ action, query, params });
}
```

### 7. Migrate Data
```bash
SUPABASE_URL=https://xxx.supabase.co \
SUPABASE_SERVICE_KEY=eyJ... \
GOOGLE_API_KEY=AIza... \
node supabase/migrate_sheets.js
```

## Architecture Changes

| Before (Apps Script) | After (Supabase) |
|---|---|
| Google Sheets (8 sheets) | PostgreSQL (7 tables) |
| doPost/doGet HTTP | supabase-js SDK direct |
| sync_meta sheet (dirty bits) | `updated_at` column + triggers |
| No auth | Google OAuth via Supabase Auth |
| No RLS | Row-level security per user |
| Server-side fee calc (GAS) | PostgreSQL `donate()` RPC |
| 2-5s latency per call | <200ms per query |

## Key Design Decisions

1. **sync_meta → trigger-based `updated_at`**: Instead of a separate sync_meta table, jars.updated_at is auto-touched by triggers on entries/donations. The `checkSync` query reads this directly.

2. **donate as RPC**: Fee calculation (server-side `Math.random() * 0.5`) must stay server-side to prevent client manipulation. Implemented as `donate()` and `donate_bulk()` PostgreSQL functions with `security definer`.

3. **RLS**: All tables have row-level security. Users can only see jars they're members of. The `current_user_id()` helper maps Supabase Auth UID to the app's `user_id`.

4. **camelCase → snake_case**: DB columns use snake_case. The client module maps between snake_case (DB) and camelCase (app.js) to keep app.js changes minimal.

5. **Backward compatibility**: `supabase.js` exposes `DreamJarSupabase.api()` with the same `{action, query, params}` interface as the old `apiFetchReal()`, making it a 1-line swap.
