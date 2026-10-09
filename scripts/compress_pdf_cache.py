"""Losslessly compress generated PDF templates; keep every source and cache file."""
import os,sys,hashlib
from collections import Counter
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tmp/pdf-engine'))
import pikepdf
from pypdf import PdfReader
from pdf_form_cache import wrap_template

def content(pdf):
    return [([float(x) for x in p.mediabox],hashlib.sha256(p.obj['/Contents'].read_bytes()).hexdigest()) for p in pdf.pages]

saved=0;count=0
base=(ROOT/'tmp/library/books').resolve()
paths=sorted(base.glob('*.template.pdf'),key=lambda p:-p.stat().st_size)
for path in paths:
    assert path.resolve().parent==base
    before=path.stat().st_size;temporary=path.with_suffix('.compressing.pdf')
    original=[([float(x) for x in p.mediabox],hashlib.sha256(p.get_contents().get_data()).hexdigest()) for p in PdfReader(path).pages]
    wrap_template(path,path.with_suffix('.sha256').read_text())
    with pikepdf.open(path) as pdf:
        assert content(pdf)==original,path.name
        assert not pdf.check_pdf_syntax(),path.name
        pdf.save(temporary,compress_streams=True,object_stream_mode=pikepdf.ObjectStreamMode.generate,deterministic_id=True)
    with pikepdf.open(temporary) as pdf:assert content(pdf)==original,path.name
    after=temporary.stat().st_size
    if after<before:os.replace(temporary,path);saved+=before-after
    else:os.replace(temporary,path)
    count+=1
    if '--sample' in sys.argv:break
    if count%100==0:print('COMPRESSED',count,'templates; bytes saved',saved,flush=True)
print('COMPRESSED',count,'templates; bytes saved',saved,flush=True)
