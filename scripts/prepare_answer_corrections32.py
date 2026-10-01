"""Append official errata as untouched native PDF pages, then splice corrected source ranges.
Original answers and errata remain archived unchanged. No chemistry is redrawn.
"""
import hashlib,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tmp/pdf-engine'))
import pikepdf
CACHE=ROOT/'tmp/library32'
cfg_path=ROOT/'data/editions.json';cfg=json.loads(cfg_path.read_text(encoding='utf8'))
original=ROOT/'sources'/cfg['32'].get('aOriginal',cfg['32']['a'])
errata=ROOT/'sources/第32届Chemy化学奥林匹克答案补正.pdf'
destination=ROOT/'sources/第32届Chemy答案（含官方补正工作源）.pdf'
index=json.loads((CACHE/'a/index.json').read_text(encoding='utf8'))
original_count=len(pikepdf.open(original).pages)
def page(kind,n):return json.loads((CACHE/kind/f'{n:03}.json').read_text(encoding='utf8'))
def anchor(kind,n,prefix):
    matches=[r for r in page(kind,n)['rows'] if r['text'].startswith(prefix)]
    assert matches,(kind,n,prefix)
    return matches[0]['top']-2
def heading_end(n,number):
    rows=[r for r in page('errata',n)['rows'] if r['text'].startswith(f'第{number}题')]
    assert len(rows)==1
    return rows[0]['bottom']+.5
def original_ranges(paper,number):
    heads=index['questions'];i=next(i for i,h in enumerate(heads) if (h['paper'],h['number'])==(paper,number));h=heads[i]
    end=heads[i+1] if i+1<len(heads) and heads[i+1]['paper']==paper else {'page':int(index['papers'].get(str(paper+1),original_count+1)),'top':70}
    ranges=[]
    for n in range(h['page'],end['page']+1):
        lo=h['bottom']+.5 if n==h['page'] else 70
        hi=end['top']-3 if n==end['page'] else min(770,page('a',n)['height']-70)
        if hi>lo+2:ranges.append([n,lo,hi])
    return ranges
def portion(ranges,start=None,end=None):
    out=[]
    for n,lo,hi in ranges:
        if start:
            if n<start[0]:continue
            if n==start[0]:lo=max(lo,start[1])
        if end:
            if n>end[0]:continue
            if n==end[0]:hi=min(hi,end[1])
        if hi>lo+2:out.append([n,lo,hi])
    return out
def er(n,lo,hi):return [original_count+n,lo,hi]
corrections={}
def splice(p,q,new,start=None,end=None):
    old=original_ranges(p,q)
    effective=(portion(old,end=start) if start else [])+new+(portion(old,start=end) if end else [])
    assert effective
    corrections[f'{p}-{q}']={'originalRanges':old,'effectiveRanges':effective,'errataPages':sorted({n-original_count for n,lo,hi in new})}
splice(1,8,[er(1,anchor('errata',1,'8-1-1'),anchor('errata',1,'6-2')-1)],(5,anchor('a',5,'8-1-1')),(5,anchor('a',5,'8-1-2')))
splice(2,6,[er(1,anchor('errata',1,'6-2'),770),er(2,70,anchor('errata',2,'第8题')-1)],(12,anchor('a',12,'6-2')))
splice(2,8,[er(2,heading_end(2,8),anchor('errata',2,'第9题')-1)])
splice(2,9,[er(2,anchor('errata',2,'9-1-1'),770),er(3,70,anchor('errata',3,'6-2')-1)],(14,anchor('a',14,'9-1-1')),(14,anchor('a',14,'9-1-3')))
splice(3,6,[er(3,anchor('errata',3,'6-2'),anchor('errata',3,'第1题')-1)],(19,anchor('a',19,'6-2')),(19,anchor('a',19,'6-3')))
splice(4,1,[er(3,heading_end(3,1),anchor('errata',3,'2-1')-1)])
splice(5,2,[er(3,anchor('errata',3,'2-1'),770),er(4,70,anchor('errata',4,'4-3-2')-1)],(30,anchor('a',30,'2-1')))
splice(12,4,[er(4,anchor('errata',4,'4-3-2'),anchor('errata',4,'第13题')-1)],(94,anchor('a',94,'4-3-2')),(94,anchor('a',94,'4-7')))
splice(12,13,[er(4,heading_end(4,13),770),er(5,70,770),er(6,70,anchor('errata',6,'20-5')-1)])
splice(12,20,[er(6,anchor('errata',6,'20-5'),770)],(108,anchor('a',108,'20-5')))
for key,c in corrections.items():
    for n,lo,hi in c['effectiveRanges']:assert 0<lo<hi<=842 and 1<=n<=original_count+6,(key,n,lo,hi)
with pikepdf.open(original) as book,pikepdf.open(errata) as fix:
    book.pages.extend(fix.pages)
    book.save(destination,compress_streams=True,object_stream_mode=pikepdf.ObjectStreamMode.generate,deterministic_id=True)
    assert len(book.pages)==original_count+6
recipe={'edition':32,'originalPages':original_count,'originalAnswer':original.name,'originalSha256':hashlib.sha256(original.read_bytes()).hexdigest(),'errata':errata.name,'errataSha256':hashlib.sha256(errata.read_bytes()).hexdigest(),'workingAnswer':destination.name,'workingSha256':hashlib.sha256(destination.read_bytes()).hexdigest(),'corrections':corrections}
(ROOT/'data/answer_corrections32.json').write_text(json.dumps(recipe,ensure_ascii=False,indent=2),encoding='utf8')
cfg['32'].update(a=destination.name,aOriginal=original.name,aContentPages=original_count)
cfg_path.write_text(json.dumps(cfg,ensure_ascii=False,indent=2),encoding='utf8')
path=ROOT/'sources/manifest.json';manifest=json.loads(path.read_text(encoding='utf8'))
manifest['editions']['32']['workingFiles']=[{'kind':'a','filename':destination.name,'sha256':recipe['workingSha256'],'bytes':destination.stat().st_size,'derivedFrom':[original.name,errata.name],'recipe':'data/answer_corrections32.json'}]
path.write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf8')
print('CORRECTED',len(corrections),'questions from all 6 official errata pages; originals retained')
