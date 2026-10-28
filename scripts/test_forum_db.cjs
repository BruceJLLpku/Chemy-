let PGlite;try{({PGlite}=require(process.env.CHEMY_PGLITE_PATH||'@electric-sql/pglite'));}catch{({PGlite}=require('../../chemy-site/tmp/forum-db-test/package/dist/index.cjs'));}
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
(async()=>{
const db=new PGlite();await db.exec(`create role anon;create role authenticated;create schema auth;create schema storage;
create table auth.users(id uuid primary key,email text,email_confirmed_at timestamptz);
create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub',true),'')::uuid $$;
grant usage on schema auth,storage,public to anon,authenticated;grant execute on function auth.uid() to anon,authenticated;
create table storage.buckets(id text primary key,name text,public boolean,file_size_limit bigint,allowed_mime_types text[]);
create table storage.objects(id uuid default gen_random_uuid(),bucket_id text,name text);alter table storage.objects enable row level security;grant select,insert,delete on storage.objects to anon,authenticated;
create function storage.foldername(text) returns text[] language sql as $$ select string_to_array($1,'/') $$;
insert into auth.users values('00000000-0000-0000-0000-000000000001','admin@example.com',now()),('00000000-0000-0000-0000-000000000002','a@example.com',now()),('00000000-0000-0000-0000-000000000003','b@example.com',now()),('00000000-0000-0000-0000-000000000004','unverified@example.com',null);`);
await db.exec(fs.readFileSync(path.resolve(__dirname,'../supabase/002_forum.sql'),'utf8'));await db.exec(fs.readFileSync(path.resolve(__dirname,'../supabase/003_question_registry.sql'),'utf8'));
await db.exec(`insert into public.forum_profiles(user_id,display_name,is_admin,is_team) values('00000000-0000-0000-0000-000000000001','管理员',true,true);`);
const user=n=>'00000000-0000-0000-0000-'+String(n).padStart(12,'0');
async function as(n,role='authenticated'){await db.exec(`reset role;set role ${role};select set_config('request.jwt.claim.sub','${n?user(n):''}',false);`)}
async function action(action,payload){return (await db.query('select public.forum_action($1,$2::jsonb) as data',[action,JSON.stringify(payload)])).rows[0].data;}
async function deny(name,fn){await assert.rejects(fn);console.log('PASS',name)}
const question=(await db.query('select question_id from public.forum_questions limit 1')).rows[0].question_id;
await as(0,'anon');await deny('Anonymous cannot post',()=>action('new_thread',{}));assert.equal((await db.query('select * from public.forum_threads')).rows.length,0);
await as(4);await deny('Unverified cannot create profile',()=>action('set_name',{name:'未验证'}));
await as(2);await action('set_name',{name:'学习者甲'});await deny('User cannot forge team/admin columns',()=>db.exec(`update public.forum_profiles set is_team=true,is_admin=true where user_id='${user(2)}'`));await deny('User cannot self-certify through RPC',()=>action('set_team',{id:user(2),enabled:true}));
const t=(await action('new_thread',{question_id:question,kind:'question',title:'为什么这样计算？',body:'我的推导是 $x^2$。'})).id;
await deny('Unknown question rejected',()=>action('new_thread',{question_id:'not-a-question',kind:'chat',title:'无效题目',body:'测试'}));
await as(3);await action('set_name',{name:'学习者乙'});const r=(await action('new_reply',{thread_id:t,body:'可以从质量守恒开始。'})).id;await deny('Cannot edit another user post',()=>action('edit_thread',{id:t,title:'篡改',body:'篡改'}));await deny('Non-owner cannot accept',()=>action('accept',{thread_id:t,reply_id:r}));
await as(2);assert.equal((await db.query('select count(*)::int n from public.forum_notifications')).rows[0].n,1);await action('accept',{thread_id:t,reply_id:r});await action('edit_thread',{id:t,title:'为什么这样计算？更新',body:'补充推导'});
const before=(await db.query('select last_activity from public.forum_threads where id=$1',[t])).rows[0].last_activity;await action('edit_thread',{id:t,title:'为什么这样计算？再更新',body:'补充推导 2'});assert.deepEqual((await db.query('select last_activity from public.forum_threads where id=$1',[t])).rows[0].last_activity,before);console.log('PASS edit does not bump activity');
await as(3);assert.equal((await db.query('select count(*)::int n from public.forum_notifications')).rows[0].n,1);await action('read_notifications',{});assert.equal((await db.query('select count(*)::int n from public.forum_notifications where not is_read')).rows[0].n,0);await deny('Cannot read another account notifications',()=>db.exec(`update public.forum_notifications set is_read=false`));
const other=(await action('new_thread',{question_id:question,kind:'chat',title:'另一条交流',body:'测试'})).id;await deny('Cross-thread reply target rejected',()=>action('new_reply',{thread_id:other,reply_to:r,body:'错误引用'}));await deny('Cannot accept reply from another thread',()=>action('accept',{thread_id:other,reply_id:r}));
await as(1);await action('set_team',{id:user(3),enabled:true});await as(3);await deny('Certified team member has no moderation power',()=>action('hide_thread',{id:t,enabled:true}));await deny('Cannot attach another user path',()=>action('new_reply',{thread_id:t,body:'图片',images:[user(2)+'/test.png']}));
await as(1);await action('lock_thread',{id:t,enabled:true});await as(3);await deny('Closed thread rejects reply',()=>action('new_reply',{thread_id:t,body:'不能发表'}));await as(1);await action('lock_thread',{id:t,enabled:false});await action('set_ban',{id:user(3),enabled:true});await as(3);await deny('Banned user cannot reply',()=>action('new_reply',{thread_id:t,body:'不能发表'}));await as(1);await action('set_ban',{id:user(3),enabled:false});await action('hide_reply',{id:r,enabled:true});
await as(0,'anon');assert.equal((await db.query('select * from public.forum_replies where id=$1',[r])).rows.length,0);assert.equal((await db.query('select accepted_reply from public.forum_threads where id=$1',[t])).rows[0].accepted_reply,null);console.log('PASS hidden reply unreadable and unaccepted');
await as(1);await action('hide_reply',{id:r,enabled:false});await action('hide_thread',{id:t,enabled:true});await as(0,'anon');assert.equal((await db.query('select * from public.forum_threads where id=$1',[t])).rows.length,0);assert.equal((await db.query('select * from public.forum_replies where thread_id=$1',[t])).rows.length,0);console.log('PASS hidden thread and replies unreadable anonymously');
await as(1);await action('hide_thread',{id:t,enabled:false});await as(2);await action('delete_thread',{id:t});await as(0,'anon');assert.equal((await db.query('select body from public.forum_threads where id=$1',[t])).rows[0].body,'');assert.equal((await db.query('select count(*)::int n from public.forum_replies where thread_id=$1',[t])).rows[0].n,1);console.log('PASS deleted original leaves replies');
assert.equal((await db.query('select count(*)::int n from public.forum_recent')).rows[0].n,1);console.log('PASS recent page groups by question');
await db.close();console.log('PASS actual PostgreSQL RLS and forum mutation suite');
})().catch(e=>{console.error(e);process.exitCode=1});
