"""Verify type changes leave every native body, glyph, clip and page unchanged."""
import hashlib,json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from fast_pdf import pikepdf
from pdf_typography import STYLE,groups
from restyle_topic_pdfs import ROOT,BACKUP,DATA

def digest(obj,memo=None):
    memo={} if memo is None else memo
    if isinstance(obj,pikepdf.Object) and obj.is_indirect:
        if obj.objgen in memo:return memo[obj.objgen]
    if isinstance(obj,pikepdf.Stream):
        values=sorted((str(k),digest(v,memo)) for k,v in obj.items() if str(k) not in ['/Length','/Filter','/DecodeParms'])
        try:data=obj.read_bytes()
        except pikepdf.PdfError:
            data=obj.read_raw_bytes()
            values += [('encoded-filter',str(obj.get('/Filter'))),('encoded-params',str(obj.get('/DecodeParms')))]
        result=hashlib.sha256(data+repr(values).encode()).hexdigest()
    elif isinstance(obj,pikepdf.Dictionary):
        result=hashlib.sha256(repr(sorted((str(k),digest(v,memo)) for k,v in obj.items())).encode()).hexdigest()
    elif isinstance(obj,pikepdf.Array):
        result=hashlib.sha256(repr([digest(v,memo) for v in obj]).encode()).hexdigest()
    else:result=str(obj)
    if isinstance(obj,pikepdf.Object) and obj.is_indirect:memo[obj.objgen]=result
    return result

def test(path):
    layout=json.loads((DATA/path.with_suffix('.json').name).read_text(encoding='utf8'))
    before=json.loads((BACKUP/path.with_suffix('.json').name).read_text(encoding='utf8'))
    for key in ['records','heads','questions','placements','pages','sourcePages','sourceSha256']:
        assert layout[key]==before[key],(path.name,key,'continuous layout changed')
    assert layout['typography']==STYLE
    assert layout['sha256']==hashlib.sha256(path.read_bytes()).hexdigest()
    owners=defaultdict(list)
    for p in layout['placements']:
        if p['first']:owners[p['sourcePage']].append(p['id'])
    checked=set();count=0;memo_old={};memo_new={}
    with pikepdf.open(BACKUP/path.name) as old,pikepdf.open(path) as new:
        assert len(new.pages)==len(old.pages)==layout['pages']
        assert new.docinfo['/ChemyTypography']==STYLE
        for a,b in zip(old.pages,new.pages):
            old_streams=list(a.obj['/Contents']);new_streams=list(b.obj['/Contents'])
            assert len(old_streams)==len(new_streams)
            assert [s.read_bytes() for s in old_streams[1:]]==[s.read_bytes() for s in new_streams[1:]],(path.name,'body clips or watermark changed')
            assert sum(bool(s.get('/ChemyWatermark')) for s in new_streams)==1
            frame=b.obj['/Resources']['/XObject']['/ChemyPageFrame']
            assert b'11.04 Tf' in frame.read_bytes() and b'10.56 Tf' in frame.read_bytes() and b'2 Tr' in frame.read_bytes()
            assert b' l S' not in frame.read_bytes(),(path.name,'old masthead rule remains')
            fonts=frame['/Resources']['/Font']
            names=[str(f.get('/BaseFont')) for f in fonts.values()]
            assert any('TimesNewRomanPS-BoldMT' in n for n in names) and any('SimSun' in n for n in names)
            for key,form in b.obj['/Resources']['/XObject'].items():
                if not str(key).startswith('/Source'):continue
                number=int(str(key).removeprefix('/Source'))
                if number in checked:continue
                previous=a.obj['/Resources']['/XObject'][key]
                old_objects=previous['/Resources']['/XObject'];new_objects=form['/Resources']['/XObject']
                assert digest(new_objects['/Static'],memo_new)==digest(old_objects['/Static'],memo_old),(path.name,number,'native body or font resource changed')
                ids=owners[number]
                if ids:
                    assert form.get('/ChemyTypography')==STYLE
                    assert form.read_bytes()==previous.read_bytes()+b'\nq /ChemyTypesetHeadings Do Q\n'
                    previous_overlay=next(o for k,o in old_objects.items() if k not in ['/Static','/ChemyWatermark'])
                    current_overlay=next(o for k,o in new_objects.items() if k not in ['/Static','/ChemyWatermark','/ChemyTypesetHeadings'])
                    original=previous_overlay.read_bytes();blocks=groups(original)
                    assert current_overlay.read_bytes()==original[:blocks[0][0]]+original[blocks[len(ids)-1][1]:]
                    assert digest(current_overlay['/Resources'],memo_new)==digest(previous_overlay['/Resources'],memo_old)
                    typed=new_objects['/ChemyTypesetHeadings'];assert b'10.56 Tf' in typed.read_bytes() and b'2 Tr' in typed.read_bytes()
                    count+=len(ids)
                else:assert digest(form,memo_new)==digest(previous,memo_old)
                checked.add(number)
    assert count==len(layout['records'])
    print('PASS',path.name,count,'headings;',layout['pages'],'pages; native body/fonts, clips, watermark and layout unchanged',flush=True)
    return {'file':path.name,'headings':count,'pages':layout['pages'],'nativeSourceForms':len(checked),'bodyAndGlyphsPreserved':True,'continuousLayoutPreserved':True}

if __name__=='__main__':
    paths=sorted((ROOT/'dist/downloads').glob('*.pdf'))
    with ProcessPoolExecutor(max_workers=3) as pool:books=list(pool.map(test,paths))
    report={'passed':True,'typography':STYLE,'books':books,'headings':sum(b['headings'] for b in books),'pages':sum(b['pages'] for b in books)}
    assert len(books)==18 and report['headings']==3866 and report['pages']==3040
    (ROOT/'output/typography/audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('TYPOGRAPHY AUDIT',report['headings'],'headings;',report['pages'],'pages; 18 books passed',flush=True)
