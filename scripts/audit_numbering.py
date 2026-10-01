"""Verify numbering and preservation separately from the earlier full source audit."""
import argparse,hashlib,json,os,re,subprocess
from collections import Counter
from html.parser import HTMLParser
from pathlib import Path
from PIL import Image,ImageChops,ImageDraw
from pypdf import PdfReader
from paper1_manifest import ROOT,SLUGS

class Html(HTMLParser):
    def __init__(self,s):super().__init__();self.tags=[];self.nodes=[];self.feed(s)
    def handle_starttag(self,t,a):self.tags.append((t,dict(a)))
    def handle_data(self,s):self.nodes.append(s)

def canonical(s,root,original,exceptions=()):
    s=re.sub(r'第\s*'+str(root)+r'\s*题','第#题',s)
    def replace(m):
        prefix,suffix=m.group(1),m.group(2)
        if int(prefix)==root:return '#-'+suffix
        for old,new in exceptions:
            if m.group()==old:return new
        return m.group()
    s=re.sub(r'(?<![\dA-Za-z,，])(\d+)-(\d+(?:-\d+)*)(?![\d.])',replace,s)
    return re.sub(r'\s+','',s)

def main(web_only=False):
    bank=json.loads((ROOT/'dist/questions.json').read_text(encoding='utf8'));numbers=json.loads((ROOT/'dist/numbering.json').read_text(encoding='utf8'))
    display=json.loads((ROOT/'dist/presentation.json').read_text(encoding='utf8'));assert set(display)=={q['id'] for q in bank}==set(numbers['numberById'])
    counts=Counter();report={'questions':len(bank),'nativeSections':0,'numberedCaptures':0,'preservedPixelsOutsideLabels':True,'pdfs':{},'issues':[]}
    for q in bank:
        counts[q['topic']]+=1;n=numbers['numberById'][q['id']];assert n==counts[q['topic']]
        for field in ['body','answer']:
            original=q[field];changed=display[q['id']][field];before=Html(original);after=Html(changed)
            assert [t for t,a in before.tags]==[t for t,a in after.tags],(q['id'],'HTML structure changed')
            assert len(before.nodes)==len(after.nodes),(q['id'],'text nodes changed')
            for a,b in zip(before.nodes,after.nodes):
                if '原答案册将本问编号' in a:assert a==b;continue
                original_exceptions=[];display_exceptions=[]
                if q['id']=='chemy39-8-2':
                    target=numbers['numberById']['chemy39-8-1'];original_exceptions=[('1-2-2','cross-2-2')];display_exceptions=[(f'{target}-2-2','cross-2-2')]
                if q['id']=='chemy36-25-4' and field=='answer':original_exceptions=[('9-4','#-4')]
                assert canonical(a,q['number'],True,original_exceptions)==canonical(b,n,False,display_exceptions),(q['id'],field,a[:110],b[:110])
                if 'eq.' in a:
                    assert re.findall(r'\([\d .-]+eq\.\)',a)==re.findall(r'\([\d .-]+eq\.\)',b),(q['id'],'reagent quantities changed')
            report['nativeSections']+=1
    assert dict(counts)==numbers['countsByTopic']
    assert '提示、常数与评分说明' not in (ROOT/'dist/app.js').read_text(encoding='utf8')
    for e in [39,36,35]:
        cache=ROOT/'tmp'/('library' if e==39 else f'library{e}')
        assets=json.loads((ROOT/'data'/f'numbering-assets-{e}.json').read_text(encoding='utf8'))
        for record in assets:
            page=json.loads((cache/record['kind']/f'{record["page"]:03}.json').read_text(encoding='utf8'))
            with Image.open(cache/record['kind']/f'{record["page"]:03}-clean.png') as im:
                scale=im.width/page['width'];original=im.convert('RGB').crop(tuple(round(v*scale) for v in record['displayBox']))
            asset=ROOT/'dist/assets'/record['asset'];assert hashlib.sha256(asset.read_bytes()).hexdigest()==record['sha256']
            with Image.open(asset) as im:changed=im.convert('RGB')
            assert original.size==changed.size
            diff=ImageChops.difference(original,changed);draw=ImageDraw.Draw(diff)
            for x0,y0,x1,y1 in record['masks']:draw.rectangle((x0,y0,x1-1,y1-1),fill=(0,0,0))
            assert diff.getbbox() is None,(record['id'],'original diagram pixels changed')
            report['numberedCaptures']+=1
    env=os.environ.copy();env.update(GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='safe.directory',GIT_CONFIG_VALUE_0=ROOT.as_posix())
    git='C:/Users/Prettibruce/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe'
    raw=subprocess.run([git,'show','3da5d197f96c8790741aaf2d62ebe0bc76520a1c:dist/questions.json'],cwd=ROOT,env=env,capture_output=True,check=True).stdout
    assert json.loads(raw)==bank,'Original source dataset changed'
    report['originalDatasetPreserved']=True
    if not web_only:
        index=json.loads((ROOT/'data/print_index.json').read_text(encoding='utf8'))
        for topic,slug in SLUGS.items():
            ids=[q['id'] for q in bank if q['topic']==topic]
            for kind in ['questions','answers']:
                entries=index[f'{slug}-{kind}'];assert [x['id'] for x in entries]==ids
                assert [x['number'] for x in entries]==list(range(1,len(ids)+1))
                path=ROOT/'dist/downloads'/f'{slug}-{kind}.pdf';reader=PdfReader(path)
                assert all(1<=x['firstPage']<=x['lastPage']<=len(reader.pages) for x in entries)
                assert len(reader.outline)==len(ids)
                report['pdfs'][path.name]={'pages':len(reader.pages),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'numberedQuestions':len(entries)}
    report['passed']=True
    if not web_only:(ROOT/'data/numbering-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('NUMBERING AUDIT',report['questions'],'questions',report['nativeSections'],'native sections',report['numberedCaptures'],'unchanged diagrams outside label boxes',len(report['pdfs']),'PDFs',flush=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--web-only',action='store_true');args=ap.parse_args();main(args.web_only)
