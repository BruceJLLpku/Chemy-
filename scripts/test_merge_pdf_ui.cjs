// Exercise the merged AI export lifecycle, including upstream Word/print exports.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../dist/ai-paper.js'),'utf8');

function between(start,end){
  const a=source.indexOf(start),b=source.indexOf(end,a);
  assert.ok(a>=0&&b>a,'Missing lifecycle section '+start);
  return source.slice(a,b);
}
const code=[
  between("el('ai-dialog').addEventListener('close',()=>{","  for(const id of ['ai-topic','ai-edition'])"),
  between('function currentLecture()',"  function addTurn("),
  between('async function download(kind)',"  document.querySelectorAll('[data-ai-export]')"),
  between("document.querySelectorAll('[data-ai-word]')",'  async function printPaper(kind)'),
  between('async function printPaper(kind)',"  document.querySelectorAll('[data-ai-print]')"),
].join('\n');
const deferred=()=>{let resolve;const promise=new Promise(r=>{resolve=r;});return {promise,resolve};};

function harness(protocol='http:'){
  const elements=new Map(),workers=[],downloads=[],saves=[],busyChanges=[];
  const wordButtons=['questions','answers'].map(kind=>({dataset:{aiWord:kind},addEventListener(type,handler){this.handler=handler;}}));
  const classes=new Set();
  const element=id=>{
    if(!elements.has(id))elements.set(id,{
      textContent:'',innerHTML:'',handlers:{},focus(){},replaceChildren(){this.innerHTML='';},
      addEventListener(type,handler){this.handlers[type]=handler;},insertAdjacentHTML(position,text){this.innerHTML+=text;},
      querySelectorAll(){return [];},
    });
    return elements.get(id);
  };
  const h={elements,workers,downloads,saves,busyChanges,wordButtons,element,classes};
  const state={items:[{id:'first',links:[]}],concept:{id:'chemistry',name:'化学测试'},index:{entries:[{id:'first'}]},introduction:'知识介绍正文',exportNonce:0,exporting:false,generating:false,worker:null};
  const context=vm.createContext({
    state,location:{protocol},localPreviewMessage:'Open http://127.0.0.1:8765/',el:element,
    engine:{availableConcepts:()=>[{id:'chemistry',name:'化学测试'}]},questions:[{id:'first'}],
    byId:new Map([['first',{id:'first',topic:'晶体化学'}]]),slugByTopic:{'晶体化学':'crystal'},
    presentation:{first:{body:'<p>原题</p>',answer:'<p>原答案</p>'}},numbers:{first:1},
    pdfVersion:'fixture',safe:String,labels:()=>['关联说明'],origin:()=> '原题来源',association:()=>'<aside>关联说明</aside>',introductionHtml:text=>'<p>'+text+'</p>',
    busy(value){h.busy=value;busyChanges.push(value);},cancelGeneration(){state.generating=false;},
    canvasNote:lines=>({bytes:new Uint8Array([1]),lines}),
    canvasNotes:lines=>[{bytes:new Uint8Array([2]),lines}],
    Worker:class{
      constructor(url){if(h.failStartup)throw Error('startup failed');this.url=url;workers.push(this);}
      postMessage(request){this.request=request;}
      terminate(){this.terminated=true;}
      emit(data){this.onmessage?.({data});}
      fail(){this.onerror?.({message:'old worker failed'});}
    },
    document:{fonts:{ready:Promise.resolve()},
      querySelectorAll(selector){assert.equal(selector,'[data-ai-word]');return wordButtons;},
      createElement(){return {click(){downloads.push(this.download);},remove(){}};},
      body:{append(){},classList:{add(name){classes.add(name);},remove(name){classes.delete(name);}}},
    },
    window:{ChemyLecture:{blocks:text=>[{kind:'paragraph',html:text}]},
      ChemyAccount:{savePaper(ids,title){saves.push({ids:Array.from(ids),title});}},
      ChemyWord:{build:async()=>new Blob(['word'])},print(){h.prints=(h.prints||0)+1;}},
    Blob,Uint8Array,setTimeout(){},
    URL:{createObjectURL:()=> 'blob:fixture',revokeObjectURL(){}},
  });
  vm.runInContext(code,context,{filename:'merged-ai-export-lifecycle.js'});
  return Object.assign(h,{context,state,close:()=>element('ai-dialog').handlers.close()});
}

