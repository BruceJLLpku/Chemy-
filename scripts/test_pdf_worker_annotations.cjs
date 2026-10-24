/* Exercise the real Worker with small native fragments; no full-book build needed. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm'),zlib=require('node:zlib');
const root=path.resolve(__dirname,'..'),PDFLib=require(path.join(root,'dist/vendor/pdf-lib.min.js'));
const vendor=fs.readFileSync(path.join(root,'dist/vendor/pdf-lib.min.js'),'utf8');
const worker=fs.readFileSync(path.join(root,'dist/pdf-worker.js'),'utf8');

function png(width,height) {
  function chunk(type,data) {
    const bytes=Buffer.concat([Buffer.from(type),data]);let crc=0xffffffff;
    for(const byte of bytes){crc^=byte;for(let bit=0;bit<8;bit++)crc=(crc>>>1)^((crc&1)?0xedb88320:0);}
    const length=Buffer.alloc(4),checksum=Buffer.alloc(4);length.writeUInt32BE(data.length);checksum.writeUInt32BE((crc^0xffffffff)>>>0);
    return Buffer.concat([length,bytes,checksum]);
  }
  const header=Buffer.alloc(13);header.writeUInt32BE(width);header.writeUInt32BE(height,4);header[8]=8;header[9]=2;
  const pixels=Buffer.alloc((width*3+1)*height,255);
  for(let row=0;row<height;row++)pixels[row*(width*3+1)]=0;
  return new Uint8Array(Buffer.concat([Buffer.from([137,80,78,71,13,10,26,10]),chunk('IHDR',header),chunk('IDAT',zlib.deflateSync(pixels)),chunk('IEND',Buffer.alloc(0))]));
}

(async()=>{
  const files=new Map();
  async function fragment(name,heights) {
    const doc=await PDFLib.PDFDocument.create();
    for(const height of heights){const page=doc.addPage([595.28,height]);page.drawRectangle({x:60,y:1,width:20,height:height-2,color:PDFLib.rgb(.2,.3,.4)});}
    const bytes=await doc.save();files.set(`export-parts/${name}`,bytes);
    return {path:name,bytes:bytes.length};
  }
  const frame=await fragment('frame.pdf',[13,16]),questions={};
  const headerHeight=(595.28-96)*126/1000,annotationHeight=(595.28-96)*153/1000;
  const atFloor=(841.89-48-55-32-headerHeight-annotationHeight-20)/.85;
  for(const [id,height] of [['short',54.3633],['long',670],['medium',600],['floor',atFloor],['below-floor',atFloor+.01]]){
    questions[id]={...await fragment(id+'.pdf',[height]),pages:[{}],regions:[{sourcePage:0,bands:[{page:0,top:0,bottom:height,width:595.28}]}]};
  }
  files.set('export-parts/inference-answers.json',Buffer.from(JSON.stringify({profile:'clean-vector-v1',bookVersion:'fixture',frame,questions})));
  files.set('export-parts/inference-questions.json',files.get('export-parts/inference-answers.json'));
  files.set('assets/chemy-watermark.jpg',fs.readFileSync(path.join(root,'dist/assets/chemy-watermark.jpg')));
  async function run(items,options={}) {
    let result;const self={postMessage(data){if(data.bytes||data.error)result=data;}};
    const context=vm.createContext({importScripts(){},self,Uint8Array,ArrayBuffer,setTimeout,clearTimeout,fetch:async url=>{
      const bytes=files.get(url.split('?')[0]);assert.ok(bytes,'Unexpected request '+url);
      return {ok:true,json:async()=>JSON.parse(Buffer.from(bytes).toString()),arrayBuffer:async()=>bytes.buffer.slice(bytes.byteOffset,bytes.byteOffset+bytes.byteLength)};
    }});
    vm.runInContext(vendor,context);vm.runInContext(worker,context,{filename:'pdf-worker.js'});
    await self.onmessage({data:{items,kind:'answers',title:'Annotation layout regression',version:'fixture',...options}});
    assert.ok(result,'Worker did not finish');return result;
  }
  // ai-paper.js: width1000, padding24 and three lines at 23+12px.
  const annotation={bytes:png(1000,153)},short={slug:'inference',id:'short'},long={slug:'inference',id:'long',annotation};
  for(const [name,items] of [['first',[long]],['same-topic',[short,long]]]){
    const result=await run(items);assert.ok(result.bytes,result.error);
    const placed=result.placements.find(p=>p.id==='long'),note=result.annotations.find(p=>p.id==='long');
    assert.equal(placed.page,note.page,'Note must remain with the complete first answer block');
    assert.ok(placed.scale>=.85&&placed.scale<1,'Long answer may shrink only enough to fit its note');
    assert.ok(Math.abs(placed.height-670*placed.scale)<1e-6,'Never trim the first answer block');
    assert.ok(Math.abs(note.top+note.height+10-placed.top)<1e-6,'Keep the note-to-answer gap');
    assert.ok(placed.top+placed.height<=786.890001,'Use the content area without overlapping the footer');
    if(name==='first')assert.equal(result.headings[0].page,note.page,'Heading must stay with note and answer');
    else assert.ok(note.page>result.placements[0].page,'Move a same-topic note before placing it');
  }
  const excessive=await run([{...long,annotation:{bytes:png(1000,433)}}]);
  assert.match(excessive.error,/说明过长.*字号清晰/);assert.ok(!excessive.bytes,'Do not emit unreadably small source text');
  // ai-paper.js: its ordinary two-line heading uses 27+12px spacing.
  const paperHeader={bytes:png(1000,126)};
  for(const kind of ['questions','answers']){
    const result=await run([{slug:'inference',id:'long'}],{kind,paperHeader});assert.ok(result.bytes,result.error);
    const header=result.annotations.find(a=>a.id==='paper-header'),first=result.placements[0];
    assert.equal(header.page,1);assert.equal(first.page,1);assert.equal(result.headings[0].page,1);
    assert.ok(header.top+header.height+10<=result.headings[0].top+1e-6,'Header precedes topic heading');
    assert.ok(first.scale>=.85&&first.scale<1,'Keep the complete long first block with its header');
    assert.equal((await PDFLib.PDFDocument.load(result.bytes)).getPageCount(),1,'No header-only cover sheet');
  }
  for(const id of ['medium','floor']){
    const result=await run([{slug:'inference',id,annotation}],{paperHeader});assert.ok(result.bytes,result.error);
    const first=result.placements[0],header=result.annotations[0],note=result.annotations[1],heading=result.headings[0];
    assert.equal(header.page,1);assert.equal(heading.page,1);assert.equal(note.page,1);assert.equal(first.page,1);
    assert.ok(header.top+header.height+10<=heading.top+1e-6);
    assert.ok(heading.top+heading.height<=note.top&&note.top+note.height+10<=first.top+1e-6);
    assert.ok(first.scale>=.85&&first.top+first.height<=786.890001);
    if(id==='floor')assert.ok(Math.abs(first.scale-.85)<1e-10,'Accept the exact readable-size boundary');
  }
  for(const [name,items,header] of [
    ['too tall header',[{slug:'inference',id:'long'}],{bytes:png(1000,433)}],
    ['combined notes',[long],paperHeader],
    ['below scale floor',[{slug:'inference',id:'below-floor',annotation}],paperHeader],
  ]){
    const result=await run(items,{paperHeader:header});assert.match(result.error,/说明过长.*字号清晰/,name);
    assert.ok(!result.bytes,'Reject unreadable '+name+' before emitting a header-only PDF');
  }
  const plain=await run([short,{slug:'inference',id:'long'}]);assert.ok(plain.bytes,plain.error);
  assert.equal(plain.annotations.length,0);
  assert.deepEqual(Array.from(plain.placements,p=>[p.id,p.page,p.top,p.height,p.scale]),[['short',1,80,54.3633,1],['long',2,48,670,1]],'Unannotated placement and scale must remain unchanged');
  console.log('PASS annotated and header opening groups; question/answer headers; same-topic keep-together; exact 85% boundary; oversized and combined-note rejection; unchanged unannotated layout.');
})().catch(error=>{console.error(error);process.exitCode=1;});
