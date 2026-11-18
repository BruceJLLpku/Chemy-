"""Synthetic device-level tests; no generated books or local fonts required."""
from io import BytesIO
import unittest
from unittest.mock import patch

import pymupdf as fitz
from PIL import Image, ImageChops
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from pdf_render_verify import (
    exact_paint_mask, filled_text_is_distant, scissors, stroke_states, text_ink_bounds,
)


def vector_document(prefix=b'', suffix=b''):
    doc = fitz.open()
    page = doc.new_page(width=220, height=180)
    stream = (b'q 20 20 m 210 20 l 180 150 l 20 150 l h W n\n'
              b'1.8 .37 .42 .65 9 11 cm 0 G 3 w 1 J 0 j '
              b'2 M [12 4] 3 d 10 40 m 80 40 l 20 43 l 70 60 l S Q\n')
    xref = doc.get_new_xref()
    doc.update_object(xref, '<<>>')
    doc.update_stream(xref, prefix + stream + suffix)
    page.set_contents(xref)
    return doc


def text_document():
    with fitz.open() as doc:
        page = doc.new_page(width=200, height=100)
        page.insert_text((10, 50), 'NH', fontsize=12)
        reader = PdfReader(BytesIO(doc.tobytes()))
    stream = DecodedStreamObject()
    stream.set_data(b'BT /helv 12 Tf 10 50 Td (N) Tj 150 0 Td (H) Tj ET')
    reader.pages[0][NameObject('/Contents')] = stream
    writer = PdfWriter()
    writer.add_page(reader.pages[0])
    output = BytesIO()
    writer.write(output)
    return fitz.open('pdf', output.getvalue())


def context_document(kind):
    doc = fitz.open()
    page = doc.new_page(width=100, height=100)
    resource = doc.get_new_xref()
    if kind == 'tile':
        doc.update_object(resource, '<< /Type /Pattern /PatternType 1 /PaintType 1 /TilingType 1 '
                          '/BBox [0 0 10 10] /XStep 10 /YStep 10 /Resources <<>> >>')
        doc.update_stream(resource, b'0 g 0 0 5 5 re f')
        resources = f'<< /Pattern << /P {resource} 0 R >> >>'
        content = b'/Pattern cs /P scn 0 0 100 100 re f'
    else:
        doc.update_object(resource, '<< /Type /XObject /Subtype /Form /BBox [0 0 100 100] '
                          '/Group << /S /Transparency /CS /DeviceGray >> /Resources <<>> >>')
        doc.update_stream(resource, b'1 g 0 0 100 100 re f')
        resources = f'<< /ExtGState << /GS << /SMask << /S /Luminosity /G {resource} 0 R >> >> >> >>'
        content = b'/GS gs 0 g 10 10 30 30 re f'
    doc.xref_set_key(page.xref, 'Resources', resources)
    xref = doc.get_new_xref()
    doc.update_object(xref, '<<>>')
    doc.update_stream(xref, content)
    page.set_contents(xref)
    return doc


