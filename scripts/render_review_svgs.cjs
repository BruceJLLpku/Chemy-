/* Render only local question SVG assets for AI contact sheets; source unchanged. */
const {chromium}=require('playwright');
const fs=require('fs'),path=require('path');
const root=path.resolve(__dirname,'..'),folder=path.join(root,'output/knowledge-review/svg');
(async()=>{
 fs.mkdirSync(folder,{recursive:true});
 const browser=await chromium.launch({headless:true,channel:'msedge'});
 try {
  const page=await browser.newPage({viewport:{width:1500,height:1000},deviceScaleFactor:1});
  for(const name of fs.readdirSync(path.join(root,'dist/assets')).filter(n=>n.endsWith('.svg'))){
   await page.goto('file:///'+path.join(root,'dist/assets',name).replaceAll('\\','/'));
   const svg=page.locator('svg');
   await svg.screenshot({path:path.join(folder,name+'.png')});
   console.log(name);
  }
 } finally {await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
