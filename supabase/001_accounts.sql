-- Run once in the Supabase SQL editor. No public access to personal data.
begin;
create table public.favorites (
 user_id uuid not null references auth.users(id) on delete cascade,
 question_id text not null check (length(question_id) between 1 and 200),
 created_at timestamptz not null default now(),
 primary key (user_id, question_id)
);
create table public.paper_history (
 id uuid primary key default gen_random_uuid(),
 user_id uuid not null references auth.users(id) on delete cascade,
 title text not null check (length(title) between 1 and 150),
 question_ids text[] not null check (cardinality(question_ids) between 1 and 2500 and array_position(question_ids, null) is null),
 created_at timestamptz not null default now()
);
create index paper_history_owner_date on public.paper_history(user_id, created_at desc);
alter table public.favorites enable row level security;
alter table public.paper_history enable row level security;
revoke all on public.favorites, public.paper_history from anon, authenticated;
grant select, insert, delete on public.favorites, public.paper_history to authenticated;
create policy favorites_read on public.favorites for select to authenticated using ((select auth.uid()) = user_id);
create policy favorites_insert on public.favorites for insert to authenticated with check ((select auth.uid()) = user_id);
create policy favorites_delete on public.favorites for delete to authenticated using ((select auth.uid()) = user_id);
create policy history_read on public.paper_history for select to authenticated using ((select auth.uid()) = user_id);
create policy history_insert on public.paper_history for insert to authenticated with check ((select auth.uid()) = user_id);
create policy history_delete on public.paper_history for delete to authenticated using ((select auth.uid()) = user_id);
commit;
