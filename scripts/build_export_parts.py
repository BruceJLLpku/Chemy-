"""Build clean, font-subsetted vector fragments for private browser composition.

Uses committed books/indexes; needs neither ingestion caches nor system fonts.
Generated PDFs live in dist/export-parts and can be rebuilt on Pages or locally.
"""
import argparse
from concurrent.futures import ProcessPoolExecutor
import gc
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ContentStream, DictionaryObject, FloatObject, NameObject

from pdf_clip_cleanup import clean_source_page
from pdf_font_subset import subset_pdf_fonts
from pdf_watermark import strip_watermark

ROOT = Path(__file__).resolve().parents[1]
DEST = ROOT / 'dist/export-parts'
CACHE = ROOT / 'tmp/export-parts'
PROFILE = 'clean-vector-v1'


def sha(data):
    return hashlib.sha256(data).hexdigest()


def json_bytes(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).encode('utf8')


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_bytes(data)
    temporary.replace(path)


def namespace_page(page, reader, prefix):
    """Give page-level resources unique names before direct browser composition."""
    resources = page['/Resources'].get_object()
    names = {}
    renamed = DictionaryObject()
    for category, value in resources.items():
        resolved = value.get_object()
        if not isinstance(resolved, DictionaryObject):
            renamed[category] = value
            continue
        result = DictionaryObject()
        for old, reference in resolved.items():
            # The category is part of the name because fonts and images may both
            # be named /R0. Nested resources (e.g. patterns) retain their scope.
            new = NameObject('/' + prefix + category[1:] + old[1:])
            names[(str(category), str(old))] = new
            result[new] = reference
        renamed[category] = result
    stream = ContentStream(page['/Contents'], reader)
    categories = {b'Tf': ('/Font', 0), b'gs': ('/ExtGState', 0), b'Do': ('/XObject', 0),
                  b'sh': ('/Shading', 0), b'CS': ('/ColorSpace', 0), b'cs': ('/ColorSpace', 0),
                  b'SCN': ('/Pattern', -1), b'scn': ('/Pattern', -1),
                  b'BDC': ('/Properties', -1), b'DP': ('/Properties', -1)}
    operations = []
    for args, op in stream.operations:
        if op == b'INLINE IMAGE':
            # Only the inline image's color-space name belongs to page resources.
            args = dict(args)
            args['settings'] = DictionaryObject(args['settings'])
            for key in ['/CS', '/ColorSpace']:
                old = args['settings'].get(key)
                if ('/ColorSpace', str(old)) in names:
                    args['settings'][NameObject(key)] = names[('/ColorSpace', str(old))]
        else:
            args = list(args)
            if op in categories and args:
                category, index = categories[op]
                args[index] = names.get((category, str(args[index])), args[index])
        operations.append((args, op))
    stream.operations = operations
    page[NameObject('/Contents')] = stream
    page[NameObject('/Resources')] = renamed


def make_part(clean_pages, bands, identity):
    """Each mini-page physically contains one safe band, never the source page."""
    doc = fitz.open()
    sources = {}
    try:
        for band in bands:
            number = band['sourcePage']
            if number not in sources:
                sources[number] = fitz.open('pdf', clean_pages(number))
            source = sources[number]
            doc.insert_pdf(source, from_page=0, to_page=0, final=0)
            page = doc[-1]
            # Cleaning a source page uses temporary PDFs. Their inline font
            # dictionaries must not contaminate this document's clip metrics.
            fitz.TOOLS.store_shrink(100)
            page.clip_to_rect(fitz.Rect(band['box']))
            page.clean_contents()
        fitz.TOOLS.store_shrink(100)
        doc.subset_fonts()
        raw = doc.tobytes(garbage=1, deflate=True, use_objstms=1, no_new_id=True)
    finally:
        doc.close()
        for source in sources.values():
            source.close()
    reader = PdfReader(BytesIO(raw))
    writer = PdfWriter()
    # Same document resource identities are reused by PdfWriter. Unique page
    # prefixes also make accidental cross-page collisions impossible.
    for n, (page, band) in enumerate(zip(reader.pages, bands)):
        namespace_page(page, reader, 'C' + sha(identity.encode())[:20] + 'P' + str(n))
        x0, top, x1, bottom = band['box']
        height = float(page.mediabox.height)
        page[NameObject('/MediaBox')] = ArrayObject([FloatObject(v) for v in [x0, height-bottom, x1, height-top]])
        for key in ['/CropBox', '/TrimBox', '/BleedBox', '/ArtBox', '/Annots']:
            if key in page:
                del page[key]
        writer.add_page(page)
    writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    output = BytesIO()
    writer.write(output)
    # Deduplication above is deliberately performed by pypdf. MuPDF's higher
    # garbage levels can incorrectly remap images with separate alpha masks.
    with fitz.open('pdf', output.getvalue()) as result:
        assert all(not p.get_xobjects() for p in result), 'Page Form survived cleanup'
        return subset_pdf_fonts(result.tobytes(garbage=1, deflate=True, use_objstms=1, no_new_id=True))


