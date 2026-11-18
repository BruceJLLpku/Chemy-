from io import BytesIO
from functools import lru_cache
from pathlib import Path
import re,unittest
from unittest.mock import patch
import pymupdf as fitz
from PIL import Image,ImageChops
from pypdf import PdfReader,PdfWriter
from pypdf.generic import ArrayObject,DictionaryObject,NameObject,FloatObject,NumberObject,DecodedStreamObject
import pdf_clip_cleanup as cleaner
from pdf_clip_cleanup import _matched_image_difference as matched_image_difference
from test_pdf_cleanup_validation import real_pair
from pdf_watermark import strip_watermark

def sample(*,copies=1,shift=0,color=(0,0,0),mask=128,opacity=1,text=False,line=False,blend='Normal',clip=None,backdrop=False):
    image=Image.new('RGBA',(13,39),(*color,mask))
    for y in range(39):image.putpixel((y%13,y),(*color,255))
    png=BytesIO();image.save(png,format='PNG')
    with fitz.open()as doc:
        page=doc.new_page(width=100,height=100)
        if backdrop:page.draw_rect((35,35,50,55),color=None,fill=(.6,.6,.6))
        for _ in range(copies):
            xref=page.insert_image((40.184+shift,40.5059,43.900+shift,50.6539),stream=png.getvalue())
            doc.xref_set_key(xref,'ColorSpace','/DeviceRGB')
        if text:page.insert_text((40.5,45),'p',fontsize=4)
        if line:page.draw_line((40.5,41),(43,49),width=.3)
        if clip:
            xref=page.get_contents()[0]
            doc.update_stream(xref,b'q '+clip+b' W n\n'+doc.xref_stream(xref)+b'\nQ')
        raw=doc.tobytes(garbage=1)
    if opacity!=1 or blend!='Normal':
        writer=PdfWriter(clone_from=BytesIO(raw));page=writer.pages[0]
        resources=page['/Resources'];resources[NameObject('/ExtGState')]=DictionaryObject({NameObject('/Fade'):DictionaryObject({NameObject('/ca'):FloatObject(opacity),NameObject('/BM'):NameObject('/'+blend)})})
        stream=DecodedStreamObject();stream.set_data(b'q /Fade gs\n'+page.get_contents().get_data()+b'\nQ')
        page[NameObject('/Contents')]=writer._add_object(stream)
        out=BytesIO();writer.write(out);raw=out.getvalue()
    return raw

def render(page,offset=(0,0)):
    fitz.TOOLS.store_shrink(100)
    pix=page.get_pixmap(matrix=fitz.Matrix(2,0,0,2,*offset),alpha=False)
    return Image.frombytes('RGB',(pix.width,pix.height),pix.samples)

class ImageSamplingTest(unittest.TestCase):
    def proof(self,first,second):
        with fitz.open('pdf',first)as a,fitz.open('pdf',second)as b:
            images=[render(p)for p in (a[0],b[0])]
            diff=ImageChops.difference(*images)
            self.assertGreater(max(v[1]for v in diff.getextrema()),8)
            return matched_image_difference(a[0],b[0],diff)
    def test_real_image_sampling_has_identical_call_and_strict_phases(self):
        _,_,stats=real_pair('inference-questions',72)
        self.assertEqual(stats['render_initial_max_delta'],116)
        self.assertEqual(stats['image_sampling_proof']['matched'],1)
        self.assertEqual(stats['image_sampling_phase_deltas'],[0,0])
        self.assertEqual(stats['render_max_delta'],0)
    def test_deleted_added_and_duplicate_image_calls_are_rejected(self):
        for counts in ((1,0),(0,1),(2,1),(1,2)):
            with self.subTest(counts=counts):
                self.assertEqual(self.proof(sample(copies=counts[0]),sample(copies=counts[1]))['matched'],0)
    def test_changed_pixels_mask_alpha_and_small_move_are_rejected(self):
        for change in ({'color':(200,0,0)},{'mask':255},{'opacity':.5},{'shift':.2}):
            with self.subTest(change=change):
                self.assertEqual(self.proof(sample(),sample(**change))['matched'],0)
    def test_other_text_or_path_loss_cannot_borrow_image_bounds(self):
        for change in ({'text':True},{'line':True}):
            with self.subTest(change=change):
                self.assertEqual(self.proof(sample(**change),sample())['matched'],0)
    def test_nonrectangular_clip_and_non_normal_blend_remain_unsupported(self):
        for change in ({'clip':b'40.184 49.3461 m 43.9 49.3461 l 43.9 59.4941 l h'},):
            with self.subTest(change=change):
                self.assertEqual(self.proof(sample(),sample(**change))['matched'],0)
    def test_non_normal_image_blend_against_backdrop_is_rejected(self):
        self.assertEqual(self.proof(sample(backdrop=True),sample(backdrop=True,blend='Screen'))['matched'],0)
    def test_same_rgb_with_different_soft_masks_is_not_resolved_by_digest(self):
        pair=[]
        png=BytesIO();Image.new('RGBA',(13,39),(0,0,0,255)).save(png,format='PNG')
        for opacity in (128,64):
            with fitz.open('pdf',sample(mask=opacity))as doc:
                xref=doc[0].insert_image((70,40,74,51),stream=png.getvalue())
                doc.xref_set_key(xref,'ColorSpace','/DeviceRGB')
                pair.append(doc.tobytes(garbage=1))
        result=self.proof(*pair)
        self.assertEqual(result['matched'],0,result)
        self.assertEqual(result['reason'],'unsupported image resource')

