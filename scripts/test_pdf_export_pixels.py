"""Compare browser placements with relocated source pixels, including pattern fills.

Run test_export_parts_browser.cjs --patterns first. Comparison removes only the
known decorative watermark; source chemistry is rendered at the output scale and
translation on the same pixel grid. --synthetic checks drawNative's small fixture.
"""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import sys

import fitz
from PIL import Image, ImageChops, ImageFilter
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, NameObject

from pdf_watermark import strip_watermark

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'work/export-validation/patterns'


def open_without_browser_watermark(path):
    reader=PdfReader(path)
    writer=PdfWriter()
    jpeg=(ROOT/'dist/assets/chemy-watermark.jpg').read_bytes()
    digest=hashlib.sha256(jpeg).digest()
    for original in reader.pages:
        page=writer.add_page(original)
        resources=page['/Resources']
        names=set()
        for name,ref in resources.get('/XObject',{}).items():
            obj=ref.get_object()
            if obj.get('/Subtype')=='/Image' and hashlib.sha256(obj.get_data()).digest()==digest:
                names.add(name)
        content=ContentStream(page.get('/Contents'),writer)
        removed=sum(op==b'Do' and args[0] in names for args,op in content.operations)
        assert removed==1, ('Expected one known watermark draw per page',path,removed)
        content.operations=[(args,op) for args,op in content.operations if not (op==b'Do' and args[0] in names)]
        page[NameObject('/Contents')]=writer._add_object(content)
    raw=BytesIO();writer.write(raw)
    return fitz.open('pdf',raw.getvalue())


def source_page(reader,number):
    writer=PdfWriter();page=writer.add_page(reader.pages[number]);strip_watermark(page)
    raw=BytesIO();writer.write(raw)
    return fitz.open('pdf',raw.getvalue())


def projected_glyphs(page, source_rect, x, top, scale):
    """Put visible text identity, paint and geometry in output-page coordinates."""
    fitz.TOOLS.store_shrink(100)
    transform=fitz.Matrix(scale,0,0,scale,x-source_rect.x0*scale,top-source_rect.y0*scale)
    glyphs=[]
    for span in page.get_texttrace():
        if span['type'] not in (0,1) or span['opacity']<=0:
            continue
        paint={key:span.get(key) for key in ('font','type','flags','wmode','dir','color','opacity','layer')}
        paint['size']=span['size']*scale
        paint['linewidth']=span.get('linewidth')*scale if span.get('linewidth') is not None else None
        for code,gid,origin,bbox in span['chars']:
            if not fitz.Rect(bbox).intersects(source_rect):
                continue
            glyphs.append(paint|{'unicode':code,'gid':gid,'origin':tuple(fitz.Point(origin)*transform),
                                 'bbox':tuple(fitz.Rect(bbox)*transform)})
    return glyphs


def matched_relocated_glyphs(before,after,critical_boxes):
    """Match every overlapping paint occurrence, not just one surviving glyph.

    A missing duplicate or overprinted character must not borrow another
    character's bounding box as proof. The multiset match also checks colour,
    opacity, font, glyph ID and transformed geometry before any sampling retry.
    """
    def relevant(glyph):
        return any(fitz.Rect(glyph['bbox']).intersects(box) for box in critical_boxes)
    old=[glyph for glyph in before if relevant(glyph)]
    new=[glyph for glyph in after if relevant(glyph)]
    if not old or len(old)!=len(new):
        return None
    def same(a,b):
        exact=('font','type','flags','wmode','dir','color','opacity','layer','unicode','gid')
        if any(a.get(key)!=b.get(key) for key in exact):
            return False
        for key in ('size','linewidth'):
            av,bv=a.get(key),b.get(key)
            if av is None or bv is None:
                if av!=bv:return False
            elif abs(av-bv)>.001:return False
        return all(abs(a[key][i]-b[key][i])<=.001 for key in ('origin','bbox') for i in range(len(a[key])))
    remaining=new[:]
    for glyph in old:
        match=next((i for i,candidate in enumerate(remaining) if same(glyph,candidate)),None)
        if match is None:return None
        remaining.pop(match)
    if not all(any(fitz.Rect(g['bbox']).contains((box.tl+box.br)/2) for g in old) for box in critical_boxes):
        return None
    return {'paintOccurrences':len(old),'unicode':sorted(set(g['unicode'] for g in old)),
            'geometryTolerancePt':.001,'criticalPixels':len(critical_boxes)}


