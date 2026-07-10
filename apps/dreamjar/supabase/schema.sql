-- DreamJar — Supabase PostgreSQL Schema
-- Migrated from Google Sheets (Code.gs v5.0-cmpa891, 8 sheets)
-- CMPA-893 Phase 1

-- ============================================================
-- 0. Extensions
-- ============================================================
create extension if not exists "uuid-ossp";

-- ============================================================
-- 1. users  (was: users sheet)
-- ============================================================
create table public.users (
  user_id   text primary key,                    -- e.g. 'hong-gildong-01'
  name      text not null default '',
  email     text not null default '',
  auth_uid  uuid unique references auth.users(id) on delete set null,  -- Supabase Auth FK
  created_at timestamptz not null default now()
);

-- ============================================================
-- 2. jars  (was: jars sheet)
-- ============================================================
create table public.jars (
  jar_id      text primary key default ('jar_' || extract(epoch from now())::bigint || '_' || floor(random()*1e6)::int),
  name        text not null default '',
  description text not null default '',
  owner_id    text not null references public.users(user_id),
  goal_amount bigint not null default 0,
  control_id  text not null default '',
  created_at  timestamptz not null default now(),
  archived    boolean not null default false,
  archived_at timestamptz
);
create index idx_jars_owner on public.jars(owner_id);

-- ============================================================
-- 3. jar_members  (was: jar_members sheet)
-- ============================================================
create table public.jar_members (
  member_id  text primary key default ('m_' || extract(epoch from now())::bigint || '_' || floor(random()*1e6)::int),
  jar_id     text not null references public.jars(jar_id),
  user_id    text not null references public.users(user_id),
  role       text not null default 'member' check (role in ('owner','member')),
  control_id text not null default '',
  joined_at  timestamptz not null default now(),
  unique (jar_id, user_id)
);
create index idx_jar_members_user on public.jar_members(user_id);
create index idx_jar_members_jar  on public.jar_members(jar_id);

-- ============================================================
-- 4. entries  (was: entries sheet)
-- ============================================================
create table public.entries (
  entry_id   text primary key default ('ent_' || extract(epoch from now())::bigint || '_' || floor(random()*1e6)::int),
  jar_id     text not null references public.jars(jar_id),
  user_id    text not null references public.users(user_id),
  amount     bigint not null default 0,
  note       text not null default '',
  created_at timestamptz not null default now()
);
create index idx_entries_jar  on public.entries(jar_id);
create index idx_entries_user on public.entries(user_id);

-- ============================================================
-- 5. donation_out  (was: donation_out sheet)
-- ============================================================
create table public.donation_out (
  donation_id    text primary key default ('don_' || extract(epoch from now())::bigint || '_' || floor(random()*1e6)::int),
  from_jar_id    text not null references public.jars(jar_id),
  to_jar_id      text not null references public.jars(jar_id),
  request_amount bigint not null default 0,
  fee_rate       double precision not null default 0,
  fee_amount     bigint not null default 0,
  net_amount     bigint not null default 0,
  source_notes   text not null default '',
  created_at     timestamptz not null default now()
);
create index idx_donation_out_from on public.donation_out(from_jar_id);

-- ============================================================
-- 6. donation_in  (was: donation_in sheet)
-- ============================================================
create table public.donation_in (
  donation_id    text primary key,
  to_jar_id      text not null references public.jars(jar_id),
  from_jar_id    text not null references public.jars(jar_id),
  request_amount bigint not null default 0,
  fee_rate       double precision not null default 0,
  fee_amount     bigint not null default 0,
  net_amount     bigint not null default 0,
  source_notes   text not null default '',
  created_at     timestamptz not null default now()
);
create index idx_donation_in_to on public.donation_in(to_jar_id);

-- ============================================================
-- 7. controls  (was: controls sheet)
-- ============================================================
create table public.controls (
  control_id  text primary key default ('ctrl_' || extract(epoch from now())::bigint || '_' || floor(random()*1e6)::int),
  name        text not null default '',
  description text not null default '',
  owner_id    text not null default '',
  type        text not null default '',
  created_at  timestamptz not null default now()
);

