/* Compose clean, font-subsetted native fragments, without whole-page Forms. */
importScripts('vendor/pdf-lib.min.js');
const {PDFDocument, PageSizes, StandardFonts, rgb, BlendMode, PDFArray, PDFDict, PDFName, PDFRef} = PDFLib;
const PROFILE = 'clean-vector-v1';
const MIN_ANNOTATED_SCALE = .85;
const indexes = new Map();

async function getIndex(slug, version, kind) {
  if (!/^[a-z]+$/.test(slug)) throw new Error('专题标识无效。');
  const key = `${slug}-${kind}-${version}`;
  if (!indexes.has(key)) {
    const response = await fetch(`export-parts/${slug}-${kind}.json?v=${encodeURIComponent(version)}-${PROFILE}`);
    if (!response.ok) throw new Error('分题 PDF 尚未准备好。维护者需运行 python scripts/build_export_parts.py 后重新发布；本地预览也需先完成这一步。');
    const data = await response.json();
    if (data.profile !== PROFILE || data.bookVersion !== version) throw new Error('题册正在更新，请刷新页面后重试。');
    indexes.set(key, data);
  }
  return indexes.get(key);
}

async function loadFragment(record) {
  if (!record || !/^[a-zA-Z0-9/._-]+\.pdf$/.test(record.path) || record.path.split('/').includes('..') || record.path.startsWith('/')) throw new Error('分题 PDF 索引无效。');
  const response = await fetch(`export-parts/${record.path}?v=${record.sha256}`);
  if (!response.ok) throw new Error('分题 PDF 暂时无法读取，请检查网络后重试。');
  const bytes = await response.arrayBuffer();
  if (record.bytes && bytes.byteLength !== record.bytes) throw new Error('分题 PDF 正在更新，请刷新页面后重试。');
  if (self.crypto?.subtle) {
    const digest = await crypto.subtle.digest('SHA-256', bytes);
    const actual = Array.from(new Uint8Array(digest), b => b.toString(16).padStart(2, '0')).join('');
    if (actual !== record.sha256) throw new Error('分题 PDF 与索引不一致，请刷新页面后重试。');
  }
  return PDFDocument.load(bytes);
}

