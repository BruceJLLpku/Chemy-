begin;
create table public.forum_profiles (
 user_id uuid primary key references auth.users(id) on delete cascade,
 display_name text not null check(length(btrim(display_name)) between 2 and 30),
 is_team boolean not null default false, is_admin boolean not null default false,
 created_at timestamptz not null default now()
);
create table public.forum_bans(user_id uuid primary key references auth.users(id) on delete cascade, created_at timestamptz not null default now());
create table public.forum_questions(question_id text primary key,topic text not null,title text not null,topic_number integer not null);
create table public.forum_threads(
 id uuid primary key default gen_random_uuid(), question_id text not null references public.forum_questions(question_id),
 author_id uuid not null references public.forum_profiles(user_id), kind text not null check(kind in ('question','chat')),
 title text not null check(length(btrim(title)) between 2 and 160),body text not null check(length(body)<=12000),
 images text[] not null default '{}' check(cardinality(images)<=3 and array_position(images,null) is null),
 created_at timestamptz not null default now(),edited_at timestamptz,last_activity timestamptz not null default now(),
 accepted_reply uuid,is_locked boolean not null default false,is_hidden boolean not null default false,is_deleted boolean not null default false
);
create table public.forum_replies(
 id uuid primary key default gen_random_uuid(),thread_id uuid not null references public.forum_threads(id),
 author_id uuid not null references public.forum_profiles(user_id),reply_to uuid references public.forum_replies(id),
 body text not null check(length(body)<=12000),images text[] not null default '{}' check(cardinality(images)<=3 and array_position(images,null) is null),
 created_at timestamptz not null default now(),edited_at timestamptz,is_hidden boolean not null default false,is_deleted boolean not null default false
);
alter table public.forum_threads add constraint forum_accepted_reply_fk foreign key(accepted_reply) references public.forum_replies(id);
create table public.forum_notifications(
 id uuid primary key default gen_random_uuid(),recipient uuid not null references auth.users(id) on delete cascade,
 actor uuid references public.forum_profiles(user_id),thread_id uuid not null references public.forum_threads(id),reply_id uuid references public.forum_replies(id),
 kind text not null check(kind in ('reply','direct_reply','accepted')),is_read boolean not null default false,created_at timestamptz not null default now()
);
create table public.forum_admin_log(id bigint generated always as identity primary key,actor uuid not null,action text not null,target uuid,payload jsonb,created_at timestamptz not null default now());
create index forum_threads_question on public.forum_threads(question_id,last_activity desc);
create index forum_threads_recent on public.forum_threads(last_activity desc);
create index forum_replies_thread on public.forum_replies(thread_id,created_at);
create index forum_notifications_owner on public.forum_notifications(recipient,is_read,created_at desc);
create function public.forum_is_admin() returns boolean language sql stable security definer set search_path='' as $$
 select exists(select 1 from public.forum_profiles where user_id=auth.uid() and is_admin)
$$;
create function public.forum_can_post() returns boolean language sql stable security definer set search_path='' as $$
 select exists(select 1 from auth.users where id=auth.uid() and email_confirmed_at is not null)
 and not exists(select 1 from public.forum_bans where user_id=auth.uid())
$$;
alter table public.forum_profiles enable row level security;
alter table public.forum_questions enable row level security;
alter table public.forum_threads enable row level security;
alter table public.forum_replies enable row level security;
alter table public.forum_notifications enable row level security;
alter table public.forum_bans enable row level security;
alter table public.forum_admin_log enable row level security;
revoke all on public.forum_profiles,public.forum_questions,public.forum_threads,public.forum_replies,public.forum_notifications,public.forum_bans,public.forum_admin_log from anon,authenticated;
grant select on public.forum_profiles,public.forum_questions,public.forum_threads,public.forum_replies to anon,authenticated;
grant select on public.forum_notifications,public.forum_bans,public.forum_admin_log to authenticated;
create policy forum_profiles_read on public.forum_profiles for select using(true);
create policy forum_questions_read on public.forum_questions for select using(true);
create policy forum_threads_read on public.forum_threads for select using(not is_hidden or public.forum_is_admin());
create policy forum_replies_read on public.forum_replies for select using((not is_hidden or public.forum_is_admin()) and exists(select 1 from public.forum_threads t where t.id=thread_id and (not t.is_hidden or public.forum_is_admin())));
create policy forum_notifications_read on public.forum_notifications for select using(recipient=auth.uid());
create policy forum_bans_read on public.forum_bans for select using(user_id=auth.uid() or public.forum_is_admin());
create policy forum_log_read on public.forum_admin_log for select using(public.forum_is_admin());

