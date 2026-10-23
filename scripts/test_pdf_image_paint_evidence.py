from io import BytesIO
import unittest
from unittest.mock import patch
import pymupdf as fitz
from PIL import Image
from pdf_render_verify import image_paints


def fixture(*,clip=None,mask=128,interpolate=False,decode=False,layer=False):
    png=BytesIO();image=Image.new('RGBA',(3,3),(80,150,230,mask))
    image.putpixel((1,1),(200,40,60,255));image.save(png,format='PNG')
    with fitz.open() as doc:
        page=doc.new_page(width=100,height=100)
        oc=doc.add_ocg('optional image') if layer else 0
        xref=page.insert_image((40,40,60,60),stream=png.getvalue(),oc=oc)
        # PyMuPDF inserts its sRGB ICC profile by default; this gate deliberately
        # covers only explicit DeviceRGB/Gray so fixtures must use that subset.
        doc.xref_set_key(xref,'ColorSpace','/DeviceRGB')
        if layer:
            resource=int(doc.xref_get_key(page.xref,'Resources')[1].split()[0])
            doc.xref_set_key(resource,'Properties',f'<< /Layer {oc} 0 R >>')
            content=page.get_contents()[0]
            doc.update_stream(content,b'/OC /Layer BDC\n'+doc.xref_stream(content)+b'\nEMC')
        if interpolate:doc.xref_set_key(xref,'Interpolate','true')
        if decode:doc.xref_set_key(xref,'Decode','[1 0 1 0 1 0]')
        if clip:
            content=page.get_contents()[0]
            doc.update_stream(content,b'q '+clip+b' W* n\n'+doc.xref_stream(content)+b'\nQ')
        return doc.tobytes(garbage=1)


def evidence(raw):
    with fitz.open('pdf',raw) as doc:return image_paints(doc[0])


class ImagePaintEvidenceTests(unittest.TestCase):
    def test_intrinsic_mask_and_real_pixels_are_copied(self):
        state=evidence(fixture())['images'][0]
        self.assertTrue(state['context_safe'])
        self.assertEqual(state['native_image'][:4],(3,3,8,3))
        self.assertTrue(any(clip[0]=='image-mask' for clip in state['clip_context']))
        self.assertEqual(state,evidence(fixture())['images'][0])

    def test_rectangular_hole_with_identical_outer_scissor_changes_state(self):
        before=evidence(fixture(clip=b'40 40 20 20 re'))
        after=evidence(fixture(clip=b'40 40 20 20 re 47 47 6 6 re'))
        self.assertEqual(before['scissors'],after['scissors'])
        self.assertTrue(before['images'][0]['context_safe'])
        self.assertTrue(after['images'][0]['context_safe'])
        self.assertNotEqual(before['images'][0]['clip_context'],after['images'][0]['clip_context'])

    def test_remote_hole_has_proven_no_effect_on_entire_image(self):
        plain=evidence(fixture())['images'][0]
        clipped=evidence(fixture(clip=b'0 0 100 100 re 10 10 5 5 re'))['images'][0]
        self.assertTrue(clipped['context_safe'])
        self.assertEqual(plain,clipped)

    def test_triangle_clip_and_optional_layer_are_not_proved(self):
        for options in ({'clip':b'40 40 m 60 40 l 60 60 l h'},{'layer':True}):
            with self.subTest(options=options):
                state=evidence(fixture(**options))['images'][0]
                self.assertFalse(state['context_safe'])

    def test_interpolation_decode_and_mask_changes_are_visible_in_evidence(self):
        plain=evidence(fixture())['images'][0]
        for change in ({'interpolate':True},{'decode':True},{'mask':64}):
            with self.subTest(change=change):
                state=evidence(fixture(**change))['images'][0]
                self.assertNotEqual(plain,state)

    def test_unmatched_paint_sequence_is_rejected(self):
        with fitz.open('pdf',fixture()) as doc:
            with patch.object(fitz.Page,'get_bboxlog',return_value=[]):
                with self.assertRaisesRegex(ValueError,'sequence mismatch'):image_paints(doc[0])


if __name__=='__main__':unittest.main()
