"""Validate fragments against the current, independently verified clean pages.

Run after build_export_parts.py. The default checks every file's structure and
renders the first question/answer in each topic; --all-renders checks every band.
Retain tmp/export-parts/pages from the build: missing or stale clean references
fail explicitly. Use --allow-incomplete only for a development sample build.
"""
import argparse
from collections import Counter, OrderedDict
from concurrent.futures import ProcessPoolExecutor
import hashlib
from io import BytesIO
import json
import math
from multiprocessing import get_context
import os
from pathlib import Path
import re

import fitz
from PIL import Image, ImageChops
from pypdf import PdfReader
from pypdf.generic import IndirectObject, DictionaryObject, ArrayObject, StreamObject, NullObject

ROOT = Path(__file__).resolve().parents[1]
PARTS = ROOT / 'dist/export-parts'
CLEANING_FILES = ('pdf_clip_cleanup.py', 'pdf_render_verify.py', 'pdf_watermark.py', 'export-requirements.txt')
BUILD_FILES = ('build_export_parts.py', 'pdf_clip_cleanup.py', 'pdf_render_verify.py',
               'pdf_font_subset.py', 'pdf_watermark.py', 'export-requirements.txt')
PROFILE = 'clean-vector-v1'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def code_digests(root):
    cleaning = digest(b''.join((root / 'scripts' / name).read_bytes() for name in CLEANING_FILES))
    build = digest(b''.join((root / 'scripts' / name).read_bytes() for name in BUILD_FILES)
                   + (root / 'dist/assets/chemy-watermark.jpg').read_bytes())
    return cleaning, build


def check_build_signature(manifest, source_sha, index_sha, build_sha):
    expected = digest(json.dumps([PROFILE, source_sha, index_sha, build_sha],
                                ensure_ascii=False, separators=(',', ':')).encode('utf8'))
    assert manifest.get('profile') == PROFILE, ('unsupported export profile', manifest.get('profile'))
    assert manifest.get('signature') == expected, 'Stale build signature: rebuild export parts before validation'


class ValidatedCleanPages:
    """A bounded cache of references accepted by this source/cleaner revision.

    The builder writes a stamp only after full-page cleanup verification passes.
    Never substitute the original page: its intentional cleanup differences
    belong to that earlier proof, not to the strict fragment comparison.
    """
    def __init__(self, root, source_sha, cleaning_sha, *, max_open=4):
        assert isinstance(max_open, int) and max_open > 0
        self.directory = root / 'tmp/export-parts/pages' / digest((source_sha + cleaning_sha).encode())
        self.documents = OrderedDict()
        self.verified = {}
        self.max_open = max_open

    def page(self, number):
        assert isinstance(number, int) and not isinstance(number, bool) and number >= 0
        if number in self.documents:
            self.documents.move_to_end(number)
            return self.documents[number][0]
        path = self.directory / f'{number}.pdf'
        stamp_path = path.with_suffix('.json')
        assert path.is_file() and stamp_path.is_file(), (
            'Missing current verified clean page; run build_export_parts.py and retain its page cache', path)
        raw = path.read_bytes()
        stamp = json.loads(stamp_path.read_text(encoding='utf8'))
        assert isinstance(stamp, dict) and stamp.get('sourcePage') == number, ('clean page identity', path)
        assert stamp.get('sha256') == digest(raw), ('clean page sha256', path)
        delta = stamp.get('render_max_delta')
        assert (isinstance(delta, (int, float)) and not isinstance(delta, bool)
                and math.isfinite(delta) and 0 <= delta <= 8), (
            'clean page has no successful full-page verification', path, delta)
        if len(self.documents) >= self.max_open:
            _, evicted = self.documents.popitem(last=False)
            evicted.close()
        doc = fitz.open(stream=raw, filetype='pdf')
        if len(doc) != 1:
            doc.close()
            raise AssertionError(('clean page count', path))
        self.documents[number] = doc
        self.verified[number] = {'sourcePage': number, 'sha256': stamp['sha256'],
                                 'renderMaxDelta': delta,
                                 'initialMaxDelta': stamp.get('render_initial_max_delta', delta)}
        return doc[0]

    def close(self):
        for doc in self.documents.values():
            doc.close()
        self.documents.clear()


