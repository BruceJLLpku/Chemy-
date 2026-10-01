"""Import the reviewed first paper without OCR, redrawing, or model transcription.

Extract native PDF characters into flowing HTML; render ONLY source diagram
regions as lossless images. Source PDFs stay unchanged. The manifest records
every reviewed boundary so a correction only regenerates affected content.
"""
import json
import re
import subprocess
from collections import Counter
from html import escape
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, NameObject
import pdfplumber
from PIL import Image
from paper1_manifest import ROOT, Q_SOURCE, A_SOURCE, PAPER, FIGURES, SLUGS
from write_questions import organic, electro

TMP = ROOT / 'tmp' / 'paper1'
ASSETS = ROOT / 'dist' / 'assets'
TMP.mkdir(parents=True, exist_ok=True)
ASSETS.mkdir(exist_ok=True)
SOURCES = {'q':Q_SOURCE, 'a':A_SOURCE}
START = {'q':4, 'a':3}
END = {'q':10, 'a':16}

def prepare(kind):
    """One native extraction and one render per source page, reused for all crops."""
    cache_path = TMP / f'{kind}-characters.json'
    if cache_path.exists():
        return json.loads(cache_path.read_text(encoding='utf8'))
    reader = PdfReader(SOURCES[kind])
    writer = PdfWriter()
    cache = {}
    with pdfplumber.open(SOURCES[kind]) as doc:
        for n in range(START[kind], END[kind] + 1):
            page = doc.pages[n-1]
            cache[n] = [{k:c[k] for k in ('text','x0','x1','top','bottom','size','fontname')}
                        for c in page.chars]
            # Strip ONLY page-wide background decoration, preserving all actual
            # figures and their masking/overprinting operations.
            backgrounds = {'/'+im['name'] for im in page.images
                           if im['width'] > 400 and im['height'] > 100
                           and 190 < im['top'] < 550}
            source_page = reader.pages[n-1]
            stream = ContentStream(source_page.get_contents(), reader)
            stream.operations = [(args,op) for args,op in stream.operations
                                 if not(op == b'Do' and str(args[0]) in backgrounds)]
            source_page[NameObject('/Contents')] = stream
            writer.add_page(source_page)
    writer.write(TMP / f'{kind}-clean.pdf')
    subprocess.run(['pdftoppm','-r','252','-png',str(TMP/f'{kind}-clean.pdf'),
                    str(TMP/f'{kind}-page')],check=True,stdout=subprocess.DEVNULL)
    cache_path.write_text(json.dumps(cache,ensure_ascii=False),encoding='utf8')
    return {str(k):v for k,v in cache.items()}

def in_box(c, box):
    x0,y0,x1,y1 = box
    return x0 <= (c['x0']+c['x1'])/2 <= x1 and y0 <= (c['top']+c['bottom'])/2 <= y1

def export_crops():
    for kind,n,x0,y0,x1,y1,name,label in FIGURES:
        index = n - START[kind] + 1
        digits = len(str(END[kind]-START[kind]+1))
        page_path = TMP / f'{kind}-page-{index:0{digits}d}.png'
        with Image.open(page_path) as im:
            scale = im.width / 595.32
            crop = im.crop(tuple(round(v*scale) for v in (x0,y0,x1,y1)))
            crop.save(ASSETS/f'{name}.webp',lossless=True,method=6)

