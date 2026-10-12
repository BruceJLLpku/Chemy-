"""Check every source page's visible ink survives native compact book layout."""
import argparse
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from io import BytesIO
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from pypdf import PdfReader
from build_continuous_books import ROOT, SOURCE, DATA, W, H, TOP, BOTTOM, QUESTION_GAP
from fast_pdf import pikepdf
from pdf_typography import STYLE,groups


def check_book(path):
    layout = json.loads(path.read_text(encoding='utf8'))
    assert layout['profile'] == 'continuous-native-v2'
    book = ROOT/'dist/downloads'/path.with_suffix('.pdf').name
    assert hashlib.sha256(book.read_bytes()).hexdigest() == layout['sha256']
    entries = layout['records']
    assert layout['pages'] < layout['sourcePages'], book.name
    assert [r['number'] for r in entries] == list(range(1,len(entries)+1))
    assert set(layout['questions']) == {r['id'] for r in entries}
    assert all(1 <= r['firstPage'] <= r['lastPage'] <= layout['pages'] for r in entries)
    outline = PdfReader(book).outline
    assert len(outline) == len(entries), (book.name,'bookmark count')
    placements = layout['placements']
    by_page,by_source,by_id = {},{},{}
    for p in placements:
        assert p['scale'] > .95, (book.name,p,'unexpectedly shrunk content')
        assert p['top'] >= TOP-.01 and p['top']+p['height'] <= H-BOTTOM+.01
        by_page.setdefault(p['page'],[]).append(p)
        by_source.setdefault(p['sourcePage'],[]).append(p)
        by_id.setdefault(p['id'],[]).append(p)
    for parts in by_page.values():
        assert all(a['top']+a['height'] <= b['top']+.01 for a,b in zip(parts,parts[1:])), (book.name,'overlapping body')
    joined = cross_paper = 0
    for a,b in zip(entries,entries[1:]):
        if a['lastPage'] == b['firstPage']:
            joined += 1
            if (a['sourceEdition'],a['sourcePaper']) != (b['sourceEdition'],b['sourcePaper']):
                cross_paper += 1
        else:
            last,first = by_id[a['id']][-1],by_id[b['id']][0]
            remaining = H-BOTTOM-(last['top']+last['height'])-QUESTION_GAP
            first_band = layout['questions'][b['id']][0]['bands'][0]
            assert first_band[1]-first_band[0] > remaining-.1, (book.name,a['id'],b['id'],'unnecessary new page')
    assert joined > 0 and cross_paper > 0, (book.name,'paper boundaries still force pages')
    source_path = SOURCE/book.name
    with pikepdf.open(source_path) as source,pikepdf.open(book) as current:
        for page in source.pages:
            value = page.obj.get('/Contents')
            streams = list(value) if isinstance(value,pikepdf.Array) else [value]
            page.obj['/Contents'] = pikepdf.Array([s for s in streams if not s.get('/ChemyWatermark',False)])
        assert set(by_source) == set(range(len(source.pages))), (book.name,'source page missing')
        seen = set()
        for page in current.pages:
            streams = list(page.obj['/Contents'])
            assert sum(bool(s.get('/ChemyWatermark',False)) for s in streams) == 1
            for name,form in page.obj['/Resources']['/XObject'].items():
                if not name.startswith('/Source'):
                    continue
                number = int(name.removeprefix('/Source'))
                if number not in seen:
                    expected = source.pages[number].as_form_xobject().read_bytes()
                    if form.get('/ChemyTypography') == STYLE:
                        assert form.read_bytes() == expected+b'\nq /ChemyTypesetHeadings Do Q\n'
                        old_objects=source.pages[number].as_form_xobject()['/Resources']['/XObject']
                        objects=form['/Resources']['/XObject']
                        assert objects['/Static'].read_bytes()==old_objects['/Static'].read_bytes(),(book.name,number,'original body changed')
                        ids=[p['id'] for p in by_source[number] if p['first']]
                        old_overlay=next(o for key,o in old_objects.items() if key not in ['/Static','/ChemyWatermark'])
                        new_overlay=next(o for key,o in objects.items() if key not in ['/Static','/ChemyWatermark','/ChemyTypesetHeadings'])
                        original=old_overlay.read_bytes();blocks=groups(original)
                        assert new_overlay.read_bytes()==original[:blocks[0][0]]+original[blocks[len(ids)-1][1]:],(book.name,number,'numbered labels changed')
                        assert str(objects['/ChemyTypesetHeadings']['/Subtype'])=='/Form'
                    else:
                        assert form.read_bytes() == expected, (book.name,number,'native drawing operators changed')
                    seen.add(number)
        buf = BytesIO(); source.save(buf)
    rendered = pdfium.PdfDocument(buf.getvalue())
    scale = 1.5
    for number in range(len(rendered)):
        page = rendered[number]
        bitmap = page.render(scale=scale)
        pixels = np.asarray(bitmap.to_pil().convert('RGB'))
        ink = (pixels[:,int(30*scale):int((W-25)*scale),:].min(axis=2) < 225).any(axis=1)
        allowed = np.zeros(len(ink),dtype=bool)
        for p in by_source[number]:
            lo = max(0,int(np.floor(p['sourceTop']*scale))-2)
            hi = min(len(ink),int(np.ceil(p['sourceBottom']*scale))+3)
            allowed[lo:hi] = True
        start,end = int(TOP*scale),int((H-BOTTOM)*scale)
        missing = np.flatnonzero(ink[start:end] & ~allowed[start:end])+start
        if len(missing):
            target = ROOT/'output/continuous'/f'issue-{book.stem}-{number+1}.png'
            bitmap.to_pil().save(target)
            raise AssertionError((book.name,number+1,'visible source ink outside retained clips',(missing/scale).tolist()))
        bitmap.close(); page.close()
        if number % 100 == 0:
            print('INK',book.name,number+1,'/',len(rendered),flush=True)
    rendered.close()
    result = {'file':book.name,'before':layout['sourcePages'],'after':layout['pages'],
              'questions':len(entries),'joinedPairs':joined,'crossPaperPairs':cross_paper,
              'sourcePagesChecked':len(by_source),'nativeFormsChecked':len(seen),'visibleInkPreserved':True}
    print('PASS',book.name,layout['sourcePages'],'->',layout['pages'],'pages',cross_paper,'cross-paper joins',flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topics',nargs='+')
    args = parser.parse_args()
    paths = sorted(p for p in DATA.glob('*.json') if not args.topics or any(p.stem.startswith(t+'-') for t in args.topics))
    (ROOT/'output/continuous').mkdir(parents=True,exist_ok=True)
    with ProcessPoolExecutor(max_workers=3) as pool:
        reports = list(pool.map(check_book,paths))
    result = {'passed':True,'books':reports,'before':sum(r['before'] for r in reports),'after':sum(r['after'] for r in reports)}
    (ROOT/'output/continuous/audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    print('CONTINUOUS AUDIT',len(reports),'books',result['before'],'->',result['after'],'pages',flush=True)
