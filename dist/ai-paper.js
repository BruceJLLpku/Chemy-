/* DeepSeek plans and selects; audited original questions and answers remain unchanged. */
(function() {
  'use strict';
  const el=id=>document.getElementById(id),engine=window.ChemyPaper,safe=escapeHtml;
  const state={index:null,loading:null,config:null,configLoading:null,concept:null,pool:[],items:[],count:5,
    worker:null,exporting:false,exportNonce:0,agentController:null,agentNonce:0,generating:false,undo:[]};
  let progressTimer;
  function snapshot(){
    const {items,pool,concept,introduction,scope,count,filters,canEdit,lastQuery,history}=state;
    return structuredClone({items,pool,concept,introduction,scope,count,filters,canEdit,lastQuery,history});
  }
  function remember(previous){if(previous.items.length){state.undo.push(previous);state.undo=state.undo.slice(-15);}}
  function syncTools(){
    el('ai-undo').disabled=state.generating||state.exporting||!state.undo.length;
    el('ai-answers-toggle').disabled=!state.items.length;
    el('ai-result').querySelectorAll('[data-ai-word],[data-ai-export],[data-ai-print]').forEach(button=>{button.disabled=state.generating||state.exporting||!state.items.length;});
  }
  function retry(query,editing){
    state.retry={query,editing};el('ai-retry').hidden=false;
  }
  el('ai-retry').onclick=()=>{
    if(state.generating||state.exporting||!state.retry)return;
    const {query,editing}=state.retry;el('ai-query').value=query;
    if(editing&&state.canEdit)editPaper();else generate();
  };
  el('ai-undo').onclick=()=>{
    if(state.generating||state.exporting||!state.undo.length)return;
    Object.assign(state,state.undo.pop());render();showPaper(true);updateComposer();syncTools();
    el('ai-export-status').textContent='已恢复上一次修改前的试卷和知识介绍。';
  };
  document.querySelectorAll('[data-ai-prompt]').forEach(button=>button.onclick=()=>{
    el('ai-query').value=button.dataset.aiPrompt;el('ai-query').focus();
  });
  el('ai-jump').onchange=()=>{
    const target=el('ai-jump').value==='intro'?el('ai-paper-intro'):el('ai-items').children[Number(el('ai-jump').value)];
    target?.scrollIntoView({block:'start',behavior:'instant'});
  };
  el('ai-answers-toggle').onclick=()=>{
    const open=el('ai-answers-toggle').getAttribute('aria-pressed')!=='true';
    el('ai-items').querySelectorAll('.answers').forEach(details=>{details.open=open;});
    el('ai-answers-toggle').setAttribute('aria-pressed',String(open));
    el('ai-answers-toggle').textContent=open?'收起全部答案':'展开全部答案';
  };
  const status=message=>{
    el('ai-status').textContent=message;
    const scroll=el('ai-chat-scroll');
    scroll.scrollTop=scroll.scrollHeight;
  };

  async function loadAgentConfig() {
    if(state.config)return state.config;
    if(!state.configLoading)state.configLoading=(async()=>{
      const response=await fetch('ai-config.json?v=deepseek-v2',{cache:'no-store'});
      if(!response.ok)throw new Error('组卷服务配置暂时无法读取，请重试。');
      const data=await response.json();
      if(!['local','deepseek'].includes(data.mode)||typeof data.backendUrl!=='string')throw new Error('组卷服务配置无效，请联系管理员。');
      let base='';
      if(data.backendUrl){
        const url=new URL(data.backendUrl);
        if(url.username||url.password||url.search||url.hash||url.pathname!=='/'||
          !['http:','https:'].includes(url.protocol)||(location.protocol==='https:'&&url.protocol!=='https:'))throw new Error('组卷后端地址配置无效。');
        base=url.origin;
      }
      state.config={mode:data.mode,backendUrl:base};
      el('ai-welcome').querySelector('.ai-starters').hidden=data.mode!=='deepseek';
      el('ai-mode').textContent=data.mode==='deepseek'?'DeepSeek 对话式组卷':'本地知识点索引选题';
      if(data.mode==='deepseek'){
        el('ai-lead').textContent='描述想要的试卷，组卷助手会从 Chemy 题库选题。出卷后可以继续对话修改。';
        el('ai-query').placeholder='例如：组 5 道羟醛缩合题，先介绍基本原理';
      }
      return state.config;
    })().catch(error=>{state.configLoading=null;throw error;});
    return state.configLoading;
  }
  async function loadIndex() {
    if(state.index)return state.index;
    if(!state.loading)state.loading=(async()=>{
      const response=await fetch('knowledge-index.json?v=keywords-v1',{cache:'no-store'});
      if(!response.ok)throw new Error('知识点索引暂时无法读取，请检查网络后重试。');
      const index=await response.json();
      if(index.schemaVersion!==1||!Array.isArray(index.concepts)||!Array.isArray(index.entries))throw new Error('知识点索引格式不匹配，请刷新重试。');
      if(index.numberingVersion!==numberingVersion||index.entries.some(e=>!byId.has(e.id)))throw new Error('题库与知识点索引正在更新，请刷新后重试。');
      state.index=index;
      el('ai-coverage').textContent=`已审核 ${index.entries.length} / ${questions.length} 道大题，当前仅在已审核题目中选题；保留完整原题与来源。`;
      refreshKnowledge();
      return index;
    })().catch(error=>{state.loading=null;throw error;});
    return state.loading;
  }
  function initialize() {
    el('ai-launch').disabled=false;
    el('ai-topic').innerHTML=option('all','全部专题','all')+topics.map(t=>option(t,t,'all')).join('');
    el('ai-edition').innerHTML=option('all','全部届次','all')+editionValues(questions).map(e=>option(e,editionLabel(e),'all')).join('');
    refreshPapers();
  }
  if(ready)initialize();else document.addEventListener('chemy-library-ready',initialize);
  function refreshPapers() {
    const previous=el('ai-paper').value;
    const list=questions.filter(q=>(el('ai-topic').value==='all'||q.topic===el('ai-topic').value)&&(el('ai-edition').value==='all'||String(editionOf(q))===el('ai-edition').value));
    const keys=[...new Set(list.map(paperKey))];
    el('ai-paper').innerHTML=option('all','全部试卷','all')+keys.map(k=>option(k,paperLabel(k),previous)).join('');
    refreshKnowledge();
  }
  function favoriteBank(){return el('ai-favorites-only').checked?questions.filter(q=>window.ChemyAccount?.has(q.id)):questions;}
  function resetFavoriteScope(){if(!el('ai-favorites-only').checked)return;if(state.generating)cancelGeneration('收藏范围已变化，请重新生成。');state.pool=state.pool.filter(q=>window.ChemyAccount?.has(q.id));state.items=state.items.filter(q=>window.ChemyAccount?.has(q.id));if(state.concept)render();else el('ai-result').hidden=true;refreshKnowledge();}
  document.addEventListener('chemy-favorites-changed',resetFavoriteScope);
  el('ai-favorites-only').addEventListener('change',()=>{cancelGeneration('');state.pool=[];state.items=[];state.canEdit=false;showPaper(false);updateComposer();refreshKnowledge();status(el('ai-favorites-only').checked?'仅从收藏中匹配知识点；题目不足时按实际题量生成。':'已恢复全部题库范围。');});
  function refreshKnowledge() {
    if(!state.index)return;
    const filters={topic:el('ai-topic').value,edition:el('ai-edition').value,paper:el('ai-paper').value};
    const available=engine.availableConcepts(state.index,favoriteBank(),filters);
    const total=engine.availableConcepts(state.index,questions).length;
    el('ai-knowledge-summary').textContent=`查看全部可用知识点（当前范围 ${available.length} / 共 ${total} 个）`;
    const preferred=['羟醛缩合','Michael 加成','Diels-Alder 反应','核磁共振','配位化学','晶胞计算','化学平衡','沉淀溶解平衡','能斯特方程','阿伦尼乌斯方程','配位滴定','高分子分子量'];
    const picked=preferred.map(name=>available.find(c=>c.name===name)).filter(Boolean);
    const suggested=[...picked,...available.filter(c=>!picked.some(p=>p.id===c.id))].slice(0,12);
    const button=c=>`<button type="button" data-ai-keyword="${safe(c.id)}"${state.generating||state.worker?' disabled':''}><span>${safe(c.name)}</span><small>${c.count} 道</small></button>`;
    el('ai-suggested').innerHTML=suggested.map(button).join('');
    const key=engine.normalize(el('ai-knowledge-search').value);
    const visible=available.filter(c=>!key||[c.name,...(c.aliases||[])].some(name=>engine.normalize(name).includes(key)));
    el('ai-knowledge-count').textContent=`找到 ${visible.length} 个知识点。题数为当前筛选范围内的完整大题数；同一题可关联多个知识点。`;
    el('ai-knowledge-list').innerHTML=visible.length?visible.map(button).join(''):'<p class="ai-hint">当前范围没有匹配的知识点，可更换搜索词或放宽高级设置中的来源范围。</p>';
  }
  el('ai-knowledge-search').addEventListener('input',refreshKnowledge);
  el('ai-paper').addEventListener('change',refreshKnowledge);
  el('ai-dialog').querySelector('.ai-discovery').addEventListener('click',event=>{
    const button=event.target.closest('[data-ai-keyword]');
    const concept=button&&state.index?.concepts.find(c=>c.id===button.dataset.aiKeyword);
    if(concept&&!state.generating&&!state.worker){el('ai-query').value=concept.name;generate(concept.id);}
  });
  el('ai-launch').addEventListener('click',async()=>{
    if(!ready)return;
    closePanel(false);el('ai-dialog').showModal();el('ai-query').focus();
    try{await Promise.all([loadAgentConfig(),loadIndex()]);}catch(error){status(error.message);}
  });
  el('ai-close').addEventListener('click',()=>el('ai-dialog').close());
  function cancelGeneration(message) {
    clearInterval(progressTimer);
    state.agentNonce++;state.agentController?.abort();state.agentController=null;state.generating=false;
    el('ai-cancel').hidden=true;busy(false);
    if(message)status(message);
  }
  el('ai-cancel').addEventListener('click',()=>cancelGeneration(!state.canEdit
    ?'本次组卷已取消，可重新生成。':'本次修改已取消，当前试卷已保留。'));
  el('ai-dialog').addEventListener('close',()=>{
    cancelGeneration('');state.exportNonce++;
    const exporting=state.exporting;
    state.worker?.terminate();state.worker=null;state.exporting=false;busy(false);
    if(exporting)el('ai-export-status').textContent='文档生成已取消，可重新下载。';
    el('ai-launch').focus({preventScroll:true});
  });
  for(const id of ['ai-topic','ai-edition'])el(id).addEventListener('change',refreshPapers);
  el('ai-form').addEventListener('submit',event=>{
    event.preventDefault();
    if(state.canEdit)editPaper();else generate();
  });
  el('ai-query').addEventListener('keydown',event=>{
    if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing&&event.keyCode!==229){
      event.preventDefault();el('ai-form').requestSubmit();
    }
  });
  function showPaper(open) {
    const visible=open&&(state.items.length>0||state.undo.length>0);
    el('ai-result').hidden=!visible;
    const button=el('ai-paper-toggle');
    button.hidden=!state.items.length&&!state.undo.length;
    button.setAttribute('aria-expanded',String(visible));
    button.textContent=visible?'返回对话':'查看试卷';
  }
  function updateComposer() {
    el('ai-query').placeholder=state.canEdit
      ?'继续修改这套试卷，例如：第 2 题换一道更难的'
      :state.config?.mode==='deepseek'?'描述你想要的试卷…':'输入想练习的知识点…';
  }
  el('ai-paper-toggle').onclick=()=>showPaper(el('ai-result').hidden);
  el('ai-new').onclick=()=>{
    cancelGeneration('');
    Object.assign(state,{canEdit:false,lastQuery:'',items:[],pool:[],concept:null,introduction:'',scope:null,history:[],undo:[]});
    for(const id of ['ai-turns','ai-candidates','ai-items'])el(id).replaceChildren();
    el('ai-welcome').hidden=false;
    el('ai-query').value='';
    el('ai-retry').hidden=true;
    status('');showPaper(false);updateComposer();syncTools();el('ai-query').focus();
  };

  function showCandidates(concepts,message) {
    state.items=[];state.pool=[];el('ai-result').hidden=true;status(message);
    el('ai-candidates').innerHTML=concepts.map(c=>`<button type="button" data-ai-concept="${safe(c.id)}">${safe(c.name)}</button>`).join('');
  }
  function readBankItems(items) {
    return (Array.isArray(items)?items:[]).filter(item=>byId.has(item?.id));
  }
  function modelReply(data,fallback) {
    const text=data.message||fallback;
    return data.missingQuestions
      ?`${text}
有 ${data.missingQuestions} 个题号无法从本次题库范围读取。`
      :text;
  }
  async function requestPaper(config,body,signal) {
    let response;
    try {
      response=await fetch(`${config.backendUrl}/api/compose`,{method:'POST',headers:{'Content-Type':'application/json'},
        body:JSON.stringify({numberingVersion,conversation:true,...body}),signal});
    } catch(error){
      if(signal.aborted)throw error;
      throw new Error('暂时无法连接智能组卷服务，请稍后重试。');
    }
    let data;
    try{data=await response.json();}catch{throw new Error('组卷服务暂时未就绪，请稍后重试。');}
    if(!response.ok)throw new Error(typeof data?.error==='string'?data.error:'智能组卷失败，请稍后重试。');
    return data;
  }
  function introductionHtml(text) {
    return window.ChemyLecture.html(text);
  }
  function addTurn(speaker,message,{introduction,paper}={}) {
    el('ai-welcome').hidden=true;
    state.history=[...(state.history||[]),{role:speaker==='你'?'user':'assistant',text:message.slice(0,400)}].slice(-8);
    const turn=document.createElement('article');
    turn.className=speaker==='你'?'ai-turn ai-turn-user':'ai-turn ai-turn-assistant';
    const author=document.createElement('strong'),body=document.createElement('p');
    author.textContent=speaker;body.textContent=message;
    turn.append(author,body);
    if(introduction){
      const note=document.createElement('details'),heading=document.createElement('summary'),text=document.createElement('div');
      note.className='ai-chat-intro';heading.textContent='查看本轮知识介绍';text.innerHTML=introductionHtml(introduction);
      note.append(heading,text);turn.append(note);
    }
    if(paper){
      const button=document.createElement('button');
      button.type='button';button.textContent='查看当前试卷';button.onclick=()=>{showPaper(true);el('ai-paper-toggle').focus();};
      turn.append(button);
    }
    el('ai-turns').append(turn);
    const scroll=el('ai-chat-scroll');
    scroll.scrollTop=scroll.scrollHeight;
  }
  async function generate(conceptId) {
    if(state.exporting||state.worker||state.generating||!el('ai-form').reportValidity())return;
    const previous=snapshot();
    const query=el('ai-query').value.trim(),count=Number(el('ai-count').value);
    if(!query)return;
    if(el('ai-favorites-only').checked&&!window.ChemyAccount?.isSignedIn()){status('请先登录，再从收藏中组卷。');return;}
    const bank=favoriteBank();
    const filters={topic:el('ai-topic').value,edition:el('ai-edition').value,paper:el('ai-paper').value};
    const nonce=++state.agentNonce,controller=new AbortController();
    state.agentController=controller;state.generating=true;busy(true);el('ai-cancel').hidden=false;
    const history=state.history;
    el('ai-candidates').replaceChildren();
    Object.assign(state,{lastQuery:query});
    el('ai-retry').hidden=true;
    addTurn('你',query);
    el('ai-query').value='';
    el('ai-form').querySelector('details').open=false;
    status('正在匹配知识点…');
    let timer,response;
    try {
      const [config,index]=await Promise.all([loadAgentConfig(),loadIndex()]);
      if(nonce!==state.agentNonce)return;
      if(!index.entries.length){status('题库的知识点分析尚未完成，请稍后再试。');return;}
      state.count=count;
      if(config.mode==='local'||el('ai-favorites-only').checked) {
        const resolved=conceptId?{kind:'exact',concepts:index.concepts.filter(c=>c.id===conceptId)}:engine.resolve(query,index.concepts);
        if(resolved.kind!=='exact'||!resolved.concepts.length){showCandidates(resolved.concepts,resolved.concepts.length?'请选择你想练习的知识点，再生成试卷。':'未识别到这个知识点，请更换名称或使用更具体的表述。');return;}
        state.concept=resolved.concepts[0];
        state.pool=engine.candidates(state.concept.id,index,bank,filters);state.items=engine.choose(state.pool,count);
        state.introduction='';state.canEdit=false;
      } else {
        status('DeepSeek 正在理解需求并选择题目，首次唤醒服务可能需要稍候…');
        timer=setTimeout(()=>controller.abort('timeout'),180000);
        const data=await requestPaper(config,{query,count,filters,history,...(conceptId?{conceptId}:{})},controller.signal);
        if(nonce!==state.agentNonce)return;
        if(data.kind==='unknown'){
          addTurn('组卷助手',typeof data.message==='string'&&data.message.trim()?data.message:'你想练习哪个化学主题？也可以把想要的内容一起告诉我。');
          status('');return;
        }
        if(data.kind!=='paper')throw new Error('暂时无法读取组卷结果，请重试。');
        response=data;
        Object.assign(state,{concept:data.concept,scope:data.scope,items:readBankItems(data.items),pool:readBankItems(data.pool),count:data.count??count,filters});
        state.introduction=typeof data.introduction==='string'?data.introduction:'';
        state.canEdit=state.items.length>0;
      }
      if(nonce!==state.agentNonce)return;
      remember(previous);
      if(state.items.length||response?.message||response?.missingQuestions){
        addTurn('组卷助手',modelReply(response||{},`已从题库选出 ${state.items.length} 道题。`),{introduction:state.introduction,paper:state.items.length>0});
      }
      updateComposer();
      el('ai-export-status').textContent='';render();showPaper(true);
    } catch(error){
      if(nonce!==state.agentNonce)return;
      Object.assign(state,previous);render();retry(query,false);
      status(controller.signal.aborted?'等待智能组卷服务超时，请稍后重试。':error.message||'组卷失败，请重试。');
    } finally {
      clearTimeout(timer);
      if(nonce===state.agentNonce){state.agentController=null;state.generating=false;el('ai-cancel').hidden=true;busy(false);el('ai-query').focus();}
    }
  }
  async function editPaper(queryOverride){
    if(state.generating||state.exporting||state.worker||!state.canEdit)return;
    const input=el('ai-query'),query=queryOverride||input.value.trim();
    if(!query)return;
    const nonce=++state.agentNonce,controller=new AbortController();
    const previous=new Map(state.items.map(item=>[item.id,item]));
    const before=snapshot();
    const history=state.history;
    state.agentController=controller;state.generating=true;busy(true);el('ai-cancel').hidden=false;
    addTurn('你',query);if(!queryOverride)input.value='';
    el('ai-retry').hidden=true;
    status('正在根据当前试卷处理修改…');
    const timer=setTimeout(()=>controller.abort('timeout'),180000);
    try {
      const data=await requestPaper(state.config,{query,history,count:state.count,filters:state.filters,
        ...(state.scope?{scope:state.scope}:{conceptId:state.concept.id}),currentIds:[...previous.keys()],introduction:state.introduction.slice(0,4500)},controller.signal);
      if(nonce!==state.agentNonce)return;
      if(data.kind!=='paper')throw new Error('暂时无法读取修改结果，当前试卷已保留。');
      const items=readBankItems(data.items),pool=readBankItems(data.pool);
      remember(before);
      state.items=items.map(item=>previous.get(item.id)||item);state.pool=pool;
      state.count=items.length;state.canEdit=items.length>0;
      if(data.scope)state.scope=data.scope;
      if(data.concept)state.concept=data.concept;
      if(typeof data.introduction==='string')state.introduction=data.introduction;
      el('ai-export-status').textContent='';
      addTurn('组卷助手',modelReply(data,'已按本轮结果更新试卷。'),{introduction:data.introduction,paper:items.length>0});
      render();updateComposer();
    } catch(error) {
      if(nonce===state.agentNonce){retry(query,true);status(controller.signal.aborted?'修改超时，当前试卷已保留。':error.message);}
    } finally {
      clearTimeout(timer);
      if(nonce===state.agentNonce){
        state.agentController=null;state.generating=false;el('ai-cancel').hidden=true;busy(false);input.focus();
      }
    }
  }
  el('ai-candidates').addEventListener('click',event=>{
    const button=event.target.closest('[data-ai-concept]');
    const concept=button&&state.index?.concepts.find(c=>c.id===button.dataset.aiConcept);
    if(concept){
      el('ai-query').value=concept.name;
      generate(concept.id);
    }
  });
  function labels(item) {
    const q=byId.get(item.id);
    return item.links.map(link=>{
      const refs=link.subquestions.map(ref=>{
        if(ref==='整题')return '整道题';
        const displayed=ref.replace(new RegExp(`^${q.number}(?=-|$)`),String(numbers[q.id]));
        return displayed===ref?`第 ${ref} 问`:`第 ${displayed} 问（原 ${ref}）`;
      }).join('、');
      return `${refs}：${link.reason}`;
    });
  }
  function association(item) {
    return `<aside class="ai-association"><h5>知识点关联说明：${safe(state.concept.name)}</h5>${labels(item).map(t=>`<p>${safe(t)}</p>`).join('')}<p class="ai-hint">以上为 AI 分析的关联说明，以下为原卷参考答案。</p></aside>`;
  }
  function origin(q) {return `${paperLabel(paperKey(q))} · 原第 ${q.number} 题 · ${q.topic}专题第 ${numbers[q.id]} 题`;}
  const saveButton=document.createElement('button');saveButton.type='button';saveButton.textContent='保存到组卷历史';el('ai-result').querySelector('.ai-actions').append(saveButton);
  saveButton.onclick=()=>window.ChemyAccount?.savePaper(state.items.map(q=>q.id),state.concept.name+' · 专题练习',true);
  function render() {
    const items=state.items;
    syncTools();
    showPaper(!el('ai-result').hidden);
    const introduction=el('ai-paper-intro');
    introduction.querySelector('div').innerHTML=introductionHtml(state.introduction||'');
    introduction.hidden=!state.introduction;
    if(!items.length){el('ai-items').replaceChildren();el('ai-jump').replaceChildren();el('ai-result-count').textContent='当前试卷 0 道题';status(state.pool.length?'本卷已清空，可撤销修改或重新组卷。':'当前筛选范围内没有可用的相关题目，请放宽来源范围或更换知识点。');if(state.undo.length){el('ai-result').hidden=false;el('ai-export-status').textContent='本卷已清空，可撤销修改或重新组卷。';}return;}
    el('ai-result-title').textContent=`${state.concept.name} · 专题练习`;
    el('ai-result-count').textContent=`本卷 ${items.length} 道完整大题 · 范围内已确认相关 ${state.pool.length} 道 · 保留专题编号与来源`;
    el('ai-jump').innerHTML=(state.introduction?'<option value="intro">知识介绍</option>':'')+items.map((_,i)=>`<option value="${i}">第 ${i+1} 题</option>`).join('');
    el('ai-answers-toggle').setAttribute('aria-pressed','false');el('ai-answers-toggle').textContent='展开全部答案';
    status(items.length<state.count?`目标 ${state.count} 道，当前保留 ${items.length} 道。${state.pool.length<state.count?'相关题量不足，已按实际题量组卷。':'可重新组卷恢复目标题量。'}`:'');
    el('ai-items').innerHTML=items.map((item,i)=>{
      const q=byId.get(item.id);
      return `<article class="ai-item" data-ai-id="${safe(q.id)}"><div class="ai-item-top"><h4>练习第 ${i+1} 题　${safe(q.topic)} · 专题第 ${numbers[q.id]} 题</h4><div class="ai-item-controls"><button type="button" data-favorite="${safe(q.id)}" aria-pressed="false">收藏</button><button type="button" data-ai-replace="${safe(q.id)}"${state.pool.length<=items.length?' disabled':''}>换一题</button><button type="button" data-ai-remove="${safe(q.id)}">删除</button></div></div><p class="ai-origin">${safe(origin(q))}</p><div class="q-body">${lazyFigures(presentation[q.id].body)}</div><details class="answers"><summary><span>查看答案与关联说明</span></summary>${association(item)}<div class="answer-content">${lazyFigures(presentation[q.id].answer)}</div></details></article>`;
    }).join('');
    window.ChemyAccount?.refreshButtons();
  }
  el('ai-items').addEventListener('click',event=>{
    if(state.worker||state.exporting||state.generating)return;
    const remove=event.target.closest('[data-ai-remove]'),replace=event.target.closest('[data-ai-replace]');
    const anchor=(remove||replace)?.closest('.ai-item');
    const y=anchor?.getBoundingClientRect().top;
    if(remove){remember(snapshot());state.items=state.items.filter(q=>q.id!==remove.dataset.aiRemove);state.count=state.items.length;state.canEdit=state.canEdit&&state.items.length>0;render();updateComposer();el('ai-export-status').textContent='已删除题目，可撤销修改。';}
    if(replace){
      if(state.canEdit){
        const position=state.items.findIndex(item=>item.id===replace.dataset.aiReplace)+1;
        editPaper(`请替换第 ${position} 题，保持其余题目与顺序，兼顾整卷知识覆盖和难度，并同步更新需要调整的知识介绍。`);return;
      }
      const next=engine.choose(state.pool,1,state.items.map(q=>q.id))[0];
      if(!next){el('ai-export-status').textContent='没有其他符合当前条件的题目可替换。';return;}
      remember(snapshot());state.items=state.items.map(q=>q.id===replace.dataset.aiReplace?next:q);render();
      const target=el('ai-items').querySelector(`[data-ai-id="${CSS.escape(next.id)}"]`);
      if(target && y!=null)el('ai-result').scrollTop+=target.getBoundingClientRect().top-y;
      target?.querySelector('[data-ai-replace]')?.focus({preventScroll:true});
    }
  });
  el('ai-reroll').addEventListener('click',()=>{el('ai-query').value=state.lastQuery;generate();});
  function busy(value) {
    clearInterval(progressTimer);
    el('ai-dialog').classList.toggle('ai-is-working',state.generating);
    el('ai-turns').setAttribute('aria-busy',String(state.generating));
    if(state.generating){
      const started=Date.now();
      progressTimer=setInterval(()=>{el('ai-status').dataset.elapsed=`已等待 ${Math.floor((Date.now()-started)/1000)} 秒`;},1000);
    }else delete el('ai-status').dataset.elapsed;
    el('ai-dialog').querySelectorAll('#ai-form input,#ai-form select,#ai-form textarea,#ai-generate,#ai-new').forEach(input=>{input.disabled=value;});
    el('ai-result').querySelectorAll('button').forEach(button=>{button.disabled=value;});
    el('ai-dialog').querySelectorAll('[data-ai-keyword]').forEach(button=>{button.disabled=value;});
    if(!value) el('ai-items').querySelectorAll('[data-ai-replace]').forEach(button=>{button.disabled=state.pool.length<=state.items.length;});
    if(!value)syncTools();
  }
  function canvasNotes(lines,heading=false,formatted=false) {
    const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');
    const width=1000,padding=24,size=heading?27:23,lineHeight=Math.ceil(size*1.65);
    const family=getComputedStyle(document.documentElement).getPropertyValue('--question-font').trim();
    const wrapped=[],tags=[];
    for(const entry of lines) {
      const line=typeof entry==='string'?entry:entry.html,kind=typeof entry==='string'?'paragraph':entry.kind;
      if(formatted&&wrapped.length)wrapped.push([]);
      let row=[],x=0;
      const pushRow=()=>{row.kind=kind;row.width=x;wrapped.push(row);};
      const parts=formatted?line.split(/(<\/?(?:sub|sup|i|strong)>)/gi):[line];
      for(const part of parts){
        const tag=formatted&&/^<(\/?)(sub|sup|i|strong)>$/i.exec(part);
        if(tag){
          const name=tag[2].toLowerCase();
          if(!tag[1])tags.push(name);
          else if(tags.includes(name))tags.splice(tags.lastIndexOf(name),1);
          continue;
        }
        const offset=tags.includes('sub')?5:tags.includes('sup')?-8:0;
        const font=`${tags.includes('i')?'italic ':''}${tags.includes('strong')?'bold ':''}${offset?Math.round(size*.72):size}px ${family}`;
        ctx.font=font;
        for(const char of part){
          const advance=ctx.measureText(char).width;
          if(x+advance>width-2*padding&&row.length){pushRow();row=[];x=0;}
          row.push({char,x,font,offset});
          x+=advance;
        }
      }
      pushRow();
    }
    const images=[],pageLength=formatted?24:wrapped.length;
    for(let start=0;start<wrapped.length;){
      let end=Math.min(wrapped.length,start+pageLength);
      if(formatted&&end<wrapped.length){while(end>start+1&&(!wrapped[end-1].length||wrapped[end-1].kind==='heading'))end--;}
      const page=wrapped.slice(start,end);start=end;
      canvas.width=width;canvas.height=padding*2+page.length*lineHeight;
      ctx.fillStyle='#fff';ctx.fillRect(0,0,width,canvas.height);ctx.fillStyle='#252b29';
      page.forEach((row,i)=>row.forEach(({char,x,font,offset})=>{
        ctx.font=font;ctx.fillText(char,(row.kind==='formula'?(width-row.width)/2:padding)+x,padding+size+i*lineHeight+offset);
      }));
      const raw=atob(canvas.toDataURL('image/png').split(',')[1]);
      images.push({bytes:Uint8Array.from(raw,c=>c.charCodeAt(0)),width,height:canvas.height});
    }
    return images;
  }
  const canvasNote=(lines,heading=false)=>canvasNotes(lines,heading)[0];
  async function download(kind) {
    if(state.exporting||state.generating||state.worker || !state.items.length)return;
    const snapshot=state.items.slice(),name=state.concept.name,introduction=state.introduction;
    const nonce=++state.exportNonce;
    state.exporting=true;busy(true);el('ai-export-status').textContent='正在准备 PDF…';
    try {
      await document.fonts.ready;
      if(nonce!==state.exportNonce)return;
      // Only our added commentary is rasterized; source answers remain vector pages.
      const header=canvasNote([`${name} · ${kind==='answers'?'参考答案':'专题练习'}`,`共 ${snapshot.length} 道完整大题，保留原专题编号与来源。`],true);
      const paperIntro=kind==='questions'&&introduction
        ?canvasNotes([{html:'<strong>知识介绍</strong>',kind:'heading'},...window.ChemyLecture.blocks(introduction)],false,true):[];
      const items=snapshot.map((item,i)=>({id:item.id,slug:slugByTopic[byId.get(item.id).topic],annotation:kind==='answers'?canvasNote([`练习第 ${i+1} 题 · 知识点关联说明`,...labels(item),'关联说明由 AI 分析；下方为原卷参考答案。']):null}));
      state.worker=new Worker('pdf-worker.js?v=ai-paper-intro-v1');
      const fail=message=>{state.worker?.terminate();state.worker=null;state.exporting=false;busy(false);el('ai-export-status').textContent=message;};
      state.worker.onerror=()=>fail('PDF 工具加载失败，请检查网络后重新下载。');
      state.worker.onmessage=({data})=>{
        if(data.status)el('ai-export-status').textContent=data.status;
        else if(data.error)fail(data.error);
        else if(data.bytes){
          const url=URL.createObjectURL(new Blob([data.bytes],{type:'application/pdf'})),link=document.createElement('a');
          link.href=url;link.download=`Chemy-${name.replace(/[\\/:*?"<>|]/g,'_')}-${kind==='answers'?'答案':'题目'}.pdf`;
          document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
          state.worker.terminate();state.worker=null;state.exporting=false;busy(false);el('ai-export-status').textContent='PDF 已生成，下载已开始。';window.ChemyAccount?.savePaper(items.map(q=>q.id),name+' · 专题练习');
        }
      };
      state.worker.postMessage({items,version:pdfVersion,kind,title:`Chemy · ${name} · ${kind==='answers'?'答案':'题目'}`,paperHeader:header,paperIntro});
    }catch(_){state.worker?.terminate();state.worker=null;state.exporting=false;busy(false);el('ai-export-status').textContent='PDF 生成失败，请重试下载。';}
  }
  document.querySelectorAll('[data-ai-export]').forEach(button=>button.addEventListener('click',()=>download(button.dataset.aiExport)));
  document.querySelectorAll('[data-ai-word]').forEach(button=>button.addEventListener('click',async()=>{
    if(state.exporting||state.worker||state.generating||button.disabled||!state.items.length)return;
    const answers=button.dataset.aiWord==='answers',kind=answers?'答案':'题目';
    const name=state.concept.name,nonce=++state.exportNonce;
    const items=state.items.map(({id})=>({origin:origin(byId.get(id)),html:presentation[id][answers?'answer':'body']}));
    state.exporting=true;busy(true);el('ai-export-status').textContent='正在生成可编辑的 Word 文档…';
    try{
      const blob=await window.ChemyWord.build({title:`${name} ${kind}`,
        introduction:answers?'':state.introduction||'',items});
      if(nonce!==state.exportNonce)return;
      const url=URL.createObjectURL(blob),link=document.createElement('a');
      link.href=url;link.download=`Chemy-${name.replace(/[\\/:*?"<>|]/g,'_')}-${kind}.docx`;
      document.body.append(link);link.click();link.remove();
      setTimeout(()=>URL.revokeObjectURL(url),60000);
      el('ai-export-status').textContent='Word 已生成，下载已开始。';
      window.ChemyAccount?.savePaper(state.items.map(q=>q.id),name+' · 专题练习');
    }catch(error){
      if(nonce===state.exportNonce)el('ai-export-status').textContent=error.message||'Word 生成失败，请重试。';
    }finally{
      if(nonce===state.exportNonce){state.exporting=false;busy(false);}
    }
  }));
  async function printPaper(kind) {
    if(state.exporting||state.generating||state.worker || !state.items.length)return;
    state.exporting=true;busy(true);
    const target=el('ai-print');
    const intro=kind==='questions'&&state.introduction
      ?`<section class="ai-paper-intro"><h2>知识介绍</h2><div class="q-body ai-paper-intro-text">${introductionHtml(state.introduction)}</div></section>`:'';
    target.innerHTML=`<h1>${safe(state.concept.name)} · ${kind==='answers'?'参考答案':'专题练习'}</h1><p>共 ${state.items.length} 道完整大题，保留原专题编号与来源。</p>`+intro+state.items.map((item,i)=>{
      const q=byId.get(item.id);
      return `<article class="ai-item"><h2>练习第 ${i+1} 题 · ${safe(q.topic)}专题第 ${numbers[q.id]} 题</h2><p class="ai-origin">${safe(origin(q))}</p>${kind==='answers'?association(item):''}<div class="${kind==='answers'?'answer-content':'q-body'}">${presentation[q.id][kind==='answers'?'answer':'body']}</div></article>`;
    }).join('');
    target.insertAdjacentHTML('beforeend','<footer class="ai-print-copyright">题目与参考答案版权归 Chemy 化学奥林匹克团队原命题组所有，仅供学术交流使用。</footer>');
    target.querySelectorAll('img').forEach(img=>{img.loading='eager';});
    try{
      await Promise.all([...target.querySelectorAll('img')].map(img=>img.decode()));await document.fonts.ready;
      document.body.classList.add('ai-printing');window.print();
    }catch(_){el('ai-export-status').textContent='有题图未能加载，请检查网络后重新打印。';}
    finally{document.body.classList.remove('ai-printing');target.replaceChildren();state.exporting=false;busy(false);}
  }
  document.querySelectorAll('[data-ai-print]').forEach(button=>button.addEventListener('click',()=>printPaper(button.dataset.aiPrint)));
})();