def line_html(chars):
    anchors = [c for c in chars if c['size'] >= 9.8 and c['text'].strip()]
    if not anchors:
        raise ValueError('Unanchored native text: inspect source figure boundary')
    bottoms = sorted(c['bottom'] for c in anchors)
    baseline = bottoms[len(bottoms)//2]
    pieces = []
    previous = None
    current_tag = ''
    for c in sorted(chars, key=lambda c:c['x0']):
        if previous and c['x0']-previous['x1'] > 2.2:
            pieces.append(' ')
        text = c['text'].replace('\uf044','Δ')
        tag = ''
        if c['size'] < 9.5:
            if c['bottom'] < baseline-1.3:
                tag = 'sup'
            else:
                tag = 'sub'
        if tag != current_tag:
            if current_tag: pieces.append(f'</{current_tag}>')
            if tag: pieces.append(f'<{tag}>')
            current_tag = tag
        pieces.append(escape(text))
        previous = c
    if current_tag: pieces.append(f'</{current_tag}>')
    html = ''.join(pieces).strip()
    html = re.sub(r'^((?:\d+-)+\d+)', r'<strong>\1</strong>', html)
    return html

def native_blocks(chars):
    """Group on full-size character baselines; attach smaller sub/superscripts."""
    rows = []
    for c in sorted((c for c in chars if c['size'] >= 9.8 and c['text'].strip()),
                    key=lambda c:c['top']):
        center = (c['top']+c['bottom'])/2
        if rows and abs(center-rows[-1]['center']) < 2.2:
            rows[-1]['anchors'].append(c)
        else:
            rows.append({'center':center,'anchors':[c],'chars':[]})
    if not rows and chars:
        raise ValueError('Native extraction contains no full-size baseline')
    for c in chars:
        center = (c['top']+c['bottom'])/2
        row = min(rows,key=lambda r:abs(r['center']-center))
        if abs(row['center']-center)>9:
            raise ValueError(f'Unassigned character {c["text"]!r} at ({c["x0"]:.1f}, {c["top"]:.1f}); nearest baseline {row["center"]:.1f}')
        row['chars'].append(c)
    return [(min(c['top'] for c in r['anchors']), line_html(r['chars']),
             min(c['x0'] for c in r['anchors'])) for r in rows]

AUDIT = []
def section(kind, ranges):
    parts = []
    for n,y0,y1 in ranges:
        chars = [c for c in CACHE[kind][str(n)]
                 if y0-1.1 <= c['top'] < y1 and 86 <= c['x0'] < 512 and c['text'].strip()]
        figures = [f for f in FIGURES if f[0]==kind and f[1]==n and y0<=f[3]<y1]
        text_chars = [c for c in chars if not any(in_box(c,f[2:6]) for f in figures)]
        # Preserve explicit source spaces, including narrow spaces in justified
        # lines; guessing solely from geometric gaps can join “0.400 mol SF4”.
        anchors=[c for c in text_chars if c['size']>=9.8]
        spaces=[c for c in CACHE[kind][str(n)] if c['text']==' '
                and y0-1.1<=c['top']<y1 and 86<=c['x0']<512
                and not any(in_box(c,f[2:6]) for f in figures)
                and any(abs((c['top']+c['bottom']-a['top']-a['bottom'])/2)<2.3
                        for a in anchors)]
        try:
            rows = native_blocks(text_chars+spaces) if text_chars else []
        except ValueError as e:
            raise ValueError(f'{kind} original page {n}, range {y0}-{y1}: {e}') from e
        events = [(top,'text',html,x) for top,html,x in rows]
        for f in figures:
            _,_,x0,top,x1,bottom,name,label = f
            with Image.open(ASSETS/f'{name}.webp') as im:w,h=im.size
            width = round((x1-x0)*1.7)
            html = (f'<figure class="source-figure"><a href="assets/{name}.webp" '
                    f'target="_blank" rel="noopener" aria-label="查看大图：{escape(label)}">'
                    f'<img src="assets/{name}.webp" alt="{escape(label)}" width="{w}" '
                    f'height="{h}" loading="lazy" style="--figure-width:{width}px"></a></figure>')
            events.append((top,'figure',html,0))
        pending = []
        last_top = None
        def flush():
            if pending:parts.append('<p>'+''.join(pending)+'</p>');pending.clear()
        for top,event,html,x in sorted(events,key=lambda t:t[0]):
            if event=='figure':flush();parts.append(html);last_top=None;continue
            # New subquestion, source paragraph indent, or larger source gap.
            new_para = bool(re.match(r'^(?:<strong>|第\s*\d|\(?\d\)|\d[）)]|关于)',html))
            if pending and (new_para or x>95 or (last_top is not None and top-last_top>19)):
                flush()
            # Keep separated source lines from accidentally joining Latin
            # words/formulae (e.g. the final formula D and the next label E).
            if pending:
                tail=re.sub('<[^>]+>','',pending[-1]).rstrip()
                head=re.sub('<[^>]+>','',html).lstrip()
                if tail and head and tail[-1].isascii() and head[0].isascii():
                    pending.append(' ')
            pending.append(html)
            last_top=top
        flush()
        assigned = len(text_chars)+sum(any(in_box(c,f[2:6]) for f in figures) for c in chars)
        if assigned != len(chars):raise AssertionError('Source character coverage mismatch')
        AUDIT.append({'kind':kind,'page':n,'top':y0,'bottom':y1,
                      'sourceCharacters':len(chars),'nativeCharacters':len(text_chars),
                      'figureCharacters':len(chars)-len(text_chars),'figures':[f[6] for f in figures]})
    return ''.join(parts)

if __name__ == '__main__':
    CACHE = {kind:prepare(kind) for kind in SOURCES}
    export_crops()
    approved = {6:electro,8:organic}
    items = []
    for spec in PAPER:
        n=spec['number']
        item = dict(approved[n]) if spec.get('approved') else {
            'id':f'chemy39-1-{n}', 'body':section('q',spec['question']),
            'answer':section('a',spec['answer'])}
        item.update({k:spec[k] for k in ('number','title','topic','points','percent')})
        item['paper']=1
        item['pdfReady']=all((ROOT/'dist'/'downloads'/f'{SLUGS[spec["topic"]]}-{kind}.pdf').exists()
                            for kind in ('questions','answers'))
        def pages(ranges):
            ns=sorted({r[0] for r in ranges})
            return str(ns[0]) if len(ns)==1 else f'{ns[0]}–{ns[-1]}'
        item['questionPages']=pages(spec['printQuestion'])
        item['answerPages']=pages(spec['answer'])
        if n==6:item['answerPages']='7–9'
        if n==8:item['answerPages']='10–11'
        if n==9:item['answerPages']='11–13'
        if n==7:
            item['answer']+='<div class="note">原答案在 Na-O 高度计算的“解得”行将 h₁ 写成了 h₂；这里保留原文，数值与后续晶胞参数按原答案展示。</div>'
        items.append(item)
    (ROOT/'dist'/'questions.json').write_text(json.dumps(items,ensure_ascii=False,indent=2),encoding='utf8')
    common={'instructions':section('q',[(4,132,289)]),
            'scoring':section('a',[(3,320,459)])}
    (ROOT/'dist'/'paper1-notes.json').write_text(json.dumps(common,ensure_ascii=False,indent=2),encoding='utf8')
    (TMP/'coverage.json').write_text(json.dumps(AUDIT,ensure_ascii=False,indent=2),encoding='utf8')
    print('Imported',len(items),'complete questions;',dict(Counter(q['topic'] for q in items)))
    print('Original diagram captures:',len(FIGURES),'; native extraction ranges:',len(AUDIT))
