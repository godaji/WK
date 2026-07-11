-- CMPA-893 / CMPA-927: Fix RLS for anon access
-- Problem: RLS policies require auth.uid() but DreamJar uses its own userId (localStorage)
--          without Supabase Auth login. searchJars() returns 0 results because
--          jars_select policy filters out jars the user doesn't own/belong to.
-- Fix: Replace auth-based policies with permissive policies for anon key access.
--       App-level userId provides logical isolation (same as Code.gs era).

-- 1. Drop all existing restrictive policies
-- (covers both reset_db.sql auth-based policies and any prior allow_all)
drop policy if exists "users_select_own" on public.users;
drop policy if exists "users_update_own" on public.users;
drop policy if exists "users_insert_own" on public.users;
drop policy if exists "users_insert" on public.users;
drop policy if exists "allow_all" on public.users;
drop policy if exists "jars_select" on public.jars;
drop policy if exists "jars_insert" on public.jars;
drop policy if exists "jars_update" on public.jars;
drop policy if exists "allow_all" on public.jars;
drop policy if exists "jar_members_select" on public.jar_members;
drop policy if exists "jar_members_insert" on public.jar_members;
drop policy if exists "jar_members_update" on public.jar_members;
drop policy if exists "allow_all" on public.jar_members;
drop policy if exists "entries_select" on public.entries;
drop policy if exists "entries_insert" on public.entries;
drop policy if exists "entries_delete" on public.entries;
drop policy if exists "allow_all" on public.entries;
drop policy if exists "donation_out_select" on public.donation_out;
drop policy if exists "donation_out_insert" on public.donation_out;
drop policy if exists "allow_all" on public.donation_out;
drop policy if exists "donation_in_select" on public.donation_in;
drop policy if exists "donation_in_insert" on public.donation_in;
drop policy if exists "allow_all" on public.donation_in;
drop policy if exists "controls_select" on public.controls;
drop policy if exists "controls_insert" on public.controls;
drop policy if exists "controls_update" on public.controls;
drop policy if exists "controls_delete" on public.controls;
drop policy if exists "allow_all" on public.controls;

-- 2. Create permissive policies (anon + authenticated can read/write)
-- Same security level as original Code.gs (no auth, open endpoints)
create policy "allow_all" on public.users     for all using (true) with check (true);
create policy "allow_all" on public.jars      for all using (true) with check (true);
create policy "allow_all" on public.jar_members for all using (true) with check (true);
create policy "allow_all" on public.entries   for all using (true) with check (true);
create policy "allow_all" on public.donation_out for all using (true) with check (true);
create policy "allow_all" on public.donation_in  for all using (true) with check (true);
create policy "allow_all" on public.controls  for all using (true) with check (true);
