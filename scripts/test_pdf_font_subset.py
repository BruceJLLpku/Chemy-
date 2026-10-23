"""Font-subset regressions, using a generated font rather than system fonts."""
from io import BytesIO
from pathlib import Path
import json
import shutil
import subprocess
import sys
import unittest
from unittest.mock import patch

import pymupdf as fitz
from fontTools.fontBuilder import FontBuilder
from fontTools.pens.ttGlyphPen import TTGlyphPen
from fontTools.ttLib import TTFont
from fontTools.ttLib.tables._c_m_a_p import CmapSubtable
from pypdf import PdfReader, PdfWriter
from pypdf.generic import NameObject

from pdf_font_subset import _matches, _program_usage, _subset_program, subset_pdf_fonts


def fixture_font(*, legacy=False, symbol=False):
    """Keep a high glyph ID and unused outlines to exercise retain_gids."""
    names = ['.notdef'] + [f'g{i}' for i in range(1,301)]
    builder = FontBuilder(1000,isTTF=True)
    builder.setupGlyphOrder(names)
    builder.setupCharacterMap({65:'g1',66:'g2',0x4e2d:'g254'})
    glyphs = {}
    for index,name in enumerate(names):
        pen = TTGlyphPen(None)
        pen.moveTo((30,0))
        # Numerous distinct unused outlines make the expected saving meaningful.
        for point in range(1,60):
            pen.lineTo((30 + point * 8,100 + ((point * 71 + index * 29) % 600)))
        pen.lineTo((500,0))
        pen.closePath()
        glyphs[name] = pen.glyph()
    builder.setupGlyf(glyphs)
    builder.setupHorizontalMetrics({name:(600,0) for name in names})
    builder.setupHorizontalHeader(ascent=800,descent=-200)
    builder.setupOS2(sTypoAscender=800,sTypoDescender=-200,usWinAscent=800,usWinDescent=200)
    builder.setupNameTable({'familyName':'ChemySubsetFixture','styleName':'Regular',
        'psName':'ChemySubsetFixture','fullName':'ChemySubsetFixture',
        'copyright':'Test fixture created for Chemy','licenseDescription':'MIT test fixture'})
    builder.setupPost()
    builder.setupMaxp()
    output = BytesIO()
    builder.save(output)
    if legacy or symbol:
        with TTFont(BytesIO(output.getvalue())) as font:
            table = CmapSubtable.newSubtable(4 if symbol else 6)
            table.platformID,table.platEncID,table.language = (3 if symbol else 1),0,0
            table.cmap = {0xf041:'g1',0xf042:'g2'} if symbol else {65:'g1',66:'g2'}
            font['cmap'].tables = [table]
            output = BytesIO()
            font.save(output)
    return output.getvalue()


def fixture_pdf(*,inline=False,indirect_category=False,legacy=False):
    doc = fitz.open()
    for text in (['AB','BA'] if legacy else ['AB中','B中A']):
        page = doc.new_page(width=200,height=100)
        page.insert_font(fontname='Embedded',fontbuffer=fixture_font(legacy=legacy),set_simple=legacy)
        page.insert_text((20,50),text,fontname='Embedded',fontsize=20)
    raw = doc.tobytes(deflate=True)
    doc.close()
    if inline or indirect_category:
        writer = PdfWriter(clone_from=BytesIO(raw))
        for page in writer.pages:
            resources = page['/Resources']
            fonts = resources['/Font']
            if inline:
                for name,ref in list(fonts.items()):
                    fonts[name] = ref.get_object()
            if indirect_category:
                resources[NameObject('/Font')] = writer._add_object(fonts)
        output = BytesIO()
        writer.write(output)
        raw = output.getvalue()
    return raw


def remove_cmaps(program):
    """Reproduce the prior FontTools default dropping Macintosh-only cmaps."""
    with TTFont(BytesIO(program)) as font:
        if 'cmap' in font:
            font['cmap'].tables = []
        output = BytesIO()
        font.save(output)
        return output.getvalue()


