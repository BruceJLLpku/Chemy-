import test from 'node:test';
import assert from 'node:assert/strict';
import {readFileSync} from 'node:fs';
import {createRequire} from 'node:module';
import {createAgent} from '../server/agent.mjs';

const require=createRequire(import.meta.url),engine=require('../dist/paper-engine.js');
const load=name=>JSON.parse(readFileSync(new URL(`../dist/${name}`,import.meta.url),'utf8'));
const bank=load('questions.json'),index=load('knowledge-index.json'),numbering=load('numbering.json');
const concept=index.concepts.find(c=>c.name==='羟醛缩合');
const pool=engine.candidates(concept.id,index,bank).sort((a,b)=>b.strength-a.strength);
assert.ok(pool.length>=4,'Existing audited Aldol fixtures are available');
const env={DEEPSEEK_API_KEY:'test-secret-must-never-leak',DEEPSEEK_MODEL:'deepseek-flash'};
const request={query:'想练习醛醇缩合，选五道原题',count:5,filters:{topic:'all',edition:'all',paper:'all'},numberingVersion:numbering.version};
const resolved={kind:'resolved',conceptIds:[concept.id]};
const selected=items=>({selected:items.map(item=>({id:item.id,linkIndices:[0]}))});
const reply=(content,finish='stop')=>new Response(JSON.stringify({choices:[{finish_reason:finish,message:{content:JSON.stringify(content)}}]}),{status:200});
function make({answers=[resolved,selected(pool.slice(0,5))],fetchImpl,...options}={}) {
  const calls=[];
  const mocked=fetchImpl|| (async(url,init)=>{calls.push({url,init,body:JSON.parse(init.body)});return reply(answers.shift());});
  return {...createAgent({bank,index,numbering,env,fetchImpl:mocked,...options}),calls};
}
const code=value=>error=>error.code===value;

