"""Stream-verify all publicly downloadable final booklets against local bytes."""
import argparse,hashlib,json,time,urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
BASE='https://brucejllpku.github.io/Chemy-/'

def check(item):
    path,sha=item
    expected=hashlib.sha256(path.read_bytes()).hexdigest()
    for attempt in range(4):
        try:
            digest=hashlib.sha256();count=0
            req=urllib.request.Request(BASE+'downloads/'+path.name+'?commit='+sha,headers={'Cache-Control':'no-cache'})
            with urllib.request.urlopen(req,timeout=90) as response:
                while True:
                    chunk=response.read(1024*1024)
                    if not chunk:break
                    digest.update(chunk);count+=len(chunk)
            assert digest.hexdigest()==expected and count==path.stat().st_size,path.name
            print('PUBLIC PDF',path.name,'verified',flush=True)
            return path.name,{'sha256':expected,'bytes':count}
        except Exception:
            if attempt==3:raise
            time.sleep(5)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('sha');args=ap.parse_args()
    paths=sorted((ROOT/'dist/downloads').glob('*.pdf'));assert len(paths)==18
    with ThreadPoolExecutor(max_workers=3) as pool:books=dict(pool.map(check,[(p,args.sha) for p in paths]))
    report={'passed':True,'publicationCommit':args.sha,'url':BASE,'books':books}
    (ROOT/'data/public-pdf-verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('PUBLIC DOWNLOADS',len(books),'byte-identical',flush=True)
