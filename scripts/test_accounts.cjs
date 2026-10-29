const {chromium}=require('playwright');
const assert=require('node:assert/strict');
(async()=>{
 const fs=require('node:fs'),path=require('node:path');const root=path.resolve(__dirname,'../dist');
 const server=require('node:http').createServer((req,res)=>{const file=path.resolve(root,'.'+decodeURIComponent(req.url.split('?')[0]==='/'?'/index.html':req.url.split('?')[0]));if(!file.startsWith(root+path.sep)){res.writeHead(403).end();return;}fs.readFile(fs.existsSync(file)?file:path.resolve(__dirname,'../../chemy-site/dist',path.relative(root,file)),(err,data)=>{if(err){res.writeHead(404).end();return;}res.setHeader('Content-Type',file.endsWith('.js')?'text/javascript':file.endsWith('.css')?'text/css':file.endsWith('.json')?'application/json':file.endsWith('.html')?'text/html':'application/octet-stream');res.end(data);});});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const base='http://127.0.0.1:'+server.address().port+'/';
 const browser=await chromium.launch({channel:'msedge',headless:true});
 const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const externalSdk=[];
 await page.route('https://cdn.jsdelivr.net/npm/@supabase/**',r=>{externalSdk.push(r.request().url());return r.abort();});
 try{
  await page.goto(base);await page.waitForFunction(()=>typeof ready!=='undefined'&&ready);
  await page.waitForFunction(()=>document.getElementById('account-status').textContent.includes('登录后'),{},{timeout:60000});assert.deepEqual(externalSdk,[]);console.log('PASS: real bundled Supabase SDK initializes with external SDK downloads blocked');
  await page.route('**/account-config.json',r=>r.fulfill({json:{url:'',publishableKey:''}}));
  await page.goto(base+'?test=accounts#access_token=callback-test&type=recovery');await page.waitForFunction(()=>ready);assert(page.url().includes('access_token=callback-test'));console.log('PASS: auth callback fragment survives library initialization');
  await page.goto(base+'?test=accounts#analysis');await page.reload();await page.waitForFunction(()=>typeof ready!=='undefined'&&ready);
  await page.locator('#account-launch').click();await page.waitForFunction(()=>document.getElementById('account-status').textContent.includes('尚未启用'));
  assert(await page.locator('#account-form').isVisible());await page.locator('#account-close').click();assert(await page.locator('[data-favorite]').count()>0);
  await page.locator('[data-favorite]').first().click();await page.waitForFunction(()=>document.getElementById('account-status').textContent.includes('尚未启用'));await page.locator('#account-close').click();
  await page.route('**/account-config.json',r=>r.fulfill({json:{url:'https://test.supabase.co',publishableKey:'public-test'}}));
  await page.route('**/vendor/supabase-2.57.4/client.js',r=>r.fulfill({contentType:'text/javascript',body:`
   let cb;let session=null;const rows={favorites:[],paper_history:[]};
   export function createClient(){return {auth:{onAuthStateChange(fn){cb=fn},async getSession(){return {data:{session}}},async getUser(){return {data:{user:session.user}}},async signInWithPassword(){session={user:{id:'user-a',email:'test@example.com'}};cb('SIGNED_IN',session);return {data:{session}}},async signOut(){session=null;cb('SIGNED_OUT',null);return {}},async signUp(){return {}},async resetPasswordForEmail(){return {}}},from(table){let mode='read',body,filters=[];const q={select(){return q},eq(k,v){filters.push([k,v]);return q},order(){return q},range(){return q},insert(b){mode='insert';body=b;return q},upsert(b){mode='insert';body=b;return q},delete(){mode='delete';return q},then(resolve){if(mode==='insert')for(const b of (Array.isArray(body)?body:[body])){if(table==='favorites'&&rows[table].some(x=>x.user_id===b.user_id&&x.question_id===b.question_id))continue;rows[table].push({...b,id:crypto.randomUUID(),created_at:new Date().toISOString()});}if(mode==='delete')rows[table]=rows[table].filter(x=>!filters.every(([k,v])=>x[k]===v));return Promise.resolve({data:rows[table].filter(x=>filters.every(([k,v])=>x[k]===v)),error:null}).then(resolve)}};return q}}}
  `}));
  await page.reload();await page.waitForFunction(()=>ready);await page.locator('#account-launch').click();
  await page.locator('[name=email]').fill('test@example.com');await page.locator('#account-form [name=password]').fill('password123');await page.locator('[value=login]').click();await page.waitForFunction(()=>!document.getElementById('account-library').hidden);
  await page.locator('#account-close').click();await page.locator('#questions [data-favorite]').first().click();await page.waitForFunction(()=>document.querySelector('#questions [data-favorite]').getAttribute('aria-pressed')==='true');
  await page.locator('#questions [data-select-question]').first().check();await page.locator('#account-launch').click();await page.locator('#account-save').click();await page.waitForFunction(()=>document.querySelector('[data-restore]'));
  assert((await page.locator('#account-favorites').textContent()).includes('第'));await page.locator('#account-close').click();await page.locator('[data-community-view=history]').click();await page.locator('#community-content [data-restore]').click();assert(await page.locator('#export-dialog').isVisible());
  await page.evaluate(()=>document.getElementById('export-dialog').close());await page.locator('[data-community-view=history]').click();await page.locator('#community-content [data-delete-paper]').click();await page.waitForFunction(()=>!document.querySelector('#community-content [data-restore]'));await page.locator('#account-launch').click();
  await page.locator('#account-logout').click();await page.waitForFunction(()=>!document.getElementById('account-form').hidden);assert.equal(await page.locator('#account-favorites [data-account-open]').count(),0);
  assert.deepEqual(errors,[]);console.log('PASS: unconfigured service, login, favorite, save history, restore, delete, logout isolation; browser API mocked');
 }finally{await browser.close();server.close()}
})().catch(e=>{console.error(e);process.exitCode=1});
