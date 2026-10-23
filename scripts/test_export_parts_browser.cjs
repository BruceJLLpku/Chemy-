/* Product-level selected-PDF regression; uses an isolated local HTTP server. */
const fs = require('node:fs');
const path = require('node:path');
const http = require('node:http');
const assert = require('node:assert/strict');
const {chromium} = require('playwright');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'work', 'export-validation');
const mime = {'.html':'text/html', '.js':'text/javascript', '.json':'application/json', '.css':'text/css', '.pdf':'application/pdf', '.jpg':'image/jpeg', '.webp':'image/webp'};
const server = http.createServer((req, res) => {
  const relative = decodeURIComponent(new URL(req.url, 'http://localhost').pathname).replace(/^\/+/, '') || 'index.html';
  const file = path.resolve(root, 'dist', relative);
  if (!file.startsWith(path.join(root, 'dist') + path.sep)) {res.writeHead(403);res.end();return;}
  fs.readFile(file, (err, data) => {if (err) {res.writeHead(404);res.end();return;}res.setHeader('Content-Type', mime[path.extname(file)] || 'application/octet-stream');res.end(data);});
});
const patternMode = process.argv.includes('--patterns');
const annotationMode = process.argv.includes('--annotations');
assert.ok(!(patternMode && annotationMode), 'Choose one specialist regression mode');
const patternTopics = (process.env.CHEMY_TEST_PATTERN_TOPICS || '').split(',').filter(Boolean);
assert.ok(patternTopics.every(slug => ['polymer','kinetics','organic'].includes(slug)), 'Unknown pattern topic');
const report = {checks:[], errors:[], requests:[], exports:[]};
function check(name, result) {assert.ok(result, name);report.checks.push(name);console.log('PASS', name);}
(async () => {
  fs.mkdirSync(output, {recursive:true});
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const launch = {headless:true};
  if (process.env.CHEMY_TEST_CHROMIUM) launch.executablePath = process.env.CHEMY_TEST_CHROMIUM;
  const browser = await chromium.launch(launch);
  try {
    const context = await browser.newContext({acceptDownloads:true});
    await context.addInitScript(() => {
      const NativeWorker = window.Worker;
      window.Worker = class extends NativeWorker {
        constructor(...args) {super(...args);this.addEventListener('message', ({data}) => {if (data.placements) window.lastExport = data;});}
      };
    });
    const page = await context.newPage();
    page.on('pageerror', e => report.errors.push(e.message));
    page.on('request', req => report.requests.push(req.url()));
    await page.goto(`http://127.0.0.1:${server.address().port}/#polymer`);
    await page.waitForFunction(() => typeof ready !== 'undefined' && ready);
    const crossIds = await page.evaluate(() => topics.map(t => byTopic.get(t)[0].id));
    check('Nine topics available', crossIds.length === 9);
    const jobs = annotationMode ? [] : patternMode ? [
      ['pattern-polymer', ['chemy39-17-4','chemy39-20-7'], ['questions','answers']],
      ['pattern-kinetics', ['chemy39-3-7'], ['questions','answers']],
      ['pattern-organic', ['chemy34-6-8','chemy34-6-9','chemy34-7-10','chemy34-7-11','chemy34-8-8'], ['answers']],
    ] : [['single-polymer', ['chemy39-5-4'], ['questions','answers']]];
    if (!patternMode && !annotationMode && !process.env.CHEMY_TEST_SINGLE && !process.argv.includes('--single')) jobs.push(['nine-topics', crossIds, ['questions','answers']]);
    for (const [name, ids, kinds] of jobs.filter(([name]) => !patternMode || !patternTopics.length || patternTopics.includes(name.replace('pattern-', '')))) {
      await page.evaluate(ids => openExport(ids), ids);
      for (const kind of kinds) {
        const before = report.requests.length;
        const downloading = page.waitForEvent('download', {timeout:240000});
        await page.locator(kind === 'questions' ? '#export-start' : '#export-answers').click();
        const failure = page.waitForFunction(() => ['export-start', 'export-answers'].some(id => document.getElementById(id).textContent.includes('重试')), null, {timeout:240000}).then(async () => {throw new Error(await page.locator('#export-status').textContent());});
        const download = await Promise.race([downloading, failure]);
        const file = `${name}-${kind}.pdf`;
        await download.saveAs(path.join(output, file));
        const bytes = fs.statSync(path.join(output, file)).size;
        const layout = await page.evaluate(() => ({placements:window.lastExport.placements, headings:window.lastExport.headings, annotations:window.lastExport.annotations}));
        check(`${file}: exactly selected questions`, JSON.stringify([...new Set(layout.placements.map(p => p.id))].sort()) === JSON.stringify([...ids].sort()));
        check(`${file}: within page bounds`, layout.placements.every(p => p.top >= 47 && p.top+p.height <= 787));
        check(`${file}: no full-topic book download`, !report.requests.slice(before).some(url => /\/downloads\/.*\.pdf/.test(url)));
        if (name === 'single-polymer') check(`${file}: under 1 MiB`, bytes < 1024*1024);
        report.exports.push({file, kind, ids, bytes, ...layout});
      }
      await page.locator('#export-close').click();
    }
    if (patternMode) { check('No JavaScript errors', report.errors.length === 0); return; }
    if (annotationMode) {
      const cases = await page.evaluate(async () => {
        async function note(extraLines=0) {
          // Match ai-paper.js's actual 1000px width, 24px padding and 23+12px
          // line spacing. Three lines are a real minimal association note.
          const lines=['练习第 1 题 · 知识点关联说明','整道题：检验说明和完整答案块的同页排版。',
            ...Array(extraLines).fill('额外说明：验证过长说明不能无限缩小答案文字。'),
            '关联说明由 AI 分析；下方为原卷参考答案。'];
          const canvas=document.createElement('canvas');canvas.width=1000;canvas.height=48+lines.length*35;
          const draw=canvas.getContext('2d');draw.fillStyle='#fff';draw.fillRect(0,0,canvas.width,canvas.height);
          draw.fillStyle='#252b29';draw.font='23px "Microsoft YaHei",sans-serif';
          lines.forEach((line,i)=>draw.fillText(line,24,47+i*35));
          return {bytes:new Uint8Array(await (await new Promise(resolve=>canvas.toBlob(resolve,'image/png'))).arrayBuffer())};
        }
        async function paperHeader() {
          const canvas=document.createElement('canvas');canvas.width=1000;canvas.height=126;
          const draw=canvas.getContext('2d');draw.fillStyle='#fff';draw.fillRect(0,0,1000,126);
          draw.fillStyle='#252b29';draw.font='27px "Microsoft YaHei",sans-serif';
          draw.fillText('化学专题练习 · 参考答案',24,51);
          draw.fillText('保留原专题编号与来源。',24,90);
          return {bytes:new Uint8Array(await (await new Promise(resolve=>canvas.toBlob(resolve,'image/png'))).arrayBuffer())};
        }
        async function run(items,options={}) {
          return new Promise((resolve,reject)=>{
            const worker=new Worker('pdf-worker.js');
            const timer=setTimeout(()=>{worker.terminate();reject(new Error('Annotated export timed out'));},180000);
            worker.onmessage=({data})=>{
              if(data.error || data.bytes){clearTimeout(timer);worker.terminate();resolve(data.bytes ? {...data,bytes:Array.from(new Uint8Array(data.bytes))} : data);}
            };
            worker.onerror=event=>{clearTimeout(timer);worker.terminate();reject(new Error(event.message));};
            worker.postMessage({items,kind:'answers',title:'Chemy · 说明与长答案排版回归',version:pdfVersion,...options});
          });
        }
        const long={slug:'inference',id:'chemy37-23-4',annotation:await note()};
        const short={slug:'inference',id:'chemy36-5-12'};
        const header=await paperHeader();
        return [
          {name:'annotation-long-first',ids:[long.id],noteId:long.id,scaled:true,result:await run([long])},
          {name:'annotation-same-topic',ids:[short.id,long.id],noteId:long.id,scaled:true,moved:true,result:await run([short,long])},
          {name:'header-long-first',ids:[long.id],header:true,scaled:true,result:await run([{...long,annotation:null}],{paperHeader:header})},
          {name:'header-and-annotation',ids:[short.id],header:true,noteId:short.id,result:await run([{...short,annotation:await note()}],{paperHeader:header})},
          {name:'annotation-too-long',reject:true,result:await run([{...long,annotation:await note(8)}])},
          {name:'header-too-long',reject:true,result:await run([{...long,annotation:null}],{paperHeader:await note(8)})},
          {name:'header-and-note-too-long',reject:true,result:await run([long],{paperHeader:header})},
        ];
      });
      for (const item of cases.filter(item=>!item.reject)) {
        assert.ok(item.result.bytes, item.result.error || 'Expected an annotated PDF');
        const layout=item.result, annotation=layout.annotations.find(a=>a.id===item.noteId);
        const first=layout.placements.find(p=>p.id===(item.noteId||item.ids[0]));
        if(item.noteId) check(`${item.name}: note and complete first answer block share a page`, annotation.page===first.page && annotation.top+annotation.height+9.99<=first.top);
        check(`${item.name}: source text shrinks by at most 15 percent`, first.scale>=.85 && (item.scaled ? first.scale<1 : first.scale===1));
        check(`${item.name}: placements stay within the content area`, layout.placements.every(p=>p.top>=48 && p.top+p.height<=786.891));
        if(item.moved) check('Same-topic note moves with its answer to the next page', annotation.page>layout.placements[0].page);
        else check(`${item.name}: first answer retains its topic heading`, layout.headings[0].page===first.page);
        if(item.header) {
          const header=layout.annotations.find(a=>a.id==='paper-header'),heading=layout.headings[0];
          check(`${item.name}: no header-only cover sheet`, header.page===1 && first.page===header.page && heading.page===header.page);
          check(`${item.name}: header precedes heading and answer`, header.top+header.height+9.99<=heading.top && heading.top+heading.height<=first.top);
        }
        const file=item.name+'-answers.pdf';fs.writeFileSync(path.join(output,file),Buffer.from(layout.bytes));delete layout.bytes;
        report.exports.push({file,kind:'answers',ids:item.ids,bytes:fs.statSync(path.join(output,file)).size,...layout});
      }
      for(const item of cases.filter(item=>item.reject)) check(`${item.name}: excessive commentary fails clearly`, /说明过长.*字号清晰/.test(item.result.error||'') && !item.result.bytes);
      check('No JavaScript errors', report.errors.length===0);
      return;
    }
    // A failed manifest request must release both actions and allow a new Worker
    // to retry; this also exercises an empty per-worker manifest cache.
    await page.evaluate(() => openExport(['chemy39-5-4']));
    await context.route('**/export-parts/polymer-questions.json*', route => route.abort());
    await page.locator('#export-start').click();
    await page.waitForFunction(() => document.getElementById('export-start').textContent.includes('重试'));
    check('Fragment failure enables both retry actions', await page.locator('#export-start').isEnabled() && await page.locator('#export-answers').isEnabled());
    await context.unroute('**/export-parts/polymer-questions.json*');
    const retried = page.waitForEvent('download', {timeout:240000});
    await page.locator('#export-start').click();
    await (await retried).saveAs(path.join(output, 'retry-polymer-questions.pdf'));
    const retryLayout = await page.evaluate(() => ({placements:window.lastExport.placements, headings:window.lastExport.headings, annotations:window.lastExport.annotations}));
    check('Retry downloads a real selected-question PDF', fs.readFileSync(path.join(output, 'retry-polymer-questions.pdf')).subarray(0,5).toString() === '%PDF-');
    report.exports.push({file:'retry-polymer-questions.pdf', kind:'questions', ids:['chemy39-5-4'], bytes:fs.statSync(path.join(output, 'retry-polymer-questions.pdf')).size, ...retryLayout});
    await page.locator('#export-close').click();

    if (!process.env.CHEMY_TEST_SINGLE && !process.argv.includes('--single')) {
      const boundary = await page.evaluate(async () => {
        const first = byTopic.get('有机化学')[0].id;
        const second = 'chemy39-5-4';
        async function png(height, label) {
          const canvas = document.createElement('canvas');canvas.width=1000;canvas.height=Math.max(1,Math.round(height*1000/(595.28-96)));
          const draw=canvas.getContext('2d');draw.fillStyle='#f5f8fa';draw.fillRect(0,0,canvas.width,canvas.height);draw.fillStyle='#123';draw.font='24px sans-serif';draw.fillText(label,20,30);
          return {bytes:new Uint8Array(await (await new Promise(resolve=>canvas.toBlob(resolve,'image/png'))).arrayBuffer())};
        }
        async function run(headerHeight, annotated) {
          const items=[{id:first,slug:'organic'},{id:second,slug:'polymer'}];
          if(annotated)items[1].annotation=await png(120,'关联说明排版回归测试');
          const request={items,kind:'answers',title:'Export boundary regression',version:pdfVersion};
          if(headerHeight>0)request.paperHeader=await png(headerHeight,'组卷说明排版回归测试');
          return new Promise((resolve,reject)=>{
            const worker=new Worker('pdf-worker.js');
            const timer=setTimeout(()=>{worker.terminate();reject(new Error('Boundary export timed out'));},180000);
            worker.onmessage=({data})=>{if(data.error){clearTimeout(timer);worker.terminate();reject(new Error(data.error));}else if(data.bytes){clearTimeout(timer);worker.terminate();resolve({...data,bytes:Array.from(new Uint8Array(data.bytes))});}};
            worker.onerror=event=>{clearTimeout(timer);worker.terminate();reject(new Error(event.message));};
            worker.postMessage(request);
          });
        }
        const baseline=await run(0,false);
        const previous=baseline.placements.filter(p=>p.id===first).at(-1);
        const remaining=841.89-previous.top-previous.height-55-22;
        const headerHeight=remaining-140-10;
        if(headerHeight<=0)throw new Error('Baseline no longer permits the intended 140-point boundary; update the fixture');
        const result=await run(headerHeight,true);
        const lastPrevious=result.placements.filter(p=>p.id===first).at(-1);
        return {...result, ids:[first,second],headerHeight,remainingBeforeHeading:841.89-lastPrevious.top-lastPrevious.height-55-22};
      });
      const heading = boundary.headings.find(h=>h.slug==='polymer');
      const annotation = boundary.annotations.find(a=>a.id==='chemy39-5-4');
      const firstBand = boundary.placements.find(p=>p.id==='chemy39-5-4');
      const prior = boundary.placements.filter(p=>p.id===boundary.ids[0]).at(-1);
      check('Annotation regression reaches the 140-point boundary', Math.abs(boundary.remainingBeforeHeading-140)<1);
      check('Topic heading moves with annotation and first question band', heading.page===annotation.page && heading.page===firstBand.page && heading.page>prior.page);
      check('Heading, annotation and question have correct order', heading.top+heading.height<=annotation.top && annotation.top+annotation.height<=firstBand.top);
      fs.writeFileSync(path.join(output,'annotation-boundary-answers.pdf'), Buffer.from(boundary.bytes));
      delete boundary.bytes;
      report.exports.push({file:'annotation-boundary-answers.pdf',kind:'answers',bytes:fs.statSync(path.join(output,'annotation-boundary-answers.pdf')).size,...boundary});
    }

    check('No JavaScript errors', report.errors.length === 0);
    await page.locator('img[src*="e39-p05-a04-02"]').first().scrollIntoViewIfNeeded();
    await page.screenshot({path:path.join(output,'polymer-web.png')});
  } finally {
    await browser.close();server.close();
    fs.writeFileSync(path.join(output, annotationMode ? 'annotation-browser-report.json' : patternMode ? `pattern-browser${patternTopics.length ? '-' + patternTopics.join('-') : ''}-report.json` : 'browser-report.json'), JSON.stringify(report, null, 2));
  }
})().catch(error => {console.error(error);server.close();process.exitCode=1;});
