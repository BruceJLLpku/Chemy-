/* Convert the existing question-bank markup into editable Word content. */
(function () {
  'use strict';
  let library;
  function loadLibrary() {
    if (!library) library = new Promise((resolve, reject) => {
      const script = document.createElement('script');
      script.src = 'vendor/docx-9.6.1.js';
      script.onload = () => resolve(window.docx);
      script.onerror = () => {
        script.remove();
        library = null;
        reject(new Error('暂时无法加载 Word 导出工具。'));
      };
      document.head.append(script);
    });
    return library;
  }

  const blocks = new Set(['p', 'div', 'figure', 'figcaption', 'table', 'ol', 'ul', 'li']);

  async function build({title, introduction, items}) {
    const {Document, Packer, Paragraph, TextRun, ImageRun, Table, TableRow, TableCell,
      HeadingLevel, AlignmentType, WidthType, Footer, PageNumber, Math: WordMath, MathRun, MathFraction, MathSuperScript} = await loadLibrary();
    const font = {ascii: 'Times New Roman', hAnsi: 'Times New Roman', eastAsia: 'SimSun'};

    async function picture(element) {
      const response = await fetch(element.src);
      if (!response.ok) throw new Error('有原题图片无法加载，请重试 Word 下载。');
      const bitmap = await createImageBitmap(await response.blob());
      try {
        const canvas = document.createElement('canvas');
        const renderScale = Math.min(1, 1600 / Math.max(bitmap.width, bitmap.height));
        canvas.width = Math.max(1, Math.round(bitmap.width * renderScale));
        canvas.height = Math.max(1, Math.round(bitmap.height * renderScale));
        canvas.getContext('2d').drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        const png = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
        if (!png) throw new Error('有原题图片无法转换为 Word 图片。');
        const requested = Number.parseFloat(element.style.getPropertyValue('--figure-width')) || bitmap.width;
        const scale = Math.min(1, requested / bitmap.width, 560 / bitmap.width, 720 / bitmap.height);
        const alt = element.alt || '原题图片';
        return new ImageRun({type: 'png', data: new Uint8Array(await png.arrayBuffer()),
          transformation: {width: Math.max(1, Math.round(bitmap.width * scale)), height: Math.max(1, Math.round(bitmap.height * scale))},
          altText: {name: alt, title: alt, description: alt}});
      } finally { bitmap.close(); }
    }

    function mathParts(node) {
      if (node.nodeType === Node.TEXT_NODE) return node.textContent.trim() ? [new MathRun(node.textContent)] : [];
      if (node.localName === 'mfrac') return [new MathFraction({
        numerator: mathParts(node.children[0]), denominator: mathParts(node.children[1]),
      })];
      if (node.localName === 'msup') return [new MathSuperScript({
        children: mathParts(node.children[0]), superScript: mathParts(node.children[1]),
      })];
      return [...node.childNodes].flatMap(mathParts);
    }

    async function runs(nodes, style = {}) {
      const result = [];
      for (const node of nodes) {
        if (node.nodeType === Node.TEXT_NODE) {
          result.push(new TextRun({...style, text: node.textContent.replace(/\s+/g, ' ')}));
          continue;
        }
        const tag = node.localName;
        if (tag === 'img') result.push(await picture(node));
        else if (tag === 'br') result.push(new TextRun({break: 1}));
        else if (tag === 'math') result.push(new WordMath({children: mathParts(node)}));
        else if (tag) result.push(...await runs(node.childNodes, {...style,
          bold: style.bold || tag === 'strong' || tag === 'b',
          italics: style.italics || tag === 'i' || tag === 'em',
          superScript: style.superScript || tag === 'sup',
          subScript: style.subScript || tag === 'sub',
        }));
      }
      return result;
    }

    async function content(nodes) {
      const paragraphs = [];
      let inline = [];
      async function flush() {
        if (inline.some(node => node.nodeType !== Node.TEXT_NODE || node.textContent.trim())) {
          const text=inline.map(node=>node.textContent).join('').trim();
          paragraphs.push(new Paragraph({keepNext: /[:：]$/.test(text)||/^[\u0300-\u036f\u20d0-\u20ff]+$/.test(text),children: await runs(inline)}));
        }
        inline = [];
      }
      for (const node of nodes) {
        const tag = node.localName;
        if (!blocks.has(tag)) { inline.push(node); continue; }
        await flush();
        if (tag === 'table') {
          const rows = [];
          for (const row of node.rows) {
            const children = [];
            for (const cell of row.cells) {
              const body = await content(cell.childNodes);
              children.push(new TableCell({columnSpan: cell.colSpan, rowSpan: cell.rowSpan,
                children: body.length ? body : [new Paragraph('')]}));
            }
            rows.push(new TableRow({children, tableHeader: row.parentElement.localName === 'thead'}));
          }
          if (rows.length) paragraphs.push(new Table({rows, width: {size: 100, type: WidthType.PERCENTAGE}}));
        } else if (tag === 'figure') {
          for (const image of node.querySelectorAll('img')) {
            paragraphs.push(new Paragraph({alignment: AlignmentType.CENTER, children: [await picture(image)]}));
          }
          for (const caption of node.querySelectorAll('figcaption')) {
            paragraphs.push(new Paragraph({alignment: AlignmentType.CENTER, children: await runs(caption.childNodes)}));
          }
        } else if (tag === 'ol' || tag === 'ul') {
          let number = tag === 'ol' ? node.start : 1;
          for (const item of node.children) {
            const originalNumber = item.querySelector(':scope > .number');
            const questionBody = item.querySelector(':scope > div');
            if (node.classList.contains('subquestions') && originalNumber && questionBody) {
              const body = questionBody.cloneNode(true);
              const label = originalNumber.cloneNode(true);
              body.prepend(label, document.createTextNode(' '));
              paragraphs.push(...await content(body.childNodes));
              continue;
            }
            const label = tag === 'ol' ? `${number++}. ` : '• ';
            paragraphs.push(new Paragraph({indent: {left: 360}, children: [new TextRun(label), ...await runs(item.childNodes)]}));
          }
        } else {
          paragraphs.push(...await content(node.childNodes));
        }
      }
      await flush();
      return paragraphs;
    }

    function parse(html) {
      const template = document.createElement('template');
      template.innerHTML = html;
      return template.content.childNodes;
    }

    const children = [new Paragraph({text: title, heading: HeadingLevel.TITLE}),
      new Paragraph({alignment: AlignmentType.CENTER, keepNext: true, spacing: {after: 280},
        children: [new TextRun({text: `Chemy 化学竞赛 · 共 ${items.length} 道完整大题`, size: 18})]})];
    if (introduction) {
      children.push(new Paragraph({text: '知识介绍', heading: HeadingLevel.HEADING_1}));
      for (const block of window.ChemyLecture.blocks(introduction)) {
        children.push(new Paragraph({
          ...(block.kind==='heading'?{heading: HeadingLevel.HEADING_2,keepNext:true}:{}),
          ...(block.kind==='formula'?{alignment:AlignmentType.CENTER,keepLines:true,spacing:{before:120,after:180}}:{}),
          children: await runs(parse(block.html)),
        }));
      }
    }
    for (const [index, item] of items.entries()) {
      children.push(new Paragraph({text: `第 ${index + 1} 题`, heading: HeadingLevel.HEADING_1}));
      children.push(new Paragraph({keepNext: true, spacing: {after: 100}, children: [new TextRun({text: item.origin, size: 18})]}));
      children.push(...await content(parse(item.html)));
    }
    const paper = new Document({
      title, creator: 'Chemy',
      styles: {default: {
        document: {run: {font, size: 22, color: '000000'}, paragraph: {spacing: {line: 360, after: 120}, widowControl: true}},
        title: {run: {font, size: 34, bold: true, color: '000000'}, paragraph: {alignment:AlignmentType.CENTER,spacing: {after: 120}, keepNext: true}},
        heading1: {run: {font, size: 26, bold: true, color: '000000'}, paragraph: {spacing: {before: 240, after: 100}, keepNext: true}},
        heading2: {run: {font, size: 22, bold: true, color: '000000'}, paragraph: {spacing: {before: 200, after: 100}, keepNext: true}},
      }},
      sections: [{properties: {page: {size: {width: 11906, height: 16838},
        margin: {top: 1134, bottom: 1134, left: 1134, right: 1134}}},
        footers:{default:new Footer({children:[new Paragraph({alignment:AlignmentType.CENTER,
          children:[new TextRun({text:'Chemy  ·  ',size:18}),new TextRun({children:[PageNumber.CURRENT],size:18}),
            new TextRun({text:' / ',size:18}),new TextRun({children:[PageNumber.TOTAL_PAGES],size:18})]})]})},children}],
    });
    return Packer.toBlob(paper);
  }
  window.ChemyWord = {build};
})();
