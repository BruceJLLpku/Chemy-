const {chromium}=require('playwright');
const fs=require('fs'),path=require('path'),assert=require('assert/strict');
const root=path.resolve(__dirname,'..'),base=process.env.CHEMY_TEST_URL||'http://127.0.0.1:8765/';
const checks=[];
function check(name,ok){assert.ok(ok,name);checks.push(name);console.log('PASS',name)}
(async()=>{
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 const page=await browser.newPage({viewport:{width:1450,height:960}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const out=path.join(root,'output/watermark');fs.mkdirSync(out,{recursive:true});
 try{
  await page.goto(base+'#analysis');await page.waitForFunction(()=>typeof ready!=='undefined'&&ready);
  const mark=page.locator('.reader-watermark');
  check('Original illustration loads',await mark.evaluate(el=>el.complete&&el.naturalWidth===786&&el.naturalHeight===841));
  for(const [name,width,height,offset] of [['desktop',1450,960,500],['tablet',1000,900,190],['mobile',390,844,0]]){
   await page.setViewportSize({width,height});
   await page.locator('.question').first().scrollIntoViewIfNeeded();
   const before=await mark.boundingBox();
   check(name+' watermark is centered in reading column',Math.abs(before.x+before.width/2-(width+offset)/2)<2);
   check(name+' watermark stays inside reading viewport',before.x>=offset&&before.x+before.width<=width&&before.y>=64&&before.y+before.height<=height);
   await page.evaluate(()=>scrollBy(0,160));const after=await mark.boundingBox();
   check(name+' watermark stays centered when scrolling',Math.abs(before.y-after.y)<1);
   check(name+' watermark leaves controls clickable',await mark.evaluate(el=>getComputedStyle(el).pointerEvents==='none'&&getComputedStyle(el).mixBlendMode==='multiply'&&getComputedStyle(el).opacity==='0.18'));
   await page.screenshot({path:path.join(out,`website-${name}.png`)});
  }
  await page.locator('.answers').first().locator('summary').click();
  check('Answers can open beneath watermark',await page.locator('.answers').first().getAttribute('open')!==null);
  await page.locator('#select-visible').click();
  check('Question picker opens above watermark',await page.locator('#question-picker').evaluate(el=>el.open));
  await page.locator('#picker-close').click();
  await page.goto(base+'#about');await page.waitForFunction(()=>typeof ready!=='undefined'&&ready);
  check('Introduction remains clear',!await mark.isVisible());
  check('No browser errors',errors.length===0);
 }finally{
  fs.writeFileSync(path.join(out,'browser-checks.json'),JSON.stringify({checks,errors},null,2));
  await browser.close();
 }
})().catch(e=>{console.error(e);process.exitCode=1});
