// Browser regressions use real bank content and mocked model replies; no API credits.
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const {chromium}=require('playwright');
const JSZip=require('jszip');
const root=path.resolve(__dirname,'..');
const engine=require('../dist/paper-engine.js');
const load=name=>JSON.parse(fs.readFileSync(path.join(root,'dist',name),'utf8'));
const index=load('knowledge-index.json'),bank=load('questions.json');
const concept=index.concepts.find(c=>c.name==='晶胞计算');
const pool=engine.candidates(concept.id,index,bank);
const introduction='<strong>一、晶胞中的粒子数</strong>\n晶胞中的粒子按共享比例计数。顶点、棱上、面上和体内的粒子，分别计入 1/8、1/4、1/2 和 1。\n\n<i>N</i> = <i>n</i><sub>顶点</sub>/8 + <i>n</i><sub>棱</sub>/4 + <i>n</i><sub>面</sub>/2 + <i>n</i><sub>体内</sub>\n\n<strong>二、晶胞密度</strong>\n先确定每个晶胞所含的化学式单位数，再由晶胞质量和体积求密度。\n\nρ = <i>ZM</i>/(<i>N</i><sub>A</sub><i>V</i>)\n\n<i>Z</i> 为化学式单位数，<i>M</i> 为摩尔质量，<i>V</i> 为晶胞体积。各量采用同一套单位。\n\n<strong>三、配位数与堆积</strong>\n配位数是与指定粒子最近邻的粒子数。先确定最近邻距离，再统计达到该距离的粒子，不能仅按图中可见的粒子计数。';
const fixture={kind:'paper',concept,pool,items:pool.slice(0,5),count:5,scope:{conceptIds:[concept.id],topics:[]},introduction,message:'已选好 5 道题，并整理了卷首知识介绍。可以继续调整难度或题量。'};
const out=path.join(root,'output','workspace-qa');fs.mkdirSync(out,{recursive:true});
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const page=await browser.newPage({viewport:{width:1440,height:1000}}),errors=[];
  page.on('pageerror',e=>errors.push(e.message));
  let next='paper',calls=0;
  await page.route('**/ai-config.json*',r=>r.fulfill({json:{mode:'deepseek',backendUrl:''}}));
  await page.route('**/api/compose',async r=>{
   calls++;
   if(next==='error'){next='paper';return r.fulfill({status:502,json:{error:'测试：连接中断，请重试。'}});}
   if(next==='slow'){await new Promise(resolve=>setTimeout(resolve,1500));next='paper';}
   await r.fulfill({json:fixture}).catch(()=>{});
  });
  await page.goto(process.env.CHEMY_TEST_URL||'http://127.0.0.1:8788/');
  await page.locator('#ai-launch').click();
  await page.locator('[data-ai-prompt]').first().click();
  assert.match(await page.locator('#ai-query').inputValue(),/晶体化学/);
  await page.screenshot({path:path.join(out,'welcome.png')});
  await page.locator('#ai-generate').click();
  await page.locator('#ai-items .ai-item').nth(4).waitFor();
  await page.waitForFunction(()=>!document.getElementById('ai-generate').disabled);
  assert.equal(await page.locator('#ai-paper-intro .ai-lecture-heading').count(),3);
  assert.equal(await page.locator('#ai-paper-intro .ai-lecture-formula').count(),2);
  const typography=await page.evaluate(()=>{
    const style=s=>{const x=getComputedStyle(document.querySelector(s));return [x.fontFamily,x.fontSize,x.lineHeight];};
    return [style('#ai-paper-intro .q-body'),style('.ai-item .q-body')];
  });assert.deepEqual(typography[0],typography[1]);
  await page.screenshot({path:path.join(out,'lecture-desktop.png')});
  const original=await page.locator('.ai-item').evaluateAll(nodes=>nodes.map(x=>x.dataset.aiId));
  await page.locator('[data-ai-remove]').first().click();
  assert.equal(await page.locator('.ai-item').count(),4);
  await page.locator('#ai-undo').click();
  assert.deepEqual(await page.locator('.ai-item').evaluateAll(nodes=>nodes.map(x=>x.dataset.aiId)),original);
  await page.locator('#ai-answers-toggle').click();
  assert.equal(await page.locator('#ai-items .answers[open]').count(),5);
  await page.locator('#ai-answers-toggle').click();
  next='error';await page.locator('#ai-query').fill('把第二题换成更难的');await page.locator('#ai-generate').click();
  await page.locator('#ai-retry').waitFor();
  assert.equal(await page.locator('.ai-item').count(),5);
  await page.locator('#ai-retry').click();
  await page.waitForFunction(()=>!document.getElementById('ai-generate').disabled);
  assert.equal(calls,3);
  next='slow';await page.locator('#ai-query').fill('再补充一点知识介绍');await page.locator('#ai-generate').click();
  await page.locator('#ai-cancel').click();
  await page.waitForTimeout(1700);
  assert.deepEqual(await page.locator('.ai-item').evaluateAll(nodes=>nodes.map(x=>x.dataset.aiId)),original);
  await page.locator('#ai-result').evaluate(x=>x.scrollTop=0);
  await page.locator('.ai-download-menu>summary').click();
  for(const kind of ['questions','answers']){
    const pending=page.waitForEvent('download');
    await page.locator(`[data-ai-word="${kind}"]`).click();
    const downloaded=await pending;const target=path.join(out,kind+'.docx');await downloaded.saveAs(target);
    await page.waitForFunction(()=>!document.getElementById('ai-generate').disabled);
    const zip=await JSZip.loadAsync(fs.readFileSync(target));const xml=await zip.file('word/document.xml').async('string');
    assert.match(xml,/<w:t/);assert.match(xml,/<w:drawing>/);assert.match(await zip.file('word/styles.xml').async('string'),/SimSun/);
    if(kind==='questions'){assert.match(xml,/晶胞中的粒子数/);assert.match(xml,/Heading2/);assert.match(xml,/w:val="center"/);}
    else assert.ok(!xml.includes('晶胞中的粒子数'));
    const footer=await zip.file('word/footer1.xml').async('string');assert.match(footer,/NUMPAGES/);
  }
  const pdfPending=page.waitForEvent('download');await page.locator('[data-ai-export="questions"]').click();
  const pdfDownload=await pdfPending;await pdfDownload.saveAs(path.join(out,'export-questions.pdf'));
  await page.waitForFunction(()=>!document.getElementById('ai-generate').disabled);
  assert.equal(fs.readFileSync(path.join(out,'export-questions.pdf')).subarray(0,4).toString(),'%PDF');
  await page.evaluate(()=>{window.print=()=>{window.printedLecture=document.querySelector('#ai-print .ai-lecture-heading')?.textContent;};});
  await page.locator('[data-ai-print="questions"]').click();
  await page.waitForFunction(()=>!document.getElementById('ai-generate').disabled);
  assert.match(await page.evaluate(()=>window.printedLecture),/晶胞中的粒子数/);
  await page.locator('.ai-download-menu>summary').click();
  await page.setViewportSize({width:390,height:844});
  await page.locator('#ai-result').evaluate(x=>x.scrollTop=0);
  await page.screenshot({path:path.join(out,'lecture-mobile.png')});
  assert.equal(await page.locator('.ai-chat-column').isVisible(),false);
  const widths=await page.locator('#ai-result').evaluate(x=>[x.scrollWidth,x.clientWidth]);assert.ok(widths[0]<=widths[1]+1,'No mobile horizontal overflow');
  await page.locator('#ai-paper-toggle').click();assert.equal(await page.locator('#ai-query').isVisible(),true);
  next='error';await page.locator('#ai-paper-toggle').click();await page.locator('#ai-reroll').click();
  await page.waitForFunction(()=>!document.getElementById('ai-generate').disabled);
  assert.deepEqual(await page.locator('.ai-item').evaluateAll(nodes=>nodes.map(x=>x.dataset.aiId)),original);
  for(let i=0;i<5;i++)await page.locator('[data-ai-remove]').first().click();
  assert.equal(await page.locator('#ai-undo').isEnabled(),true);
  await page.locator('#ai-undo').click();assert.equal(await page.locator('.ai-item').count(),1);
  await page.locator('#ai-new').click();await page.locator('#ai-welcome').waitFor();
  assert.deepEqual(errors,[]);
  console.log('PASS: lecture typography, formula blocks, desktop/mobile, undo (including empty paper), retry, cancellation, failed reroll preservation, answers, Word/PDF downloads and print.');
 }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
