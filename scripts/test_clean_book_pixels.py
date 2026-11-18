"""Compare every delivered topic-book page with its validated clean source page.

Run after a complete build_export_parts.py run, with its page cache retained.
Checks bookmarks, text and 144 dpi pixels, removing only the known watermark.
Results are written to work/whole-book-validation/. No published files change.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import hashlib
import json
import math
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import pymupdf as fitz
from PIL import Image, ImageChops
from pdf_clip_cleanup import _matched_image_difference
from pdf_export_validation import open_without_browser_watermark
from pdf_image_verify import canonical_image_proof
from pdf_render_verify import render_no_tile_cache
from test_export_parts import ValidatedCleanPages, code_digests, check_build_signature


def sha(data):
    return hashlib.sha256(data).hexdigest()


def delta(a, b):
    assert (a.width, a.height, a.n) == (b.width, b.height, b.n)
    return max(high for low, high in ImageChops.difference(
        Image.frombytes('RGB', (a.width, a.height), a.samples),
        Image.frombytes('RGB', (b.width, b.height), b.samples)).getextrema())


def original_page_pdfium(page, scale):
    """Render the selected page from unchanged loaded bytes, without a page copy.

    Copying a page into a new document can change the font/resource context.
    This check must use the actual complete book bytes and original page index.
    """
    import pypdfium2 as pdfium

    document = page.parent
    raw, number = document.stream, page.number
    if (document.is_dirty or document.is_repaired or not isinstance(raw, bytes) or not raw
            or type(number) is not int or not 0 <= number < len(document)):
        raise ValueError('Independent rendering requires unchanged loaded PDF bytes and page identity')
    if type(scale) not in (int, float) or not math.isfinite(scale) or scale <= 0:
        raise ValueError('Independent render scale must be finite and positive')
    size = page.rect.width, page.rect.height
    if page.rotation or not all(math.isfinite(value) and value > 0 for value in size):
        raise ValueError('Unsupported native page geometry')
    identity = {'inputSha256': sha(raw), 'pageIndex': number, 'pages': len(document)}
    with pdfium.PdfDocument(raw) as independent:
        if len(independent) != len(document):
            raise ValueError('Independent page count differs from loaded PDF')
        selected = independent[number]
        try:
            if selected.get_rotation():
                raise ValueError('Independent page rotation differs')
            width, height = selected.get_size()
            box = 0., 0., width, height
            if (any(abs(a - b) > 1e-4 for a, b in zip((width, height), size))
                    or any(abs(a - b) > 1e-4 for a, b in zip(selected.get_mediabox(), box))
                    or any(abs(a - b) > 1e-4 for a, b in zip(selected.get_cropbox(), box))):
                raise ValueError('Independent page geometry differs from native page')
            bitmap = selected.render(scale=scale, rotation=0, crop=(0, 0, 0, 0),
                                     fill_color=(255, 255, 255, 255), may_draw_forms=False)
            try:
                if (bitmap.width, bitmap.height) != (math.ceil(width * scale), math.ceil(height * scale)):
                    raise ValueError('Independent bitmap dimensions differ')
                image = bitmap.to_pil().convert('RGB').copy()
                scales = bitmap.width / width, bitmap.height / height
            finally:
                bitmap.close()
        finally:
            selected.close()
    if document.is_dirty or document.stream is not raw:
        raise ValueError('Loaded PDF changed during independent rendering')
    return image, scales, identity


def compare_page(expected, actual):
    """Strict full-page comparison, with the existing image identity proof."""
    assert actual.rect == expected.rect
    fitz.TOOLS.store_shrink(100)
    actual_text = actual.get_text()
    actual_pixels = actual.get_pixmap(matrix=fitz.Matrix(2, 2))
    fitz.TOOLS.store_shrink(100)
    expected_text = expected.get_text()
    expected_pixels = expected.get_pixmap(matrix=fitz.Matrix(2, 2))
    difference = delta(actual_pixels, expected_pixels)
    entry = {'maxDelta': difference, 'textEqual': actual_text == expected_text,
             'tileCacheDisabled': False}
    if difference > 8:
        entry['initialMaxDelta'] = difference
        fitz.TOOLS.store_shrink(100)
        actual_pixels = render_no_tile_cache(actual)
        fitz.TOOLS.store_shrink(100)
        expected_pixels = render_no_tile_cache(expected)
        difference = delta(actual_pixels, expected_pixels)
        entry.update(tileCacheDisabled=True, tileCacheMaxDelta=difference, maxDelta=difference)
    if difference > 8 and entry['textEqual']:
        before = Image.frombytes('RGB', (expected_pixels.width, expected_pixels.height), expected_pixels.samples)
        after = Image.frombytes('RGB', (actual_pixels.width, actual_pixels.height), actual_pixels.samples)
        proof = _matched_image_difference(expected, actual, ImageChops.difference(before, after))
        entry['imageSamplingProof'] = proof
        if not proof['matched'] and proof.get('reason') == 'image bytes, paint, transform or clipping differs':
            try:
                canonical, evidence = canonical_image_proof(expected, actual, ImageChops.difference(before, after))
            except (ValueError, RuntimeError, AssertionError) as error:
                entry['losslessImageProofError'] = str(error)
            else:
                entry['losslessImageProof'] = {'proof': canonical, 'copies': evidence}
                if canonical['matched']:
                    entry['initialImageSamplingProof'] = proof
                    proof = canonical
                    entry['imageSamplingProof'] = proof
        if proof['matched']:
            phases = []
            for offset in ((.37, .23), (.73, .61)):
                fitz.TOOLS.store_shrink(100)
                left = render_no_tile_cache(expected, offset=offset)
                fitz.TOOLS.store_shrink(100)
                right = render_no_tile_cache(actual, offset=offset)
                phases.append(delta(left, right))
            entry['imageSamplingPhaseDeltas'] = phases
            # Both shifted full pages must pass the unchanged threshold. No
            # label holes, local masks, or page-specific exceptions apply.
            if max(phases) <= 8:
                entry['maxDelta'] = max(phases)
            else:
                checks = []
                try:
                    for scale in (2, 4):
                        left, left_scale, left_input = original_page_pdfium(expected, scale)
                        right, right_scale, right_input = original_page_pdfium(actual, scale)
                        if left.size != right.size or left_scale != right_scale:
                            raise ValueError('Independent bitmap coordinate mappings differ')
                        maximum = max(high for low, high in ImageChops.difference(left, right).getextrema())
                        checks.append({'dpi': scale * 72, 'maxDelta': maximum,
                                       'pixelScales': list(left_scale),
                                       'expectedInput': left_input, 'actualInput': right_input})
                except (ValueError, RuntimeError, AssertionError) as error:
                    entry['independentError'] = str(error)
                entry.update(independentRenderer='PDFium', independentFullPageChecks=checks)
                # Both original full-page rasters must pass. Nothing is masked
                # or removed from this comparison, including original numbers.
                if len(checks) == 2 and 'independentError' not in entry and max(c['maxDelta'] for c in checks) <= 8:
                    entry['maxDelta'] = max(c['maxDelta'] for c in checks)
    return entry


def check(path):
    metadata = json.loads(path.read_text(encoding='utf8'))
    assert metadata['complete']
    book = ROOT / 'dist/export-parts' / metadata['cleanBook']['path']
    assert sha(book.read_bytes()) == metadata['cleanBook']['sha256']
    cleaning, build = code_digests(ROOT)
    source_path = ROOT / 'dist' / metadata['sourceBook']
    source_sha = sha(source_path.read_bytes())
    assert source_sha == metadata['sourceSha256'], ('stale source', path)
    slug, kind = path.stem.rsplit('-', 1)
    index_path = ROOT / 'dist/export-index' / (slug + ('-answers' if kind == 'answers' else '') + '.json')
    index_sha = sha(index_path.read_bytes())
    assert index_sha == metadata['indexSha256'], ('stale index', path)
    check_build_signature(metadata, source_sha, index_sha, build)
    references = ValidatedCleanPages(ROOT, source_sha, cleaning)
    report = {'book': book.name, 'pages': [], 'errors': []}
    with fitz.open(ROOT / 'dist' / metadata['sourceBook']) as source, fitz.open(book) as original:
        assert original.get_toc() == source.get_toc(), ('bookmark titles/targets', book)
    try:
        with open_without_browser_watermark(book) as result:
            assert len(result) == metadata['cleanBook']['pages']
            for number, actual in enumerate(result):
                entry = {'page': number + 1, **compare_page(references.page(number), actual)}
                report['pages'].append(entry)
                if entry['maxDelta'] > 8 or not entry['textEqual']:
                    report['errors'].append(entry)
                if number % 50 == 0:
                    print(book.name, number + 1, '/', len(result), flush=True)
        report['cleanReferenceCache'] = references.directory.name
        report['cleanReferences'] = list(references.verified.values())
    finally:
        references.close()
    assert code_digests(ROOT) == (cleaning, build), 'Production code changed during book validation'
    out = ROOT / 'work/whole-book-validation'
    out.mkdir(parents=True, exist_ok=True)
    (out / (path.stem + '.json')).write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    print('VERIFIED', book.name, len(report['pages']), 'pages', len(report['errors']), 'errors', flush=True)
    return {'book': book.name, 'pages': len(report['pages']), 'errors': report['errors']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--jobs', type=int, default=2)
    args = parser.parse_args()
    paths = sorted((ROOT / 'dist/export-parts').glob('*-questions.json')) + sorted((ROOT / 'dist/export-parts').glob('*-answers.json'))
    assert len(paths) == 18
    with ProcessPoolExecutor(max_workers=args.jobs) as pool:
        report = list(pool.map(check, paths))
    (ROOT / 'work/whole-book-validation/summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf8')
    assert not any(item['errors'] for item in report), 'Whole-topic content changed'
