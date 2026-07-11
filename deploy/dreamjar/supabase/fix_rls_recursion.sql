-- DreamJar — Fix RLS recursion issue (CMPA-913)
-- The jar_members_select policy had a self-referential subquery causing
-- "Database error querying schema" on Supabase Auth login.
-- This script drops the broken policies and creates fixed ones.
-- Run in Supabase SQL Editor.

-- ============================================================
-- 1. Drop ALL existing RLS policies on public tables (clean slate)
-- ============================================================
do $$
declare
  r record;
begin
  for r in (
    select policyname, tablename
    from pg_policies
    where schemaname = 'public'
  ) loop
    execute format('drop policy if exists %I on public.%I', r.policyname, r.tablename);
  end loop;
end $$;

-- ============================================================
-- 2. Helper: security definer function to get my jar_ids
--    Bypasses RLS to avoid self-referential recursion
-- ============================================================
create or replace function public.my_user_id()
returns text as $$
  select user_id from public.users where auth_uid = auth.uid() limit 1;
$$ language sql security definer stable;

create or replace function public.my_jar_ids()
returns setof text as $$
  select jar_id from public.jar_members where user_id = public.my_user_id();
$$ language sql security definer stable;

-- ============================================================
-- 3. Create fixed RLS policies using helper functions
-- ============================================================

-- users: own row only
create policy "users_select_own" on public.users
  for select using (auth_uid = auth.uid());
create policy "users_update_own" on public.users
  for update using (auth_uid = auth.uid());
create policy "users_insert_own" on public.users
  for insert with check (auth_uid = auth.uid());

-- jars: owner or member
create policy "jars_select" on public.jars
  for select using (
    owner_id = public.my_user_id()
    or jar_id in (select public.my_jar_ids())
  );
create policy "jars_insert" on public.jars
  for insert with check (owner_id = public.my_user_id());
create policy "jars_update" on public.jars
  for update using (
    owner_id = public.my_user_id()
    or jar_id in (select public.my_jar_ids())
  );

-- jar_members: I'm the member OR I own the jar (no self-ref!)
create policy "jar_members_select" on public.jar_members
  for select using (
    user_id = public.my_user_id()
    or jar_id in (select jar_id from public.jars where owner_id = public.my_user_id())
  );
create policy "jar_members_insert" on public.jar_members
  for insert with check (
    user_id = public.my_user_id()
    or jar_id in (select jar_id from public.jars where owner_id = public.my_user_id())
  );
create policy "jar_members_update" on public.jar_members
  for update using (
    user_id = public.my_user_id()
    or jar_id in (select jar_id from public.jars where owner_id = public.my_user_id())
  );

-- entries: my jars
create policy "entries_select" on public.entries
  for select using (jar_id in (select public.my_jar_ids()));
create policy "entries_insert" on public.entries
  for insert with check (user_id = public.my_user_id());
create policy "entries_delete" on public.entries
  for delete using (user_id = public.my_user_id());

-- donation_out: my jars
create policy "donation_out_select" on public.donation_out
  for select using (
    from_jar_id in (select public.my_jar_ids())
    or to_jar_id in (select public.my_jar_ids())
  );

-- donation_in: my jars
create policy "donation_in_select" on public.donation_in
  for select using (
    to_jar_id in (select public.my_jar_ids())
    or from_jar_id in (select public.my_jar_ids())
  );

-- controls: admin for all authenticated; custom by owner
create policy "controls_select" on public.controls
  for select using (
    owner_id = 'admin'
    or owner_id = public.my_user_id()
  );
create policy "controls_insert" on public.controls
  for insert with check (owner_id = public.my_user_id());
create policy "controls_update" on public.controls
  for update using (owner_id = public.my_user_id());
create policy "controls_delete" on public.controls
  for delete using (owner_id = public.my_user_id());
