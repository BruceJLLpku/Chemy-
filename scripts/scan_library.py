"""Cache read-only native geometry and locate papers/questions in both source PDFs."""
import hashlib,json,re,sys
from collections import Counter
from pathlib import Path
import pdfplumber
from pypdf import PdfReader
from library_config import ROOT,Q_SOURCE,A_SOURCE,CACHE,EDITION,config

CACHE.mkdir(parents=True,exist_ok=True)

INDEX_VERSION=2
SCORE=re.compile(r'[（(]\s*(?:([\d.]+)\s*分(?:\s*[,，]\s*(?:占(?:比)?\s*)?([\d.]+)\s*[%％])?|占(?:比)?\s*([\d.]+)\s*[%％])\s*[）)]')

def header_paper(text):
    if config.get('series')=='league':
        m=re.match(r'^第\s*(\d+)\s*届.*联赛',text)
        return int(m[1]) if m else None
    if '练习题目集锦' in text:
        return next((int(k) for k,v in config.get('paperLabels',{}).items() if v=='练习题目集锦'),None)
    m=re.search(r'决赛模拟(?:试[题卷])?\s*(\d*)',text)
    if m:label='决赛模拟试题'+m[1]
    else:
        m=re.search(r'((?:有机|无机)化学专题|计算题专题)\s*(\d*)',text)
        if m:label=m[1]+m[2]
        else:
            m=re.search(r'模拟试[题卷]\s*(\d+)',text)
            return int(m[1]) if m else None
    return next((int(k) for k,v in config.get('paperLabels',{}).items() if v==label),None)

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

def index_rows(lines,n,paper,starts,start_tops,headings):
    header=''.join(r['text'] for r in lines if r['top']<130)
    if '目录' not in header:
        for row in lines:
            text=row['text']
            title=re.match(r'^第\s*\d+\s*届',text)
            inline_title=EDITION==40 and re.fullmatch(
                r'第40届Chemy化学奥林匹克[（(](?:初赛|有机|无机)[）)]模拟试题\d+参考答案',text)
            if not title or row['top']>=130 and not inline_title:continue
            matched=header_paper(text)
            if matched is not None:
                if matched!=paper:
                    paper=matched;starts[paper]=n;start_tops[paper]=row['top']
                break
    for row in lines:
        match=re.match(r'^第\s*(\d+)\s*题(.*)',row['text'])
        if not match or not paper or '评判' in match[2]:continue
        owner=paper
        if EDITION==40 and starts[paper]==n and row['top']<start_tops[paper]:
            owner=next((p for p in reversed(starts) if p!=paper),0)
        if not owner:continue
        unscored=config.get('paperLabels',{}).get(str(owner))=='练习题目集锦'
        if EDITION==40:
            score=SCORE.search(match[2])
            if not score:continue
            points=score[1]
            percent=score[2] or score[3]
            title=SCORE.sub('',match[2]).strip()
        else:
            pts=re.search(r'[（(]\s*([\d.]+)\s*分',match[2])
            if not pts and not unscored:continue
            pct=re.search(r'占(?:比)?\s*([\d.]+)\s*[%％]',match[2])
            points=pts[1] if pts else None
            percent=pct[1] if pct else None
            title=re.sub(r'[（(]\s*[\d.]+\s*分.*?[）)]','',match[2]).strip()
        number=int(match[1])
        if any((h['paper'],h['number'])==(owner,number) for h in headings):continue
        headings.append({'paper':owner,'number':number,'title':title,
                         'points':(float(points) if '.' in points else int(points)) if points else None,
                         'percent':float(percent) if percent else None,'page':n,'top':row['top'],'bottom':row['bottom']})
    return paper

def scan(kind,path):
    folder=CACHE/kind;folder.mkdir(exist_ok=True)
    fingerprint=hashlib.sha256(path.read_bytes()).hexdigest()
    manifest_path=folder/'index.json'
    if manifest_path.exists():
        stored=json.loads(manifest_path.read_text(encoding='utf8'))
        if stored['sha256']==fingerprint and all((folder/f'{n:03}.json').exists() for n in stored['pages']):
            if stored.get('indexVersion')==INDEX_VERSION or EDITION!=40:return stored
            paper=0;starts={};start_tops={};headings=[]
            for n in stored['pages']:
                page_path=folder/f'{n:03}.json'
                payload=json.loads(page_path.read_text(encoding='utf8'))
                paper=index_rows(payload['rows'],n,paper,starts,start_tops,headings)
                if payload['paper']!=paper:
                    payload['paper']=paper
                    page_path.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf8')
            stored.update(indexVersion=INDEX_VERSION,papers=starts,paperStartTops=start_tops,questions=headings)
            manifest_path.write_text(json.dumps(stored,ensure_ascii=False,indent=2),encoding='utf8')
            return stored
    reader=PdfReader(path);image_hashes={};image_frequency=Counter();pages=[];paper=0;headings=[];starts={};start_tops={}
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
            paper=index_rows(lines,n,paper,starts,start_tops,headings)
            shape_keys=('x0','x1','top','bottom','width','height','stroke','fill','linewidth','non_stroking_color','stroking_color')
            shapes=[{k:o.get(k) for k in shape_keys} for o in p.curves+p.lines+p.rects]
            payload={'page':n,'paper':paper,'width':p.width,'height':p.height,'chars':chars,'shapes':shapes,'images':images,'rows':lines}
            (folder/f'{n:03}.json').write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf8')
            pages.append(n)
            if n%25==0:print(kind,n,'/',len(doc.pages),flush=True)
            p.close()
    result={'indexVersion':INDEX_VERSION,'sha256':fingerprint,'pages':pages,'papers':starts,'paperStartTops':start_tops,'questions':headings,'imageFrequency':dict(image_frequency)}
    manifest_path.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf8')
    return result

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf8')
    for kind,path in [('q',Q_SOURCE),('a',A_SOURCE)]:
        index=scan(kind,path)
        print(kind,'papers:',index['papers'],'question headings:',len(index['questions']),flush=True)
    q=json.loads((CACHE/'q'/'index.json').read_text(encoding='utf8'));a=json.loads((CACHE/'a'/'index.json').read_text(encoding='utf8'))
    qkeys={(h['paper'],h['number']) for h in q['questions']};akeys={(h['paper'],h['number']) for h in a['questions']}
    print('EDITION',EDITION,'matching',len(qkeys&akeys),'question-only',sorted(qkeys-akeys),'answer-only',sorted(akeys-qkeys),flush=True)
