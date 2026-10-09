"""Read-only final samples: later editions, league transitions, and official errata."""
import json,subprocess
from concurrent.futures import ThreadPoolExecutor
from PIL import Image,ImageDraw,ImageFont
from paper1_manifest import ROOT,SLUGS
OUT=ROOT/'tmp/final-review';OUT.mkdir(exist_ok=True)
font=ImageFont.truetype('C:/Windows/Fonts/arial.ttf',16)
bank=json.loads((ROOT/'dist/questions.json').read_text(encoding='utf8'))
index=json.loads((ROOT/'data/print_index.json').read_text(encoding='utf8'))
byid={q['id']:q for q in bank}
selected=[]
for e in [38,37,36,35,34,33,32,0]:
    qs=[q for q in bank if q.get('edition',39)==e]
    selected.extend([qs[0]['id'],qs[-1]['id']])
selected.extend('chemy32-'+key for key in json.loads((ROOT/'data/answer_corrections32.json').read_text(encoding='utf8'))['corrections'])
selected.append('chemy33-13-1')
jobs=[]
for qid in dict.fromkeys(selected):
    q=byid[qid];slug=SLUGS[q['topic']]
    for kind in ['questions','answers']:
        entry=next(x for x in index[f'{slug}-{kind}'] if x['id']==qid)
        jobs.append((slug,kind,entry['firstPage'],qid+'-'+kind))
        if q.get('answerCorrectionPages') and kind=='answers' and entry['lastPage']!=entry['firstPage']:
            jobs.append((slug,kind,entry['lastPage'],qid+'-'+kind+'-last'))
def render(job):
    slug,kind,page,name=job
    subprocess.run(['pdftoppm','-f',str(page),'-l',str(page),'-singlefile','-r','100','-png',str(ROOT/'dist/downloads'/f'{slug}-{kind}.pdf'),str(OUT/name)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    return name
def sheet(names,target):
    canvas=Image.new('RGB',(1800,900),'#edf0ee');draw=ImageDraw.Draw(canvas)
    for col,name in enumerate(names):
        draw.text((col*600+8,6),name,font=font,fill='#182c24')
        path=OUT/(name+'.png')
        with Image.open(path) as im:
            im.thumbnail((600,850));canvas.paste(im,(col*600,30))
    canvas.save(target)
if __name__=='__main__':
    with ThreadPoolExecutor(max_workers=4) as p:names=list(p.map(render,jobs))
    for i in range(0,len(names),3):sheet(names[i:i+3],OUT/f'samples-{i//3+1:02}.png')
    for n in range(113,119):
        with Image.open(ROOT/'tmp/library32/a'/f'{n:03}-clean.png') as im:im.save(OUT/f'errata-{n-112}.png')
    for i in [0,3]:sheet([f'errata-{n}' for n in range(i+1,i+4)],OUT/f'errata-sheet-{i//3+1}.png')
    print('FINAL SAMPLE PAGES',len(jobs),flush=True)