def cold_render(raw):
    """Use a fresh process so the test oracle cannot share a PDF font cache."""
    code = '''import hashlib,json,sys,pymupdf as f
d=f.open('pdf',sys.stdin.buffer.read())
pages=[]
for p in d:
    pix=p.get_pixmap(matrix=f.Matrix(2,2),alpha=False)
    pages.append({'text':p.get_text(),'sha256':hashlib.sha256(pix.samples).hexdigest()})
print(json.dumps({'pages':pages,'warnings':f.TOOLS.mupdf_warnings()}))
'''
    result = subprocess.run([sys.executable,'-c',code],input=raw,capture_output=True,check=True,timeout=60)
    return json.loads(result.stdout)


def pdf_lib_copy(raw):
    node = shutil.which('node')
    if not node:
        raise unittest.SkipTest('Node.js is needed for the PDF-lib copy regression')
    vendor = Path(__file__).resolve().parents[1]/'dist/vendor/pdf-lib.min.js'
    code = '''const fs=require('fs');const {PDFDocument}=require(process.argv[1]);
(async()=>{const source=await PDFDocument.load(fs.readFileSync(0));
const output=await PDFDocument.create();
for(const page of await output.copyPages(source,source.getPageIndices()))output.addPage(page);
process.stdout.write(Buffer.from(await output.save()));})().catch(e=>{console.error(e);process.exit(1)});'''
    return subprocess.run([node,'-e',code,str(vendor)],input=raw,capture_output=True,check=True,timeout=60).stdout


def font_programs(raw):
    doc = fitz.open('pdf',raw)
    programs = [doc.xref_stream(xref) for xref in _program_usage(raw,doc)]
    doc.close()
    return programs


def unicode_maps(raw):
    reader = PdfReader(BytesIO(raw))
    result = []
    for page in reader.pages:
        for ref in page['/Resources']['/Font'].values():
            font = ref.get_object()
            if '/ToUnicode' in font:
                result.append(font['/ToUnicode'].get_data())
    return result


