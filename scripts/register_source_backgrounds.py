"""Register only repeated broad pale raster watermarks; never discard black chemistry."""
import argparse,json
from pathlib import Path
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('editions',nargs='+',type=int);args=ap.parse_args()
cfg=json.loads((ROOT/'data/editions.json').read_text(encoding='utf8'));path=ROOT/'data/source_exceptions.json';data=json.loads(path.read_text(encoding='utf8'));known=set(data['backgroundHashes']);evidence=[]
for e in args.editions:
    for k in ['q','a']:
        base=ROOT/f'tmp/library{e}/{k}';ix=json.loads((base/'index.json').read_text(encoding='utf8'));reader=None;seen=set();count=0
        for n in ix['pages']:
            page=json.loads((base/f'{n:03}.json').read_text(encoding='utf8'))
            for im in page['images']:
                digest=im['hash']
                if digest in seen or digest in known or not(im['width']>390 and 89<im['x0']<92 and 180<im['top']<650 and ix['imageFrequency'].get(digest,0)>=5):continue
                seen.add(digest)
                if reader is None:reader=PdfReader(ROOT/'sources'/cfg[str(e)][k])
                image=reader.pages[n-1].images['/'+im['name']].image.convert('RGB');extrema=image.getextrema()
                if min(lo for lo,hi in extrema)>=100:
                    known.add(digest);count+=1;evidence.append({'edition':e,'kind':k,'page':n,'hash':digest,'extrema':extrema,'reason':'Repeated broad pale source watermark; black chemistry content excluded by pixel minimum.'})
                else:print('RETAIN',e,k,n,digest[:12],extrema)
        print('BACKGROUND',e,k,count)
data['backgroundHashes']=sorted(known);data.setdefault('backgroundEvidence',[]).extend(evidence)
path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
