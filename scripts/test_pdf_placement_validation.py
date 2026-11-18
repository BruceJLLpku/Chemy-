"""Strict native placement-grid regressions, including damaged actual PDFs."""
from io import BytesIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf as fitz
from PIL import Image, ImageChops
import pypdfium2 as pdfium
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, FloatObject, NameObject

import pdf_placement_verify as checker
import test_pdf_export_pixels as browser


def fixture(scale=1):
    with fitz.open() as source:
        source.new_page(width=120, height=120)
        page = source.new_page(width=120, height=120)
        page.insert_text((26, 48), 'KEEP ME', fontsize=12)
        page.draw_rect((27, 60, 65, 82), color=None, fill=(1, 0, 0))
        original = source.tobytes()
    rectangle = fitz.Rect(20, 20, 100, 100)
    x, top = 35.3, 55.7
    with fitz.open(stream=original, filetype='pdf') as source, fitz.open() as actual:
        actual.new_page(width=180, height=200)
        actual.new_page(width=180, height=200)
        page = actual.new_page(width=180, height=200)
        target = fitz.Rect(x, top, x + rectangle.width * scale, top + rectangle.height * scale)
        page.show_pdf_page(target, source, 1, clip=rectangle)
        observed = actual.tobytes()
    return original, observed, rectangle, x, top, scale


def shift_actual(data):
    writer = PdfWriter(clone_from=PdfReader(BytesIO(data)))
    page = writer.pages[2]
    content = ContentStream(page.get('/Contents'), writer)
    content.operations = [([], b'q'), ([FloatObject(v) for v in (1, 0, 0, 1, 1, 0)], b'cm')] + content.operations + [([], b'Q')]
    page[NameObject('/Contents')] = writer._add_object(content)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


class NativePlacementTests(unittest.TestCase):
    def compare(self, inputs=None):
        before, after, rectangle, x, top, scale = inputs or fixture()
        with fitz.open(stream=before, filetype='pdf') as source, fitz.open(stream=after, filetype='pdf') as actual:
            return checker.compare_placement_pdfium(source[1], actual[2], rectangle, x, top, scale)

    def test_real_native_multipage_original_index_and_noninteger_translation(self):
        result = self.compare()
        self.assertTrue(result['passed'], result)
        self.assertEqual(result['source']['pageIndex'], 1)
        self.assertEqual(result['actual']['pageIndex'], 2)
        self.assertEqual([check['dpi'] for check in result['checks']], [144, 288])
        self.assertTrue(all(check['maxDelta'] <= 8 for check in result['checks']))

    def test_real_scaled_full_band(self):
        result = self.compare(fixture(1.25))
        self.assertTrue(result['passed'], result)

    def test_real_one_point_displacement_is_rejected_at_both_resolutions(self):
        original, actual, *geometry = fixture()
        result = self.compare((original, shift_actual(actual), *geometry))
        self.assertFalse(result['passed'], result)
        self.assertTrue(all(check['maxDelta'] > 8 for check in result['checks']))

    def test_real_deleted_visible_text_is_rejected_at_both_resolutions(self):
        original, actual, *geometry = fixture()
        with fitz.open(stream=actual, filetype='pdf') as document:
            page = document[2]
            boxes = page.search_for('KEEP')
            self.assertEqual(len(boxes), 1)
            page.add_redact_annot(boxes[0], fill=(1, 1, 1), cross_out=False)
            page.apply_redactions(images=0, graphics=0, text=0)
            self.assertNotIn('KEEP', page.get_text())
            changed = document.tobytes()
        result = self.compare((original, changed, *geometry))
        self.assertFalse(result['passed'], result)
        self.assertTrue(all(check['maxDelta'] > 8 for check in result['checks']))

    def test_direct_matrix_agrees_with_native_page_orientation(self):
        before, *_ = fixture()
        with fitz.open(stream=before, filetype='pdf') as document:
            data, index, identity = checker._loaded(document[1])
            image = checker._render_original(data, index, identity, (240, 240), (2, 0, 0, 2, 0, 0))
        with pdfium.PdfDocument(before) as document:
            page = document[1]
            try:
                bitmap = page.render(scale=2, may_draw_forms=False)
                try:
                    normal = bitmap.to_pil().convert('RGB').copy()
                finally:
                    bitmap.close()
            finally:
                page.close()
        self.assertEqual(max(high for _, high in ImageChops.difference(image, normal).getextrema()), 0)
        self.assertEqual(image.getpixel((80, 140)), (255, 0, 0))

    def test_dirty_or_repaired_input_is_rejected(self):
        before, after, rectangle, x, top, scale = fixture()
        for repaired in (False, True):
            damaged = before[:before.rfind(b'\nxref\n')] if repaired else before
            try:
                with fitz.open(stream=damaged, filetype='pdf') as source, fitz.open(stream=after, filetype='pdf') as actual:
                    if repaired:
                        self.assertTrue(source.is_repaired)
                    else:
                        source[1].insert_text((10, 110), 'changed')
                    result = checker.compare_placement_pdfium(source[1], actual[2], rectangle, x, top, scale)
                    self.assertFalse(result['passed'])
                    self.assertIn('dirty or repaired', result['error'])
            finally:
                fitz.TOOLS.mupdf_warnings(reset=True)

    def test_missing_loaded_stream_or_self_reference_is_rejected(self):
        before, after, rectangle, x, top, scale = fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'source.pdf'
            path.write_bytes(before)
            with fitz.open(path) as source, fitz.open(stream=after, filetype='pdf') as actual:
                result = checker.compare_placement_pdfium(source[1], actual[2], rectangle, x, top, scale)
                self.assertFalse(result['passed'])
                self.assertIn('bytes unavailable', result['error'])
        with fitz.open(stream=before, filetype='pdf') as source:
            result = checker.compare_placement_pdfium(source[1], source[1], rectangle, 20, 20, 1)
            self.assertFalse(result['passed'])
            self.assertIn('independent original inputs', result['error'])

    def test_unsupported_crop_rotation_and_out_of_page_rect_are_rejected(self):
        before, after, rectangle, x, top, scale = fixture()
        for change in ('crop', 'rotation', 'outside'):
            with fitz.open(stream=before, filetype='pdf') as source:
                if change == 'crop': source[1].set_cropbox((0, 0, 115, 115))
                if change == 'rotation': source[1].set_rotation(90)
                modified = source.tobytes()
            with fitz.open(stream=modified, filetype='pdf') as source, fitz.open(stream=after, filetype='pdf') as actual:
                result = checker.compare_placement_pdfium(source[1], actual[2], rectangle,
                                                          1000 if change == 'outside' else x, top, scale)
                self.assertFalse(result['passed'], result)


