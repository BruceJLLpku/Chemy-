"""The verification device preserves ordinary drawing and disables tile reuse."""
from io import BytesIO
import unittest

from PIL import Image, ImageChops
import pymupdf as fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject

from pdf_render_verify import render_no_tile_cache, render_pdfium


def array(values):
    return ArrayObject([FloatObject(v) for v in values])


def drawing_sample():
    with fitz.open() as doc:
        page = doc.new_page(width=240, height=180)
        page.insert_text((12, 20), 'Native text: H2O 0123', fontsize=13)
        page.draw_rect(fitz.Rect(10, 35, 90, 85), color=(.2,.4,.8), fill=(.9,.2,.1),
                       width=2, fill_opacity=.4)
        page.draw_circle(fitz.Point(125, 60), 22, color=(0,.5,.2), width=3)
        image = Image.new('RGBA', (4,4), (10,70,220,110))
        image.putpixel((0,0), (230,40,20,255))
        png = BytesIO()
        image.save(png, format='PNG')
        page.insert_image(fitz.Rect(160,35,220,95), stream=png.getvalue())
        raw = doc.tobytes()
    writer = PdfWriter(clone_from=BytesIO(raw))
    page = writer.pages[0]
    function = DictionaryObject({NameObject('/FunctionType'):NumberObject(2),
        NameObject('/Domain'):array([0,1]), NameObject('/C0'):array([.1,.2,.8]),
        NameObject('/C1'):array([.8,.7,.1]), NameObject('/N'):NumberObject(1)})
    shading = DictionaryObject({NameObject('/ShadingType'):NumberObject(2),
        NameObject('/ColorSpace'):NameObject('/DeviceRGB'), NameObject('/Coords'):array([10,30,220,30]),
        NameObject('/Function'):function})
    page['/Resources'][NameObject('/Shading')] = DictionaryObject({NameObject('/TestShade'):shading})
    stream = DecodedStreamObject()
    stream.set_data(b'q 10 15 210 35 re W n /TestShade sh Q\n')
    previous = page.get('/Contents')
    previous = previous.get_object()
    page[NameObject('/Contents')] = ArrayObject([*previous,writer._add_object(stream)]
        if isinstance(previous,ArrayObject) else [writer._add_object(previous),writer._add_object(stream)])
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


class RenderVerifyTests(unittest.TestCase):
    def test_text_paths_rgba_image_transparency_and_shading_match(self):
        with fitz.open('pdf', drawing_sample()) as doc:
            for scale in (1,2,2.5):
                for offset in ((0,0),(.37,.23),(.73,.61)):
                    with self.subTest(scale=scale,offset=offset):
                        expected = doc[0].get_pixmap(matrix=fitz.Matrix(scale,0,0,scale,*offset),alpha=False)
                        actual = render_no_tile_cache(doc[0],scale,offset=offset)
                        self.assertEqual((actual.width,actual.height,actual.n,actual.x,actual.y),
                                         (expected.width,expected.height,expected.n,expected.x,expected.y))
                        before = Image.frombytes('RGB',(expected.width,expected.height),expected.samples)
                        after = Image.frombytes('RGB',(actual.width,actual.height),actual.samples)
                        self.assertIsNone(ImageChops.difference(before,after).getbbox())

    def test_invalid_scale_fails(self):
        with fitz.open('pdf', drawing_sample()) as doc:
            for scale in (0,-1,float('inf'),float('nan')):
                with self.subTest(scale=scale), self.assertRaises(ValueError):
                    render_no_tile_cache(doc[0],scale)

    def test_invalid_offset_fails(self):
        with fitz.open('pdf', drawing_sample()) as doc:
            for offset in (None,(0,),('x',0),(0,float('nan')),(float('inf'),0)):
                with self.subTest(offset=offset), self.assertRaises(ValueError):
                    render_no_tile_cache(doc[0],offset=offset)


