-- DreamJar — DB Reset & Auth Migration
-- CMPA-913: userId+password auth + RLS + full data wipe
-- Run this in Supabase SQL Editor (보드 실행)

-- ============================================================
-- 1. Drop existing RLS policies (allow_all → auth-based)
-- ============================================================
drop policy if exists "allow_all" on public.users;
drop policy if exists "allow_all" on public.jars;
drop policy if exists "allow_all" on public.jar_members;
drop policy if exists "allow_all" on public.entries;
drop policy if exists "allow_all" on public.donation_out;
drop policy if exists "allow_all" on public.donation_in;
drop policy if exists "allow_all" on public.controls;

-- ============================================================
-- 2. Truncate all data (보드 지시: 싹 밀기)
-- ============================================================
truncate public.donation_in  cascade;
truncate public.donation_out cascade;
truncate public.entries      cascade;
truncate public.jar_members  cascade;
truncate public.controls     cascade;
truncate public.jars         cascade;
truncate public.users        cascade;

-- ============================================================
-- 3. New auth-based RLS policies
-- ============================================================

-- Helper: get user_id from auth.uid()
-- Users table stores auth_uid (Supabase Auth UUID) mapped to user_id (app-level text ID)
-- All RLS policies resolve auth.uid() → user_id via the users table

-- users: can read/update own row only (matched by auth_uid)
create policy "users_select_own" on public.users
  for select using (auth_uid = auth.uid());
create policy "users_update_own" on public.users
  for update using (auth_uid = auth.uid());
create policy "users_insert_own" on public.users
  for insert with check (auth_uid = auth.uid());

-- jars: owner or member can access
create policy "jars_select" on public.jars
  for select using (
    owner_id in (select user_id from public.users where auth_uid = auth.uid())
    or jar_id in (select jar_id from public.jar_members where user_id in (select user_id from public.users where auth_uid = auth.uid()))
  );
create policy "jars_insert" on public.jars
  for insert with check (
    owner_id in (select user_id from public.users where auth_uid = auth.uid())
  );
create policy "jars_update" on public.jars
  for update using (
    owner_id in (select user_id from public.users where auth_uid = auth.uid())
    or jar_id in (select jar_id from public.jar_members where user_id in (select user_id from public.users where auth_uid = auth.uid()))
  );

-- jar_members: member of the jar can read; owner can insert/delete
create policy "jar_members_select" on public.jar_members
  for select using (
    jar_id in (
      select jar_id from public.jar_members jm
      where jm.user_id in (select user_id from public.users where auth_uid = auth.uid())
    )
    or jar_id in (
      select jar_id from public.jars where owner_id in (select user_id from public.users where auth_uid = auth.uid())
    )
  );
create policy "jar_members_insert" on public.jar_members
  for insert with check (
    user_id in (select user_id from public.users where auth_uid = auth.uid())
    or jar_id in (select jar_id from public.jars where owner_id in (select user_id from public.users where auth_uid = auth.uid()))
  );
create policy "jar_members_update" on public.jar_members
  for update using (
    user_id in (select user_id from public.users where auth_uid = auth.uid())
    or jar_id in (select jar_id from public.jars where owner_id in (select user_id from public.users where auth_uid = auth.uid()))
  );

-- entries: jar member can read/insert/delete
create policy "entries_select" on public.entries
  for select using (
    jar_id in (select jar_id from public.jar_members where user_id in (select user_id from public.users where auth_uid = auth.uid()))
    or jar_id in (select jar_id from public.jars where owner_id in (select user_id from public.users where auth_uid = auth.uid()))
  );
create policy "entries_insert" on public.entries
  for insert with check (
    user_id in (select user_id from public.users where auth_uid = auth.uid())
  );
create policy "entries_delete" on public.entries
  for delete using (
    user_id in (select user_id from public.users where auth_uid = auth.uid())
  );

-- donation_out: jar member can read; jar owner can insert
create policy "donation_out_select" on public.donation_out
  for select using (
    from_jar_id in (select jar_id from public.jar_members where user_id in (select user_id from public.users where auth_uid = auth.uid()))
    or from_jar_id in (select jar_id from public.jars where owner_id in (select user_id from public.users where auth_uid = auth.uid()))
    or to_jar_id in (select jar_id from public.jar_members where user_id in (select user_id from public.users where auth_uid = auth.uid()))
    or to_jar_id in (select jar_id from public.jars where owner_id in (select user_id from public.users where auth_uid = auth.uid()))
  );