class CharacterPaints(fitz.mupdf.FzDevice2):
    def __init__(self, rect):
        super().__init__()
        self.rect = fitz.Rect(rect)
        self.counts = Counter()
        self.error = None
        self.use_virtual_fill_text()
        self.use_virtual_stroke_text()

    def contains(self, box):
        # Rect.contains(empty) treats zero-advance glyphs as an empty set. Keep
        # their actual position bounded, including spaces and Unicode tails.
        return (self.rect.x0 <= box.x0 <= box.x1 <= self.rect.x1 and
                self.rect.y0 <= box.y0 <= box.y1 <= self.rect.y1)

    def fill_text(self, ctx, text, ctm, *args):
        self.capture(text, ctm)

    def stroke_text(self, ctx, text, stroke, ctm, *args):
        self.capture(text, ctm)

    def capture(self, text, matrix):
        if self.error is not None:
            return
        try:
            self._capture(text, matrix)
        except Exception as error:
            # Exceptions raised through SWIG callbacks can be swallowed by
            # library builds; retain and raise after the run has returned.
            self.error = error

    def _capture(self, text, matrix):
        m = fitz.mupdf
        ctm = m.FzMatrix(matrix)
        raw = text.head
        while raw:
            span = m.FzTextSpan(raw)
            mat = m.fz_concat(span.trm(), ctm)
            direction = m.fz_transform_vector(m.fz_make_point(1, 0), mat)
            size = math.hypot(direction.x, direction.y)
            direction = m.fz_normalize_vector(direction)
            ascender = m.fz_font_ascender(span.font())
            descender = m.fz_font_descender(span.font())
            if ascender < 1e-3:
                ascender, descender = .9, -.1
            if not all(math.isfinite(x) for x in (size, ascender, descender)) or ascender == descender:
                raise ValueError('Invalid glyph metrics')
            ascsize = ascender * size / (ascender - descender)
            dscsize = descender * size / (ascender - descender)
            rotation = m.fz_make_matrix(direction.x, direction.y, -direction.y, direction.x, 0, 0)
            if direction.x == -1:
                rotation.d = 1
            previous_box = None
            for index in range(raw.len):
                item = span.items(index)
                if item.gid < 0:
                    if previous_box is None:
                        raise ValueError('Unicode continuation has no preceding glyph')
                    if self.contains(previous_box):
                        char = chr(item.ucs) if 0 <= item.ucs <= 0x10ffff else f'<unicode:{item.ucs}>'
                        self.counts[char] += 1
                    continue
                advance = 0
                if item.gid >= 0:
                    count = span.font().m_internal.glyph_count
                    if count > 0 and item.gid >= count:
                        raise ValueError(f'Drawn GID {item.gid} is outside font glyph count {count}')
                    # Do not catch or clear renderer warnings: a genuinely
                    # invalid drawn GID must remain fatal in the caller.
                    advance = m.fz_advance_glyph(span.font(), item.gid, raw.wmode) * size
                origin = m.fz_transform_point(m.fz_make_point(item.x, item.y), ctm)
                transform = m.fz_make_matrix(1, 0, 0, 1, -origin.x, -origin.y)
                transform = m.fz_concat(transform, rotation)
                transform = m.fz_concat(transform, m.FzMatrix(1, 0, 0, 1, origin.x, origin.y))
                if (mat.d > 0 and direction.x in (1, -1)) or (mat.b != 0 and mat.b == -mat.c):
                    y0, y1 = origin.y + dscsize, origin.y + ascsize
                else:
                    y0, y1 = origin.y - ascsize, origin.y - dscsize
                box = m.fz_transform_rect(m.fz_make_rect(origin.x, y0, origin.x + advance, y1), transform)
                values = (box.x0, box.y0, box.x1, box.y1)
                if not all(math.isfinite(value) for value in values):
                    raise ValueError('Nonfinite character rectangle')
                previous_box = fitz.Rect(values)
                if self.contains(previous_box):
                    char = chr(item.ucs) if 0 <= item.ucs <= 0x10ffff else f'<unicode:{item.ucs}>'
                    self.counts[char] += 1
            raw = raw.next


