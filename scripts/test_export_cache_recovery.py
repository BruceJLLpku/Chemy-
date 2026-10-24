"""Exercise interrupted/corrupted manifest recovery with a tiny real PDF."""
from pathlib import Path
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch

import pymupdf as fitz
import build_export_parts as builder


class ExportCacheRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('scripts', 'dist/downloads', 'dist/export-index', 'dist/assets'):
            (self.root/name).mkdir(parents=True, exist_ok=True)
        for name in ('build_export_parts.py', 'pdf_clip_cleanup.py', 'pdf_render_verify.py',
                     'pdf_font_subset.py', 'pdf_watermark.py', 'export-requirements.txt'):
            shutil.copy2(builder.ROOT/'scripts'/name, self.root/'scripts'/name)
        shutil.copy2(builder.ROOT/'dist/assets/chemy-watermark.jpg', self.root/'dist/assets/chemy-watermark.jpg')
        with fitz.open() as doc:
            page = doc.new_page(width=595.28, height=841.89)
            page.insert_text((60, 110), 'Visible question one')
            page.insert_text((60, 180), 'Visible question two')
            doc.save(self.root/'dist/downloads/fixture-questions.pdf')
        index = {'bookVersion':'fixture', 'questions':{
            'question-one':[{'page':0, 'bands':[[80,130]]}],
            'question-two':[{'page':0, 'bands':[[150,210]]}]}}
        (self.root/'dist/export-index/fixture.json').write_text(json.dumps(index), encoding='utf8')
        self.dest, self.cache = self.root/'parts', self.root/'cache'
        self.manifest = self.dest/'fixture-questions.json'

    def build(self):
        with patch.object(builder, 'ROOT', self.root), patch.object(builder, 'DEST', self.dest), patch.object(builder, 'CACHE', self.cache):
            builder.build_book(('fixture', 'questions', ['question-one'], False))
        return json.loads(self.manifest.read_text(encoding='utf8'))

    def test_valid_part_repairs_corrupted_metadata_and_drops_unknown_entries(self):
        original = self.build()
        expected = dict(original['questions']['question-one'])
        part = self.dest/expected['path']
        raw = part.read_bytes()
        original['questions']['question-one'].update(path='wrong.pdf', bytes=1, pages=[], regions=[])
        original['questions']['unknown-question'] = expected
        original['questions']['question-two'] = ['invalid entry']
        original['frame'] = []
        self.manifest.write_text(json.dumps(original), encoding='utf8')
        actual = self.build()
        self.assertEqual(actual['questions'], {'question-one':expected})
        self.assertFalse(actual['complete'])
        self.assertEqual(part.read_bytes(), raw)
        self.assertEqual(actual['frame']['bytes'], (self.dest/actual['frame']['path']).stat().st_size)

    def test_invalid_questions_and_wrong_page_stamp_rebuild_safely(self):
        original = self.build()
        original['questions'] = ['invalid table']
        self.manifest.write_text(json.dumps(original), encoding='utf8')
        stamp_path = next((self.cache/'pages').glob('*/0.json'))
        stamp = json.loads(stamp_path.read_text(encoding='utf8'))
        stamp['sourcePage'] = 999
        stamp_path.write_text(json.dumps(stamp), encoding='utf8')
        actual = self.build()
        self.assertEqual(set(actual['questions']), {'question-one'})
        self.assertFalse(actual['complete'])
        self.assertEqual(json.loads(stamp_path.read_text(encoding='utf8'))['sourcePage'], 0)
        with fitz.open(self.dest/actual['questions']['question-one']['path']) as doc:
            self.assertIn('Visible question one', doc[0].get_text())
            self.assertNotIn('Visible question two', doc[0].get_text())
            self.assertEqual(doc[0].get_xobjects(), [])


if __name__ == '__main__':
    unittest.main()
