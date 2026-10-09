"""Release the existing disposable render cache after an edition worker finishes."""
import hashlib,json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
read=lambda p:json.loads(p.read_text(encoding='utf8'))
bank=read(ROOT/'dist/questions.json');numbers=read(ROOT/'dist/numbering.json')['numberById']
source=hashlib.sha256(b''.join((ROOT/'scripts'/s).read_bytes() for s in ['renumber_library.py','build_numbered_pdfs.py','import_library.py','display_numbering.py','fast_pdf.py','pdf_form_cache.py','source_info.py'])).hexdigest()
total=count=0
for e in {q.get('edition',39) for q in bank}:
    items=[q for q in bank if q.get('edition',39)==e]
    cache=ROOT/'tmp'/('library' if e==39 else f'library{e}')/'numbered';stamp=cache/'edition.sha256'
    expected=hashlib.sha256(json.dumps({'q':items,'n':{q['id']:numbers[q['id']] for q in items},'scripts':source},sort_keys=True).encode()).hexdigest()
    if not stamp.exists() or stamp.read_text()!=expected:continue
    before=cache.stat()
    for path in cache.iterdir():
        if not path.is_file() or path.suffix.lower() not in {'.pdf','.png'}:continue
        assert path.resolve().parent==cache.resolve() and path.resolve().is_relative_to((ROOT/'tmp').resolve())
        total+=path.stat().st_size;path.unlink();count+=1
    os.utime(cache,ns=(before.st_atime_ns,before.st_mtime_ns))
print('SCRATCH released',count,'temporary files',total,'bytes; original pages, diagrams, templates and books retained',flush=True)
