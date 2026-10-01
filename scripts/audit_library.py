"""Final cross-edition source/content/resource audit; never marks visual review complete."""
import argparse,hashlib,json,re
from collections import Counter,defaultdict
from functools import lru_cache
from html.parser import HTMLParser
from pathlib import Path
import xml.etree.ElementTree as ET
from PIL import Image,ImageChops
from pypdf import PdfReader
from paper1_manifest import ROOT,SLUGS

REPORT=ROOT/'data/audit_report.json'
EXCEPTIONS=json.loads((ROOT/'data/source_exceptions.json').read_text(encoding='utf8'))
def read(path):return json.loads(path.read_text(encoding='utf8'))
def cache_for(e):return ROOT/'tmp'/('library' if e==39 else f'library{e}')
@lru_cache(maxsize=6)
def source_index(e,k):return read(cache_for(e)/k/'index.json')
def digest(raw):return hashlib.sha256(raw).hexdigest()
def colored(color):return isinstance(color,(tuple,list)) and len(color)>=3 and max(color[:3])-min(color[:3])>.12
def part(e,p,slug,k):return ROOT/'tmp/library/books'/f'{p:02}-{slug}-{k}.pdf' if e==39 else ROOT/'tmp/library/books'/f'e{e}-{p:02}-{slug}-{k}.pdf'
@lru_cache(maxsize=16)
def geometry(e,k,n):
    data=read(cache_for(e)/k/f'{n:03}.json');seen=set();chars=[]
    for c in data['chars']:
        key=(c['text'],round(c['x0'],2),round(c['x1'],2),round(c['top'],2),round(c['bottom'],2),c['fontname'],str(c['non_stroking_color']))
        if key not in seen:seen.add(key);chars.append(c)
    data['chars']=chars;return data
class Text(HTMLParser):
    def __init__(self):super().__init__();self.parts=[]
    def handle_data(self,data):self.parts.append(data)
def text_of(html):
    parser=Text();parser.feed(html);return ''.join(parser.parts)
def chars_of(text):return Counter(c for c in text.replace('\uf044','Δ') if not c.isspace())

