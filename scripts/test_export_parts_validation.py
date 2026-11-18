"""Regress the two-stage export oracle, provenance checks and bounded memory."""
from argparse import Namespace
import contextlib
from io import StringIO, BytesIO
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from collections import Counter
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from unittest.mock import patch

import fitz
import build_export_parts as builder
import test_export_parts as validation
from pypdf import PdfWriter
from pypdf.generic import NameObject, NumberObject, ArrayObject, DictionaryObject, DecodedStreamObject


class ExportPartValidationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for directory in ('scripts', 'dist/downloads', 'dist/export-index', 'dist/assets'):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        for name in validation.BUILD_FILES:
            shutil.copy2(builder.ROOT / 'scripts' / name, self.root / 'scripts' / name)
        shutil.copy2(builder.ROOT / 'dist/assets/chemy-watermark.jpg', self.root / 'dist/assets/chemy-watermark.jpg')
        with fitz.open() as doc:
            page = doc.new_page(width=595.28, height=841.89)
            page.insert_text((60, 110), 'Visible H2O question one')
            page.draw_line((60, 115), (170, 115), width=.3)
            page.insert_text((60, 180), 'Visible CO2 question two')
            doc.save(self.root / 'dist/downloads/fixture-questions.pdf')
        index = {'bookVersion': 'fixture', 'questions': {
            'question-one': [{'page': 0, 'bands': [[80, 130]]}],
            'question-two': [{'page': 0, 'bands': [[150, 210]]}],
            'question-three': [{'page': 0, 'bands': [[220, 250]]}]}}
        (self.root / 'dist/export-index/fixture.json').write_text(json.dumps(index), encoding='utf8')
        (self.root / 'dist/numbering.json').write_text(json.dumps({'pdfVersion': 'fixture'}), encoding='utf8')
        self.parts = self.root / 'dist/export-parts'
        with patch.object(builder, 'ROOT', self.root), patch.object(builder, 'DEST', self.parts), \
                patch.object(builder, 'CACHE', self.root / 'tmp/export-parts'):
            builder.build_book(('fixture', 'questions', ['question-one', 'question-two'], False))
        self.manifest = json.loads((self.parts / 'fixture-questions.json').read_text(encoding='utf8'))
        cleaning, _ = validation.code_digests(self.root)
        self.references = validation.ValidatedCleanPages(self.root, self.manifest['sourceSha256'], cleaning, max_open=2)
        self.addCleanup(self.references.close)
        self.stamp_path = self.references.directory / '0.json'

    def validate(self, **overrides):
        args = Namespace(allow_incomplete=True, all_renders=True, max_mae=.8,
                         max_changed_fraction=.01, max_delta=8, report=self.root / 'report.json')
        vars(args).update(overrides)
        with patch.object(validation, 'ROOT', self.root), patch.object(validation, 'PARTS', self.parts), \
                contextlib.redirect_stdout(StringIO()):
            validation.validate(args)
        return json.loads(args.report.read_text(encoding='utf8'))

    def build_second_book(self):
        with fitz.open(self.root / 'dist/downloads/fixture-questions.pdf') as doc:
            doc[0].insert_text((250, 110), 'Second topic with its own source')
            doc.save(self.root / 'dist/downloads/second-questions.pdf')
        shutil.copy2(self.root / 'dist/export-index/fixture.json', self.root / 'dist/export-index/second.json')
        with patch.object(builder, 'ROOT', self.root), patch.object(builder, 'DEST', self.parts), \
                patch.object(builder, 'CACHE', self.root / 'tmp/export-parts'):
            builder.build_book(('second', 'questions', ['question-one', 'question-two'], False))
        return json.loads((self.parts / 'second-questions.json').read_text(encoding='utf8'))

    def test_real_development_parts_compare_with_current_clean_references(self):
        report = self.validate()
        self.assertEqual(report['reference'], 'validated-clean-page')
        self.assertEqual(report['totals']['renderedBands'], 2)
        self.assertEqual(report['errors'], [])
        self.assertTrue(all(check['textEqual'] and check['maxDelta'] <= 8 for check in report['renderChecks']))
        self.assertEqual(len(report['books'][0]['cleanReferences']), 1)

    def test_changed_part_bytes_rejected_before_rendering(self):
        path = self.parts / self.manifest['questions']['question-one']['path']
        raw = bytearray(path.read_bytes())
        raw[-10] ^= 1
        path.write_bytes(raw)
        with self.assertRaisesRegex(AssertionError, 'sha256'):
            self.validate()

    def test_stale_production_signature_rejected_even_in_sample_mode(self):
        path = self.root / 'scripts/pdf_render_verify.py'
        path.write_bytes(path.read_bytes() + b'\n# Different verifier revision.\n')
        with self.assertRaisesRegex(AssertionError, 'Stale build signature'):
            self.validate()

    def test_invalid_clean_stamp_and_missing_reference_fail_closed(self):
        stamp = json.loads(self.stamp_path.read_text(encoding='utf8'))
        for key, value, expected in [('sha256', '0' * 64, 'clean page sha256'),
                                     ('sourcePage', 99, 'clean page identity'),
                                     ('render_max_delta', 9, 'successful full-page'),
                                     ('render_max_delta', None, 'successful full-page')]:
            with self.subTest(key=key, value=value):
                self.stamp_path.write_text(json.dumps({**stamp, key: value}), encoding='utf8')
                with self.assertRaisesRegex(AssertionError, expected):
                    self.references.page(0)
        self.stamp_path.unlink()
        with self.assertRaisesRegex(AssertionError, 'Missing current verified clean page'):
            self.validate()

    def test_accepted_upstream_difference_is_not_reapplied_to_fragment(self):
        # Cleanup's initial delta is evidence, not a second-stage tolerance.
        stamp = json.loads(self.stamp_path.read_text(encoding='utf8'))
        stamp['render_initial_max_delta'] = 54
        self.stamp_path.write_text(json.dumps(stamp), encoding='utf8')
        report = self.validate()
        self.assertEqual(report['books'][0]['cleanReferences'][0]['initialMaxDelta'], 54)
        self.assertTrue(all(check['maxDelta'] == 0 for check in report['renderChecks']))

    def test_changed_content_and_unicode_multiplicity_still_rejected(self):
        source = self.references.page(0)
        metadata = self.manifest['questions']['question-one']
        with fitz.open(self.parts / metadata['path']) as part:
            # Restoring the source coordinates must not conceal a deleted bond.
            part[0].set_mediabox(source.mediabox)
            part[0].add_redact_annot(fitz.Rect(59, 114, 171, 116))
            part[0].apply_redactions(images=0, graphics=2, text=0)
            result = validation.compare_band(source, part, 0, metadata['pages'][0])
            self.assertGreater(result['maxDelta'], 8)
        with fitz.open() as expected, fitz.open() as actual:
            for doc, count in ((expected, 2), (actual, 1)):
                page = doc.new_page(width=200, height=100)
                for _ in range(count):
                    page.insert_text((20, 50), 'H')
            result = validation.compare_band(expected[0], actual, 0, {'box': [0, 0, 200, 100]})
            self.assertFalse(result['textEqual'])
            self.assertEqual(result['missingCharacters'], {'H': 1})

    def test_reference_documents_are_closed_on_lru_eviction(self):
        raw = (self.references.directory / '0.pdf').read_bytes()
        stamp = json.loads(self.stamp_path.read_text(encoding='utf8'))
        for number in (1, 2):
            (self.references.directory / f'{number}.pdf').write_bytes(raw)
            (self.references.directory / f'{number}.json').write_text(
                json.dumps({**stamp, 'sourcePage': number}), encoding='utf8')
        self.references.page(0)
        first = self.references.documents[0]
        self.references.page(1)
        self.references.page(2)
        self.assertTrue(first.is_closed)
        self.assertEqual(list(self.references.documents), [1, 2])
        self.references.page(1)
        self.references.page(0)
        self.assertEqual(list(self.references.documents), [1, 0])
        self.references.close()
        self.assertFalse(self.references.documents)

    def test_multiple_books_have_identical_serial_and_spawned_reports(self):
        self.build_second_book()
        serial = self.validate(jobs=1)
        parallel = self.validate(jobs=2)
        self.assertEqual(serial, parallel)
        self.assertEqual(serial['totals']['books'], 2)
        self.assertEqual(serial['totals']['parts'], 4)
        self.assertEqual(serial['totals']['renderedBands'], 4)
        self.assertEqual([book['book'] for book in parallel['books']],
                         ['fixture-questions.pdf', 'second-questions.pdf'])

    def test_spawned_worker_assertion_reaches_caller(self):
        metadata = self.build_second_book()
        path = self.parts / metadata['questions']['question-one']['path']
        raw = bytearray(path.read_bytes())
        raw[-10] ^= 1
        path.write_bytes(raw)
        with self.assertRaisesRegex(AssertionError, 'sha256'):
            self.validate(jobs=2)
        self.assertFalse((self.root / 'report.json').exists(), 'A worker failure must not publish a passing report')

    def test_band_exception_is_recorded_and_remaining_bands_are_checked(self):
        real = validation.compare_band
        calls = 0
        def fail_first(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise AssertionError('unknown font parser warning')
            return real(*args, **kwargs)
        with patch.object(validation, 'compare_band', side_effect=fail_first):
            with self.assertRaisesRegex(AssertionError, 'Visible content differs'):
                self.validate()
        report = json.loads((self.root / 'report.json').read_text(encoding='utf8'))
        self.assertEqual(calls, 2)
        self.assertEqual(len(report['renderChecks']), 2)
        self.assertEqual(len(report['errors']), 1)
        failure = report['errors'][0]
        self.assertEqual(failure['id'], 'question-one')
        self.assertEqual(failure['sourcePage'], 0)
        self.assertEqual(failure['page'], 0)
        self.assertIn('question-one', failure['path'])
        self.assertIn('unknown font parser warning', failure['error'])

    def test_worker_defaults_keep_sampling_and_legacy_calls_serial(self):
        with patch.object(validation.os, 'cpu_count', return_value=8):
            self.assertEqual(validation.worker_count(Namespace(all_renders=True), 18), 1)
            self.assertEqual(validation.worker_count(Namespace(all_renders=False, jobs=None), 18), 1)
            self.assertEqual(validation.worker_count(Namespace(all_renders=True, jobs=None), 18), 4)
            self.assertEqual(validation.worker_count(Namespace(all_renders=True, jobs=1), 18), 1)


def warning_fixture(*, ascent=3117, family=None, changed_bbox=False, subset_name=False, program_padding=False, changed_subtype=False):
    """A small embedded font with real MuPDF metrics warnings, no system fonts."""
    with fitz.open() as doc:
        page = doc.new_page(width=200, height=100)
        page.insert_font(fontname='probe', fontbuffer=fitz.Font('helv').buffer)
        page.insert_text((30, 50), 'H2O', fontname='probe')
        raw = doc.tobytes(garbage=1)
    writer = PdfWriter(clone_from=BytesIO(raw))
    visited = set()

    def visit(value):
        value = value.get_object()
        if id(value) in visited:
            return
        visited.add(id(value))
        if isinstance(value, DictionaryObject):
            if '/FontDescriptor' in value:
                descriptor = value['/FontDescriptor'].get_object()
                descriptor[NameObject('/Ascent')] = NumberObject(ascent)
                descriptor[NameObject('/Descent')] = NumberObject(-2464)
                if changed_subtype:
                    value[NameObject('/Subtype')] = NameObject('/UnknownFontType')
                if family:
                    descriptor[NameObject('/FontName')] = NameObject('/'+family)
                    value[NameObject('/BaseFont')] = NameObject('/'+family)
                if changed_bbox:
                    box = descriptor['/FontBBox']
                    box[0] = NumberObject(float(box[0])-1)
                if subset_name:
                    for obj, key in ((descriptor, '/FontName'), (value, '/BaseFont')):
                        obj[NameObject(key)] = NameObject('/ABCDEF+'+str(obj[key]).lstrip('/'))
                if program_padding:
                    for key in ('/FontFile', '/FontFile2', '/FontFile3'):
                        if key in descriptor:
                            stream = descriptor[key].get_object()
                            stream.set_data(stream.get_data()+b'\0')
            for item in value.values():
                visit(item)
        elif isinstance(value, ArrayObject):
            for item in value:
                visit(item)
    visit(writer.pages[0]['/Resources'])
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


class InheritedFontWarningTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'font.pdf'
        self.original = warning_fixture()
        self.source = validation.FontWarningSource(self.original)

    def inventory(self, raw, source=True):
        self.path.write_bytes(raw)
        metadata = {'bytes': len(raw), 'sha256': validation.digest(raw)}
        return validation.inventory(self.path, metadata,
            warning_source=self.source if source else None, source_pages=[0])

    def test_inherited_warning_records_original_font_metrics_and_hashes(self):
        proof = self.inventory(self.original)['inheritedWarnings'][0]
        self.assertIn('3117 / -2464', proof['warnings'])
        self.assertEqual(proof['sourcePage'], 0)
        self.assertTrue(all(font['programUnchanged'] for font in proof['fonts']))
        self.assertEqual(proof['proofScope'], 'inherited font descriptor metrics only')

    def test_missing_original_evidence_includes_actual_warning_and_path(self):
        with self.assertRaisesRegex(AssertionError, '3117 / -2464') as error:
            self.inventory(self.original, source=False)
        self.assertIn('font.pdf', str(error.exception))

    def test_new_metrics_family_and_bbox_are_rejected(self):
        for changed in ({'ascent': 3120}, {'family': 'AnotherFont'}, {'changed_bbox': True}):
            with self.subTest(changed=changed):
                with self.assertRaisesRegex(AssertionError, 'PDF parser/font warnings'):
                    self.inventory(warning_fixture(**changed))

    def test_extra_original_warning_cannot_authorize_an_unknown_output_warning(self):
        original_warning, pairs, evidence = self.source.page(0)
        original_warning += '\nActualtext with no position'
        self.assertEqual(validation.metric_warning_pairs(original_warning, source=True), pairs)
        self.source.pages[0] = (original_warning, pairs, evidence)
        proof = self.source.prove(self.original, 0, 0,
                                 'bogus font ascent/descent values (3117 / -2464)')
        self.assertIn('Actualtext with no position', proof['sourceWarnings'])
        with self.assertRaisesRegex(AssertionError, 'Unproved PDF parser/font warning'):
            self.source.prove(self.original, 0, 0, original_warning)

    def test_different_font_subtype_cannot_reuse_same_metrics(self):
        with self.assertRaisesRegex(AssertionError, 'Font metrics/family differ'):
            self.source.prove(warning_fixture(changed_subtype=True), 0, 0,
                              'bogus font ascent/descent values (3117 / -2464)')

    def test_unrelated_parser_warning_is_never_inherited(self):
        warning = 'bogus font ascent/descent values (3117 / -2464)\nsyntax error in content stream'
        with self.assertRaisesRegex(AssertionError, 'Unproved PDF parser/font warning'):
            self.source.prove(self.original, 0, 0, warning)
        with self.assertRaisesRegex(AssertionError, 'Unproved PDF parser/font warning'):
            validation.metric_warning_pairs('... repeated 2 times...')

    def test_subset_prefix_and_program_bytes_are_explicitly_separate_from_metrics(self):
        # Padding is a harmless program-byte change, not an invented substitute
        # for glyph QA. The report must expose the changed program SHA clearly.
        proof = self.inventory(warning_fixture(subset_name=True, program_padding=True))['inheritedWarnings'][0]
        self.assertTrue(all(not font['programUnchanged'] for font in proof['fonts']))
        self.assertTrue(all(font['sourceFontPrograms'] for font in proof['fonts']))

    def test_band_comparison_keeps_warning_proof_and_strict_pixel_checks(self):
        with fitz.open('pdf', self.original) as source, fitz.open('pdf', self.original) as target:
            result = validation.compare_band(source[0], target, 0, {'box': [0, 0, 200, 100]})
            self.assertEqual(result['warnings'], '')
            self.assertTrue(result['inheritedWarnings'])
            self.assertEqual(result['maxDelta'], 0)
            target[0].insert_text((30, 75), 'EXTRA')
            result = validation.compare_band(source[0], target, 0, {'box': [0, 0, 200, 100]})
            self.assertFalse(result['textEqual'])
            self.assertGreater(result['maxDelta'], 8)


def counter_font(*, hyphen_only=False):
    builder = FontBuilder(1000, isTTF=True)
    order = ['.notdef', 'hyphen'] if hyphen_only else ['.notdef', 'A', 'space', 'acute']
    builder.setupGlyphOrder(order)
    builder.setupCharacterMap({45: 'hyphen'} if hyphen_only else {65: 'A', 32: 'space', 769: 'acute'})
    glyphs = {}
    for name in order:
        pen = TTGlyphPen(None)
        if name not in ('.notdef', 'space'):
            height = 100 if name == 'hyphen' else 500
            pen.moveTo((0, 0)); pen.lineTo((200, 0)); pen.lineTo((200, height)); pen.lineTo((0, height)); pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name: (0 if name == 'acute' else 500, 0) for name in order})
    builder.setupHorizontalHeader(ascent=800, descent=-200)
    builder.setupOS2(sTypoAscender=800, sTypoDescender=-200, usWinAscent=800, usWinDescent=200)
    builder.setupNameTable({'familyName': 'CounterFixture', 'styleName': 'Regular',
                           'uniqueFontIdentifier': 'CounterFixture-Regular', 'fullName': 'CounterFixture Regular',
                           'psName': 'CounterFixture-Regular'})
    builder.setupPost(); builder.setupMaxp()
    out = BytesIO(); builder.save(out)
    return out.getvalue()