def _compact_book_resources(raw):
    """Merge nested resource references to a fixed point using pinned pypdf.

    A first pass may merge masks/font programs, making their parent images or
    font dictionaries identical only on the next pass. Keep all objects while
    rewriting references, then remove unreferenced objects without new merges.
    """
    writer = PdfWriter(clone_from=PdfReader(BytesIO(raw)))
    remaining = sum(obj is not None for obj in writer._objects)
    while True:
        writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=False)
        current = sum(obj is not None for obj in writer._objects)
        if current == remaining:
            break
        remaining = current
    writer.compress_identical_objects(remove_duplicates=False, remove_unreferenced=True)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _assemble_clean_pages(clean_pages, count, batch_size):
    """Bound duplicate resource growth before final whole-book decoration.

    Each checkpoint deduplicates the complete accumulated document, so later
    batches can still share earlier fonts/images. Close the native document
    before pypdf clones it, then reopen the resulting bytes before inserting
    more pages. No references from a previous native document survive reuse.
    """
    if not isinstance(batch_size, int) or isinstance(batch_size, bool) or batch_size < 1:
        raise ValueError('Book batch size must be a positive integer')
    doc = fitz.open()
    try:
        for number in range(count):
            with fitz.open('pdf', clean_pages(number)) as source:
                doc.insert_pdf(source)
            if (number + 1) % batch_size == 0 or (number + 1 == count and count > batch_size):
                raw = doc.tobytes(garbage=1, deflate=True, use_objstms=1, no_new_id=True)
                doc.close()
                fitz.TOOLS.store_shrink(100)
                try:
                    compacted = _compact_book_resources(raw)
                finally:
                    del raw
                    # pypdf readers/writers contain cycles; do not retain each
                    # prior checkpoint until an incidental later collection.
                    gc.collect()
                    fitz.TOOLS.store_shrink(100)
                doc = fitz.open('pdf', compacted)
                del compacted
        return doc
    except BaseException:
        if not doc.is_closed:
            doc.close()
        raise


def make_clean_book(clean_pages, count, title, toc=None, *, batch_size=32):
    """Assemble native pages in bounded batches, then add whole-book metadata."""
    doc = _assemble_clean_pages(clean_pages, count, batch_size)
    image_xref = 0
    state = doc.get_new_xref()
    doc.update_object(state, '<< /Type /ExtGState /ca 0.18 /CA 0.18 /BM /Multiply >>')
    from PIL import Image
    watermark_path = ROOT / 'dist/assets/chemy-watermark.jpg'
    with Image.open(watermark_path) as image:
        iw, ih = image.size
    for page in doc:
        w, h = page.rect.width, page.rect.height
        draw_width = min(w*.62, h*.60*iw/ih)
        draw_height = draw_width*ih/iw
        rect = fitz.Rect((w-draw_width)/2, (h-draw_height)/2, (w+draw_width)/2, (h+draw_height)/2)
        image_xref = page.insert_image(rect, filename=str(watermark_path), xref=image_xref)
        resource_kind, resource_value = doc.xref_get_key(page.xref, 'Resources')
        if resource_kind == 'dict':
            resource_xref = doc.get_new_xref()
            doc.update_object(resource_xref, resource_value)
            doc.xref_set_key(page.xref, 'Resources', f'{resource_xref} 0 R')
        elif resource_kind == 'xref':
            resource_xref = int(resource_value.split()[0])
        else:
            raise ValueError('Missing resources in assembled book')
        state_kind, state_value = doc.xref_get_key(resource_xref, 'ExtGState')
        if state_kind == 'null':
            doc.xref_set_key(resource_xref, 'ExtGState', '<<>>')
        if state_kind == 'xref':
            doc.xref_set_key(int(state_value.split()[0]), 'ChemyExportWatermark', f'{state} 0 R')
        else:
            doc.xref_set_key(resource_xref, 'ExtGState/ChemyExportWatermark', f'{state} 0 R')
        stream = page.get_contents()[-1]
        doc.update_stream(stream, b'q /ChemyExportWatermark gs\n' + doc.xref_stream(stream) + b'\nQ')
    doc.set_metadata({'title': title, 'author': 'Chemy 化学奥林匹克团队', 'creator': 'Chemy clean vector export'})
    if toc:
        doc.set_toc(toc)
    raw = doc.tobytes(garbage=1, deflate=True, use_objstms=1, no_new_id=True)
    doc.close()
    # Keep the whole catalog, including the source question bookmarks, while
    # merging resources duplicated by the individual cleaned page documents.
    raw = _compact_book_resources(raw)
    with fitz.open('pdf', raw) as compacted:
        raw = compacted.tobytes(garbage=1, deflate=True, use_objstms=1, no_new_id=True)
    return subset_pdf_fonts(raw)