def characters(page, rect):
    """Count each fill/stroke occurrence; ignore invisible text and clipping."""
    m = fitz.mupdf
    rotation = page.rotation
    if rotation:
        page.set_rotation(0)
    device = CharacterPaints(rect)
    try:
        try:
            m.fz_run_page(page.this, device, m.FzMatrix(), m.FzCookie())
        finally:
            m.fz_close_device(device)
        if device.error is not None:
            raise device.error
        return device.counts
    finally:
        if rotation:
            page.set_rotation(rotation)


def metric_warning_pairs(warnings, *, source=False):
    """Only this metrics diagnostic can be proved inherited, never parser errors."""
    pairs = set()
    previous = False
    for line in warnings.splitlines():
        match = re.fullmatch(r'bogus font ascent/descent values \((-?\d+) / (-?\d+)\)', line)
        if match:
            pairs.add(tuple(map(int, match.groups())))
            previous = True
        elif previous and re.fullmatch(r'\.\.\. repeated \d+ times\.\.\.', line):
            previous = False
        elif source:
            # Original pages can also contain unrelated legacy warnings. They
            # are reported verbatim but authorize no output warning exception.
            previous = False
        else:
            raise AssertionError(('Unproved PDF parser/font warning', warnings))
    return pairs


def metric_font_evidence(reader, number, pairs):
    """Identify metrics separately from the embedded program checked by render QA."""
    found, visited = {}, set()

    def canonical(value):
        value = value.get_object() if hasattr(value, 'get_object') else value
        if isinstance(value, StreamObject):
            return {'streamSha256': digest(value.get_data()),
                    'attributes': {str(key): canonical(item) for key, item in value.items()
                                   if key not in ('/Length', '/Filter', '/DecodeParms')}}
        if isinstance(value, DictionaryObject):
            return {str(key): canonical(item) for key, item in value.items()}
        if isinstance(value, (ArrayObject, list, tuple)):
            return [canonical(item) for item in value]
        if isinstance(value, NullObject):
            return None
        if isinstance(value, bytes):
            return {'hex': value.hex()}
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
        if isinstance(value, (str, bool)) or value is None:
            return value
        raise AssertionError(('Unsupported font descriptor value', type(value).__name__))

    def visit(value):
        if isinstance(value, IndirectObject):
            key = (id(value.pdf), value.idnum, value.generation)
        else:
            key = id(value)
        if key in visited:
            return
        visited.add(key)
        value = value.get_object() if hasattr(value, 'get_object') else value
        if isinstance(value, DictionaryObject):
            if '/FontDescriptor' in value:
                descriptor = value['/FontDescriptor'].get_object()
                pair = (float(descriptor.get('/Ascent', 0)), float(descriptor.get('/Descent', 0)))
                if pair in pairs:
                    programs = {key: digest(descriptor[key].get_object().get_data())
                                for key in ('/FontFile', '/FontFile2', '/FontFile3') if key in descriptor}
                    assert programs, ('Metrics warning has no embedded font program', pair)
                    metrics = canonical(DictionaryObject({key: item for key, item in descriptor.items()
                        if key not in ('/Type', '/FontFile', '/FontFile2', '/FontFile3', '/CIDSet')}))
                    # Subsetting changes program bytes and may rename a subset.
                    # This proof only explains the inherited descriptor warning;
                    # the independent text/pixel checks still audit actual glyphs.
                    metrics['/FontName'] = re.sub(r'^[A-Z]{6}\+', '', str(descriptor.get('/FontName', '')).lstrip('/'))
                    metrics['/BaseFont'] = re.sub(r'^[A-Z]{6}\+', '', str(value.get('/BaseFont', '')).lstrip('/'))
                    metrics['/Subtype'] = str(value.get('/Subtype', ''))
                    identity = digest(json.dumps(metrics, sort_keys=True, separators=(',', ':')).encode())
                    program_id = digest(json.dumps(programs, sort_keys=True).encode())
                    found[(identity, program_id)] = {'fontName': metrics['/FontName'], 'metrics': list(pair),
                        'fontPrograms': programs, 'metricsSha256': identity, 'descriptorMetrics': metrics}
            for item in value.values():
                visit(item)
        elif isinstance(value, (ArrayObject, list, tuple)):
            for item in value:
                visit(item)
    visit(reader.pages[number]['/Resources'])
    return found


