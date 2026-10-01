"""Print the shared topic numbering, omitting paper-wide instruction sheets."""
import argparse,os
ap=argparse.ArgumentParser();ap.add_argument('--edition',type=int,default=39);ap.add_argument('--merge-only',action='store_true');args=ap.parse_args()
os.environ['CHEMY_EDITION']=str(args.edition)
import copy,json,hashlib
from io import BytesIO
from html import escape
from pypdf import PdfReader,PdfWriter,Transformation
from pypdf.generic import RectangleObject,DecodedStreamObject,NameObject
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from build_library_pdfs import ROOT,CACHE,DATA,SLUGS,W,H,bands,part_path,render_page
from paper1_manifest import PAPER,FIGURES
from library_config import EDITION

pdfmetrics.registerFontFamily('SourceSong',normal='SourceSong',bold='SourceSong',italic='SourceSong',boldItalic='SourceSong')
BANK=json.loads((ROOT/'dist/questions.json').read_text(encoding='utf8'));QUESTIONS={q['id']:q for q in BANK}
NUMBERS=json.loads((ROOT/'dist/numbering.json').read_text(encoding='utf8'))['numberById']
MANIFEST=json.loads(DATA.read_text(encoding='utf8'));NUMBERED=CACHE/'numbered'
LABELS=json.loads((NUMBERED/'labels.json').read_text(encoding='utf8'))['patches'] if (NUMBERED/'labels.json').exists() else {}
TITLE_STYLE=ParagraphStyle('title',fontName='SourceSong',fontSize=12,leading=17)

def specs_for(paper):
    if EDITION!=39 or paper!=1:return MANIFEST['papers'][str(paper) if EDITION==39 else f'{EDITION}-{paper}']['questions']
    result=[]
    for raw in PAPER:
        s=copy.deepcopy(raw);s['figures']={'q':[],'a':[]};q=QUESTIONS[f'chemy39-1-{s["number"]}']
        for k,n,x0,y0,x1,y1,name,alt in FIGURES:
            if f'assets/{name}.webp' in q['body' if k=='q' else 'answer']:s['figures'][k].append({'page':n,'box':[x0,y0,x1,y1],'mode':'band'})
        result.append(s)
    return result

def frame(topic,k,paper,index):
    buf=BytesIO();c=canvas.Canvas(buf,pagesize=(W,H));c.setFont('SourceSong',14)
    c.drawString(62,H-48,f'Chemy 化学竞赛专题题库 · {topic} · '+('题目册' if k=='q' else '答案册'))
    c.setFont('SourceSong',9);c.drawString(62,H-66,f'第{EDITION}届模拟试题{paper} · 专题连续编号')
    c.setLineWidth(.4);c.setStrokeColorRGB(.55,.6,.57);c.line(62,H-77,W-62,H-77)
    c.setFillColorRGB(.3,.3,.3);c.setFont('SourceSong',7.5)
    c.drawString(62,35,'版权归 Chemy 化学奥林匹克团队原命题组所有，仅供学术交流，禁止商业用途。');c.drawRightString(W-62,35,str(index))
    if EDITION==39 and paper==1 and k=='a':
        if topic=='电化学':c.drawString(62,48,'来源校注：原答案 6-5 对应原题 6-4；原代入式遗漏负号，标准电势应为 -0.679 V。')
        if topic=='晶体化学':c.drawString(62,48,'来源校注：Na-O 高度计算“解得”行原文 h2 对应 h1，保留原文与数值。')
    c.save();return PdfReader(buf).pages[0]

def heading(q,cursor):
    n=NUMBERS[q['id']];title=q.get('titleHtml') or escape(q['title'])
    title=reformat_title(title)
    percent='' if q.get('percent') is None else f'，占 {q["percent"]}%'
    p=Paragraph(f'第 {n} 题　{title}（{q["points"]} 分{percent}）',TITLE_STYLE);_,height=p.wrap(W-124,100)
    buf=BytesIO();c=canvas.Canvas(buf,pagesize=(W,H));p.drawOn(c,62,cursor-height)
    c.setFont('SourceSong',8.5);c.setFillColorRGB(.35,.4,.37)
    c.drawString(62,cursor-height-13,f'来源：第{EDITION}届 · 模拟试题{q["paper"]} · 原第{q["number"]}题')
    c.save();return PdfReader(buf).pages[0],height+25

def reformat_title(title):
    import re
    return re.sub(r'<(sub|sup)>',r'<\1>',title)