class FontSubsetTests(unittest.TestCase):
    def assert_preserved(self,raw,result):
        first = fitz.open('pdf',raw)
        second = fitz.open('pdf',result)
        self.assertTrue(_matches(first,second)[0])
        first.close();second.close()
        self.assertEqual(unicode_maps(raw),unicode_maps(result))

    def test_embedded_font_shrinks_with_unicode_and_high_glyph_id_retained(self):
        raw = fixture_pdf()
        stats = {}
        result = subset_pdf_fonts(raw,diagnostics=stats)
        self.assertLess(len(result),len(raw)*0.8)
        self.assertGreater(stats['changed_fonts'],0)
        self.assertEqual(stats['render_max_delta'],0)
        self.assert_preserved(raw,result)
        with fitz.open('pdf',result) as doc:
            self.assertIn('中',doc[0].get_text())
        before = TTFont(BytesIO(font_programs(raw)[0]))
        after = TTFont(BytesIO(font_programs(result)[0]))
        self.assertEqual(after.getGlyphID(after.getBestCmap()[0x4e2d]),254)
        self.assertEqual(before['glyf'][before.getGlyphOrder()[254]].coordinates,
                         after['glyf'][after.getGlyphOrder()[254]].coordinates)
        self.assertIn('Test fixture created for Chemy',str(after['name'].getDebugName(0)))
        self.assertIn('MIT test fixture',str(after['name'].getDebugName(13)))
        before.close();after.close()

    def test_inline_font_and_indirect_resource_category_are_supported(self):
        raw = fixture_pdf(inline=True,indirect_category=True)
        original = fitz.open('pdf',raw)
        self.assertEqual(original[0].get_fonts()[0][0],0)
        original.close()
        stats = {}
        result = subset_pdf_fonts(raw,diagnostics=stats)
        self.assertLess(len(result),len(raw))
        self.assertGreater(stats['changed_fonts'],0)
        self.assert_preserved(raw,result)

    def test_legacy_and_symbol_cmaps_keep_the_original_glyph_mapping(self):
        for kind in ['legacy','symbol']:
            with self.subTest(kind=kind):
                raw = fixture_font(**{kind:True})
                result = _subset_program(raw,(1,2),True)
                with TTFont(BytesIO(raw)) as before, TTFont(BytesIO(result)) as after:
                    self.assertEqual(len(after['cmap'].tables),1)
                    a,b = before['cmap'].tables[0],after['cmap'].tables[0]
                    self.assertEqual((a.platformID,a.platEncID),(b.platformID,b.platEncID))
                    self.assertEqual({c:before.getGlyphID(g) for c,g in a.cmap.items()},
                                     {c:after.getGlyphID(g) for c,g in b.cmap.items()})

    def test_legacy_simple_font_survives_real_pdf_lib_copy_and_cold_render(self):
        raw = fixture_pdf(legacy=True,inline=True)
        stats = {}
        result = subset_pdf_fonts(raw,diagnostics=stats)
        self.assertGreater(stats['changed_fonts'],0)
        self.assertLess(len(result),len(raw)*0.8)
        original = cold_render(raw)
        self.assertFalse(original['warnings'])
        self.assertEqual(cold_render(result),original)
        self.assertEqual(cold_render(pdf_lib_copy(result)),original)

    def test_guard_rejects_lost_cmap_despite_warm_inline_font_cache(self):
        raw = fixture_pdf(legacy=True,inline=True)
        with fitz.open('pdf',raw) as original:
            self.assertEqual(original[0].get_fonts()[0][0],0)
            with fitz.open('pdf',raw) as changed:
                for xref in _program_usage(raw,changed):
                    changed.update_stream(xref,remove_cmaps(changed.xref_stream(xref)))
                bad = changed.tobytes(deflate=True)
            self.assertTrue(cold_render(bad)['warnings'])
            # The old interleaved get_text/render guard returned True here:
            # identical inline dictionaries masked the broken candidate font.
            original[0].get_text()
            original[0].get_pixmap()
            with fitz.open('pdf',bad) as candidate:
                valid,reason,_delta = _matches(original,candidate)
                self.assertFalse(valid)
                self.assertIn('cmaps',reason)

    def test_subset_falls_back_if_a_future_optimizer_drops_cmap(self):
        raw = fixture_pdf(legacy=True,inline=True)
        subsetter = _subset_program
        with patch('pdf_font_subset._subset_program',side_effect=lambda program,glyphs,hinting:
                   remove_cmaps(subsetter(program,glyphs,hinting))):
            stats = {}
            self.assertEqual(subset_pdf_fonts(raw,diagnostics=stats),raw)
            self.assertIn('cmaps',stats['retained_original_reason'])

    def test_unsupported_embedded_program_is_left_intact(self):
        raw = fixture_pdf()
        from fontTools.ttLib import TTLibError
        with patch('pdf_font_subset._subset_program',side_effect=TTLibError('Unsupported format')):
            stats = {}
            self.assertEqual(subset_pdf_fonts(raw,diagnostics=stats),raw)
            self.assertTrue(stats['skipped_fonts'])

    def test_missing_used_glyphs_cannot_be_published(self):
        raw = fixture_pdf()
        subsetter = _subset_program
        with patch('pdf_font_subset._subset_program',side_effect=lambda program,glyphs,hinting:
                   subsetter(program,(0,),hinting)):
            stats = {}
            self.assertEqual(subset_pdf_fonts(raw,diagnostics=stats),raw)
            self.assertIn('retained_original_reason',stats)

    def test_render_guard_detects_visible_changes_with_identical_text(self):
        raw = fixture_pdf()
        original = fitz.open('pdf',raw)
        changed = fitz.open('pdf',raw)
        changed[0].draw_rect(fitz.Rect(0,0,10,10),color=(1,0,0),fill=(1,0,0))
        self.assertEqual(original[0].get_text(),changed[0].get_text())
        self.assertFalse(_matches(original,changed)[0])
        original.close();changed.close()

    def test_no_embedded_fonts_returns_exact_original(self):
        doc = fitz.open();page = doc.new_page()
        page.insert_text((30,30),'Standard font')
        raw = doc.tobytes();doc.close()
        self.assertEqual(subset_pdf_fonts(raw),raw)
        doc = fitz.open();doc.new_page()
        blank = doc.tobytes();doc.close()
        self.assertEqual(subset_pdf_fonts(blank),blank)

    def test_real_polymer_question_if_built(self):
        path = Path(__file__).resolve().parents[1]/'dist/export-parts/polymer/chemy39-5-4-questions.pdf'
        if not path.exists():
            self.skipTest('Run the export-part builder to include this source regression')
        raw = path.read_bytes()
        stats = {}
        result = subset_pdf_fonts(raw,diagnostics=stats)
        # It is valid for the builder to have already applied this pass.
        self.assertLessEqual(len(result),len(raw))
        self.assert_preserved(raw,result)


if __name__ == '__main__':
    unittest.main()
