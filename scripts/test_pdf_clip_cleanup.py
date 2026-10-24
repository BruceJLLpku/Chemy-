"""Regression tests for clipping cleanup; no source or published assets change."""
from io import BytesIO
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import patch

import pymupdf as fitz
from PIL import Image, ImageChops
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ArrayObject, ContentStream, DecodedStreamObject, DictionaryObject, FloatObject, NameObject, NumberObject

from pdf_clip_cleanup import clean_source_page, UnsupportedPDF
from pdf_watermark import strip_watermark


def sample(content, *, form=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300,height=200)
    font = DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
    resources = DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
    stream = DecodedStreamObject()
    stream.set_data(content)
    if form:
        stream.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),
                       NameObject('/BBox'):ArrayObject([FloatObject(v) for v in [0,0,300,200]]),
                       NameObject('/Matrix'):ArrayObject([FloatObject(v) for v in [1,0,0,1,0,0]]),NameObject('/Resources'):resources})
        resources = DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/Source'):writer._add_object(stream)})})
        stream = DecodedStreamObject();stream.set_data(b'q /Source Do Q')
    page[NameObject('/Contents')] = writer._add_object(stream)
    page[NameObject('/Resources')] = writer._add_object(resources)
    buffer = BytesIO();writer.write(buffer)
    return PdfReader(BytesIO(buffer.getvalue()))


def pattern_sample(tiling=False):
    writer = PdfWriter()
    page = writer.add_blank_page(width=300,height=200)
    if tiling:
        image = DecodedStreamObject();image.set_data(b'\xff\x00\x00\x00\xff\x00\x00\x00\xff\xff\xff\xff')
        image.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Image'),
            NameObject('/Width'):NumberObject(2),NameObject('/Height'):NumberObject(2),
            NameObject('/ColorSpace'):NameObject('/DeviceRGB'),NameObject('/BitsPerComponent'):NumberObject(8)})
        pattern = DecodedStreamObject();pattern.set_data(b'q 2 0 0 2 0 0 cm /Image Do Q')
        pattern.update({NameObject('/Type'):NameObject('/Pattern'),NameObject('/PatternType'):NumberObject(1),
            NameObject('/PaintType'):NumberObject(1),NameObject('/TilingType'):NumberObject(2),
            NameObject('/BBox'):ArrayObject([NumberObject(v) for v in [0,0,2,2]]),
            NameObject('/XStep'):NumberObject(2),NameObject('/YStep'):NumberObject(2),
            NameObject('/Matrix'):ArrayObject([NumberObject(v) for v in [5,0,0,5,0,0]]),
            NameObject('/Resources'):DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/Image'):writer._add_object(image)})})})
    else:
        function = DictionaryObject({NameObject('/FunctionType'):NumberObject(2),
            NameObject('/Domain'):ArrayObject([NumberObject(0),NumberObject(1)]),
            NameObject('/C0'):ArrayObject([NumberObject(1),NumberObject(1),NumberObject(1)]),
            NameObject('/C1'):ArrayObject([NumberObject(0),NumberObject(0),NumberObject(0)]),NameObject('/N'):NumberObject(1)})
        shading = DictionaryObject({NameObject('/ShadingType'):NumberObject(2),NameObject('/ColorSpace'):NameObject('/DeviceRGB'),
            NameObject('/Coords'):ArrayObject([NumberObject(v) for v in [0,0,80,0]]),NameObject('/Function'):function})
        pattern = DictionaryObject({NameObject('/Type'):NameObject('/Pattern'),NameObject('/PatternType'):NumberObject(2),NameObject('/Shading'):shading})
    form = DecodedStreamObject();form.set_data(b'2 J /Pattern cs /PatternFill scn 0 0 80 30 re f')
    form.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),
        NameObject('/BBox'):ArrayObject([NumberObject(v) for v in [0,0,80,30]]),
        NameObject('/Resources'):DictionaryObject({NameObject('/Pattern'):DictionaryObject({NameObject('/PatternFill'):writer._add_object(pattern)})})})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/Figure'):writer._add_object(form)})})
    stream = DecodedStreamObject();stream.set_data(b'q 1 0 0 1 20 100 cm /Figure Do Q q 1 0 0 1 160 50 cm /Figure Do Q')
    page[NameObject('/Contents')] = writer._add_object(stream)
    out = BytesIO();writer.write(out)
    return PdfReader(BytesIO(out.getvalue()))