class TwoResolutionGateTests(unittest.TestCase):
    def compare_mocked(self, deltas, *, fail_at=None, wrong_size=False):
        before, after, rectangle, x, top, scale = fixture()
        calls = []
        def render(data, index, identity, size, matrix):
            calls.append((data, index, identity, size, matrix))
            if fail_at == len(calls):
                raise ValueError('missing native render')
            value = deltas[(len(calls) - 1) // 2] if len(calls) % 2 == 0 else 0
            image_size = (size[0] - 1, size[1]) if wrong_size and len(calls) == 2 else size
            return Image.new('RGB', image_size, (value,) * 3)
        with fitz.open(stream=before, filetype='pdf') as source, fitz.open(stream=after, filetype='pdf') as actual, \
                patch.object(checker, '_render_original', side_effect=render):
            result = checker.compare_placement_pdfium(source[1], actual[2], rectangle, x, top, scale)
        return result, calls

    def test_both_native_resolutions_and_original_inputs_are_required(self):
        result, calls = self.compare_mocked((8, 8))
        self.assertTrue(result['passed'], result)
        self.assertEqual([call[1] for call in calls], [1, 2, 1, 2])
        self.assertIs(calls[0][0], calls[2][0])
        self.assertIs(calls[1][0], calls[3][0])

    def test_either_single_resolution_failure_is_rejected(self):
        for deltas in ((9, 0), (0, 9)):
            result, _ = self.compare_mocked(deltas)
            self.assertFalse(result['passed'], result)
            self.assertEqual([entry['maxDelta'] for entry in result['checks']], list(deltas))

    def test_incomplete_render_retains_first_result_and_fails(self):
        result, _ = self.compare_mocked((0, 0), fail_at=4)
        self.assertFalse(result['passed'])
        self.assertEqual(len(result['checks']), 1)
        self.assertIn('missing native render', result['error'])

    def test_bitmap_mapping_mismatch_is_rejected(self):
        result, _ = self.compare_mocked((0, 0), wrong_size=True)
        self.assertFalse(result['passed'])
        self.assertIn('bitmap geometry differs', result['error'])


class BrowserSecondaryGateTests(unittest.TestCase):
    def compare(self, *, large_change=False, retry=True, proof_passed=True):
        before, after, rectangle, x, top, scale = fixture()
        with fitz.open(stream=after, filetype='pdf') as document:
            box = (90, 100, 110, 125) if large_change else (100, 120, 100.5, 120.5)
            document[2].draw_rect(box, color=None, fill=(0, 0, 0))
            changed = document.tobytes()
        with tempfile.TemporaryDirectory() as directory, \
                fitz.open(stream=before, filetype='pdf') as source, \
                fitz.open(stream=changed, filetype='pdf') as actual, \
                patch.object(browser, 'OUT', Path(directory)), \
                patch.object(browser, 'matched_relocated_glyphs', return_value=None), \
                patch.object(browser, 'compare_placement_pdfium', return_value={'passed': proof_passed}) as oracle:
            result = browser.relocate_compare(source[1], actual[2], rectangle, x, top, scale,
                                               'gate', _allow_sampling_retry=retry)
        return result, oracle.call_count

    def test_strict_secondary_retains_initial_metrics(self):
        result, calls = self.compare()
        self.assertEqual(calls, 1)
        self.assertTrue(result['ordinaryMetricsPassed'])
        self.assertFalse(result['initialPassed'])
        self.assertGreater(result['tolerantMaxDelta'], 32)
        self.assertTrue(result['passed'])

    def test_secondary_failure_is_not_accepted(self):
        result, calls = self.compare(proof_passed=False)
        self.assertEqual(calls, 1)
        self.assertFalse(result['passed'])

    def test_ordinary_metrics_failure_cannot_borrow_secondary_proof(self):
        result, calls = self.compare(large_change=True)
        self.assertFalse(result['ordinaryMetricsPassed'])
        self.assertEqual(calls, 0)
        self.assertFalse(result['passed'])

    def test_shifted_sampling_phase_cannot_call_secondary(self):
        result, calls = self.compare(retry=False)
        self.assertEqual(calls, 0)
        self.assertFalse(result['passed'])


if __name__ == '__main__':
    unittest.main()
