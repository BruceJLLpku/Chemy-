"""Run one authorized paper import, cumulative PDF update, and Pages publish."""
import argparse,json,subprocess,sys
from import_library import ROOT,import_paper
from publish_library import publish
from library_config import EDITION

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('paper',type=int);ap.add_argument('--skip-import',action='store_true');args=ap.parse_args()
    plan=json.loads((ROOT/'data'/('import_plan.json' if EDITION==39 else f'import_plan{EDITION}.json')).read_text(encoding='utf8'))
    if not args.skip_import:import_paper(args.paper,plan[str(args.paper)])
    subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/rebuild_numbering.py')],cwd=ROOT,check=True)
    publish(args.paper)