(async()=>{
  {
    const h=harness('file:');await h.context.download('questions');
    assert.equal(h.workers.length,0);assert.equal(h.state.exporting,false);
    assert.match(h.element('ai-export-status').textContent,/127\.0\.0\.1/);
  }
  {
    const h=harness(),fonts=deferred();h.context.document.fonts.ready=fonts.promise;
    const preparing=h.context.download('questions');
    assert.equal(h.state.exporting,true);assert.equal(h.workers.length,0);
    await h.context.download('answers');await h.wordButtons[0].handler();
    assert.equal(h.workers.length,0,'Preparation must lock both PDF and Word starts');
    h.close();fonts.resolve();await preparing;
    assert.equal(h.workers.length,0,'Closing during preparation must not start a late worker');
    assert.equal(h.state.exporting,false);
  }
  {
    const h=harness(),fonts=deferred();h.context.document.fonts.ready=fonts.promise;
    const preparing=h.context.download('questions');
    h.state.introduction='更新后的讲义';h.state.items=[{id:'second',links:[]}];
    fonts.resolve();await preparing;
    assert.equal(h.workers[0].request.items[0].id,'first');
    assert.match(JSON.stringify(h.workers[0].request.paperIntro),/知识介绍正文/);
    assert.ok(!JSON.stringify(h.workers[0].request.paperIntro).includes('更新后的讲义'),
      'Font preparation must not mix a newer lecture into the original paper snapshot');
  }
  {
    const h=harness();h.state.introduction=undefined;
    await h.context.download('questions');
    assert.match(JSON.stringify(h.workers[0].request.paperIntro),/本卷知识点/);
    assert.match(JSON.stringify(h.workers[0].request.paperIntro),/化学测试/);
    h.close();h.state.introduction='';await h.context.download('questions');
    assert.equal(h.workers[1].request.paperIntro.length,0,
      'An explicitly removed lecture must not be replaced by the local knowledge summary');
  }
  {
    const h=harness();await h.context.download('questions');
    const old=h.workers[0];assert.match(old.url,/clean-vector-packed-v2/);
    assert.equal(old.request.paperIntro.length,1,'Question PDF receives the upstream lecture');
    assert.ok(old.request.paperHeader?.bytes);assert.equal(old.request.items[0].annotation,null);
    h.close();await h.context.download('answers');const active=h.workers[1];
    old.fail();old.emit({status:'late progress'});old.emit({bytes:new Uint8Array([37,80,68,70])});
    assert.equal(h.state.worker,active);assert.equal(h.state.exporting,true);assert.equal(h.busy,true);
    assert.equal(h.downloads.length,0);assert.ok(!active.terminated);
    assert.equal(active.request.paperIntro.length,0,'Answer PDF must not receive the question lecture');
    assert.ok(active.request.items[0].annotation?.bytes);
    active.fail();assert.equal(h.state.exporting,false);assert.equal(h.state.worker,null);assert.equal(h.busy,false);
    await h.context.download('answers');h.workers[2].emit({bytes:new Uint8Array([37,80,68,70])});
    assert.equal(h.downloads.length,1);assert.match(h.downloads[0],/答案\.pdf$/);
    assert.deepEqual(h.saves,[{ids:['first'],title:'化学测试 · 专题练习'}]);
  }
  {
    const h=harness();h.failStartup=true;await h.context.download('questions');
    assert.equal(h.state.exporting,false);assert.equal(h.busy,false);
    assert.match(h.element('ai-export-status').textContent,/重试/);
  }
  {
    const h=harness(),word=deferred();h.context.window.ChemyWord.build=()=>word.promise;
    const old=h.wordButtons[0].handler();assert.equal(h.state.exporting,true);
    h.close();await h.context.download('answers');const active=h.state.worker;
    word.resolve(new Blob(['word']));await old;
    assert.equal(h.downloads.length,0,'A cancelled Word job must not download after reopening');
    assert.equal(h.state.worker,active);assert.equal(h.state.exporting,true);assert.equal(h.busy,true);
  }
  {
    const h=harness(),word=deferred();let documentInput;
    h.context.window.ChemyWord.build=input=>{documentInput=input;return word.promise;};
    const exporting=h.wordButtons[0].handler();
    h.state.items=[{id:'second',links:[]}];h.state.introduction='更新后的讲义';
    word.resolve(new Blob(['word']));await exporting;
    assert.equal(documentInput.items.length,1);assert.equal(documentInput.items[0].html,'<p>原题</p>');
    assert.equal(documentInput.introduction,'知识介绍正文');assert.equal(documentInput.introductionTitle,'知识点讲义');
    assert.equal(h.downloads.length,1);assert.match(h.downloads[0],/题目\.docx$/);
    assert.deepEqual(h.saves,[{ids:['first'],title:'化学测试 · 专题练习'}],
      'Word history must describe the exported document even if a favorites refresh changes the active paper');
    assert.equal(h.state.exporting,false);assert.equal(h.busy,false);
  }
  {
    const h=harness(),image=deferred();
    h.element('ai-print').querySelectorAll=()=>[{decode:()=>image.promise}];
    const old=h.context.printPaper('questions');assert.equal(h.state.exporting,true);
    h.close();await h.context.download('answers');const active=h.state.worker;
    image.resolve();await old;
    assert.equal(h.prints||0,0,'A cancelled print must not open the print dialog');
    assert.equal(h.state.worker,active);assert.equal(h.state.exporting,true);assert.equal(h.busy,true);
    assert.equal(h.element('ai-print').innerHTML,'');assert.ok(!h.classes.has('ai-printing'));
  }
  console.log('PASS AI PDF/Word/print mutual exclusion, lecture forwarding and local fallback, stale callbacks, cancelled preparation, failure retry and paper-history snapshots.');
})().catch(error=>{console.error(error);process.exitCode=1;});
