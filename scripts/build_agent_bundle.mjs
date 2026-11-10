import {mkdirSync,copyFileSync,readFileSync,writeFileSync} from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';

const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)),'..');
const dest=path.join(root,'output','agent-service');
for(const name of ['server','dist'])mkdirSync(path.join(dest,name),{recursive:true});
for(const name of ['server/agent.mjs','dist/paper-engine.js','dist/knowledge-index.json'])copyFileSync(path.join(root,name),path.join(dest,name));
const load=name=>JSON.parse(readFileSync(path.join(root,'dist',name),'utf8'));
const bank=load('questions.json').map(({id,topic,edition,paper,number,title,points,percent,body})=>({
  id,topic,edition,paper,number,title,points,percent,
  body:body.replace(/<\/(?:p|li|tr)>/gi,'\n').replace(/<(?!\/?(?:sub|sup|i|b|strong)>)[^>]*>/gi,' ').slice(0,4200),
}));
writeFileSync(path.join(dest,'dist','questions.json'),JSON.stringify(bank));
writeFileSync(path.join(dest,'dist','numbering.json'),JSON.stringify({version:load('numbering.json').version}));
console.log(`Backend bundle prepared: ${dest} (${bank.length} question summaries; no images or PDFs)`);