-- All mutations pass through this function. Client-provided role flags are ignored.
create function public.forum_action(action text,payload jsonb default '{}'::jsonb) returns jsonb
language plpgsql security definer set search_path='' as $$
declare
 me uuid:=auth.uid(); adm boolean:=public.forum_is_admin(); target uuid; tid uuid; rid uuid; parent uuid; owner uuid;
 t public.forum_threads; r public.forum_replies; text_body text; image_paths text[]; profile_name text; result uuid; item text;
begin
 if me is null then raise exception '请先登录'; end if;
 if payload->>'expected_user' is not null and payload->>'expected_user'<>me::text then raise exception '登录账户已变化，请重新操作';end if;
 if action='read_notifications' then
  update public.forum_notifications set is_read=true where recipient=me and (payload->>'id' is null or id=(payload->>'id')::uuid);
  return '{}'::jsonb;
 end if;
 if action in ('set_team','set_ban','hide_thread','hide_reply','lock_thread') then
  if not adm then raise exception '仅管理员可以执行此操作'; end if;
  target:=(payload->>'id')::uuid;
  if action='set_team' then
   update public.forum_profiles set is_team=(payload->>'enabled')::boolean where user_id=target;
   if not found then raise exception '该用户尚未设置论坛昵称'; end if;
  elsif action='set_ban' then
   if exists(select 1 from public.forum_profiles where user_id=target and is_admin) then raise exception '不能禁言管理员'; end if;
   if (payload->>'enabled')::boolean then insert into public.forum_bans(user_id) values(target) on conflict do nothing;
   else delete from public.forum_bans where user_id=target; end if;
  elsif action='hide_thread' then update public.forum_threads set is_hidden=(payload->>'enabled')::boolean where id=target;
  elsif action='hide_reply' then
   update public.forum_replies set is_hidden=(payload->>'enabled')::boolean where id=target;
   if (payload->>'enabled')::boolean then update public.forum_threads set accepted_reply=null where accepted_reply=target;end if;
  else update public.forum_threads set is_locked=(payload->>'enabled')::boolean where id=target; end if;
  insert into public.forum_admin_log(actor,action,target,payload) values(me,action,target,payload);
  return '{}'::jsonb;
 end if;
 if not public.forum_can_post() then raise exception '请先验证邮箱；被禁言的账户暂不能发言'; end if;
 if action='set_name' then
  profile_name:=btrim(payload->>'name');
  if profile_name is null or length(profile_name)<2 or length(profile_name)>30 then raise exception '昵称需为 2–30 个字'; end if;
  insert into public.forum_profiles(user_id,display_name) values(me,profile_name) on conflict(user_id) do update set display_name=excluded.display_name;
  return '{}'::jsonb;
 end if;
 if not exists(select 1 from public.forum_profiles where user_id=me) then raise exception '请先设置论坛昵称'; end if;
 if action='accept' then
  tid:=(payload->>'thread_id')::uuid;rid:=(payload->>'reply_id')::uuid;
  select * into t from public.forum_threads where id=tid for update;
  if not found or t.is_hidden or t.is_deleted or t.kind<>'question' or (t.author_id<>me and not adm) then raise exception '无权更改解决状态'; end if;
  if rid is not null and not exists(select 1 from public.forum_replies where id=rid and thread_id=tid and not is_hidden and not is_deleted) then raise exception '回复不可采纳'; end if;
  update public.forum_threads set accepted_reply=rid where id=tid;
  if rid is not null and rid is distinct from t.accepted_reply then
   select author_id into owner from public.forum_replies where id=rid;
   if owner<>me then insert into public.forum_notifications(recipient,actor,thread_id,reply_id,kind) values(owner,me,tid,rid,'accepted');end if;
  end if;
  return '{}'::jsonb;
 end if;
 if action in ('delete_thread','delete_reply') then
  target:=(payload->>'id')::uuid;
  if action='delete_thread' then
   update public.forum_threads set title='原帖已删除',body='',images='{}',is_deleted=true,accepted_reply=null,edited_at=now() where id=target and author_id=me;
  else
   update public.forum_replies set body='',images='{}',is_deleted=true,edited_at=now() where id=target and author_id=me;
   if found then update public.forum_threads set accepted_reply=null where accepted_reply=target;return '{}'::jsonb;end if;
  end if;
  if not found then raise exception '只能删除自己的发言';end if;
  return '{}'::jsonb;
 end if;
 if action not in ('new_thread','new_reply','edit_thread','edit_reply') then raise exception '未知操作'; end if;
 text_body:=btrim(coalesce(payload->>'body',''));
 select coalesce(array_agg(value),'{}') into image_paths from jsonb_array_elements_text(coalesce(payload->'images','[]'::jsonb));
 if (length(text_body)<1 and cardinality(image_paths)=0) or length(text_body)>12000 or cardinality(image_paths)>3 then raise exception '内容不能为空，文字最多 12000 字，图片最多 3 张';end if;
 foreach item in array image_paths loop
  if item not like me::text||'/%' or item like '%..%' or not exists(select 1 from storage.objects where bucket_id='forum-images' and name=item) then raise exception '图片无效或不属于当前用户';end if;
 end loop;
 -- Serialize posting per account to make rate limits effective under concurrent requests.
 perform pg_advisory_xact_lock(hashtext(me::text));
 if action in ('new_thread','new_reply') and (
  (select count(*) from public.forum_threads where author_id=me and created_at>now()-interval '1 minute')+
  (select count(*) from public.forum_replies where author_id=me and created_at>now()-interval '1 minute'))>=10 then raise exception '发言太快，请稍后再试'; end if;
 if action='new_thread' then
  if length(btrim(coalesce(payload->>'title','')))<2 then raise exception '请填写讨论标题';end if;
  insert into public.forum_threads(question_id,author_id,kind,title,body,images) values(payload->>'question_id',me,payload->>'kind',btrim(payload->>'title'),text_body,image_paths) returning id into result;
 elsif action='new_reply' then
  tid:=(payload->>'thread_id')::uuid;parent:=(payload->>'reply_to')::uuid;
  select * into t from public.forum_threads where id=tid for update;
  if not found or t.is_hidden or t.is_locked then raise exception '讨论已关闭或不可访问';end if;
  if parent is not null and not exists(select 1 from public.forum_replies where id=parent and thread_id=tid and not is_hidden and not is_deleted) then raise exception '被回复的内容不可访问';end if;
  insert into public.forum_replies(thread_id,author_id,reply_to,body,images) values(tid,me,parent,text_body,image_paths) returning id into result;
  update public.forum_threads set last_activity=now() where id=tid;
  if t.author_id<>me then insert into public.forum_notifications(recipient,actor,thread_id,reply_id,kind) values(t.author_id,me,tid,result,'reply');end if;
  if parent is not null then
   select author_id into owner from public.forum_replies where id=parent;
   if owner<>me and owner<>t.author_id then insert into public.forum_notifications(recipient,actor,thread_id,reply_id,kind) values(owner,me,tid,result,'direct_reply');end if;
  end if;
 elsif action='edit_thread' then
  update public.forum_threads set title=btrim(payload->>'title'),body=text_body,images=image_paths,edited_at=now() where id=(payload->>'id')::uuid and author_id=me and not is_deleted and not is_hidden and not is_locked returning id into result;
  if not found then raise exception '无法编辑这条讨论';end if;
 else
  update public.forum_replies rr set body=text_body,images=image_paths,edited_at=now() where rr.id=(payload->>'id')::uuid and rr.author_id=me and not rr.is_deleted and not rr.is_hidden and exists(select 1 from public.forum_threads tt where tt.id=rr.thread_id and not tt.is_hidden and not tt.is_locked) returning rr.id into result;
  if not found then raise exception '无法编辑这条回复';end if;
 end if;
 return jsonb_build_object('id',result);
