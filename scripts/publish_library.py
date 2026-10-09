"""Authorized per-paper GitHub Pages publish; credentials stay in process memory."""
import argparse,hashlib,json,os,subprocess,time,urllib.request
from pathlib import Path
from datetime import datetime,timezone
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor
from PIL import Image
from paper1_manifest import ROOT
from library_config import EDITION,edition_of

GIT='C:/Users/Prettibruce/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe'
REPO='BruceJLLpku/Chemy-';BASE='https://brucejllpku.github.io/Chemy-/'
env=os.environ.copy();env.update(GCM_INTERACTIVE='never',GIT_TERMINAL_PROMPT='0',GIT_CONFIG_COUNT='3',GIT_CONFIG_KEY_0='safe.directory',GIT_CONFIG_VALUE_0=ROOT.as_posix(),GIT_CONFIG_KEY_1='gc.auto',GIT_CONFIG_VALUE_1='0',GIT_CONFIG_KEY_2='maintenance.auto',GIT_CONFIG_VALUE_2='false')
# Use the same configured system proxy as the publication API requests.
proxy=urllib.request.getproxies().get('https')
if proxy:
    env.update(GIT_CONFIG_COUNT='4',GIT_CONFIG_KEY_3='http.proxy',GIT_CONFIG_VALUE_3=proxy if '://' in proxy else 'http://'+proxy)
def git(*args):
    return subprocess.run([GIT,*args],cwd=ROOT,env=env,text=True,capture_output=True,check=True,encoding='utf8').stdout.strip()

def committed(path,revision='HEAD'):
    return subprocess.run([GIT,'show',revision+':'+path],cwd=ROOT,env=env,capture_output=True,check=True).stdout

def committed_assets(paths,revision):
    ordered=sorted(paths)
    requests=''.join(revision+':dist/'+path+'\n' for path in ordered).encode('utf8')
    raw=subprocess.run([GIT,'cat-file','--batch'],input=requests,cwd=ROOT,env=env,capture_output=True,check=True).stdout
    result={};offset=0
    for path in ordered:
        end=raw.index(b'\n',offset);header=raw[offset:end].rsplit(b' ',2)
        assert header[-2]==b'blob',path
        size=int(header[-1]);offset=end+1;result[path]=raw[offset:offset+size];offset+=size+1
    return result
def api(path,headers):
    with urllib.request.urlopen(urllib.request.Request('https://api.github.com/repos/'+REPO+path,headers=headers),timeout=45) as r:return json.load(r)
