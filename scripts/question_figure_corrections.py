"""Restore verified missing figures from the repeated prompt, never from solutions.

Original source PDFs remain byte-identical. The recipe points to a reviewed, fully
rendered crop: extracting its underlying JPEG would expose a label masked by the
source PDF. Used by both re-ingestion and the targeted published-book migration.
"""
import argparse
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
RECIPE = ROOT / 'data/question_figure_corrections.json'


def corrections(edition, kind, page, paper=None, number=None):
    if kind != 'q':
        return []
    return [c for c in json.loads(RECIPE.read_text(encoding='utf8'))['corrections']
            if (c['edition'], c['page']) == (edition, page)
            and (paper is None or c['paper'] == paper)
            and (number is None or c['number'] == number)]


def correction_signature(edition, kind, page):
    found = corrections(edition, kind, page)
    return hashlib.sha256(json.dumps(found, sort_keys=True).encode()).hexdigest() if found else ''


def verified_asset(c):
    path = ROOT / 'dist/assets' / c['asset']
    if hashlib.sha256(path.read_bytes()).hexdigest() != c['sha256']:
        raise ValueError('Reviewed figure bytes changed: ' + c['asset'])
    return path


def png_bytes(c):
    from PIL import Image
    out = BytesIO()
    with Image.open(verified_asset(c)) as image:
        image.convert('RGB').save(out, format='PNG')
    return out.getvalue()


def patch_page(page, c, box):
    import fitz
    marker = c['id'] + ':' + c['sha256']
    if page.parent.xref_get_key(page.xref, 'ChemyFigureCorrection')[1] == marker:
        return False
    # Physically remove the obsolete D/E/X text; a white cover alone would leave
    # editable duplicate text under the restored plot. Preserve all other art.
    page.add_redact_annot(fitz.Rect(box), fill=(1, 1, 1))
    page.apply_redactions(images=0, graphics=0, text=0)
    page.insert_image(fitz.Rect(box), stream=png_bytes(c), keep_proportion=False)
    page.parent.xref_set_key(page.xref, 'ChemyFigureCorrection', fitz.get_pdf_str(marker))
    return True


def patch_source_page(path, edition, kind, page_number):
    fixes = corrections(edition, kind, page_number)
    if not fixes:
        return
    import fitz
    with fitz.open(path) as doc:
        changed = any([patch_page(doc[0], c, c['box']) for c in fixes])
        if changed:
            raw = doc.tobytes(garbage=1, deflate=True)
    if changed:
        Path(path).write_bytes(raw)


def replace_figures(html, c):
    old = c['replaces']
    figures = list(re.finditer(r'<figure\b[^>]*>.*?</figure>', html))
    matches = [m for m in figures if any('assets/' + name in m[0] for name in old)]
    if not matches:
        if 'assets/' + c['asset'] in html:
            return html
        raise ValueError('Expected missing-figure placeholders were not found')
    if len(matches) != len(old) or html[matches[0].end():matches[-1].start()].strip():
        raise ValueError('Unexpected text between missing-figure placeholders')
    from PIL import Image
    with Image.open(verified_asset(c)) as image:
        width, height = image.size
    alt = '第39届模拟试题5 第4题 核磁共振氢谱（由官方答案的重复题干恢复）'
    figure = (f'<figure class="source-figure" style="--source-width:731px">'
              f'<a href="assets/{c["asset"]}" target="_blank" rel="noopener" aria-label="查看大图：{alt}">'
              f'<img src="assets/{c["asset"]}" alt="{alt}" width="{width}" height="{height}" '
              f'loading="lazy" style="--figure-width:731px"></a></figure>')
    return html[:matches[0].start()] + figure + html[matches[-1].end():]


def update_web(c):
    bank_path = ROOT / 'dist/questions.json'
    bank = json.loads(bank_path.read_text(encoding='utf8'))
    q = next(q for q in bank if q['id'] == c['id'])
    q['body'] = replace_figures(q['body'], c)
    bank_path.write_text(json.dumps(bank, ensure_ascii=False, indent=2), encoding='utf8', newline='\n')
    presentation_path = ROOT / 'dist/presentation.json'
    presentation = json.loads(presentation_path.read_text(encoding='utf8'))
    presentation[c['id']]['body'] = replace_figures(presentation[c['id']]['body'], c)
    presentation_path.write_text(json.dumps(presentation, ensure_ascii=False, separators=(',', ':')), encoding='utf8', newline='\n')
    manifest_path = ROOT / 'data/library_manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    spec = next(q for q in manifest['papers'][str(c['paper'])]['questions'] if q['number'] == c['number'])
    figures = spec['figures']['q']
    if any(f['asset'] in c['replaces'] for f in figures):
        first = next(i for i, f in enumerate(figures) if f['asset'] in c['replaces'])
        figures[:] = [f for f in figures if f['asset'] not in c['replaces']]
        figures.insert(first, {'page': c['page'], 'box': c['box'], 'asset': c['asset'],
                              'mode': 'band', 'sha256': c['sha256'], 'restoredFrom': 'data/question_figure_corrections.json'})
        coverage = next(p for p in spec['coverage']['q'] if p['page'] == c['page'])
        coverage['figures'] -= len(c['replaces']) - 1
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf8', newline='\n')