def relocate_compare(source,target,source_rect,x,top,scale,label,zoom=2,*,offset=(0,0),_allow_sampling_retry=True):
    # Matrices operate after the PDF page's own coordinate conversion. Translating
    # before rasterization avoids resizing pixels or guessing subpixel alignment.
    expected_matrix=fitz.Matrix(scale*zoom,0,0,scale*zoom,(x-source_rect.x0*scale)*zoom+offset[0],(top-source_rect.y0*scale)*zoom+offset[1])
    # MuPDF's process store can otherwise reuse an inline FontDescriptor from
    # another PDF and hide a broken subset font. Keep each document's render cold.
    fitz.TOOLS.store_shrink(100)
    expected=source.get_pixmap(matrix=expected_matrix,clip=source_rect,alpha=False)
    target_rect=fitz.Rect(x,top,x+source_rect.width*scale,top+source_rect.height*scale)
    fitz.TOOLS.store_shrink(100)
    actual=target.get_pixmap(matrix=fitz.Matrix(zoom,0,0,zoom,*offset),clip=target_rect,alpha=False)
    assert expected.n==actual.n==3
    left=max(expected.x,actual.x);right=min(expected.x+expected.width,actual.x+actual.width)
    upper=max(expected.y,actual.y);lower=min(expected.y+expected.height,actual.y+actual.height)
    assert right-left>4 and lower-upper>4, ('Empty placement render',label)
    a=Image.frombytes('RGB',(expected.width,expected.height),expected.samples).crop((left-expected.x,upper-expected.y,right-expected.x,lower-expected.y))
    b=Image.frombytes('RGB',(actual.width,actual.height),actual.samples).crop((left-actual.x,upper-actual.y,right-actual.x,lower-actual.y))
    # Clip-edge antialiasing differs when a boundary falls between pixels. All
    # indexed band boundaries are whitespace; ignore only their outer pixel.
    a=a.crop((1,1,a.width-1,a.height-1));b=b.crop((1,1,b.width-1,b.height-1))
    diff=ImageChops.difference(a,b);hist=diff.histogram();count=sum(hist)
    result={'label':label,'mae':sum((i%256)*n for i,n in enumerate(hist))/count,
            'fractionOver32':sum(n for i,n in enumerate(hist) if i%256>32)/count,
            'maxDelta':max(i%256 for i,n in enumerate(hist) if n)}
    # A one-pixel neighborhood permits renderer edge-phase differences under
    # scaled tiling patterns. Interior colors and displacement over 0.5 pt at
    # 144 dpi must still match; compare both directions so missing ink fails.
    def outside(reference, candidate):
        low=reference.filter(ImageFilter.MinFilter(3));high=reference.filter(ImageFilter.MaxFilter(3))
        return ImageChops.lighter(ImageChops.subtract(candidate,high),ImageChops.subtract(low,candidate))
    tolerant=ImageChops.lighter(outside(a,b),outside(b,a));th=tolerant.histogram()
    result['tolerantMae']=sum((i%256)*n for i,n in enumerate(th))/count
    result['tolerantFractionOver32']=sum(n for i,n in enumerate(th) if i%256>32)/count
    result['tolerantMaxDelta']=max(i%256 for i,n in enumerate(th) if n)
    ordinary_metrics=(result['mae']<=1.5 and result['fractionOver32']<=.015 and result['tolerantMae']<=.2 and result['tolerantFractionOver32']<=.001)
    result['passed']=ordinary_metrics and result['tolerantMaxDelta']<=32
    if not result['passed']:
        a.save(OUT/(label+'-expected.png'));b.save(OUT/(label+'-actual.png'));diff.save(OUT/(label+'-diff.png'))
        if _allow_sampling_retry and ordinary_metrics:
            channels=tolerant.split()
            maximum=ImageChops.lighter(ImageChops.lighter(channels[0],channels[1]),channels[2])
            critical=maximum.point(lambda value:255 if value>32 else 0)
            bounds=critical.getbbox();boxes=[]
            for py in range(bounds[1],bounds[3]):
                for px in range(bounds[0],bounds[2]):
                    if critical.getpixel((px,py)):
                        xx=(left+1+px-offset[0])/zoom;yy=(upper+1+py-offset[1])/zoom
                        boxes.append(fitz.Rect(xx,yy,xx+1/zoom,yy+1/zoom))
            if len(boxes)<=64:
                before=projected_glyphs(source,source_rect,x,top,scale)
                after=projected_glyphs(target,target_rect,target_rect.x0,target_rect.y0,1)
                proof=matched_relocated_glyphs(before,after,boxes)
                if proof:
                    phases=[relocate_compare(source,target,source_rect,x,top,scale,label+'-phase'+str(n),zoom,
                                             offset=phase,_allow_sampling_retry=False)
                            for n,phase in enumerate(((.37,.23),(.73,.61)))]
                    # Retain the initial metrics and failure; a retry succeeds
                    # only if both shifted rasters satisfy the unchanged limits.
                    result.update(initialPassed=False,glyphSamplingProof=proof,samplingPhases=phases)
                    result['passed']=all(phase['passed'] for phase in phases)
    return result