-- ============================================================
-- 8. sync_meta  (was: sync_meta sheet — jar dirty bits)
--    Replaced by trigger-based updated_at on jars table.
--    No separate table needed — see trigger below.
-- ============================================================
alter table public.jars add column if not exists updated_at timestamptz not null default now();

create or replace function public.touch_jar_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger trg_jars_updated_at
  before update on public.jars
  for each row execute function public.touch_jar_updated_at();

-- Also auto-touch parent jar when entries/donations change
create or replace function public.touch_jar_on_child()
returns trigger as $$
begin
  if tg_op = 'DELETE' then
    update public.jars set updated_at = now() where jar_id = old.jar_id;
    return old;
  end if;
  update public.jars set updated_at = now() where jar_id = new.jar_id;
  return new;
end;
$$ language plpgsql;

create trigger trg_entries_touch_jar
  after insert or update or delete on public.entries
  for each row execute function public.touch_jar_on_child();

-- Touch both from/to jars on donation
create or replace function public.touch_jars_on_donation()
returns trigger as $$
begin
  update public.jars set updated_at = now()
    where jar_id in (new.from_jar_id, new.to_jar_id);
  return new;
end;
$$ language plpgsql;

create trigger trg_donation_out_touch_jars
  after insert on public.donation_out
  for each row execute function public.touch_jars_on_donation();

create trigger trg_donation_in_touch_jars
  after insert on public.donation_in
  for each row execute function public.touch_jars_on_donation();

-- ============================================================
-- 9. Row-Level Security (RLS)
-- ============================================================
alter table public.users       enable row level security;
alter table public.jars        enable row level security;
alter table public.jar_members enable row level security;
alter table public.entries     enable row level security;
alter table public.donation_out enable row level security;
alter table public.donation_in  enable row level security;
alter table public.controls    enable row level security;

-- Helper: get the user_id for the current auth user
create or replace function public.current_user_id()
returns text as $$
  select user_id from public.users where auth_uid = auth.uid() limit 1;
$$ language sql stable security definer;

-- users: can read self, insert self
create policy "users_select_own" on public.users for select using (auth_uid = auth.uid());
create policy "users_insert"     on public.users for insert with check (auth_uid = auth.uid());

-- jars: readable by members, writable by owner
create policy "jars_select" on public.jars for select using (
  jar_id in (select jar_id from public.jar_members where user_id = public.current_user_id())
  or owner_id = public.current_user_id()
);
create policy "jars_insert" on public.jars for insert with check (
  owner_id = public.current_user_id()
);
create policy "jars_update" on public.jars for update using (
  owner_id = public.current_user_id()
);

-- jar_members: readable by same-jar members, insertable by self
create policy "jar_members_select" on public.jar_members for select using (
  jar_id in (select jar_id from public.jar_members jm2 where jm2.user_id = public.current_user_id())
);
create policy "jar_members_insert" on public.jar_members for insert with check (
  user_id = public.current_user_id()
);
create policy "jar_members_update" on public.jar_members for update using (
  user_id = public.current_user_id()
);

-- entries: readable by jar members, insertable by self
create policy "entries_select" on public.entries for select using (
  jar_id in (select jar_id from public.jar_members where user_id = public.current_user_id())
);
create policy "entries_insert" on public.entries for insert with check (
  user_id = public.current_user_id()
);
create policy "entries_delete" on public.entries for delete using (
  user_id = public.current_user_id()
);

-- donation_out: readable by from-jar members
create policy "donation_out_select" on public.donation_out for select using (
  from_jar_id in (select jar_id from public.jar_members where user_id = public.current_user_id())
  or to_jar_id in (select jar_id from public.jar_members where user_id = public.current_user_id())
);
create policy "donation_out_insert" on public.donation_out for insert with check (
  from_jar_id in (select jar_id from public.jar_members where user_id = public.current_user_id())
);

-- donation_in: readable by to-jar members
create policy "donation_in_select" on public.donation_in for select using (
  to_jar_id in (select jar_id from public.jar_members where user_id = public.current_user_id())
  or from_jar_id in (select jar_id from public.jar_members where user_id = public.current_user_id())
);
create policy "donation_in_insert" on public.donation_in for insert with check (
  to_jar_id in (select jar_id from public.jar_members where user_id = public.current_user_id())
  or from_jar_id in (select jar_id from public.jar_members where user_id = public.current_user_id())
);

