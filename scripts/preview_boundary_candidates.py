"""Annotated diagnostic views only; never alters website or original assets."""
import json
from collections import defaultdict
from PIL import Image,ImageDraw,ImageFont
from paper1_manifest import ROOT
OUT=ROOT/'tmp/boundary-review';OUT.mkdir(exist_ok=True)
candidates=json.loads((ROOT/'tmp/audit-source-preliminary.json').read_text(encoding='utf8'))['reviewCandidates']
manifest=json.loads((ROOT/'data/library_manifest.json').read_text(encoding='utf8'))['papers']
groups=defaultdict(list)
for c in candidates:groups[c['edition'],c['paper'],c['kind'],c['page']].append(c)
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',17)
names=[]
for (e,p,k,n),cs in groups.items():
    cache=ROOT/'tmp'/('library' if e==39 else f'library{e}')/k
    data=json.loads((cache/f'{n:03}.json').read_text(encoding='utf8'))
    key=str(p) if e==39 else f'{e}-{p}'
    rs=[(q['number'],r) for q in manifest[key]['questions'] for r in q['question' if k=='q' else 'answer'] if r[0]==n]
    top=max(0,min(c['box'][1] for c in cs)-65);bottom=min(data['height'],max(c['box'][3] for c in cs)+65)
    with Image.open(cache/f'{n:03}-clean.png') as im:
        sc=im.width/data['width'];tile=im.convert('RGB').crop(tuple(round(v*sc) for v in [75,top,550,bottom]))
    draw=ImageDraw.Draw(tile)
    for number,(_,lo,hi) in rs:
        for y,label in [(lo,f'{number} start'),(hi,f'{number} end')]:
            if top<y<bottom:
                yy=round((y-top)*sc);draw.line((0,yy,tile.width,yy),fill='#2b80e7',width=3);draw.text((8,yy+3),label,font=font,fill='#2b80e7')
    for c in cs:
        x0,y0,x1,y1=c['box'];draw.rectangle(tuple(round(v*sc) for v in [x0-75,y0-top,x1-75,y1-top]),outline='#ef3333',width=3)
    name=f'e{e}-p{p}-{k}{n}';tile.thumbnail((600,800));canvas=Image.new('RGB',(600,850),'white');canvas.paste(tile,(0,30));ImageDraw.Draw(canvas).text((8,6),name,font=font,fill='#182c24');canvas.save(OUT/(name+'.png'));names.append(name)
for i in range(0,len(names),3):
    sheet=Image.new('RGB',(1800,850),'#edf0ee')
    for col,name in enumerate(names[i:i+3]):
        with Image.open(OUT/(name+'.png')) as im:sheet.paste(im,(col*600,0))
    sheet.save(OUT/f'candidates-{i//3+1:02}.png')
print('BOUNDARY VIEWS',len(names),flush=True)