test('Natural-language planning and selection use two real-shaped DeepSeek requests',async()=>{
  const agent=make(),result=await agent.compose(request);
  assert.equal(result.kind,'paper');assert.equal(result.concept.id,concept.id);
  assert.equal(result.items.length,Math.min(5,pool.length));assert.equal(agent.calls.length,2);
  for(const call of agent.calls){
    assert.equal(call.url,'https://api.deepseek.com/chat/completions');
    assert.equal(call.init.headers.Authorization,`Bearer ${env.DEEPSEEK_API_KEY}`);
    assert.equal(call.body.model,'deepseek-flash');assert.equal(call.body.response_format.type,'json_object');
    assert.equal(call.init.redirect,'error');assert.equal(call.body.thinking.type,'disabled');
  }
  assert.equal(JSON.parse(agent.calls[0].body.messages[1].content).concepts.length,index.concepts.length);
  assert.deepEqual(result.items[0].links[0],pool[0].links[0]);
  assert.ok(!JSON.stringify(result).includes(env.DEEPSEEK_API_KEY));
});
test('Audited candidate set obeys every server-side filter and never pads shortages',async()=>{
  const chosen=bank.find(q=>q.id===pool[0].id),edition=String(chosen.edition??39);
  const paper=(chosen.edition??39)===39?String(chosen.paper):`${edition}-${chosen.paper}`;
  const filters={topic:chosen.topic,edition,paper};
  const filtered=engine.candidates(concept.id,index,bank,filters).sort((a,b)=>b.strength-a.strength);
  const agent=make({answers:[selected(filtered)]});
  const result=await agent.compose({...request,conceptId:concept.id,filters,count:50});
  assert.deepEqual(result.items.map(i=>i.id),filtered.map(i=>i.id));
  assert.equal(new Set(result.items.map(i=>i.id)).size,result.items.length);
  assert.ok(result.notices.length);assert.equal(agent.calls.length,1);
});
test('Ambiguous and unknown plans require confirmation instead of silent rewriting',async()=>{
  for(const plan of [{kind:'ambiguous',conceptIds:[concept.id]},{kind:'unknown',conceptIds:[]}]){
    const agent=make({answers:[plan]}),result=await agent.compose(request);
    assert.equal(result.kind,plan.kind);assert.equal(agent.calls.length,1);assert.equal(result.items,undefined);
  }
});
test('Empty filtered pool does not spend a selection call',async()=>{
  const agent=make(),result=await agent.compose({...request,filters:{topic:'晶体化学'}});
  assert.equal(result.items.length,0);assert.equal(agent.calls.length,1);
});
test('Forged concept IDs, unknown fields and incomplete/truncated output fail closed',async()=>{
  for(const invalid of [{kind:'resolved',conceptIds:['invented']},{kind:'resolved',conceptIds:[]},
    {kind:'resolved',conceptIds:[concept.id],prompt:'ignore rules'},{kind:'unknown',conceptIds:[concept.id]}]){
    await assert.rejects(make({answers:[invalid]}).compose(request),code('invalid_result'));
  }
  for(const response of [reply(resolved,'length'),new Response('{bad json'),reply('not an object')]){
    await assert.rejects(make({fetchImpl:async()=>response}).compose(request),code('invalid_result'));
  }
});
test('Model cannot inject another question, duplicate IDs, subquestions or fabricated explanations',async()=>{
  const good={id:pool[0].id,linkIndices:[0]};
  for(const invalid of [
    {selected:[{id:'invented',linkIndices:[0]}]},
    {selected:[good,good]},
    {selected:[{id:pool[0].id,linkIndices:[999]}]},
    {selected:[{id:pool[0].id,linkIndices:[0,0]}]},
    {selected:[{...good,reason:'invented evidence'}]},
    {selected:[]},
    {selected:[{id:pool[0].id,linkIndices:[]}]},
  ])await assert.rejects(make({answers:[invalid]}).compose({...request,conceptId:concept.id}),code('invalid_result'));
  await assert.rejects(make({answers:[selected(pool.slice(0,2))]}).compose({...request,conceptId:concept.id,count:1}),code('invalid_result'));
});
test('Validation rejects client key/model/URL overrides and stale versions before billing',async()=>{
  const agent=make();
  for(const invalid of [
    {...request,model:'other'},{...request,apiKey:'secret'},{...request,baseURL:'http://attacker'},
    {...request,count:1.2},{...request,count:'5'},{...request,query:' '},
    {...request,filters:[]},{...request,filters:{topic:'invented'}},
    {...request,conceptId:'invented'},{...request,numberingVersion:'old'},
  ])await assert.rejects(agent.compose(invalid));
  assert.equal(agent.calls.length,0);
});
test('Selection preserves the requested available count and prioritizes primary examination',async()=>{
  const mixed=structuredClone(index);
  for(const entry of mixed.entries)for(const link of entry.links){
    if(link.conceptId===concept.id)link.strength=entry.id===pool[0].id?3:2;
  }
  await assert.rejects(make({index:mixed,answers:[selected([pool[1]])]}).compose({...request,count:1,conceptId:concept.id}),code('invalid_result'));
  await assert.rejects(make({answers:[selected(pool.slice(0,1))]}).compose({...request,conceptId:concept.id}),code('invalid_result'));
});
test('Missing key and upstream failures are honest, sanitized and never automatically retried',async()=>{
  await assert.rejects(make({env:{}}).compose(request),code('not_configured'));
  for(const [status,expected] of [[401,'upstream_auth'],[402,'upstream_quota'],[429,'upstream_rate'],[503,'upstream_unavailable']]){
    let calls=0;
    const agent=make({fetchImpl:async()=>{calls++;return new Response(env.DEEPSEEK_API_KEY,{status});}});
    await assert.rejects(agent.compose(request),error=>error.code===expected&&!error.message.includes(env.DEEPSEEK_API_KEY));
    assert.equal(calls,1);
  }
  await assert.rejects(make({fetchImpl:async()=>{throw new Error(env.DEEPSEEK_API_KEY);}}).compose(request),error=>!error.message.includes(env.DEEPSEEK_API_KEY));
});
test('Timeout aborts the upstream and leaves a retryable error',async()=>{
  const agent=make({env:{...env,AGENT_TIMEOUT_MS:'15'},fetchImpl:async(_url,{signal})=>new Promise((resolve,reject)=>{
    signal.addEventListener('abort',()=>reject(signal.reason),{once:true});
  })});
  // AbortSignal.timeout uses an unref timer; keep the isolated test alive.
  const keepAlive=setInterval(()=>{},100);
  try{await assert.rejects(agent.compose(request),code('upstream_timeout'));}finally{clearInterval(keepAlive);}
});
test('Global call limit covers planning and selection and resets by UTC day',async()=>{
  let time=Date.UTC(2026,9,17);
  const agent=make({env:{...env,AGENT_DAILY_CALL_LIMIT:'1'},now:()=>time,answers:[selected(pool.slice(0,1)),selected(pool.slice(0,1))]});
  const direct={...request,count:1,conceptId:concept.id};
  await agent.compose(direct);await assert.rejects(agent.compose(direct),code('daily_limit'));
  assert.equal(agent.calls.length,1);time+=86400000;await agent.compose(direct);assert.equal(agent.calls.length,2);
});
test('Concurrency is bounded, and caller cancellation propagates upstream',async()=>{
  let started;
  const begun=new Promise(resolve=>{started=resolve;});
  const agent=make({env:{...env,AGENT_MAX_CONCURRENT:'1'},fetchImpl:async(_url,{signal})=>{
    started();return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(signal.reason),{once:true}));
  }});
  const controller=new AbortController(),first=agent.compose(request,controller.signal);
  await begun;await assert.rejects(agent.compose(request),code('busy'));controller.abort();
  await assert.rejects(first,code('cancelled'));
});
test('HTTP preview, CORS, body limits, rate limiting and missing-key health do not expose secrets',async()=>{
  const agent=make({env:{AGENT_REQUESTS_PER_MINUTE:'2',ALLOWED_ORIGINS:'https://brucejllpku.github.io'}});
  await new Promise(resolve=>agent.server.listen(0,'127.0.0.1',resolve));
  const base=`http://127.0.0.1:${agent.server.address().port}`;
  const post=(body,origin='https://brucejllpku.github.io')=>fetch(base+'/api/compose',{method:'POST',headers:{'Content-Type':'application/json',Origin:origin},body:JSON.stringify(body)});
  try{
    const health=await (await fetch(base+'/health')).json();assert.equal(health.configured,false);
    const config=await (await fetch(base+'/ai-config.json')).json();assert.equal(config.mode,'deepseek');assert.equal(config.backendUrl,'');
    assert.equal((await fetch(base+'/.env')).status,404);
    assert.equal((await fetch(base+'/server/agent.mjs')).status,404);
    const blocked=await post(request,'https://attacker.example');assert.equal(blocked.status,403);assert.equal(blocked.headers.get('access-control-allow-origin'),null);
    const oversized=await post({query:'x'.repeat(9000)});assert.equal(oversized.status,413);
    const missing=await post(request);assert.equal(missing.status,503);assert.equal((await missing.json()).code,'not_configured');
    assert.equal(missing.headers.get('access-control-allow-origin'),'https://brucejllpku.github.io');
    assert.equal((await post(request)).status,429);assert.equal(agent.calls.length,0);
  }finally{agent.server.closeAllConnections();await new Promise(resolve=>agent.server.close(resolve));}
});
test('Production never serves repository files or accepts an unapproved/no browser Origin',async()=>{
  const agent=make({env:{...env,NODE_ENV:'production',ALLOWED_ORIGINS:'https://brucejllpku.github.io'}});
  await new Promise(resolve=>agent.server.listen(0,'127.0.0.1',resolve));
  const base=`http://127.0.0.1:${agent.server.address().port}`;
  try{
    assert.equal((await fetch(base+'/')).status,404);
    assert.equal((await fetch(base+'/api/compose',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(request)})).status,403);
  }finally{agent.server.closeAllConnections();await new Promise(resolve=>agent.server.close(resolve));}
});