def shared_form_sample(*,mask=128,conflicting_mask=False,cycle=False,unknown=False):
    writer=PdfWriter(clone_from=BytesIO(sample(mask=mask)));page=writer.pages[0]
    def form(data,resources):
        stream=DecodedStreamObject();stream.set_data(data)
        stream.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),
            NameObject('/BBox'):ArrayObject([NumberObject(value)for value in (0,0,100,100)]),
            NameObject('/Resources'):resources})
        return writer._add_object(stream)
    shared=form(b'',DictionaryObject())
    if cycle:
        shared.get_object()[NameObject('/Resources')]=DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/Self'):shared})})
    # Both dictionaries refer to Shared. The real image follows that alias in
    # Wrapper, so an early return on a previously seen Form would miss it.
    resources=DictionaryObject(page['/Resources'])
    images=DictionaryObject({NameObject('/Shared'):shared,**page['/Resources']['/XObject']})
    if conflicting_mask:
        alternate=PdfReader(BytesIO(sample(mask=64)))
        image=next(iter(alternate.pages[0]['/Resources']['/XObject'].values())).get_object().clone(writer)
        images[NameObject('/UnusedMaskVariant')]=writer._add_object(image)
    if unknown:
        invalid=DecodedStreamObject();invalid.set_data(b'')
        invalid[NameObject('/Subtype')]=NameObject('/Unknown')
        images[NameObject('/Unsupported')]=writer._add_object(invalid)
    resources[NameObject('/XObject')]=images
    wrapper=form(page.get_contents().get_data(),resources)
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/Shared'):shared,NameObject('/Wrapper'):wrapper})})
    stream=DecodedStreamObject();stream.set_data(b'q /Wrapper Do Q')
    page[NameObject('/Contents')]=writer._add_object(stream)
    output=BytesIO();writer.write(output);return output.getvalue()


class SharedFormImageResourceTest(unittest.TestCase):
    def test_shared_form_does_not_hide_a_later_sibling_image_resource(self):
        with fitz.open('pdf',shared_form_sample())as document:
            page=document[0]
            xrefs=cleaner._image_resource_xrefs(page)
            self.assertEqual(len(xrefs),1)
            self.assertEqual(len(cleaner.image_paints(page)['images']),1)
            calls=page.get_image_info(hashes=True,xrefs=True)
            self.assertEqual(len(calls),1)
            self.assertEqual(fitz.Pixmap(document,xrefs[0]).digest,calls[0]['digest'])
            self.assertIsNotNone(cleaner._image_fingerprint(document,xrefs[0]))

    def test_unpainted_mask_variant_after_shared_form_still_blocks_rgb_mapping(self):
        with fitz.open('pdf',shared_form_sample(conflicting_mask=True))as before, \
                fitz.open('pdf',shared_form_sample(mask=64))as after:
            xrefs=cleaner._image_resource_xrefs(before[0])
            self.assertEqual(len(xrefs),2)
            self.assertEqual(len({fitz.Pixmap(before,xref).digest for xref in xrefs}),1)
            self.assertEqual(len({cleaner._image_fingerprint(before,xref)for xref in xrefs}),2)
            difference=ImageChops.difference(render(before[0]),render(after[0]))
            self.assertGreater(max(value[1]for value in difference.getextrema()),8)
            result=matched_image_difference(before[0],after[0],difference)
            self.assertEqual(result['matched'],0,result)
            self.assertEqual(result['reason'],'unsupported image resource')

    def test_ancestor_cycles_and_unknown_xobject_subtypes_fail_closed(self):
        for change in ({'cycle':True},{'unknown':True}):
            with self.subTest(change=change),fitz.open('pdf',shared_form_sample(**change))as document:
                with self.assertRaises(cleaner.UnsupportedPDF):
                    cleaner._image_resource_xrefs(document[0])