-- controls: public read, admin insert
create policy "controls_select" on public.controls for select using (true);
create policy "controls_insert" on public.controls for insert with check (
  owner_id = 'admin'
);

-- ============================================================
-- 10. Donate RPC (server-side random fee — replaces Code.gs handleDonate)
-- ============================================================
create or replace function public.donate(
  p_from_jar_id text,
  p_to_jar_id   text,
  p_amount      bigint
)
returns jsonb as $$
declare
  v_donation_id text;
  v_fee_rate    double precision;
  v_fee_amount  bigint;
  v_net_amount  bigint;
begin
  v_donation_id := 'don_' || extract(epoch from now())::bigint || '_' || floor(random()*1e6)::int;
  v_fee_rate    := random() * 0.5;
  v_fee_amount  := round(p_amount * v_fee_rate);
  v_net_amount  := p_amount - v_fee_amount;

  insert into public.donation_out (donation_id, from_jar_id, to_jar_id, request_amount, fee_rate, fee_amount, net_amount)
    values (v_donation_id, p_from_jar_id, p_to_jar_id, p_amount, v_fee_rate, v_fee_amount, v_net_amount);

  insert into public.donation_in (donation_id, to_jar_id, from_jar_id, request_amount, fee_rate, fee_amount, net_amount)
    values (v_donation_id, p_to_jar_id, p_from_jar_id, p_amount, v_fee_rate, v_fee_amount, v_net_amount);

  return jsonb_build_object(
    'donationId', v_donation_id,
    'feeRate',    v_fee_rate,
    'feeAmount',  v_fee_amount,
    'netAmount',  v_net_amount
  );
end;
$$ language plpgsql security definer;

-- ============================================================
-- 11. Donate Bulk RPC (replaces Code.gs handleDonateBulk)
-- ============================================================
create or replace function public.donate_bulk(
  p_from_jar_id text,
  p_to_jar_id   text,
  p_items       jsonb  -- [{amount, note}]
)
returns jsonb as $$
declare
  v_item        jsonb;
  v_donation_id text;
  v_fee_rate    double precision;
  v_fee_amount  bigint;
  v_net_amount  bigint;
  v_request_amt bigint;
  v_results     jsonb := '[]'::jsonb;
  v_total_req   bigint := 0;
  v_total_fee   bigint := 0;
  v_total_net   bigint := 0;
begin
  for v_item in select * from jsonb_array_elements(p_items)
  loop
    v_donation_id := 'don_' || extract(epoch from now())::bigint || '_' || floor(random()*1e6)::int;
    v_request_amt := (v_item->>'amount')::bigint;
    v_fee_rate    := random() * 0.5;
    v_fee_amount  := round(v_request_amt * v_fee_rate);
    v_net_amount  := v_request_amt - v_fee_amount;

    insert into public.donation_out (donation_id, from_jar_id, to_jar_id, request_amount, fee_rate, fee_amount, net_amount, source_notes)
      values (v_donation_id, p_from_jar_id, p_to_jar_id, v_request_amt, v_fee_rate, v_fee_amount, v_net_amount, coalesce(v_item->>'note',''));

    insert into public.donation_in (donation_id, to_jar_id, from_jar_id, request_amount, fee_rate, fee_amount, net_amount, source_notes)
      values (v_donation_id, p_to_jar_id, p_from_jar_id, v_request_amt, v_fee_rate, v_fee_amount, v_net_amount, coalesce(v_item->>'note',''));

    v_total_req := v_total_req + v_request_amt;
    v_total_fee := v_total_fee + v_fee_amount;
    v_total_net := v_total_net + v_net_amount;

    v_results := v_results || jsonb_build_object(
      'donationId', v_donation_id,
      'note',       coalesce(v_item->>'note',''),
      'amount',     v_request_amt,
      'feeRate',    v_fee_rate,
      'feeAmount',  v_fee_amount,
      'netAmount',  v_net_amount
    );
  end loop;

  return jsonb_build_object(
    'items',        v_results,
    'totalRequest', v_total_req,
    'totalFee',     v_total_fee,
    'totalNet',     v_total_net
  );
end;
$$ language plpgsql security definer;