class FontWarningSource:
    """Lazy original-page evidence; constructed only for a verified source file."""
    def __init__(self, source):
        self.source = source
        self.raw = None
        self.reader = None
        self.pages = {}

    def page(self, number):
        if number not in self.pages:
            if self.raw is None:
                self.raw = self.source if isinstance(self.source, bytes) else self.source.read_bytes()
                self.reader = PdfReader(BytesIO(self.raw))
            fitz.TOOLS.store_shrink(100)
            fitz.TOOLS.mupdf_warnings(reset=True)
            with fitz.open(stream=self.raw, filetype='pdf') as doc:
                doc[number].get_text()
            warnings = fitz.TOOLS.mupdf_warnings(reset=True)
            pairs = metric_warning_pairs(warnings, source=True)
            self.pages[number] = (warnings, pairs, metric_font_evidence(self.reader, number, pairs))
        return self.pages[number]

    def prove(self, raw, number, source_number, warnings):
        pairs = metric_warning_pairs(warnings)
        reference_warning, reference_pairs, reference = self.page(source_number)
        assert pairs <= reference_pairs, ('New font metrics warning', number, warnings, reference_warning)
        actual = metric_font_evidence(PdfReader(BytesIO(raw)), number, pairs)
        actual_pairs = {tuple(item['metrics']) for item in actual.values()}
        reference_ids = {item['metricsSha256'] for item in reference.values()}
        assert pairs <= actual_pairs and actual and all(item['metricsSha256'] in reference_ids for item in actual.values()), (
            'Font metrics/family differ from source', number, warnings,
            list(actual.values()), list(reference.values()))
        fonts = []
        for item in actual.values():
            source_programs = [old['fontPrograms'] for old in reference.values()
                               if old['metricsSha256'] == item['metricsSha256']]
            fonts.append({**item, 'sourceFontPrograms': source_programs,
                          'programUnchanged': item['fontPrograms'] in source_programs})
        return {'page': number, 'sourcePage': source_number, 'warnings': warnings,
                'sourceWarnings': reference_warning, 'proofScope': 'inherited font descriptor metrics only',
                'fonts': fonts}



def inventory(path, metadata, *, warning_source=None, source_pages=None):
    raw = path.read_bytes()
    assert len(raw) == metadata['bytes'], ('bytes', path)
    assert digest(raw) == metadata['sha256'], ('sha256', path)
    fonts, forms, warnings_by_page = {}, [], []
    fitz.TOOLS.store_shrink(100)
    fitz.TOOLS.mupdf_warnings(reset=True)
    with fitz.open(stream=raw, filetype='pdf') as doc:
        for n in range(1, doc.xref_length()):
            obj = doc.xref_object(n)
            if re.search(r'/Subtype\s*/Form\b', obj):
                forms.append(n)
            for ref in re.findall(r'/FontFile(?:2|3)?\s+(\d+)\s+0\s+R', obj):
                ref = int(ref)
                fonts[ref] = doc.xref_stream_raw(ref)
        assert not forms, ('Nested/clipped page Form remains', path, forms)
        warnings = fitz.TOOLS.mupdf_warnings(reset=True)
        assert not warnings, ('PDF parser warnings', path, warnings)
        page_count = len(doc)
        text = []
        for number, page in enumerate(doc):
            text.append(page.get_text())
            warnings = fitz.TOOLS.mupdf_warnings(reset=True)
            if warnings:
                warnings_by_page.append((number, warnings))
    warnings = fitz.TOOLS.mupdf_warnings(reset=True)
    assert not warnings, ('PDF close/parser warnings', path, warnings)
    inherited = []
    for number, warnings in warnings_by_page:
        assert warning_source is not None and source_pages is not None, (
            'PDF parser/font warnings without original evidence', path, number, warnings)
        try:
            inherited.append(warning_source.prove(raw, number, source_pages[number], warnings))
        except AssertionError as exc:
            raise AssertionError(('PDF parser/font warnings', path, number, warnings, str(exc))) from exc
    hashes = Counter(digest(blob) for blob in fonts.values())
    return {'bytes': len(raw), 'pages': page_count, 'fontBytes': sum(map(len, fonts.values())),
            'fontPrograms': len(fonts), 'duplicateFontPrograms': sum(n - 1 for n in hashes.values()),
            'text': '\n'.join(text), 'inheritedWarnings': inherited}


