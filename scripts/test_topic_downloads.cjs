const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict'),crypto=require('crypto');
const root=path.resolve(__dirname,'..'),base=process.env.CHEMY_TEST_URL||'http://127.0.0.1:8765/';
const report={checks:[],errors:[]};
function check(name,ok){assert.ok(ok,name);report.checks.push(name);console.log('PASS',name)}
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:1450,height:960},acceptDownloads:true});
 page.on('pageerror',e=>report.errors.push(e.message));
 try{
  await page.goto(base+'#equilibrium');await page.waitForFunction(()=>typeof ready!=='undefined'&&ready);
  const links=await page.locator('#downloads a').evaluateAll(items=>items.map(x=>x.href));
  check('Both full-topic links use the new PDF content version',links.length===2&&links.every(h=>/equilibrium-(questions|answers)\.pdf\?v=topic-pdf-/.test(h)));
  await page.locator('#edition-select').selectOption('39');
  check('Filtering still downloads the complete topic',JSON.stringify(links)===JSON.stringify(await page.locator('#downloads a').evaluateAll(items=>items.map(x=>x.href))));
  for(const [i,kind] of ['questions','answers'].entries()){
   const event=page.waitForEvent('download',{timeout:180000});await page.locator('#downloads a').nth(i).click();
   const target=path.join(root,'output/pdf',`topic-equilibrium-${kind}.pdf`);
   await (await event).saveAs(target);
   const hash=data=>crypto.createHash('sha256').update(data).digest('hex');
   check('Actual '+kind+' download matches the compact full topic book',hash(fs.readFileSync(target))===hash(fs.readFileSync(path.join(root,'dist/downloads',`equilibrium-${kind}.pdf`))));
  }
  check('Single-question action remains available',await page.locator('[data-download-question]').count()>0);
  check('No browser errors',report.errors.length===0);
 }finally{
  fs.writeFileSync(path.join(root,'output/continuous/download-checks.json'),JSON.stringify(report,null,2));
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exitCode=1});
