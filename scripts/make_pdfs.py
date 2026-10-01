"""Topic workbooks retaining original PDF fonts, diagrams, and scoring rules."""
import argparse
from copy import deepcopy
from io import BytesIO
from pathlib import Path
import json
import pdfplumber
from pypdf import PdfReader,PdfWriter,Transformation
from pypdf.generic import ContentStream,NameObject,RectangleObject
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from paper1_manifest import PAPER, SLUGS, Q_SOURCE, A_SOURCE

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'dist'/'downloads';OUT.mkdir(exist_ok=True)
Q=PdfReader(Q_SOURCE)
A=PdfReader(A_SOURCE)
pdfmetrics.registerFont(TTFont('SampleSong','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
W,H=A4
ANSWER_GEOMETRY={}
GEOMETRY_SOURCE=pdfplumber.open(A_SOURCE)

def print_bounds(reader,n,y0,y1):
    if reader is not A:return y0,y1
    if n not in ANSWER_GEOMETRY:
        p=GEOMETRY_SOURCE.pages[n-1]
        ANSWER_GEOMETRY[n]=(p.chars,[o for o in p.lines+p.rects
                                   if o['width']>400 and o['height']<1])
    chars,rules=ANSWER_GEOMETRY[n]
    selected=[c for c in chars if y0-1.1<=c['top']<y1 and c['text'].strip()
              and 84<=c['x0']<512]
    if not selected:return y0,y1
    top=min(c['top'] for c in selected)
    bottom=max(c['bottom'] for c in selected)
    starts=[r for r in rules if 0<=top-r['top']<=6 or abs(r['top']-y0)<=4]
    ends=[r for r in rules if 0<=r['top']-bottom<=12]
    if starts:y0=min(y0,max(r['top'] for r in starts)-1)
    y1=max(y1,bottom+1)
    if ends:y1=max(y1,min(r['bottom'] for r in ends)+1)
    return y0,y1

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
    c.setFont('SampleSong',9);c.drawString(62,H-66,'第39届模拟试题1 · 专题汇编 · 保留原卷题号、字体及图形')
    c.setLineWidth(.4);c.setStrokeColorRGB(.55,.6,.57);c.line(62,H-77,W-62,H-77)
    c.setFillColorRGB(.3,.3,.3);c.setFont('SampleSong',7.5)
    c.drawString(62,35,'版权归 Chemy 化学奥林匹克团队原命题组所有，仅供学术交流，禁止商业用途。')
    c.drawRightString(W-62,35,str(index))
    if note:c.drawString(62,48,note)
    c.save();return PdfReader(buf).pages[0]

def create(topic,kind,slug,reader,segments,note=''):
    writer=PdfWriter();target=None;cursor=0;idx=0
    for n,y0,y1 in segments:
        y0,y1=print_bounds(reader,n,y0,y1)
        height=(y1-y0)*1.1
        if target is None or cursor-height<70:
            if target:writer.add_page(target)
            idx+=1;target=frame(topic,kind,idx,note);cursor=H-96
        source,ph=fragment(reader,n,y0,y1)
        transform=Transformation().scale(1.1).translate(62-84*1.1,cursor-(ph-y0)*1.1)
        target.merge_transformed_page(source,transform,expand=False)
        cursor-=height+10
    if target:writer.add_page(target)
    writer.add_metadata({'/Title':f'Chemy {topic}专题{kind}（模拟试题1）','/Author':'Chemy 化学奥林匹克团队（原题与答案）','/Subject':'第39届模拟试题1，专题汇编，仅供学术交流'})
    dest=OUT/f'{slug}.pdf';writer.write(dest)
    print(f'{dest.name}: {len(writer.pages)} page(s)')

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--topics',nargs='+',choices=list(SLUGS.values()),
                        help='Only regenerate these topic slugs; omit to build all topics.')
    args=parser.parse_args()
    for topic,slug in SLUGS.items():
        if args.topics and slug not in args.topics:continue
        specs=[p for p in PAPER if p['topic']==topic]
        if not specs:continue
        question_ranges=[r for p in specs for r in p['printQuestion']]
        # The original paper-wide instructions also apply to each topic booklet.
        create(topic,'题目册',slug+'-questions',Q,[(4,131,289)]+question_ranges)
        answer_ranges=[r for p in specs for r in p['answer']]
        note=''
        if topic=='电化学':
            note='注：原答案“6-5”对应题目“6-4”；原代入式遗漏负号，标准电势应为 -0.679 V。'
        if topic=='晶体化学':
            note='注：Na-O 高度计算“解得”行原文 h2 对应 h1，保留原文与数值。'
        create(topic,'答案册',slug+'-answers',A,[(3,319,460)]+answer_ranges,note)
    data_path=ROOT/'dist'/'questions.json'
    data=json.loads(data_path.read_text(encoding='utf-8'))
    assert len(data)==10 and {x['number'] for x in data}==set(range(1,11))
    for item in data:
        item['pdfReady']=all((OUT/f'{SLUGS[item["topic"]]}-{kind}.pdf').exists()
                             for kind in ('questions','answers'))
    data_path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    GEOMETRY_SOURCE.close()
