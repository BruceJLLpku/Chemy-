"""Exercise safe staging, referenced-asset retention, and the Pages byte limit."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from unittest.mock import patch

from stage_site import plan_site, stage_site, SLUGS
import test_release_check as release_fixtures


class StageSiteTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.write('dist/index.html', b'<img src="assets/logo.svg"><link href="styles.css">')
        self.write('dist/styles.css', b'.a{background:url("assets/ui.png")}')
        self.write('dist/app.js', b'fetch("questions.json");fetch("presentation.json");')
        self.write('dist/questions.json', json.dumps([{'body': '<img src="assets/q.webp">'}]).encode())
        self.write('dist/presentation.json', json.dumps({'q': {'answer': '<img src="assets/a.webp">'}}).encode())
        self.write('dist/assets/logo.svg', b'<svg><image href="logo-detail.png"/></svg>')
        for name in ['ui.png', 'logo-detail.png', 'q.webp', 'a.webp', 'unused.webp', 'chemy-watermark.jpg']:
            self.write('dist/assets/' + name, name.encode())
        self.write('dist/numbering.123.tmp', b'old temporary file')
        self.write('dist/downloads/polymer-questions.pdf', b'%PDF-1.7\noriginal topic book')

    def write(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value)

    def clean_books(self):
        # Reuse the release check's complete small fixture instead of encoding a
        # second, weaker interpretation of the generated manifest schema.
        fixture = release_fixtures.ReleaseCheckTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        fixture.prepare_parts()
        shutil.copytree(fixture.root, self.root, dirs_exist_ok=True)
        self.write('dist/app.js', b'const base="export-parts/";const suffix="-book.pdf";')

    def alter_json(self, name, mutate):
        value = json.loads((self.root / name).read_text(encoding='utf-8'))
        mutate(value)
        self.write(name, json.dumps(value).encode('utf-8'))

    def test_stages_exact_copies_of_referenced_assets(self):
        before = {p.relative_to(self.root / 'dist').as_posix(): p.read_bytes()
                  for p in (self.root / 'dist').rglob('*') if p.is_file()}
        report = stage_site(self.root)
        target = Path(report['path'])
        self.assertFalse((target / 'assets/unused.webp').exists())
        self.assertFalse((target / 'numbering.123.tmp').exists())
        for name in ['logo.svg', 'logo-detail.png', 'q.webp', 'a.webp', 'ui.png', 'chemy-watermark.jpg']:
            self.assertEqual((target / 'assets' / name).read_bytes(), before['assets/' + name])
        self.assertEqual(report['bytes'], sum(p.stat().st_size for p in target.rglob('*') if p.is_file()))
        self.assertEqual(before, {p.relative_to(self.root / 'dist').as_posix(): p.read_bytes()
                                 for p in (self.root / 'dist').rglob('*') if p.is_file()})

    def test_missing_asset_does_not_replace_previous_stage(self):
        self.write('output/site/sentinel.txt', b'keep')
        (self.root / 'dist/assets/q.webp').unlink()
        with self.assertRaisesRegex(ValueError, 'Missing referenced'):
            stage_site(self.root)
        self.assertEqual((self.root / 'output/site/sentinel.txt').read_bytes(), b'keep')

    def test_over_budget_fails_before_copy(self):
        with self.assertRaisesRegex(ValueError, 'budget'):
            stage_site(self.root, max_bytes=10)
        self.assertFalse((self.root / 'output').exists())

    def test_old_stage_is_preserved_in_unique_backup(self):
        self.write('output/site/sentinel.txt', b'old site')
        report = stage_site(self.root)
        backup = Path(report['previousSiteBackup'])
        self.assertTrue(backup.is_relative_to(self.root / 'output'))
        self.assertEqual((backup / 'sentinel.txt').read_bytes(), b'old site')
        self.assertTrue((self.root / 'output/site/index.html').is_file())

    def test_input_traversal_is_rejected(self):
        self.write('dist/questions.json', b'[{"body":"assets/../../outside.png"}]')
        with self.assertRaisesRegex(ValueError, 'escapes dist'):
            stage_site(self.root)

    def test_output_cannot_replace_source(self):
        with self.assertRaisesRegex(ValueError, 'below project/output'):
            stage_site(self.root, output=self.root / 'dist')

    def test_copy_failure_keeps_old_stage(self):
        self.write('output/site/sentinel.txt', b'keep')
        with patch('stage_site.shutil.copy2', side_effect=OSError('simulated copy failure')):
            with self.assertRaisesRegex(OSError, 'simulated'):
                stage_site(self.root)
        self.assertEqual((self.root / 'output/site/sentinel.txt').read_bytes(), b'keep')

    def test_clean_books_mode_preserves_source_but_excludes_it_from_site(self):
        self.clean_books()
        report = stage_site(self.root, clean_books=True)
        self.assertFalse((Path(report['path']) / 'downloads').exists())
        self.assertTrue((self.root / 'dist/downloads/polymer-questions.pdf').is_file())
        self.assertEqual(len(list((Path(report['path']) / 'export-parts').glob('*-book.pdf'))), 18)

    def test_clean_books_mode_requires_all_18_books(self):
        self.clean_books()
        (self.root / 'dist/export-parts/organic-answers-book.pdf').unlink()
        with self.assertRaisesRegex(ValueError, 'missing PDF'):
            plan_site(self.root, clean_books=True)

    def test_clean_books_mode_rejects_old_download_links(self):
        self.clean_books()
        self.write('dist/app.js', b'const base="downloads/";')
        with self.assertRaisesRegex(ValueError, 'still refers to source downloads'):
            plan_site(self.root, clean_books=True)

    def test_incomplete_manifest_does_not_replace_previous_site(self):
        self.clean_books()
        self.write('output/site/sentinel.txt', b'keep')
        self.alter_json('dist/export-parts/polymer-questions.json',
                        lambda value: value.update(complete=False))
        with self.assertRaisesRegex(ValueError, 'incomplete build'):
            stage_site(self.root, clean_books=True)
        self.assertEqual((self.root / 'output/site/sentinel.txt').read_bytes(), b'keep')
        self.assertFalse(list((self.root / 'output').glob('site-building-*')))

    def test_incomplete_global_inventory_is_rejected(self):
        self.clean_books()
        self.write('dist/export-parts/manifest.json', b'{"complete":false,"books":{}}')
        with self.assertRaisesRegex(ValueError, 'inventory must contain all 18 books'):
            plan_site(self.root, clean_books=True)

    def test_stale_source_build_or_question_set_is_rejected(self):
        self.clean_books()
        changes = [
            ('dist/export-index/polymer.json', 'source index SHA-256 differs',
             lambda data: {**data, 'changedSinceBuild': True}),
            ('dist/export-parts/polymer-questions.json', 'stale build signature',
             lambda data: {**data, 'signature': 'old-build'}),
            ('dist/export-parts/polymer-questions.json', 'generated question IDs differ',
             lambda data: {**data, 'questions': {}}),
        ]
        for name, message, mutate in changes:
            with self.subTest(input=name, reason=message):
                original = (self.root / name).read_bytes()
                self.write(name, json.dumps(mutate(json.loads(original))).encode('utf-8'))
                with self.assertRaisesRegex(ValueError, message):
                    plan_site(self.root, clean_books=True)
                self.write(name, original)

    def test_stale_unreferenced_export_files_are_not_published_or_deleted(self):
        self.clean_books()
        stale = ['polymer/removed-question-answers.pdf', 'old-topic-book.pdf', 'old-topic.json']
        for name in stale:
            self.write('dist/export-parts/' + name, b'%PDF-1.7\nstale unreferenced bytes')
        report = stage_site(self.root, clean_books=True)
        target = Path(report['path']) / 'export-parts'
        for name in stale:
            self.assertTrue((self.root / 'dist/export-parts' / name).is_file())
            self.assertFalse((target / name).exists())
        expected = {'manifest.json'}
        for slug in SLUGS.values():
            for kind in ('questions', 'answers'):
                expected.update({f'{slug}-{kind}.json', f'{slug}-{kind}-frame.pdf',
                                 f'{slug}-{kind}-book.pdf', f'{slug}/fixture-{slug}-{kind}.pdf'})
        self.assertEqual({p.relative_to(target).as_posix() for p in target.rglob('*') if p.is_file()}, expected)


if __name__ == '__main__':
    unittest.main()
