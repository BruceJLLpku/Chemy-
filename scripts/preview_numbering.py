"""Render one final page from each booklet plus the longest topic number."""
import json,subprocess
from concurrent.futures import ThreadPoolExecutor
from PIL import Image,ImageDraw,ImageFont
from paper1_manifest import ROOT,SLUGS
OUT=ROOT/'tmp/numbering-review';OUT.mkdir(exist_ok=True)
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',16)

def render(job):
    slug,kind,page,name=job;target=OUT/name
    subprocess.run(['pdftoppm','-f',str(page),'-l',str(page),'-singlefile','-r','110','-png',str(ROOT/'dist/downloads'/f'{slug}-{kind}.pdf'),str(target)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return target.with_suffix('.png')

if __name__=='__main__':
    jobs=[(slug,kind,1,f'{slug}-{kind}-first') for slug in SLUGS.values() for kind in ['questions','answers']]
    index=json.loads((ROOT/'data/print_index.json').read_text(encoding='utf8'))
    jobs.extend(('organic',kind,index[f'organic-{kind}'][-1]['firstPage'],f'organic-{kind}-last') for kind in ['questions','answers'])
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(render,jobs))
    slugs=list(SLUGS.values())
    for group in range(3):
        sheet=Image.new('RGB',(1800,1770),'#edf0ee')
        for col,slug in enumerate(slugs[group*3:(group+1)*3]):
            for row,kind in enumerate(['questions','answers']):
                with Image.open(OUT/f'{slug}-{kind}-first.png') as source:
                    source.thumbnail((600,850));sheet.paste(source,(col*600,row*885+30))
                ImageDraw.Draw(sheet).text((col*600+8,row*885+6),slug+' / '+kind,font=font,fill='#182c24')
        sheet.save(OUT/f'book-samples-{group+1}.png')
    print('Rendered 18 booklet pages and 2 pages with the last topic question',flush=True)