class CleanupTests(unittest.TestCase):
    def clean(self, reader):
        stats = {}
        raw = clean_source_page(reader.pages[0],reader,diagnostics=stats)
        return fitz.open('pdf',raw),stats

    def test_number_hole_does_not_delete_replacement(self):
        reader = sample(b'q 0 0 300 200 re 39 117 35 20 re W* n BT /F1 12 Tf 40 123 Td (4-1) Tj ET Q '
                        b'BT /F1 12 Tf 40 123 Td (1-1) Tj ET',form=True)
        doc,stats = self.clean(reader)
        self.assertNotIn('4-1',doc[0].get_text())
        self.assertIn('1-1',doc[0].get_text())
        self.assertEqual(doc[0].get_xobjects(),[])
        self.assertGreaterEqual(stats['removed_glyphs'],3)

    def test_rectangular_polygon_removes_neighbor_text(self):
        reader = sample(b'q 0 0 m 150 0 l 150 200 l 0 200 l h W n '
                        b'BT /F1 12 Tf 20 100 Td (KEEP) Tj 170 0 Td (NEIGHBOR) Tj ET Q')
        doc,stats = self.clean(reader)
        self.assertIn('KEEP',doc[0].get_text())
        self.assertNotIn('NEIGHBOR',doc[0].get_text())
        self.assertEqual(stats['nonrectangular_clips'],0)

    def test_inline_image_and_partial_clip_keep_appearance(self):
        reader = sample(b'q 0 0 80 80 re W n 80 0 0 80 20 20 cm '
                        b'BI /W 1 /H 1 /CS /RGB /BPC 8 ID \xff\x00\x00 EI Q',form=True)
        doc,stats = self.clean(reader)
        self.assertGreater(len(doc[0].get_image_info()),0)
        self.assertEqual(stats['render_max_delta'],0)

    def test_nonrectangular_clip_is_preserved_and_reported(self):
        reader = sample(b'q 0 0 m 100 0 l 0 100 l h W n 1 0 0 rg 0 0 100 100 re f Q')
        doc,stats = self.clean(reader)
        self.assertEqual(stats['nonrectangular_clips'],1)
        self.assertEqual(stats['render_max_delta'],0)

    def test_reused_form_patterns_keep_independent_transforms(self):
        for tiling in [False,True]:
            with self.subTest(tiling=tiling):
                reader = pattern_sample(tiling)
                raw = clean_source_page(reader.pages[0],reader)
                doc = fitz.open('pdf',raw)
                self.assertEqual(doc[0].get_xobjects(),[])
                parsed = PdfReader(BytesIO(raw))
                patterns = list(parsed.pages[0]['/Resources']['/Pattern'].values())
                self.assertEqual(len(patterns),2)
                matrices = [tuple(ref.get_object()['/Matrix']) for ref in patterns]
                self.assertNotEqual(matrices[0],matrices[1])
                # PDF line-cap/join operands require integers; Poppler rejects reals.
                for args,op in ContentStream(parsed.pages[0]['/Contents'],parsed).operations:
                    if op in (b'J',b'j'):
                        self.assertIsInstance(args[0],NumberObject)
                doc.close()

    def test_real_gradient_and_removed_number_edges(self):
        root = Path(__file__).resolve().parents[1]
        for slug,number in [('polymer-questions',3),('polymer-answers',5),('polymer-questions',5),
                            ('polymer-questions',31),('polymer-answers',20),('organic-answers',500),('organic-answers',504)]:
            with self.subTest(slug=slug,page=number+1):
                reader = PdfReader(root/'dist/downloads'/f'{slug}.pdf')
                strip_watermark(reader.pages[number])
                stats = {};raw = clean_source_page(reader.pages[number],reader,diagnostics=stats)
                self.assertGreater(stats['removed_glyphs'],0)
                self.assertLessEqual(stats.get('label_edge_pixels',0),128)
                self.assertLessEqual(stats.get('label_edge_max_delta',0),64)
                if slug == 'polymer-questions' and number == 5:
                    doc = fitz.open('pdf',raw)
                    self.assertIn('6-1',doc[0].get_text())
                    self.assertNotIn('3-1',doc[0].get_text())
                    doc.close()
                if slug == 'polymer-questions' and number == 31:
                    doc = fitz.open('pdf',raw)
                    for label in ['43-1','43-2','43-3','43-4']:
                        self.assertIn(label,doc[0].get_text())
                    for old_label in ['7-1','7-2','7-3','7-4']:
                        self.assertNotIn(old_label,doc[0].get_text())
                    doc.close()
                if slug == 'organic-answers' and number == 500:
                    self.assertTrue(stats['tile_cache_disabled'])
                    self.assertGreater(stats['render_cached_max_delta'],8)
                    self.assertLessEqual(stats['render_max_delta'],8)

    def test_clip_edge_antialias_keeps_adjacent_line(self):
        reader = sample(b'q 20 20 200 100 re W n 0 g 20 19.9 200 0.05 re f Q')
        doc,stats = self.clean(reader)
        self.assertEqual(stats['render_max_delta'],0)
        self.assertTrue(doc[0].get_drawings())
        doc.close()

    def test_float_rounded_chemical_glyphs_require_two_strict_sampling_phases(self):
        root = Path(__file__).resolve().parents[1]
        for slug,number in [('organic-questions',12),('organic-answers',8)]:
            with self.subTest(slug=slug,page=number+1):
                reader = PdfReader(root/'dist/downloads'/f'{slug}.pdf')
                strip_watermark(reader.pages[number])
                stats = {}
                clean_source_page(reader.pages[number],reader,diagnostics=stats)
                self.assertGreater(stats['render_initial_max_delta'],8)
                self.assertGreater(stats['glyph_sampling_matched'],0)
                self.assertEqual(len(stats['glyph_sampling_phase_deltas']),2)
                self.assertLessEqual(max(stats['glyph_sampling_phase_deltas']),8)
                self.assertNotIn('label_edge_pixels',stats)

    def test_unsupported_transparency_fails_explicitly(self):
        reader = sample(b'BT /F1 12 Tf 20 100 Td (KEEP) Tj ET',form=True)
        form = reader.pages[0]['/Resources']['/XObject']['/Source']
        form[NameObject('/Group')] = DictionaryObject({NameObject('/S'):NameObject('/Transparency')})
        with self.assertRaisesRegex(UnsupportedPDF,'Transparency-group'):
            self.clean(reader)

    def test_late_clip_fails_instead_of_filtering_earlier_paint(self):
        reader = sample(b'q 0 0 30 30 re f 0 0 100 100 re W n BT /F1 12 Tf 20 100 Td (KEEP) Tj ET Q')
        with self.assertRaisesRegex(UnsupportedPDF,'after painted content'):
            self.clean(reader)

    def test_source_is_not_mutated(self):
        reader = sample(b'q 0 0 100 200 re W n BT /F1 12 Tf 170 100 Td (HIDDEN) Tj ET Q')
        before = reader.pages[0].get_contents().get_data()
        self.clean(reader)
        self.assertEqual(reader.pages[0].get_contents().get_data(),before)
        self.assertIn('HIDDEN',reader.pages[0].extract_text())

    def test_render_guard_rejects_visible_content_loss(self):
        reader = sample(b'q 0 0 300 200 re W n BT /F1 12 Tf 20 100 Td (KEEP) Tj ET Q')
        with patch('pdf_clip_cleanup._Culler.culler',lambda self,ctx,bbox,kind: int(kind == 8)):
            with self.assertRaisesRegex(UnsupportedPDF,'changed rendered content'):
                self.clean(reader)

    def test_sampling_retry_rejects_lost_overlapping_glyph(self):
        import pdf_clip_cleanup as cleanup
        reader = sample(b'q 0 0 300 200 re W n '
                        b'BT /F1 24 Tf 40 100 Td (O) Tj ET '
                        b'BT /F1 24 Tf 40 100 Td (I) Tj ET Q')
        culler = cleanup._Culler.culler
        matcher = cleanup._matched_glyph_difference
        seen = {'glyphs':0,'matched':0}

        def remove_second_glyph(self,ctx,bbox,kind):
            if kind == 8:
                seen['glyphs'] += 1
                if seen['glyphs'] == 2:
                    return 1
            return culler(self,ctx,bbox,kind)

        def record_match(*args):
            result = matcher(*args)
            seen['matched'] = result
            return result

        with patch.object(cleanup._Culler,'culler',remove_second_glyph), \
             patch.object(cleanup,'_matched_glyph_difference',side_effect=record_match):
            with self.assertRaisesRegex(UnsupportedPDF,'changed rendered content'):
                self.clean(reader)
        # The surviving O covers the lost I's difference region, so bounding
        # boxes alone would accept it. The two full renders must still reject.
        self.assertGreater(seen['matched'],0)

    def test_sampling_gate_rejects_deleted_chemical_character(self):
        import pdf_clip_cleanup as cleanup
        reader = sample(b'q 0 0 300 200 re W n '
                        b'BT /F1 24 Tf 40 100 Td (p-Tol) Tj ET Q')
        culler = cleanup._Culler.culler
        seen = {'glyphs':0}

        def remove_p(self,ctx,bbox,kind):
            if kind == 8:
                seen['glyphs'] += 1
                if seen['glyphs'] == 1:
                    return 1
            return culler(self,ctx,bbox,kind)

        with patch.object(cleanup._Culler,'culler',remove_p):
            with self.assertRaisesRegex(UnsupportedPDF,'changed rendered content'):
                self.clean(reader)
        self.assertGreater(seen['glyphs'],1)

    def test_sampling_gate_rejects_moved_or_recoloured_text(self):
        from pdf_clip_cleanup import _matched_glyph_difference
        with fitz.open() as original:
            original.new_page(width=200,height=120).insert_text((40,80),'p-Tol',fontsize=24)
            pix = original[0].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
            before = Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
            for point,color in [((40.5,80),(0,0,0)),((40,80),(1,0,0))]:
                with self.subTest(point=point,color=color), fitz.open() as changed:
                    changed.new_page(width=200,height=120).insert_text(point,'p-Tol',fontsize=24,color=color)
                    pix = changed[0].get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
                    after = Image.frombytes('RGB',(pix.width,pix.height),pix.samples)
                    difference = ImageChops.difference(before,after)
                    self.assertIsNotNone(difference.getbbox())
                    self.assertEqual(_matched_glyph_difference(original[0],changed[0],difference),0)

    def test_polymer_original_label_is_physically_removed(self):
        path = Path(__file__).resolve().parents[1]/'dist/downloads/polymer-questions.pdf'
        reader = PdfReader(path)
        doc,stats = self.clean(reader)
        doc[0].clip_to_rect((0,96,595.3,168.3))
        self.assertNotIn('4-1',doc[0].get_text())
        self.assertIn('1-1',doc[0].get_text())
        self.assertIn('正离子聚合',doc[0].get_text())
        self.assertEqual(doc[0].get_xobjects(),[])
        self.assertLessEqual(stats['render_max_delta'],8)

    def test_production_sequence_does_not_reuse_another_documents_font(self):
        # The page-6 heading was correct in isolated cleanup, but turned into
        # unrelated Chinese text after earlier parts had warmed MuPDF's store.
        # Exercise the real frame / part / subset order with a private cache.
        import build_export_parts as builder
        selected = ['chemy39-5-4','chemy39-17-4','chemy39-20-7']
        temporary_root = builder.ROOT/'tmp'
        temporary_root.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temporary_root) as directory:
            dest, cache = Path(directory)/'parts', Path(directory)/'cache'
            dest.mkdir()
            # An interrupted manifest write must behave like a cache miss.
            (dest/'polymer-answers.json').write_text('{"questions":',encoding='utf8')
            with patch.object(builder,'DEST',dest), patch.object(builder,'CACHE',cache):
                builder.build_book(('polymer','answers',selected,False))
            manifest = json.loads((dest/'polymer-answers.json').read_text(encoding='utf8'))
            self.assertEqual(set(manifest['questions']),set(selected))
            for entry in manifest['questions'].values():
                with fitz.open(dest/entry['path']) as doc:
                    self.assertTrue(all(not page.get_xobjects() for page in doc))
            page6 = list((cache/'pages').glob('*/5.pdf'))
            self.assertEqual(len(page6),1)
            stats = json.loads(page6[0].with_suffix('.json').read_text(encoding='utf8'))
            self.assertLessEqual(stats['render_max_delta'],8)
            fitz.TOOLS.store_shrink(100)
            with fitz.open(page6[0]) as doc:
                self.assertIn('刺激响应聚合物',doc[0].get_text())
            # Recheck the serialized page in a cold subprocess; this oracle
            # cannot share the font store used by the production sequence.
            from test_pdf_font_subset import cold_render
            snapshot = cold_render(page6[0].read_bytes())
            self.assertFalse(snapshot['warnings'])
            self.assertIn('刺激响应聚合物',snapshot['pages'][0]['text'])


# Include the verification-only regressions in this existing CI entry point.
from test_pdf_cleanup_validation import PathSamplingTests, LabelProofTest, RealLabelProofTest, FillSamplingTests
from test_pdf_image_resources import FilterImageResourceTests
from test_pdf_image_sampling import ImageSamplingTest, InlineImageIdentityTest
from test_pdf_image_paint_evidence import ImagePaintEvidenceTests
from test_pdf_label_ownership import LabelOwnershipTests
from test_pdf_paint_evidence import PaintEvidenceTests
from test_pdf_cleanup_composite import (CompositeLabelTest, RectangleSupportTest,
                                       CombinedProofTest, OpaqueVectorTest, PartialClipTest,
                                       IndependentVectorProofTest)


if __name__ == '__main__':
    unittest.main()