def inline_with_unused_rgb_resource(interpolate):
    image=Image.new('RGB',(13,39))
    for y in range(39):
        for x in range(13):image.putpixel((x,y),((0 if (x+y)%2 else 255),)*3)
    png=BytesIO();image.save(png,format='PNG')
    with fitz.open() as doc:
        page=doc.new_page(width=100,height=100)
        page.insert_image((20.184,10.5059,40.9,70.6539),stream=png.getvalue(),keep_proportion=False)
        raw=doc.tobytes(garbage=1)
    writer=PdfWriter(clone_from=BytesIO(raw));page=writer.pages[0]
    for ref in page['/Resources']['/XObject'].values():
        ref.get_object()[NameObject('/ColorSpace')]=NameObject('/DeviceRGB')
    data=page.get_contents().get_data()
    inline=(b'BI /W 13 /H 39 /BPC 8 /CS /RGB /I '+(b'true' if interpolate else b'false')
            +b' ID\n'+image.tobytes()+b'\nEI')
    stream=DecodedStreamObject();stream.set_data(re.sub(rb'/\S+\s+Do',lambda _:inline,data))
    page[NameObject('/Contents')]=writer._add_object(stream)
    out=BytesIO();writer.write(out);return out.getvalue()

class InlineImageIdentityTest(unittest.TestCase):
    def test_interpolation_change_cannot_borrow_same_rgb_resource(self):
        with fitz.open('pdf',inline_with_unused_rgb_resource(False)) as before, \
                fitz.open('pdf',inline_with_unused_rgb_resource(True)) as after:
            # get_image_info falsely assigns the external xref to the inline
            # occurrence solely because their decoded RGB bytes are identical.
            self.assertEqual(before[0].get_image_info(hashes=True,xrefs=True),
                             after[0].get_image_info(hashes=True,xrefs=True))
            difference=ImageChops.difference(render(before[0]),render(after[0]))
            self.assertGreater(max(value[1] for value in difference.getextrema()),8)
            self.assertEqual(matched_image_difference(before[0],after[0],difference)['matched'],0)

@lru_cache(maxsize=3)
def independent_image_case(slug,number):
    reader=PdfReader(Path(__file__).resolve().parents[1]/'dist/downloads'/f'{slug}.pdf')
    for page in reader.pages:strip_watermark(page)
    page=reader.pages[number]
    writer=PdfWriter();writer.add_page(page);source=BytesIO();writer.write(source)
    stats={};cleaner.clean_source_page(page,reader,diagnostics=stats)
    return source.getvalue(),stats