// Every fragment resource has a unique name assigned by the builder. Copy its
// original content streams straight onto the target page, preserving native text.
function drawNative(out, target, source, x, y, scale=1) {
  const box = source.getMediaBox();
  const tx = x-box.x*scale, ty = y-box.y*scale;
  const resources = target.node.Resources();
  for (const [category, value] of source.node.Resources().entries()) {
    const dictionary = out.context.lookup(value);
    if (!(dictionary instanceof PDFDict)) continue;
    let destination = resources.lookupMaybe(category, PDFDict);
    if (!destination) { destination = out.context.obj({}); resources.set(category, destination); }
    for (const [name, ref] of dictionary.entries()) {
      const previous = destination.get(name);
      if (previous && previous.toString() !== ref.toString()) throw new Error('PDF 资源名称冲突，请重新生成分题文件。');
      if (category.toString() === '/Pattern') {
        // Pattern matrices use the page's initial coordinates, not the current
        // cm. Each band has its own names; clone rather than mutate a shared
        // font/graphics object used by another band or another output page.
        if (previous) throw new Error('PDF 图案被重复放置，请检查选题是否重复。');
        const pattern = out.context.lookup(ref).clone(out.context);
        const settings = pattern instanceof PDFDict ? pattern : pattern.dict;
        const matrix = settings.lookupMaybe(PDFName.of('Matrix'), PDFArray);
        const [a,b,c,d,e,f] = matrix ? matrix.asArray().map(v=>out.context.lookup(v).asNumber()) : [1,0,0,1,0,0];
        settings.set(PDFName.of('Matrix'), out.context.obj([scale*a,scale*b,scale*c,scale*d,scale*e+tx,scale*f+ty]));
        destination.set(name, out.context.register(pattern));
      } else destination.set(name, ref);
    }
  }
  const contentsRef = source.node.get(PDFName.of('Contents'));
  const contents = out.context.lookup(contentsRef);
  const streams = contents instanceof PDFArray ? contents.asArray() : contents ? [contentsRef] : [];
  // Ensure subsequent pdf-lib drawings start a new stream after the raw content.
  target.contentStream = undefined;
  target.contentStreamRef = undefined;
  // A cropped page clips even partially visible paths to its MediaBox. Preserve
  // that boundary when copying operators: a diagram's larger white background
  // must not cover previously placed bands on the destination page.
  target.node.addContentStream(out.context.register(out.context.stream(`q\n${scale} 0 0 ${scale} ${tx} ${ty} cm\n${box.x} ${box.y} ${box.width} ${box.height} re W n\n`)));
  for (const stream of streams) target.node.addContentStream(stream instanceof PDFRef ? stream : out.context.register(stream));
  target.node.addContentStream(out.context.register(out.context.stream('\nQ\n')));
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
    let page, cursor, pageCount = 0, previousSlug = '', footer;
    const frames = new Map(), placements = [], headings = [], annotations = [];
    const footerPages = new Set();
    function newPage() {
      page = out.addPage([width,height]); cursor = height-margin; pageCount++;
      page.drawText(String(pageCount), {x:width-68,y:30,size:9,font,color:rgb(.3,.3,.3)});
      if (footer) { drawNative(out,page,footer,50,31); footerPages.add(pageCount); }
    }
    async function drawNote(note,id,keep=0,prepared) {
      if (!note?.bytes) return;
      const image = prepared || await out.embedPng(note.bytes);
      const drawWidth = width-2*margin, drawHeight = drawWidth*image.height/image.width;
      if (drawHeight+keep > height-margin-bottom) throw new Error('关联说明过长，无法安全排版。');
      if (!page || cursor-bottom < drawHeight+keep) newPage();
      page.drawImage(image,{x:margin,y:cursor-drawHeight,width:drawWidth,height:drawHeight});
      annotations.push({id,page:pageCount,top:height-cursor,height:drawHeight});
      cursor -= drawHeight+10;
    }
    const paperHeaderImage = data.paperHeader?.bytes ? await out.embedPng(data.paperHeader.bytes) : null;
    for (let i=0; i<data.items.length; i++) {
      const item = data.items[i];
      const index = await getIndex(item.slug,data.version,kind);
      const record = index.questions[item.id];
      if (!record?.regions?.length) throw new Error('这道题的分题 PDF 缺失，请联系维护者重新生成。');
      self.postMessage({status:`正在读取第 ${i+1} / ${data.items.length} 道题…`});
      const source = await loadFragment(record);
      if (source.getPageCount() !== record.pages.length) throw new Error('分题 PDF 页数与索引不一致，请刷新后重试。');
      const copied = await out.copyPages(source,source.getPageIndices());
      const regions = record.regions;
      const annotationImage = kind === 'answers' && item.annotation?.bytes ? await out.embedPng(item.annotation.bytes) : null;
      const annotationSpace = annotationImage ? (width-2*margin)*annotationImage.height/annotationImage.width+10 : 0;
      const firstBand = regions[0].bands[0];
      const firstBandHeight = firstBand.bottom-firstBand.top;
      const headingHeight = 16, headingSpace = headingHeight+16;
      const headerImage = i === 0 ? paperHeaderImage : null;
      const headerSpace = headerImage ? (width-2*margin)*headerImage.height/headerImage.width+10 : 0;
      const hasNotes = !!(annotationImage || headerImage);
      // Plan the complete opening group before painting any note: paper
      // header, topic heading, answer annotation and the first safe block.
      // Reduce source text by at most 15%, even when both notes are present.
      const firstScale = hasNotes ? Math.min(1,
        (height-margin-bottom-headerSpace-annotationSpace-(previousSlug !== item.slug ? headingSpace : 0))/firstBandHeight) : 1;
      if (firstScale < MIN_ANNOTATED_SCALE) throw new Error(`${headerImage ? '卷首或关联' : '关联'}说明过长，无法在保证题目和答案字号清晰的同时与正文放在同一页；请减少说明内容后重试。`);
      const firstKeep = firstBandHeight*firstScale;
      if (headerImage) await drawNote(data.paperHeader,'paper-header',headingSpace+annotationSpace+firstKeep+10-1e-6,headerImage);
      if (previousSlug !== item.slug) {
        if (!frames.has(item.slug)) {
          const frameSource = await loadFragment(index.frame);
          frames.set(item.slug,await out.copyPages(frameSource,[0,1]));
        }
        const frame = frames.get(item.slug);
        footer = frame[0];
        if (page && !footerPages.has(pageCount)) { drawNative(out,page,footer,50,31); footerPages.add(pageCount); }
        const keep = hasNotes ? firstKeep : Math.min(firstBandHeight,height-margin-bottom-headingSpace);
        if (!page || cursor-bottom+(hasNotes ? 1e-6 : 0) < headingSpace+annotationSpace+keep) newPage();
        headings.push({slug:item.slug,sourcePage:0,page:pageCount,top:height-cursor,height:headingHeight});
        drawNative(out,page,frame[1],0,cursor-headingHeight); cursor -= headingSpace;
        previousSlug = item.slug;
      }
      if (annotationImage) await drawNote(item.annotation,item.id,firstKeep+10-1e-6,annotationImage);
      self.postMessage({status:`正在排版第 ${i+1} / ${data.items.length} 道题…`});
      let first = true;
      for (const region of regions) {
        let offset = 0;
        while (offset < region.bands.length) {
          const top = region.bands[offset].top;
          const initialHeight = region.bands[offset].bottom-top;
          const preferredScale = first && hasNotes ? firstScale : 1;
          if (!page || cursor-bottom+(first && hasNotes ? 1e-6 : 0) < Math.min(initialHeight*preferredScale,height-margin-bottom)) newPage();
          const capacity = cursor-bottom;
          let end = offset;
          while (end+1 < region.bands.length && (region.bands[end+1].bottom-top)*preferredScale <= capacity) end++;
          const inkBottom = region.bands[end].bottom;
          const naturalHeight = inkBottom-top;
          const scale = Math.min(preferredScale,capacity/naturalHeight);
          for (let n=offset; n<=end; n++) {
            const band = region.bands[n];
            drawNative(out,page,copied[band.page],(width-band.width*scale)/2,cursor-(band.bottom-top)*scale,scale);
          }
          const drawnHeight = naturalHeight*scale;
          placements.push({id:item.id,slug:item.slug,sourcePage:region.sourcePage,sourceTop:top,sourceBottom:inkBottom,scale,page:pageCount,top:height-cursor,height:drawnHeight,first});
          first = false; cursor -= drawnHeight;
          offset = end+1;
          if (offset < region.bands.length) cursor -= Math.min(18,Math.max(3,region.bands[offset].top-inkBottom));
          else cursor -= 10;
        }
      }
      cursor -= 12;
    }
    const watermarkWidth = width*.62, watermarkHeight = watermarkWidth*watermark.height/watermark.width;
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
