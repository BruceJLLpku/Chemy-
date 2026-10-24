// UI lifecycle tests use controlled workers; real PDF contents are tested separately.
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),http=require('http'),assert=require('assert/strict');
const {pathToFileURL}=require('url');
const root=path.resolve(__dirname,'..'),dist=path.join(root,'dist');
const out=path.join(root,'output/ui-recovery'),report={checks:[],errors:[]};
fs.mkdirSync(out,{recursive:true});
const check=(name,value)=>{assert.ok(value,name);report.checks.push(name);console.log('PASS',name);};
const mime={'.html':'text/html','.js':'text/javascript','.json':'application/json','.css':'text/css','.svg':'image/svg+xml','.webp':'image/webp','.png':'image/png'};
const server=http.createServer((req,res)=>{
  const pathname=decodeURIComponent(new URL(req.url,'http://localhost').pathname);
  const target=path.resolve(dist,'.'+pathname+(pathname.endsWith('/')?'index.html':''));
  if(path.relative(dist,target).startsWith('..')){res.writeHead(403).end();return;}
  fs.stat(target,(error,stat)=>{
    if(error||!stat.isFile()){res.writeHead(404).end();return;}
    res.setHeader('Content-Type',mime[path.extname(target)]||'application/octet-stream');
    fs.createReadStream(target).pipe(res);
  });
});
function mockWorkers(){
  window.testWorkers=[];
  window.Worker=class{
    constructor(){if(window.failWorkerStart)throw new Error('worker unavailable');window.testWorkers.push(this);}
    postMessage(data){this.request=structuredClone(data);}
    terminate(){this.terminated=true;}
    emit(data){this.onmessage?.({data});}
    fail(){this.onerror?.({message:'worker unavailable'});}
  };
}
async function nextWorker(page,button){
  const count=await page.evaluate(()=>testWorkers.length);
  await page.locator(button).click();
  await page.waitForFunction(n=>testWorkers.length===n+1,count);
}
(async()=>{
  await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));
  const base=`http://127.0.0.1:${server.address().port}/`;
  const options={headless:true};
  if(process.env.CHEMY_BROWSER_EXECUTABLE)options.executablePath=process.env.CHEMY_BROWSER_EXECUTABLE;
  else options.channel='msedge';
  const browser=await chromium.launch(options);
  try{
    for(const [resource,hash,width] of [['presentation.json','',390],['questions.json','#analysis',390],['numbering.json','?question=chemy39-1-6#electrochemistry',390],['presentation.json','#analysis',1440]]){
      const page=await browser.newPage({viewport:{width,height:844}});
      page.on('pageerror',error=>report.errors.push(error.message));
      const pattern=`**/${resource}*`;
      await page.route(pattern,route=>route.fulfill({status:503,body:'temporarily unavailable'}));
      await page.goto(base+hash);
      await page.locator('#library-notice').waitFor();
      check(`${width}px ${resource}: failure and retry are visible`,await page.locator('#retry-load').isVisible()&&await page.locator('#library-notice').evaluate(el=>{const r=el.getBoundingClientRect();return r.top>=0&&r.bottom<=innerHeight;}));
      check(`${width}px ${resource}: loading state ends`,await page.locator('#questions').getAttribute('aria-busy')==='false');
      await page.locator('#retry-load').click();
      await page.waitForFunction(()=>!libraryLoading);
      check(`${width}px ${resource}: repeated failure remains retryable`,await page.locator('#retry-load').isEnabled());
      if(width===390&&resource==='presentation.json')await page.screenshot({path:path.join(out,'mobile-load-error.png')});
      await page.unroute(pattern);
      let release,requestCount=0;
      const pending=new Promise(resolve=>{release=resolve;});
      await page.route(pattern,async route=>{requestCount++;await pending;await route.continue();});
      await page.locator('#retry-load').click();
      check(`${width}px ${resource}: retry is locked while loading`,await page.locator('#retry-load').isDisabled());
      await page.evaluate(()=>{loadLibrary();loadLibrary();});
      release();
      await page.waitForFunction(()=>ready);
      check(`${width}px ${resource}: one retry request restores the requested view`,requestCount===1&&await page.locator('#library-notice').isHidden()&&new URL(page.url()).hash===new URL(base+hash).hash);
      if(hash.includes('question='))check('Retry restores deep-linked question',await page.locator('#chemy39-1-6').count()===1&&new URL(page.url()).searchParams.get('question')==='chemy39-1-6');
      await page.close();
    }
    const page=await browser.newPage({viewport:{width:390,height:844},acceptDownloads:true});
    page.on('pageerror',error=>report.errors.push(error.message));
    await page.addInitScript(mockWorkers);
    await page.goto(pathToFileURL(path.join(dist,'index.html')).href);
    check('file URL shows local HTTP instructions without an endless retry',await page.locator('#local-preview-help').isVisible()&&await page.locator('#retry-load').isHidden()&&(await page.locator('#local-preview-help').textContent()).includes('python -m http.server'));
    check('Local instructions fit the phone width',await page.locator('#library-notice').evaluate(el=>el.scrollWidth<=el.clientWidth));
    await page.screenshot({path:path.join(out,'local-file-help.png')});
    await page.evaluate(()=>{byId.set('test',{id:'test',topic:topics[0],title:'Test',paper:1,number:1});numbers.test=1;openExport(['test']);startExport();});
    check('Single and selected file exports explain how to run locally',await page.locator('#export-start').isDisabled()&&await page.locator('#export-answers').isDisabled()&&(await page.locator('#export-status').textContent()).includes('http://127.0.0.1:8765/')&&await page.evaluate(()=>testWorkers.length===0));
    await page.goto(base+'#analysis');await page.waitForFunction(()=>ready);
    await page.evaluate(()=>openExport(byTopic.get('分析化学').slice(0,2).map(q=>q.id)));
    await nextWorker(page,'#export-answers');
    check('Answer export locks both version buttons and snapshots two questions',await page.locator('#export-start').isDisabled()&&await page.locator('#export-answers').isDisabled()&&await page.evaluate(()=>testWorkers.at(-1).request.kind==='answers'&&testWorkers.at(-1).request.items.length===2));
    await page.locator('#export-cancel').click();
    check('Cancel terminates the worker and releases export state',await page.evaluate(()=>testWorkers.at(-1).terminated&&exportWorker===null&&!exportBusy));
    await page.evaluate(()=>openExport(byTopic.get('分析化学').slice(0,1).map(q=>q.id)));
    await nextWorker(page,'#export-start');
    await page.evaluate(()=>{testWorkers[0].emit({status:'old progress'});testWorkers[0].fail();testWorkers[0].emit({bytes:new TextEncoder().encode('%PDF-1.7\n%%EOF')});});
    check('Cancelled worker cannot alter a new export',await page.evaluate(()=>exportBusy&&exportWorker===testWorkers.at(-1))&&(await page.locator('#export-status').textContent()).includes('正在准备题目'));
    await page.evaluate(()=>testWorkers.at(-1).emit({error:'测试网络故障，请重试。'}));
    check('Worker failure restores both buttons',await page.locator('#export-start').isEnabled()&&await page.locator('#export-answers').isEnabled());
    await nextWorker(page,'#export-answers');
    const downloadEvent=page.waitForEvent('download');
    await page.evaluate(()=>{exportItems=[];testWorkers.at(-1).emit({bytes:new TextEncoder().encode('%PDF-1.7\n%%EOF')});});
    const download=await downloadEvent;
    check('Retry uses the chosen version and captured filename',download.suggestedFilename().includes('分析化学-第1题-答案')&&await page.locator('#export-start').isEnabled()&&await page.locator('#export-answers').isEnabled());
    await page.locator('#export-close').click();
    await page.evaluate(()=>{openExport(byTopic.get('分析化学').slice(0,1).map(q=>q.id));window.failWorkerStart=true;});
    await page.locator('#export-start').click();
    check('Worker startup failure exposes a usable retry',await page.locator('#export-start').isEnabled()&&(await page.locator('#export-start').textContent()).includes('重试'));
    await page.evaluate(()=>{window.failWorkerStart=false;});
    await nextWorker(page,'#export-start');await page.keyboard.press('Escape');
    check('Escape cancels PDF generation',await page.locator('#export-dialog').isHidden()&&await page.evaluate(()=>testWorkers.at(-1).terminated&&!exportBusy));
    await page.locator('#ai-launch').click();
    await page.locator('#ai-query').fill('Aldol');await page.locator('#ai-generate').click();
    await page.locator('#ai-items .ai-item').first().waitFor();
    await nextWorker(page,'[data-ai-export="answers"]');
    const oldAi=await page.evaluate(()=>testWorkers.length-1);
    await page.locator('#ai-close').click();await page.locator('#ai-launch').click();
    await nextWorker(page,'[data-ai-export="questions"]');
    await page.evaluate(i=>{testWorkers[i].fail();testWorkers[i].emit({status:'old AI progress'});},oldAi);
    check('AI cancelled worker cannot unlock or overwrite the next export',await page.locator('[data-ai-export="questions"]').isDisabled()&&(await page.locator('#ai-export-status').textContent()).includes('正在准备'));
    await page.evaluate(()=>testWorkers.at(-1).fail());
    check('AI export failure enables both version buttons',await page.locator('[data-ai-export="questions"]').isEnabled()&&await page.locator('[data-ai-export="answers"]').isEnabled());
    await page.close();
    check('No unexpected browser runtime errors',report.errors.length===0);
  }finally{await browser.close();server.close();fs.writeFileSync(path.join(out,'report.json'),JSON.stringify(report,null,2));}
})().catch(error=>{console.error(error);server.close();process.exitCode=1;});
