-- 위마카세 — 방명록 & 기부하기 Supabase 스키마 (CMPA-1340)
-- DreamJar와 동일한 Supabase 프로젝트 재사용:
--   URL  https://odtivpszffoufyiufqwy.supabase.co
--   anon key (프론트 노출 OK — RLS로 보호). service_role 키는 프론트 금지.
--
-- 실행: Supabase SQL Editor에서 직접 실행(WK 메모리: run-sql-migrations, 보드에게 안 시킴).
-- 방명록은 공개 쓰기(로그인 불필요)이므로 permissive RLS로 public insert/select 허용.
-- DreamJar apps/dreamjar/supabase/reset_db.sql의 "allow_all" RLS 패턴 참고.

-- ============================================================
-- 1. guestbook 테이블 (보드 지시 컬럼: 날짜·이름·내용·기부금)
-- ============================================================
create table if not exists public.guestbook (
  id         uuid primary key default gen_random_uuid(),
  name       text not null,                       -- 이름(사용자 입력)
  content    text not null,                       -- 내용(사용자 입력)
  donation   integer not null default 0,          -- 기부금(원, 사용자 입력)
  created_at timestamptz not null default now()   -- 날짜(자동)
);
create index if not exists idx_guestbook_created_at on public.guestbook(created_at desc);

-- ============================================================
-- 2. Row-Level Security — 공개 방명록(로그인 불필요)
-- ============================================================
alter table public.guestbook enable row level security;

-- 재실행 안전: 기존 정책 제거 후 재생성
drop policy if exists "guestbook_public_select" on public.guestbook;
drop policy if exists "guestbook_public_insert" on public.guestbook;

-- 누구나 읽기(방명록 목록 표시)
create policy "guestbook_public_select" on public.guestbook
  for select using (true);

-- 누구나 쓰기(방명록 작성) — update/delete는 정책 없음 = 차단
create policy "guestbook_public_insert" on public.guestbook
  for insert with check (true);
