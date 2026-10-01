"""Authorized per-paper GitHub Pages publish; credentials stay in process memory."""
import argparse,hashlib,json,os,subprocess,time,urllib.request
from pathlib import Path
from datetime import datetime,timezone
from paper1_manifest import ROOT

GIT='C:/Users/Prettibruce/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe'
REPO='BruceJLLpku/Chemy-';BASE='https://brucejllpku.github.io/Chemy-/'
env=os.environ.copy();env.update(GCM_INTERACTIVE='never',GIT_TERMINAL_PROMPT='0',GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='safe.directory',GIT_CONFIG_VALUE_0=ROOT.as_posix())
def git(*args):
    return subprocess.run([GIT,*args],cwd=ROOT,env=env,text=True,capture_output=True,check=True,encoding='utf8').stdout.strip()
def api(path,headers):
    with urllib.request.urlopen(urllib.request.Request('https://api.github.com/repos/'+REPO+path,headers=headers),timeout=45) as r:return json.load(r)
def publish(paper):
    bank=json.loads((ROOT/'dist/questions.json').read_text(encoding='utf8'))
    assert max(q['paper'] for q in bank)==paper
    assert len({q['id'] for q in bank})==len(bank)
    # Structural preflight only; visual/content review is deferred until all papers are imported.
    import re
    for q in bank:
        assert q['body'] and q['answer'] and q['pdfReady']
        for name in re.findall(r'(?:src|href)="(assets/[^\"]+)"',q['body']+q['answer']):assert (ROOT/'dist'/name).is_file(),name
    old=json.loads(git('show','HEAD:dist/questions.json'));assert [q for q in bank if q['paper']==1]==[q for q in old if q['paper']==1]
    readme=ROOT/'README.md';s=readme.read_text(encoding='utf8')
    start=s.index('当前完整收录');end=s.index('网页正文',start)
    s=s[:start]+f'当前完整收录第39届模拟试题1–{paper}，共{len(bank)}道完整大题。每道大题只设置一个主专题。已有题目的专题提供累计题目册、答案册，保留原卷字体、结构式、评分和来源。图文与对应关系将在全套录入结束后统一复核。\n\n'+s[end:]
    readme.write_text(s,encoding='utf8')
    git('add','dist','scripts','data','docs','README.md')
    git('commit','-m',f'Import Chemy 39 mock paper {paper} with cumulative topic PDFs')
    sha=git('rev-parse','HEAD');print('PUSH',paper,sha,flush=True);print(git('push','origin','main'),flush=True)
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
    for filename in ['questions.json','app.js','papers.json']:
        local=(ROOT/'dist'/filename).read_bytes();url=BASE+filename+'?commit='+sha
        for attempt in range(12):
            with urllib.request.urlopen(urllib.request.Request(url,headers={'Cache-Control':'no-cache'}),timeout=45) as r:remote=r.read()
            if hashlib.sha256(remote).digest()==hashlib.sha256(local).digest():break
            time.sleep(10)
        else:raise RuntimeError('Published file not current: '+filename)
    print('PUBLISHED',paper,len(bank),BASE,sha,flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('paper',type=int);publish(ap.parse_args().paper)