def counter_fixture(text='A', *, copies=1, mode=0, x=30, ligature=False, bad_gid=False, hyphen_only=False):
    with fitz.open() as doc:
        page = doc.new_page(width=200, height=100)
        page.insert_font(fontname='probe', fontbuffer=counter_font(hyphen_only=hyphen_only))
        for _ in range(copies):
            page.insert_text((x, 50), text, fontname='probe', render_mode=mode)
        raw = doc.tobytes(garbage=1)
    if ligature or bad_gid:
        writer = PdfWriter(clone_from=BytesIO(raw))
        font = writer.pages[0]['/Resources']['/Font']['/probe'].get_object()
        if ligature:
            stream = DecodedStreamObject()
            stream.set_data(b'/CIDInit /ProcSet findresource begin 12 dict begin begincmap '
                b'1 begincodespacerange <0000> <FFFF> endcodespacerange '
                b'1 beginbfchar <0001> <00660069> endbfchar '
                b'endcmap CMapName currentdict /CMap defineresource pop end end')
            font[NameObject('/ToUnicode')] = writer._add_object(stream)
        if bad_gid:
            descendant = font['/DescendantFonts'][0].get_object()
            stream = DecodedStreamObject(); stream.set_data(b'\0\0\xff\xff')
            descendant[NameObject('/CIDToGIDMap')] = writer._add_object(stream)
        out = BytesIO(); writer.write(out); raw = out.getvalue()
    return raw


