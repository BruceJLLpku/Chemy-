"""Independent edition workers; merge only after every display and print part is ready."""
import argparse,json,subprocess,sys,hashlib,os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from display_numbering import renumber_attributes
ROOT=Path(__file__).resolve().parents[1]

def edition(e):
    bank=json.loads((ROOT/'dist/questions.json').read_text(encoding='utf8'))
    numbers=json.loads((ROOT/'dist/numbering.json').read_text(encoding='utf8'))['numberById']
    items=[q for q in bank if q.get('edition',39)==e]
    cache=ROOT/'tmp'/('library' if e==39 else f'library{e}')/'numbered'
    stamp=cache/'edition.sha256'
    source=hashlib.sha256(b''.join((ROOT/'scripts'/s).read_bytes() for s in ['renumber_library.py','build_numbered_pdfs.py','import_library.py','display_numbering.py','fast_pdf.py','pdf_form_cache.py','source_info.py'])).hexdigest()
    signature=hashlib.sha256(json.dumps({'q':items,'n':{q['id']:numbers[q['id']] for q in items},'scripts':source},sort_keys=True).encode()).hexdigest()
    if stamp.exists() and stamp.read_text()==signature and (cache/'presentation.json').exists():
        return
    for script in ['renumber_library.py','build_numbered_pdfs.py']:
        subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts'/script),'--edition',str(e)],cwd=ROOT,check=True)
    stamp.write_text(signature)
    # Release disposable renders as soon as this edition is done, before other editions finish.
    before=cache.stat()
    for path in cache.iterdir():
        if path.is_file() and path.suffix.lower() in {'.pdf','.png'}:
            assert path.resolve().parent==cache.resolve() and path.resolve().is_relative_to((ROOT/'tmp').resolve())
            path.unlink()
    os.utime(cache,ns=(before.st_atime_ns,before.st_mtime_ns))

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--presentation-only',action='store_true');ap.add_argument('--editions',nargs='+',type=int);args=ap.parse_args()
    bank=json.loads((ROOT/'dist/questions.json').read_text(encoding='utf8'))
    editions=sorted({q.get('edition',39) for q in bank},reverse=True)
    workers=editions if args.editions is None else args.editions
    assert set(workers)<=set(editions)
    if not args.presentation_only:
        with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(edition,workers))
    display={}
    for e in editions:
        cache=ROOT/'tmp'/('library' if e==39 else f'library{e}')/'numbered/presentation.json'
        display.update(json.loads(cache.read_text(encoding='utf8')))
    bank=json.loads((ROOT/'dist/questions.json').read_text(encoding='utf8'));assert set(display)=={q['id'] for q in bank}
    numbers=json.loads((ROOT/'dist/numbering.json').read_text(encoding='utf8'))['numberById']
    for q in bank:
        for field in ['body','answer']:display[q['id']][field]=renumber_attributes(display[q['id']][field],q['number'],numbers[q['id']])
    (ROOT/'dist/presentation.json').write_text(json.dumps(display,ensure_ascii=False,separators=(',',':')),encoding='utf8')
    import re
    active={name for d in display.values() for name in re.findall(r'assets/(numbered-[^\"]+)',d['body']+d['answer'])}
    assets_root=(ROOT/'dist/assets').resolve()
    for path in assets_root.glob('numbered-*.webp'):
        assert path.resolve().parent==assets_root
        if path.name not in active:path.unlink()
    print('WEBSITE',len(display),'presentation entries ready',flush=True)
    if not args.presentation_only:
        subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/build_numbered_pdfs.py'),'--merge-only'],cwd=ROOT,check=True)
        # Only scratch render files; retain source pages, labels, templates and final books.
        scratch=(ROOT/'tmp').resolve()
        transient=[p for p in scratch.glob('library*/numbered/*') if p.is_file() and p.suffix.lower() in {'.pdf','.png'}]
        for p in transient:
            resolved=p.resolve()
            assert resolved.is_relative_to(scratch) and resolved.parent.name=='numbered'
        for p in transient:p.unlink()
        print('CACHE',len(transient),'temporary render files released',flush=True)
