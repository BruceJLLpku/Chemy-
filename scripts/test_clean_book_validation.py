"""Whole-book renderer provenance and strict independent comparison regressions."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import pymupdf as fitz
from PIL import Image

import test_clean_book_pixels as checker


def fixture(*, changed=False, text=''):
    with fitz.open() as document:
        document.new_page(width=100, height=100)
        page = document.new_page(width=100, height=100)
        page.draw_rect((20, 20, 40, 40), color=None, fill=(1, 0, 0) if changed else (0, 0, 0))
        if text:
            page.insert_text((10, 80), text)
        return document.tobytes()


class OriginalPageTests(unittest.TestCase):
    def test_real_renderer_uses_complete_loaded_bytes_and_selected_page(self):
        raw = fixture(changed=True)
        with fitz.open(stream=raw, filetype='pdf') as document:
            for scale in (2, 4):
                image, scales, identity = checker.original_page_pdfium(document[1], scale)
                self.assertEqual(image.size, (100 * scale, 100 * scale))
                self.assertEqual(scales, (scale, scale))
                self.assertEqual(image.getpixel((30 * scale, 30 * scale)), (255, 0, 0))
                self.assertEqual(identity, {'inputSha256': hashlib.sha256(raw).hexdigest(),
                                            'pageIndex': 1, 'pages': 2})

    def test_dirty_document_is_rejected(self):
        with fitz.open(stream=fixture(), filetype='pdf') as document:
            document[1].insert_text((10, 70), 'changed after load')
            with self.assertRaisesRegex(ValueError, 'unchanged loaded PDF bytes'):
                checker.original_page_pdfium(document[1], 2)

    def test_document_without_original_loaded_stream_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'input.pdf'
            path.write_bytes(fixture())
            with fitz.open(path) as document:
                with self.assertRaisesRegex(ValueError, 'unchanged loaded PDF bytes'):
                    checker.original_page_pdfium(document[1], 2)

    def test_repaired_original_input_is_rejected(self):
        raw = fixture()
        marker = raw.rfind(b'\nxref\n')
        self.assertGreater(marker, 0)
        try:
            with fitz.open(stream=raw[:marker], filetype='pdf') as document:
                self.assertTrue(document.is_repaired)
                with self.assertRaisesRegex(ValueError, 'unchanged loaded PDF bytes'):
                    checker.original_page_pdfium(document[1], 2)
        finally:
            fitz.TOOLS.mupdf_warnings(reset=True)

    def test_rotated_or_nondefault_crop_geometry_is_rejected(self):
        for change in ('rotation', 'crop'):
            with self.subTest(change=change), fitz.open(stream=fixture(), filetype='pdf') as document:
                if change == 'rotation':
                    document[1].set_rotation(90)
                else:
                    document[1].set_cropbox((0, 0, 90, 90))
                raw = document.tobytes()
            with fitz.open(stream=raw, filetype='pdf') as document:
                with self.assertRaises(ValueError):
                    checker.original_page_pdfium(document[1], 2)

    def test_invalid_scale_is_rejected(self):
        with fitz.open(stream=fixture(), filetype='pdf') as document:
            for scale in (0, -1, float('nan'), float('inf'), True, '2'):
                with self.subTest(scale=scale), self.assertRaises(ValueError):
                    checker.original_page_pdfium(document[1], scale)


class IndependentGateTests(unittest.TestCase):
    def check(self, deltas=(0, 0), *, proof=1, text='', error_at=None, wrong_mapping=False, canonical=None):
        calls = []

        def render(page, scale):
            calls.append((page.parent is after, page.number, scale))
            if error_at == len(calls):
                raise ValueError('unproved renderer input')
            value = deltas[(0 if scale == 2 else 1)] if page.parent is after else 0
            mapping = (scale + .01, scale) if wrong_mapping and page.parent is after else (scale, scale)
            return Image.new('RGB', (20, 20), (value,) * 3), mapping, {'pageIndex': 1}

        image_proof = {'matched': proof}
        if canonical is not None:
            image_proof['reason'] = 'image bytes, paint, transform or clipping differs'
        with fitz.open(stream=fixture(), filetype='pdf') as before, \
                fitz.open(stream=fixture(changed=True, text=text), filetype='pdf') as after, \
                patch.object(checker, '_matched_image_difference', return_value=image_proof), \
                patch.object(checker, 'canonical_image_proof', return_value=({'matched': canonical}, {})), \
                patch.object(checker, 'original_page_pdfium', side_effect=render):
            result = checker.compare_page(before[1], after[1])
        return result, calls

    def test_both_resolutions_are_required_and_original_failures_remain(self):
        result, calls = self.check((8, 8))
        self.assertEqual(result['maxDelta'], 8)
        self.assertGreater(result['initialMaxDelta'], 8)
        self.assertTrue(all(value > 8 for value in result['imageSamplingPhaseDeltas']))
        self.assertEqual(calls, [(False, 1, 2), (True, 1, 2), (False, 1, 4), (True, 1, 4)])
        self.assertEqual([entry['dpi'] for entry in result['independentFullPageChecks']], [144, 288])

    def test_a_failure_at_either_resolution_is_not_accepted(self):
        for deltas in ((9, 0), (0, 9)):
            with self.subTest(deltas=deltas):
                result, _ = self.check(deltas)
                self.assertGreater(result['maxDelta'], 8)
                self.assertEqual([item['maxDelta'] for item in result['independentFullPageChecks']], list(deltas))

    def test_missing_image_identity_cannot_use_independent_renderer(self):
        result, calls = self.check(proof=0)
        self.assertGreater(result['maxDelta'], 8)
        self.assertEqual(calls, [])

    def test_changed_text_cannot_use_independent_renderer(self):
        result, calls = self.check(text='extra visible content')
        self.assertFalse(result['textEqual'])
        self.assertGreater(result['maxDelta'], 8)
        self.assertEqual(calls, [])

    def test_incomplete_independent_evidence_is_rejected(self):
        result, _ = self.check(error_at=4)
        self.assertGreater(result['maxDelta'], 8)
        self.assertIn('independentError', result)
        self.assertEqual(len(result['independentFullPageChecks']), 1)

    def test_different_pixel_mapping_is_rejected(self):
        result, _ = self.check(wrong_mapping=True)
        self.assertGreater(result['maxDelta'], 8)
        self.assertIn('coordinate mappings', result['independentError'])

    def test_lossless_identity_does_not_authorize_failing_original_pixels(self):
        for deltas in ((9, 0), (0, 9)):
            with self.subTest(deltas=deltas):
                result, calls = self.check(deltas, proof=0, canonical=1)
                self.assertEqual(result['initialImageSamplingProof']['matched'], 0)
                self.assertEqual(result['imageSamplingProof']['matched'], 1)
                self.assertEqual(len(calls), 4)
                self.assertGreater(result['maxDelta'], 8)

    def test_failed_lossless_identity_cannot_use_independent_renderer(self):
        result, calls = self.check(proof=0, canonical=0)
        self.assertEqual(result['imageSamplingProof']['matched'], 0)
        self.assertGreater(result['maxDelta'], 8)
        self.assertEqual(calls, [])


if __name__ == '__main__':
    unittest.main()
