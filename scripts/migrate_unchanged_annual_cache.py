"""Reuse published annual caches when only newer collection-source support changed."""
import hashlib,json,os,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(p):return json.loads(p.read_text(encoding='utf8'))
bank=read(ROOT/'dist/questions.json');numbers=read(ROOT/'dist/numbering.json')['numberById']
env=os.environ.copy();env.update(GIT_CONFIG_COUNT='1',GIT_CONFIG_KEY_0='safe.directory',GIT_CONFIG_VALUE_0=ROOT.as_posix())
git='C:/Users/Prettibruce/.cache/codex-runtimes/codex-primary-runtime/dependencies/native/git/cmd/git.exe'
published=json.loads(subprocess.run([git,'show','HEAD:dist/questions.json'],cwd=ROOT,env=env,capture_output=True,check=True).stdout)
source=hashlib.sha256(b''.join((ROOT/'scripts'/s).read_bytes() for s in ['renumber_library.py','build_numbered_pdfs.py','import_library.py','display_numbering.py','fast_pdf.py','pdf_form_cache.py','source_info.py'])).hexdigest()
from source_info import source_name
for e in [39,38,37,36,35]:
    items=[q for q in bank if q.get('edition',39)==e]
    assert items==[q for q in published if q.get('edition',39)==e]
    assert all(source_name(e,q['paper'],True)==f'第{e}届模拟试题{q["paper"]}' and q['points'] is not None and not q.get('answerCorrectionPages') for q in items)
    cache=ROOT/'tmp'/('library' if e==39 else f'library{e}')/'numbered'
    assert set(read(cache/'presentation.json'))=={q['id'] for q in items}
    prefix='[0-9][0-9]-' if e==39 else f'e{e}-'
    found=set()
    for p in (ROOT/'tmp/library/books').glob(prefix+'*.json'):
        if any(tag in p.name for tag in ['layout','merge-']):continue
        records=read(p)
        if not isinstance(records,list):continue
        assert p.with_suffix('.pdf').is_file()
        for r in records:assert r['number']==numbers[r['id']];found.add(r['id'])
    assert found=={q['id'] for q in items},e
    signature=hashlib.sha256(json.dumps({'q':items,'n':{q['id']:numbers[q['id']] for q in items},'scripts':source},sort_keys=True).encode()).hexdigest()
    (cache/'edition.sha256').write_text(signature)
    print('CACHE REUSED',e,len(items),'published questions; source content, names and numbers unchanged',flush=True)