def compare_band(source, part, n, band, *, scale=2):
    """Restore the source media box, retaining the fragment's actual operators.

    This aligns both renders on the same pixel grid, including fractional band
    edges, so typography and chemistry can be compared without OCR guesses.
    """
    fitz.TOOLS.mupdf_warnings(reset=True)
    with fitz.open() as placed:
        placed.insert_pdf(part, from_page=n, to_page=n)
        page = placed[0]
        page.set_mediabox(source.mediabox)
        rect = fitz.Rect(band['box'])
        # Inline PDF font dictionaries can share a MuPDF store key across
        # documents. Render each side with an empty store so a damaged font
        # cannot silently borrow the reference document's font program.
        fitz.TOOLS.store_shrink(100)
        expected_text = characters(source, rect)
        left = source.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
        reference_warnings = fitz.TOOLS.mupdf_warnings(reset=True)
        fitz.TOOLS.store_shrink(100)
        fitz.TOOLS.mupdf_warnings(reset=True)
        actual_text = characters(page, rect)
        right = page.get_pixmap(matrix=fitz.Matrix(scale, scale), clip=rect, alpha=False)
        warnings = fitz.TOOLS.mupdf_warnings(reset=True)
        inherited = []
        metric_warning_pairs(reference_warnings)
        if warnings:
            original = FontWarningSource(source.parent.tobytes(garbage=1))
            inherited.append(original.prove(placed.tobytes(garbage=1), 0, source.number, warnings))
        assert (left.width, left.height, left.n) == (right.width, right.height, right.n), ('render dimensions', n)
        a = Image.frombytes('RGB', (left.width, left.height), left.samples)
        b = Image.frombytes('RGB', (right.width, right.height), right.samples)
        histogram = ImageChops.difference(a, b).histogram()
        total = sum(histogram)
        return {'mae': sum((i % 256) * count for i, count in enumerate(histogram)) / total,
                'fractionOver32': sum(count for i, count in enumerate(histogram) if i % 256 > 32) / total,
                'maxDelta': max(i % 256 for i, count in enumerate(histogram) if count),
                'textEqual': expected_text == actual_text,
                'missingCharacters': dict(expected_text - actual_text),
                'extraCharacters': dict(actual_text - expected_text),
                'warnings': '', 'referenceWarnings': reference_warnings, 'inheritedWarnings': inherited}