class PdfiumRenderTests(unittest.TestCase):
    def test_independent_render_is_deterministic_and_preserves_bitmap_ownership(self):
        raw=drawing_sample()
        for scale in (2,4):
            first,mapping=render_pdfium(raw,(240,180),scale)
            second,other=render_pdfium(raw,(240,180),scale)
            self.assertEqual(first.mode,'RGB')
            self.assertEqual(mapping,(scale,scale))
            self.assertEqual(mapping,other)
            self.assertIsNone(ImageChops.difference(first,second).getbbox())
            self.assertLess(min(first.getpixel((30*scale,60*scale))),250)

    def test_fractional_page_dimensions_return_actual_axis_scales(self):
        with fitz.open() as doc:
            page=doc.new_page(width=100.3,height=80.7)
            size=(page.rect.width,page.rect.height)
            raw=doc.tobytes(garbage=1)
        image,mapping=render_pdfium(raw,size,2)
        self.assertEqual(image.size,(201,162))
        self.assertEqual(mapping,(201/size[0],162/size[1]))

    def test_rotation_crop_page_count_or_expected_geometry_mismatch_rejects(self):
        raw=drawing_sample()
        for mutation in ('rotation','crop','count','size'):
            with self.subTest(mutation=mutation),fitz.open('pdf',raw) as doc:
                size=(240,180)
                if mutation=='rotation':doc[0].set_rotation(90)
                if mutation=='crop':doc[0].set_cropbox(fitz.Rect(0,0,200,170))
                if mutation=='count':doc.new_page()
                if mutation=='size':size=(241,180)
                with self.assertRaises(ValueError):
                    render_pdfium(doc.tobytes(garbage=1),size,2)

    def test_missing_thin_bond_body_character_or_image_remains_visible(self):
        for kind in ('bond','text','image','moved'):
            documents=[]
            for source in (True,False):
                with fitz.open() as doc:
                    page=doc.new_page(width=100,height=100)
                    page.draw_line((10,80),(90,80),width=.3)
                    if source:
                        if kind=='bond':page.draw_line((30,40),(50,46),width=.3)
                        elif kind=='text':page.insert_text((30,40),'p',fontsize=8)
                        elif kind=='image':
                            png=BytesIO();Image.new('RGB',(1,1),'black').save(png,format='PNG')
                            page.insert_image((30,40,31,41),stream=png.getvalue())
                    if kind=='moved':page.draw_line((30+(.5 if source else 0),40),(50,46),width=.3)
                    documents.append(doc.tobytes(garbage=1))
            for scale in (2,4):
                with self.subTest(kind=kind,scale=scale):
                    images=[render_pdfium(raw,(100,100),scale)[0] for raw in documents]
                    self.assertGreater(max(v[1] for v in ImageChops.difference(*images).getextrema()),8)

    def test_invalid_scale_rejects(self):
        for scale in (0,-1,float('inf'),float('nan')):
            with self.assertRaises(ValueError):
                render_pdfium(drawing_sample(),(240,180),scale)

    def test_deleted_graphic_cannot_borrow_matching_number_labels_in_pdfium(self):
        from pdf_clip_cleanup import _label_coverage
        from test_pdf_label_ownership import graphic_pair

        for kind in ('fill','image'):
            original,cleaned=graphic_pair(kind)
            for scale in (2,4):
                with self.subTest(kind=kind,scale=scale),fitz.open('pdf',original) as a,fitz.open('pdf',cleaned) as b:
                    before,mapping=render_pdfium(original,(100,100),scale)
                    after,other=render_pdfium(cleaned,(100,100),scale)
                    self.assertEqual(mapping,other)
                    proof=_label_coverage(a[0],b[0],[(10,72.5,40,85)],
                                          before,after,scale=mapping)
                    self.assertEqual(proof['count'],0)
                    self.assertGreater(proof['unprovenMax'],8)


if __name__ == '__main__':
    unittest.main()
