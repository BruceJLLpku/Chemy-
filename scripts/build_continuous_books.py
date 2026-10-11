"""Flow complete topic questions and answers across paper boundaries as native PDF."""
import argparse
import hashlib
import json
from concurrent.futures import ProcessPoolExecutor
from io import BytesIO
from pathlib import Path
import numpy as np
import pypdfium2 as pdfium

from reportlab.lib.pagesizes import A4
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

from build_export_index import index_book
from fast_pdf import pikepdf, share_streams
from pdf_watermark import stamp_pdf
from source_info import source_name

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'tmp/continuous/source'
CACHE = ROOT / 'tmp/continuous/index'
DATA = ROOT / 'data/continuous-books'
W, H = A4
TOP, BOTTOM, QUESTION_GAP = 96, 70, 14
PROFILE = 'continuous-native-v2'
pdfmetrics.registerFont(TTFont('ContinuousSong', 'C:/Windows/Fonts/simsun.ttc', subfontIndex=0))


def frame(topic, kind, count, number):
    buf = BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    c.setFont('ContinuousSong', 14)
    label = '题目册' if kind == 'questions' else '答案册'
    c.drawString(62, H-48, f'Chemy 化学竞赛专题题库 · {topic} · {label}')
    c.setFont('ContinuousSong', 9)
    c.drawString(62, H-66, f'{count} 道题 · 专题连续编号')
    c.setLineWidth(.4); c.setStrokeColorRGB(.55,.6,.57)
    c.line(62, H-77, W-62, H-77)
    c.setFillColorRGB(.3,.3,.3); c.setFont('ContinuousSong', 7.5)
    c.drawString(62,35,'版权归 Chemy 化学奥林匹克团队原命题组所有，仅供学术交流，禁止商业用途。')
    c.drawRightString(W-62,35,str(number))
    c.save()
    return buf.getvalue()


def source_index(slug, kind, source, records):
    CACHE.mkdir(parents=True, exist_ok=True)
    target = CACHE / (slug+'-'+kind+'.json')
    signature = hashlib.sha256(source.read_bytes()+json.dumps(records,sort_keys=True).encode()
                               +(ROOT/'scripts/build_export_index.py').read_bytes()).hexdigest()
    if target.exists():
        data = json.loads(target.read_text(encoding='utf8'))
        if data['signature'] == signature:
            return data['questions']
    if kind == 'questions' and source.parent == SOURCE:
        regions = json.loads((SOURCE/'export-index'/f'{slug}.json').read_text(encoding='utf8'))['questions']
    else:
        regions = index_book(slug,kind,book=source,index=records)
    target.write_text(json.dumps({'signature':signature,'questions':regions},separators=(',',':')),encoding='utf8')
    return regions


def complete_visible_bands(slug,kind,source,records,regions,originals):
    """Protect vector figures and also include ink missed by PDF object geometry."""
    key = 'q' if kind == 'questions' else 'a'
    by_id = {r['id']:r for r in records}
    heads = {}
    for path in (ROOT/'tmp/library/books').glob(f'*-{slug}-{key}.layout.json'):
        layout = json.loads(path.read_text(encoding='utf8'))
        if not layout['ledger'] or layout['ledger'][0]['id'] not in by_id:
            continue
        first = layout['ledger'][0]
        offset = by_id[first['id']]['firstPage']-first['firstPage']
        for h in layout['heads']:
            if h['id'] in by_id:
                heads[h['id']] = (h['page']+offset-1,H-h['cursor'])
    assert set(heads) == set(by_id)
    signature = hashlib.sha256(source.read_bytes()+json.dumps(regions,sort_keys=True).encode()
                               +b'visible-bands-v2').hexdigest()
    cache = CACHE/(slug+'-'+kind+'.visible.json')
    if cache.exists():
        saved = json.loads(cache.read_text(encoding='utf8'))
        if saved['signature'] == signature:
            return saved['questions']
    by_page = {}
    for i,record in enumerate(records):
        qid = record['id']; first_page,first_top = heads[qid]
        for number in range(first_page,record['lastPage']):
            top = first_top if number == first_page else TOP
            bottom = H-BOTTOM
            if i+1 < len(records):
                next_page,next_top = heads[records[i+1]['id']]
                if next_page == number:
                    bottom = min(bottom,next_top-3)
            by_page.setdefault(number,[]).append((qid,top,bottom,number==first_page))
    raw = BytesIO(); originals.save(raw)
    rendered = pdfium.PdfDocument(raw.getvalue())
    output = {}
    from build_export_index import merge
    scale = 1.5
    for number,items in by_page.items():
        page = rendered[number]; bitmap = page.render(scale=scale)
        pixels = np.asarray(bitmap.to_pil().convert('RGB'))
        ink = (pixels[:,int(30*scale):int((W-25)*scale),:].min(axis=2)<230).any(axis=1)
        for qid,top,bottom,first in items:
            rows = np.flatnonzero(ink[int(top*scale):int(bottom*scale)])+int(top*scale)
            assert len(rows), (slug,kind,qid,number,'empty source')
            runs = []
            for row in rows:
                a,b = max(top,row/scale-.7),min(bottom,(row+1)/scale+.7)
                # A small gap inside a fraction stays with the rest of its line.
                if runs and a <= runs[-1][1]+3:
                    runs[-1][1] = b
                else:
                    runs.append([a,b])
            vectors = [band for r in regions[qid] if r['page']==number for band in r['bands']]
            bands = merge(vectors+runs)
            if first:
                end = next((i for i,b in enumerate(bands) if b[1]>=bands[0][0]+65),len(bands)-1)
                bands = [[bands[0][0],bands[end][1]]] + bands[end+1:]
            output.setdefault(qid,[]).append({'page':number,'bands':[[round(a,4),round(b,4)] for a,b in bands]})
        bitmap.close(); page.close()
        if number % 100 == 0:
            print('VISIBLE',slug,kind,number+1,'/',len(rendered),flush=True)
    rendered.close()
    cache.write_text(json.dumps({'signature':signature,'questions':output},separators=(',',':')),encoding='utf8')
    return output


