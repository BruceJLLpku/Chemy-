from io import BytesIO
import re,unittest
import pymupdf as fitz
from PIL import Image,ImageChops
from pypdf import PdfReader,PdfWriter
from pypdf.generic import DictionaryObject,NameObject,FloatObject,DecodedStreamObject
import pdf_clip_cleanup as cleaner
from pdf_clip_cleanup import _matched_image_difference as matched_image_difference
from test_pdf_cleanup_validation import real_pair

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

if __name__=='__main__':unittest.main()