def audit(pixels=True,books=True):
    bank=read(ROOT/'dist/questions.json');manifest=read(ROOT/'data/library_manifest.json');notes=read(ROOT/'dist/papers.json')
    expected={}
    for e in sorted({q.get('edition',39) for q in bank},reverse=True):
        index=source_index(e,'q')
        expected[e]=(len(index['papers']),len({(h['paper'],h['number']) for h in index['questions']}))
    issues=[];candidates=[];checks=Counter();bykey={(q.get('edition',39),q['paper'],q['number']):q for q in bank}
    def require(condition,code,context):
        if not condition:issues.append({'code':code,**context})
    require(len(bykey)==len(bank)==sum(n for _,n in expected.values()),'total_or_duplicate',{'count':len(bank)})
    original=read(ROOT/'tmp/approved-paper1.json')
    require([q for q in bank if q.get('edition',39)==39 and q['paper']==1]==original,'approved_sample_changed',{})
    for e,(papers,count) in expected.items():
        qindex=source_index(e,'q');aindex=source_index(e,'a')
        sourcekeys={(e,h['paper'],h['number']) for h in qindex['questions']}
        require(sourcekeys=={(e,h['paper'],h['number']) for h in aindex['questions']},'source_pairing',{'edition':e})
        require(sourcekeys=={key for key in bykey if key[0]==e},'bank_source_keys',{'edition':e})
        require(len(sourcekeys)==count and len(qindex['papers'])==papers,'edition_totals',{'edition':e})
        entry=read(ROOT/'sources/manifest.json')['editions'][str(e)]
        sources=entry['originalFiles']+entry.get('workingFiles',[])
        config=read(ROOT/'data/editions.json')[str(e)]
        for source in sources:
            require(digest((ROOT/'sources'/source['filename']).read_bytes())==source['sha256'],'source_changed',{'edition':e,'kind':source['kind']})
            if source['kind'] in ['q','a'] and source['filename']==config[source['kind']]:
                require(source['sha256']=={'q':qindex,'a':aindex}[source['kind']]['sha256'],'source_index_changed',{'edition':e,'kind':source['kind']})
        checks['source_questions']+=count
    allhtml=[q['body']+q['answer'] for q in bank]+[str(n.get('instructions',''))+str(n.get('scoring','')) for n in list(notes.values())+[read(ROOT/'dist/paper1-notes.json')]]
    allrefs={name for html in allhtml for name in re.findall(r'src="assets/([^\"]+)"',html)}
    for name in sorted(allrefs):
        path=ROOT/'dist/assets'/name
        require(path.is_file(),'missing_image',{'asset':name})
        if path.is_file():
            try:
                if path.suffix.lower()=='.svg':assert ET.parse(path).getroot().tag.endswith('svg')
                else:
                    with Image.open(path) as im:im.verify()
                checks['decodable_images']+=1
            except Exception as exc:issues.append({'code':'image_decode','asset':name,'error':str(exc)})
    grouped=defaultdict(list)
    for key,chapter in manifest['papers'].items():
        e,p=map(int,key.split('-')) if '-' in key else (39,int(key))
        records=chapter['questions']
        for record in records:
            q=bykey.get((e,p,record['number']));context={'edition':e,'paper':p,'number':record['number']}
            if q is None:continue
            require(q['topic']==record['topic'] and q['topic'] in SLUGS,'topic_record',context)
            for k,field in [('q','body'),('a','answer')]:
                html=q[field];figures=record['figures'][k];ranges=record['question' if k=='q' else 'answer']
                expected=Counter()
                for n,lo,hi in ranges:
                    d=geometry(e,k,n);ff=[f['box'] for f in figures if f['page']==n]
                    for c in d['chars']:
                        center=(c['top']+c['bottom'])/2
                        if lo-1<=c['top']<hi and 85<=c['x0']<514 and (k=='q' or colored(c['non_stroking_color'])) and not any(box[0]<=(c['x0']+c['x1'])/2<=box[2] and box[1]<=center<=box[3] for box in ff):expected.update(chars_of(c['text']))
                    def covered(obj):
                        return any(box[0]-1<=obj['x0'] and obj['x1']<=box[2]+1 and box[1]-1<=obj['top'] and obj['bottom']<=box[3]+1 for box in ff)
                    for c in d['chars']:
                        if not c['text'].strip() or k=='a' and not colored(c['non_stroking_color']):continue
                        if lo<=c['top']<hi and 75<=c['x0']<590 and not 85<=c['x0']<514 and not covered(c):
                            candidates.append({**context,'kind':k,'page':n,'code':'glyph_outside_native_region','text':c['text'],'box':[c['x0'],c['top'],c['x1'],c['bottom']]})
                        if hi==766 and 766<=c['top']<771 and 85<=c['x0']<550:
                            candidates.append({**context,'kind':k,'page':n,'code':'glyph_near_footer_cut','text':c['text'],'box':[c['x0'],c['top'],c['x1'],c['bottom']]})
                    for obj in d['shapes']+d['images']:
                        if obj['bottom']<lo or obj['top']>=hi or obj['x1']<75 or obj['x0']>550:continue
                        if 'hash' in obj:
                            index=source_index(e,k)
                            if obj['hash'] in EXCEPTIONS['backgroundHashes'] or obj['width']>400 and 89<obj['x0']<92 and 190<obj['top']<645 and index['imageFrequency'].get(obj['hash'],0)>10:continue
                            eligible=k=='q'
                        else:
                            color=obj['non_stroking_color']
                            if not obj.get('stroke') and obj.get('fill') and isinstance(color,(list,tuple)) and len(color)>=3 and min(color[:3])>.99:continue
                            if obj['width']>400 and (obj['height']>500 or obj['height']<1 and (obj['top']<75 or obj['top']>770)):continue
                            eligible=k=='q' or colored(obj['stroking_color']) or colored(obj['non_stroking_color'])
                            if k=='a' and not eligible and obj['width']>100 and obj['height']>30:
                                red=sum(colored(c['non_stroking_color']) and obj['x0']<c['x0']<obj['x1'] and obj['top']<c['top']<obj['bottom'] for c in d['chars'])
                                if red>8 and not covered(obj):candidates.append({**context,'kind':k,'page':n,'code':'black_table_with_answer','box':[obj['x0'],obj['top'],obj['x1'],obj['bottom']]})
                        if eligible and not covered(obj):
                            candidates.append({**context,'kind':k,'page':n,'code':'graphic_boundary' if obj['top']<lo or obj['bottom']>hi else 'uncaptured_source_graphic','box':[obj['x0'],obj['top'],obj['x1'],obj['bottom']]})
                actual=chars_of(text_of(html))
                require(actual==expected,'native_glyph_coverage',{**context,'kind':k,'missing':dict(expected-actual),'extra':dict(actual-expected)})
                require(not re.search(r'\(cid:\d+\)|[\ue000-\uf043\uf045-\uf8ff\ufffd]',text_of(html)),'unsupported_native_glyph',{**context,'kind':k})
                for f in figures:grouped[(e,k,f['page'])].append(f)
                checks['paired_sections']+=1
        for f in chapter.get('common',{}).get('figures',[]):grouped[(e,'q',f['page'])].append(f)
    for (e,k,n),figures in sorted(grouped.items()):
        page=geometry(e,k,n);image=None
        if pixels:image=Image.open(cache_for(e)/k/f'{n:03}-clean.png').convert('RGB')
        for f in figures:
            path=ROOT/'dist/assets'/f['asset'];context={'edition':e,'kind':k,'page':n,'asset':f['asset']}
            require(path.is_file() and digest(path.read_bytes())==f['sha256'],'image_manifest_hash',context)
            x0,y0,x1,y1=f['box'];require(0<=x0<x1<=page['width'] and 0<=y0<y1<=page['height'],'crop_outside_page',context)
            if image:
                sc=image.width/page['width'];expected=image.crop(tuple(round(v*sc) for v in f['box']))
                with Image.open(path) as output:
                    actual=output.convert('RGB');require(actual.size==expected.size and ImageChops.difference(actual,expected).getbbox() is None,'original_crop_pixels',context)
            checks['original_captures']+=1
        if image:image.close()
    if books:
        for topic,slug in SLUGS.items():
            chapters=sorted({(q.get('edition',39),q['paper']) for q in bank if q['topic']==topic},key=lambda pair:(-pair[0],pair[1]))
            for k,kind in [('q','questions'),('a','answers')]:
                target=ROOT/'dist/downloads'/f'{slug}-{kind}.pdf';book=PdfReader(target);offset=0
                for e,p in chapters:
                    chapter_path=part(e,p,slug,k);require(chapter_path.is_file(),'missing_print_chapter',{'edition':e,'paper':p,'topic':topic,'kind':k})
                    if not chapter_path.exists():continue
                    reader=PdfReader(chapter_path)
                    for page in reader.pages:
                        require(offset<len(book.pages) and digest(page.get_contents().get_data())==digest(book.pages[offset].get_contents().get_data()),'print_chapter_content',{'edition':e,'paper':p,'topic':topic,'kind':k,'page':offset+1})
                        offset+=1
                require(offset==len(book.pages),'print_page_total',{'topic':topic,'kind':k,'pages':len(book.pages),'expected':offset})
                checks['topic_pdfs']+=1;checks['print_pages']+=len(book.pages)
    candidates=list({json.dumps(c,sort_keys=True):c for c in candidates}.values())
    report={'scope':{str(e):{'papers':p,'questions':n} for e,(p,n) in expected.items()},'methods':{'losslessSourcePixelComparison':pixels,'printChapterContentComparison':books,'nativeGlyphCoverage':True,'sourcePairingAndHashes':True},'checks':dict(checks),'issues':issues,'reviewCandidates':candidates,'automatedPassed':not issues,'visualReviewComplete':False}
    REPORT.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print(json.dumps({'checks':dict(checks),'issues':len(issues),'reviewCandidates':len(candidates),'report':str(REPORT)},ensure_ascii=False),flush=True)
    for issue in issues[:12]:print(json.dumps(issue,ensure_ascii=False),flush=True)
    return report
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--no-pixels',action='store_true');ap.add_argument('--no-books',action='store_true');args=ap.parse_args();audit(not args.no_pixels,not args.no_books)
