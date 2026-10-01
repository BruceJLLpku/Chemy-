"""Render source-edition transitions for final print-layout review, outside public assets."""
import argparse,json,subprocess
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont
from pypdf import PdfReader
from paper1_manifest import ROOT,SLUGS
from audit_library import part

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--topics',nargs='*');args=ap.parse_args()
    bank=json.loads((ROOT/'dist/questions.json').read_text(encoding='utf8'));out=ROOT/'tmp/final-review';out.mkdir(exist_ok=True)
    font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',17)
    for topic,slug in SLUGS.items():
        if args.topics and slug not in args.topics:continue
        chapters=sorted({(q.get('edition',39),q['paper']) for q in bank if q['topic']==topic},key=lambda pair:(-pair[0],pair[1]))
        for k,kind in [('q','questions'),('a','answers')]:
            offset=0;first={}
            for e,p in chapters:
                first.setdefault(e,(offset+1,p));offset+=len(PdfReader(part(e,p,slug,k)).pages)
            selections=[(e,*first[e]) for e in (36,35) if e in first];panels=[]
            for e,page,p in selections:
                path=out/f'{slug}-{k}-e{e}'
                subprocess.run(['pdftoppm','-f',str(page),'-l',str(page),'-singlefile','-r','110','-png',str(ROOT/'dist/downloads'/f'{slug}-{kind}.pdf'),str(path)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                with Image.open(path.with_suffix('.png')) as source:
                    source.thumbnail((800,1160));panel=Image.new('RGB',(800,source.height+32),'#edf0ee');panel.paste(source,((800-source.width)//2,32));ImageDraw.Draw(panel).text((12,6),f'{slug} / {kind} / edition {e}, paper {p}, book page {page}',font=font,fill='#182c24');panels.append(panel)
            sheet=Image.new('RGB',(sum(p.width for p in panels),max(p.height for p in panels)),'#edf0ee');x=0
            for panel in panels:sheet.paste(panel,(x,0));x+=panel.width
            sheet.save(out/f'{slug}-{k}-contact.png');print(slug,k,'rendered',flush=True)
