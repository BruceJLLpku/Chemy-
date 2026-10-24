/* DeepSeek plans and selects; audited original questions and answers remain unchanged. */
(function() {
  'use strict';
  const el=id=>document.getElementById(id),engine=window.ChemyPaper,safe=escapeHtml;
  const state={index:null,loading:null,config:null,configLoading:null,concept:null,pool:[],items:[],count:5,
    worker:null,exportNonce:0,agentController:null,agentNonce:0,generating:false};
  const status=message=>{el('ai-status').textContent=message;};

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
      el('ai-mode').textContent=data.mode==='deepseek'?'DeepSeek 智能组卷':'本地知识点索引选题';
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
  function refreshKnowledge() {
    if(!state.index)return;
    const filters={topic:el('ai-topic').value,edition:el('ai-edition').value,paper:el('ai-paper').value};
    const available=engine.availableConcepts(state.index,questions,filters);
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
    state.agentNonce++;state.agentController?.abort();state.agentController=null;state.generating=false;
    el('ai-cancel').hidden=true;busy(false);
    if(message)status(message);
  }
  el('ai-cancel').addEventListener('click',()=>cancelGeneration('本次组卷已取消，可重新生成。'));
  el('ai-dialog').addEventListener('close',()=>{
    cancelGeneration('');state.exportNonce++;
    const exporting=!!state.worker;
    state.worker?.terminate();state.worker=null;busy(false);
    if(exporting)el('ai-export-status').textContent='PDF 生成已取消，可重新下载。';
    el('ai-launch').focus({preventScroll:true});
  });
  for(const id of ['ai-topic','ai-edition'])el(id).addEventListener('change',refreshPapers);
  el('ai-form').addEventListener('submit',event=>{event.preventDefault();generate();});

  function showCandidates(concepts,message) {
    state.items=[];state.pool=[];el('ai-result').hidden=true;status(message);
    el('ai-candidates').innerHTML=concepts.map(c=>`<button type="button" data-ai-concept="${safe(c.id)}">${safe(c.name)}</button>`).join('');
  }
  function validatePaper(data,index,filters,count) {
    const concept=index.concepts.find(c=>c.id===data?.concept?.id);
    if(!concept||concept.name!==data.concept.name||data.coverage?.total!==questions.length||data.coverage?.analyzed!==index.entries.length)throw new Error('后端与网页题库不一致，请刷新后重试。');
    const allowed=new Map(engine.candidates(concept.id,index,questions,filters).map(item=>[item.id,item]));
    const validateList=list=>{
      if(!Array.isArray(list)||new Set(list.map(item=>item?.id)).size!==list.length)throw new Error('组卷结果格式无效，请重试。');
      return list.map(item=>{
        const source=allowed.get(item.id);
        if(!source||!Array.isArray(item.links)||!item.links.length)throw new Error('组卷结果超出了所选题库范围，请重试。');
        const links=item.links.map(link=>source.links.find(l=>JSON.stringify(l)===JSON.stringify(link)));
        if(links.some(l=>!l))throw new Error('选题关联未通过证据校验，请重试。');
        return {...source,links};
      });
    };
    const pool=validateList(data.pool),items=validateList(data.items);
    if(items.length>count||items.some(item=>!pool.some(p=>p.id===item.id)))throw new Error('组卷题量或候选范围无效，请重试。');
    return {concept,pool,items};
  }
  async function generate(conceptId) {
    if(state.worker||state.generating||!el('ai-form').reportValidity())return;
    const query=el('ai-query').value.trim(),count=Number(el('ai-count').value);
    const filters={topic:el('ai-topic').value,edition:el('ai-edition').value,paper:el('ai-paper').value};
    const nonce=++state.agentNonce,controller=new AbortController();
    state.agentController=controller;state.generating=true;busy(true);el('ai-cancel').hidden=false;
    el('ai-candidates').replaceChildren();el('ai-result').hidden=true;state.items=[];state.pool=[];status('正在匹配知识点…');
    let timer;
    try {
      const [config,index]=await Promise.all([loadAgentConfig(),loadIndex()]);
      if(nonce!==state.agentNonce)return;
      if(!index.entries.length){status('题库的知识点分析尚未完成，请稍后再试。');return;}
      state.count=count;
      if(config.mode==='local') {
        const resolved=conceptId?{kind:'exact',concepts:index.concepts.filter(c=>c.id===conceptId)}:engine.resolve(query,index.concepts);
        if(resolved.kind!=='exact'||!resolved.concepts.length){showCandidates(resolved.concepts,resolved.concepts.length?'请选择你想练习的知识点，再生成试卷。':'未识别到这个知识点，请更换名称或使用更具体的表述。');return;}
        state.concept=resolved.concepts[0];
        state.pool=engine.candidates(state.concept.id,index,questions,filters);state.items=engine.choose(state.pool,count);
      } else {
        status('DeepSeek 正在理解需求并选择题目，首次唤醒服务可能需要稍候…');
        timer=setTimeout(()=>controller.abort('timeout'),180000);
        let response;
        try {
          response=await fetch(`${config.backendUrl}/api/compose`,{method:'POST',headers:{'Content-Type':'application/json'},
            body:JSON.stringify({query,count,filters,numberingVersion,...(conceptId?{conceptId}:{})}),signal:controller.signal});
        } catch(error){if(controller.signal.aborted)throw error;throw new Error('暂时无法连接智能组卷服务，请稍后重试。');}
        let data;
        try{data=await response.json();}catch{throw new Error('组卷服务暂时未就绪，请稍后重试。');}
        if(nonce!==state.agentNonce)return;
        if(!response.ok)throw new Error(typeof data?.error==='string'?data.error:'智能组卷失败，请稍后重试。');
        if(['ambiguous','unknown'].includes(data.kind)){
          if(!Array.isArray(data.concepts)||data.concepts.length>12||data.concepts.some(c=>!index.concepts.some(i=>i.id===c.id&&i.name===c.name)))throw new Error('知识点候选校验失败，请重试。');
          showCandidates(data.concepts,data.kind==='ambiguous'?'DeepSeek 找到了几个可能的知识点，请选择你想练习的一个。':'当前已审核索引中未找到对应知识点，请换一种表述。');return;
        }
        if(data.kind!=='paper')throw new Error('组卷结果格式无效，请重试。');
        Object.assign(state,validatePaper(data,index,filters,count));
      }
      if(nonce!==state.agentNonce)return;
      el('ai-export-status').textContent='';render();
    } catch(error){
      if(nonce!==state.agentNonce)return;
      state.items=[];state.pool=[];el('ai-result').hidden=true;
      status(controller.signal.aborted?'等待智能组卷服务超时，请稍后重试。':error.message||'组卷失败，请重试。');
    } finally {
      clearTimeout(timer);
      if(nonce===state.agentNonce){state.agentController=null;state.generating=false;el('ai-cancel').hidden=true;busy(false);}
    }
  }
  el('ai-candidates').addEventListener('click',event=>{
    const button=event.target.closest('[data-ai-concept]');
    const concept=button&&state.index?.concepts.find(c=>c.id===button.dataset.aiConcept);
    if(concept){el('ai-query').value=concept.name;generate(concept.id);}
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
  function render() {
    const items=state.items;
    el('ai-result').hidden=!items.length;
    if(!items.length){status(state.pool.length?'本卷已清空。点击“生成练习卷”可重新选题。':'当前筛选范围内没有可用的相关题目，请放宽来源范围或更换知识点。');return;}
    el('ai-result-title').textContent=`${state.concept.name} · 专题练习`;
    el('ai-result-count').textContent=`本卷 ${items.length} 道完整大题 · 范围内已确认相关 ${state.pool.length} 道 · 保留专题编号与来源`;
    status(items.length<state.count?`目标 ${state.count} 道，当前保留 ${items.length} 道。${state.pool.length<state.count?'相关题量不足，已按实际题量组卷。':'可重新组卷恢复目标题量。'}`:'');
    el('ai-items').innerHTML=items.map((item,i)=>{
      const q=byId.get(item.id);
      return `<article class="ai-item" data-ai-id="${safe(q.id)}"><div class="ai-item-top"><h4>练习第 ${i+1} 题　${safe(q.topic)} · 专题第 ${numbers[q.id]} 题</h4><div class="ai-item-controls"><button type="button" data-ai-replace="${safe(q.id)}"${state.pool.length<=items.length?' disabled':''}>换一题</button><button type="button" data-ai-remove="${safe(q.id)}">删除</button></div></div><p class="ai-origin">${safe(origin(q))}</p><div class="q-body">${lazyFigures(presentation[q.id].body)}</div><details class="answers"><summary><span>查看答案与关联说明</span></summary>${association(item)}<div class="answer-content">${lazyFigures(presentation[q.id].answer)}</div></details></article>`;
    }).join('');
  }
  el('ai-items').addEventListener('click',event=>{
    if(state.worker)return;
    const remove=event.target.closest('[data-ai-remove]'),replace=event.target.closest('[data-ai-replace]');
    const anchor=(remove||replace)?.closest('.ai-item');
    const y=anchor?.getBoundingClientRect().top;
    if(remove){state.items=state.items.filter(q=>q.id!==remove.dataset.aiRemove);render();}
    if(replace){
      const next=engine.choose(state.pool,1,state.items.map(q=>q.id))[0];
      if(!next){el('ai-export-status').textContent='没有其他符合当前条件的题目可替换。';return;}
      state.items=state.items.map(q=>q.id===replace.dataset.aiReplace?next:q);render();
      const target=el('ai-items').querySelector(`[data-ai-id="${CSS.escape(next.id)}"]`);
      if(target && y!=null)el('ai-dialog').querySelector('.ai-scroll').scrollTop+=target.getBoundingClientRect().top-y;
      target?.querySelector('[data-ai-replace]')?.focus({preventScroll:true});
    }
  });
  el('ai-reroll').addEventListener('click',()=>generate());
  function busy(value) {
    el('ai-form').querySelectorAll('input,select,button').forEach(input=>{input.disabled=value;});
    el('ai-result').querySelectorAll('button').forEach(button=>{button.disabled=value;});
    el('ai-dialog').querySelectorAll('[data-ai-keyword]').forEach(button=>{button.disabled=value;});
    if(!value) el('ai-items').querySelectorAll('[data-ai-replace]').forEach(button=>{button.disabled=state.pool.length<=state.items.length;});
  }
  function canvasNote(lines,heading=false) {
    const canvas=document.createElement('canvas'),ctx=canvas.getContext('2d');
    const width=1000,padding=24,size=heading?27:23;
    ctx.font=`${size}px "Microsoft YaHei",sans-serif`;
    const wrapped=[];
    for(const line of lines) {
      let part='';
      for(const char of line){if(ctx.measureText(part+char).width>width-2*padding){wrapped.push(part);part='';}part+=char;}
      wrapped.push(part);
    }
    const height=padding*2+wrapped.length*(size+12);
    canvas.width=width;canvas.height=height;
    ctx.fillStyle='#fff';ctx.fillRect(0,0,width,height);ctx.fillStyle='#252b29';ctx.font=`${size}px "Microsoft YaHei",sans-serif`;
    wrapped.forEach((line,i)=>ctx.fillText(line,padding,padding+size+i*(size+12)));
    const raw=atob(canvas.toDataURL('image/png').split(',')[1]);
    return {bytes:Uint8Array.from(raw,c=>c.charCodeAt(0)),width,height};
  }
  async function download(kind) {
    if(state.worker || !state.items.length)return;
    if(location.protocol==='file:'){el('ai-export-status').textContent=localPreviewMessage;return;}
    const snapshot=state.items.slice(),name=state.concept.name;
    const nonce=++state.exportNonce;
    busy(true);el('ai-export-status').textContent='正在准备 PDF…';
    try {
      await document.fonts.ready;
      if(nonce!==state.exportNonce)return;
      // Only our added commentary is rasterized; source answers remain vector pages.
      const header=canvasNote([`${name} · ${kind==='answers'?'参考答案':'专题练习'}`,`共 ${snapshot.length} 道完整大题，保留原专题编号与来源。`],true);
      const items=snapshot.map((item,i)=>({id:item.id,slug:slugByTopic[byId.get(item.id).topic],annotation:kind==='answers'?canvasNote([`练习第 ${i+1} 题 · 知识点关联说明`,...labels(item),'关联说明由 AI 分析；下方为原卷参考答案。']):null}));
      state.worker=new Worker('pdf-worker.js?v=clean-vector-v1');
      const worker=state.worker;
      const fail=message=>{if(state.worker!==worker)return;worker.terminate();state.worker=null;busy(false);el('ai-export-status').textContent=message;};
      state.worker.onerror=()=>fail('PDF 工具加载失败，请检查网络后重新下载。');
      state.worker.onmessage=({data})=>{
        if(state.worker!==worker || nonce!==state.exportNonce)return;
        if(data.status)el('ai-export-status').textContent=data.status;
        else if(data.error)fail(data.error);
        else if(data.bytes){
          const url=URL.createObjectURL(new Blob([data.bytes],{type:'application/pdf'})),link=document.createElement('a');
          link.href=url;link.download=`Chemy-${name.replace(/[\\/:*?"<>|]/g,'_')}-${kind==='answers'?'答案':'题目'}.pdf`;
          document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),60000);
          state.worker.terminate();state.worker=null;busy(false);el('ai-export-status').textContent='PDF 已生成，下载已开始。';
        }
      };
      state.worker.postMessage({items,version:pdfVersion,kind,title:`Chemy · ${name} · ${kind==='answers'?'答案':'题目'}`,paperHeader:header});
    }catch(_){if(nonce!==state.exportNonce)return;state.worker?.terminate();state.worker=null;busy(false);el('ai-export-status').textContent='PDF 生成失败，请重试下载。';}
  }
  document.querySelectorAll('[data-ai-export]').forEach(button=>button.addEventListener('click',()=>download(button.dataset.aiExport)));
  async function printPaper(kind) {
    if(state.worker || !state.items.length)return;
    const target=el('ai-print');
    target.innerHTML=`<h1>${safe(state.concept.name)} · ${kind==='answers'?'参考答案':'专题练习'}</h1><p>共 ${state.items.length} 道完整大题，保留原专题编号与来源。</p>`+state.items.map((item,i)=>{
      const q=byId.get(item.id);
      return `<article class="ai-item"><h2>练习第 ${i+1} 题 · ${safe(q.topic)}专题第 ${numbers[q.id]} 题</h2><p class="ai-origin">${safe(origin(q))}</p>${kind==='answers'?association(item):''}<div class="${kind==='answers'?'answer-content':'q-body'}">${presentation[q.id][kind==='answers'?'answer':'body']}</div></article>`;
    }).join('');
    target.insertAdjacentHTML('beforeend','<footer class="ai-print-copyright">题目与参考答案版权归 Chemy 化学奥林匹克团队原命题组所有，仅供学术交流使用。</footer>');
    target.querySelectorAll('img').forEach(img=>{img.loading='eager';});
    try{
      await Promise.all([...target.querySelectorAll('img')].map(img=>img.decode()));await document.fonts.ready;
      document.body.classList.add('ai-printing');window.print();
    }catch(_){el('ai-export-status').textContent='有题图未能加载，请检查网络后重新打印。';}
    finally{document.body.classList.remove('ai-printing');target.replaceChildren();}
  }
  document.querySelectorAll('[data-ai-print]').forEach(button=>button.addEventListener('click',()=>printPaper(button.dataset.aiPrint)));
})();