class IndependentImageSamplingTests(unittest.TestCase):
    def assert_independent_page(self,slug,number,initial,phases,matched):
        _,stats=independent_image_case(slug,number)
        self.assertEqual(stats['render_initial_max_delta'],initial)
        self.assertEqual(stats['image_sampling_phase_deltas'],phases)
        self.assertEqual(stats['image_sampling_proof']['matched'],matched)
        self.assertEqual(stats['independent_renderer'],'PDFium')
        self.assertEqual([check['dpi']for check in stats['independent_render_checks']],[144,288])
        self.assertTrue(all(check['max_delta']<=8 for check in stats['independent_render_checks']))
        self.assertLessEqual(stats['render_max_delta'],8)

    def test_real_inference_answer_image_keeps_failed_mupdf_phases_as_evidence(self):
        self.assert_independent_page('inference-answers',263,33,[30,44],1)

    def test_real_organic_image_with_one_passing_phase_still_needs_both_independent_scales(self):
        self.assert_independent_page('organic-questions',157,96,[111,0],1)

    def test_real_multiple_organic_images_use_the_same_strict_full_page_proof(self):
        self.assert_independent_page('organic-questions',331,59,[0,72],2)

    def reject_changed_oracle(self,scale):
        import pdf_render_verify as renderer
        source,_=independent_image_case('inference-answers',263)
        reader=PdfReader(BytesIO(source));real=renderer.render_pdfium;calls=[];stats={}
        def render(raw,size,factor):
            image,pixel_scale=real(raw,size,factor);calls.append(factor)
            # A new unowned background pixel cannot borrow the matching image
            # identity or a passing result at the other independent scale.
            if len(calls)%2==0 and factor==scale:
                image=image.copy();image.putpixel((0,0),(0,0,0))
            return image,pixel_scale
        with patch.object(renderer,'render_pdfium',side_effect=render):
            with self.assertRaises(cleaner.UnsupportedPDF):
                cleaner.clean_source_page(reader.pages[0],reader,diagnostics=stats)
        self.assertEqual(calls,[2,2,4,4])
        self.assertGreater(max(check['max_delta']for check in stats['independent_render_checks']),8)

    def test_failed_144dpi_render_cannot_borrow_a_passing_288dpi_result(self):
        self.reject_changed_oracle(2)

    def test_failed_288dpi_render_cannot_borrow_a_passing_144dpi_result(self):
        self.reject_changed_oracle(4)

    def test_incomplete_image_identity_proof_cannot_invoke_independent_fallback(self):
        import pdf_render_verify as renderer
        source,_=independent_image_case('inference-answers',263)
        reader=PdfReader(BytesIO(source))
        with patch.object(cleaner,'_matched_image_difference',return_value={'matched':0,'reason':'unsupported image resource'}), \
                patch.object(renderer,'render_pdfium')as independent:
            with self.assertRaises(cleaner.UnsupportedPDF):
                cleaner.clean_source_page(reader.pages[0],reader)
        independent.assert_not_called()


@lru_cache(maxsize=1)
def foreign_stroke_case():
    reader=PdfReader(Path(__file__).resolve().parents[1]/'dist/downloads/organic-answers.pdf')
    for page in reader.pages:strip_watermark(page)
    page=reader.pages[771]
    writer=PdfWriter();writer.add_page(page);source=BytesIO();writer.write(source)
    stats={};result=cleaner.clean_source_page(page,reader,diagnostics=stats)
    return source.getvalue(),result,stats


class ForeignStrokeSupportTests(unittest.TestCase):
    def test_conservative_stroke_bbox_does_not_hide_an_unchanged_real_image(self):
        source,result,stats=foreign_stroke_case()
        self.assertEqual(stats['render_initial_max_delta'],41)
        self.assertEqual(stats['image_sampling_phase_deltas'],[41,53])
        self.assertEqual(stats['image_sampling_proof']['matched'],1)
        self.assertTrue(all(check['max_delta']<=8 for check in stats['independent_render_checks']))
        with fitz.open('pdf',source)as before,fitz.open('pdf',result)as after:
            difference=ImageChops.difference(render(before[0]),render(after[0]))
            self.assertEqual(matched_image_difference(before[0],after[0],difference)['matched'],1)

    def test_a_real_thin_stroke_loss_cannot_borrow_the_image_bounds(self):
        with fitz.open('pdf',sample(line=True))as before,fitz.open('pdf',sample())as after:
            difference=ImageChops.difference(render(before[0]),render(after[0]))
            result=matched_image_difference(before[0],after[0],difference)
            self.assertEqual(result['matched'],0,result)
            self.assertEqual(result['reason'],'overlapping stroke-path')

    def test_unknown_or_incomplete_paint_masks_cannot_exclude_a_stroke_bbox(self):
        source,result,_=foreign_stroke_case()
        with fitz.open('pdf',source)as before,fitz.open('pdf',result)as after:
            difference=ImageChops.difference(render(before[0]),render(after[0]))
            invalid=[('context',{'side_effect':ValueError('unknown stroke or clipping context')}),
                     ('size',{'return_value':(Image.new('L',(1,1)),{})}),
                     ('mode',{'return_value':(Image.new('RGB',difference.size),{})})]
            for label,options in invalid:
                with self.subTest(label=label),patch.object(cleaner,'exact_paint_mask',**options):
                    proof=matched_image_difference(before[0],after[0],difference)
                self.assertEqual(proof['matched'],0,proof)
                self.assertEqual(proof['reason'],'overlapping stroke-path')


if __name__=='__main__':unittest.main()
