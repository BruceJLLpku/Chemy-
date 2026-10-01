"""Change presentation labels only; immutable source questions and diagrams remain archived.

PDF labels are clipped and replaced as vector text, never by redrawing chemistry.
Raster captures containing a label reuse the identical old pixels outside its box.
"""
import argparse,os
_ap=argparse.ArgumentParser();_ap.add_argument('--edition',type=int,default=39);_ap.add_argument('--plan-only',action='store_true')
_args=_ap.parse_args();os.environ['CHEMY_EDITION']=str(_args.edition)
import copy,hashlib,json,re,subprocess
from collections import defaultdict
from functools import lru_cache
from html import unescape
from io import BytesIO
from pathlib import Path
from PIL import Image
from pypdf import PdfReader,PdfWriter
from pypdf.generic import DecodedStreamObject,NameObject
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from import_library import ROOT,CACHE,DATA,load,render_page,colored,SOURCES
from paper1_manifest import PAPER,FIGURES
from display_numbering import write_numbering,renumber_attributes

EDITION=_args.edition;OUT=CACHE/'numbered';OUT.mkdir(exist_ok=True)
pdfmetrics.registerFont(TTFont('LabelRegular','C:/Windows/Fonts/times.ttf'))
pdfmetrics.registerFont(TTFont('LabelBold','C:/Windows/Fonts/timesbd.ttf'))
pdfmetrics.registerFont(TTFont('LabelSong','C:/Windows/Fonts/simsun.ttc',subfontIndex=0))
BANK=json.loads((ROOT/'dist/questions.json').read_text(encoding='utf8'))
NUMBER=write_numbering(BANK)['numberById'];QUESTIONS={q['id']:q for q in BANK}
# Verified cross-question reference; ordinary reaction/spectrum ranges are not labels.
CROSS_REFERENCES={('chemy39-8-2','1-2-2'):'chemy39-8-1'}
LABEL_CORRECTIONS={('chemy39-1-6','a','6-5'):'6-4',('chemy36-25-4','a','9-4'):'4-4'}

def first_specs():
    result=[]
    for raw in PAPER:
        s=copy.deepcopy(raw);s['figures']={'q':[],'a':[]}
        q=QUESTIONS[f'chemy39-1-{s["number"]}']
        for k,n,x0,y0,x1,y1,name,alt in FIGURES:
            if f'assets/{name}.webp' in q['body' if k=='q' else 'answer']:
                s['figures'][k].append({'page':n,'box':[x0,y0,x1,y1],'asset':name+'.webp','mode':'band'})
        result.append(s)
    return result

MANIFEST=json.loads(DATA.read_text(encoding='utf8'))
SPECS={}
if EDITION==39:SPECS[1]=first_specs()
for key,chapter in MANIFEST['papers'].items():
    e,p=map(int,key.split('-')) if '-' in key else (39,int(key))
    if e==EDITION:SPECS[p]=chapter['questions']

def runs(chars):
    """Keep one text baseline/font and only contiguous numeric characters."""
    rows=defaultdict(list)
    for c in chars:
        if c['text'].strip() and c['size']>=9.5:
            rows[(round(c['bottom'],1),c['fontname'],round(c['size'],2),str(c['non_stroking_color']))].append(c)
    out=[]
    for cs in rows.values():
        current=[]
        for c in sorted(cs,key=lambda c:c['x0']):
            if re.fullmatch(r'[\d-]+',c['text']) and (not current or c['x0']-current[-1]['x1']<1.4):current.append(c)
            else:
                if current:out.append(current)
                current=[c] if re.fullmatch(r'[\d-]+',c['text']) else []
        if current:out.append(current)
    return out

def neighbors(chars,group):
    ids={id(c) for c in group};c=group[0]
    row=[x for x in chars if id(x) not in ids and x['text'].strip() and abs(x['bottom']-c['bottom'])<1.5]
    left=[x for x in row if x['x1']<=c['x0']+.1]
    right=[x for x in row if x['x0']>=group[-1]['x1']-.1]
    return max(left,key=lambda x:x['x1'],default=None),min(right,key=lambda x:x['x0'],default=None)

def label_candidates(k,n,lo,hi,old):
    d=load(k,n)
    cs=[c for c in d['chars'] if 80<c['x0']<550 and lo-.5<=c['top']<hi]
    result=[]
    for group in runs(cs):
        text=''.join(c['text'] for c in group)
        if not re.fullmatch(str(old)+r'-\d+(?:-\d+)*',text):continue
        before,after=neighbors(cs,group)
        lead=group[0]['x0']<122 and (before is None or before['text'] in ['（','('])
        # Source bold runs are question labels and explicit cross-references.
        bold=any('Bold' in c['fontname'] or re.search(r'\+F(?:7|6)$',c['fontname']) for c in group)
        if not(lead or bold):continue
        if before and before['text'] in ',，' and before['x1']>group[0]['x0']-1:continue
        result.append((group,text,lead))
    return result,cs

