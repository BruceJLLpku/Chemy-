"""Run one authorized paper import, cumulative PDF update, and Pages publish."""
import argparse,json
from import_library import ROOT,import_paper
from build_library_pdfs import build
from publish_library import publish

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('paper',type=int);ap.add_argument('--skip-import',action='store_true');args=ap.parse_args()
    plan=json.loads((ROOT/'data/import_plan.json').read_text(encoding='utf8'))
    if not args.skip_import:import_paper(args.paper,plan[str(args.paper)])
    build(args.paper);publish(args.paper)
