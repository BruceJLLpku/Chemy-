"""Sequential papers; each deploy completes before starting the next import."""
import argparse,gc,json
from import_library import ROOT,import_paper
from build_library_pdfs import build
from publish_library import publish
from library_config import EDITION

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--start',type=int,required=True);ap.add_argument('--end',type=int,default=22);ap.add_argument('--local-only',action='store_true');args=ap.parse_args()
    plan=json.loads((ROOT/'data'/('import_plan.json' if EDITION==39 else f'import_plan{EDITION}.json')).read_text(encoding='utf8'))
    for paper in range(args.start,args.end+1):
        print('START',paper,flush=True)
        import_paper(paper,plan[str(paper)]);build(paper)
        if args.local_only:print('LOCAL COMPLETE',paper,flush=True)
        else:publish(paper)
        gc.collect()
