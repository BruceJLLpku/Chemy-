/* Execute the real drawNative function without a browser; no product files change. */
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..'),PDFLib=require(path.join(root,'dist/vendor/pdf-lib.min.js'));
const sandbox={PDFLib,importScripts(){},self:{}};
vm.runInNewContext(fs.readFileSync(path.join(root,'dist/pdf-worker.js'),'utf8'),sandbox,{filename:'pdf-worker.js'});
const {PDFDocument,PDFName,PDFArray,PDFDict}=PDFLib;
const values=(object)=>{const d=object instanceof PDFDict?object:object.dict;return d.lookup(PDFName.of('Matrix'),PDFArray).asArray().map(n=>n.asNumber());};
const original=[.8,.1,-.2,1.1,7,13];
(async()=>{
 const source=await PDFDocument.create();
 const fn=source.context.register(source.context.obj({FunctionType:2,Domain:[0,1],C0:[1,0,0],C1:[0,0,1],N:1}));
 const shading=source.context.register(source.context.obj({ShadingType:2,ColorSpace:'DeviceRGB',Coords:[105,180,170,180],Function:fn,Extend:[true,true]}));
 const tile=source.context.register(source.context.stream('1 0 0 rg 0 0 4 4 re f 0 0 1 rg 4 4 4 4 re f',{Type:'Pattern',PatternType:1,PaintType:1,TilingType:1,BBox:[0,0,8,8],XStep:8,YStep:8,Resources:{},Matrix:original}));
 const gradient=source.context.register(source.context.obj({Type:'Pattern',PatternType:2,Shading:shading,Matrix:original}));
 for(const suffix of ['A','B']){
  const p=source.addPage([120,300]);p.setMediaBox(10,200,100,60);
  p.node.set(PDFName.of('Resources'),source.context.obj({Pattern:{['Tile'+suffix]:tile,['Gradient'+suffix]:gradient}}));
  p.node.set(PDFName.of('Contents'),source.context.register(source.context.stream(`1 1 1 rg -1000 -1000 2000 2000 re f /Pattern cs /Tile${suffix} scn 10 205 45 50 re f /Gradient${suffix} scn 60 205 45 50 re f`)));
 }
 const output=await PDFDocument.create(),copied=await output.copyPages(source,[0,1]),target=output.addPage([400,300]);
 const patternRefs=copied.map(p=>p.node.Resources().lookup(PDFName.of('Pattern'),PDFDict));
 assert.equal(patternRefs[0].get(PDFName.of('TileA')).toString(),patternRefs[1].get(PDFName.of('TileB')).toString(),'Bands must share the same original tiling-pattern object');
 assert.equal(patternRefs[0].get(PDFName.of('GradientA')).toString(),patternRefs[1].get(PDFName.of('GradientB')).toString(),'Bands must share the same original shading-pattern object');
 const placements=[{x:25,y:40,scale:1.25},{x:210,y:120,scale:.75}];
 for(let i=0;i<copied.length;i++){
  const p=placements[i];sandbox.drawNative(output,target,copied[i],p.x,p.y,p.scale);
  const expected=[p.scale*original[0],p.scale*original[1],p.scale*original[2],p.scale*original[3],p.scale*original[4]+p.x-10*p.scale,p.scale*original[5]+p.y-200*p.scale];
  const current=target.node.Resources().lookup(PDFName.of('Pattern'),PDFDict);
  for(const name of ['Tile','Gradient']){
   const local=PDFName.of(name+['A','B'][i]),ref=patternRefs[i].get(local),clone=current.get(local);
   assert.notEqual(ref.toString(),clone.toString(),'Placed pattern must be a clone');
   assert.deepEqual(values(output.context.lookup(ref)),original,'Drawing a band must not mutate its shared source pattern');
   assert.deepEqual(values(output.context.lookup(clone)),expected,`${name} matrix must include scale and nonzero MediaBox origin`);
  }
 }
 const dictionary=target.node.Resources().lookup(PDFName.of('Pattern'),PDFDict);
 for(const name of ['TileA','GradientA']){
  const expected=[1, .125,-.25,1.375,21.25,-193.75];
  assert.deepEqual(values(output.context.lookup(dictionary.get(PDFName.of(name)))),expected,'Second band must not rebase the first band again');
 }
 // Reuse a copied band on another output page: each page must own its rebased
 // pattern without changing the first page or the shared source object.
 const nextPage=output.addPage([400,300]);
 const repeated={x:50,y:60,scale:.5,source:0,page:1};
 sandbox.drawNative(output,nextPage,copied[0],repeated.x,repeated.y,repeated.scale);
 const nextPatterns=nextPage.node.Resources().lookup(PDFName.of('Pattern'),PDFDict);
 for(const name of ['TileA','GradientA']){
  const key=PDFName.of(name);
  assert.deepEqual(values(output.context.lookup(nextPatterns.get(key))),[.4,.05,-.1,.55,48.5,-33.5]);
  assert.deepEqual(values(output.context.lookup(dictionary.get(key))),[1,.125,-.25,1.375,21.25,-193.75]);
  assert.deepEqual(values(output.context.lookup(patternRefs[0].get(key))),original);
 }
 placements.push(repeated);
 const folder=path.join(root,'work/export-validation/patterns');fs.mkdirSync(folder,{recursive:true});
 fs.writeFileSync(path.join(folder,'synthetic-source.pdf'),await source.save());
 fs.writeFileSync(path.join(folder,'synthetic-output.pdf'),await output.save());
 fs.writeFileSync(path.join(folder,'synthetic-layout.json'),JSON.stringify({sourceMediaBox:[10,200,110,260],placements},null,2));
 console.log('PASS Type 1 and Type 2 pattern matrices; nonzero page origins; scaled placements; same-page and cross-page shared resources remain unchanged. Run test_pdf_export_pixels.py --synthetic to verify clipped white backgrounds.');
})().catch(error=>{console.error(error);process.exitCode=1;});
