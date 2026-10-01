"""Incremental native import: unchanged paper 1, source diagrams, cached geometry."""
import argparse,copy,hashlib,json,re,subprocess
from html import escape
from pathlib import Path
from collections import Counter
from functools import lru_cache
from PIL import Image
from pypdf import PdfReader,PdfWriter
from pypdf.generic import ContentStream,NameObject,DictionaryObject
from paper1_manifest import ROOT,Q_SOURCE,A_SOURCE,SLUGS
from import_paper1 import native_blocks,in_box

CACHE=ROOT/'tmp/library'; ASSETS=ROOT/'dist/assets'; DATA=ROOT/'data/library_manifest.json'
SOURCES={'q':Q_SOURCE,'a':A_SOURCE}
INDEX={k:json.loads((CACHE/k/'index.json').read_text(encoding='utf8')) for k in SOURCES}
READERS={}
@lru_cache(maxsize=24)
def load(k,n):
    d=json.loads((CACHE/k/f'{n:03}.json').read_text(encoding='utf8'))
    seen=set();chars=[]
    for c in d['chars']:
        key=(c['text'],round(c['x0'],2),round(c['x1'],2),round(c['top'],2),round(c['bottom'],2),c['fontname'],str(c['non_stroking_color']))
        if key not in seen:chars.append(c);seen.add(key)
    d['chars']=chars;return d
def colored(c):
    return isinstance(c,(list,tuple)) and len(c)>=3 and max(c[:3])-min(c[:3])>.12
def background(im,k):
    return (im['width']>400 and 89<im['x0']<92 and 190<im['top']<645
            and INDEX[k]['imageFrequency'].get(im['hash'],0)>10)
def spans(k,paper,number,heading=False):
    hs=INDEX[k]['questions']; i=next(i for i,x in enumerate(hs) if (x['paper'],x['number'])==(paper,number)); h=hs[i]
    end=hs[i+1] if i+1<len(hs) and hs[i+1]['paper']==paper else {'page':int(INDEX[k]['papers'].get(str(paper+1),len(INDEX[k]['pages'])+1)),'top':70}
    ranges=[]
    for n in range(h['page'],end['page']+1):
        lo=(h['top']-2 if heading else h['bottom']+.5) if n==h['page'] else 70
        hi=end['top']-3 if n==end['page'] else 766
        if hi>lo+2:ranges.append([n,lo,hi])
    return ranges
