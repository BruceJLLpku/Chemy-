"""Regression checks for local PDF paint evidence; no diagnostic files required."""
from pathlib import Path
from io import BytesIO
from functools import lru_cache
import unittest
import pymupdf as fitz
from pypdf import PdfWriter
from pypdf.generic import NameObject,DecodedStreamObject
from PIL import Image,ImageChops
import pdf_clip_cleanup as cleaner
from test_pdf_cleanup_validation import real_pair,span
import test_pdf_cleanup_validation as baseline_tests

label_coverage=cleaner._label_coverage
rect_fill_is_distant=cleaner._rect_fill_is_distant
pixel_cells_touch=cleaner._pixel_cells_touch

def render_pair(original,cleaned,offset=(0,0)):
    images=[]
    for page in (original,cleaned):
        fitz.TOOLS.store_shrink(100)
        pix=page.get_pixmap(matrix=fitz.Matrix(2,0,0,2,*offset),alpha=False)
        images.append(Image.frombytes('RGB',(pix.width,pix.height),pix.samples))
    return images

@lru_cache(maxsize=16)
def named_pair(name):
    slug,number=name.removeprefix('failure-').rsplit('-',1)
    original,cleaned,stats=real_pair(slug,int(number)-1)
    with fitz.open('pdf',original) as doc:
        inverse=~doc[0].transformation_matrix
        holes=[tuple(fitz.Rect(item['hole'])*inverse) for item in stats.get('label_edge_proof',[])]
    return original,cleaned,holes,stats

def evaluate_label(original,cleaned,holes):
    images=render_pair(original,cleaned)
    proof=label_coverage(original,cleaned,holes,*images)
    return {'accepted':proof['unprovenMax']<=8,'base':proof}

def evaluate_combined(source,target,holes=()):
    before,after=render_pair(source,target)
    label=label_coverage(source,target,holes,before,after)
    remaining=before.copy()
    for point in label['covered']:remaining.putpixel(point,after.getpixel(point))
    difference=ImageChops.difference(remaining,after)
    glyph=cleaner._matched_glyph_difference(source,target,difference)
    fill=cleaner._matched_fill_difference(source,target,difference)
    path=cleaner._verify_path_sampling(source,target,remaining,after)
    report={'accepted':label['unprovenMax']<=8 or path['accepted'],'label':label,
            'matchedGlyphs':glyph,'matchedFills':fill,'pathProof':path}
    if not report['accepted'] and (glyph or fill):
        deltas=[]
        for offset in ((.37,.23),(.73,.61)):
            images=render_pair(source,target,offset)
            deltas.append(label_coverage(source,target,holes,*images,offset=offset)['unprovenMax'])
        report['phaseDeltas']=deltas
        report['accepted']=max(deltas)<=8
    return report

