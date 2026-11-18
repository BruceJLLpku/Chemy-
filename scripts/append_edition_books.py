"""Append new native chapters without changing earlier question numbers or page positions."""
import argparse
import hashlib
import json
import os
import shutil
from concurrent.futures import ProcessPoolExecutor
from io import BytesIO
from pathlib import Path

from fast_pdf import ROOT, merge_parts, page_count, pikepdf, share_streams
from build_continuous_books import flow_book, sync_pdf_version
from paper1_manifest import SLUGS
from pdf_typography import frame
from source_info import source_name

DIST = ROOT / 'dist'
DATA = ROOT / 'data'
FRAME = b'q /ChemyPageFrame Do Q\n'


def read(path):
    return json.loads(path.read_text(encoding='utf8'))


def write(path, data, **kwargs):
    path.write_text(json.dumps(data, ensure_ascii=False, **kwargs), encoding='utf8')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def streams(page):
    contents = page.obj['/Contents']
    return list(contents) if isinstance(contents, pikepdf.Array) else [contents]


def shifted(rows, **offsets):
    return [row | {key: row[key] + offset for key, offset in offsets.items()} for row in rows]


def append_book(job):
    topic, slug, kind, edition, scratch = job
    key = f'{slug}-{kind}'
    pdf_name = key + '.pdf'
    index_name = (slug if kind == 'questions' else key) + '.json'
    legacy_path = DIST / 'downloads' / pdf_name
    legacy = read(DATA / 'continuous-books' / (key + '.json'))
    index = read(DIST / 'export-index' / index_name)
    bank = [q for q in read(DIST / 'questions.json') if q['topic'] == topic]
    numbers = read(DIST / 'numbering.json')['numberById']
    new = [q for q in bank if q.get('edition', 39) == edition]
    old = [q for q in bank if q.get('edition', 39) != edition]
    assert [row['id'] for row in legacy['records']] == [q['id'] for q in old], key
    assert legacy['sha256'] == digest(legacy_path), key
    assert set(index['questions']) == set(legacy['questions']), key
    assert [numbers[q['id']] for q in bank] == list(range(1, len(bank) + 1)), key

    records, paths, count = [], [], 0
    parts = Path(os.environ.get('CHEMY_PDF_PARTS') or ROOT / 'tmp/library/books')
    for paper in sorted({q['paper'] for q in new}):
        part = parts / f'e{edition}-{paper:02}-{slug}-{kind[0]}.pdf'
        records.extend(shifted(read(part.with_suffix('.json')), firstPage=count, lastPage=count))
        paths.append(part)
        count += page_count(part)
    assert [r['id'] for r in records] == [q['id'] for q in new], key
    assert all(numbers[r['id']] == r['number'] for r in records), key

    raw = scratch / 'raw' / pdf_name
    addon = scratch / 'addon' / pdf_name
    target = scratch / 'final' / pdf_name
    assert merge_parts(paths, records, raw, {}) == count, key
    flow_book(raw, records, topic, slug, kind, addon, layout_dir=scratch / 'layout')
    addition = read(scratch / 'layout' / (key + '.json'))
    offset = legacy['pages']
    page_total = offset + addition['pages']
    ledger = legacy['records'] + shifted(addition['records'], firstPage=offset, lastPage=offset)
    source_offset = legacy['sourcePages']
    addon_index = {qid: shifted(regions, page=offset) for qid, regions in addition['questions'].items()}
    index['questions'].update(addon_index)

    with pikepdf.open(legacy_path) as base, pikepdf.open(addon) as extra, pikepdf.Pdf.new() as out:
        assert len(base.pages) == offset and len(extra.pages) == addition['pages'], key
        for name, value in base.docinfo.items():
            out.docinfo[name] = str(value)
        out.pages.extend(base.pages)
        out.pages.extend(extra.pages)
        frame_commands = out.make_stream(FRAME)
        for i, page in enumerate(out.pages):
            content = streams(page)
            assert len(content) >= 3 and content[-1].get('/ChemyWatermark'), (key, i)
            if i < offset:
                assert content[0].read_bytes() == FRAME, (key, i)
            resources = pikepdf.Dictionary(page.obj['/Resources'])
            objects = pikepdf.Dictionary(resources['/XObject'])
            with pikepdf.open(BytesIO(frame(topic, kind, len(bank), i + 1, page_total))) as cover:
                objects['/ChemyPageFrame'] = out.copy_foreign(cover.pages[0].as_form_xobject())
            resources['/XObject'] = objects
            page.obj['/Resources'] = resources
            page.obj['/Contents'] = pikepdf.Array([frame_commands, *content[1:]])
        with out.open_outline() as outline:
            for entry in ledger:
                source = source_name(entry['sourceEdition'], entry['sourcePaper'], compact=True)
                title = f'第{entry["number"]}题 · {source}原第{entry["sourceNumber"]}题'
                outline.root.append(pikepdf.OutlineItem(title, entry['firstPage'] - 1))
        share_streams(out)
        out.save(target, compress_streams=True, object_stream_mode=pikepdf.ObjectStreamMode.generate,
                 deterministic_id=True)
        with pikepdf.open(target) as check:
            assert len(check.pages) == page_total
            for original, updated in zip((*base.pages, *extra.pages), check.pages):
                assert [s.read_bytes() for s in streams(original)[1:]] == [
                    s.read_bytes() for s in streams(updated)[1:]], key
            with check.open_outline() as outline:
                assert len(outline.root) == len(bank), key
    assert target.stat().st_size < 100 * 1024**2, target
    layout = legacy | {
        'pages': page_total, 'sha256': digest(target), 'sourcePages': source_offset + count,
        'appendedSources': legacy.get('appendedSources', []) + [
            {'edition': edition, 'sourceSha256': addition['sourceSha256'], 'firstPage': offset + 1}],
        'records': ledger, 'heads': legacy['heads'] + shifted(addition['heads'], page=offset),
        'placements': legacy['placements'] + shifted(addition['placements'], page=offset, sourcePage=source_offset),
        'questions': legacy['questions'] | addon_index,
    }
    write(scratch / 'final-layout' / (key + '.json'), layout, separators=(',', ':'))
    write(scratch / 'final-index' / index_name, index, separators=(',', ':'))
    print(key, f'{len(new)} new questions, {offset} → {page_total} pages', flush=True)
    return key, index_name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--edition', type=int, required=True)
    parser.add_argument('--scratch', type=Path, required=True)
    parser.add_argument('--workers', type=int, default=3)
    args = parser.parse_args()
    for subdir in ('raw', 'addon', 'final', 'final-layout', 'final-index'):
        (args.scratch / subdir).mkdir(parents=True, exist_ok=True)
    jobs = [(topic, slug, kind, args.edition, args.scratch)
            for topic, slug in SLUGS.items() for kind in ('questions', 'answers')]
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        built = list(pool.map(append_book, jobs))
    ledger = read(DATA / 'print_index.json')
    for key, index_name in built:
        pdf = args.scratch / 'final' / (key + '.pdf')
        layout = args.scratch / 'final-layout' / (key + '.json')
        index = args.scratch / 'final-index' / index_name
        ledger[key] = read(layout)['records']
        for src, dest in [(pdf, DIST / 'downloads' / pdf.name),
                          (layout, DATA / 'continuous-books' / layout.name),
                          (index, DIST / 'export-index' / index.name)]:
            temporary = dest.with_suffix('.edition.tmp')
            shutil.copyfile(src, temporary)
            temporary.replace(dest)
    write(DATA / 'print_index.json', ledger, indent=2)
    sync_pdf_version()


if __name__ == '__main__':
    main()
