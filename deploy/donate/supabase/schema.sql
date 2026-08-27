-- donate — Supabase PostgreSQL Schema
-- CMPA-1358: 라이언 딸 심장수술 기부/위스키 판매 문의 페이지
-- 같은 CaskCode 인프라(odtivpszffoufyiufqwy) 재사용 — 새 테이블만 추가.

create extension if not exists "pgcrypto";

-- ============================================================
-- whisky_inquiries — 위스키 구매 문의 (익명 insert, 관리자만 열람)
-- ============================================================
create table if not exists public.whisky_inquiries (
  id                uuid primary key default gen_random_uuid(),
  whiskies          jsonb  not null default '[]'::jsonb,   -- [{name, qty}]
  amount            bigint not null default 0,             -- 총 입금 예정 금액(원)
  depositor_name    text   not null default '',            -- 입금자 이름
  shipping_address  text   not null default '',            -- 배송지 주소
  contact           text,                                  -- 연락처 (nullable)
  one_point_lesson  boolean not null default false,        -- 30만원 이상 자동 true
  status            text   not null default 'new',         -- new/contacted/paid/shipped
  created_at        timestamptz not null default now()
);

create index if not exists idx_whisky_inquiries_created on public.whisky_inquiries(created_at desc);

-- ============================================================
-- RLS — 익명(anon) insert 허용, select 은 관리자(service_role)만
-- 개인정보(입금자명·배송지·연락처)를 anon 이 조회하지 못하게 한다.
-- ============================================================
alter table public.whisky_inquiries enable row level security;

-- anon/authenticated 는 insert 만 가능. (select 정책이 없으므로 조회 불가)
drop policy if exists whisky_inquiries_insert_anon on public.whisky_inquiries;
create policy whisky_inquiries_insert_anon
  on public.whisky_inquiries
  for insert
  to anon, authenticated
  with check (
    -- 최소한의 형식 방어: 금액 음수 금지, 위스키 목록은 배열
    amount >= 0
    and jsonb_typeof(whiskies) = 'array'
  );

-- select/update/delete 정책은 두지 않는다 → anon/authenticated 는 조회·수정 불가.
-- service_role 은 RLS 를 우회하므로 관리자 열람은 서버 키로만 가능.
