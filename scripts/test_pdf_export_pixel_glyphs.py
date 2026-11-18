"""Negative checks for the relocated-glyph raster-sampling proof."""
from copy import deepcopy
import unittest

import fitz

from test_pdf_export_pixels import matched_relocated_glyphs


def glyph():
    return {'font':'Fixture','type':0,'flags':0,'wmode':0,'dir':(1,0),'color':(1,0,0),
            'opacity':1,'layer':'','unicode':23481,'gid':4585,'size':11.313,
            'linewidth':.56565,'origin':(100,200),'bbox':(100,190,112,202)}


class GlyphSamplingProofTest(unittest.TestCase):
    boxes=[fitz.Rect(103,193,103.5,193.5)]

    def test_same_transformed_glyph_allows_float_rounding_only(self):
        before=glyph();after=deepcopy(before);after['origin']=(100.00006,200)
        self.assertEqual(matched_relocated_glyphs([before],[after],self.boxes)['paintOccurrences'],1)

    def test_deleted_overlapping_occurrence_cannot_borrow_surviving_glyph(self):
        value=glyph()
        self.assertIsNone(matched_relocated_glyphs([value,deepcopy(value)],[value],self.boxes))
        self.assertIsNone(matched_relocated_glyphs([value],[value,deepcopy(value)],self.boxes))

    def test_two_kept_overlapping_occurrences_are_counted(self):
        values=[glyph(),glyph()]
        self.assertEqual(matched_relocated_glyphs(values,deepcopy(values),self.boxes)['paintOccurrences'],2)

    def test_missing_changed_or_repainted_character_is_rejected(self):
        for key,value in [('unicode',ord('H')),('gid',5),('font','Other'),('color',(0,0,0)),
                          ('opacity',.5),('type',1),('size',10),('linewidth',.4),
                          ('origin',(100.002,200)),('bbox',(100,190,112,202.002))]:
            with self.subTest(key=key):
                before=glyph();after=deepcopy(before);after[key]=value
                self.assertIsNone(matched_relocated_glyphs([before],[after],self.boxes))
        self.assertIsNone(matched_relocated_glyphs([glyph()],[],self.boxes))

    def test_changes_outside_matched_text_cannot_claim_glyph_evidence(self):
        self.assertIsNone(matched_relocated_glyphs([glyph()],[glyph()],[fitz.Rect(120,193,120.5,193.5)]))


if __name__=='__main__':
    unittest.main()
