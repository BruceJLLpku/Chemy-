"""Check the committed website snapshot without ingestion caches or PDF libraries.

This checks references and release metadata, not chemical correctness or rendered
figure completeness. Pass --pdfs to also hash the 18 topic books against their
layout records, and --parts to verify a complete generated fragment inventory.
Fragment page counts are checked from metadata; use test_export_parts.py for
actual PDF structure and rendering. The check never changes its input files.
"""
import argparse
import hashlib
from collections import Counter
from html.parser import HTMLParser
import json
import math
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

from paper1_manifest import SLUGS

PART_PROFILE = 'clean-vector-v1'


def check_parts(root, version, wanted_by_slug, errors, counts):
    """Validate generated manifests and bytes; PDF semantics need PDF tests."""
    destination = (root / 'dist/export-parts').resolve()

    def require(condition, message):
        if not condition:
            errors.append('export-parts: ' + message)
        return condition

    def read(path):
        try:
            value = json.loads(path.read_text(encoding='utf-8'))
            if require(isinstance(value, dict), f'{path.name}: expected object'):
                return value
        except (OSError, ValueError) as exc:
            require(False, f'{path.name}: {exc}')
        return {}

    def digest(path):
        try:
            with path.open('rb') as stream:
                return hashlib.file_digest(stream, 'sha256').hexdigest()
        except OSError as exc:
            require(False, f'{path.name}: {exc}')
            return None

    def check_file(metadata, expected, label):
        if not require(isinstance(metadata, dict), f'{label}: invalid file metadata'):
            return
        name = metadata.get('path')
        safe = (isinstance(name, str) and bool(name) and '\\' not in name and ':' not in name
                and not PurePosixPath(name).is_absolute() and '..' not in PurePosixPath(name).parts)
        if not require(safe, f'{label}: unsafe file path'):
            return
        path = (destination / name).resolve()
        if not require(path.is_relative_to(destination), f'{label}: file escapes export-parts'):
            return
        require(name == expected, f'{label}: unexpected file path')
        if not require(path.is_file(), f'{label}: missing PDF'):
            return
        require(type(metadata.get('bytes')) is int and metadata['bytes'] > 5
                and path.stat().st_size == metadata['bytes'], f'{label}: PDF byte count differs')
        require(digest(path) == metadata.get('sha256'), f'{label}: PDF SHA-256 differs')
        with path.open('rb') as stream:
            require(stream.read(5) == b'%PDF-', f'{label}: invalid PDF header')
        counts['partFiles'] += 1

    try:
        code_inputs = b''.join((root / 'scripts' / name).read_bytes() for name in
                              ['build_export_parts.py', 'pdf_clip_cleanup.py', 'pdf_render_verify.py', 'pdf_font_subset.py',
                               'pdf_watermark.py', 'export-requirements.txt'])
        code_sha = hashlib.sha256(code_inputs + (root / 'dist/assets/chemy-watermark.jpg').read_bytes()).hexdigest()
    except OSError as exc:
        require(False, f'build inputs unavailable: {exc}')
        return
    inventory = read(destination / 'manifest.json')
    require(inventory.get('profile') == PART_PROFILE, 'unsupported inventory profile')
    require(inventory.get('bookVersion') == version, 'stale inventory PDF version')
    inventory_books = inventory.get('books', {})
    if not require(isinstance(inventory_books, dict), 'invalid inventory books'):
        inventory_books = {}
    expected_books = {f'{slug}-{kind}' for slug in wanted_by_slug for kind in ('questions', 'answers')}
    require(set(inventory_books) == expected_books, 'inventory must contain all 18 books')
    for slug, wanted in wanted_by_slug.items():
        for kind in ('questions', 'answers'):
            key = f'{slug}-{kind}'
            metadata = read(destination / f'{key}.json')
            source = root / 'dist/downloads' / f'{key}.pdf'
            index_name = slug + ('-answers' if kind == 'answers' else '')
            index_path = root / 'dist/export-index' / f'{index_name}.json'
            index = read(index_path)
            book_sha, index_sha = digest(source), digest(index_path)
            require(metadata.get('profile') == PART_PROFILE, f'{key}: unsupported profile')
            require(metadata.get('bookVersion') == version, f'{key}: stale PDF version')
            require(metadata.get('sourceBook') == f'downloads/{key}.pdf', f'{key}: wrong source book')
            require(metadata.get('sourceSha256') == book_sha, f'{key}: source book SHA-256 differs')
            require(metadata.get('indexSha256') == index_sha, f'{key}: source index SHA-256 differs')
            signature = hashlib.sha256(json.dumps([PART_PROFILE, book_sha, index_sha, code_sha],
                                                  separators=(',', ':')).encode('utf-8')).hexdigest()
            require(metadata.get('signature') == signature, f'{key}: stale build signature')
            require(metadata.get('complete') is True, f'{key}: incomplete build')
            summary = inventory_books.get(key, {})
            if require(isinstance(summary, dict), f'{key}: invalid inventory summary'):
                require(summary.get('complete') is True and summary.get('count') == len(wanted)
                        and summary.get('sourceSha256') == book_sha, f'{key}: inventory summary differs')
            questions = metadata.get('questions', {})
            if not require(isinstance(questions, dict), f'{key}: invalid questions'):
                continue
            require(set(questions) == set(wanted), f'{key}: generated question IDs differ')
            check_file(metadata.get('frame'), f'{key}-frame.pdf', key + '/frame')
            clean_book = metadata.get('cleanBook')
            check_file(clean_book, f'{key}-book.pdf', key + '/cleanBook')
            layout = read(root / f'data/continuous-books/{key}.json')
            if isinstance(clean_book, dict):
                require(type(clean_book.get('pages')) is int and clean_book['pages'] == layout.get('pages'),
                        f'{key}: clean topic book page count differs')
            for qid in wanted:
                part = questions.get(qid)
                if not require(isinstance(part, dict), f'{key}/{qid}: missing question metadata'):
                    continue
                check_file(part, f'{slug}/{qid}-{kind}.pdf', key + '/' + qid)
                pages = part.get('pages')
                regions = part.get('regions')
                source_regions = index.get('questions', {}).get(qid, [])
                expected_count = sum(len(r['bands']) for r in source_regions)
                if not require(isinstance(pages, list) and len(pages) == expected_count and expected_count > 0,
                               f'{key}/{qid}: page metadata count differs from source bands'):
                    continue
                if not require(isinstance(regions, list) and len(regions) == len(source_regions),
                               f'{key}/{qid}: region count differs'):
                    continue
                offset = 0
                for region, original in zip(regions, source_regions):
                    if not require(isinstance(region, dict) and region.get('sourcePage') == original['page'],
                                   f'{key}/{qid}: region source page differs'):
                        continue
                    bands = region.get('bands')
                    if not require(isinstance(bands, list) and len(bands) == len(original['bands']),
                                   f'{key}/{qid}: region band count differs'):
                        continue
                    for band, (top, bottom) in zip(bands, original['bands']):
                        page = pages[offset]
                        valid = isinstance(page, dict) and isinstance(band, dict)
                        if require(valid, f'{key}/{qid}: invalid band/page metadata'):
                            box = page.get('box')
                            valid_box = (isinstance(box, list) and len(box) == 4
                                         and all(type(n) in (int, float) and math.isfinite(n) for n in box)
                                         and box[0] == 0 and box[2] > 0 and box[1] == top and box[3] == bottom)
                            require(valid_box and page.get('sourcePage') == original['page'],
                                    f'{key}/{qid}: page geometry differs from source band')
                            require(band.get('page') == offset and band.get('top') == top
                                    and band.get('bottom') == bottom and valid_box and band.get('width') == box[2],
                                    f'{key}/{qid}: region geometry differs from page metadata')
                        offset += 1
            counts['partBooks'] += 1


