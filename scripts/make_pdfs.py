"""Print-ready topic samples retaining the original PDF fonts and graphics."""
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import json
from pypdf import PdfReader,PdfWriter,Transformation
from pypdf.generic import ContentStream,NameObject,RectangleObject
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'dist'/'downloads';OUT.mkdir(exist_ok=True)
Q=PdfReader('C:/Users/Prettibruce/Downloads/第39届Chemy化学奥林匹克竞赛模拟试题题目合集.pdf')
A=PdfReader('C:/Users/Prettibruce/Downloads/第39届Chemy化学奥林匹克竞赛模拟试题参考答案合集.pdf')
pdfmetrics.registerFont(TTFont('SampleSong','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
W,H=A4

def fragment(reader,n,y0,y1):
    page=deepcopy(reader.pages[n-1])
    stream=ContentStream(page.get_contents(),reader)
    # Identify only page-wide background images. Actual diagram images are kept.
    background={'/Image1','/Image2','/Image3','/Image4'} if reader is Q else {'/Image1'}
    stream.operations=[(args,op) for args,op in stream.operations if not(op==b'Do' and str(args[0]) in background)]
    page[NameObject('/Contents')]=stream
    ph=float(page.mediabox.height)
    page.cropbox=RectangleObject([84,ph-y1,512,ph-y0])
    return page,ph

def frame(topic,kind,index,note):
    buf=BytesIO();c=canvas.Canvas(buf,pagesize=A4)
    c.setFont('SampleSong',14);c.drawString(62,H-48,f'Chemy 化学竞赛专题题库 · {topic} · {kind}')
    c.setFont('SampleSong',9);c.drawString(62,H-66,'第39届模拟卷1 · 样例册 · 保留原卷题号、字体及图形')
    c.setLineWidth(.4);c.setStrokeColorRGB(.55,.6,.57);c.line(62,H-77,W-62,H-77)
    c.setFillColorRGB(.3,.3,.3);c.setFont('SampleSong',7.5)
    c.drawString(62,35,'版权归 Chemy 化学奥林匹克团队原命题组所有，仅供学术交流，禁止商业用途。')
    c.drawRightString(W-62,35,str(index))
    if note:c.drawString(62,48,note)
    c.save();return PdfReader(buf).pages[0]

def create(topic,kind,slug,reader,segments,note=''):
    writer=PdfWriter();target=None;cursor=0;idx=0
    for n,y0,y1 in segments:
        height=(y1-y0)*1.1
        if target is None or cursor-height<70:
            if target:writer.add_page(target)
            idx+=1;target=frame(topic,kind,idx,note);cursor=H-96
        source,ph=fragment(reader,n,y0,y1)
        transform=Transformation().scale(1.1).translate(62-84*1.1,cursor-(ph-y0)*1.1)
        target.merge_transformed_page(source,transform,expand=False)
        cursor-=height+19
    if target:writer.add_page(target)
    writer.add_metadata({'/Title':f'Chemy {topic}专题{kind}（样例）','/Author':'Chemy 化学奥林匹克团队（原题与答案）','/Subject':'第39届模拟卷1，专题汇编样例，仅供学术交流'})
    dest=OUT/f'{slug}.pdf';writer.write(dest)
    print(f'{dest.name}: {len(writer.pages)} page(s)')

create('有机化学','题目册','organic-questions',Q,[(7,543,731),(8,73,337)])
create('有机化学','答案册','organic-answers',A,[(11,73,367)])
create('电化学','题目册','electrochemistry-questions',Q,[(6,307,697),(7,73,233)])
create('电化学','答案册','electrochemistry-answers',A,[(8,245,558),(9,73,248)],'注：原答案“6-5”对应题目“6-4”；原代入式遗漏负号，标准电势应为 -0.679 V。')
data_path=ROOT/'dist'/'questions.json'
data=json.loads(data_path.read_text(encoding='utf-8'))
for item in data:item['pdfReady']=True
data_path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