class NativeCharacterPaintTests(unittest.TestCase):
    def counts(self, raw, rect=(0, 0, 200, 100)):
        fitz.TOOLS.store_shrink(100)
        fitz.TOOLS.mupdf_warnings(reset=True)
        with fitz.open('pdf', raw) as doc:
            result = validation.characters(doc[0], fitz.Rect(rect))
        return result, fitz.TOOLS.mupdf_warnings(reset=True)

    def test_hyphen_only_subset_needs_no_synthetic_space_glyph(self):
        result, warnings = self.counts(counter_fixture('--', hyphen_only=True))
        self.assertEqual(result, Counter({'-': 2}))
        self.assertEqual(warnings, '')

    def test_duplicate_and_fill_stroke_paints_keep_multiplicity(self):
        for options in ({'copies': 2}, {'mode': 2}):
            with self.subTest(options=options):
                result, warnings = self.counts(counter_fixture(**options))
                self.assertEqual(result, Counter({'A': 2}))
                self.assertEqual(warnings, '')
        self.assertEqual(self.counts(counter_fixture(mode=3))[0], Counter())

    def test_multicodepoint_glyph_keeps_continuation_at_the_same_position(self):
        raw = counter_fixture(ligature=True)
        self.assertEqual(self.counts(raw)[0], Counter({'f': 1, 'i': 1}))
        self.assertEqual(self.counts(raw, (100, 0, 200, 100))[0], Counter())
        with fitz.open('pdf', raw) as source, fitz.open('pdf', counter_fixture()) as target:
            result = validation.compare_band(source[0], target, 0, {'box': [0, 0, 200, 100]})
            self.assertFalse(result['textEqual'])
            self.assertEqual(result['missingCharacters'], {'f': 1, 'i': 1})

    def test_spaces_and_zero_advance_marks_are_bounded(self):
        for text in (' ', '\u0301'):
            with self.subTest(text=text):
                raw = counter_fixture(text, x=150)
                self.assertEqual(self.counts(raw, (0, 0, 100, 100))[0], Counter())
                self.assertEqual(self.counts(raw)[0], Counter({text: 1}))

    def test_actual_out_of_range_drawn_gid_remains_a_failure(self):
        try:
            _, warnings = self.counts(counter_fixture(bad_gid=True))
        except ValueError as error:
            self.assertIn('outside font glyph count', str(error))
        else:
            self.assertTrue(warnings, 'A genuinely corrupt CID-to-GID mapping must be rejected')
            with self.assertRaisesRegex(AssertionError, 'Unproved PDF parser/font warning'):
                validation.metric_warning_pairs(warnings)