class CompositeLabelTest(unittest.TestCase):
    pair=baseline_tests.LabelProofTest.pair
    def proof(self,a,b,holes=((10,10,40,30),)):
        return label_coverage(a,b,holes,a.image,b.image)
    def test_actual_pixel_cell_overlap_includes_edges_but_never_disjoint_cells(self):
        for left,accept in ((15.49,True),(15.5,False),(15.51,False)):
            a,b=self.pair()
            a.spans[0]['chars']=[(c[0],c[1],c[2],(left,10,40,30))for c in a.spans[0]['chars']]
            self.assertEqual(bool(self.proof(a,b)['count']),accept)
    def test_coloured_edge_over_matching_retained_number_accepts(self):
        a,b=self.pair(before=(255,244,244),after=(255,253,253))
        for s in a.spans+b.spans:s['color']=(1.,0.,0.)
        self.assertEqual(self.proof(a,b)['count'],1)
    def test_nonwhite_output_outside_kept_glyph_or_with_wrong_ink_rejects(self):
        for reason in ('outside','wrongpaint','wrongpixel','darkening','transparent'):
            with self.subTest(reason=reason):
                a,b=self.pair(before=(255,244,244),after=(255,253,253))
                for s in a.spans+b.spans:s['color']=(1.,0.,0.)
                if reason=='outside':
                    for s in (a.spans[1],b.spans[0]):
                        s['chars']=[(c[0],c[1],c[2],(35,15,40,30))for c in s['chars']]
                elif reason=='wrongpaint':
                    for s in (a.spans[1],b.spans[0]):s['color']=(0.,0.,1.)
                elif reason=='wrongpixel':b.image.putpixel((30,20),(250,253,253))
                elif reason=='darkening':a.image.putpixel((30,20),(255,253,253));b.image.putpixel((30,20),(255,240,240))
                elif reason=='transparent':a.spans[0]['opacity']=.5
                self.assertEqual(self.proof(a,b)['count'],0)
    def test_partial_proof_does_not_approve_unrelated_body_deletion(self):
        a,b=self.pair();a.image.putpixel((100,50),(0,0,0))
        result=self.proof(a,b)
        self.assertEqual(result['count'],1);self.assertEqual(result['unprovenMax'],255)
        self.assertFalse(evaluate_label(a,b,[(10,10,40,30)])['accepted'])
    def test_replacement_changes_and_chemical_deletion_still_reject(self):
        for reason in ('delete','unicode','glyph','move','color','chemical'):
            with self.subTest(reason=reason):
                a,b=self.pair()
                if reason=='delete':b.spans=[]
                elif reason=='chemical':a.spans[0]=span('p-Tol')
                elif reason=='color':b.spans[0]['color']=(1.,0.,0.)
                else:
                    c=list(b.spans[0]['chars'][0])
                    if reason=='unicode':c[0]=ord('p')
                    if reason=='glyph':c[1]+=1
                    if reason=='move':c[2]=(18,25)
                    b.spans[0]['chars'][0]=tuple(c)
                self.assertEqual(self.proof(a,b)['count'],0)
    def test_more_than_128_proven_pixels_does_not_silently_truncate(self):
        pts=[(x,y)for y in (20,21,22)for x in range(20,80)][:129]
        a,b=self.pair(points=pts)
        # A wider perimeter encloses these three sample rows; the existing
        # one-pixel boundary constraint otherwise excludes row 22.
        holes=[(10,y/2,40,30)for y in (20,21,22)]
        result=self.proof(a,b,holes)
        self.assertEqual(result['count'],0);self.assertEqual(result['rejectedCount'],129)
    def test_real_label_only_and_mixed_glyph_pages(self):
        for slug,page,labels,glyph in [('inference-answers',258,1,False),
                                      ('crystal-answers',86,3,False),
                                      ('organic-answers',197,7,False),
                                      ('crystal-questions',81,113,True)]:
            with self.subTest(book=slug,page=page):
                _,_,stats=real_pair(slug,page-1)
                self.assertEqual(stats['label_edge_pixels'],labels)
                self.assertLessEqual(stats['render_max_delta'],8)
                if glyph:self.assertEqual(stats['glyph_sampling_phase_deltas'],[8,8])
    def test_colored_old_ink_requires_known_opaque_matching_paint(self):
        for color,pixel in [((1.,0.,0.),(255,240,240)),((0.,0.,1.),(240,240,255))]:
            a,b=self.pair(before=pixel);a.spans[0]['color']=color
            self.assertEqual(self.proof(a,b)['count'],1)
            for mutation in ({'color':(0.,1.,0.)},{'opacity':.5},{'colorspace':4}):
                a,b=self.pair(before=pixel);a.spans[0]['color']=color;a.spans[0].update(mutation)
                self.assertEqual(self.proof(a,b)['count'],0)

