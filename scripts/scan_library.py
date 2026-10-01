"""Cache read-only native geometry and locate papers/questions in both source PDFs."""
import hashlib,json,re,sys
from collections import Counter
from pathlib import Path
import pdfplumber
from pypdf import PdfReader
from paper1_manifest import ROOT,Q_SOURCE,A_SOURCE

CACHE=ROOT/'tmp'/'library';CACHE.mkdir(parents=True,exist_ok=True)

def rows(chars):
    groups=[]
    for c in sorted([c for c in chars if c['size']>=9.8 and c['text'].strip()],key=lambda c:c['top']):
        center=(c['top']+c['bottom'])/2
        if groups and abs(center-groups[-1]['center'])<2.3:groups[-1]['chars'].append(c)
        else:groups.append({'center':center,'chars':[c]})
    return [{'top':min(c['top'] for c in g['chars']),
             'bottom':max(c['bottom'] for c in g['chars']),
             'text':''.join(c['text'] for c in sorted(g['chars'],key=lambda c:c['x0']))}
            for g in groups]

def scan(kind,path):
    folder=CACHE/kind;folder.mkdir(exist_ok=True)
    fingerprint=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path=folder/'index.json'
    if manifest_path.exists():
        stored=json.loads(manifest_path.read_text(encoding='utf8'))
        if stored['sha256']==fingerprint and all((folder/f'{n:03}.json').exists() for n in stored['pages']):return stored
    reader=PdfReader(path);image_hashes={};image_frequency=Counter();pages=[];paper=0;headings=[];starts={}
    with pdfplumber.open(path) as doc:
        for n,p in enumerate(doc.pages,1):
            rp=reader.pages[n-1];objects=rp.get('/Resources',{}).get('/XObject',{})
            if hasattr(objects,'get_object'):objects=objects.get_object()
            images=[]
            for im in p.images:
                name='/'+im['name'];ref=objects.get(name)
                if ref is None:continue
                obj=ref.get_object();key=getattr(ref,'idnum',name)
                if key not in image_hashes:image_hashes[key]=hashlib.sha256(obj.get_data()).hexdigest()
                image_frequency[image_hashes[key]]+=1
                images.append({k:im[k] for k in ('name','x0','x1','top','bottom','width','height')}|{'hash':image_hashes[key]})
            chars=[{k:c[k] for k in ('text','x0','x1','top','bottom','size','fontname','non_stroking_color')} for c in p.chars]
            lines=rows(chars)
            header=''.join(r['text'] for r in lines if r['top']<130)
            match=re.search(r'模拟试题\s*(\d+)',header)
            if match and int(match[1])!=paper:
                paper=int(match[1]);starts[paper]=n
            shape_keys=('x0','x1','top','bottom','width','height','stroke','fill','linewidth','non_stroking_color','stroking_color')
            shapes=[{k:o.get(k) for k in shape_keys} for o in p.curves+p.lines+p.rects]
            payload={'page':n,'paper':paper,'width':p.width,'height':p.height,'chars':chars,'shapes':shapes,'images':images,'rows':lines}
            (folder/f'{n:03}.json').write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf8')
            pages.append(n)
            for r in lines:
                match=re.match(r'^第\s*(\d+)\s*题(.*)',r['text'])
                if match and '分' in match[2] and '评判' not in match[2]:
                    pts=re.search(r'[（(]\s*(\d+)\s*分',match[2])
                    if pts:
                        pct=re.search(r'占(?:比)?\s*([\d.]+)\s*[%％]',match[2])
                        title=re.sub(r'[（(]\s*\d+\s*分.*?[）)]','',match[2]).strip()
                        headings.append({'paper':paper,'number':int(match[1]),'title':title,
                                         'points':int(pts[1]),'percent':float(pct[1]) if pct else None,'page':n,'top':r['top'],'bottom':r['bottom']})
            if n%25==0:print(kind,n,'/',len(doc.pages),flush=True)
            p.close()
    result={'sha256':fingerprint,'pages':pages,'papers':starts,'questions':headings,'imageFrequency':dict(image_frequency)}
    manifest_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8')
    for kind,path in [('q',Q_SOURCE),('a',A_SOURCE)]:
        index=scan(kind,path)
        print(kind,'papers:',index['papers'],'question headings:',len(index['questions']),flush=True)
    q=json.loads((CACHE/'q'/'index.json').read_text(encoding='utf8'))
    print('PAPER 2:',[x for x in q['questions'] if x['paper']==2])
