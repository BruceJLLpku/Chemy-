/* Personal data is authorized by database RLS, never by UI filtering alone. */
(function () {
  'use strict';
  const dialog=document.createElement('dialog');dialog.id='account-dialog';dialog.className='account-dialog';
  dialog.innerHTML=`<div class="search-heading"><h2>我的题库</h2><button type="button" id="account-close" aria-label="关闭我的题库">×</button></div>
    <p id="account-status" role="status" aria-live="polite"></p>
    <form id="account-form"><label>邮箱<input name="email" type="email" autocomplete="email" required maxlength="254"></label><label>密码<input name="password" type="password" autocomplete="current-password" minlength="8" maxlength="128" required></label><p>首次使用请注册，并通过邮件验证邮箱。密码至少 8 位。</p><div class="account-actions"><button name="action" value="login">登录</button><button name="action" value="signup">注册账户</button><button name="action" value="reset" formnovalidate>忘记密码</button></div></form>
    <form id="account-recovery" hidden><label>设置新密码<input name="password" type="password" autocomplete="new-password" minlength="8" maxlength="128" required></label><button>保存新密码</button></form>
    <section id="account-library" hidden><p id="account-email"></p><div class="account-actions"><button id="account-refresh">刷新</button><button id="account-logout">退出登录</button><button id="account-save">保存当前选题</button></div><label class="auto-favorite-label"><input type="checkbox" data-auto-favorite checked>保存或下载组卷后自动收藏</label><button type="button" id="account-retry" hidden>重试未完成的保存</button><div hidden><div id="account-favorites"></div><div id="account-history"></div><button id="account-more" hidden>加载更多历史</button></div><p>收藏与组卷历史已移至左侧栏。</p><button type="button" id="account-name">设置论坛昵称</button></section>`;
  document.body.append(dialog);
  const el=id=>document.getElementById(id), message=t=>{el('account-status').textContent=t;};
  let client,user=null,favorites=new Set(),history=[],epoch=0,loading=false,offset=0;
  let favoriteSignature="";
  let setup, autoFavorite=true, preferencesReady=false, retryJob=null, favoritesPage=0, personalError="";
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
      if(changed){epoch++;favorites=new Set();history=[];offset=0;autoFavorite=true;preferencesReady=false;personalError="";retryJob=null;el("account-retry").hidden=true;paint();}
      if(user)autoFavorite=user.user_metadata?.chemy_auto_favorite!==false;
      showState();
      if(event==='PASSWORD_RECOVERY'){el('account-recovery').hidden=false;dialog.open||dialog.showModal();message('请设置新密码。');}
      if(user&&changed)setTimeout(()=>load().catch(fail),0);
    });
    const {data,error}=await client.auth.getSession();if(error)throw error;
    user=data.session?.user||null;showState();if(user)await load();else message('登录后，收藏和组卷历史会保存在你的账户中。');
  }
  function connect(){if(!setup)setup=initialize().catch(e=>{setup=null;throw e;});return setup;}
  function showState(){document.dispatchEvent(new Event('chemy-auth-changed'));el('account-form').hidden=!!user;el('account-library').hidden=!user;el('account-email').textContent=user?.email||'';el('account-launch').textContent=user?'我的题库':'登录 / 我的题库';if(!user)el('account-recovery').hidden=true;}
  async function requireUser(){await connect();if(!user){if(!dialog.open)dialog.showModal();throw Error('请先登录，再保存到个人题库。');}return user.id;}
  function refreshButtons(){document.querySelectorAll('[data-favorite]').forEach(b=>{const yes=favorites.has(b.dataset.favorite);b.textContent=yes?'已收藏':'收藏';b.setAttribute('aria-pressed',String(yes));});}
  function label(id){const q=byId.get(id);return q?`${q.topic} · 第 ${numbers[id]} 题 · ${questionTitle(q)}`:'题目已不在当前题库';}
  function paint(){
    document.querySelectorAll("[data-auto-favorite]").forEach(input=>{input.checked=autoFavorite;input.disabled=!user||!preferencesReady;});
    el("favorites-nav-count").textContent=favorites.size;
    if(ready&&showingFavorites)renderFavorites();
    if(ready&&el("question-picker").open)renderPicker();
    const signature=JSON.stringify([user?.id,[...favorites].sort()]);if(signature!==favoriteSignature){favoriteSignature=signature;document.dispatchEvent(new Event("chemy-favorites-changed"));}
    el('account-favorites').innerHTML=[...favorites].map(id=>`<div class="account-row"><button data-account-open="${escapeHtml(id)}">${escapeHtml(label(id))}</button><button data-favorite="${escapeHtml(id)}">取消收藏</button></div>`).join('')||'<p>还没有收藏。在题目旁点击“收藏”即可添加。</p>';
    el('account-history').innerHTML=history.map(h=>`<div class="account-row"><div><strong>${escapeHtml(h.title)}</strong><small>${escapeHtml(new Date(h.created_at).toLocaleString())} · ${h.question_ids.length} 题</small></div><button data-restore="${escapeHtml(h.id)}">恢复选题</button><button data-delete-paper="${escapeHtml(h.id)}">删除</button></div>`).join('')||'<p>还没有保存的练习卷。</p>';
    if(ready&&window.communityView==='history')renderHistory();
    refreshButtons();
  }
  async function readFavorites(uid){
    const data=[];for(let start=0;;start+=500){const result=await client.from('favorites').select('question_id').eq('user_id',uid).order('question_id').range(start,start+499);if(result.error)return result;data.push(...result.data);if(result.data.length<500)return {data,error:null};}
  }
  async function load(more=false){
    if(!user)return;const version=epoch,uid=user.id,start=more?offset:0;
    const [f,h,profile]=await Promise.all([readFavorites(uid),client.from('paper_history').select('*').eq('user_id',uid).order('created_at',{ascending:false}).range(start,start+49),client.auth.getUser()]);
    if(version!==epoch)return;if(f.error||h.error||profile.error){personalError="个人数据同步失败，请在我的题库中刷新重试。";paint();throw f.error||h.error||profile.error;}
    autoFavorite=profile.data.user.user_metadata?.chemy_auto_favorite!==false;preferencesReady=true;personalError="";
    favorites=new Set(f.data.map(x=>x.question_id));history=more?history.concat(h.data):h.data;offset=start+h.data.length;el('account-more').hidden=h.data.length<50;paint();message('个人题库已同步。');
  }
  const pendingFavorites=new Set();
  async function toggle(button){
    const uid=await requireUser(),version=epoch,id=button.dataset.favorite;if(pendingFavorites.has(id))return;pendingFavorites.add(id);const remove=favorites.has(id);button.disabled=true;
    try{const result=remove?await client.from('favorites').delete().eq('user_id',uid).eq('question_id',id):await client.from('favorites').upsert({user_id:uid,question_id:id},{onConflict:'user_id,question_id',ignoreDuplicates:true});if(result.error)throw result.error;if(version!==epoch)return;remove?favorites.delete(id):favorites.add(id);paint();}
    finally{pendingFavorites.delete(button.dataset.favorite);button.disabled=false;}
  }
  const saving=new Set();
  async function savePaper(ids,title,interactive=false,collect=true){
    const owner=user?.id;let historySaved=false;
    try{
      if(!ids.length){if(interactive)message('请先在题库中勾选题目。');return;}if(!user&&!interactive)return;
      const uid=await requireUser(),version=epoch,valid=[...new Set(ids)].filter(id=>byId.has(id));if(!valid.length)throw Error('没有可保存的题目。');
      const key=JSON.stringify([uid,title,valid]);if(saving.has(key))return;saving.add(key);
      try{const {error}=await client.from('paper_history').insert({user_id:uid,title:String(title).slice(0,150),question_ids:valid});if(error)throw error;historySaved=true;if(version===epoch){retryJob=null;el('account-retry').hidden=true;if(collect)await collectPaper(uid,valid);await load();message(retryJob?'练习卷已保存，自动收藏未完成。请点击重试，无需重新下载。':'练习卷已保存。');}}finally{saving.delete(key);}
    }catch(e){if(owner&&user?.id===owner){retryJob={uid:owner,ids:ids.filter(id=>byId.has(id)),title,collect,history:!historySaved};el('account-retry').hidden=false;message('云端保存未完成，请点击重试，无需重新下载。');}else fail(e);if(!dialog.open)dialog.showModal();}
  }
  async function collectPaper(uid,ids){
    try{
      const version=epoch;const profile=await client.auth.getUser();if(profile.error)throw profile.error;if(version!==epoch||profile.data.user.id!==uid)return;autoFavorite=profile.data.user.user_metadata?.chemy_auto_favorite!==false;preferencesReady=true;
      if(!autoFavorite){retryJob=null;el('account-retry').hidden=true;paint();return;}
      const {error}=await client.from('favorites').upsert(ids.map(question_id=>({user_id:uid,question_id})),{onConflict:'user_id,question_id',ignoreDuplicates:true});if(error)throw error;if(version!==epoch)return;ids.forEach(id=>favorites.add(id));retryJob=null;el('account-retry').hidden=true;paint();
    }catch(error){if(user?.id!==uid)return;retryJob={uid,ids};el('account-retry').hidden=false;message('练习卷已保存，自动收藏未完成。请点击重试，无需重新下载。');if(!dialog.open)dialog.showModal();}
  }
  el('account-retry').onclick=async()=>{const job=retryJob;if(!job||user?.id!==job.uid)return;if(job.history){await savePaper(job.ids,job.title,true,job.collect);return;}try{await load();if(job.collect!==false)await collectPaper(job.uid,job.ids);else{retryJob=null;el('account-retry').hidden=true;}if(!retryJob)message('自动收藏已完成。');}catch(e){fail(e);}};
  document.addEventListener('change',async event=>{const input=event.target.closest('[data-auto-favorite]');if(!input)return;const previous=autoFavorite,version=epoch;document.querySelectorAll('[data-auto-favorite]').forEach(i=>i.disabled=true);try{await requireUser();const {error}=await client.auth.updateUser({data:{chemy_auto_favorite:input.checked}});if(error)throw error;if(version===epoch)autoFavorite=input.checked;}catch(e){if(version===epoch)autoFavorite=previous;if(!dialog.open)dialog.showModal();fail(e);}finally{paint();}});
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
  document.addEventListener('click',async e=>{
    const b=e.target.closest('button');if(!b)return;
    if(b.dataset.accountOpen){if(!byId.has(b.dataset.accountOpen))return;dialog.close();navigateQuestion(b.dataset.accountOpen);}
    if(b.dataset.restore){const h=history.find(h=>h.id===b.dataset.restore);if(!h)return;const ids=h.question_ids.filter(id=>byId.has(id));if(!ids.length){message('这些题目已不在当前题库。');return;}selectItems(questions,false);selectItems(ids.map(id=>byId.get(id)),true);if(dialog.open)dialog.close();openExport(ids);}
    if(b.dataset.deletePaper){b.disabled=true;try{const uid=await requireUser();const {error}=await client.from('paper_history').delete().eq('user_id',uid).eq('id',b.dataset.deletePaper);if(error)throw error;await load();}catch(e){fail(e);}finally{b.disabled=false;}}
  });
  function renderHistory(){const host=document.getElementById('community-content');host.innerHTML='<h1>组卷历史</h1><p>恢复选题后，可以重新下载题目与答案。</p>'+(!user?'<button type="button" data-community-login>登录查看历史</button>':el('account-history').innerHTML+'<button type="button" id="history-more" '+(el('account-more').hidden?'hidden':'')+'>加载更多历史</button>');const more=document.getElementById('history-more');if(more)more.onclick=()=>load(true).catch(fail);}
  el('account-name').onclick=()=>window.ChemyForum?.editName();
  function renderFavorites(){
    document.title='我的收藏 · Chemy';el('topic-title').textContent='我的收藏';el('downloads').replaceChildren();el('questions').setAttribute('aria-busy','false');
    el('favorites-login').hidden=!!user;el('favorites-status').textContent=personalError||(!user?'登录后可在这里查看、筛选和组卷。':'收藏题目可直接阅读、展开答案，勾选后下载练习卷。');
    const topic=el('favorites-topic').value,key=normalizeText(el('favorites-search').value).toLowerCase();
    const list=questions.filter(q=>user&&favorites.has(q.id)&&(topic==='all'||q.topic===topic)&&(!key||normalizeText(questionTitle(q)+' '+presentation[q.id].body.replace(/<[^>]*>/g,' ')).toLowerCase().includes(key)));
    const pages=Math.max(1,Math.ceil(list.length/10));favoritesPage=Math.min(favoritesPage,pages-1);
    el('topic-summary').textContent=`共收藏 ${favorites.size} 题 · 当前筛选 ${list.length} 题`;
    el('favorites-page').textContent=`第 ${favoritesPage+1} / ${pages} 页`;el('favorites-prev').disabled=favoritesPage===0;el('favorites-next').disabled=favoritesPage>=pages-1;
    el('questions').innerHTML=list.slice(favoritesPage*10,favoritesPage*10+10).map(renderQuestion).join('')||'<section class="empty"><h2>这里还没有题目</h2><p>可在题目旁点击收藏，或保存、下载一份练习卷。</p></section>';refreshButtons();updateSelection();window.ChemyForum?.mount();
  }
  el('favorites-topic').innerHTML=option('all','全部专题','all')+topics.map(t=>option(t,t,'all')).join('');
  for(const id of ['favorites-topic','favorites-search'])el(id).addEventListener('input',()=>{favoritesPage=0;renderFavorites();});
  for(const [id,step] of [['favorites-prev',-1],['favorites-next',1]])el(id).onclick=()=>{favoritesPage+=step;renderFavorites();window.scrollTo({top:0,behavior:'instant'});};
  el('favorites-login').onclick=()=>el('account-launch').click();
  window.ChemyAccount={refreshButtons,savePaper,renderFavorites,has:id=>!!user&&favorites.has(id),isSignedIn:()=>!!user,connection:async()=>{await connect();return {client,user};},renderHistory};
  el('account-launch').disabled=!ready;
  document.addEventListener('chemy-library-ready',()=>{el('account-launch').disabled=false;paint();connect().catch(()=>{});});
  if(ready){paint();connect().catch(()=>{});}
})();
