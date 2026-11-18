"""A valid numbering pair cannot conceal loss of overlapping body content."""
from copy import deepcopy
from io import BytesIO
from types import SimpleNamespace
import unittest

import pymupdf as fitz
from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, NameObject

from pdf_clip_cleanup import _label_coverage, _unmatched_nonlabel_glyphs


def span(text):
    return {'font': 'NumberingFont', 'type': 0, 'wmode': 0, 'flags': 16,
            'colorspace': 3, 'layer': '', 'size': 12., 'opacity': 1.,
            'linewidth': None, 'dir': (1., 0.), 'color': (0., 0., 0.),
            'bbox': (10., 10., 40., 30.),
            'chars': [(ord(c), ord(c), (15.+i, 25.), (10., 10., 40., 30.))
                      for i, c in enumerate(text)]}


class TracePage:
    transformation_matrix = fitz.Matrix(1, 1)

    def __init__(self, image, spans):
        self.image, self.spans = image, spans

    def get_pixmap(self, **kwargs):
        return SimpleNamespace(width=self.image.width, height=self.image.height,
                               samples=self.image.tobytes())

    def get_texttrace(self):
        return self.spans


def numbering_pair():
    before, after = Image.new('RGB', (128, 100), 'white'), Image.new('RGB', (128, 100), 'white')
    before.putpixel((30, 20), (100, 100, 100))
    return TracePage(before, [span('6-1'), span('42-1')]), TracePage(after, [span('42-1')])


def coverage(before, after, holes=((10, 10, 40, 30),)):
    images = []
    for page in (before, after):
        fitz.TOOLS.store_shrink(100)
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
        images.append(Image.frombytes('RGB', (pix.width, pix.height), pix.samples))
    return _label_coverage(before, after, holes, *images)


def graphic_pair(kind):
    result = []
    for original in (True, False):
        with fitz.open() as doc:
            page = doc.new_page(width=100, height=100)
            if original:
                page.insert_text((15, 25), '6-1', fontsize=12)
                xref = page.get_contents()[0]
                doc.update_stream(xref, b'q 0 0 1 1 re W n\n' + doc.xref_stream(xref) + b'\nQ')
            page.insert_text((15, 25), '42-1', fontsize=12)
            if original:
                if kind == 'fill':
                    page.draw_rect((16, 27, 16.5, 27.5), color=None, fill=(0, 0, 0))
                else:
                    image = Image.new('RGB', (1, 1), 'black')
                    buffer = BytesIO()
                    image.save(buffer, format='PNG')
                    page.insert_image((16, 27, 16.5, 27.5), stream=buffer.getvalue(), keep_proportion=False)
            result.append(doc.tobytes(garbage=1))
    return result


def body_paint_pair(first,second,*,hidden_prefix=False):
    result=[]
    for source,paints in ((True,first),(False,second)):
        with fitz.open() as doc:
            page=doc.new_page(width=595.2755737304688,height=841.8900146484375)
            if source:
                page.insert_text((15,25),'6-1',fontsize=12)
                xref=page.get_contents()[-1]
                doc.update_stream(xref,b'q 0 0 1 1 re W n\n'+doc.xref_stream(xref)+b'\nQ')
            page.insert_text((15,25),'42-1',fontsize=12)
            if source and hidden_prefix:
                page.insert_text((16,27.5),'p',fontsize=.8)
                xref=page.get_contents()[-1]
                doc.update_stream(xref,b'q 0 0 1 1 re W n\n'+doc.xref_stream(xref)+b'\nQ')
            for color in paints:
                page.insert_text((16,27.5),'p',fontsize=.8,color=color)
            result.append(doc.tobytes(garbage=1))
    return result


class LabelOwnershipTests(unittest.TestCase):
    def test_deleted_overlapping_chemical_glyph_cannot_borrow_numbering(self):
        before, after = numbering_pair()
        before.spans.append(span('p'))
        self.assertEqual(coverage(before, after)['count'], 0)

    def test_changed_overlapping_chemical_glyph_cannot_borrow_numbering(self):
        for reason in ('unicode', 'glyph', 'move', 'color'):
            with self.subTest(reason=reason):
                before, after = numbering_pair()
                body = span('p')
                before.spans.append(body)
                after.spans.append(deepcopy(body))
                target = after.spans[-1]
                if reason == 'color':
                    target['color'] = (1, 0, 0)
                else:
                    char = list(target['chars'][0])
                    if reason == 'unicode': char[0] = ord('q')
                    if reason == 'glyph': char[1] += 1
                    if reason == 'move': char[2] = (char[2][0]+.5, char[2][1])
                    target['chars'][0] = tuple(char)
                self.assertEqual(coverage(before, after)['count'], 0)

    def test_unchanged_overlapping_body_preserves_a_proven_number_edge(self):
        before, after = numbering_pair()
        before.spans.append(span('p'))
        after.spans.append(span('p'))
        self.assertEqual(coverage(before, after)['count'], 1)

    def test_clipping_proof_excludes_only_definitely_hidden_body(self):
        with fitz.open() as doc:
            doc.new_page(width=100, height=100).insert_text((30, 50), 'p', fontsize=12)
            raw = doc.tobytes()
        reader = PdfReader(BytesIO(raw))
        stream = DecodedStreamObject()
        stream.set_data(b'q 0 0 10 10 re W n\n' + reader.pages[0].get_contents().get_data() + b'\nQ')
        reader.pages[0][NameObject('/Contents')] = stream
        writer, output = PdfWriter(), BytesIO()
        writer.add_page(reader.pages[0])
        writer.write(output)
        with fitz.open('pdf', output.getvalue()) as hidden, fitz.open('pdf', raw) as visible, fitz.open() as blank:
            blank.new_page(width=100, height=100)
            self.assertTrue(_unmatched_nonlabel_glyphs(visible[0], blank[0]))
            self.assertFalse(_unmatched_nonlabel_glyphs(hidden[0], blank[0]))

    def test_deleted_real_fill_or_image_cannot_borrow_hidden_old_number(self):
        for kind in ('fill', 'image'):
            with self.subTest(kind=kind):
                original, cleaned = graphic_pair(kind)
                with fitz.open('pdf', original) as before, fitz.open('pdf', cleaned) as after:
                    proof = coverage(before[0], after[0], [(10, 72.5, 40, 85)])
                self.assertEqual(proof['count'], 0)
                self.assertGreater(proof['unprovenMax'], 8)

    def test_visible_body_paint_count_order_and_color_cannot_borrow_old_number(self):
        black,gray,red=(0,0,0),(.5,.5,.5),(1,0,0)
        cases=[([black,black],[black]),([black],[black,black]),
               ([gray,black],[black,gray]),([black],[red])]
        for first,second in cases:
            with self.subTest(first=first,second=second):
                original,cleaned=body_paint_pair(first,second)
                with fitz.open('pdf',original)as a,fitz.open('pdf',cleaned)as b:
                    self.assertTrue(_unmatched_nonlabel_glyphs(a[0],b[0]))
                    holes=[(10,a[0].rect.height-27.5,40,a[0].rect.height-15)]
                    proof=coverage(a[0],b[0],holes)
                    self.assertGreater(proof['unprovenMax'],8,proof)

    def test_hidden_body_duplicate_does_not_consume_visible_match(self):
        black=(0,0,0)
        original,cleaned=body_paint_pair([black,black],[black,black],hidden_prefix=True)
        with fitz.open('pdf',original)as a,fitz.open('pdf',cleaned)as b:
            self.assertFalse(_unmatched_nonlabel_glyphs(a[0],b[0]))


if __name__ == '__main__':
    unittest.main()