def check_browser(path):
    report=json.loads(path.read_text(encoding='utf8'));checks=[];readers={};documents={}
    for export in report['exports']:
        pdf=path.parent/export['file']
        with open_without_browser_watermark(pdf) as target:
            for number,item in enumerate(export['placements']):
                key=(item['slug'],export['kind']);sourcekey=(*key,item['sourcePage'])
                if key not in readers:readers[key]=PdfReader(ROOT/'dist/downloads'/f'{key[0]}-{key[1]}.pdf')
                if sourcekey not in documents:documents[sourcekey]=source_page(readers[key],item['sourcePage'])
                source=documents[sourcekey][0];page=target[item['page']-1]
                rect=fitz.Rect(0,item['sourceTop'],source.rect.width,item['sourceBottom'])
                x=(page.rect.width-rect.width*item['scale'])/2
                label=Path(export['file']).stem+'-'+str(number)
                check=relocate_compare(source,page,rect,x,item['top'],item['scale'],label)
                check.update(id=item['id'],sourcePage=item['sourcePage']+1,outputPage=item['page'])
                checks.append(check)
    for document in documents.values():document.close()
    return checks


def check_synthetic():
    layout=json.loads((OUT/'synthetic-layout.json').read_text())
    checks=[]
    with fitz.open(OUT/'synthetic-source.pdf') as source, fitz.open(OUT/'synthetic-output.pdf') as target:
        for n,placed in enumerate(layout['placements']):
            before=source[placed.get('source',n)];after=target[placed.get('page',0)]
            top=after.rect.height-placed['y']-before.rect.height*placed['scale']
            checks.append(relocate_compare(before,after,before.rect,placed['x'],top,placed['scale'],'synthetic-'+str(n)))
    return checks


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--browser-report',type=Path,default=ROOT/'work/export-validation/pattern-browser-report.json')
    parser.add_argument('--synthetic',action='store_true')
    args=parser.parse_args();OUT.mkdir(parents=True,exist_ok=True)
    checks=check_synthetic() if args.synthetic else check_browser(args.browser_report)
    name='synthetic-pixels.json' if args.synthetic else args.browser_report.stem.removesuffix('-report')+'-pixels.json'
    (OUT/name).write_text(json.dumps(checks,ensure_ascii=False,indent=2)+'\n',encoding='utf8',newline='\n')
    errors=[entry for entry in checks if not entry['passed']]
    print(json.dumps({'checked':len(checks),'failed':len(errors),'worstMae':max(c['mae'] for c in checks),'maxDelta':max(c['maxDelta'] for c in checks)},ensure_ascii=False))
    if errors:
        print(json.dumps(errors[:10],ensure_ascii=False));sys.exit(1)
