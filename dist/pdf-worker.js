/* Original vector pages are clipped only at indexed blank gaps, then flowed onto A4. */
importScripts('vendor/pdf-lib.min.js');
const {PDFDocument, PageSizes, StandardFonts, rgb, BlendMode, PDFArray, PDFName} = PDFLib;
const indexes = new Map();
let cachedBook;
async function getIndex(slug,version,kind='questions') {
  const key = `${slug}-${kind}-${version}`;
  if (!indexes.has(key)) {
    const response = await fetch(`export-index/${slug}${kind === 'answers' ? '-answers' : ''}.json?v=${encodeURIComponent(version)}-continuous-v2`);
    if (!response.ok) throw new Error('题目下载索引暂时无法读取，请稍后重试。');
    indexes.set(key, await response.json());
  }
  const data = indexes.get(key);
  if (data.bookVersion !== version) throw new Error('题册正在更新，请刷新页面后重试。');
  return data.questions;
}
async function getBook(slug, version,kind='questions') {
  if (cachedBook?.slug === slug && cachedBook?.kind === kind && cachedBook?.version === version) return cachedBook.doc;
  self.postMessage({status:'正在读取专题题册，首次下载可能需要稍候…'});
  const response = await fetch(`downloads/${slug}-${kind}.pdf?v=${encodeURIComponent(version)}-watermark-v1`);
  if (!response.ok) throw new Error('专题题册暂时无法读取，请检查网络后重试。');
  const doc = await PDFDocument.load(await response.arrayBuffer());
  // A source-page watermark must not be clipped and repeated with each question.
  // Remove only our separate decorative layer, then stamp each final page once.
  for (const page of doc.getPages()) {
    const value = page.node.Contents();
    const streams = value instanceof PDFArray ? value.asArray() : value ? [value] : [];
    const clean = streams.filter(ref => !doc.context.lookup(ref).dict.get(PDFName.of('ChemyWatermark')));
    if (clean.length !== streams.length) page.node.set(PDFName.of('Contents'),doc.context.obj(clean));
  }
  cachedBook = {slug,kind,version,doc};
  return doc;
}
self.onmessage = async ({data}) => {
  try {
    const kind = data.kind === 'answers' ? 'answers' : 'questions';
    if (!Array.isArray(data.items) || !data.items.length) throw new Error('请先选择题目。');
    const out = await PDFDocument.create();
    out.setTitle(data.title); out.setAuthor('Chemy 化学奥林匹克团队');
    out.setCreator('Chemy 专题题库 · 选题下载'); out.setLanguage('zh-CN');
    const [width,height] = PageSizes.A4;
    const margin = 48, bottom = 55;
    const font = await out.embedFont(StandardFonts.TimesRoman);
    const watermarkResponse = await fetch('assets/chemy-watermark.jpg');
    if (!watermarkResponse.ok) throw new Error('Chemy 水印暂时无法读取，请稍后重试。');
    const watermark = await out.embedJpg(await watermarkResponse.arrayBuffer());
    let page, cursor, pageCount = 0, copiedSlug = '', copiedPages, footer;
    const placements = [];
    const headings = [];
    const annotations = [];
    const footerPages = new Set();
    function newPage() {
      page = out.addPage([width,height]); cursor = height-margin; pageCount++;
      page.drawText(String(pageCount), {x:width-68,y:30,size:9,font,color:rgb(.3,.3,.3)});
      if (footer) { page.drawPage(footer,{x:50,y:31}); footerPages.add(pageCount); }
    }
    async function drawNote(note,id,keep=0) {
      if (!note?.bytes) return;
      const image = await out.embedPng(note.bytes);
      const drawWidth = width-2*margin, drawHeight = drawWidth*image.height/image.width;
      if (drawHeight+keep > height-margin-bottom) throw new Error('关联说明过长，无法安全排版。');
      if (!page || cursor-bottom < drawHeight+keep) newPage();
      page.drawImage(image,{x:margin,y:cursor-drawHeight,width:drawWidth,height:drawHeight});
      annotations.push({id,page:pageCount,top:height-cursor,height:drawHeight});
      cursor -= drawHeight+10;
    }
    await drawNote(data.paperHeader,'paper-header',90);
    for (let i=0; i<data.items.length; i++) {
      const item = data.items[i];
      const index = await getIndex(item.slug,data.version,kind);
      const regions = index[item.id];
      if (!regions?.length) throw new Error('这道题的下载索引缺失，请稍后重试。');
      const source = await getBook(item.slug,data.version,kind);
      if (copiedSlug !== item.slug) {
        const ids = [...new Set(data.items.filter(q => q.slug === item.slug).flatMap(q => {
          if (!index[q.id]?.length) throw new Error('所选题目的下载索引缺失，请刷新后重试。');
          return index[q.id].map(r => r.page);
        }))];
        const copied = await out.copyPages(source,ids);
        copiedPages = new Map(ids.map((id,n) => [id,copied[n]]));
        copiedSlug = item.slug;
        // Preserve the copyright line without the source book's page counter.
        footer = await out.embedPage(copied[0],{left:50,right:width-90,bottom:31,top:44});
        if (page && !footerPages.has(pageCount)) { page.drawPage(footer,{x:50,y:31}); footerPages.add(pageCount); }
        // Keep the complete centered masthead from the original-paper layout.
        // The second line is the full-book count and does not describe a selection.
        const headingTop = 47, headingBottom = 63;
        const label = await out.embedPage(copied[0],{left:0,right:width,bottom:height-headingBottom,top:height-headingTop});
        const headingHeight = headingBottom-headingTop, headingSpace = headingHeight+16;
        const firstBand = regions[0].bands[0];
        if (!page || cursor-bottom < headingSpace+Math.min(firstBand[1]-firstBand[0],height-margin-bottom-headingSpace)) newPage();
        headings.push({slug:item.slug,sourcePage:ids[0],page:pageCount,top:height-cursor,height:headingHeight});
        page.drawPage(label,{x:0,y:cursor-headingHeight}); cursor -= headingSpace;
      }
      if (kind === 'answers') await drawNote(item.annotation,item.id,Math.min(90,regions[0].bands[0][1]-regions[0].bands[0][0]));
      self.postMessage({status:`正在排版第 ${i+1} / ${data.items.length} 道题…`});
      let first = true;
      for (const region of regions) {
        let offset = 0;
        while (offset < region.bands.length) {
          const top = region.bands[offset][0];
          const initialHeight = region.bands[offset][1]-top;
          if (!page || cursor-bottom < Math.min(initialHeight,height-margin-bottom)) newPage();
          const capacity = cursor-bottom;
          let end = offset;
          while (end+1 < region.bands.length && region.bands[end+1][1]-top <= capacity) end++;
          const inkBottom = region.bands[end][1];
          const naturalHeight = inkBottom-top;
          // A single oversized diagram stays whole and is scaled to a fresh page.
          const scale = Math.min(1,capacity/naturalHeight);
          const sourcePage = copiedPages.get(region.page);
          const h = sourcePage.getHeight();
          const embedded = await out.embedPage(sourcePage,{left:0,right:sourcePage.getWidth(),top:h-top,bottom:h-inkBottom});
          const drawnHeight = naturalHeight*scale;
          page.drawPage(embedded,{x:(width-sourcePage.getWidth()*scale)/2,y:cursor-drawnHeight,xScale:scale,yScale:scale});
          placements.push({id:item.id,slug:item.slug,sourcePage:region.page,sourceTop:top,sourceBottom:inkBottom,scale,page:pageCount,top:height-cursor,height:drawnHeight,first});
          first = false; cursor -= drawnHeight;
          offset = end+1;
          if (offset < region.bands.length) {
            const gap = region.bands[offset][0]-inkBottom;
            cursor -= Math.min(18, Math.max(3,gap));
          } else cursor -= 10;
        }
      }
      cursor -= 12;
    }
    const watermarkWidth = width*.62;
    const watermarkHeight = watermarkWidth*watermark.height/watermark.width;
    for (const sheet of out.getPages()) sheet.drawImage(watermark,{
      x:(width-watermarkWidth)/2,y:(height-watermarkHeight)/2,
      width:watermarkWidth,height:watermarkHeight,opacity:.18,blendMode:BlendMode.Multiply
    });
    const bytes = await out.save();
    self.postMessage({bytes:bytes.buffer,placements,headings,annotations},[bytes.buffer]);
  } catch (error) {
    self.postMessage({error:error instanceof TypeError ? '下载中断，请检查网络后重试。' : error.message || 'PDF 生成失败，请重试。'});
  }
};
