"""Append source-vector booklets for one reviewed paper to each topic."""
import argparse,copy,json
from io import BytesIO
from pathlib import Path
from PIL import Image,ImageOps,ImageDraw
from pypdf import PdfReader,PdfWriter,Transformation
from pypdf.generic import RectangleObject,DecodedStreamObject,NameObject
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from import_library import ROOT,CACHE,DATA,load,render_page,colored,merge,figure_bands,foreign_float_boxes,char_inside
from paper1_manifest import SLUGS,PAPER
from library_config import EDITION,paper_key

OUT=ROOT/'dist/downloads';PARTS=ROOT/'tmp/library/books';PARTS.mkdir(exist_ok=True)

def part_path(edition,paper,slug,k):
    prefix=f'{paper:02}' if edition==39 else f'e{edition}-{paper:02}'
    return PARTS/f'{prefix}-{slug}-{k}.pdf'
pdfmetrics.registerFont(TTFont('SourceSong','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
W,H=A4
def frame(topic,kind,paper,index):
    buf=BytesIO();c=canvas.Canvas(buf,pagesize=A4)
    c.setFont('SourceSong',14);c.drawString(62,H-48,f'Chemy 化学竞赛专题题库 · {topic} · {kind}')
    c.setFont('SourceSong',9);c.drawString(62,H-66,f'第{EDITION}届模拟试题{paper} · 保留原卷题号、字体及图形')
    c.setLineWidth(.4);c.setStrokeColorRGB(.55,.6,.57);c.line(62,H-77,W-62,H-77)
    c.setFillColorRGB(.3,.3,.3);c.setFont('SourceSong',7.5)
    c.drawString(62,35,'版权归 Chemy 化学奥林匹克团队原命题组所有，仅供学术交流，禁止商业用途。')
    c.drawRightString(W-62,35,str(index));c.save();return PdfReader(buf).pages[0]
def bands(k,n,lo,hi,figures=(),paper=None,number=None):
    d=load(k,n)
    ff=[f['box'] for f in figures if f['page']==n and (f.get('mode')=='float' or f['box'][1]<hi and f['box'][3]>lo)];floats=[f['box'] for f in figures if f['page']==n and f.get('mode')=='float']
    foreign=foreign_float_boxes(k,paper,number,n) if paper is not None else []
    cc=[c for c in d['chars'] if c['text'].strip() and lo-1<=c['top']<hi and 85<c['x0']<514 and (k=='q' or colored(c['non_stroking_color'])) and not any(char_inside(c,b) for b in foreign)]
    bb=figure_bands(k,d,lo,hi,floats+foreign)+[[max(lo,c['top']-1),min(hi+8,c['bottom']+1)] for c in cc]+[[box[1],box[3]] for box in ff]
    return merge(bb,4)
def create(paper,topic,k,specs):
    writer=PdfWriter();target=None;cursor=0;idx=0
    for spec in specs:
        for n,lo,hi in spec['printQuestion' if k=='q' else 'answer']:
            bb=bands(k,n,lo,hi,spec['figures'][k])
            # Preserve source gaps inside each fitting block; break only in blank gaps.
            chunks=[]
            for a,b in bb:
                if chunks and b-chunks[-1][0]<610:chunks[-1][1]=b
                else:chunks.append([a,b])
            render_page(k,n);reader=PdfReader(CACHE/k/f'{n:03}-clean.pdf')
            for a,b in chunks:
                scale=min(1.1,670/max(b-a,1));height=(b-a)*scale
                if target is None or cursor-height<70:
                    if target is not None:writer.add_page(target)
                    idx+=1;target=frame(topic,'题目册' if k=='q' else '答案册',paper,idx);cursor=H-96
                p=copy.copy(reader.pages[0]);ph=float(p.mediabox.height)
                ff=[f['box'] for f in spec['figures'][k] if f['page']==n and f['box'][1]<b and f['box'][3]>a]
                left=min([84]+[f[0] for f in ff]);right=max([514]+[f[2] for f in ff]);p.cropbox=RectangleObject([left,ph-b,right,ph-a])
                floats=[f['box'] for f in spec['figures'][k] if f['page']==n and f.get('mode')=='float']
                if floats:
                    rects=[(left,ph-min(b,hi),right-left,max(0,min(b,hi)-max(a,lo)))]
                    rects += [(f[0],ph-min(b,f[3]),f[2]-f[0],max(0,min(b,f[3])-max(a,f[1]))) for f in floats if f[1]<b and f[3]>a]
                    clip='q\n'+''.join(f'{x:.5f} {y:.5f} {w:.5f} {h:.5f} re\n' for x,y,w,h in rects if h>0)+'W n\n'
                    stream=DecodedStreamObject();stream.set_data(clip.encode()+p.get_contents().get_data()+b'\nQ\n');p[NameObject('/Contents')]=stream
                target.merge_transformed_page(p,Transformation().scale(scale).translate(62-84*scale,cursor-(ph-a)*scale),expand=False)
                cursor-=height+10
    if target is not None:writer.add_page(target)
    writer.compress_identical_objects(remove_duplicates=True,remove_unreferenced=True)
    path=part_path(EDITION,paper,SLUGS[topic],k);writer.write(path);return path
def merge_all():
    manifest=json.loads(DATA.read_text(encoding='utf8'));chapters={(39,1)}
    for key in manifest['papers']:
        edition,n=map(int,key.split('-')) if '-' in key else (39,int(key));chapters.add((edition,n))
    for topic,slug in SLUGS.items():
        for k,kind in [('q','questions'),('a','answers')]:
            writer=PdfWriter()
            for edition,n in sorted(chapters,key=lambda pair:(-pair[0],pair[1])):
                path=part_path(edition,n,slug,k)
                if path.exists():writer.append(path)
            writer.add_metadata({'/Title':f'Chemy {topic}专题'+('题目册' if k=='q' else '答案册'),'/Author':'Chemy 化学奥林匹克团队（原题与答案）','/Subject':'、'.join(f'第{e}届' for e in sorted({e for e,n in chapters},reverse=True))+'模拟试题专题汇编'})
            writer.compress_identical_objects(remove_duplicates=True,remove_unreferenced=True);target=OUT/f'{slug}-{kind}.pdf';writer.write(target)
            print(target.name,len(writer.pages),'pages',flush=True)
def build(paper,parts_only=False):
    manifest=json.loads(DATA.read_text(encoding='utf8'));chapter=manifest['papers'][paper_key(paper)];specs=chapter['questions']
    for topic in dict.fromkeys(s['topic'] for s in specs):
        slug=SLUGS[topic]
        for k,kind in [('q','questions'),('a','answers')]:
            target=OUT/f'{slug}-{kind}.pdf';base=PARTS/f'01-{slug}-{k}.pdf'
            saved=ROOT/'data/book_bases'/base.name
            if not base.exists() and saved.exists():base.write_bytes(saved.read_bytes())
            elif not base.exists() and target.exists() and any(q['topic']==topic for q in PAPER):base.write_bytes(target.read_bytes())
            ss=[s for s in specs if s['topic']==topic]
            if k=='q' and chapter.get('common',{}).get('question'):
                ss=[{'printQuestion':chapter['common']['question'],'figures':{'q':chapter['common']['figures']}}]+ss
            create(paper,topic,k,ss)
            if parts_only:continue
            writer=PdfWriter()
            chapters={(39,1)}
            for key in manifest['papers']:
                edition,n=map(int,key.split('-')) if '-' in key else (39,int(key))
                chapters.add((edition,n))
            for edition,n in sorted(chapters,key=lambda pair:(-pair[0],pair[1])):
                path=part_path(edition,n,slug,k)
                if path.exists():writer.append(path)
            writer.add_metadata({'/Title':f'Chemy {topic}专题'+('题目册' if k=='q' else '答案册'),'/Author':'Chemy 化学奥林匹克团队（原题与答案）','/Subject':'、'.join(f'第{e}届' for e in sorted({e for e,n in chapters},reverse=True))+'模拟试题专题汇编'})
            writer.compress_identical_objects(remove_duplicates=True,remove_unreferenced=True);writer.write(target)
            print(target.name,len(writer.pages),'pages',round(target.stat().st_size/1024),'KB',flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('paper',type=int,nargs='?');ap.add_argument('--parts-only',action='store_true');ap.add_argument('--merge-only',action='store_true');args=ap.parse_args()
    if args.merge_only:merge_all()
    else:build(args.paper,args.parts_only)