def create(paper,topic,k,specs):
    dest=part_path(EDITION,paper,SLUGS[topic],k);stamp=dest.with_suffix('.sha256')
    ids={f'chemy{EDITION}-{paper}-{s["number"]}' for s in specs}
    signature=hashlib.sha256(json.dumps({'profile':'numbered-print-v1','specs':specs,'questions':[{key:QUESTIONS[i].get(key) for key in ['id','title','titleHtml','points','percent']} for i in sorted(ids)],'numbers':{i:NUMBERS[i] for i in ids},'labels':{page:[p for p in ps if p['id'] in ids] for page,ps in LABELS.items() if any(p['id'] in ids for p in ps)}},sort_keys=True).encode()).hexdigest()
    if dest.exists() and dest.with_suffix('.json').exists() and stamp.exists() and stamp.read_text()==signature:return
    writer=PdfWriter();target=None;cursor=0;index=0;ledger=[]
    def new_page():
        nonlocal target,cursor,index
        if target is not None:writer.add_page(target)
        index+=1;target=frame(topic,k,paper,index);cursor=H-96
    for spec in specs:
        qid=f'chemy{EDITION}-{paper}-{spec["number"]}';q=QUESTIONS[qid];first=True;record={'id':qid,'number':NUMBERS[qid],'sourceNumber':q['number'],'sourceEdition':EDITION,'sourcePaper':paper}
        for n,lo,hi in spec['question' if k=='q' else 'answer']:
            if EDITION==39 and paper==1:
                if k=='a':
                    from make_pdfs import print_bounds,A
                    lo,hi=print_bounds(A,n,lo,hi)
                bb=[[lo,hi]]
            else:bb=bands(k,n,lo,hi,spec['figures'][k])
            chunks=[]
            for a,b in bb:
                if chunks and b-chunks[-1][0]<570:chunks[-1][1]=b
                else:chunks.append([a,b])
            render_page(k,n);path=NUMBERED/f'{k}-{n:03}.pdf'
            if not path.exists():path=CACHE/k/f'{n:03}-clean.pdf'
            reader=PdfReader(path)
            for a,b in chunks:
                scale=min(1.1,620/max(b-a,1));height=(b-a)*scale
                head,headheight=heading(q,cursor) if first else (None,0)
                if target is None or cursor-height-headheight<70:
                    new_page()
                    if first:head,headheight=heading(q,cursor)
                if first:
                    target.merge_page(head);cursor-=headheight;record['firstPage']=index;first=False
                p=copy.copy(reader.pages[0]);ph=float(p.mediabox.height)
                ff=[f['box'] for f in spec['figures'][k] if f['page']==n and f['box'][1]<b and f['box'][3]>a]
                label_boxes=[v['drawBox'] for v in LABELS.get(f'{k}-{n}',[]) if v['id']==qid and v['box'][1]<b and v['box'][3]>a]
                left=min([84]+[f[0] for f in ff]+[f[0]-.5 for f in label_boxes]);right=max([514]+[f[2] for f in ff]+[f[2]+.5 for f in label_boxes]);p.cropbox=RectangleObject([left,ph-b,right,ph-a])
                floats=[f['box'] for f in spec['figures'][k] if f['page']==n and f.get('mode')=='float']
                if floats:
                    rects=[(left,ph-min(b,hi),right-left,max(0,min(b,hi)-max(a,lo)))]
                    rects += [(f[0],ph-min(b,f[3]),f[2]-f[0],max(0,min(b,f[3])-max(a,f[1]))) for f in floats if f[1]<b and f[3]>a]
                    clip='q\n'+''.join(f'{x:.5f} {y:.5f} {w:.5f} {h:.5f} re\n' for x,y,w,h in rects if h>0)+'W n\n'
                    stream=DecodedStreamObject();stream.set_data(clip.encode()+p.get_contents().get_data()+b'\nQ\n');p[NameObject('/Contents')]=stream
                target.merge_transformed_page(p,Transformation().scale(scale).translate(62-84*scale,cursor-(ph-a)*scale),expand=False);cursor-=height+10
                record['lastPage']=index
        assert not first,qid;ledger.append(record)
    if target is not None:writer.add_page(target)
    writer.compress_identical_objects(remove_duplicates=True,remove_unreferenced=True)
    writer.write(dest);dest.with_suffix('.json').write_text(json.dumps(ledger,ensure_ascii=False,indent=2),encoding='utf8');stamp.write_text(signature)

def merge_all():
    chapters=sorted({(q.get('edition',39),q['paper']) for q in BANK},key=lambda p:(-p[0],p[1]));all_index={};sizes={}
    for topic,slug in SLUGS.items():
        for k,kind in [('q','questions'),('a','answers')]:
            writer=PdfWriter();records=[]
            for e,paper in chapters:
                if not any(q['topic']==topic and q.get('edition',39)==e and q['paper']==paper for q in BANK):continue
                path=part_path(e,paper,slug,k);offset=len(writer.pages);writer.append(path)
                entries=json.loads(path.with_suffix('.json').read_text(encoding='utf8'))
                for entry in entries:
                    entry={**entry,'firstPage':offset+entry['firstPage'],'lastPage':offset+entry['lastPage']};records.append(entry)
                    writer.add_outline_item(f'第{entry["number"]}题 · 第{e}届模拟试题{paper}原第{entry["sourceNumber"]}题',entry['firstPage']-1)
            expected=[q['id'] for q in BANK if q['topic']==topic];assert [r['id'] for r in records]==expected,(topic,kind)
            assert [r['number'] for r in records]==list(range(1,len(expected)+1))
            writer.add_metadata({'/Title':f'Chemy {topic}专题'+('题目册' if k=='q' else '答案册'),'/Author':'Chemy 化学奥林匹克团队（原题与答案）','/Subject':'专题连续编号，题目与小问统一编号；来源单独标注'})
            writer.compress_identical_objects(remove_duplicates=True,remove_unreferenced=True);dest=ROOT/'dist/downloads'/f'{slug}-{kind}.pdf';writer.write(dest)
            all_index[f'{slug}-{kind}']=records;sizes[dest.name]=len(writer.pages);print('BOOK',dest.name,len(writer.pages),'pages',flush=True)
    (ROOT/'data/print_index.json').write_text(json.dumps(all_index,ensure_ascii=False,indent=2),encoding='utf8');print('TOTAL',sum(sizes.values()),'pages',flush=True)

if __name__=='__main__':
    if args.merge_only:merge_all()
    else:
        papers=sorted({q['paper'] for q in BANK if q.get('edition',39)==EDITION})
        for paper in papers:
            specs=specs_for(paper)
            for topic in dict.fromkeys(s['topic'] for s in specs):
                for k in ['q','a']:create(paper,topic,k,[s for s in specs if s['topic']==topic])
            print('PARTS',EDITION,paper,'ready',flush=True)
