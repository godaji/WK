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
-- 3. Permissive RLS policies (CMPA-927)
-- ============================================================
-- DreamJar uses localStorage userId, not Supabase Auth (auth.uid()).
-- Auth-based RLS blocked searchJars() — users couldn't find jars to join.
-- Use permissive policies; app-level userId provides logical isolation.

create policy "allow_all" on public.users     for all using (true) with check (true);
create policy "allow_all" on public.jars      for all using (true) with check (true);
create policy "allow_all" on public.jar_members for all using (true) with check (true);
create policy "allow_all" on public.entries   for all using (true) with check (true);
create policy "allow_all" on public.donation_out for all using (true) with check (true);
create policy "allow_all" on public.donation_in  for all using (true) with check (true);
create policy "allow_all" on public.controls  for all using (true) with check (true);

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
  v_email := p_user_id || '@dreamjar.io';
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
