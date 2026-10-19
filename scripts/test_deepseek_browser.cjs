const {chromium}=require('playwright');
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict');
const {pathToFileURL}=require('node:url');
const root=path.resolve(__dirname,'..'),output=path.join(root,'output','deepseek-agent');
fs.mkdirSync(output,{recursive:true});
const read=name=>JSON.parse(fs.readFileSync(path.join(root,'dist',name),'utf8'));
const bank=read('questions.json'),full=read('knowledge-index.json'),numbering=read('numbering.json');
const seeds=new Set(['chemy35-3-10','chemy35-10-8','chemy36-22-9','chemy36-24-9']);
const index={...full,entries:full.entries.filter(e=>seeds.has(e.id)),analyzedQuestions:4,complete:false};
const concept=index.concepts.find(c=>c.name==='羟醛缩合');
const checks=[],errors=[];
function check(name,value){assert.ok(value,name);checks.push(name);console.log('PASS',name);}

(async()=>{
  const {createAgent}=await import(pathToFileURL(path.join(root,'server','agent.mjs')));
  let scenario='normal',upstreamCalls=0,releaseDelayed,delayedStarted;
  const reply=data=>new Response(JSON.stringify({choices:[{finish_reason:'stop',message:{content:JSON.stringify(data)}}]}));
  const agent=createAgent({bank,index,numbering,env:{DEEPSEEK_API_KEY:'mock-browser-key'},fetchImpl:async(_url,init)=>{
    upstreamCalls++;
    if(scenario==='auth')return new Response('mock-browser-key',{status:401});
    const data=JSON.parse(JSON.parse(init.body).messages[1].content);
    if(data.concepts)return reply(scenario==='ambiguous'?{kind:'ambiguous',conceptIds:[concept.id]}:{kind:'resolved',conceptIds:[concept.id]});
    return reply({selected:data.candidates.slice(0,Math.min(data.count,data.candidates.length)).map(c=>({id:c.id,linkIndices:[0]}))});
  }});
  await new Promise(resolve=>agent.server.listen(0,'127.0.0.1',resolve));
  const base=`http://127.0.0.1:${agent.server.address().port}`;
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  const context=await browser.newContext({viewport:{width:1440,height:1000},acceptDownloads:true});
  await context.route('**/knowledge-index.json*',route=>route.fulfill({json:index}));
  await context.route('**/api/compose',async route=>{
    const current=scenario;
    try{
      const data=route.request().postDataJSON();
      let result;
      try{result=await agent.compose(data);}catch(error){await route.fulfill({status:error.status||500,json:{code:error.code,error:error.message}});return;}
      if(current==='forged')result.items[0].id='not-in-the-bank';
      if(current==='delayed'){
        delayedStarted?.();
        await new Promise(resolve=>{releaseDelayed=resolve;});
      }
      await route.fulfill({json:result});
    }catch(error){if(!/closed|cancel|abort|invalid interception/i.test(error.message))errors.push(error.message);}
  });
  const page=await context.newPage();page.on('pageerror',error=>errors.push(error.message));
  const generate=async()=>{await page.locator('#ai-generate').click();await page.waitForFunction(()=>!document.getElementById('ai-generate').disabled);};
  try{
    await page.goto(base);await page.waitForFunction(()=>typeof ready!=='undefined'&&ready);
    await page.locator('#ai-launch').click();
    await page.locator('#ai-mode').filter({hasText:'DeepSeek'}).waitFor();
    await page.locator('#ai-query').fill('想练习醛醇缩合，帮我挑几道竞赛原题');
    await generate();
    check('Browser request reaches Agent planning and selection',upstreamCalls===2);
    check('A five-question request returns the available four original questions',await page.locator('#ai-items .ai-item').count()===4);
    check('Coverage accurately reports four of 1933 in the isolated fixture',/4.*1933/.test(await page.locator('#ai-coverage').textContent()));
    check('Shortage is disclosed',(await page.locator('#ai-status').textContent()).includes('不足'));
    check('Original answers and association text stay collapsed',await page.locator('#ai-items .answers[open]').count()===0&&await page.locator('#ai-items .ai-association').first().isHidden());
    check('Complete original question bodies are preserved',await page.evaluate(()=>[...document.querySelectorAll('[data-ai-id]')].every(a=>{
      const expected=document.createElement('div');expected.innerHTML=presentation[a.dataset.aiId].body;
      const actual=a.querySelector('.q-body').cloneNode(true);
      for(const tree of [expected,actual])tree.querySelectorAll('img').forEach(img=>{img.removeAttribute('loading');img.removeAttribute('decoding');});
      return expected.innerHTML===actual.innerHTML;
    })));
    await page.screenshot({path:path.join(output,'desktop.png'),fullPage:false});
    await page.locator('.ai-advanced summary').click();
    await page.locator('#ai-count').fill('1');await generate();
    const before=await page.locator('[data-ai-id]').getAttribute('data-ai-id'),calls=upstreamCalls;
    await page.locator('[data-ai-replace]').first().click();
    check('Replacement chooses a different audited candidate without another API call',await page.locator('[data-ai-id]').getAttribute('data-ai-id')!==before&&upstreamCalls===calls);
    await page.locator('[data-ai-remove]').first().click();
    check('Removing the last question clears the result',await page.locator('#ai-result').isHidden());
    await generate();const rerollCalls=upstreamCalls;await page.locator('#ai-reroll').click();await page.waitForFunction(()=>!document.getElementById('ai-generate').disabled);
    check('Reroll asks DeepSeek again',upstreamCalls===rerollCalls+2);
    await page.locator('#ai-edition').selectOption('36');await page.locator('#ai-paper').selectOption('36-24');await generate();
    check('Source filters survive the full browser-to-Agent flow',await page.locator('[data-ai-id]').getAttribute('data-ai-id')==='chemy36-24-9');
    await page.locator('#ai-edition').selectOption('all');await page.locator('#ai-paper').selectOption('all');
    scenario='ambiguous';await page.locator('#ai-query').fill('缩合');await generate();
    check('Ambiguous requests show explicit concept choices',await page.locator('[data-ai-concept]').count()===1&&await page.locator('#ai-result').isHidden());
    scenario='normal';const confirmationCalls=upstreamCalls;
    await page.locator('[data-ai-concept]').click();await page.waitForFunction(()=>!document.getElementById('ai-generate').disabled);
    check('Confirmed concept skips replanning but still calls model selection',upstreamCalls===confirmationCalls+1&&await page.locator('[data-ai-id]').count()===1);
    scenario='auth';await generate();
    check('Upstream authentication failure stays in DeepSeek mode and exposes no key',await page.locator('#ai-result').isHidden()&&(await page.locator('#ai-status').textContent()).includes('鉴权')&&!(await page.content()).includes('mock-browser-key'));
    scenario='forged';await generate();
    check('Browser independently rejects an unknown question ID',await page.locator('#ai-result').isHidden()&&(await page.locator('#ai-status').textContent()).includes('范围'));
    scenario='delayed';const started=new Promise(resolve=>{delayedStarted=resolve;});
    await page.locator('#ai-generate').click();await started;
    check('Pending generation disables duplicate submit',await page.locator('#ai-generate').isDisabled());
    await page.locator('#ai-cancel').click();
    check('Cancel restores controls immediately',!(await page.locator('#ai-generate').isDisabled())&&await page.locator('#ai-cancel').isHidden());
    scenario='normal';await generate();releaseDelayed();
    check('A new generation succeeds after cancellation',await page.locator('[data-ai-id]').count()===1);
    scenario='delayed';const closedStarted=new Promise(resolve=>{delayedStarted=resolve;});
    await page.locator('#ai-generate').click();await closedStarted;await page.locator('#ai-close').click();releaseDelayed();
    await page.locator('#ai-launch').click();
    check('Close cancels pending work and reopens with usable controls',!(await page.locator('#ai-generate').isDisabled()));
    scenario='normal';await generate();
    const [download]=await Promise.all([page.waitForEvent('download',{timeout:120000}),page.locator('[data-ai-export="questions"]').click()]);
    await download.saveAs(path.join(output,'agent-question.pdf'));
    check('DeepSeek-selected original questions still export a real PDF',fs.readFileSync(path.join(output,'agent-question.pdf')).subarray(0,4).toString()==='%PDF');
    await page.setViewportSize({width:390,height:844});await page.screenshot({path:path.join(output,'mobile.png')});
    check('Mobile dialog remains inside the viewport',await page.locator('#ai-dialog').evaluate(el=>el.getBoundingClientRect().width<=window.innerWidth));
    check('No uncaught browser errors',errors.length===0);
  }finally{
    releaseDelayed?.();fs.writeFileSync(path.join(output,'browser-report.json'),JSON.stringify({checks,errors},null,2));
    await browser.close();agent.server.closeAllConnections();await new Promise(resolve=>agent.server.close(resolve));
  }
})().catch(error=>{console.error(error);process.exitCode=1;});
