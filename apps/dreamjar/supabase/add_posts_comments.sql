-- DreamJar — Posts & Comments Schema
-- CMPA-933: Jar에 게시글(posts) + 댓글(comments) 기능 추가
-- 멤버는 바로 글/댓글 작성, 외부 방문자는 닉네임 입력 후 글/응원 가능

-- ============================================================
-- 1. posts (게시글)
-- ============================================================
create table if not exists public.posts (
  post_id     text primary key default ('post_' || extract(epoch from now())::bigint || '_' || floor(random()*1e6)::int),
  jar_id      text not null references public.jars(jar_id),
  author_id   text,                                   -- null = 외부 방문자 (guest)
  guest_name  text not null default '',                -- 외부 방문자 닉네임
  content     text not null default '',
  created_at  timestamptz not null default now()
);
create index if not exists idx_posts_jar on public.posts(jar_id);

-- ============================================================
-- 2. comments (댓글)
-- ============================================================
create table if not exists public.comments (
  comment_id  text primary key default ('cmt_' || extract(epoch from now())::bigint || '_' || floor(random()*1e6)::int),
  post_id     text not null references public.posts(post_id) on delete cascade,
  jar_id      text not null references public.jars(jar_id),
  author_id   text,                                   -- null = 외부 방문자
  guest_name  text not null default '',
  content     text not null default '',
  created_at  timestamptz not null default now()
);
create index if not exists idx_comments_post on public.comments(post_id);
create index if not exists idx_comments_jar  on public.comments(jar_id);

-- ============================================================
-- 3. cheers (응원 — 외부 방문자 + 멤버 가능)
-- ============================================================
create table if not exists public.cheers (
  cheer_id    text primary key default ('cheer_' || extract(epoch from now())::bigint || '_' || floor(random()*1e6)::int),
  jar_id      text not null references public.jars(jar_id),
  author_id   text,
  guest_name  text not null default '',
  emoji       text not null default '👏',
  created_at  timestamptz not null default now()
);
create index if not exists idx_cheers_jar on public.cheers(jar_id);

-- ============================================================
-- 4. RLS (permissive — consistent with existing tables, CMPA-927)
-- ============================================================
alter table public.posts    enable row level security;
alter table public.comments enable row level security;
alter table public.cheers   enable row level security;

create policy "posts_allow_all"    on public.posts    for all using (true) with check (true);
create policy "comments_allow_all" on public.comments for all using (true) with check (true);
create policy "cheers_allow_all"   on public.cheers   for all using (true) with check (true);

-- ============================================================
-- 5. Touch jar updated_at when posts/comments/cheers change
-- ============================================================
create or replace function public.touch_jar_on_post()
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

create trigger trg_posts_touch_jar
  after insert or update or delete on public.posts
  for each row execute function public.touch_jar_on_post();

create trigger trg_comments_touch_jar
  after insert or update or delete on public.comments
  for each row execute function public.touch_jar_on_post();

create trigger trg_cheers_touch_jar
  after insert or update or delete on public.cheers
  for each row execute function public.touch_jar_on_post();
