"""Small generated fixtures for validator-only lossless image verification."""
from io import BytesIO
import math
import unittest
import zlib

import pymupdf as fitz
from PIL import Image
from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject, BooleanObject, DictionaryObject, NameObject, NullObject,
    NumberObject,
)

import pdf_clip_cleanup as cleaner
from pdf_image_verify import canonical_image_proof, _canonical_copy
from test_pdf_image_sampling import sample


def fixture(level, *, change=None, shift=0, clip=None, opacity=1,
            conflicting_mask=False, null_parameters=False):
    """Encode identical generated RGB/mask samples at a requested Flate level."""
    writer = PdfWriter(clone_from=BytesIO(sample(
        shift=shift, clip=clip, opacity=opacity,
    )))
    page = writer.pages[0]
    resources = page['/Resources']['/XObject']
    image = next(iter(resources.values())).get_object()
    if conflicting_mask:
        alternate = PdfWriter(clone_from=BytesIO(sample(mask=64)))
        other = next(iter(alternate.pages[0]['/Resources']['/XObject'].values()))
        resources[NameObject('/UnusedMaskVariant')] = other.clone(writer)
    seen = set()

    def encode(reference):
        obj = reference.get_object()
        identity = getattr(reference, 'idnum', id(obj))
        if identity in seen:
            return
        seen.add(identity)
        decoded = obj.get_data()
        if obj is image and change == 'rgb':
            decoded = bytes([decoded[0] ^ 255]) + decoded[1:]
        if reference is image.get('/SMask') and change == 'mask':
            decoded = bytes([decoded[0] ^ 255]) + decoded[1:]
        obj._data = zlib.compress(decoded, level)
        obj[NameObject('/Filter')] = NameObject('/FlateDecode')
        obj.pop('/DecodeParms', None)
        if null_parameters:
            obj[NameObject('/DecodeParms')] = NullObject()
        for name in ('/SMask', '/Mask'):
            child = obj.get(name)
            if hasattr(child, 'idnum'):
                encode(child)

    for reference in resources.values():
        if reference.get_object().get('/Subtype') == '/Image':
            encode(reference)
    if change == 'decode':
        image[NameObject('/Decode')] = ArrayObject([
            NumberObject(value) for value in (1, 0, 1, 0, 1, 0)
        ])
    elif change == 'interpolate':
        image[NameObject('/Interpolate')] = BooleanObject(True)
    elif change == 'parameters':
        image[NameObject('/DecodeParms')] = DictionaryObject({
            NameObject('/Predictor'): NumberObject(1),
        })
    elif change == 'filter':
        image._data = zlib.decompress(image._data).hex().encode() + b'>'
        image[NameObject('/Filter')] = NameObject('/ASCIIHexDecode')
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def sampling_difference(page):
    """Supply a one-pixel image sampling discrepancy to the identity proof.

    The helper does not render an oracle. Its contract receives the caller's
    discrepancy; actual whole-page raster acceptance is tested separately.
    """
    bounds = fitz.Rect(page.get_image_info()[0]['bbox'])
    pixel = (math.floor((bounds.x0 + bounds.x1)),
             math.floor((bounds.y0 + bounds.y1)))
    difference = Image.new('RGB', (200, 200), (0, 0, 0))
    difference.putpixel(pixel, (64, 64, 64))
    return difference


