"""Append source-vector booklets for one reviewed paper to each topic."""
import argparse,copy,json
from io import BytesIO
from pathlib import Path
from PIL import Image,ImageOps,ImageDraw
from pypdf import PdfReader,PdfWriter,Transformation
from pypdf.generic import RectangleObject
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from import_library import ROOT,CACHE,DATA,load,render_page,colored,merge,figure_bands
from paper1_manifest import SLUGS,PAPER

OUT=ROOT/'dist/downloads';PARTS=CACHE/'books';PARTS.mkdir(exist_ok=True)
pdfmetrics.registerFont(TTFont('SourceSong','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
W,H=A4
def frame(topic,kind,paper,index):
    buf=BytesIO();c=canvas.Canvas(buf,pagesize=A4)
    c.setFont('SourceSong',14);c.drawString(62,H-48,f'Chemy 化学竞赛专题题库 · {topic} · {kind}')
    c.setFont('SourceSong',9);c.drawString(62,H-66,f'第39届模拟试题{paper} · 保留原卷题号、字体及图形')
    c.setLineWidth(.4);c.setStrokeColorRGB(.55,.6,.57);c.line(62,H-77,W-62,H-77)
    c.setFillColorRGB(.3,.3,.3);c.setFont('SourceSong',7.5)
    c.drawString(62,35,'版权归 Chemy 化学奥林匹克团队原命题组所有，仅供学术交流，禁止商业用途。')
    c.drawRightString(W-62,35,str(index));c.save();return PdfReader(buf).pages[0]
def bands(k,n,lo,hi):
    d=load(k,n)
    cc=[c for c in d['chars'] if c['text'].strip() and lo-1<=c['top']<hi and 85<c['x0']<514 and (k=='q' or colored(c['non_stroking_color']))]
    bb=figure_bands(k,d,lo,hi)+[[max(lo,c['top']-1),min(hi+8,c['bottom']+1)] for c in cc]
    return merge(bb,4)
def create(paper,topic,k,specs):
    writer=PdfWriter();target=None;cursor=0;idx=0
    for spec in specs:
        for n,lo,hi in spec['printQuestion' if k=='q' else 'answer']:
            bb=bands(k,n,lo,hi)
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
                target.merge_transformed_page(p,Transformation().scale(scale).translate(62-84*scale,cursor-(ph-a)*scale),expand=False)
                cursor-=height+10
    if target is not None:writer.add_page(target)
    writer.compress_identical_objects(remove_duplicates=True,remove_unreferenced=True)
    path=PARTS/f'{paper:02}-{SLUGS[topic]}-{k}.pdf';writer.write(path);return path
def build(paper):
    manifest=json.loads(DATA.read_text(encoding='utf8'));chapter=manifest['papers'][str(paper)];specs=chapter['questions']
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
            writer=PdfWriter()
            for n in range(1,paper+1):
                path=PARTS/f'{n:02}-{slug}-{k}.pdf'
                if path.exists():writer.append(path)
            writer.add_metadata({'/Title':f'Chemy {topic}专题'+('题目册' if k=='q' else '答案册'),'/Author':'Chemy 化学奥林匹克团队（原题与答案）','/Subject':f'第39届模拟试题1–{paper}，专题汇编'})
            writer.compress_identical_objects(remove_duplicates=True,remove_unreferenced=True);writer.write(target)
            print(target.name,len(writer.pages),'pages',round(target.stat().st_size/1024),'KB',flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('paper',type=int);build(ap.parse_args().paper)
