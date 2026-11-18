from pathlib import Path
from io import BytesIO
import unittest
import pymupdf as fitz
from PIL import Image
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject,DecodedStreamObject
from functools import lru_cache
from PIL import ImageChops
from pdf_clip_cleanup import clean_source_page, _verify_path_sampling, _verify_label_edges, _matched_fill_difference
from pdf_watermark import strip_watermark


def verify_path_sampling(first,second):
    with fitz.open('pdf',first) as original, fitz.open('pdf',second) as cleaned:
        images=[]
        for page in (original[0],cleaned[0]):
            fitz.TOOLS.store_shrink(100)
            pix=page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
            images.append(Image.frombytes('RGB',(pix.width,pix.height),pix.samples))
        return _verify_path_sampling(original[0],cleaned[0],*images)


@lru_cache(maxsize=6)
def real_pair(slug,number):
    reader=PdfReader(Path(__file__).resolve().parents[1]/'dist/downloads'/f'{slug}.pdf')
    page=reader.pages[number];strip_watermark(page)
    writer=PdfWriter();writer.add_page(page);buffer=BytesIO();writer.write(buffer)
    stats={};result=clean_source_page(page,reader,diagnostics=stats)
    return buffer.getvalue(),result,stats



def fixture(*,shift=0,color=(0,0,0),copies=1,bond=False,text=False,filled=False,opacity=1):
    with fitz.open() as doc:
        page=doc.new_page(width=200,height=140)
        for _ in range(copies):
            shape=page.new_shape()
            shape.draw_bezier((30+shift,80.123+shift),(60+shift,20.123+shift),
                              (130+shift,120.123+shift),(170+shift,60.123+shift))
            shape.finish(width=.3,color=color,closePath=False,stroke_opacity=opacity)
            shape.commit()
        if bond:page.draw_line((65,90.123),(120,75.123),width=.3)
        if text:page.insert_text((70,70),'p-Tol',fontsize=24)
        if filled:page.draw_rect((80,60,90,70),fill=(0,0,0),color=None)
        return doc.tobytes()


class PathSamplingTests(unittest.TestCase):
    def real_pair(self):
        return real_pair('organic-questions',13)[:2]

    def test_real_organic_curve_rounding(self):
        result=verify_path_sampling(*self.real_pair())
        self.assertTrue(result['accepted'],result)
        self.assertEqual(result['selected_paths'],[1,1])
        self.assertLessEqual(result['neighborhood_max_delta'],8)

    def test_deleted_point_three_pt_bond_is_rejected(self):
        result=verify_path_sampling(fixture(bond=True),fixture())
        self.assertFalse(result['accepted'],result)

    def test_moved_curve_is_rejected(self):
        result=verify_path_sampling(fixture(),fixture(shift=.5))
        self.assertFalse(result['accepted'],result)

    def test_changed_colour_is_rejected(self):
        result=verify_path_sampling(fixture(),fixture(color=(1,0,0)))
        self.assertFalse(result['accepted'],result)

    def test_deleting_overlapping_path_is_rejected(self):
        result=verify_path_sampling(fixture(copies=2),fixture(copies=1))
        self.assertFalse(result['accepted'],result)
        self.assertEqual(result['selected_paths'],[2,1])

    def test_fill_inside_large_curve_bbox_does_not_borrow_curve_match(self):
        result=verify_path_sampling(fixture(),fixture(filled=True))
        self.assertFalse(result['accepted'],result)

    def test_transparency_is_not_eligible(self):
        result=verify_path_sampling(fixture(opacity=.5),fixture(opacity=.6))
        self.assertFalse(result['accepted'],result)

    def test_text_image_or_fill_at_comparison_pixels_is_not_eligible(self):
        for kind in ['text','image','fill']:
            with self.subTest(kind=kind):
                pair=[]
                for raw in self.real_pair():
                    with fitz.open('pdf',raw) as doc:
                        if kind=='text':
                            doc[0].insert_text((373,443.9),'i',fontsize=1)
                        elif kind=='image':
                            image=Image.new('RGB',(1,1),(40,120,200));buffer=BytesIO();image.save(buffer,format='PNG')
                            doc[0].insert_image((373.5,443.5,373.7,443.7),stream=buffer.getvalue())
                        else:
                            doc[0].draw_rect((373.5,443.5,373.7,443.7),fill=(.2,.2,.8),color=None)
                        pair.append(doc.tobytes())
                result=verify_path_sampling(*pair)
                self.assertFalse(result['accepted'],result)
                self.assertTrue('overlapping' in result['reason'] or 'unsupported nearby path' in result['reason'],result)

    def test_remote_overlap_does_not_enter_neighborhood_comparison(self):
        pair=[]
        for raw in self.real_pair():
            with fitz.open('pdf',raw) as doc:
                doc[0].insert_text((339,457),'p-Tol',fontsize=8)
                pair.append(doc.tobytes())
        result=verify_path_sampling(*pair)
        self.assertTrue(result['accepted'],result)

    def test_real_organic_rounded_frame_with_hidden_duplicate(self):
        result=verify_path_sampling(*real_pair('organic-answers',201)[:2])
        self.assertTrue(result['accepted'],result)
        self.assertEqual(result['selected_paths'],[1,1])

    def test_real_empty_clip_fill_does_not_obscure_retained_charge_circle(self):
        _before,_after,stats=real_pair('elements-answers',24)
        self.assertEqual(stats['render_initial_max_delta'],16)
        self.assertLessEqual(stats['path_sampling_proof']['neighborhood_max_delta'],8)

    def test_changed_clip_cannot_borrow_unclipped_path_geometry(self):
        pair=[]
        for height in [70,70.5]:
            reader=PdfReader(BytesIO(fixture()))
            page=reader.pages[0];stream=DecodedStreamObject()
            stream.set_data(f'q 0 0 200 {height} re W n\n'.encode()+page.get_contents().get_data()+b'\nQ')
            page[NameObject('/Contents')]=stream
            writer=PdfWriter();writer.add_page(page);out=BytesIO();writer.write(out);pair.append(out.getvalue())
        result=verify_path_sampling(*pair)
        self.assertFalse(result['accepted'],result)