class LosslessImageVerificationTests(unittest.TestCase):
    def assert_rejected(self, first, second):
        with fitz.open(stream=first, filetype='pdf') as before, \
                fitz.open(stream=second, filetype='pdf') as after:
            difference = sampling_difference(before[0])
            proof, _ = canonical_image_proof(before[0], after[0], difference)
            self.assertEqual(proof['matched'], 0, proof)

    def test_different_lossless_encodings_keep_the_complete_original_proof(self):
        with fitz.open(stream=fixture(1), filetype='pdf') as before, \
                fitz.open(stream=fixture(9), filetype='pdf') as after:
            difference = sampling_difference(before[0])
            original = cleaner._matched_image_difference(before[0], after[0], difference)
            self.assertEqual(original['matched'], 0)
            proof, evidence = canonical_image_proof(before[0], after[0], difference)
            self.assertEqual(proof['matched'], 1, proof)
            for side in evidence.values():
                self.assertEqual(len(side['operations']), 2)
                self.assertTrue(side['oracleUseForbidden'])
                self.assertTrue(all(row['decodedUnchanged']
                                    and row['dictionaryUnchanged']
                                    for row in side['operations']))

    def test_explicit_null_parameters_are_preserved_as_null(self):
        with fitz.open(stream=fixture(1, null_parameters=True), filetype='pdf') as before, \
                fitz.open(stream=fixture(9, null_parameters=True), filetype='pdf') as after:
            proof, _ = canonical_image_proof(before[0], after[0], sampling_difference(before[0]))
            self.assertEqual(proof['matched'], 1, proof)
            copied, _ = _canonical_copy(before[0])
            try:
                for xref in cleaner._image_resource_xrefs(copied[0]):
                    self.assertIn('DecodeParms', copied.xref_get_keys(xref))
                    self.assertEqual(copied.xref_get_key(xref, 'DecodeParms'), ('null', 'null'))
            finally:
                copied.close()

    def test_one_decoded_rgb_byte_change_is_rejected(self):
        self.assert_rejected(fixture(1), fixture(9, change='rgb'))

    def test_one_decoded_smask_byte_change_is_rejected(self):
        self.assert_rejected(fixture(1), fixture(9, change='mask'))

    def test_decode_and_interpolation_changes_are_rejected(self):
        for change in ('decode', 'interpolate'):
            with self.subTest(change=change):
                self.assert_rejected(fixture(1), fixture(9, change=change))

    def test_transform_clipping_and_opacity_changes_are_rejected(self):
        changes = [
            {'shift': .2},
            {'clip': b'40.184 49.3461 m 43.9 49.3461 l 43.9 59.4941 l h'},
            {'opacity': .5},
        ]
        for change in changes:
            with self.subTest(change=change):
                self.assert_rejected(fixture(1), fixture(9, **change))

    def test_same_rgb_with_an_unused_different_mask_remains_ambiguous(self):
        with fitz.open(stream=fixture(1, conflicting_mask=True), filetype='pdf') as before, \
                fitz.open(stream=fixture(9), filetype='pdf') as after:
            proof, _ = canonical_image_proof(before[0], after[0], sampling_difference(before[0]))
            self.assertEqual(proof['matched'], 0, proof)
            self.assertEqual(proof['reason'], 'unsupported image resource')

    def test_other_filters_and_nonempty_parameters_are_not_normalized(self):
        for change in ('filter', 'parameters'):
            with self.subTest(change=change), \
                    fitz.open(stream=fixture(1, change=change), filetype='pdf') as original:
                copied, evidence = _canonical_copy(original[0])
                try:
                    xref = cleaner._image_resource_xrefs(copied[0])[0]
                    self.assertNotIn(xref, [row['xref'] for row in evidence['operations']])
                    original_xref = cleaner._image_resource_xrefs(original[0])[0]
                    self.assertEqual(copied.xref_stream_raw(xref), original.xref_stream_raw(original_xref))
                finally:
                    copied.close()
            self.assert_rejected(fixture(1), fixture(9, change=change))

    def test_original_inputs_remain_byte_identical_and_clean(self):
        first, second = fixture(1), fixture(9)
        with fitz.open(stream=first, filetype='pdf') as before, \
                fitz.open(stream=second, filetype='pdf') as after:
            first_stream, second_stream = before.stream, after.stream
            canonical_image_proof(before[0], after[0], sampling_difference(before[0]))
            self.assertIs(before.stream, first_stream)
            self.assertIs(after.stream, second_stream)
            self.assertEqual(before.stream, first)
            self.assertEqual(after.stream, second)
            self.assertFalse(before.is_dirty)
            self.assertFalse(after.is_dirty)

    def test_dirty_or_missing_original_byte_stream_is_rejected(self):
        with fitz.open(stream=fixture(1), filetype='pdf') as dirty:
            dirty[0].insert_text((10, 10), 'changed')
            with self.assertRaises(ValueError):
                _canonical_copy(dirty[0])
        with fitz.open() as generated:
            generated.new_page()
            with self.assertRaises(ValueError):
                _canonical_copy(generated[0])


if __name__ == '__main__':
    unittest.main()