def _build_book(job):
    slug, kind, selected, force = job
    book_path = ROOT / 'dist/downloads' / f'{slug}-{kind}.pdf'
    index_path = ROOT / 'dist/export-index' / (slug + ('-answers' if kind == 'answers' else '') + '.json')
    book_sha = sha(book_path.read_bytes())
    index = json.loads(index_path.read_text(encoding='utf8'))
    code_sha = sha(b''.join((ROOT/'scripts'/p).read_bytes() for p in ['build_export_parts.py', 'pdf_clip_cleanup.py', 'pdf_render_verify.py', 'pdf_font_subset.py', 'pdf_watermark.py', 'export-requirements.txt']) + (ROOT/'dist/assets/chemy-watermark.jpg').read_bytes())
    signature = sha(json_bytes([PROFILE, book_sha, sha(index_path.read_bytes()), code_sha]))
    manifest_path = DEST / f'{slug}-{kind}.json'
    try:
        existing = json.loads(manifest_path.read_text(encoding='utf8')) if manifest_path.exists() else {}
    except (json.JSONDecodeError, UnicodeDecodeError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    if existing.get('signature') != signature:
        existing = {}
    question_ids = [qid for qid in index['questions'] if selected is None or qid in selected]
    if not question_ids:
        return None
    reader = PdfReader(book_path)
    # The browser stamps one watermark on the final page. Remove the publisher's
    # marked decorative stream before splitting; never crop it into every band.
    for page in reader.pages:
        strip_watermark(page)
    # Layout/font/manifest changes need not repeat the expensive scope cleanup.
    cleaning_sha = sha(b''.join((ROOT/'scripts'/p).read_bytes() for p in ['pdf_clip_cleanup.py', 'pdf_render_verify.py', 'pdf_watermark.py', 'export-requirements.txt']))
    page_cache = CACHE / 'pages' / sha((book_sha+cleaning_sha).encode())
    cleaned_this_run = set()
    verified_cache = set()

    def clean(number):
        target = page_cache / f'{number}.pdf'
        stamp = target.with_suffix('.json')
        cached = None
        if target.exists() and stamp.exists():
            cached = target.read_bytes()
            if number not in verified_cache:
                try:
                    metadata = json.loads(stamp.read_text(encoding='utf8'))
                    if (not isinstance(metadata, dict) or metadata.get('sourcePage') != number
                            or metadata.get('sha256') != sha(cached)):
                        cached = None
                    else:
                        verified_cache.add(number)
                except (ValueError, OSError):
                    cached = None
        if cached is None or (force and number not in cleaned_this_run):
            diagnostics = {}
            try:
                data = clean_source_page(reader.pages[number], reader, diagnostics=diagnostics)
            except Exception as exc:
                raise RuntimeError(f'{slug} {kind}, source page {number+1}: {exc}') from exc
            atomic_write(target, data)
            atomic_write(stamp, json_bytes({'sourcePage': number, 'sha256': sha(data), **diagnostics}))
            cleaned_this_run.add(number)
            verified_cache.add(number)
            return data
        return cached

    cached_questions = existing.get('questions', {})
    if not isinstance(cached_questions, dict):
        cached_questions = {}
    data = {'profile': PROFILE, 'bookVersion': index['bookVersion'], 'signature': signature,
            'sourceBook': f'downloads/{slug}-{kind}.pdf', 'sourceSha256': book_sha,
            'indexSha256': sha(index_path.read_bytes()),
            'questions': {qid: entry for qid, entry in cached_questions.items()
                          if qid in index['questions'] and isinstance(entry, dict)}}
    frame_bands = [{'sourcePage': 0, 'box': [50, float(reader.pages[0].mediabox.height)-44, float(reader.pages[0].mediabox.width)-90, float(reader.pages[0].mediabox.height)-31]},
                   {'sourcePage': 0, 'box': [0, 47, float(reader.pages[0].mediabox.width), 63]}]
    frame_path = DEST / f'{slug}-{kind}-frame.pdf'
    frame_old = existing.get('frame', {})
    if not isinstance(frame_old, dict):
        frame_old = {}
    if force or not frame_path.exists() or sha(frame_path.read_bytes()) != frame_old.get('sha256'):
        atomic_write(frame_path, make_part(clean, frame_bands, slug+'-'+kind+'-frame'))
    data['frame'] = {'path': frame_path.relative_to(DEST).as_posix(), 'sha256': sha(frame_path.read_bytes()), 'bytes': frame_path.stat().st_size}
    for n, qid in enumerate(question_ids):
        assert re.fullmatch(r'[a-zA-Z0-9-]+', qid), qid
        part_path = DEST / slug / f'{qid}-{kind}.pdf'
        old = data['questions'].get(qid, {})
        bands, regions = [], []
        for region in index['questions'][qid]:
            width = float(reader.pages[region['page']].mediabox.width)
            entries = []
            for top, bottom in region['bands']:
                entries.append({'page': len(bands), 'top': top, 'bottom': bottom, 'width': width})
                bands.append({'sourcePage': region['page'], 'box': [0, top, width, bottom]})
            regions.append({'sourcePage': region['page'], 'bands': entries})
        cached_part = part_path.read_bytes() if not force and part_path.exists() else None
        reused = cached_part is not None and sha(cached_part) == old.get('sha256')
        raw = cached_part if reused else make_part(clean, bands, qid+'-'+kind)
        if not reused:
            atomic_write(part_path, raw)
        # A valid PDF digest does not validate cached page/placement metadata.
        # Reconstruct it from this signed index even when reusing the bytes.
        data['questions'][qid] = {'path': part_path.relative_to(DEST).as_posix(), 'sha256': sha(raw),
                                 'bytes': len(raw), 'pages': bands, 'regions': regions}
        if n % 20 == 0 and not reused:
            data['complete'] = False
            atomic_write(manifest_path, json_bytes(data))
            print(slug, kind, n+1, '/', len(question_ids), len(raw), 'bytes', flush=True)
    data['complete'] = set(data['questions']) == set(index['questions'])
    if data['complete']:
        clean_book_path = DEST / f'{slug}-{kind}-book.pdf'
        old_book = existing.get('cleanBook', {})
        if not isinstance(old_book, dict):
            old_book = {}
        if force or not clean_book_path.exists() or sha(clean_book_path.read_bytes()) != old_book.get('sha256'):
            with fitz.open(book_path) as original:
                toc = original.get_toc()
            raw = make_clean_book(clean, len(reader.pages), (reader.metadata or {}).get('/Title', f'Chemy {slug} {kind}'), toc)
            atomic_write(clean_book_path, raw)
        data['cleanBook'] = {'path': clean_book_path.name, 'bytes': clean_book_path.stat().st_size,
                             'sha256': sha(clean_book_path.read_bytes()), 'pages': len(reader.pages)}
    atomic_write(manifest_path, json_bytes(data))
    print('BUILT', slug, kind, len(data['questions']), 'questions', flush=True)
    return {'path': manifest_path.name, 'sha256': sha(manifest_path.read_bytes()), 'complete': data['complete']}


def build_book(job):
    try:
        return _build_book(job)
    except Exception as exc:
        # ProcessPoolExecutor waits for other workers before propagating an
        # exception. Show the failing book/page immediately in long CI builds.
        print('FAILED', job[0], job[1], str(exc), flush=True)
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--topics', nargs='+', help='Build only these topic slugs')
    ap.add_argument('--ids', nargs='+', help='Build only these question IDs (development samples)')
    ap.add_argument('--jobs', type=int, default=2)
    ap.add_argument('--force', action='store_true')
    args = ap.parse_args()
    slugs = sorted(p.stem.removesuffix('-questions') for p in (ROOT/'dist/downloads').glob('*-questions.pdf'))
    if args.topics:
        if set(args.topics)-set(slugs):
            ap.error('Unknown topic slug')
        slugs = args.topics
    jobs = [(slug, kind, args.ids, args.force) for slug in slugs for kind in ['questions','answers']]
    if args.jobs == 1:
        results = list(map(build_book, jobs))
    else:
        with ProcessPoolExecutor(max_workers=args.jobs) as pool:
            results = list(pool.map(build_book, jobs))
    # Inventory is diagnostic; workers use one small topic manifest, not a full
    # 3,866-entry catalogue, so first export stays lightweight.
    manifests = [json.loads(p.read_text(encoding='utf8')) for p in DEST.glob('*-questions.json')] + [json.loads(p.read_text(encoding='utf8')) for p in DEST.glob('*-answers.json')]
    atomic_write(DEST/'manifest.json', json_bytes({'profile': PROFILE, 'bookVersion': json.loads((ROOT/'dist/numbering.json').read_text(encoding='utf8'))['pdfVersion'],
        'books': {Path(m['sourceBook']).stem: {'complete': m['complete'], 'sourceSha256': m['sourceSha256'], 'count': len(m['questions'])} for m in manifests}}))


if __name__ == '__main__':
    main()
