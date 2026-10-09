"""Mechanical PDF stream guard for the repaired native print pipeline."""
import json,hashlib,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tmp/pdf-engine'))
import pikepdf
report={};pages=0
for path in sorted((ROOT/'dist/downloads').glob('*.pdf')):
    with pikepdf.open(path) as pdf:
        warnings=pdf.check_pdf_syntax()
        # Source hyperlinks may occur twice when two cropped bands share one source page.
        # These annotations do not draw the question; reject every other syntax warning.
        assert all('Annots has duplicate entry for annotation' in warning for warning in warnings),(path.name,warnings)
        for page in pdf.pages:
            contents=page.obj['/Contents']
            assert isinstance(contents,pikepdf.Stream) or isinstance(contents,pikepdf.Array) and all(isinstance(x,pikepdf.Stream) for x in contents),path.name
        count=len(pdf.pages);pages+=count
    report[path.name]={'pages':count,'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'sourceLinkAnnotationWarnings':warnings}
assert len(report)==18
(ROOT/'data/print_structure_check.json').write_text(json.dumps({'passed':True,'pages':pages,'fullContentReviewComplete':False,'books':report},ensure_ascii=False,indent=2),encoding='utf8')
print('PRINT STRUCTURE',len(report),'books',pages,'pages; full source review still deferred',flush=True)