class RectangleSupportTest(unittest.TestCase):
    def path(self,rects):
        return {'type':'f','items':[('re',fitz.Rect(rect),1)for rect in rects]}
    def support(self,point):
        mask=Image.new('L',(200,200),0);mask.putpixel(point,255);return mask
    def test_union_bbox_gap_does_not_count_as_actual_filled_coverage(self):
        path=self.path([(5,5,10,10),(80,80,90,90)])
        self.assertTrue(rect_fill_is_distant(path,self.support((100,100))))
    def test_either_actual_rectangle_and_aa_margin_always_block_exclusion(self):
        path=self.path([(5,5,10,10),(80,80,90,90)])
        for point in [(12,12),(178,178),(20,20),(159,160)]:
            self.assertFalse(rect_fill_is_distant(path,self.support(point)),point)
    def test_strokes_curves_empty_or_nonfinite_rectangles_are_not_guessed(self):
        for path in [self.path([]),{'type':'fs','items':[('re',fitz.Rect(5,5,10,10),1)]},
                     {'type':'f','items':[('l',fitz.Point(5,5),fitz.Point(10,10))]},
                     self.path([(float('nan'),5,10,10)])]:
            self.assertFalse(rect_fill_is_distant(path,self.support((100,100))))
    def test_half_open_pixel_cells_exclude_only_zero_area_contact(self):
        mask=self.support((10,10))
        self.assertFalse(pixel_cells_touch(mask,(0,0,5,6)))
        self.assertTrue(pixel_cells_touch(mask,(0,0,5.00001,6)))
        self.assertTrue(pixel_cells_touch(mask,(5,5,6,6)))
        self.assertFalse(pixel_cells_touch(mask,(5.5,5.5,6,6)))
    def pair(self,name,append=None):
        output=[]
        for side,raw in zip(('original','cleaned'),named_pair(name)[:2]):
            with fitz.open('pdf',raw)as doc:
                if append:append(doc[0],side)
                output.append(doc.tobytes(garbage=1))
        return output
    def result(self,pair):
        with fitz.open('pdf',pair[0])as a,fitz.open('pdf',pair[1])as b:
            return evaluate_combined(a[0],b[0])
    def test_real_charge_and_filled_circle_pass_without_relaxed_pixels(self):
        for name in ('failure-organic-answers-351','failure-organic-answers-378'):
            result=self.result(self.pair(name))
            self.assertTrue(result['accepted'],result)
            if result['matchedFills']:self.assertEqual(result['phaseDeltas'],[0,0])
            else:self.assertLessEqual(result['pathProof']['neighborhood_max_delta'],8)
    def test_distant_two_rectangle_union_is_excluded_in_both_fill_and_stroke_verifiers(self):
        def append(page,side):
            shape=page.new_shape();shape.draw_rect((20,20,30,30));shape.draw_rect((530,750,540,760))
            shape.finish(color=None,fill=(.2,.3,.4),even_odd=True);shape.commit()
        for name in ('failure-organic-answers-351','failure-organic-answers-378'):
            result=self.result(self.pair(name,append))
            self.assertTrue(result['accepted'],result)
    def test_deleting_ink_inside_one_rectangle_of_a_large_union_is_rejected(self):
        def append(page,side):
            if side!='original':return
            shape=page.new_shape();shape.draw_rect((20,20,30,30));shape.draw_rect((530,750,540,760))
            shape.finish(color=None,fill=(.2,.3,.4),even_odd=True);shape.commit()
        result=self.result(self.pair('failure-organic-answers-378',append))
        self.assertFalse(result['accepted'],result)
    def test_real_rectangle_piece_near_difference_cannot_borrow_union_gap(self):
        def append(page,side):
            shape=page.new_shape();shape.draw_rect((20,20,30,30));shape.draw_rect((259,648.5,259.2,648.7))
            shape.finish(color=None,fill=(.2,.3,.4),even_odd=True);shape.commit()
        result=self.result(self.pair('failure-organic-answers-378',append))
        self.assertFalse(result['accepted'],result)
    def test_thin_image_deleted_at_actual_bbox_edge_is_rejected(self):
        image=Image.new('RGB',(1,1),(0,0,0));buffer=BytesIO();image.save(buffer,format='PNG')
        for rect in ((259,648.5,259.05,648.9),(258.95,648.5,259,648.9),(259.49,648.5,259.51,648.9)):
            def append(page,side):
                if side=='original':page.insert_image(rect,stream=buffer.getvalue(),keep_proportion=False)
            result=self.result(self.pair('failure-organic-answers-378',append))
            self.assertFalse(result['accepted'],(rect,result))
            # Prove that deleting this image actually changes visible pixels;
            # a zero-coverage subpixel fixture would not establish protection.
            images=[]
            for present in (False,True):
                with fitz.open('pdf',named_pair('failure-organic-answers-378')[1])as doc:
                    if present:append(doc[0],'original')
                    fitz.TOOLS.store_shrink(100)
                    p=doc[0].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
                    images.append(Image.frombytes('RGB',(p.width,p.height),p.samples))
            self.assertGreater(max(c[1]for c in ImageChops.difference(*images).getextrema()),8,rect)

