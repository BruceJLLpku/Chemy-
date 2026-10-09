"""Rebuild repaired print caches, publish the pending paper, then continue ingestion."""
import json,subprocess,sys,time
from run_ingestion import ROOT,STATE,run

if __name__=='__main__':
    e,paper=32,2;started=time.monotonic()
    print('RECOVERY rebuild native print chapters',flush=True)
    run('rebuild_numbering.py',[],e)
    run('validate_print_structure.py',[],e)
    print('RECOVERY all 18 print books have valid PDF streams; full source review remains deferred',flush=True)
    pause=ROOT/'tmp/pause-publishing'
    if pause.exists():pause.unlink()
    state=json.loads(STATE.read_text(encoding='utf8'))
    if not any((item['edition'],item['paper'])==(e,paper) for item in state['completed']):
        sha=run('publish_library.py',[paper],e)
        state['completed'].append({'edition':e,'paper':paper,'sha':sha,'seconds':round(time.monotonic()-started),'printRecovery':True})
        STATE.write_text(json.dumps(state,ensure_ascii=False,indent=2),encoding='utf8')
    print('RECOVERY pending paper published; continuing edition 32 and league',flush=True)
    subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/run_ingestion.py'),'--editions','32','0'],cwd=ROOT,check=True)