def validate_book(job):
    # Paths and immutable code/version identities travel with each job. This
    # also keeps spawned Windows workers independent of caller module globals.
    root, parts, book, book_version, cleaning_sha, build_sha, args = job
    report = {'books': [], 'parts': [], 'renderChecks': [], 'errors': []}
    manifest_path = parts / (book.stem + '.json')
    if not manifest_path.exists():
        assert args.allow_incomplete, ('missing manifest', manifest_path)
        return report
    manifest = json.loads(manifest_path.read_text(encoding='utf8'))
    source_sha = digest(book.read_bytes())
    assert manifest['sourceSha256'] == source_sha, ('stale source', book)
    assert manifest['bookVersion'] == book_version, ('stale version', manifest_path)
    slug, kind = book.stem.rsplit('-', 1)
    index_path = root / 'dist/export-index' / (slug + ('-answers' if kind == 'answers' else '') + '.json')
    index = json.loads(index_path.read_text(encoding='utf8'))
    index_sha = digest(index_path.read_bytes())
    assert manifest['indexSha256'] == index_sha, ('stale index', manifest_path)
    check_build_signature(manifest, source_sha, index_sha, build_sha)
    ids = set(manifest['questions'])
    assert ids <= set(index['questions'])
    if not args.allow_incomplete:
        assert manifest['complete'] and ids == set(index['questions']), ('incomplete topic', manifest_path)
    with fitz.open(book) as source_book:
        source_count = len(source_book)
    warning_source = FontWarningSource(book)
    book_report = {'book': book.name, 'complete': manifest['complete'], 'count': len(ids)}
    if manifest.get('cleanBook'):
        clean = manifest['cleanBook']
        clean_stats = inventory(parts / clean['path'], clean, warning_source=warning_source, source_pages=list(range(source_count)))
        assert clean_stats['pages'] == clean['pages'] == source_count, ('clean book page count', book)
        assert len(clean_stats.pop('text').strip()) > 100, ('clean book lost searchable text', book)
        book_report['cleanBook'] = clean_stats
    elif manifest['complete'] and not args.allow_incomplete:
        raise AssertionError(('complete manifest has no cleanBook', manifest_path))
    report['books'].append(book_report)
    frame = inventory(parts / manifest['frame']['path'], manifest['frame'], warning_source=warning_source, source_pages=[0, 0])
    assert frame['pages'] == 2
    assert not re.search(r'第\s*\d+\s*题', frame['text']), ('question leaked into frame', book)
    source_pages = ValidatedCleanPages(root, source_sha, cleaning_sha)
    try:
        first_id = next(iter(manifest['questions']))
        for qid, metadata in manifest['questions'].items():
            path = parts / metadata['path']
            assert path.resolve().is_relative_to(parts.resolve())
            stats = inventory(path, metadata, warning_source=warning_source, source_pages=[p['sourcePage'] for p in metadata['pages']])
            text = stats.pop('text')
            assert stats['pages'] == len(metadata['pages']), ('page count', path)
            assert sum(len(r['bands']) for r in metadata['regions']) == stats['pages']
            stats.update(id=qid, kind=kind, path=metadata['path'])
            report['parts'].append(stats)
            if qid == 'chemy39-5-4':
                assert not re.search(r'(?<!\d)4-(?:1|2|3)(?:-\d+)*', text), ('hidden original numbering', path)
                assert not re.search(r'第\s*2\s*题', text), ('neighbor heading leaked', path)
                assert stats['bytes'] < 1024 * 1024, ('single polymer fragment remains over 1 MiB', stats)
            if args.all_renders or qid == first_id or qid == 'chemy39-5-4':
                with fitz.open(path) as part:
                    for n, band in enumerate(metadata['pages']):
                        expected = fitz.Rect(band['box'])
                        assert abs(part[n].rect.width - expected.width) < .01
                        assert abs(part[n].rect.height - expected.height) < .01
                        assert 0 <= band['sourcePage'] < source_count, ('source page range', path)
                        try:
                            result = compare_band(source_pages.page(band['sourcePage']), part, n, band)
                        except Exception as exc:
                            context = {'book': book.name, 'path': str(path), 'id': qid,
                                       'page': n, 'sourcePage': band['sourcePage'], 'box': band['box']}
                            print('FAILED BAND', json.dumps(context, ensure_ascii=False), str(exc), flush=True)
                            failure = {**context, 'error': str(exc)}
                            report['renderChecks'].append(failure)
                            report['errors'].append(failure)
                            continue
                        result.update(id=qid, kind=kind, page=n, sourcePage=band['sourcePage'], box=band['box'])
                        report['renderChecks'].append(result)
                        if (result['warnings'] or not result['textEqual'] or result['mae'] > args.max_mae
                                or result['fractionOver32'] > args.max_changed_fraction or result['maxDelta'] > args.max_delta):
                            report['errors'].append(result)
        book_report['cleanReferenceCache'] = source_pages.directory.name
        book_report['cleanReferences'] = list(source_pages.verified.values())
    finally:
        source_pages.close()
    print('CHECKED', book.name, len(ids), 'parts', flush=True)
    return report


def worker_count(args, books):
    # Programmatic legacy Namespaces have no jobs field and remain serial.
    jobs = getattr(args, 'jobs', 1)
    if jobs is None:
        jobs = min(4, os.cpu_count() or 1) if args.all_renders else 1
    if not isinstance(jobs, int) or isinstance(jobs, bool) or jobs < 1:
        raise ValueError('--jobs must be a positive integer')
    return min(jobs, max(1, books))


