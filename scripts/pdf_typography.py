"""Match the original Chemy papers: Song Chinese and Times New Roman Latin."""
import re
from html import escape
from html.parser import HTMLParser
from io import BytesIO
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.pagesizes import A4
from source_info import question_source,score_text

STYLE = 'original-paper-type-v3'
W,H=A4
pdfmetrics.registerFont(TTFont('PaperSong','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
for name,file in [('PaperTimes','times.ttf'),('PaperTimesBold','timesbd.ttf'),('PaperTimesItalic','timesi.ttf')]:
    pdfmetrics.registerFont(TTFont(name,'C:/Windows/Fonts/'+file))
pdfmetrics.registerFontFamily('PaperSong',normal='PaperSong',bold='PaperSong',italic='PaperSong',boldItalic='PaperSong')

class MixedText(HTMLParser):
    def __init__(self,latin):
        super().__init__(convert_charrefs=True);self.latin=latin;self.parts=[]
    def handle_data(self,data):
        for part in re.split(r'([\x20-\x7e]+)',data):
            if not part:continue
            value=escape(part)
            self.parts.append(f'<font name="{self.latin}">{value}</font>' if part.isascii() else value)
    def handle_starttag(self,tag,attrs):
        if tag in ['sub','sup','b','i']:self.parts.append('<'+tag+'>')
    def handle_endtag(self,tag):
        if tag in ['sub','sup','b','i']:self.parts.append('</'+tag+'>')

def mixed(html,bold=False):
    parser=MixedText('PaperTimesBold' if bold else 'PaperTimes');parser.feed(html)
    return ''.join(parser.parts)

def para(html,size,leading,bold=False,alignment=0,color=(0,0,0)):
    return Paragraph(mixed(html,bold),ParagraphStyle('paper',fontName='PaperSong',fontSize=size,
                     leading=leading,alignment=alignment,textColor=color))

def paint(c,p,x,y,width,bold=False):
    _,height=p.wrap(width,100)
    c.saveState()
    if bold:
        # The original Word-exported papers use stroked SimSun for Chinese bold.
        c.setLineWidth(.11);c.setStrokeColorRGB(0,0,0)
        c._code.append('2 Tr')
    p.drawOn(c,x,y)
    c.restoreState()
    return height

def title_html(q,number):
    title=q.get('titleHtml') or escape(q['title'])
    if q['id']=='chemy32-12-22':title=title.replace('5-4',f'{number}-4')
    return title

def heading(c,q,number,cursor,legacy_height=None):
    title=title_html(q,number)
    if legacy_height is None:
        old=Paragraph(f'第 {number} 题　{title}{score_text(q)}',ParagraphStyle('old',fontName='PaperSong',fontSize=12,leading=17))
        legacy_height=old.wrap(W-124,100)[1]
    size=10.56
    text=f'第 {number} 题 {title}{score_text(q)}'
    p=para(text,size,17,True)
    while p.wrap(W-124,100)[1]>legacy_height+.01:
        size-=.2
        assert size>=9.5,(q['id'],'title does not fit original heading')
        p=para(text,size,17,True)
    paint(c,p,62,cursor-legacy_height,W-124,True)
    source=para(escape(question_source(q)),8.5,10.2,color=(.35,.35,.35))
    # Same baseline and allocated heading space as the existing continuous books.
    paint(c,source,62,cursor-legacy_height-13-1.7,W-124)
    return legacy_height

def frame(topic,kind,count,number,total=None):
    buf=BytesIO();c=canvas.Canvas(buf,pagesize=A4)
    label='题目册' if kind=='questions' else '答案册'
    p=para(f'Chemy 化学竞赛专题题库　{escape(topic)}　{label}',11.04,14,True,alignment=1)
    paint(c,p,62,H-62,W-124,True)
    p=para(f'（{count} 道题　专题连续编号）',10.56,14,True,alignment=1)
    paint(c,p,62,H-77.6,W-124,True)
    # Original paper mastheads use two centered lines without a dashboard rule.
    p=para('版权归 Chemy 化学奥林匹克团队原命题组所有，仅供学术交流，禁止商业用途。',7.5,9,color=(.4,.4,.4))
    paint(c,p,62,33.5,W-124)
    c.setFont('PaperTimes',9);c.setFillColorRGB(.266667,.447059,.768627)
    c.drawCentredString(W/2,22,str(number)+(' / '+str(total) if total else ''))
    c.save();return buf.getvalue()

def groups(data):
    """ReportLab uses isolated top-level q/Q groups for each heading then labels."""
    depth=0;start=None;offset=0;result=[]
    for line in data.splitlines(keepends=True):
        token=line.strip()
        if token==b'q':
            if depth==0:start=offset
            depth+=1
        elif token==b'Q':
            depth-=1
            assert depth>=0
            if depth==0:result.append((start,offset+len(line)))
        offset+=len(line)
    assert depth==0
    return result

def style_form(pdf,form,ids,questions,numbers,pikepdf):
    """Replace only generated headings; preserve native static content and labels."""
    if not ids or form.get('/ChemyTypography')==STYLE:return False
    objects=form['/Resources']['/XObject']
    overlays=[o for key,o in objects.items() if key not in ['/Static','/ChemyWatermark']]
    assert len(overlays)==1,(ids,'unexpected source overlay')
    overlay=overlays[0];old=overlay.read_bytes();blocks=groups(old)
    assert len(blocks)>=len(ids)
    buf=BytesIO();c=canvas.Canvas(buf,pagesize=A4)
    removed=[]
    for qid,(a,b) in zip(ids,blocks):
        block=old[a:b]
        assert re.search(rb' 12 Tf',block) and re.search(rb' 8\.5 Tf',block),(qid,'unexpected heading block')
        y=float(re.search(rb'1 0 0 1 62 ([\d.]+) cm',block).group(1))
        q=questions[qid];n=numbers[qid]
        title=title_html(q,n)
        oldp=Paragraph(f'第 {n} 题　{title}{score_text(q)}',ParagraphStyle('legacy',fontName='PaperSong',fontSize=12,leading=17))
        height=oldp.wrap(W-124,100)[1]
        heading(c,q,n,y+height,height)
        removed.append((a,b))
    c.save()
    tail=old[removed[-1][1]:]
    overlay.write(old[:removed[0][0]]+tail)
    with pikepdf.open(BytesIO(buf.getvalue())) as replacement:
        new=pdf.copy_foreign(replacement.pages[0].as_form_xobject())
    objects['/ChemyTypesetHeadings']=new
    form.write(form.read_bytes()+b'\nq /ChemyTypesetHeadings Do Q\n')
    form['/ChemyTypography']=STYLE
    form['/ChemyPreservedLabels']=pikepdf.String(__import__('hashlib').sha256(tail).hexdigest())
    return True