def make_patch(k,n,group,newtext,qid,lead=False,font=None):
    d=load(k,n);old=''.join(c['text'] for c in group)
    oldbox=[min(c['x0'] for c in group),min(c['top'] for c in group),max(c['x1'] for c in group),max(c['bottom'] for c in group)]
    c=next((c for c in group if c['text'].isdigit()),group[0]);size=c['size']
    font=font or ('LabelBold' if re.search(r'\+F(?:7|6)$',c['fontname']) or 'Bold' in c['fontname'] else 'LabelRegular')
    width=pdfmetrics.stringWidth(newtext,font,size)
    before,after=neighbors(d['chars'],group)
    limit=max(65,(before['x1']+.8) if before else 65)
    # Keep answer panel borders and all neighboring text intact.
    for shape in d['shapes']:
        if shape['width']<1.5 and shape['height']>12 and shape['x1']<oldbox[0] and shape['top']<oldbox[3] and shape['bottom']>oldbox[1]:
            limit=max(limit,shape['x1']+.8)
    right_limit=max(oldbox[2],after['x0']-.8) if after else 514
    for shape in d['shapes']:
        if shape['top']<oldbox[3] and shape['bottom']>oldbox[1] and shape['x0']>=oldbox[2]+.1:
            right_limit=min(right_limit,shape['x0']-.8)
    left_space=max(0,oldbox[0]-limit);right_space=max(0,right_limit-oldbox[2]);oldwidth=oldbox[2]-oldbox[0]
    if width<=oldwidth+right_space:actual=width;x=oldbox[0]
    elif width<=oldwidth+left_space:actual=width;x=oldbox[2]-width
    else:
        actual=min(width,oldwidth+left_space+right_space)
        x=oldbox[0]-min(left_space,max(0,actual-oldwidth-right_space))
    descent=-.216 if font=='LabelBold' else -.211
    if font=='LabelSong':descent=-.14
    baseline=d['height']-c['bottom']-size*descent
    return {'id':qid,'old':old,'new':newtext,'box':oldbox,'drawBox':[x,oldbox[1],x+actual,oldbox[3]],'font':font,'size':size,'baseline':baseline,'x':x,'horizontalScale':actual/width,'color':c['non_stroking_color']}

def heading_candidates(k,n,lo,hi,old):
    d=load(k,n);cs=[c for c in d['chars'] if 80<c['x0']<550 and lo-.5<=c['top']<hi and c['text'].strip()]
    out=[]
    for c in cs:
        if c['text']!='第':continue
        row=sorted([x for x in cs if x['x0']>=c['x0'] and abs(x['bottom']-c['bottom'])<1.5],key=lambda x:x['x0'])
        text=''.join(x['text'] for x in row);m=re.match(r'第'+str(old)+r'题',text)
        if m:out.append(row[:len(m.group())])
    return out

PATCHES=defaultdict(list);COUNTS=defaultdict(int);LABELS=defaultdict(set)
for paper,specs in sorted(SPECS.items()):
    for spec in specs:
        for k in ['q','a']:
            for n,lo,hi in spec['question' if k=='q' else 'answer']:
                detected,_=label_candidates(k,n,lo,hi,spec['number'])
                LABELS[paper].update(text for _,text,_ in detected)
for paper,specs in sorted(SPECS.items()):
    for spec in specs:
        qid=f'chemy{EDITION}-{paper}-{spec["number"]}';q=QUESTIONS[qid];old=spec['number'];new=NUMBER[qid]
        for k in ['q','a']:
            for n,lo,hi in spec['question' if k=='q' else 'answer']:
                labels,cs=label_candidates(k,n,lo,hi,old)
                COUNTS[qid]+=len(labels)
                seen={tuple(id(c) for c in group) for group,_,_ in labels}
                # Non-bold question references and multi-column labels use the same map.
                for group in runs(cs):
                    text=''.join(c['text'] for c in group)
                    if text not in LABELS[paper] or tuple(id(c) for c in group) in seen:continue
                    source_number=int(text.split('-')[0])
                    if source_number!=old and (qid,text) not in CROSS_REFERENCES and (qid,k,text) not in LABEL_CORRECTIONS:continue
                    before,after=neighbors(cs,group)
                    if before and before['text'] in ',，' and before['x1']>group[0]['x0']-1:continue
                    if after and (after['text']=='.' or after['text'].isascii() and after['text'].isalpha()) and after['x0']<group[-1]['x1']+.3:continue
                    labels.append((group,text,False))
                for group,text,lead in labels:
                    text=LABEL_CORRECTIONS.get((qid,k,text),text)
                    source_number=int(text.split('-')[0]);target_id=CROSS_REFERENCES.get((qid,text),qid)
                    replacement=str(NUMBER.get(target_id,new))+text[len(str(source_number)):]
                    original_text=''.join(c['text'] for c in group)
                    if replacement!=original_text:PATCHES[k,n].append(make_patch(k,n,group,replacement,qid,lead))
                if new!=old:
                    for group in heading_candidates(k,n,lo,hi,old):
                        PATCHES[k,n].append(make_patch(k,n,group,f'第{new}题',qid,True,'LabelSong'))