def flow_book(source, records, topic, slug, kind, dest):
    out = pikepdf.Pdf.new()
    originals = pikepdf.open(source)
    for page in originals.pages:
        contents = page.obj.get('/Contents')
        streams = list(contents) if isinstance(contents,pikepdf.Array) else [contents] if contents else []
        page.obj['/Contents'] = pikepdf.Array([s for s in streams if not s.get('/ChemyWatermark',False)])
    regions = source_index(slug,kind,source,records)
    regions = complete_visible_bands(slug,kind,source,records,regions,originals)
    assert set(regions) == {r['id'] for r in records}
    forms = {}
    page = None
    cursor = 0
    placements, heads, ledger, final_index = [], [], [], {}

    def new_page():
        nonlocal page,cursor
        with pikepdf.open(BytesIO(frame(topic,kind,len(records),len(out.pages)+1))) as base:
            out.pages.append(base.pages[0])
        page = out.pages[-1]
        page.obj['/Resources']['/XObject'] = pikepdf.Dictionary()
        cursor = H-TOP

    def draw(source_page, top, bottom, scale, qid, bands, first, note=False):
        nonlocal cursor
        if source_page not in forms:
            forms[source_page] = out.copy_foreign(originals.pages[source_page].as_form_xobject())
        name = f'/Source{source_page}'
        page.obj['/Resources']['/XObject'][name] = forms[source_page]
        height = (bottom-top)*scale
        left = (W-W*scale)/2
        translate = cursor-(H-top)*scale
        commands = (f'q {left:.6f} {cursor-height:.6f} {W*scale:.6f} {height:.6f} re W n '
                    f'{scale:.8f} 0 0 {scale:.8f} {left:.6f} {translate:.6f} cm {name} Do Q\n')
        page.contents_add(out.make_stream(commands.encode()))
        target_top = H-cursor
        placements.append({'id':qid,'sourcePage':source_page,'sourceTop':top,'sourceBottom':bottom,
                           'page':len(out.pages)-1,'top':target_top,'height':height,'scale':scale,
                           'first':first,'note':note})
        mapped = [[round(target_top+(a-top)*scale,4),round(target_top+(b-top)*scale,4)] for a,b in bands]
        final_index.setdefault(qid,[]).append({'page':len(out.pages)-1,'bands':mapped})
        cursor -= height

    for record in records:
        qid = record['id']
        first = True
        entry = dict(record)
        for region in regions[qid]:
            bands = region['bands']
            offset = 0
            while offset < len(bands):
                top = bands[offset][0]
                initial = bands[offset][1]-top
                if page is None or cursor-BOTTOM < min(initial,H-TOP-BOTTOM):
                    new_page()
                end = offset
                while end+1 < len(bands) and bands[end+1][1]-top <= cursor-BOTTOM:
                    end += 1
                bottom = bands[end][1]
                scale = min(1,(cursor-BOTTOM)/(bottom-top))
                if first:
                    entry['firstPage'] = len(out.pages)
                    heads.append({'id':qid,'page':len(out.pages)-1,'cursor':cursor})
                draw(region['page'],top,bottom,scale,qid,bands[offset:end+1],first)
                first = False
                entry['lastPage'] = len(out.pages)
                offset = end+1
                if offset < len(bands):
                    cursor -= min(18,max(3,bands[offset][0]-bottom))
            cursor -= 8
        # Keep original source correction notes with the relevant answer.
        if kind == 'answers' and record['sourceEdition'] == 39 and record['sourcePaper'] == 1 and slug in ['crystal','electrochemistry']:
            if cursor-BOTTOM < 18:
                new_page()
            draw(regions[qid][0]['page'],H-60,H-43,1,qid,[[H-60,H-43]],False,note=True)
            entry['lastPage'] = len(out.pages)
        cursor -= QUESTION_GAP-8
        ledger.append(entry)
    assert all(p['top'] >= TOP-.01 and p['top']+p['height'] <= H-BOTTOM+.01 for p in placements)
    metadata = {'/Title':f'Chemy {topic}专题'+('题目册' if kind=='questions' else '答案册'),
                '/Author':'Chemy 化学奥林匹克团队（原题与答案）',
                '/Subject':'专题连续编号；跨试卷紧凑接续，保留原题字体、公式、结构图、评分与来源',
                '/ChemyLayout':PROFILE}
    for key,value in metadata.items():
        out.docinfo[key] = value
    with out.open_outline() as outline:
        for entry in ledger:
            title = f'第{entry["number"]}题 · {source_name(entry["sourceEdition"],entry["sourcePaper"],compact=True)}原第{entry["sourceNumber"]}题'
            outline.root.append(pikepdf.OutlineItem(title,entry['firstPage']-1))
    share_streams(out)
    dest.parent.mkdir(parents=True,exist_ok=True)
    temporary = dest.with_suffix('.flowing.pdf')
    out.save(temporary,compress_streams=True,object_stream_mode=pikepdf.ObjectStreamMode.generate,deterministic_id=True)
    pages = len(out.pages)
    out.close(); originals.close()
    stamp_pdf(temporary)
    temporary.replace(dest)
    DATA.mkdir(parents=True,exist_ok=True)
    layout = {'profile':PROFILE,'sourcePages':max(r['lastPage'] for r in records),'pages':pages,
              'sha256':hashlib.sha256(dest.read_bytes()).hexdigest(),'sourceSha256':hashlib.sha256(source.read_bytes()).hexdigest(),
              'records':ledger,'heads':heads,'questions':final_index,'placements':placements}
    (DATA/(slug+'-'+kind+'.json')).write_text(json.dumps(layout,ensure_ascii=False,separators=(',',':')),encoding='utf8')
    print('CONTINUOUS',slug,kind,layout['sourcePages'],'->',pages,'pages',len(ledger),'questions',flush=True)
    return ledger,pages,final_index