-- donation_in: jar member can read
create policy "donation_in_select" on public.donation_in
  for select using (
    to_jar_id in (select jar_id from public.jar_members where user_id in (select user_id from public.users where auth_uid = auth.uid()))
    or to_jar_id in (select jar_id from public.jars where owner_id in (select user_id from public.users where auth_uid = auth.uid()))
    or from_jar_id in (select jar_id from public.jar_members where user_id in (select user_id from public.users where auth_uid = auth.uid()))
    or from_jar_id in (select jar_id from public.jars where owner_id in (select user_id from public.users where auth_uid = auth.uid()))
  );

-- controls: admin controls readable by all authenticated users; custom controls by owner
create policy "controls_select" on public.controls
  for select using (
    owner_id = 'admin'
    or owner_id in (select user_id from public.users where auth_uid = auth.uid())
  );
create policy "controls_insert" on public.controls
  for insert with check (
    owner_id in (select user_id from public.users where auth_uid = auth.uid())
  );
create policy "controls_update" on public.controls
  for update using (
    owner_id in (select user_id from public.users where auth_uid = auth.uid())
  );
create policy "controls_delete" on public.controls
  for delete using (
    owner_id in (select user_id from public.users where auth_uid = auth.uid())
  );

-- ============================================================
-- 4. Admin user creation helper function
-- ============================================================
-- Usage: select admin_create_user('hong-gildong-01', 'mypassword123');
-- This creates a Supabase Auth user + identity + public.users row in one call.
-- Must be run from Supabase SQL Editor (needs superuser/service_role access).
create or replace function public.admin_create_user(
  p_user_id  text,
  p_password text
)
returns jsonb as $$
declare
  v_email    text;
  v_auth_uid uuid;
begin
  v_email := p_user_id || '@dreamjar.local';
  v_auth_uid := gen_random_uuid();

  -- Insert into auth.users with all required fields
  insert into auth.users (
    instance_id, id, aud, role, email, encrypted_password,
    email_confirmed_at, created_at, updated_at,
    confirmation_token, recovery_token, email_change_token_new,
    raw_app_meta_data, raw_user_meta_data,
    is_super_admin, phone, phone_confirmed_at
  ) values (
    '00000000-0000-0000-0000-000000000000',
    v_auth_uid, 'authenticated', 'authenticated',
    v_email, crypt(p_password, gen_salt('bf')),
    now(), now(), now(),
    encode(gen_random_bytes(32), 'hex'), '', '',
    '{"provider":"email","providers":["email"]}'::jsonb,
    jsonb_build_object('user_id', p_user_id),
    false, null, null
  );

  -- Insert identity row (required for Supabase Auth login to work)
  insert into auth.identities (
    id, user_id, identity_data, provider, provider_id,
    last_sign_in_at, created_at, updated_at
  ) values (
    v_auth_uid, v_auth_uid,
    jsonb_build_object('sub', v_auth_uid::text, 'email', v_email, 'email_verified', true, 'phone_verified', false),
    'email', v_auth_uid::text,
    now(), now(), now()
  );

  -- Create public.users row
  insert into public.users (user_id, name, auth_uid, created_at)
  values (p_user_id, p_user_id, v_auth_uid, now())
  on conflict (user_id) do update set auth_uid = v_auth_uid;

  return jsonb_build_object(
    'userId',  p_user_id,
    'authUid', v_auth_uid,
    'email',   v_email
  );
end;
$$ language plpgsql security definer;

-- ============================================================
-- 5. Grant donate RPCs to authenticated role
-- ============================================================
-- The donate/donate_bulk functions are SECURITY DEFINER so they bypass RLS.
-- They already exist from schema.sql — no changes needed, just ensure
-- the authenticated role can call them:
grant execute on function public.donate(text, text, bigint) to authenticated;
grant execute on function public.donate_bulk(text, text, jsonb) to authenticated;
grant execute on function public.admin_create_user(text, text) to service_role;