def patch_page(k,n):
    path=OUT/f'{k}-{n:03}.pdf';patches=PATCHES[k,n];render_page(k,n)
    signature=hashlib.sha256(('label-v2'+json.dumps(patches,sort_keys=True)).encode()).hexdigest();stamp=path.with_suffix('.sha256')
    if path.exists() and stamp.exists() and stamp.read_text()==signature:return path
    source=CACHE/k/f'{n:03}-clean.pdf';reader=PdfReader(source);p=copy.copy(reader.pages[0]);d=load(k,n);h=d['height'];w=d['width']
    if patches:
        # Even-odd clipping removes only the appearance of old label glyphs.
        holes=[]
        for patch in patches:
            x0,y0,x1,y1=patch['box'];holes.append(f'{x0-.06:.5f} {h-y1-.12:.5f} {x1-x0+.12:.5f} {y1-y0+.24:.5f} re\n')
        stream=DecodedStreamObject();stream.set_data(('q\n'+f'0 0 {w} {h} re\n'+''.join(holes)+'W* n\n').encode()+p.get_contents().get_data()+b'\nQ\n');p[NameObject('/Contents')]=stream
        buf=BytesIO();c=canvas.Canvas(buf,pagesize=(w,h))
        for patch in patches:
            c.saveState();color=patch['color'];c.setFillColorRGB(*color[:3]) if isinstance(color,list) else c.setFillGray(color or 0)
            c.translate(patch['x'],patch['baseline']);c.scale(patch['horizontalScale'],1);c.setFont(patch['font'],patch['size']);c.drawString(0,0,patch['new']);c.restoreState()
        c.save();p.merge_page(PdfReader(buf).pages[0])
    writer=PdfWriter();writer.add_page(p);temporary=path.with_suffix('.writing.pdf');writer.write(temporary);os.replace(temporary,path);stamp.write_text(signature);return path

def text_html(html,old,new,paper,kind):
    chunks=re.split(r'(<[^>]+>)',html);tags=[]
    for i,part in enumerate(chunks):
        if part.startswith('<'):
            m=re.match(r'</?(\w+)',part)
            if m:
                t=m.group(1)
                if part.startswith('</'):
                    if t in tags:tags=tags[:len(tags)-1-tags[::-1].index(t)]
                elif t not in ['img','br','hr','input']:tags.append(t)
            continue
        # Label tags cover source headings and explicit source cross-references.
        explicit=any(t in ['strong','h3','h4'] for t in tags) or (i and re.search(r'class="number"',chunks[i-1]))
        def replace_label(m):
            text=m.group();qid=f'chemy{EDITION}-{paper}-{old}';text=LABEL_CORRECTIONS.get((qid,kind,text),text)
            source=int(text.split('-')[0]);target=CROSS_REFERENCES.get((qid,text),qid)
            if source!=old and (qid,text) not in CROSS_REFERENCES:return m.group()
            if text not in LABELS[paper] and not(explicit and source==old):return text
            return str(NUMBER.get(target,new))+text[len(str(source)):]
        # Decimal subtraction and chemical locants never match this complete-token rule.
        if '原答案册将本问编号' not in part:
            part=re.sub(r'(?<![\dA-Za-z,，])(\d+)-(\d+(?:-\d+)*)(?![\d.])',replace_label,part)
        part=re.sub(r'第\s*'+str(old)+r'\s*题',f'第 {new} 题',part)
        chunks[i]=part
    return renumber_attributes(''.join(chunks),old,new)