class CombiningMarkCropTests(unittest.TestCase):
    def test_unguarded_font_optimization_cannot_replace_the_reference_ink(self):
        from fontTools.ttLib import TTFont
        from pypdf import PdfReader

        def unsafe_native_subset(doc, *args, **kwargs):
            # Fault injection models an optimizer changing a glyph before the
            # guarded subsetter captures its reference. A later self-comparison
            # cannot discover that the original letter was already distorted.
            reader = PdfReader(BytesIO(doc.tobytes(garbage=1)))
            font = next(iter(reader.pages[0]['/Resources']['/Font'].values())).get_object()
            descendant = font['/DescendantFonts'][0].get_object()
            stream = descendant['/FontDescriptor'].raw_get('/FontFile2')
            program = TTFont(BytesIO(stream.get_object().get_data()))
            program['glyf']['A'].coordinates.scale((2, 1))
            changed = BytesIO(); program.save(changed); program.close()
            doc.update_stream(stream.idnum, changed.getvalue())

        raw = counter_fixture('A')
        band = {'sourcePage': 0, 'box': [0, 0, 200, 100]}
        with patch.object(builder.fitz.Document, 'subset_fonts', autospec=True,
                          side_effect=unsafe_native_subset):
            result = builder.make_part(lambda number: raw, [band], 'guarded-font-baseline')
        with fitz.open('pdf', raw) as source, fitz.open('pdf', result) as target:
            check = validation.compare_band(source[0], target, 0, band)
            self.assertTrue(check['textEqual'])
            self.assertEqual(check['maxDelta'], 0)

    def test_zero_advance_marks_survive_but_neighbor_content_is_removed(self):
        from PIL import Image
        image = BytesIO()
        Image.new('RGB', (8, 8), (230, 10, 40)).save(image, format='PNG')
        with fitz.open() as original:
            page = original.new_page(width=200, height=160)
            page.insert_font(fontname='probe', fontbuffer=counter_font())
            page.insert_text((30, 60), 'A\u0301', fontname='probe', fontsize=20)
            page.insert_text((30, 130), 'A\u0301', fontname='probe', fontsize=20)
            page.draw_line((30, 64), (80, 64), width=.5)
            page.draw_line((30, 135), (80, 135), width=.5)
            page.insert_image((120, 110, 150, 140), stream=image.getvalue())
            raw = original.tobytes(garbage=1)
        band = {'sourcePage': 0, 'box': [0, 40, 200, 70]}
        result = builder.make_part(lambda number: raw, [band], 'combining-crop')
        with fitz.open('pdf', raw) as source, fitz.open('pdf', result) as target:
            check = validation.compare_band(source[0], target, 0, band)
            self.assertTrue(check['textEqual'])
            self.assertEqual(check['maxDelta'], 0)
            target[0].set_mediabox(source[0].mediabox)
            self.assertEqual(validation.characters(target[0], target[0].rect), Counter({'A': 1, '\u0301': 1}))
            self.assertEqual(len(target[0].get_drawings()), 1)
            self.assertEqual(target[0].get_images(), [])
            self.assertEqual(target[0].get_xobjects(), [])

    def test_zero_advance_marks_outside_the_horizontal_band_are_removed(self):
        with fitz.open() as original:
            page = original.new_page(width=200, height=100)
            page.insert_font(fontname='probe', fontbuffer=counter_font())
            for x in (10, 50, 170):
                page.insert_text((x, 50), '\u0301', fontname='probe', fontsize=20)
            raw = original.tobytes(garbage=1)
        band = {'sourcePage': 0, 'box': [30, 30, 100, 60]}
        result = builder.make_part(lambda number: raw, [band], 'combining-horizontal')
        with fitz.open('pdf', raw) as source, fitz.open('pdf', result) as target:
            check = validation.compare_band(source[0], target, 0, band)
            self.assertTrue(check['textEqual'])
            self.assertEqual(check['maxDelta'], 0)
            target[0].set_mediabox(source[0].mediabox)
            self.assertEqual(validation.characters(target[0], target[0].rect), Counter({'\u0301': 1}))


if __name__ == '__main__':
    unittest.main()
