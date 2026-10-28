/* Personal data is authorized by database RLS, never by UI filtering alone. */
(function () {
  'use strict';
  const dialog=document.createElement('dialog');dialog.id='account-dialog';dialog.className='account-dialog';
  dialog.innerHTML=`<div class="search-heading"><h2>我的题库</h2><button type="button" id="account-close" aria-label="关闭我的题库">×</button></div>
    <p id="account-status" role="status" aria-live="polite"></p>
    <form id="account-form"><label>邮箱<input name="email" type="email" autocomplete="email" required maxlength="254"></label><label>密码<input name="password" type="password" autocomplete="current-password" minlength="8" maxlength="128" required></label><p>首次使用请注册，并通过邮件验证邮箱。密码至少 8 位。</p><div class="account-actions"><button name="action" value="login">登录</button><button name="action" value="signup">注册账户</button><button name="action" value="reset" formnovalidate>忘记密码</button></div></form>
    <form id="account-recovery" hidden><label>设置新密码<input name="password" type="password" autocomplete="new-password" minlength="8" maxlength="128" required></label><button>保存新密码</button></form>
    <section id="account-library" hidden><p id="account-email"></p><div class="account-actions"><button id="account-refresh">刷新</button><button id="account-logout">退出登录</button><button id="account-save">保存当前选题</button></div><h3>我的收藏</h3><div id="account-favorites"></div><h3>组卷历史</h3><p>下载练习卷时自动保存，也可以手动保存。点击恢复后可再次下载题目与答案。</p><div id="account-history"></div><button id="account-more" hidden>加载更多历史</button></section>`;
  document.body.append(dialog);
  const el=id=>document.getElementById(id), message=t=>{el('account-status').textContent=t;};
  let client,user=null,favorites=new Set(),history=[],epoch=0,loading=false,offset=0;
  let setup;
  const fail=e=>message(e?.message||'连接失败，请稍后重试。');
  async function initialize(){
    const response=await fetch('account-config.json',{cache:'no-store'});
    if(!response.ok)throw Error('账户配置读取失败，请稍后重试。');
    const config=await response.json();
    if(!config.url||!config.publishableKey)throw Error('账户服务尚未启用，请联系站点管理员完成配置。');
    if(!/^https:\/\/[a-z0-9-]+\.supabase\.co\/?$/.test(config.url))throw Error('账户服务地址无效。');
    const {createClient}=await import('https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2.57.4/+esm');
    client=createClient(config.url,config.publishableKey);
    client.auth.onAuthStateChange((event,session)=>{
      const changed=user?.id!==session?.user?.id; user=session?.user||null;
      if(changed){epoch++;favorites=new Set();history=[];offset=0;paint();}
      showState();
      if(event==='PASSWORD_RECOVERY'){el('account-recovery').hidden=false;dialog.open||dialog.showModal();message('请设置新密码。');}
      if(user&&changed)setTimeout(()=>load().catch(fail),0);
    });
    const {data,error}=await client.auth.getSession();if(error)throw error;
    user=data.session?.user||null;showState();if(user)await load();else message('登录后，收藏和组卷历史会保存在你的账户中。');
  }
  function connect(){if(!setup)setup=initialize().catch(e=>{setup=null;throw e;});return setup;}
  function showState(){el('account-form').hidden=!!user;el('account-library').hidden=!user;el('account-email').textContent=user?.email||'';el('account-launch').textContent=user?'我的题库':'登录 / 我的题库';if(!user)el('account-recovery').hidden=true;}
  async function requireUser(){await connect();if(!user){if(!dialog.open)dialog.showModal();throw Error('请先登录，再保存到个人题库。');}return user.id;}
  function refreshButtons(){document.querySelectorAll('[data-favorite]').forEach(b=>{const yes=favorites.has(b.dataset.favorite);b.textContent=yes?'已收藏':'收藏';b.setAttribute('aria-pressed',String(yes));});}
  function label(id){const q=byId.get(id);return q?`${q.topic} · 第 ${numbers[id]} 题 · ${questionTitle(q)}`:'题目已不在当前题库';}
  function paint(){
    el('account-favorites').innerHTML=[...favorites].map(id=>`<div class="account-row"><button data-account-open="${escapeHtml(id)}">${escapeHtml(label(id))}</button><button data-favorite="${escapeHtml(id)}">取消收藏</button></div>`).join('')||'<p>还没有收藏。在题目旁点击“收藏”即可添加。</p>';
    el('account-history').innerHTML=history.map(h=>`<div class="account-row"><div><strong>${escapeHtml(h.title)}</strong><small>${escapeHtml(new Date(h.created_at).toLocaleString())} · ${h.question_ids.length} 题</small></div><button data-restore="${escapeHtml(h.id)}">恢复选题</button><button data-delete-paper="${escapeHtml(h.id)}">删除</button></div>`).join('')||'<p>还没有保存的练习卷。</p>';
    refreshButtons();
  }
  async function readFavorites(uid){
    const data=[];for(let start=0;;start+=500){const result=await client.from('favorites').select('question_id').eq('user_id',uid).order('question_id').range(start,start+499);if(result.error)return result;data.push(...result.data);if(result.data.length<500)return {data,error:null};}
  }
  async function load(more=false){
    if(!user)return;const version=epoch,uid=user.id,start=more?offset:0;
    const [f,h]=await Promise.all([readFavorites(uid),client.from('paper_history').select('*').eq('user_id',uid).order('created_at',{ascending:false}).range(start,start+49)]);
    if(version!==epoch)return;if(f.error||h.error)throw f.error||h.error;
    favorites=new Set(f.data.map(x=>x.question_id));history=more?history.concat(h.data):h.data;offset=start+h.data.length;el('account-more').hidden=h.data.length<50;paint();message('个人题库已同步。');
  }
  async function toggle(button){
    const uid=await requireUser(),version=epoch,id=button.dataset.favorite;button.disabled=true;
    try{const result=favorites.has(id)?await client.from('favorites').delete().eq('user_id',uid).eq('question_id',id):await client.from('favorites').upsert({user_id:uid,question_id:id},{onConflict:'user_id,question_id',ignoreDuplicates:true});if(result.error)throw result.error;if(version!==epoch)return;favorites.has(id)?favorites.delete(id):favorites.add(id);paint();}
    finally{button.disabled=false;}
  }
  const saving=new Set();
  async function savePaper(ids,title,interactive=false){
    try{
      if(!ids.length){if(interactive)message('请先在题库中勾选题目。');return;}if(!user&&!interactive)return;
      const uid=await requireUser(),version=epoch,valid=[...new Set(ids)].filter(id=>byId.has(id));if(!valid.length)throw Error('没有可保存的题目。');
      const key=JSON.stringify([uid,title,valid]);if(saving.has(key))return;saving.add(key);
      try{const {error}=await client.from('paper_history').insert({user_id:uid,title:String(title).slice(0,150),question_ids:valid});if(error)throw error;if(version===epoch){await load();message('练习卷已保存。');}}finally{saving.delete(key);}
    }catch(e){if(!dialog.open)dialog.showModal();fail(e);}
  }
  el('account-launch').onclick=()=>{dialog.showModal();message('正在连接账户服务…');connect().then(()=>{if(user)return load();message('登录后，收藏和组卷历史会保存在你的账户中。');}).catch(fail);};el('account-close').onclick=()=>dialog.close();
  el('account-form').onsubmit=async e=>{e.preventDefault();if(loading)return;loading=true;const form=e.target,action=e.submitter.value,email=form.elements.email.value.trim(),password=form.elements.password.value;message('正在处理…');
    try{await connect();let result;const redirect=location.origin+location.pathname;
      if(action==='reset'){if(!form.elements.email.reportValidity())return;result=await client.auth.resetPasswordForEmail(email,{redirectTo:redirect});}
      else if(action==='signup')result=await client.auth.signUp({email,password,options:{emailRedirectTo:redirect}});
      else result=await client.auth.signInWithPassword({email,password});
      if(result.error)throw result.error;form.elements.password.value='';message(action==='reset'?'若邮箱可用，重置邮件将发送，请检查收件箱。':action==='signup'?'注册请求已提交，请检查邮箱并完成验证。':'登录成功。');
    }catch(e){fail(e);}finally{loading=false;}
  };
  el('account-recovery').onsubmit=async e=>{e.preventDefault();try{const {error}=await client.auth.updateUser({password:e.target.elements.password.value});if(error)throw error;e.target.reset();e.target.hidden=true;message('密码已更新。');}catch(e){fail(e);}};
  el('account-logout').onclick=async()=>{try{const {error}=await client.auth.signOut();if(error)throw error;message('已退出登录。');}catch(e){fail(e);}};
  el('account-refresh').onclick=()=>load().catch(fail);el('account-more').onclick=()=>load(true).catch(fail);
  el('account-save').onclick=()=>savePaper([...selectedQuestions],'自选练习卷',true);
  document.addEventListener('click',e=>{const b=e.target.closest('[data-favorite]');if(b)toggle(b).catch(err=>{if(!dialog.open)dialog.showModal();fail(err);});});
  dialog.addEventListener('click',async e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.dataset.accountOpen){if(!byId.has(b.dataset.accountOpen))return;dialog.close();navigateQuestion(b.dataset.accountOpen);}
    if(b.dataset.restore){const h=history.find(h=>h.id===b.dataset.restore);if(!h)return;const ids=h.question_ids.filter(id=>byId.has(id));if(!ids.length){message('这些题目已不在当前题库。');return;}selectItems(questions,false);selectItems(ids.map(id=>byId.get(id)),true);dialog.close();openExport(ids);}
    if(b.dataset.deletePaper){b.disabled=true;try{const uid=await requireUser();const {error}=await client.from('paper_history').delete().eq('user_id',uid).eq('id',b.dataset.deletePaper);if(error)throw error;await load();}catch(e){fail(e);}finally{b.disabled=false;}}
  });
  window.ChemyAccount={refreshButtons,savePaper};
  el('account-launch').disabled=!ready;
  document.addEventListener('chemy-library-ready',()=>{el('account-launch').disabled=false;paint();connect().catch(()=>{});});
  if(ready){paint();connect().catch(()=>{});}
})();