class Images(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sources = set()

    def handle_starttag(self, tag, attrs):
        if tag == 'img':
            self.sources.add(dict(attrs).get('src', ''))


def check(root, pdfs=False, parts=False):
    root = Path(root).resolve()
    dist = root / 'dist'
    errors = []
    counts = Counter()

    def require(condition, message):
        if not condition:
            errors.append(message)
        return condition

    def read(relative, expected):
        try:
            result = json.loads((root / relative).read_text(encoding='utf-8'))
            if require(isinstance(result, expected), f'{relative}: unexpected JSON type'):
                return result
        except (OSError, ValueError) as exc:
            errors.append(f'{relative}: {exc}')
        return expected()

    bank = read('dist/questions.json', list)
    display = read('dist/presentation.json', dict)
    numbering = read('dist/numbering.json', dict)
    print_index = read('data/print_index.json', dict)
    ids = [q.get('id') for q in bank if isinstance(q, dict)]
    valid_ids = all(isinstance(qid, str) and qid for qid in ids)
    require(len(ids) == len(bank) and valid_ids, 'questions: every entry needs a nonempty ID')
    if not valid_ids:
        return {'passed': False, 'counts': dict(counts), 'errors': errors}
    require(bool(ids), 'questions: empty bank')
    require(len(ids) == len(set(ids)), 'questions: duplicate IDs')
    require(set(display) == set(ids), 'presentation: IDs do not match questions')
    numbers = numbering.get('numberById', {})
    if not isinstance(numbers, dict):
        errors.append('numbering: numberById must be an object')
        numbers = {}
    require(set(numbers) == set(ids), 'numbering: IDs do not match questions')
    version = numbering.get('pdfVersion', numbering.get('version'))
    require(isinstance(version, str) and bool(version), 'numbering: missing PDF version')
    topic_counts = Counter(q.get('topic') for q in bank if isinstance(q, dict))
    require(set(topic_counts) <= set(SLUGS), 'questions: unknown topic')
    require(dict(topic_counts) == numbering.get('countsByTopic'), 'numbering: topic counts differ')
    images = Images()
    for q in bank:
        if not isinstance(q, dict):
            continue
        qid = q['id']
        shown = display.get(qid, {})
        if not require(isinstance(shown, dict), f'{qid}: invalid presentation entry'):
            continue
        for owner, entry in [('questions', q), ('presentation', shown)]:
            for field in ('body', 'answer'):
                text = entry.get(field)
                if require(isinstance(text, str) and bool(text.strip()), f'{owner}/{qid}: empty {field}'):
                    images.feed(text)
            if isinstance(entry.get('titleHtml'), str):
                images.feed(entry['titleHtml'])
    for source in sorted(images.sources):
        url = urlsplit(source)
        path = (dist / unquote(url.path)).resolve()
        local = not url.scheme and not url.netloc and path.is_relative_to(dist)
        require(local and path.is_file(), f'asset: missing or nonlocal image {source!r}')
    counts['questions'] = len(bank)
    counts['referencedImages'] = len(images.sources)
    for topic, slug in SLUGS.items():
        wanted = [q['id'] for q in bank if isinstance(q, dict) and q.get('topic') == topic]
        require([numbers.get(qid) for qid in wanted] == list(range(1, len(wanted) + 1)),
                f'{slug}: numbering is not consecutive in source order')
        for kind in ('questions', 'answers'):
            key = f'{slug}-{kind}'
            book = dist / 'downloads' / f'{key}.pdf'
            require(book.is_file() and book.stat().st_size > 5, f'{key}: missing/empty PDF')
            with_magic = book.open('rb') if book.is_file() else None
            if with_magic:
                with with_magic as stream:
                    require(stream.read(5) == b'%PDF-', f'{key}: invalid PDF header')
            filename = slug + ('-answers' if kind == 'answers' else '')
            index = read(f'dist/export-index/{filename}.json', dict)
            require(index.get('bookVersion') == version, f'{key}: stale export index version')
            regions = index.get('questions', {})
            if not require(isinstance(regions, dict), f'{key}: invalid question regions'):
                continue
            require(set(regions) == set(wanted), f'{key}: export index IDs differ')
            layout = read(f'data/continuous-books/{key}.json', dict)
            pages = layout.get('pages')
            if not require(type(pages) is int and pages > 0, f'{key}: invalid layout page count'):
                continue
            records = print_index.get(key, [])
            if not require(isinstance(records, list) and all(isinstance(r, dict) for r in records),
                           f'{key}: invalid print index'):
                records = []
            require([r.get('id') for r in records] == wanted, f'{key}: print index IDs/order differ')
            for record in records:
                first, last = record.get('firstPage'), record.get('lastPage')
                require(type(first) is int and type(last) is int and 1 <= first <= last <= pages,
                        f'{key}/{record.get("id")}: print pages out of bounds')
                require(record.get('number') == numbers.get(record.get('id')),
                        f'{key}/{record.get("id")}: print number differs')
            for qid, pieces in regions.items():
                if not require(isinstance(pieces, list) and bool(pieces), f'{key}/{qid}: empty regions'):
                    continue
                previous = (-1, 0)
                for piece in pieces:
                    if not require(isinstance(piece, dict), f'{key}/{qid}: invalid region'):
                        continue
                    page = piece.get('page')
                    valid_page = type(page) is int and 0 <= page < pages
                    require(valid_page, f'{key}/{qid}: export page out of bounds')
                    bands = piece.get('bands')
                    if not require(isinstance(bands, list) and bool(bands), f'{key}/{qid}: empty bands'):
                        continue
                    for band in bands:
                        valid = (isinstance(band, list) and len(band) == 2
                                 and all(type(n) in (int, float) and math.isfinite(n) for n in band)
                                 and 0 <= band[0] < band[1] <= 842)
                        if require(valid, f'{key}/{qid}: invalid A4 band {band!r}') and valid_page:
                            require((page, band[0]) >= previous, f'{key}/{qid}: overlapping/unordered bands')
                            previous = (page, band[1])
            if pdfs and book.is_file():
                with book.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                require(digest == layout.get('sha256'), f'{key}: PDF bytes differ from layout; rebuild its indexes')
            counts['books'] += 1
    if parts and not errors:
        wanted_by_slug = {slug: [q['id'] for q in bank if q['topic'] == topic] for topic, slug in SLUGS.items()}
        check_parts(root, version, wanted_by_slug, errors, counts)
    return {'passed': not errors, 'counts': dict(counts), 'pdfHashesChecked': pdfs,
            'partsChecked': parts and counts['partBooks'] == 18, 'errors': errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--pdfs', action='store_true', help='also verify all topic PDF byte hashes')
    parser.add_argument('--parts', action='store_true', help='verify a complete generated export-parts build')
    parser.add_argument('--report', type=Path, help='optional JSON report, e.g. output/release-check.json')
    args = parser.parse_args()
    report = check(args.root, args.pdfs, args.parts)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
