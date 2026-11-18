"""Regression checks for broken release snapshots, using small temporary fixtures."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from check_release import check, SLUGS, PART_PROFILE


class ReleaseCheckTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.bank = []
        display, numbers, print_index = {}, {}, {}
        pdf = b'%PDF-1.7\nfixture for metadata validation only\n'
        for topic, slug in SLUGS.items():
            qid = f'fixture-{slug}'
            html = '<p>Question or answer</p><img src="assets/figure.webp">'
            self.bank.append({'id': qid, 'topic': topic, 'body': html, 'answer': html})
            display[qid] = {'body': html, 'answer': html}
            numbers[qid] = 1
            for kind in ('questions', 'answers'):
                key = f'{slug}-{kind}'
                filename = slug + ('-answers' if kind == 'answers' else '')
                self.write(f'dist/downloads/{key}.pdf', pdf)
                self.save(f'dist/export-index/{filename}.json', {
                    'bookVersion': 'fixture-v1',
                    'questions': {qid: [{'page': 0, 'bands': [[96, 150], [160, 200]]}]},
                })
                self.save(f'data/continuous-books/{key}.json', {
                    'pages': 1, 'sha256': hashlib.sha256(pdf).hexdigest(),
                })
                print_index[key] = [{'id': qid, 'number': 1, 'firstPage': 1, 'lastPage': 1}]
        self.save('dist/questions.json', self.bank)
        self.save('dist/presentation.json', display)
        self.save('dist/numbering.json', {'version': 'fixture-v1', 'numberById': numbers,
                                        'countsByTopic': {topic: 1 for topic in SLUGS}})
        self.save('data/print_index.json', print_index)
        self.write('dist/assets/figure.webp', b'fixture image: existence check only')

    def write(self, name, contents):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(contents)

    def save(self, name, value):
        self.write(name, json.dumps(value, ensure_ascii=False).encode('utf-8'))

    def read(self, name):
        return json.loads((self.root / name).read_text(encoding='utf-8'))

    def assert_rejected(self, message, pdfs=False, parts=False):
        report = check(self.root, pdfs=pdfs, parts=parts)
        self.assertFalse(report['passed'], report)
        self.assertTrue(any(message in error for error in report['errors']), report)

    def test_consistent_snapshot_passes(self):
        report = check(self.root, pdfs=True)
        self.assertTrue(report['passed'], report)
        self.assertEqual(report['counts'], {'questions': 9, 'referencedImages': 1, 'books': 18})

    def test_stale_answer_index_is_rejected(self):
        name = 'dist/export-index/polymer-answers.json'
        index = self.read(name)
        index['bookVersion'] = 'old-pdf'
        self.save(name, index)
        self.assert_rejected('stale export index version')

    def test_missing_referenced_image_is_rejected(self):
        (self.root / 'dist/assets/figure.webp').unlink()
        self.assert_rejected('missing or nonlocal image')

    def test_swapped_answer_question_is_rejected(self):
        name = 'dist/export-index/polymer-answers.json'
        index = self.read(name)
        index['questions']['fixture-organic'] = index['questions'].pop('fixture-polymer')
        self.save(name, index)
        self.assert_rejected('export index IDs differ')

    def test_nonexistent_page_and_overlapping_bands_are_rejected(self):
        name = 'dist/export-index/polymer.json'
        index = self.read(name)
        index['questions']['fixture-polymer'] = [
            {'page': 0, 'bands': [[100, 200], [190, 210]]},
            {'page': 1, 'bands': [[96, 150]]},
        ]
        self.save(name, index)
        self.assert_rejected('export page out of bounds')
        self.assert_rejected('overlapping/unordered bands')

    def test_changed_pdf_with_stale_layout_is_rejected(self):
        name = 'dist/downloads/polymer-questions.pdf'
        self.write(name, (self.root / name).read_bytes() + b'changed bytes')
        self.assert_rejected('PDF bytes differ from layout', pdfs=True)

    def test_invalid_json_fails_cleanly(self):
        self.write('dist/export-index/polymer.json', b'{broken')
        self.assert_rejected('dist/export-index/polymer.json:')

    def test_duplicate_question_ids_are_rejected(self):
        self.bank.append(self.bank[0])
        self.save('dist/questions.json', self.bank)
        self.assert_rejected('duplicate IDs')

    def prepare_parts(self):
        code_files = ['build_export_parts.py', 'pdf_clip_cleanup.py', 'pdf_render_verify.py', 'pdf_font_subset.py',
                      'pdf_watermark.py', 'export-requirements.txt']
        for name in code_files:
            self.write('scripts/' + name, b'fixture build input')
        watermark = b'fixture watermark image'
        self.write('dist/assets/chemy-watermark.jpg', watermark)
        code_sha = hashlib.sha256(b'fixture build input' * len(code_files) + watermark).hexdigest()
        inventory = {'profile': PART_PROFILE, 'bookVersion': 'fixture-v1', 'books': {}}
        pdf = b'%PDF-1.7\nfixture part for metadata validation only\n'
        for slug in SLUGS.values():
            qid = 'fixture-' + slug
            for kind in ('questions', 'answers'):
                key = f'{slug}-{kind}'
                index_name = slug + ('-answers' if kind == 'answers' else '')
                book_sha = hashlib.sha256((self.root / f'dist/downloads/{key}.pdf').read_bytes()).hexdigest()
                index_sha = hashlib.sha256((self.root / f'dist/export-index/{index_name}.json').read_bytes()).hexdigest()
                signature = hashlib.sha256(json.dumps([PART_PROFILE, book_sha, index_sha, code_sha],
                                                      separators=(',', ':')).encode('utf-8')).hexdigest()
                def file_record(name):
                    self.write('dist/export-parts/' + name, pdf)
                    return {'path': name, 'bytes': len(pdf), 'sha256': hashlib.sha256(pdf).hexdigest()}
                frame = file_record(key + '-frame.pdf')
                clean_book = {**file_record(key + '-book.pdf'), 'pages': 1}
                part = file_record(f'{slug}/{qid}-{kind}.pdf')
                part['pages'] = [{'sourcePage': 0, 'box': [0, top, 595, bottom]}
                                 for top, bottom in [[96, 150], [160, 200]]]
                part['regions'] = [{'sourcePage': 0, 'bands': [
                    {'page': 0, 'top': 96, 'bottom': 150, 'width': 595},
                    {'page': 1, 'top': 160, 'bottom': 200, 'width': 595},
                ]}]
                self.save(f'dist/export-parts/{key}.json', {
                    'profile': PART_PROFILE, 'bookVersion': 'fixture-v1', 'signature': signature,
                    'sourceBook': f'downloads/{key}.pdf', 'sourceSha256': book_sha,
                    'indexSha256': index_sha, 'complete': True, 'frame': frame, 'cleanBook': clean_book,
                    'questions': {qid: part},
                })
                inventory['books'][key] = {'complete': True, 'count': 1, 'sourceSha256': book_sha}
        self.save('dist/export-parts/manifest.json', inventory)

    def test_complete_generated_parts_pass(self):
        self.prepare_parts()
        report = check(self.root, pdfs=True, parts=True)
        self.assertTrue(report['passed'], report)
        self.assertTrue(report['partsChecked'])
        self.assertEqual(report['counts']['partFiles'], 54)

    def test_generated_parts_reject_incomplete_build(self):
        self.prepare_parts()
        name = 'dist/export-parts/polymer-questions.json'
        manifest = self.read(name)
        manifest['complete'] = False
        self.save(name, manifest)
        self.assert_rejected('incomplete build', parts=True)

    def test_generated_parts_reject_unsafe_path(self):
        self.prepare_parts()
        name = 'dist/export-parts/polymer-questions.json'
        manifest = self.read(name)
        manifest['questions']['fixture-polymer']['path'] = '../../outside.pdf'
        self.save(name, manifest)
        self.assert_rejected('unsafe file path', parts=True)

    def test_generated_parts_reject_changed_index(self):
        self.prepare_parts()
        name = 'dist/export-index/polymer.json'
        index = self.read(name)
        index['changedAfterBuild'] = True
        self.save(name, index)
        self.assert_rejected('source index SHA-256 differs', parts=True)

    def test_generated_parts_reject_changed_build_rule(self):
        self.prepare_parts()
        self.write('scripts/pdf_clip_cleanup.py', b'new cleanup rule')
        self.assert_rejected('stale build signature', parts=True)

    def test_generated_parts_reject_corrupted_part(self):
        self.prepare_parts()
        name = 'dist/export-parts/polymer/fixture-polymer-answers.pdf'
        self.write(name, (self.root / name).read_bytes() + b'changed')
        self.assert_rejected('PDF SHA-256 differs', parts=True)

    def test_generated_parts_reject_wrong_page_count(self):
        self.prepare_parts()
        name = 'dist/export-parts/polymer-questions.json'
        manifest = self.read(name)
        manifest['questions']['fixture-polymer']['pages'].pop()
        self.save(name, manifest)
        self.assert_rejected('page metadata count differs', parts=True)

    def test_generated_parts_reject_changed_geometry(self):
        self.prepare_parts()
        name = 'dist/export-parts/polymer-questions.json'
        manifest = self.read(name)
        manifest['questions']['fixture-polymer']['pages'][0]['box'][1] = 95
        self.save(name, manifest)
        self.assert_rejected('page geometry differs', parts=True)

    def test_generated_parts_require_clean_topic_books(self):
        self.prepare_parts()
        name = 'dist/export-parts/polymer-questions.json'
        manifest = self.read(name)
        del manifest['cleanBook']
        self.save(name, manifest)
        self.assert_rejected('cleanBook: invalid file metadata', parts=True)

    def test_generated_parts_require_correct_clean_book_page_count(self):
        self.prepare_parts()
        name = 'dist/export-parts/polymer-questions.json'
        manifest = self.read(name)
        manifest['cleanBook']['pages'] = 2
        self.save(name, manifest)
        self.assert_rejected('clean topic book page count differs', parts=True)


if __name__ == '__main__':
    unittest.main()