class PaintEvidenceTests(unittest.TestCase):
    def support(self, point):
        mask = Image.new('L', (400, 200), 0)
        mask.putpixel(point, 255)
        return mask

    def test_selected_alpha_preserves_full_native_stroke_and_clip(self):
        with vector_document(b'0 g 1 1 4 4 re f\n', b'0 g 190 160 20 10 re f\n') as source, vector_document() as expected:
            for scale in (2, 4):
                for offset in ((0, 0), (.37, .23)):
                    with self.subTest(scale=scale, offset=offset):
                        actual, proof = exact_paint_mask(source[0], [1], scale=scale, offset=offset)
                        fitz.TOOLS.store_shrink(100)
                        pix = expected[0].get_pixmap(matrix=fitz.Matrix(scale, 0, 0, scale, *offset), alpha=True)
                        reference = Image.frombytes('RGBA', (pix.width, pix.height), pix.samples).getchannel('A')
                        self.assertIsNone(ImageChops.difference(actual, reference).getbbox())
                        self.assertEqual(proof[1]['miterlimit'], 2)
                        self.assertEqual(proof[1]['dash_list'], [12, 4])
                        self.assertIsNone(proof[1]['uniform_scale'])

    def test_stroke_state_is_copied_before_borrowed_pointer_expires(self):
        with vector_document() as doc:
            states = stroke_states(doc[0])
        # The document and every callback have ended; only Python values remain.
        self.assertEqual(states[0]['miterlimit'], 2)
        self.assertEqual(states[0]['dash_list'], [12, 4])
        self.assertEqual(states[0]['kind'], 'stroke-path')
        self.assertEqual(len(states[0]['ctm']), 6)

    def test_scissor_proves_only_definite_outside_bounds(self):
        with vector_document(b'q 0 0 1 1 re W n 10 10 2 2 re f Q\n'
                             b'q 0 0 1 1 re W n 10 10 2 2 re W n 10 10 2 2 re f Q\n') as doc:
            visibility = scissors(doc[0])
            self.assertTrue((visibility[0] & fitz.Rect(doc[0].get_bboxlog()[0][1])).is_empty)
            self.assertTrue(visibility[1].is_empty)
            self.assertFalse(visibility[2].is_empty)

    def test_text_ink_does_not_fill_the_gap_between_distant_glyphs(self):
        with text_document() as doc:
            before = doc[0].get_pixmap().samples
            ink = text_ink_bounds(doc[0])
            self.assertEqual(len(ink), 1)
            self.assertEqual(len(ink[0]), 2)
            self.assertTrue(filled_text_is_distant(ink[0], self.support((180, 90))))
            self.assertTrue(fitz.Rect(doc[0].get_bboxlog()[0][1]).contains(fitz.Point(90, 45)))
            self.assertEqual(before, doc[0].get_pixmap().samples)

    def test_actual_glyph_ink_and_antialias_margin_remain_protected(self):
        with text_document() as doc:
            ink = text_ink_bounds(doc[0])[0]
            bounds = fitz.Rect(ink[0]['bbox'])
            for point in ((round(bounds.x0*2), round(bounds.y0*2)),
                          (round(bounds.x1*2), round(bounds.y1*2))):
                self.assertFalse(filled_text_is_distant(ink, self.support(point)))
        self.assertFalse(filled_text_is_distant(None, self.support((10, 10))))

    def test_italic_ink_outside_the_metric_advance_box_is_protected(self):
        with fitz.open() as doc:
            page = doc.new_page(width=200, height=100)
            page.insert_text((20, 60), 'f', fontname='tiit', fontsize=40)
            fitz.TOOLS.store_shrink(100)
            pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
            image = Image.frombytes('RGB', (pix.width, pix.height), pix.samples)
            metric = fitz.Rect(page.get_texttrace()[0]['chars'][0][3])
            points = [(x, y) for y in range(image.height) for x in range(image.width)
                      if min(image.getpixel((x, y))) < 200
                      and not metric.contains(fitz.Point((x+.5)/2, (y+.5)/2))]
            self.assertTrue(points, 'fixture needs actual italic overhang')
            ink = text_ink_bounds(page)[0]
            for point in points:
                self.assertFalse(filled_text_is_distant(ink, self.support(point)))

    def test_paint_sequence_mismatch_fails_closed(self):
        with text_document() as doc, patch.object(fitz.Page, 'get_bboxlog', return_value=[]):
            for operation in (scissors, text_ink_bounds, stroke_states):
                with self.subTest(operation=operation.__name__), self.assertRaises(ValueError):
                    operation(doc[0])

    def test_missing_nonvector_and_invalid_selection_fail_closed(self):
        with vector_document() as doc:
            for selected in ([10], [-1], ['0']):
                with self.subTest(selected=selected), self.assertRaises(ValueError):
                    exact_paint_mask(doc[0], selected)
            for offset in (None, (0,), ('x', 0), (0, float('nan'))):
                with self.subTest(offset=offset), self.assertRaises(ValueError):
                    exact_paint_mask(doc[0], [0], offset=offset)
        with text_document() as doc, self.assertRaises(ValueError):
            exact_paint_mask(doc[0], [0])

    def test_soft_masks_and_tiles_are_not_approximated_as_selected_vectors(self):
        for kind in ('tile', 'soft-mask'):
            with self.subTest(kind=kind), context_document(kind) as doc, self.assertRaises(ValueError):
                exact_paint_mask(doc[0], [0])


if __name__ == '__main__':
    unittest.main()
