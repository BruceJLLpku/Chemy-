/* Original vector pages are clipped only at indexed blank gaps, then flowed onto A4. */
importScripts('vendor/pdf-lib.min.js');
const {PDFDocument, PageSizes, StandardFonts, rgb, BlendMode, PDFArray, PDFName} = PDFLib;
const indexes = new Map();
let cachedBook;
async function getIndex(slug,version) {
  if (!indexes.has(slug)) {
    const response = await fetch(`export-index/${slug}.json?v=1`);
    if (!response.ok) throw new Error('题目下载索引暂时无法读取，请稍后重试。');
    indexes.set(slug, await response.json());
  }
  const data = indexes.get(slug);
  if (data.bookVersion !== version) throw new Error('题册正在更新，请刷新页面后重试。');
  return data.questions;
}
async function getBook(slug, version) {
  if (cachedBook?.slug === slug) return cachedBook.doc;
  self.postMessage({status:'正在读取专题题册，首次下载可能需要稍候…'});
  const response = await fetch(`downloads/${slug}-questions.pdf?v=${encodeURIComponent(version)}-watermark-v1`);
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
  cachedBook = {slug,doc};
  return doc;
}
self.onmessage = async ({data}) => {
  try {
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
    function newPage() {
      page = out.addPage([width,height]); cursor = height-margin; pageCount++;
      page.drawText('Chemy', {x:62,y:height-30,size:10,font,color:rgb(.3,.3,.3)});
      page.drawText(String(pageCount), {x:width-68,y:30,size:9,font,color:rgb(.3,.3,.3)});
      if (footer) page.drawPage(footer,{x:50,y:24});
    }
    for (let i=0; i<data.items.length; i++) {
      const item = data.items[i];
      const index = await getIndex(item.slug,data.version);
      const regions = index[item.id];
      if (!regions?.length) throw new Error('这道题的下载索引缺失，请稍后重试。');
      const source = await getBook(item.slug,data.version);
      if (copiedSlug !== item.slug) {
        const ids = [...new Set(data.items.filter(q => q.slug === item.slug).flatMap(q => index[q.id].map(r => r.page)))];
        const copied = await out.copyPages(source,ids);
        copiedPages = new Map(ids.map((id,n) => [id,copied[n]]));
        copiedSlug = item.slug;
        footer = await out.embedPage(copied[0],{left:50,right:width-90,bottom:24,top:44});
        const label = await out.embedPage(copied[0],{left:0,right:width,bottom:height-51,top:height-35});
        const firstBand = regions[0].bands[0];
        if (!page || cursor-bottom < 30+firstBand[1]-firstBand[0]) newPage();
        page.drawPage(label,{x:0,y:cursor-16}); cursor -= 30;
      }
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
    self.postMessage({bytes:bytes.buffer,placements},[bytes.buffer]);
  } catch (error) {
    self.postMessage({error:error instanceof TypeError ? '下载中断，请检查网络后重试。' : error.message || 'PDF 生成失败，请重试。'});
  }
};