def publish(paper,verify_only=False,check_all=False,message=None,prepare_only=False,push_existing=False,numbered_only=False):
    while (ROOT/'tmp/pause-publishing').exists():time.sleep(2)
    assert not(prepare_only and (verify_only or push_existing))
    if push_existing:verify_only=True
    bank=json.loads(committed('dist/questions.json')) if verify_only else json.loads((ROOT/'dist/questions.json').read_text(encoding='utf8'))
    assert verify_only or max(q['paper'] for q in bank if edition_of(q)==EDITION)==paper
    assert len({q['id'] for q in bank})==len(bank)
    # Structural preflight only; visual/content review is deferred until all papers are imported.
    import re
    for q in bank:
        assert q['body'] and q['answer'] and q['pdfReady']
    notes=json.loads(committed('dist/papers.json')) if verify_only else json.loads((ROOT/'dist/papers.json').read_text(encoding='utf8'))
    legacy_notes=json.loads(committed('dist/paper1-notes.json')) if verify_only else json.loads((ROOT/'dist/paper1-notes.json').read_text(encoding='utf8'))
    display=json.loads(committed('dist/presentation.json')) if verify_only else json.loads((ROOT/'dist/presentation.json').read_text(encoding='utf8'))
    numbers=json.loads(committed('dist/numbering.json')) if verify_only else json.loads((ROOT/'dist/numbering.json').read_text(encoding='utf8'))
    assert set(display)=={q['id'] for q in bank}==set(numbers['numberById'])
    all_html=[q['body']+q['answer'] for q in bank]+[d['body']+d['answer'] for d in display.values()]
    for name in {name for html in all_html for name in re.findall(r'(?:src|href)="(assets/[^\"]+)"',html)}:
        path=ROOT/'dist'/name;assert path.is_file(),name
        if path.suffix=='.webp':
            with Image.open(path) as im:im.verify()
    assert all(p.stat().st_size<100*1024*1024 for p in (ROOT/'dist/downloads').glob('*.pdf')),'PDF exceeds repository file-size limit'
    old=json.loads(git('show','HEAD:dist/questions.json'));assert [q for q in bank if edition_of(q)==39 and q['paper']==1]==[q for q in old if edition_of(q)==39 and q['paper']==1]
    if not verify_only:
        readme=ROOT/'README.md';s=readme.read_text(encoding='utf8')
        start=s.index('当前完整收录');end=s.index('网页正文',start)
        counts={e:len({q['paper'] for q in bank if edition_of(q)==e}) for e in sorted({edition_of(q) for q in bank},reverse=True)}
        scope='、'.join(f'第{e}届{n}份' if e else f'Chemy联赛{n}届' for e,n in counts.items())
        audit_path=ROOT/'data/audit_report.json';review=json.loads(audit_path.read_text(encoding='utf8')) if audit_path.exists() else {}
        reviewed=review.get('automatedPassed') and review.get('visualReviewComplete') and review.get('checks',{}).get('source_questions')==len(bank)
        status='已完成全量来源、字形、原图及题答配对检查，并复核边界异常和各专题打印册样页；记录见data/audit_report.json。' if reviewed else '图文与对应关系将在全部录入结束后统一复核。'
        s=s[:start]+f'当前完整收录{scope}试题，共{len(bank)}道完整大题。每道大题只设置一个主专题。九个专题提供累计题目册、答案册，保留原卷字体、结构式、评分和来源。{status}\n\n'+s[end:]
        readme.write_text(s,encoding='utf8')
        # Bound Git's temporary working set and pack existing objects before disk space runs low.
        import shutil
        if shutil.disk_usage(ROOT).free<3*1024**3:
            git('repack','-d','-l','--window=5','--window-memory=192m','--threads=2','--depth=20')
            git('-c','pack.windowMemory=192m','-c','pack.threads=2','multi-pack-index','write')
            git('-c','pack.windowMemory=192m','-c','pack.threads=2','multi-pack-index','repack','--batch-size=1073741824')
            git('multi-pack-index','expire')
            print('STORAGE Git history packed; all commits retained',flush=True)
        git('add','dist','scripts','data','docs','sources','README.md','WORK_STATE.md','.github/workflows/pages.yml')
        git('commit','-m',message or (f'Import Chemy league edition {paper} with cumulative topic PDFs' if EDITION==0 else f'Import Chemy {EDITION} collection {paper} with cumulative topic PDFs'))
    sha=git('rev-parse','HEAD')
    snapshot_names=['index.html','questions.json','app.js','papers.json','numbering.json','presentation.json']
    snapshot={name:subprocess.run([GIT,'show',sha+':dist/'+name],cwd=ROOT,env=env,capture_output=True,check=True).stdout for name in snapshot_names}
    selected_html=all_html if check_all else [display[q['id']]['body']+display[q['id']]['answer'] for q in bank if (edition_of(q),q['paper'])==(EDITION,paper)]
    if not check_all:
        key=str(paper) if EDITION==39 else f'{EDITION}-{paper}'
        n=legacy_notes if key=='1' else notes.get(key,{})
        selected_html.append(str(n.get('instructions',''))+str(n.get('scoring','')))
    asset_paths={name for html in selected_html for name in re.findall(r'src="(assets/[^\"]+)"',html)}
    if numbered_only:
        asset_paths={name for html in all_html for name in re.findall(r'src="(assets/numbered-[^\"]+)"',html)}
    # New immutable image filenames are also verified when later topic numbers shift.
    changed_assets=set(git('diff','--name-only','HEAD^','HEAD','--','dist/assets').splitlines())
    referenced={name for html in all_html for name in re.findall(r'src="(assets/[^\"]+)"',html)}
    asset_paths.update(name for name in referenced if 'dist/'+name in changed_assets)
    tracked=set(git('ls-files','dist/assets').splitlines())
    all_paths={name for html in all_html for name in re.findall(r'src="(assets/[^\"]+)"',html)}
    assert all('dist/'+name in tracked for name in all_paths),'Referenced image missing from Git commit'
    asset_snapshot=committed_assets(asset_paths,sha)
    if prepare_only:
        print('PREPARED',len(bank),'questions',sha,'without network access',flush=True);return sha
    if not verify_only or push_existing:print('PUSH',paper,sha,flush=True);print(git('push','origin','main'),flush=True)
    r=subprocess.run([GIT,'credential','fill'],input='protocol=https\nhost=github.com\npath='+REPO+'.git\n\n',cwd=ROOT,text=True,capture_output=True,env=env,check=True)
    creds=dict(line.split('=',1) for line in r.stdout.splitlines() if '=' in line)
    headers={'Authorization':'Bearer '+creds['password'],'Accept':'application/vnd.github+json','X-GitHub-Api-Version':'2022-11-28'}
    deadline=time.monotonic()+900;last=None
    while time.monotonic()<deadline:
        runs=api('/actions/runs?head_sha='+sha+'&per_page=1',headers)['workflow_runs']
        if runs:
            run=runs[0];status=(run['status'],run['conclusion'])
            if status!=last:print('DEPLOY',paper,*status,flush=True);last=status
            if run['status']=='completed':
                if run['conclusion']!='success':raise RuntimeError('Pages workflow '+str(run['conclusion'])+' '+run['html_url'])
                break
        time.sleep(20)
    else:raise TimeoutError('Pages deploy still pending')
    for filename in snapshot_names:
        local=snapshot[filename];url=BASE+filename+'?commit='+sha
        for attempt in range(12):
            with urllib.request.urlopen(urllib.request.Request(url,headers={'Cache-Control':'no-cache'}),timeout=45) as r:remote=r.read()
            if hashlib.sha256(remote).digest()==hashlib.sha256(local).digest():break
            time.sleep(10)
        else:raise RuntimeError('Published file not current: '+filename)
    def check_asset(item):
        filename,local=item;digest=hashlib.sha256(local).hexdigest()
        for attempt in range(4):
            try:
                req=urllib.request.Request(BASE+filename+'?v='+digest[:12],headers={'Cache-Control':'no-cache'})
                with urllib.request.urlopen(req,timeout=30) as response:remote=response.read()
                if hashlib.sha256(remote).hexdigest()==digest:return
            except Exception:
                if attempt==3:raise
            time.sleep(10)
        raise RuntimeError('Published image mismatch: '+filename)
    with ThreadPoolExecutor(max_workers=4) as pool:list(pool.map(check_asset,asset_snapshot.items()))
    print('RESOURCE CHECK',len(asset_snapshot),'source images available and byte-identical',flush=True)
    print('PUBLISHED',paper,len(json.loads(snapshot['questions.json'])),BASE,sha,flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('paper',type=int);ap.add_argument('--verify-only',action='store_true');ap.add_argument('--prepare-only',action='store_true');ap.add_argument('--push-existing',action='store_true');ap.add_argument('--assets-all',action='store_true');ap.add_argument('--numbered-assets',action='store_true');ap.add_argument('--message');args=ap.parse_args();publish(args.paper,args.verify_only,args.assets_all,args.message,args.prepare_only,args.push_existing,args.numbered_assets)