def validate(args):
    cleaning_sha, build_sha = code_digests(ROOT)
    report = {'reference': 'validated-clean-page', 'cleaningSha256': cleaning_sha,
              'buildCodeSha256': build_sha, 'books': [], 'parts': [], 'renderChecks': [], 'errors': []}
    numbering = json.loads((ROOT / 'dist/numbering.json').read_text(encoding='utf8'))
    source_books = sorted((ROOT / 'dist/downloads').glob('*.pdf'))
    jobs = [(ROOT, PARTS, book, numbering['pdfVersion'], cleaning_sha, build_sha, args)
            for book in source_books]
    workers = worker_count(args, len(jobs))
    print('VERIFYING', len(jobs), 'books with', workers, 'processes', flush=True)

    def collect(results):
        for result in results:
            for key in ('books', 'parts', 'renderChecks', 'errors'):
                report[key].extend(result[key])

    if workers == 1:
        collect(map(validate_book, jobs))
    else:
        # Spawn avoids inheriting MuPDF's process-global font/tile cache, also
        # on POSIX. map preserves source-book ordering and propagates failures.
        with ProcessPoolExecutor(max_workers=workers, mp_context=get_context('spawn')) as pool:
            collect(pool.map(validate_book, jobs))
    assert report['books'], 'No export fragments were found'
    assert code_digests(ROOT) == (cleaning_sha, build_sha), 'Production code changed during validation'
    if not args.allow_incomplete:
        assert len(report['books']) == len(source_books) == 18
    report['totals'] = {'books': len(report['books']), 'parts': len(report['parts']),
                        'bytes': sum(p['bytes'] for p in report['parts']),
                        'fontBytes': sum(p['fontBytes'] for p in report['parts']),
                        'maxPartBytes': max(p['bytes'] for p in report['parts']),
                        'renderedBands': len(report['renderChecks'])}
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf8', newline='\n')
    print(json.dumps(report['totals'], ensure_ascii=False))
    assert not report['errors'], ('Visible content differs; inspect render checks', report['errors'][:5])



def validate_downloads(args):
    """A successful download event does not prove that PDF bytes are valid."""
    directory = args.browser_report.parent
    browser = json.loads(args.browser_report.read_text(encoding='utf8'))
    assert browser['exports'], 'Browser produced no downloads'
    results = []
    for entry in browser['exports']:
        path = directory / entry['file']
        reader = PdfReader(path, strict=True)
        for page in reader.pages:
            streams = page.get('/Contents')
            if isinstance(streams, IndirectObject):
                streams = streams.get_object()
            if isinstance(streams, list):
                assert all(isinstance(stream, IndirectObject) for stream in streams), ('Illegal direct stream in /Contents array', path)
        fitz.TOOLS.mupdf_warnings(reset=True)
        with fitz.open(path) as doc:
            fitz.TOOLS.store_shrink(100)
            text = ''
            for page in doc:
                assert not page.get_xobjects(), ('Page Forms in browser export', path)
                pixels = page.get_pixmap(matrix=fitz.Matrix(1, 1), alpha=False)
                histogram = Image.frombytes('RGB', (pixels.width, pixels.height), pixels.samples).histogram()
                assert sum(count for i, count in enumerate(histogram) if i % 256 < 100) > 100, ('Blank output page', path)
                text += page.get_text()
            assert len(text.strip()) > 100, ('Missing searchable text', path)
            warnings = fitz.TOOLS.mupdf_warnings()
            results.append({'file': entry['file'], 'pages': len(doc), 'bytes': path.stat().st_size, 'textCharacters': len(text), 'forms': 0, 'warnings': warnings})
        if entry['ids'] == ['chemy39-5-4']:
            assert not re.search(r'(?<!\d)4-(?:1|2|3)(?:-\d+)*', text), ('hidden original numbering in browser export', path)
            assert not re.search(r'第\s*2\s*题', text), ('neighbor question in browser export', path)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(results, ensure_ascii=False, indent=2) + '\n', encoding='utf8', newline='\n')
    print(json.dumps(results, ensure_ascii=False))
    assert not any(item['warnings'] for item in results), ('PDF parser/render warnings', [(item['file'], item['warnings']) for item in results if item['warnings']])

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--downloads-only', action='store_true')
    parser.add_argument('--browser-report', type=Path, default=ROOT / 'work/export-validation/browser-report.json')
    parser.add_argument('--allow-incomplete', action='store_true')
    parser.add_argument('--all-renders', action='store_true')
    parser.add_argument('--jobs', type=int, default=None,
                        help='Book workers (default: up to 4 for --all-renders, otherwise 1)')
    parser.add_argument('--max-mae', type=float, default=.8)
    parser.add_argument('--max-delta', type=int, default=8)
    parser.add_argument('--max-changed-fraction', type=float, default=.01)
    parser.add_argument('--report', type=Path, default=ROOT / 'work/export-validation/parts-report.json')
    args = parser.parse_args()
    (validate_downloads if args.downloads_only else validate)(args)
