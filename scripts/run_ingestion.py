"""Sequential paper ingestion, publication and resumable compact progress."""
import argparse,json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
STATE=ROOT/'data/import_progress.json'
def run(script,args,e):
    env=os.environ.copy();env['CHEMY_EDITION']=str(e)
    with (ROOT/'tmp/ingestion.log').open('a',encoding='utf8') as log:
        process=subprocess.Popen([sys.executable,'-X','utf8',str(ROOT/'scripts'/script),*map(str,args)],cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,encoding='utf8',bufsize=1)
        tail=[];sha=None
        for line in process.stdout:
            log.write(line);log.flush();tail=(tail+[line])[-24:]
            if line.startswith(('Imported','PUBLISHED','PUSH','DEPLOY','RESOURCE CHECK','WEBSITE','TOTAL')):print(e,line.strip(),flush=True)
            if line.startswith('PUBLISHED'):sha=line.split()[-1]
        if process.wait():raise RuntimeError(''.join(tail))
        return sha
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--first-built',action='store_true');ap.add_argument('--editions',nargs='+',type=int,default=[38,37]);args=ap.parse_args()
    state=json.loads(STATE.read_text(encoding='utf8')) if STATE.exists() else {'completed':[]}
    completed={(x['edition'],x['paper']) for x in state['completed']}
    for e in args.editions:
        plan=json.loads((ROOT/f'data/import_plan{e}.json').read_text(encoding='utf8'))
        total=len(plan['papers']) if 'papers' in plan else len(plan)
        for paper in range(1,total+1):
            if (e,paper) in completed:continue
            started=time.monotonic();print('START',e,paper,flush=True)
            if not(args.first_built and (e,paper)==(38,1)):
                run('import_library.py',[paper],e);run('rebuild_numbering.py',[],e)
            else:run('rebuild_numbering.py',['--presentation-only'],e)
            sha=run('publish_library.py',[paper],e)
            state['completed'].append({'edition':e,'paper':paper,'sha':sha,'seconds':round(time.monotonic()-started)})
            STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8')
            print('DONE',e,paper,'seconds',round(time.monotonic()-started),flush=True)
    print('ALL NEW PAPERS PUBLISHED',flush=True)