import unittest
from copy import deepcopy
from types import SimpleNamespace
from PIL import Image
import pymupdf as fitz
def evaluate(original,cleaned,holes):
    images=[]
    for page in (original,cleaned):
        pix=page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
        images.append(Image.frombytes('RGB',(pix.width,pix.height),pix.samples))
    return _verify_label_edges(original,cleaned,holes,*images)


def span(text):
    return {'font':'NumberingFont','type':0,'wmode':0,'flags':16,'colorspace':3,
            'layer':'','size':12.,'opacity':1.,'linewidth':None,'dir':(1.,0.),'color':(0.,0.,0.),
            'bbox':(10.,10.,40.,30.),
            'chars':[(ord(c),ord(c),(15.+i,25.),(10.,10.,40.,30.)) for i,c in enumerate(text)]}

class Page:
    transformation_matrix=fitz.Matrix(1,1)
    def __init__(self,image,spans):self.image,self.spans=image,spans
    def get_pixmap(self,**kwargs):
        return SimpleNamespace(width=self.image.width,height=self.image.height,samples=self.image.tobytes())
    def get_texttrace(self):return self.spans

class LabelProofTest(unittest.TestCase):
    def pair(self,points=((30,20),),after=(255,255,255),before=(100,100,100)):
        a,b=Image.new('RGB',(128,100),'white'),Image.new('RGB',(128,100),'white')
        for p in points:a.putpixel(p,before);b.putpixel(p,after)
        return Page(a,[span('6-1'),span('42-1')]),Page(b,[span('42-1')])
    def test_known_number_perimeter_with_preserved_replacement_accepts(self):
        self.assertTrue(evaluate(*self.pair(),[(10,10,40,30)])['accepted'])
    def test_interior_change_is_rejected_even_within_old_number_bbox(self):
        self.assertFalse(evaluate(*self.pair(points=((30,35),)),[(10,10,40,30)])['accepted'])
    def test_change_outside_hole_perimeter_is_rejected(self):
        self.assertFalse(evaluate(*self.pair(points=((90,20),)),[(10,10,40,30)])['accepted'])
    def test_nonwhite_output_or_colored_source_ink_is_rejected(self):
        for before,after in [((100,100,100),(245,245,245)),((100,0,0),(255,255,255)),((255,255,255),(100,100,100))]:
            with self.subTest(before=before,after=after):
                first,second=self.pair(before=before,after=after)
                # Nonwhite pixels require actual overlap with a preserved
                # replacement glyph; its span's broad union bbox is not proof.
                for label in (first.spans[1],second.spans[0]):
                    label['chars']=[(c[0],c[1],c[2],(35,15,40,30))for c in label['chars']]
                self.assertFalse(evaluate(first,second,[(10,10,40,30)])['accepted'])
    def test_removed_or_changed_new_number_identity_is_rejected(self):
        for action in ('delete','unicode','glyph','move','color'):
            with self.subTest(action=action):
                a,b=self.pair();s=b.spans[0]
                if action=='delete':b.spans=[]
                if action in ('unicode','glyph','move'):
                    c=list(s['chars'][0])
                    if action=='unicode':c[0]=ord('5')
                    if action=='glyph':c[1]+=1
                    if action=='move':c[2]=(16.,25.)
                    s['chars'][0]=tuple(c)
                if action=='color':s['color']=(1.,0.,0.)
                self.assertFalse(evaluate(a,b,[(10,10,40,30)])['accepted'])
    def test_removed_chemical_character_cannot_claim_numbering_proof(self):
        a,b=self.pair();a.spans[0]=span('p-Tol')
        self.assertFalse(evaluate(a,b,[(10,10,40,30)])['accepted'])
    def test_count_bound_cannot_be_bypassed_by_recognized_holes(self):
        pts=[(x,y)for y in (20,21,22)for x in range(20,80)][:129]
        # Every changed pixel is first proven to belong to a recognized
        # perimeter; unrelated changes cannot consume a label proof's limit.
        result=evaluate(*self.pair(points=pts),[(10,y/2,40,30)for y in (20,21,22)])
        self.assertFalse(result['accepted']);self.assertEqual(result['count'],129)


