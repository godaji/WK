#!/bin/bash
# DreamJar Auth System Tests (CMPA-913)
# Tests login, JWT, RLS, and API access via curl.
# Usage: bash apps/dreamjar/supabase/test_auth.sh

set -euo pipefail

SUPABASE_URL="https://odtivpszffoufyiufqwy.supabase.co"
ANON_KEY="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Im9kdGl2cHN6ZmZvdWZ5aXVmcXd5Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODM2ODkzMTYsImV4cCI6MjA5OTI2NTMxNn0.XrXsMLtRCUbAJvFdWz_JMZ3VwFWwGBsP2YqQ0NO7m7I"

PASS=0
FAIL=0
SKIP=0

pass() { echo "  ✅ PASS: $1"; PASS=$((PASS+1)); }
fail() { echo "  ❌ FAIL: $1"; FAIL=$((FAIL+1)); }
skip() { echo "  ⏭️ SKIP: $1"; SKIP=$((SKIP+1)); }

echo "═══════════════════════════════════════════════════"
echo " DreamJar Auth Tests (CMPA-913)"
echo "═══════════════════════════════════════════════════"
echo ""

# ─── Test 1: Login with correct credentials ──────────────
echo "▶ Test 1: Login with correct credentials (shhong / star)"
LOGIN_RESP=$(curl -s -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"shhong@dreamjar.app","password":"star"}')

ACCESS_TOKEN=$(echo "$LOGIN_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null || echo "")
LOGIN_ERROR=$(echo "$LOGIN_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('error','') or d.get('msg','') or d.get('error_description',''))" 2>/dev/null || echo "")

if [ -n "$ACCESS_TOKEN" ] && [ "$ACCESS_TOKEN" != "" ]; then
  pass "Login succeeded — got access_token"
else
  fail "Login failed — $LOGIN_ERROR"
  echo "    Response: $(echo "$LOGIN_RESP" | head -c 300)"
fi

# ─── Test 2: Login with wrong password ───────────────────
echo ""
echo "▶ Test 2: Login with wrong password (shhong / wrongpass)"
BAD_RESP=$(curl -s -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"shhong@dreamjar.app","password":"wrongpass"}')

BAD_TOKEN=$(echo "$BAD_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null || echo "")
BAD_ERROR=$(echo "$BAD_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('error_description','') or d.get('msg','') or d.get('error',''))" 2>/dev/null || echo "")

if [ -z "$BAD_TOKEN" ] || [ "$BAD_TOKEN" = "" ]; then
  pass "Wrong password rejected — $BAD_ERROR"
else
  fail "Wrong password should have been rejected but got a token!"
fi

# ─── Test 3: Login with non-existent user ────────────────
echo ""
echo "▶ Test 3: Login with non-existent user"
NOUSER_RESP=$(curl -s -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"nonexistent@dreamjar.app","password":"whatever"}')

NOUSER_TOKEN=$(echo "$NOUSER_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('access_token',''))" 2>/dev/null || echo "")

if [ -z "$NOUSER_TOKEN" ] || [ "$NOUSER_TOKEN" = "" ]; then
  pass "Non-existent user rejected"
else
  fail "Non-existent user should have been rejected!"
fi

# ─── Test 4: Authenticated API — read users table ────────
echo ""
echo "▶ Test 4: Authenticated API — read own user row"
if [ -n "$ACCESS_TOKEN" ] && [ "$ACCESS_TOKEN" != "" ]; then
  USERS_RESP=$(curl -s "$SUPABASE_URL/rest/v1/users?select=user_id,name,auth_uid" \
    -H "apikey: $ANON_KEY" \
    -H "Authorization: Bearer $ACCESS_TOKEN")

  USER_COUNT=$(echo "$USERS_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 'error')" 2>/dev/null || echo "error")
  USER_ID=$(echo "$USERS_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d[0].get('user_id','') if isinstance(d,list) and len(d)>0 else '')" 2>/dev/null || echo "")

  if [ "$USER_COUNT" = "1" ] && [ "$USER_ID" = "shhong" ]; then
    pass "RLS works — can only see own user row (user_id=$USER_ID)"
  elif [ "$USER_COUNT" = "error" ]; then
    fail "API returned error: $(echo "$USERS_RESP" | head -c 200)"
  else
    fail "Expected 1 row (shhong), got $USER_COUNT rows. user_id=$USER_ID"
    echo "    Response: $(echo "$USERS_RESP" | head -c 300)"
  fi
else
  skip "Skipping (no access token from Test 1)"
fi

# ─── Test 5: Unauthenticated API — should be blocked ─────
echo ""
echo "▶ Test 5: Unauthenticated API — users table (anon, no JWT)"
ANON_RESP=$(curl -s "$SUPABASE_URL/rest/v1/users?select=user_id" \
  -H "apikey: $ANON_KEY")

ANON_COUNT=$(echo "$ANON_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d) if isinstance(d,list) else 'error')" 2>/dev/null || echo "error")

if [ "$ANON_COUNT" = "0" ]; then
  pass "Unauthenticated access returns 0 rows (RLS blocks anon)"
elif [ "$ANON_COUNT" = "error" ]; then
  # Could be a 401 error, which is also fine
  pass "Unauthenticated access blocked (error response)"
else
  fail "Unauthenticated access returned $ANON_COUNT rows — RLS may not be working!"
fi

# ─── Test 6: JWT contains correct user metadata ──────────
echo ""
echo "▶ Test 6: JWT user metadata"
if [ -n "$ACCESS_TOKEN" ] && [ "$ACCESS_TOKEN" != "" ]; then
  JWT_EMAIL=$(echo "$LOGIN_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('user',{}).get('email',''))" 2>/dev/null || echo "")
  JWT_UID=$(echo "$LOGIN_RESP" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d.get('user',{}).get('id',''))" 2>/dev/null || echo "")

  if [ "$JWT_EMAIL" = "shhong@dreamjar.app" ]; then
    pass "JWT email = shhong@dreamjar.app"
  else
    fail "JWT email = '$JWT_EMAIL', expected 'shhong@dreamjar.app'"
  fi

  if [ -n "$JWT_UID" ]; then
    pass "JWT user.id present ($JWT_UID)"
  else
    fail "JWT user.id missing"
  fi
else
  skip "Skipping (no access token)"
fi

# ─── Summary ─────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo " Results: $PASS passed, $FAIL failed, $SKIP skipped"
echo "═══════════════════════════════════════════════════"

exit $FAIL