end
$$;
revoke all on function public.forum_action(text,jsonb),public.forum_is_admin(),public.forum_can_post() from public;
grant execute on function public.forum_action(text,jsonb),public.forum_can_post() to authenticated;
grant execute on function public.forum_is_admin() to anon,authenticated;
-- One row per question, so pagination and the recent-activity order happen in PostgreSQL.
create view public.forum_recent with(security_invoker=true) as
 select q.question_id,q.topic,q.title,q.topic_number,
 (select count(*) from public.forum_threads t where t.question_id=q.question_id and not t.is_hidden) as thread_count,
 (select count(*) from public.forum_threads t where t.question_id=q.question_id and not t.is_hidden and not t.is_deleted and t.kind='question' and t.accepted_reply is null) as unresolved_count,
 (select greatest(max(t.last_activity),max(t.created_at)) from public.forum_threads t where t.question_id=q.question_id and not t.is_hidden) as last_activity,
 (select t.title from public.forum_threads t where t.question_id=q.question_id and not t.is_hidden order by t.last_activity desc limit 1) as latest_title,
 (select left(activity.body,180) from (select t.body,t.created_at from public.forum_threads t where t.question_id=q.question_id and not t.is_hidden and not t.is_deleted union all select r.body,r.created_at from public.forum_replies r join public.forum_threads t on t.id=r.thread_id where t.question_id=q.question_id and not t.is_hidden and not r.is_hidden and not r.is_deleted) activity order by activity.created_at desc limit 1) as latest_excerpt,
 exists(select 1 from public.forum_threads t join public.forum_profiles p on p.user_id=t.author_id where t.question_id=q.question_id and not t.is_hidden and not t.is_deleted and p.is_team
 union all select 1 from public.forum_replies r join public.forum_threads t on t.id=r.thread_id join public.forum_profiles p on p.user_id=r.author_id where t.question_id=q.question_id and not t.is_hidden and not r.is_hidden and not r.is_deleted and p.is_team) as team_participated
 from public.forum_questions q where exists(select 1 from public.forum_threads t where t.question_id=q.question_id and not t.is_hidden);
grant select on public.forum_recent to anon,authenticated;

-- Private images: reads require an attachment on a visible post; only an author/admin can preview unattached uploads.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types) values('forum-images','forum-images',false,5242880,array['image/png','image/jpeg','image/webp']) on conflict(id) do nothing;
create policy forum_image_upload on storage.objects for insert to authenticated with check(bucket_id='forum-images' and (storage.foldername(name))[1]=auth.uid()::text and public.forum_can_post());
create policy forum_image_read on storage.objects for select to anon,authenticated using(bucket_id='forum-images' and (
 (storage.foldername(name))[1]=auth.uid()::text or public.forum_is_admin() or
 exists(select 1 from public.forum_threads t where not t.is_hidden and not t.is_deleted and name=any(t.images)) or
 exists(select 1 from public.forum_replies r join public.forum_threads t on t.id=r.thread_id where not t.is_hidden and not r.is_hidden and not r.is_deleted and name=any(r.images))));
create policy forum_image_cleanup on storage.objects for delete to authenticated using(bucket_id='forum-images' and (storage.foldername(name))[1]=auth.uid()::text and not exists(select 1 from public.forum_threads t where name=any(t.images)) and not exists(select 1 from public.forum_replies r where name=any(r.images)));
commit;