def render_page(k,n):
    dest=CACHE/k/f'{n:03}-clean.png'
    if dest.exists():return dest
    if k not in READERS:READERS[k]=PdfReader(SOURCES[k])
    reader=READERS[k];p=copy.copy(reader.pages[n-1]);d=load(k,n)
    stream=ContentStream(p.get_contents(),reader);names={'/'+im['name'] for im in d['images'] if background(im,k)}
    stream.operations=[(args,op) for args,op in stream.operations if not(op==b'Do' and str(args[0]) in names)]
    p[NameObject('/Contents')]=stream
    resources=DictionaryObject(p['/Resources']);xo=resources.get('/XObject')
    if xo:
        resources[NameObject('/XObject')]=DictionaryObject({key:v for key,v in xo.get_object().items() if str(key) not in names})
    p[NameObject('/Resources')]=resources
    writer=PdfWriter();writer.add_page(p);pdf=CACHE/k/f'{n:03}-clean.pdf';writer.write(pdf)
    subprocess.run(['pdftoppm','-singlefile','-r','252','-png',str(pdf),str(dest.with_suffix(''))],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return dest
def merge(bands,gap=5):
    out=[]
    for lo,hi in sorted((list(b) for b in bands)):
        if out and lo<=out[-1][1]+gap:out[-1][1]=max(hi,out[-1][1])
        else:out.append([lo,hi])
    return out
def figure_bands(k,d,lo,hi):
    objects=[]
    for s in d['shapes']:
        if s['top']<lo or s['bottom']>hi or s['x1']<75 or s['x0']>550:continue
        if s['width']>400 and (s['height']>500 or s['height']<1 and (s['top']<75 or s['top']>770)):continue
        if k=='a' and not(colored(s['stroking_color']) or colored(s['non_stroking_color'])):continue
        objects.append(s)
    image=None
    for im in d['images']:
        if background(im,k) or im['top']<lo or im['bottom']>hi:continue
        if k=='a':
            if image is None:image=Image.open(render_page(k,d['page'])).convert('RGB')
            sc=image.width/d['width'];crop=image.crop(tuple(round(v*sc) for v in (im['x0'],im['top'],im['x1'],im['bottom'])))
            if not any(max(p)-min(p)>65 and (p[0]>p[1]+45 or p[2]>p[1]+45) for p in crop.get_flattened_data()):continue
        objects.append(im)
    if image:image.close()
    # Unsupported symbol fonts and detached equation scripts retain exact source appearance.
    selected=[c for c in d['chars'] if lo<=c['top']<hi and 85<c['x0']<514 and c['text'].strip() and (k=='q' or colored(c['non_stroking_color']))]
    for c in selected:
        if any(0xe000<=ord(t)<=0xf8ff for t in c['text']) and c['text']!='\uf044':objects.append(c)
        elif c['size']<9.8 and not any(a['size']>=9.8 and abs((a['top']+a['bottom']-c['top']-c['bottom'])/2)<9 for a in selected):objects.append(c)
    bands=merge([(max(lo,o['top']-3),min(hi,o['bottom']+3)) for o in objects])
    # Entire intersecting text rows stay together, including all script glyphs and labels.
    for _ in range(4):
        expanded=[]
        for a,b in bands:
            cc=[c for c in d['chars'] if 75<c['x0']<550 and c['text'].strip() and c['top']<b and c['bottom']>a and lo<=c['top']<hi]
            expanded.append([max(lo,min([a]+[c['top']-2 for c in cc])),min(hi,max([b]+[c['bottom']+2 for c in cc]))])
        new=merge(expanded)
        if new==bands:break
        bands=new
    return bands
def section(k,ranges,paper,number,label):
    parts=[];captures=[];audit=[];count=0
    for n,lo,hi in ranges:
        d=load(k,n);bands=figure_bands(k,d,lo,hi)
        selected=[c for c in d['chars'] if lo-1<=c['top']<hi and 85<=c['x0']<514 and (k=='q' or colored(c['non_stroking_color']))]
        text=[c for c in selected if not any(a<=(c['top']+c['bottom'])/2<=b for a,b in bands)]
        anchors=[c for c in text if c['text'].strip() and c['size']>=9.8]
        text=[c for c in text if c['text'].strip() or any(abs((c['top']+c['bottom']-a['top']-a['bottom'])/2)<2.3 for a in anchors)]
        try:rows=native_blocks(text) if any(c['text'].strip() for c in text) else []
        except ValueError as err:
            print('Layout fallback',k,n,str(err),flush=True)
            # Unusual stacked source maths: keep the source band, without guessing.
            bands=merge(bands+[(min(c['top'] for c in text)-2,max(c['bottom'] for c in text)+2)]);text=[];rows=[]
        events=[(y,'text',html,x) for y,html,x in rows]
        for a,b in bands:
            count+=1;name=f'p{paper:02}-{k}{number:02}-{count:02}.webp';target=ASSETS/name
            # Full original text width keeps typography at the same scale as native text.
            relevant=[o for o in d['shapes']+d['images']+d['chars'] if o['top']<b and o['bottom']>a and not('hash' in o and background(o,k)) and 75<o['x0']<550]
            x0=min([84]+[o['x0']-2 for o in relevant]);x1=max([514]+[o['x1']+2 for o in relevant]);box=[x0,a,x1,b];page_image=Image.open(render_page(k,n));sc=page_image.width/d['width']
            crop=page_image.crop(tuple(round(v*sc) for v in box));crop.save(target,lossless=True,method=4);page_image.close()
            w,h=crop.size;alt=f'模拟试题{paper} 第{number}题 {label}原图'
            html=f'<figure class="source-figure"><a href="assets/{name}" target="_blank" rel="noopener" aria-label="查看大图：{alt}"><img src="assets/{name}" alt="{alt}" width="{w}" height="{h}" loading="lazy" style="--figure-width:{round((x1-x0)*1.7)}px"></a></figure>'
            events.append((a,'figure',html,0));captures.append({'page':n,'box':box,'asset':name,'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
        pending=[];last=None
        def flush():
            if pending:parts.append('<p>'+''.join(pending)+'</p>');pending.clear()
        for y,typ,html,x in sorted(events):
            if typ=='figure':flush();parts.append(html);last=None;continue
            if pending and (x>95 or re.match(r'^(?:<strong>|\(?\d[）)])',html) or last is not None and y-last>19):flush()
            if pending:
                t=re.sub('<[^>]+>','',pending[-1]);h=re.sub('<[^>]+>','',html)
                if t and h and t[-1].isascii() and h[0].isascii():pending.append(' ')
            pending.append(html);last=y
        flush()
        audit.append({'page':n,'range':[lo,hi],'selectedCharacters':len([c for c in selected if c['text'].strip()]),'nativeCharacters':len([c for c in text if c['text'].strip()]),'figures':len(bands)})
    return ''.join(parts),captures,audit
def import_paper(paper,topics):
    manifest=json.loads(DATA.read_text(encoding='utf8')) if DATA.exists() else {'version':1,'papers':{}}
    bank=json.loads((ROOT/'dist/questions.json').read_text(encoding='utf8'))
    original=[q for q in bank if q['paper']==1];items=[];records=[]
    specs=[h for h in INDEX['q']['questions'] if h['paper']==paper]
    assert len(specs)==len(topics)
    for h,topic in zip(specs,topics):
        assert topic in SLUGS
        number=h['number'];qr=spans('q',paper,number);ar=spans('a',paper,number)
        body,qf,qa=section('q',qr,paper,number,'题目');answer,af,aa=section('a',ar,paper,number,'答案')
        assert body and answer,(paper,number)
        def pages(rs):return str(rs[0][0]) if rs[0][0]==rs[-1][0] else f'{rs[0][0]}–{rs[-1][0]}'
        items.append({k:h[k] for k in ('paper','number','title','points','percent')}|{'id':f'chemy39-{paper}-{number}','topic':topic,'body':body,'answer':answer,'questionPages':pages(qr),'answerPages':pages(ar),'pdfReady':True})
        records.append({'number':number,'topic':topic,'question':qr,'printQuestion':spans('q',paper,number,True),'answer':ar,'figures':{'q':qf,'a':af},'coverage':{'q':qa,'a':aa},'reviewed':False})
    bank=[q for q in bank if q['paper']!=paper]+items;bank.sort(key=lambda q:(q['paper'],q['number']))
    assert [q for q in bank if q['paper']==1]==original
    (ROOT/'dist/questions.json').write_text(json.dumps(bank,ensure_ascii=False,indent=2),encoding='utf8')
    manifest['papers'][str(paper)]={'questions':records,'reviewed':False};DATA.parent.mkdir(exist_ok=True);DATA.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
    print('Imported paper',paper,len(items),'questions',dict(Counter(q['topic'] for q in items)),flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('paper',type=int);ap.add_argument('--topics',nargs='+');args=ap.parse_args()
    plan=json.loads((ROOT/'data/import_plan.json').read_text(encoding='utf8'))
    import_paper(args.paper,args.topics or plan[str(args.paper)])
