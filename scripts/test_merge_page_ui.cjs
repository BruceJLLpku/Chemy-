// Integration between upstream paper-history behavior and export lifecycle guards.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');

const source = fs.readFileSync(path.resolve(__dirname, '../dist/app.js'), 'utf8');
const start = source.indexOf('function cancelExport()');
const end = source.indexOf("$('select-visible').addEventListener", start);
assert(start >= 0 && end > start, 'Export lifecycle functions must be present');

function harness(protocol = 'http:') {
  const elements = new Map();
  const workers = [], saves = [], downloads = [];
  const items = [
    {id:'first', topic:'分析化学'},
    {id:'second', topic:'分析化学'},
  ];
  const context = vm.createContext({
    exportItems:[items[0]], exportWorker:null, exportBusy:false, exportFromPaper:false,
    location:{protocol}, localPreviewMessage:'Open http://127.0.0.1:8765/',
    numbers:{first:1,second:2}, slugByTopic:{'分析化学':'analysis'}, pdfVersion:'fixture',
    $(id) {
      if (!elements.has(id)) elements.set(id,{disabled:false,textContent:''});
      return elements.get(id);
    },
    Worker:class {
      constructor(url) { this.url = url; workers.push(this); }
      postMessage(request) { this.request = request; }
      terminate() { this.terminated = true; }
      emit(data) { this.onmessage?.({data}); }
    },
    Blob,
    URL:{createObjectURL:()=> 'blob:fixture',revokeObjectURL(){}},
    document:{body:{append(){}},createElement() {
      return {click(){downloads.push(this.download);},remove(){}};
    }},
    window:{ChemyAccount:{savePaper(ids,title,ai,fromPaper) {
      saves.push({ids:Array.from(ids),title,ai,fromPaper});
    }}},
    setTimeout(){},
  });
  vm.runInContext(source.slice(start,end),context,{filename:'app-export-lifecycle.js'});
  return {context,elements,workers,saves,downloads,items};
}

for (const fromPaper of [false,true]) {
  const h = harness();
  h.context.exportFromPaper = fromPaper;
  h.context.startExport('answers');
  assert(h.elements.get('export-start').disabled && h.elements.get('export-answers').disabled);
  assert.equal(h.workers[0].request.kind,'answers');
  h.context.exportFromPaper = !fromPaper;
  h.context.exportItems = [h.items[1]];
  h.workers[0].emit({bytes:new Uint8Array([37,80,68,70])});
  assert.deepEqual(h.saves,[{ids:['first'],title:'自选练习卷',ai:false,fromPaper}]);
  assert.equal(h.downloads[0],'Chemy-分析化学-第1题-答案.pdf');
  assert.equal(h.context.exportBusy,false);
  console.log(`PASS: completed export preserves its original selection and fromPaper=${fromPaper}`);
}

{
  const h = harness();
  h.context.startExport();
  const stale = h.workers[0];
  h.context.cancelExport();
  h.context.exportItems = [h.items[1]];
  h.context.exportFromPaper = true;
  h.context.startExport();
  const active = h.workers[1];
  stale.emit({bytes:new Uint8Array([37,80,68,70])});
  stale.onerror({message:'late worker error'});
  assert.equal(h.saves.length,0);
  assert.equal(h.downloads.length,0);
  assert.equal(h.context.exportWorker,active);
  assert.equal(h.context.exportBusy,true);
  active.emit({bytes:new Uint8Array([37,80,68,70])});
  assert.deepEqual(h.saves[0].ids,['second']);
  assert.equal(h.saves[0].fromPaper,true);
  console.log('PASS: cancelled workers cannot create history or interfere with the next export');
}

{
  const h = harness('file:');
  h.context.startExport();
  assert.equal(h.workers.length,0);
  assert.equal(h.saves.length,0);
  assert.equal(h.context.exportBusy,false);
  assert.match(h.elements.get('export-status').textContent,/http:\/\/127\.0\.0\.1/);
  console.log('PASS: file URL guard stops export before worker creation or paper-history writes');
}
