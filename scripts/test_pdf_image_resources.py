"""Synthetic image-resource invariants; no external PDFs or fonts are needed.

This fixture does not reproduce MuPDF's object-renumbering bug by itself. It
checks the required behaviour through the real temporary filter and final save:
aliases, distinct alpha masks, partially clipped images and text remain intact.
"""
from io import BytesIO
import unittest

import pymupdf as fitz
from PIL import Image, ImageChops
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ContentStream, DecodedStreamObject, DictionaryObject,
                           FloatObject, NameObject, NumberObject, TextStringObject)
from pdf_clip_cleanup import _filter, clean_source_page


def image_resource_fixture():
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    # Interleave dead objects, live images, and nonimage objects. Xref identity
    # must not be relied on after the temporary PDF has been serialized.
    writer._add_object(TextStringObject('unreferenced padding'))
    rgb = bytes([255,0,0, 0,255,0, 0,0,255, 255,255,0])

    def image(pixels, colour):
        obj = DecodedStreamObject()
        obj.set_data(pixels)
        obj.update({NameObject('/Type'):NameObject('/XObject'),
                    NameObject('/Subtype'):NameObject('/Image'),
                    NameObject('/Width'):NumberObject(2),
                    NameObject('/Height'):NumberObject(2),
                    NameObject('/ColorSpace'):NameObject(colour),
                    NameObject('/BitsPerComponent'):NumberObject(8)})
        return obj

    images = []
    for alpha in [bytes([0,64,128,255]), bytes([255,128,64,0])]:
        mask = writer._add_object(image(alpha, '/DeviceGray'))
        obj = image(rgb, '/DeviceRGB')
        obj[NameObject('/SMask')] = mask
        images.append(writer._add_object(obj))
        writer._add_object(TextStringObject('unused between images'))
    opaque = writer._add_object(image(rgb, '/DeviceRGB'))
    unused = writer._add_object(image(b'\xff\x00\xff'*4, '/DeviceRGB'))
    font = writer._add_object(DictionaryObject({NameObject('/Type'):NameObject('/Font'),
        NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')}))
    resources = DictionaryObject({
        NameObject('/XObject'):DictionaryObject({
            NameObject('/RGBA'):images[0],NameObject('/RGBAAlias'):images[0],
            NameObject('/OtherAlpha'):images[1],NameObject('/Opaque'):opaque,
            NameObject('/Unused'):unused}),
        NameObject('/Font'):DictionaryObject({NameObject('/F'):font}),
        NameObject('/ExtGState'):DictionaryObject({NameObject('/Half'):DictionaryObject({
            NameObject('/Type'):NameObject('/ExtGState'),NameObject('/ca'):FloatObject(.5),
            NameObject('/CA'):FloatObject(.5)})})})
    stream = DecodedStreamObject()
    stream.set_data(b'''q 0 0 180 200 re W n
.8 .9 1 rg 0 0 180 200 re f
q 30 0 0 30 20 30 cm /RGBA Do Q
q 30 0 0 30 60 30 cm /RGBAAlias Do Q
q 30 0 0 30 100 30 cm /OtherAlpha Do Q
q /Half gs 30 0 0 30 140 30 cm /RGBAAlias Do Q
q 30 0 0 30 170 80 cm /Opaque Do Q
q 30 0 0 30 220 30 cm /Unused Do Q
BT /F 12 Tf 20 150 Td (KEEP) Tj 200 0 Td (HIDDEN) Tj ET
Q''')
    page[NameObject('/Resources')] = resources
    page[NameObject('/Contents')] = writer._add_object(stream)
    out = BytesIO()
    writer.write(out)
    return out.getvalue()


def resource_evidence(reader):
    page = reader.pages[0]
    resources = page['/Resources']
    image_calls = []
    for args, op in ContentStream(page['/Contents'], reader).operations:
        if op != b'Do':
            continue
        obj = resources['/XObject'][args[0]]
        # A reference wrongly remapped to a string/font-width array fails here.
        if not isinstance(obj, DictionaryObject) or obj.get('/Subtype') != '/Image':
            raise AssertionError(f'{args[0]} no longer resolves to an image')
        if (obj['/Width'],obj['/Height'],obj['/ColorSpace'],obj['/BitsPerComponent']) != (2,2,'/DeviceRGB',8):
            raise AssertionError('image metadata changed')
        pixels = obj.get_data()
        mask = obj.get('/SMask')
        if mask is not None:
            mask = mask.get_object()
            if (not isinstance(mask,DictionaryObject) or mask.get('/Subtype') != '/Image'
                    or mask.get('/ColorSpace') != '/DeviceGray'
                    or (mask.get('/Width'),mask.get('/Height')) != (2,2)):
                raise AssertionError('alpha mask reference changed')
        image_calls.append((pixels,mask.get_data() if mask is not None else None))
    return image_calls


def render(raw):
    fitz.TOOLS.store_shrink(100)
    with fitz.open('pdf',raw) as doc:
        fitz.TOOLS.mupdf_warnings(reset=True)
        pix = doc[0].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
        image = Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
        text = doc[0].get_text()
        warnings = fitz.TOOLS.mupdf_warnings(reset=True)
    return image,text,warnings


class FilterImageResourceTests(unittest.TestCase):
    def setUp(self):
        self.source = image_resource_fixture()
        self.reader = PdfReader(BytesIO(self.source))

    def assert_kept_image_resources(self, reader):
        calls = resource_evidence(reader)
        rgb = bytes([255,0,0,0,255,0,0,0,255,255,255,0])
        alpha1,alpha2 = bytes([0,64,128,255]),bytes([255,128,64,0])
        self.assertEqual(calls,[(rgb,alpha1),(rgb,alpha1),(rgb,alpha2),(rgb,alpha1),(rgb,None)])

    def assert_same_visible_content(self, result):
        before,_,before_warnings = render(self.source)
        after,text,after_warnings = render(result)
        self.assertFalse(before_warnings,before_warnings)
        self.assertFalse(after_warnings,after_warnings)
        self.assertEqual(ImageChops.difference(before,after).getbbox(),None)
        self.assertIn('KEEP',text)
        self.assertNotIn('HIDDEN',text)

    def test_temporary_filter_preserves_image_aliases_and_independent_alpha(self):
        page = self.reader.pages[0]
        stats = {'removed_glyphs':0,'removed_objects':0}
        filtered = _filter(ContentStream(page['/Contents'],self.reader).operations,
            page['/Resources'],page.mediabox, ([(0,0,180,200)],[]),stats)
        self.assert_kept_image_resources(filtered)
        self.assertGreater(stats['removed_objects'],0)
        self.assertGreater(stats['removed_glyphs'],0)
        filtered.stream.seek(0)
        self.assert_same_visible_content(filtered.stream.read())

    def test_final_cleanup_keeps_images_after_pdf_reparse_and_compact_save(self):
        stats = {}
        raw = clean_source_page(self.reader.pages[0],self.reader,diagnostics=stats)
        result = PdfReader(BytesIO(raw))
        self.assert_kept_image_resources(result)
        self.assert_same_visible_content(raw)
        self.assertGreater(stats['removed_objects'],0)
        self.assertEqual(stats['render_max_delta'],0)


if __name__ == '__main__':
    unittest.main()