class RealLabelProofTest(unittest.TestCase):
    def test_crystal_old_number_edge_requires_preserved_new_number_proof(self):
        _before,after,stats=real_pair('crystal-questions',78)
        self.assertGreater(stats['label_edge_max_delta'],64)
        self.assertLessEqual(stats['label_edge_pixels'],128)
        self.assertTrue(stats['label_edge_proof'])
        fitz.TOOLS.store_shrink(100)
        with fitz.open('pdf',after) as doc:
            text=doc[0].get_text()
        for label in ['121-2','121-3','121-5','122-1']:
            self.assertIn(label,text)


def filled_bond(*,shift=0,color=(1,0,0),copies=1):
    with fitz.open() as doc:
        page=doc.new_page(width=160,height=120)
        for _ in range(copies):
            shape=page.new_shape()
            points=[(40+shift,70.123),(90+shift,40.123),(89.8+shift,39.823),(39.8+shift,69.823),(40+shift,70.123)]
            for a,b in zip(points,points[1:]):shape.draw_line(a,b)
            shape.finish(color=None,fill=color,closePath=False)
            shape.commit()
        return doc.tobytes()


class FillSamplingTests(unittest.TestCase):
    def test_real_filled_chemical_bond_passes_two_strict_phases(self):
        _before,_after,stats=real_pair('inference-answers',269)
        self.assertEqual(stats['render_initial_max_delta'],14)
        self.assertGreater(stats['fill_sampling_matched'],0)
        self.assertEqual(len(stats['fill_sampling_phase_deltas']),2)
        self.assertLessEqual(max(stats['fill_sampling_phase_deltas']),8)

    def test_deleted_moved_recoloured_or_duplicate_filled_bonds_are_rejected(self):
        pairs=[(filled_bond(),filled_bond(copies=0)),
               (filled_bond(),filled_bond(shift=.5)),
               (filled_bond(),filled_bond(color=(0,0,1))),
               (filled_bond(copies=2),filled_bond())]
        for number,(a,b) in enumerate(pairs):
            with self.subTest(case=number),fitz.open('pdf',a) as first,fitz.open('pdf',b) as second:
                images=[]
                for page in (first[0],second[0]):
                    fitz.TOOLS.store_shrink(100)
                    pix=page.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
                    images.append(Image.frombytes('RGB',(pix.width,pix.height),pix.samples))
                difference=ImageChops.difference(*images)
                self.assertGreater(max(c[1] for c in difference.getextrema()),8)
                self.assertEqual(_matched_fill_difference(first[0],second[0],difference),0)


if __name__=='__main__':unittest.main()