class CombinedProofTest(unittest.TestCase):
    def run_pair(self,name,edit=None):
        original,cleaned,holes,_=named_pair(name)
        with fitz.open('pdf',original)as a,fitz.open('pdf',cleaned)as b:
            if edit:
                edit(a[0],'original');edit(b[0],'cleaned')
            return evaluate_combined(a[0],b[0],holes)
    def test_label_and_unchanged_stroke_edges_can_be_proved_independently(self):
        for name,labelcount,paths in [('failure-organic-questions-400',27,4),('failure-organic-questions-408',28,2)]:
            result=self.run_pair(name)
            self.assertTrue(result['accepted'],result)
            self.assertEqual(result['label']['count'],labelcount)
            self.assertEqual(result['pathProof']['selected_paths'],[paths,paths])
            self.assertLessEqual(result['pathProof']['neighborhood_max_delta'],8)
    def test_missing_chemical_bond_cannot_borrow_disjoint_label_or_stroke_proof(self):
        def edit(page,side):
            if side=='original':page.draw_line((300,600),(310,602),width=.3)
        self.assertFalse(self.run_pair('failure-organic-questions-408',edit)['accepted'])
    def test_new_recoloured_or_moved_strokes_are_rejected_with_valid_label_proof(self):
        for mutation in ('new','colour','move','duplicate'):
            def edit(page,side):
                if mutation=='new'and side=='cleaned':return
                shift=.5 if mutation=='move'and side=='cleaned'else 0
                color=(1,0,0)if mutation=='colour'and side=='cleaned'else(0,0,0)
                for _ in range(2 if mutation=='duplicate'and side=='original'else 1):
                    page.draw_line((300+shift,600),(310+shift,602),width=.3,color=color)
            with self.subTest(mutation=mutation):
                self.assertFalse(self.run_pair('failure-organic-questions-408',edit)['accepted'])
    def test_body_character_or_image_deletion_is_rejected_despite_label_proof(self):
        image=Image.new('RGB',(2,2),(20,50,100));buf=BytesIO();image.save(buf,format='PNG')
        for kind in ('text','image'):
            def edit(page,side):
                if side!='original':return
                if kind=='text':page.insert_text((300,600),'p',fontsize=8)
                else:page.insert_image((300,600,301,601),stream=buf.getvalue())
            with self.subTest(kind=kind):
                self.assertFalse(self.run_pair('failure-organic-questions-408',edit)['accepted'])

def arrow(*,fill=True,copies=1,shift=0,color='0 g',miter=2,cap=1,scale=1):
    writer=PdfWriter();page=writer.add_blank_page(width=120,height=100)
    head='70 45 m 80 50 l 70 55 l 72 50 l 70 45 l'
    stream=DecodedStreamObject();data=f'q {scale} 0 0 1 {shift} 0 cm 0 G {color} 1 w {cap} J 0 j {miter} M\n'
    if fill:data+=head+' f\n'
    data+=(head+' S\n')*copies+'Q\n';stream.set_data(data.encode());page[NameObject('/Contents')]=writer._add_object(stream)
    output=BytesIO();writer.write(output);return output.getvalue()

class OpaqueVectorTest(unittest.TestCase):
    def result(self,left,right):
        with fitz.open('pdf',left)as a,fitz.open('pdf',right)as b:
            images=render_pair(a[0],b[0])
            self.assertGreater(max(x[1]for x in ImageChops.difference(*images).getextrema()),8)
            return cleaner._verify_opaque_vectors(a[0],b[0],*images)
    def test_real_overlapping_arrow_keeps_exact_miter_and_ctm(self):
        original,cleaned,holes,_=named_pair('failure-organic-questions-406')
        with fitz.open('pdf',original)as a,fitz.open('pdf',cleaned)as b:
            images=render_pair(a[0],b[0]);proof=label_coverage(a[0],b[0],holes,*images)
            for p in proof['covered']:images[0].putpixel(p,images[1].getpixel(p))
            result=cleaner._verify_opaque_vectors(a[0],b[0],*images)
        self.assertTrue(result['accepted'],result);self.assertEqual(result['types'],['f','s'])
        self.assertEqual(result['miterLimits'],[None,2.0]);self.assertLessEqual(result['residual'],8)
    def test_deleting_fill_or_overlapping_stroke_is_rejected(self):
        for a,b in [(arrow(),arrow(fill=False)),(arrow(copies=2),arrow())]:
            self.assertFalse(self.result(a,b)['accepted'])
    def test_moving_recoloring_or_anisotropic_scaling_is_rejected(self):
        for b in [arrow(shift=.5),arrow(color='1 0 0 rg'),arrow(scale=1.01)]:
            self.assertFalse(self.result(arrow(),b)['accepted'])
    def test_changed_miter_limit_cannot_borrow_identical_path_geometry(self):
        self.assertFalse(self.result(arrow(miter=1),arrow(miter=10))['accepted'])
    def test_changed_caps_cannot_borrow_identical_path_geometry(self):
        self.assertFalse(self.result(arrow(cap=0),arrow(cap=2))['accepted'])
    def test_unrelated_text_deletion_remains_rejected_with_vector_aa(self):
        a=arrow();doc=fitz.open('pdf',a);doc[0].insert_text((72,50),'p',fontsize=8)
        self.assertFalse(self.result(doc.tobytes(garbage=1),a)['accepted']);doc.close()