def build(job):
    topic,slug,kind = job
    records = json.loads((SOURCE/'print_index.json').read_text(encoding='utf8'))[slug+'-'+kind]
    dest = ROOT/'dist/downloads'/f'{slug}-{kind}.pdf'
    ledger,pages,index = flow_book(SOURCE/dest.name,records,topic,slug,kind,dest)
    if kind == 'questions':
        numbering = json.loads((ROOT/'dist/numbering.json').read_text(encoding='utf8'))
        version = numbering.get('pdfVersion',numbering['version'])
        target = ROOT/'dist/export-index'/f'{slug}.json'
        target.write_text(json.dumps({'version':2,'bookVersion':version,'questions':index},separators=(',',':')),encoding='utf8')
    return slug+'-'+kind,ledger


def sync_pdf_version():
    """Publish one content version for the full PDF set and its crop indexes."""
    target = ROOT/'dist/numbering.json'
    numbering = json.loads(target.read_text(encoding='utf8'))
    digest = hashlib.sha256(numbering['version'].encode()+PROFILE.encode())
    for book in sorted((ROOT/'dist/downloads').glob('*.pdf')):
        digest.update(book.name.encode()+hashlib.sha256(book.read_bytes()).digest())
    version = 'topic-pdf-'+digest.hexdigest()[:16]
    numbering['pdfVersion'] = version
    target.write_text(json.dumps(numbering,ensure_ascii=False,indent=2)+'\n',encoding='utf8')
    for index in (ROOT/'dist/export-index').glob('*.json'):
        data = json.loads(index.read_text(encoding='utf8'))
        data['version'] = 2
        data['bookVersion'] = version
        index.write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')),encoding='utf8')
    print('PDF VERSION',version,flush=True)
    return version


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topics',nargs='+')
    args = parser.parse_args()
    from paper1_manifest import SLUGS
    topics = SLUGS
    jobs = [(topic,slug,kind) for topic,slug in topics.items() if not args.topics or slug in args.topics
            for kind in ['questions','answers']]
    all_index = json.loads((ROOT/'data/print_index.json').read_text(encoding='utf8'))
    with ProcessPoolExecutor(max_workers=3) as pool:
        for key,ledger in pool.map(build,jobs):
            all_index[key] = ledger
            (ROOT/'data/print_index.json').write_text(json.dumps(all_index,ensure_ascii=False,indent=2),encoding='utf8')
    sync_pdf_version()