def main():
    plan={'edition':EDITION,'questions':len([q for q in BANK if q.get('edition',39)==EDITION]),'patches':{f'{k}-{n}':v for (k,n),v in PATCHES.items()},'labelsDetected':dict(COUNTS)}
    (OUT/'labels.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf8')
    print('PLAN',EDITION,plan['questions'],'questions',sum(map(len,PATCHES.values())),'label patches',len(PATCHES),'pages',flush=True)
    if _args.plan_only:return
    display={};assets=[];done=0
    for paper,specs in sorted(SPECS.items()):
        for spec in specs:
            qid=f'chemy{EDITION}-{paper}-{spec["number"]}';q=QUESTIONS[qid];new=NUMBER[qid]
            entry={name:text_html(q[name],q['number'],new,paper,'q' if name=='body' else 'a') for name in ['body','answer']}
            for k in ['q','a']:
                field='body' if k=='q' else 'answer'
                for figure in spec['figures'][k]:
                    n=figure['page'];box=figure['box'];selected=[p for p in PATCHES[k,n] if p['id']==qid and p['box'][0]>=box[0]-.1 and p['box'][2]<=box[2]+.1 and p['box'][1]<box[3] and p['box'][3]>box[1]]
                    if not selected:continue
                    pdf=patch_page(k,n)
                    original=Image.open(render_page(k,n)).convert('RGB');sc=original.width/load(k,n)['width']
                    newbox=[min([box[0]]+[p['drawBox'][0]-.5 for p in selected]),box[1],max([box[2]]+[p['drawBox'][2]+.5 for p in selected]),box[3]]
                    pxbox=tuple(round(v*sc) for v in newbox);crop=original.crop(pxbox)
                    # Rasterize only the number regions; chemistry pixels always come from the original crop.
                    roi=(max(0,int(min(min(p['box'][0],p['drawBox'][0])-.6 for p in selected)*sc)),max(0,int(min(p['box'][1]-.7 for p in selected)*sc)),min(original.width,int(max(max(p['box'][2],p['drawBox'][2])+.6 for p in selected)*sc)+2),min(original.height,int(max(p['box'][3]+.7 for p in selected)*sc)+2))
                    sig=hashlib.sha256((pdf.with_suffix('.sha256').read_text()+str(roi)).encode()).hexdigest()
                    png=OUT/f'roi-{sig[:20]}.png'
                    if not png.exists():
                        subprocess.run(['pdftoppm','-singlefile','-r','252','-x',str(roi[0]),'-y',str(roi[1]),'-W',str(roi[2]-roi[0]),'-H',str(roi[3]-roi[1]),'-png',str(pdf),str(png.with_suffix(''))],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                    changed=Image.open(png).convert('RGB')
                    masks=[]
                    # Reuse original pixels everywhere except the actual label glyph box.
                    for p in selected:
                        x0=min(p['box'][0],p['drawBox'][0])-.4;y0=p['box'][1]-.5;x1=max(p['box'][2],p['drawBox'][2])+.4;y1=p['box'][3]+.5
                        rect=(max(0,round(x0*sc)-pxbox[0]),max(0,round(y0*sc)-pxbox[1]),min(crop.width,round(x1*sc)-pxbox[0]),min(crop.height,round(y1*sc)-pxbox[1]))
                        src_rect=(rect[0]+pxbox[0]-roi[0],rect[1]+pxbox[1]-roi[1],rect[2]+pxbox[0]-roi[0],rect[3]+pxbox[1]-roi[1])
                        crop.paste(changed.crop(src_rect),rect[:2]);masks.append(list(rect))
                    buf=BytesIO();crop.save(buf,format='WEBP',lossless=True,method=4);raw=buf.getvalue();sha=hashlib.sha256(raw).hexdigest();name=f'numbered-{qid}-{k}-{len(assets):04}-{sha[:12]}.webp';(ROOT/'dist/assets'/name).write_bytes(raw)
                    entry[field]=entry[field].replace('assets/'+figure['asset'],'assets/'+name)
                    # The wider label hangs in the margin; keep source graphics at their original scale.
                    if newbox[0]<box[0] or newbox[2]>box[2]:
                        pat=r'<figure\b[^>]*>.*?'+re.escape('assets/'+name)+r'.*?</figure>'
                        def resize(m):
                            s=m.group();s=re.sub(r'width="\d+"',f'width="{crop.width}"',s)
                            s=re.sub(r'--(figure|source)-width:\d+px',lambda x:f'--{x.group(1)}-width:{round((newbox[2]-newbox[0])*1.7)}px',s)
                            return s
                        entry[field]=re.sub(pat,resize,entry[field])
                    assets.append({'id':qid,'kind':k,'page':n,'originalAsset':figure['asset'],'asset':name,'sourceBox':box,'displayBox':newbox,'masks':masks,'sha256':sha,'labels':[{'old':p['old'],'new':p['new']} for p in selected]})
                    changed.close();original.close();done+=1
            display[qid]=entry
        print('DISPLAY',EDITION,paper,'processed',done,'numbered captures',flush=True)
    (OUT/'presentation.json').write_text(json.dumps(display,ensure_ascii=False,separators=(',',':')),encoding='utf8')
    (ROOT/'data'/f'numbering-assets-{EDITION}.json').write_text(json.dumps(assets,ensure_ascii=False,indent=2),encoding='utf8')
    # Materialize vector source pages for the print builder, including pages without website captures.
    # Print templates clip source labels once; only website crops need a rendered replacement page.
    print('READY',EDITION,len(display),len(assets),flush=True)

if __name__=='__main__':main()