class PartialClipTest(unittest.TestCase):
    def context(self,*,clip=(10,10,90,90),hole=None,group=None):
        scopes=[{'type':'clip','items':[('re',fitz.Rect(clip),1)],'even_odd':True}]
        if hole:scopes[0]['items'].append(('re',fitz.Rect(hole),1))
        if group:scopes.append({'type':'group','opacity':1,'blendmode':'Normal','knockout':False,**group})
        return {'_validation_scopes':scopes}
    def support(self):
        image=Image.new('L',(200,200),0);image.putpixel((100,100),255);return image
    def test_local_evidence_requires_clearance_from_every_clip_and_hole(self):
        self.assertTrue(cleaner._local_vector_context(self.context(),self.support()))
        for kwargs in ({'clip':(10,10,50,90)},{'hole':(49.8,49.8,51,51)},
                       {'group':{'opacity':.5}},{'group':{'blendmode':'Multiply'}}):
            self.assertFalse(cleaner._local_vector_context(self.context(**kwargs),self.support()))
        path=self.context();path['_validation_scopes'][0]['items']=[('c',fitz.Point(0,0))]
        self.assertFalse(cleaner._local_vector_context(path,self.support()))
    def test_real_partially_clipped_curve_keeps_exact_state_and_small_residual(self):
        _,_,stats=real_pair('kinetics-answers',21)
        self.assertEqual(stats['render_initial_max_delta'],9)
        self.assertEqual(stats['opaque_vector_proof']['matched'],1)
        self.assertLessEqual(stats['opaque_vector_proof']['residual'],8)
    def test_visible_clip_loss_cannot_borrow_identical_path_identity(self):
        pair=[]
        for width in (80,40):
            with fitz.open('pdf',arrow())as doc:
                page=doc[0];xref=page.get_contents()[0]
                doc.update_stream(xref,f'q 0 0 {width} 100 re W n\n'.encode()+doc.xref_stream(xref)+b'\nQ')
                pair.append(doc.tobytes(garbage=1))
        with fitz.open('pdf',pair[0])as a,fitz.open('pdf',pair[1])as b:
            images=render_pair(a[0],b[0])
            self.assertGreater(max(v[1]for v in ImageChops.difference(*images).getextrema()),8)
            self.assertFalse(cleaner._verify_opaque_vectors(a[0],b[0],*images)['accepted'])


class IndependentVectorProofTest(unittest.TestCase):
    def test_real_spectrum_requires_exact_vectors_and_two_independent_resolutions(self):
        _,_,stats=real_pair('organic-questions',427)
        self.assertEqual(stats['independent_renderer'],'PDFium')
        self.assertEqual(stats['opaque_vector_proof']['matched'],26)
        checks=stats['independent_render_checks']
        self.assertEqual([v['dpi'] for v in checks],[144,288])
        self.assertEqual([v['label_pixels'] for v in checks],[4,17])
        self.assertEqual([v['max_delta'] for v in checks],[8,3])
        self.assertTrue(all(v['pixel_scales'][0]!=v['pixel_scales'][1] for v in checks))

    def test_nonuniform_pixel_cells_use_each_actual_axis_scale(self):
        first,second=baseline_tests.LabelProofTest.pair(self)
        first.image=Image.new('RGB',(256,400),'white')
        second.image=first.image.copy()
        first.image.putpixel((60,80),(100,100,100))
        proof=cleaner._label_coverage(first,second,[(10,10,40,30)],
                                     first.image,second.image,scale=(4,8))
        self.assertEqual(proof['count'],1)
        for bad in (0,float('nan'),(4,0)):
            with self.assertRaises(ValueError):
                cleaner._label_coverage(first,second,[],first.image,second.image,scale=bad)

if __name__=='__main__':unittest.main()
