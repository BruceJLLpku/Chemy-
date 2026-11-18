/* Exercise the actual loader with native gzip streams and SHA-256. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const {test}=require('node:test');
const {createHash,webcrypto}=require('node:crypto');
const {gzipSync}=require('node:zlib');
const source=fs.readFileSync(path.resolve(__dirname,'../dist/pdf-worker.js'),'utf8');
const sha=bytes=>createHash('sha256').update(bytes).digest('hex');
const literal=bytes=>({data:Buffer.from(bytes),reference:false});
const reference=bytes=>({data:Buffer.from(bytes),reference:true});

function description(segments){
  const chunks=[Buffer.from('CHEMYPK1')];
  for(const segment of segments){
    const size=segment.length??segment.data.length,header=Buffer.alloc(4);
    header.writeUInt32LE((size|(segment.reference?0x80000000:0))>>>0);
    chunks.push(header,segment.reference?Buffer.from(segment.hash??sha(segment.data),'hex'):segment.data);
  }
  return Buffer.concat(chunks);
}

function harness({crypto=true,gzip=true,realPDF=false}={}){
  const responses=new Map(),requests=[],state={loads:0};
  const sandbox={Uint8Array,ArrayBuffer,DataView,TransformStream,
    DecompressionStream:gzip?DecompressionStream:undefined,
    self:{crypto:crypto?webcrypto:undefined},importScripts(){},
    PDFLib:realPDF?require('../dist/vendor/pdf-lib.min.js'):{PDFDocument:{async load(bytes){state.loads++;return {bytes:Buffer.from(bytes instanceof ArrayBuffer?new Uint8Array(bytes):bytes)};}}},
    async fetch(url,options){
      const name=new URL(url,'http://local/').pathname.slice(1);requests.push({name,options});
      let value=responses.get(name);
      if(typeof value==='function')value=await value();
      if(value instanceof Response)return value;
      return value===undefined?new Response(null,{status:404}):new Response(value);
    }};
  vm.createContext(sandbox);vm.runInContext(source,sandbox,{filename:'actual-pdf-worker.js'});
  return {responses,requests,state,load:record=>sandbox.loadFragment(record)};
}

function install(h,segments,{file='fixture/question.pdf',raw=Buffer.concat(segments.map(segment=>segment.data))}={}){
  h.responses.set('export-parts/'+file+'.pack',gzipSync(description(segments)));
  for(const segment of segments)if(segment.reference)h.responses.set('export-parts/shared/'+(segment.hash??sha(segment.data))+'.bin',segment.data);
  return {path:file,packed:true,bytes:raw.length,sha256:sha(raw)};
}
const sharedRequests=h=>h.requests.filter(request=>request.name.startsWith('export-parts/shared/'));

test('Unflagged local PDFs keep the original URL and optional-crypto behavior',async()=>{
  const h=harness({crypto:false}),raw=Buffer.from('%PDF-1.7\nlocal bytes');
  h.responses.set('export-parts/frame.pdf',raw);
  assert.deepEqual((await h.load({path:'frame.pdf',bytes:raw.length,sha256:sha(raw)})).bytes,raw);
  assert.equal(h.requests[0].name,'export-parts/frame.pdf');assert.equal(h.requests.length,1);
});

test('Literal and shared binary segments reconstruct every original PDF byte',async()=>{
  const h=harness(),block=Buffer.from([0xff,0,0x81,0xc3,0xfe,10]);
  const segments=[literal('%PDF-1.7\n'),reference(block),literal('middle'),reference(block),literal('\n%%EOF')];
  const record=install(h,segments),expected=Buffer.concat(segments.map(segment=>segment.data));
  assert.deepEqual((await h.load(record)).bytes,expected);
  assert.equal(sharedRequests(h).length,1);assert.equal(h.state.loads,1);
  assert.equal(h.requests[0].options.cache,'no-cache','Refresh descriptors when publishing changes shared block membership');
});

test('Verified shared bytes are reused across different question descriptors',async()=>{
  const h=harness(),block=reference(Buffer.from('shared font program'));
  const first=install(h,[literal('one'),block],{file:'first.pdf'});
  const second=install(h,[literal('two'),block],{file:'second.pdf'});
  await h.load(first);await h.load(second);assert.equal(sharedRequests(h).length,1);
});

test('A reconstructed native PDF loads in the real bundled PDF library',async()=>{
  const {PDFDocument}=require('../dist/vendor/pdf-lib.min.js');
  const original=await PDFDocument.create();original.addPage([123,456]);original.setTitle('Packed fixture');
  const raw=Buffer.from(await original.save()),h=harness({realPDF:true});
  const record=install(h,[literal(raw.subarray(0,64)),reference(raw.subarray(64,-8)),literal(raw.subarray(-8))]);
  const document=await h.load(record);
  assert.equal(document.getPageCount(),1);assert.deepEqual(document.getPage(0).getSize(),{width:123,height:456});
  assert.equal(document.getTitle(),'Packed fixture');
});

test('Shared downloads never exceed six concurrent requests per question',async()=>{
  const h=harness(),segments=Array.from({length:18},(_,index)=>reference(Buffer.from('block-'+String(index).padStart(3,'0'))));
  const record=install(h,segments);let active=0,maximum=0;
  for(const segment of segments)h.responses.set('export-parts/shared/'+sha(segment.data)+'.bin',async()=>{
    maximum=Math.max(maximum,++active);await new Promise(resolve=>setTimeout(resolve,12));active--;return segment.data;
  });
  assert.deepEqual((await h.load(record)).bytes,Buffer.concat(segments.map(segment=>segment.data)));
  assert.equal(maximum,6);
});

test('Packed transport requires cryptographic verification before fetching',async()=>{
  const h=harness({crypto:false}),record=install(h,[literal('pdf')]);
  await assert.rejects(h.load(record),/验证/);assert.equal(h.requests.length,0);
});

test('A browser without native gzip support fails before fetching',async()=>{
  const h=harness({gzip:false}),record=install(h,[literal('pdf')]);
  await assert.rejects(h.load(record),/浏览器/);assert.equal(h.requests.length,0);
});

test('Invalid declared PDF sizes are rejected without allocation or network',async()=>{
  for(const bytes of [0,-1,1.5,NaN,100*1024*1024+1,Number.MAX_SAFE_INTEGER]){
    const h=harness(),record={path:'q.pdf',packed:true,bytes,sha256:'0'.repeat(64)};
    await assert.rejects(h.load(record));assert.equal(h.requests.length,0);
  }
});

test('Bad magic, truncated tags and hashes, and empty segments fail before block requests',async()=>{
  const block=reference(Buffer.from('font')),valid=description([block]);
  const emptyTag=Buffer.alloc(4),missingLiteral=Buffer.alloc(4);missingLiteral.writeUInt32LE(4);
  for(const broken of [Buffer.from('CHEMYPK0'),Buffer.concat([Buffer.from('CHEMYPK1'),Buffer.from([1,2,3])]),
      valid.subarray(0,valid.length-1),Buffer.concat([Buffer.from('CHEMYPK1'),emptyTag]),
      Buffer.concat([Buffer.from('CHEMYPK1'),missingLiteral,Buffer.from('x')])]){
    const h=harness(),record=install(h,[block]);h.responses.set('export-parts/'+record.path+'.pack',gzipSync(broken));
    await assert.rejects(h.load(record));assert.equal(sharedRequests(h).length,0);assert.equal(h.state.loads,0);
  }
});

test('Truncated gzip and excessive expansion never reach the PDF parser',async()=>{
  for(const body of [gzipSync(Buffer.from('CHEMYPK1')).subarray(0,12),gzipSync(Buffer.alloc(4096,1))]){
    const h=harness(),record=install(h,[literal('x')]);h.responses.set('export-parts/'+record.path+'.pack',body);
    await assert.rejects(h.load(record));assert.equal(h.state.loads,0);assert.equal(sharedRequests(h).length,0);
  }
});

test('Segment totals, trailing bytes and inconsistent repeated block lengths are rejected',async()=>{
  const block=reference(Buffer.from('font'));
  for(const broken of [description([literal('x')]),Buffer.concat([description([block]),Buffer.from([0])]),
      description([block,{...block,length:block.data.length+1}])]){
    const h=harness(),record=install(h,[block]);h.responses.set('export-parts/'+record.path+'.pack',gzipSync(broken));
    if(broken.length>50)record.bytes=block.data.length*2+1;
    await assert.rejects(h.load(record));assert.equal(sharedRequests(h).length,0);assert.equal(h.state.loads,0);
  }
});

test('Too many nonempty segments are rejected before reconstructing a PDF',async()=>{
  const h=harness(),segments=Array.from({length:65537},()=>literal('x')),record=install(h,segments);
  await assert.rejects(h.load(record));assert.equal(h.state.loads,0);
});

test('A shared block with changed bytes, extra bytes or missing bytes is rejected',async()=>{
  const block=reference(Buffer.from('font'));
  for(const replacement of [Buffer.from('FONt'),Buffer.from('fontx'),Buffer.from('fon')]){
    const h=harness(),record=install(h,[block]);h.responses.set('export-parts/shared/'+sha(block.data)+'.bin',replacement);
    await assert.rejects(h.load(record));assert.equal(h.state.loads,0);
  }
});

test('Final PDF length and original SHA remain mandatory after valid block verification',async()=>{
  const h=harness(),record=install(h,[literal('%PDF'),reference(Buffer.from('font'))]);record.sha256='0'.repeat(64);
  await assert.rejects(h.load(record),/索引不一致/);assert.equal(h.state.loads,0);
});

test('Failed shared requests are not cached and a later retry can succeed',async()=>{
  const h=harness(),block=reference(Buffer.from('font')),record=install(h,[block]),url='export-parts/shared/'+sha(block.data)+'.bin';
  h.responses.set(url,()=>new Response(null,{status:503}));
  await assert.rejects(h.load(record),/网络/);
  h.responses.set(url,block.data);assert.deepEqual((await h.load(record)).bytes,block.data);
  assert.equal(sharedRequests(h).length,2);
});

test('Missing descriptors retain the existing readable network error',async()=>{
  const h=harness();await assert.rejects(h.load({path:'missing.pdf',packed:true,bytes:1,sha256:'0'.repeat(64)}),/网络/);
});
