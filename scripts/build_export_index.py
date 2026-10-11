"""Index visible question regions and safe line/figure breaks in reviewed PDF books.

Only geometry is published. Original books, source content, and numbering stay intact.
Run with the bundled Python runtime (pdfplumber and pypdf).
"""
import json
from io import BytesIO
from pathlib import Path
import pdfplumber
import pypdfium2 as pdfium
import numpy as np
from pdf_watermark import unwatermarked_bytes

ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / 'tmp/library/books'
BOOKS = ROOT / 'dist/downloads'

def merge(bands):
    result = []
    for a, b in sorted(bands):
        if result and a <= result[-1][1] + 2:
            result[-1][1] = max(b, result[-1][1])
        else:
            result.append([a, b])
    return result

def build(slug):
    index = json.loads((ROOT / 'data/print_index.json').read_text(encoding='utf8'))[slug+'-questions']
    records = {r['id']: r for r in index}
    heads = {}
    for path in PARTS.glob('*-'+slug+'-q.layout.json'):
        layout = json.loads(path.read_text(encoding='utf8'))
        if not layout['ledger'] or layout['ledger'][0]['id'] not in records:
            continue
        first = layout['ledger'][0]
        offset = records[first['id']]['firstPage'] - first['firstPage']
        for h in layout['heads']:
            if h['id'] in records:
                heads[h['id']] = (h['page']+offset-1, h['cursor'])
    assert set(heads) == set(records), (slug, set(records)-set(heads))
    output = {}
    original_ink = unwatermarked_bytes(BOOKS / (slug+'-questions.pdf'))
    rendered = pdfium.PdfDocument(original_ink)
    with pdfplumber.open(BytesIO(original_ink)) as pdf:
        page_regions = {}
        for i, record in enumerate(index):
            page, cursor = heads[record['id']]
            assert page == record['firstPage']-1
            for n in range(page, record['lastPage']):
                top = pdf.pages[n].height-cursor if n == page else 96
                bottom = pdf.pages[n].height-70
                if i+1 < len(index):
                    next_page, next_cursor = heads[index[i+1]['id']]
                    if next_page == n:
                        bottom = min(bottom, pdf.pages[n].height-next_cursor-3)
                page_regions.setdefault(n, []).append((record['id'], top, bottom, n == page))
        for n, regions in page_regions.items():
            page = pdf.pages[n]
            bitmap = rendered[n].render(scale=1.5)
            pixels = np.asarray(bitmap.to_pil().convert('RGB'))
            ink = (pixels[:,45:-38,:].min(axis=2) < 230).any(axis=1)
            objects = [c for c in page.chars if c['text'].strip()] + page.images
            for obj in page.curves + page.rects + page.lines:
                color = obj.get('non_stroking_color')
                if obj.get('fill') and not obj.get('stroke') and isinstance(color, (list,tuple)) and min(color[:3]) > .98:
                    continue
                objects.append(obj)
            for qid, top, bottom, first in regions:
                visible = np.flatnonzero(ink[max(0,int(top*1.5)):int(bottom*1.5)])
                assert len(visible), (slug,qid,n,'empty visible region')
                # PDF text extractors include invisible content outside nested clips.
                # Use rendered ink to trim it, while vector bounds protect actual text/figures.
                origin = max(0,int(top*1.5))
                top = max(top,(origin+int(visible[0]))/1.5-1)
                bottom = min(bottom,(origin+int(visible[-1])+1)/1.5+1)
                bands = merge([[max(top, o['top']-.6), min(bottom, o['bottom']+.6)] for o in objects
                               if o['bottom'] >= top and o['top'] < bottom and o['x1'] > 30 and o['x0'] < page.width-25
                               and ink[max(0,int(max(top,o['top']-.6)*1.5)):int(min(bottom,o['bottom']+.6)*1.5)+1].any()])
                bands = [b for b in bands if b[1] > b[0]]
                assert bands, (slug, qid, n)
                # Keep the numbered heading, source, and first body line together.
                if first:
                    i = next((i for i,b in enumerate(bands) if b[1] >= top+65), len(bands)-1)
                    bands = [[bands[0][0], bands[i][1]]] + bands[i+1:]
                output.setdefault(qid, []).append({'page': n, 'bands': [[round(a,2), round(b,2)] for a,b in bands]})
            page.close()
            bitmap.close()
            if n % 50 == 0:
                print(slug, n+1, '/', len(pdf.pages), flush=True)
    rendered.close()
    assert set(output) == set(records)
    target = ROOT / 'dist/export-index' / (slug+'.json')
    target.parent.mkdir(exist_ok=True)
    version = json.loads((ROOT/'dist/numbering.json').read_text(encoding='utf8'))['version']
    target.write_text(json.dumps({'version':1,'bookVersion':version,'questions':output},ensure_ascii=False,separators=(',',':')),encoding='utf8')
    print('DONE',slug,len(output),target.stat().st_size,flush=True)

if __name__ == '__main__':
    import sys
    from concurrent.futures import ProcessPoolExecutor
    slugs = sys.argv[1:] or [p.stem.removesuffix('-questions') for p in BOOKS.glob('*-questions.pdf')]
    # Separate processes are required because PDFium itself is not thread-safe.
    with ProcessPoolExecutor(max_workers=3) as pool:
        list(pool.map(build,slugs))
