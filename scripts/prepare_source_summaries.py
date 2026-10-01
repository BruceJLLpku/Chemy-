"""Small classification excerpts from cached source geometry, without image review."""
import argparse,json,re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
ap=argparse.ArgumentParser();ap.add_argument('edition',type=int);ap.add_argument('--show',action='store_true');args=ap.parse_args()
base=ROOT/f'tmp/library{args.edition}/q';ix=json.loads((base/'index.json').read_text(encoding='utf8'));pages={};out={}
for i,h in enumerate(ix['questions']):
    end=ix['questions'][i+1] if i+1<len(ix['questions']) and ix['questions'][i+1]['paper']==h['paper'] else {'page':int(ix['papers'].get(str(h['paper']+1),len(ix['pages'])+1)),'top':70}
    lines=[]
    for n in range(h['page'],min(end['page'],len(ix['pages']))+1):
        if n not in pages:pages[n]=json.loads((base/f'{n:03}.json').read_text(encoding='utf8'))
        lo=h['bottom'] if n==h['page'] else 70;hi=end['top'] if n==end['page'] else min(770,pages[n]['height']-70)
        lines += [x['text'] for x in pages[n]['rows'] if lo<x['top']<hi]
    key=f'{h["paper"]}-{h["number"]}';out[key]={'title':h['title'],'text':' '.join(lines),'prompts':[x for x in lines if re.match(r'^\d+-\d',x)]}
    if args.show:print(key,(out[key]['title']+' '+out[key]['text']).strip()[:44],'/','|'.join(p[:20] for p in out[key]['prompts'][-1:]))
(ROOT/f'tmp/classification-{args.edition}.json').write_text(json.dumps(out,ensure_ascii=False),encoding='utf8')
