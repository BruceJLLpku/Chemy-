"""Verify one watermark per page, original content, and the exported PDF layer."""
import argparse
import hashlib
import json
import subprocess
from io import BytesIO
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from pypdf import PdfReader
from pypdf.generic import ContentStream
from pdf_watermark import ASSET, MARKER, OPACITY, ROOT, contents, stamp_pdf, unwatermarked_bytes

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--baseline', help='Optional Git revision before the watermark-only edit')
parser.add_argument('--git', default='git')
args = parser.parse_args()
report = {'books': [], 'exports': [], 'checks': []}
asset_hash = hashlib.sha256(ASSET.read_bytes()).hexdigest()
for path in sorted((ROOT / 'dist/downloads').glob('*.pdf')):
    reader = PdfReader(path)
    for number, page in enumerate(reader.pages):
        layers = [s.get_object() for s in contents(page) if s.get_object().get(MARKER)]
        assert len(layers) == 1, (path.name, number, 'watermark count')
        form = page['/Resources']['/XObject'][MARKER]
        state = form['/Resources']['/ExtGState']['/WMState']
        assert float(state['/ca']) == OPACITY and state['/BM'] == '/Multiply'
        assert hashlib.sha256(form['/Resources']['/XObject']['/WMImage']._data).hexdigest() == asset_hash
    if args.baseline:
        original = subprocess.run([args.git, '-c', f'safe.directory={ROOT.as_posix()}',
                                   'show', f'{args.baseline}:dist/downloads/{path.name}'],
                                  cwd=ROOT, capture_output=True, check=True).stdout
        assert path.read_bytes().startswith(original), (path.name, 'original bytes changed')
        assert len(reader.pages) == len(PdfReader(BytesIO(original)).pages)
        if path.name in ['analysis-questions.pdf', 'organic-questions.pdf']:
            clean = pdfium.PdfDocument(unwatermarked_bytes(path))
            before = pdfium.PdfDocument(original)
            for number in [0, len(reader.pages)//2, len(reader.pages)-1]:
                a = clean[number].render(scale=1).to_pil().convert('RGB')
                b = before[number].render(scale=1).to_pil().convert('RGB')
                assert np.array_equal(np.asarray(a), np.asarray(b)), (path.name, number, 'original ink changed')
            clean.close(); before.close()
            report['checks'].append(path.name+' original ink matches baseline at first/middle/last page')
    report['books'].append({'file': path.name, 'pages': len(reader.pages)})
    print('PASS', path.name, len(reader.pages), 'pages', flush=True)

for path in [ROOT/'output/pdf'/name for name in ['selected-continuous.pdf','single-crystal.pdf','single-organic.pdf','nine-topics.pdf']]:
    reader = PdfReader(path)
    for number, page in enumerate(reader.pages):
        resources = page['/Resources']
        stream = ContentStream(page.get('/Contents'), reader)
        draws = []
        for operands, operator in stream.operations:
            if operator == b'Do':
                obj = resources['/XObject'][operands[0]]
                if obj['/Subtype'] == '/Image':
                    draws.append(obj)
        assert len(draws) == 1, (path.name, number, 'export watermark count')
        assert hashlib.sha256(draws[0]._data).hexdigest() == asset_hash
        states = [resources['/ExtGState'][args[0]] for args, op in stream.operations if op == b'gs']
        assert sum(float(s.get('/ca',1)) == OPACITY and s.get('/BM') == '/Multiply' for s in states) == 1
    report['exports'].append({'file': path.name, 'pages': len(reader.pages)})
    print('PASS', path.name, 'one complete watermark per output page', flush=True)

path = ROOT/'dist/downloads/analysis-questions.pdf'
before = hashlib.sha256(path.read_bytes()).hexdigest()
assert stamp_pdf(path)[1] is False
assert hashlib.sha256(path.read_bytes()).hexdigest() == before
report['checks'].append('Repeated stamping leaves already-watermarked book unchanged')
target = ROOT/'output/watermark/pdf-checks.json'
target.parent.mkdir(parents=True, exist_ok=True)
target.write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
print('PASS repeated stamping is idempotent',flush=True)
