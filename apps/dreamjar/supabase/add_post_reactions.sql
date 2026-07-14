-- DreamJar — Post Reactions Schema
-- CMPA-982: 게시글(post) 레벨 이모지 반응 — jar 주인만 추가/삭제 가능

-- ============================================================
-- 1. post_reactions (게시글 이모지 반응)
-- ============================================================
create table if not exists public.post_reactions (
  post_id     text not null references public.posts(post_id) on delete cascade,
  author_id   text not null,                              -- jar 주인 user_id
  emoji       text not null default '👍',
  created_at  timestamptz not null default now(),
  primary key (post_id, author_id, emoji)
);
create index if not exists idx_post_reactions_post on public.post_reactions(post_id);

-- ============================================================
-- 2. RLS (permissive — consistent with existing tables)
-- ============================================================
alter table public.post_reactions enable row level security;
create policy "post_reactions_allow_all" on public.post_reactions
  for all using (true) with check (true);
