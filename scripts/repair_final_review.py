"""Replay only final-review exceptions, then merge print books once."""
import json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(path):return json.loads(path.read_text(encoding='utf8'))
report=read(ROOT/'data/audit_report.json');exceptions=read(ROOT/'data/source_exceptions.json')
affected={(item['edition'],item['paper']) for item in report['issues'] if item['code']=='unsupported_native_glyph'}
affected.update((item['edition'],item['paper']) for item in exceptions['captures'])
affected.add((39,22))
cache=ROOT/'tmp/library35/q';index=read(cache/'index.json');hashes=set(exceptions['backgroundHashes'])
for path in sorted(cache.glob('[0-9][0-9][0-9].json')):
    data=read(path)
    if not any(im['hash'] in hashes for im in data['images']):continue
    n=data['page'];h=max((h for h in index['questions'] if h['page']<=n),key=lambda h:(h['page'],h['top']))
    affected.add((35,h['paper']))
    for suffix in ('-clean.pdf','-clean.png'):
        target=cache/f'{n:03}{suffix}'
        assert target.resolve().is_relative_to(ROOT/'tmp')
        target.unlink(missing_ok=True)
print('REPAIR PAPERS',sorted(affected,reverse=True),flush=True)
for e,p in sorted(affected,key=lambda pair:(-pair[0],pair[1])):
    env=os.environ.copy();env['CHEMY_EDITION']=str(e)
    for script,args in [('import_library.py',[str(p)]),('build_library_pdfs.py',[str(p),'--parts-only'])]:
        subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts'/script),*args],cwd=ROOT,env=env,check=True)
    print('REPAIRED',e,p,flush=True)
subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/build_library_pdfs.py'),'--merge-only'],cwd=ROOT,check=True)
print('ALL REPAIRS COMPLETE',flush=True)
