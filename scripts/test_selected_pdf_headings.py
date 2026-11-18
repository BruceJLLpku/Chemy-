"""Compare visible export mastheads with complete original-paper mastheads."""
import json
from pathlib import Path

import numpy as np
import pypdfium2 as pdfium
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
report = json.loads((ROOT / 'output/question-export-tests.json').read_text(encoding='utf8'))
assert isinstance(report.get('errors'), list) and not report['errors']
assert isinstance(report.get('checks'), list) and report['checks']
assert isinstance(report.get('pdfHeadings'), dict) and report['pdfHeadings']
for filename, headings in report['pdfHeadings'].items():
    assert headings, (filename, 'missing heading placements')
    for heading in headings:
        assert {'slug', 'sourcePage', 'page', 'top', 'height'} <= set(heading), (filename, heading)
        assert heading['page'] >= 1 and heading['sourcePage'] >= 0 and heading['height'] > 0
sources = {}
checks = []
samples = []

for filename, headings in report['pdfHeadings'].items():
    with pdfium.PdfDocument(ROOT / 'output/pdf' / filename) as document:
        rendered = {}
        for n in range(len(document)):
            rendered[n + 1] = document[n].render(scale=2).to_pil().convert('RGB')
            # A clipped source form still contains invisible text. Check pixels,
            # not text extraction, to catch the old standalone top-left label.
            top = np.asarray(rendered[n + 1].crop((0, 0, rendered[n + 1].width, 94)))
            assert top.min() >= 250, (filename, n + 1, 'unexpected text above masthead')
            foot = np.asarray(rendered[n + 1].crop((0, rendered[n + 1].height - 110, rendered[n + 1].width, rendered[n + 1].height))).astype(int)
            assert not ((foot[:, :, 2] - foot[:, :, 0] > 20) & (foot[:, :, 0] < 220)).any(), (filename, n + 1, 'source book page counter leaked into footer')
        for heading in headings:
            slug = heading['slug']
            if slug not in sources:
                sources[slug] = pdfium.PdfDocument(ROOT / 'dist/downloads' / f'{slug}-questions.pdf')
            original = sources[slug][heading['sourcePage']].render(scale=2).to_pil().convert('RGB')
            # Include space above and below the complete source title; a narrow
            # crop of already-clipped output must not count as a passing check.
            expected = original.crop((0, 88, original.width, 126))
            y = round(2 * (heading['top'] - 3))
            actual = rendered[heading['page']].crop((0, y, original.width, y + 38))
            # Mid-page headings can overlap the pale watermark. Ignore its gray
            # pixels and allow one pixel of rasterization phase at fractional y.
            a = np.asarray(actual.convert('L')) < 150
            b = np.asarray(expected.convert('L')) < 150
            assert b.sum() > 300, (filename, slug, 'empty reference title')
            def expanded(mask):
                return np.asarray(Image.fromarray(mask.astype('uint8') * 255).filter(ImageFilter.MaxFilter(3))) > 0
            assert (b & expanded(a)).sum() / b.sum() > .995, (filename, slug, 'missing title strokes')
            assert (a & expanded(b)).sum() / a.sum() > .995, (filename, slug, 'unexpected title fragments')
            assert a.sum() / b.sum() > .97, (filename, slug, 'title is clipped')
            checks.append({'file': filename, 'topic': slug, 'page': heading['page'], 'passed': True})
        if filename == 'single-organic.pdf':
            rendered[1].save(ROOT / 'output/pdf/selected-heading-page.png')
        samples.append((filename, rendered[1].crop((0, 0, rendered[1].width, 360))))

for source in sources.values():
    source.close()
assert len(checks) == sum(len(headings) for headings in report['pdfHeadings'].values())
expected_topics = {h['slug'] for headings in report['pdfHeadings'].values() for h in headings}
assert {item['topic'] for item in checks} == expected_topics
montage = Image.new('RGB', (samples[0][1].width, len(samples) * 390), 'white')
draw = ImageDraw.Draw(montage)
for i, (filename, sample) in enumerate(samples):
    draw.text((24, i * 390 + 8), filename, fill='black')
    montage.paste(sample, (0, i * 390 + 30))
montage.save(ROOT / 'output/pdf/selected-heading-comparison.png')
(ROOT / 'output/pdf/selected-heading-checks.json').write_text(json.dumps({'passed': True, 'checks': checks}, indent=2), encoding='utf8')
print(f'PASS {len(checks)} complete mastheads across {len(expected_topics)} topics; no standalone top-left label')