def _merge(bands):
    out = []
    for lo, hi in sorted(bands):
        if out and lo <= out[-1][1] + .01:
            out[-1][1] = max(hi, out[-1][1])
        else:
            out.append([lo, hi])
    return out


def update_published_book(c):
    """Migrate this known published layout without rebuilding 1,933 questions.

    Locate the plot by its surviving D/E/X labels, and derive the source-to-book
    transform instead of assuming a fixed page number or a particular margin.
    """
    import fitz
    from pypdf import PdfReader, PdfWriter
    from pdf_watermark import strip_watermark, stamp_pdf
    book = ROOT / 'dist/downloads/polymer-questions.pdf'
    layout_path = ROOT / 'data/continuous-books/polymer-questions.json'
    layout = json.loads(layout_path.read_text(encoding='utf8'))
    record = next(r for r in layout['records'] if r['id'] == c['id'])
    marker = c['id'] + ':' + c['sha256']
    if layout.get('sourceFigureCorrections', {}).get(c['id']) == marker:
        if layout['sha256'] != hashlib.sha256(book.read_bytes()).hexdigest():
            raise ValueError('Corrected book changed; rebuild its export index before migration')
        return False
    with fitz.open(ROOT / 'sources' / c['originalSource']) as source:
        original = {w[4]: w for w in source[c['page'] - 1].get_text('words')
                    if w[4] in ('D', 'E', 'X') and fitz.Rect(w[:4]).intersects(fitz.Rect(c['box']))}
    with fitz.open(book) as doc:
        candidates = []
        for n in range(record['firstPage'] - 1, record['lastPage']):
            words = doc[n].get_text('words')
            for d in [w for w in words if w[4] == 'D']:
                for e in [w for w in words if w[4] == 'E' and w[1] > d[1]]:
                    scale = (e[1] - d[1]) / (original['E'][1] - original['D'][1])
                    if not .8 < scale < 1.3:
                        continue
                    tx, ty = d[0] - original['D'][0] * scale, d[1] - original['D'][1] * scale
                    if abs(e[0] - (original['E'][0] * scale + tx)) > .1:
                        continue
                    x = original['X']
                    if not any(w[4] == 'X' and abs(w[0] - (x[0] * scale + tx)) < .1
                               and abs(w[1] - (x[1] * scale + ty)) < .1 for w in words):
                        continue
                    candidates.append((n, [c['box'][0] * scale + tx, c['box'][1] * scale + ty,
                                           c['box'][2] * scale + tx, c['box'][3] * scale + ty]))
        if len(candidates) != 1:
            raise ValueError('Cannot uniquely locate the missing spectrum: ' + repr(candidates))
    n, box = candidates[0]
    # Remove only this page's decorative watermark before redaction, then restore
    # its ordinary separate layer so watermark removal still works during export.
    writer = PdfWriter(clone_from=PdfReader(book))
    strip_watermark(writer.pages[n])
    buf = BytesIO()
    writer.write(buf)
    with fitz.open(stream=buf.getvalue(), filetype='pdf') as doc:
        page_count = len(doc)
        patch_page(doc[n], c, box)
        raw = doc.tobytes(garbage=1, deflate=True)
    temporary = book.with_suffix('.figure-fix.pdf')
    temporary.write_bytes(raw)
    stamp_pdf(temporary)
    with fitz.open(temporary) as doc:
        assert len(doc) == page_count
    temporary.replace(book)
    regions = layout['questions'][c['id']]
    region = next(r for r in regions if r['page'] == n and r['bands'][0][0] <= box[1] <= r['bands'][-1][1])
    region['bands'] = [[round(a, 4), round(b, 4)] for a, b in _merge(region['bands'] + [[box[1], box[3]]])]
    layout['sourceFigureCorrections'] = {c['id']: marker}
    layout['sha256'] = hashlib.sha256(book.read_bytes()).hexdigest()
    layout_path.write_text(json.dumps(layout, ensure_ascii=False, separators=(',', ':')), encoding='utf8', newline='\n')
    index_path = ROOT / 'dist/export-index/polymer.json'
    index = json.loads(index_path.read_text(encoding='utf8'))
    index['questions'][c['id']] = regions
    index_path.write_text(json.dumps(index, ensure_ascii=False, separators=(',', ':')), encoding='utf8', newline='\n')
    return True


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--web-only', action='store_true')
    args = parser.parse_args()
    for c in json.loads(RECIPE.read_text(encoding='utf8'))['corrections']:
        for filename, expected in [(c['originalSource'], c['originalSourceSha256']),
                                   (c['repeatedPromptSource'], c['repeatedPromptSha256'])]:
            assert hashlib.sha256((ROOT / 'sources' / filename).read_bytes()).hexdigest() == expected
        verified_asset(c)
        update_web(c)
        changed = False if args.web_only else update_published_book(c)
        print(c['id'], 'web restored;', 'book updated' if changed else 'book unchanged')
    if not args.web_only:
        print('After the final PDF build, run build_continuous_books.sync_pdf_version().')


if __name__ == '__main__':
    main()
