"""Whole-topic downloads preserve native pages, bookmarks and one watermark."""
from io import BytesIO
import unittest
from unittest.mock import patch

import pymupdf as fitz
from PIL import Image, ImageChops
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DictionaryObject, FloatObject, NameObject

from build_export_parts import make_clean_book
import build_export_parts as builder
import test_clean_book_pixels as book_pixels
from test_pdf_image_sampling import sample as image_sample


def source_page(*, indirect_resources, indirect_state):
    with fitz.open() as doc:
        page = doc.new_page(width=595.28, height=841.89)
        page.insert_text((50, 40), 'Native topic page', fontsize=12)
        raw = doc.tobytes()
    writer = PdfWriter(clone_from=BytesIO(raw))
    page = writer.pages[0]
    resources = page['/Resources'].get_object()
    state = DictionaryObject({NameObject('/SourceAlpha'): DictionaryObject({
        NameObject('/ca'): FloatObject(.7)})})
    resources[NameObject('/ExtGState')] = writer._add_object(state) if indirect_state else state
    page[NameObject('/Resources')] = writer._add_object(resources) if indirect_resources else resources
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


class CleanBookTests(unittest.TestCase):
    def test_multiple_compaction_batches_preserve_later_shared_image_references(self):
        pages = []
        for number in range(7):
            image = Image.new('RGBA', (3, 3), (20, 80, 180, 255))
            # The RGB bytes are identical; two independent masks must remain
            # distinct even as duplicates merge across batch boundaries.
            image.putpixel((0, 0), (20, 80, 180, 40 if number % 2 else 160))
            png = BytesIO()
            image.save(png, format='PNG')
            with fitz.open() as doc:
                page = doc.new_page(width=300, height=400)
                page.insert_text((20, 30), f'Page {number + 1}: native H2O', fontsize=12)
                xref = page.insert_image((20, 45, 55, 80), stream=png.getvalue())
                page.insert_image((65, 45, 100, 80), xref=xref)
                page.draw_line((20, 90), (100+number, 90), color=(1, 0, 0), width=.7)
                pages.append(doc.tobytes(garbage=1))
        toc = [[1, 'Start', 1], [2, 'After first batch', 3], [1, 'Last batch', 7]]
        checkpoints = []
        original_compact = builder._compact_book_resources

        def record_checkpoint(raw):
            with fitz.open('pdf', raw) as doc:
                checkpoints.append(len(doc))
            return original_compact(raw)

        with patch.object(builder, '_compact_book_resources', side_effect=record_checkpoint):
            batched = make_clean_book(pages.__getitem__, len(pages), 'Batched native book', toc, batch_size=2)
        self.assertEqual(checkpoints, [2, 4, 6, 7, 7])
        unbatched = make_clean_book(pages.__getitem__, len(pages), 'Batched native book', toc, batch_size=1000)
        reader = PdfReader(BytesIO(batched), strict=True)
        shared = {}
        for number, page in enumerate(reader.pages):
            entries = []
            for reference in page['/Resources']['/XObject'].values():
                image = reference.get_object()
                self.assertEqual(image['/Subtype'], '/Image')
                if image['/Width'] == 3:
                    mask = image['/SMask'].get_object()
                    self.assertEqual(mask['/Subtype'], '/Image')
                    entries.append((image.get_data(), mask.get_data(), reference.idnum))
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0], entries[1], 'same-page aliases must retain one image')
            image_key = entries[0][:2]
            if image_key in shared:
                self.assertEqual(shared[image_key], entries[0][2], 'later batches must share earlier identical resources')
            shared[image_key] = entries[0][2]
        self.assertEqual(len(shared), 2, 'independent alpha masks must not collapse together')
        with fitz.open('pdf', unbatched) as baseline, fitz.open('pdf', batched) as actual:
            self.assertEqual(actual.get_toc(), toc)
            self.assertEqual(actual.metadata['title'], 'Batched native book')
            for number in range(7):
                self.assertEqual(actual[number].rect, baseline[number].rect)
                self.assertEqual(actual[number].get_text(), baseline[number].get_text())
                self.assertFalse(actual[number].get_xobjects())
                for scale in (2, 4):
                    rendered = []
                    for doc in (baseline, actual):
                        fitz.TOOLS.store_shrink(100)
                        fitz.TOOLS.mupdf_warnings(reset=True)
                        pix = doc[number].get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                        self.assertFalse(fitz.TOOLS.mupdf_warnings(reset=True))
                        rendered.append(Image.frombytes('RGB', (pix.width, pix.height), pix.samples))
                    self.assertIsNone(ImageChops.difference(*rendered).getbbox())

    def test_invalid_batch_size_is_rejected_before_loading_source_pages(self):
        for size in (0, -1, True, 1.5, None):
            with self.subTest(size=size), self.assertRaises(ValueError):
                make_clean_book(lambda _: self.fail('invalid batch loaded a page'), 1, 'Invalid', batch_size=size)

    def test_resource_variants_native_text_bookmarks_and_watermark(self):
        for indirect_resources in (False, True):
            for indirect_state in (False, True):
                with self.subTest(resources=indirect_resources, state=indirect_state):
                    raw = source_page(indirect_resources=indirect_resources, indirect_state=indirect_state)
                    toc = [[1, 'First question', 1], [1, 'Second question', 2]]
                    result = make_clean_book(lambda _: raw, 2, 'Test topic', toc)
                    reader = PdfReader(BytesIO(result), strict=True)
                    with fitz.open('pdf', raw) as source, fitz.open('pdf', result) as book:
                        self.assertEqual(len(book), 2)
                        self.assertEqual(book.get_toc(), toc)
                        self.assertEqual(book.metadata['title'], 'Test topic')
                        self.assertFalse(any('/Subtype /Form' in book.xref_object(n)
                                             for n in range(1, book.xref_length())))
                        for index, page in enumerate(book):
                            self.assertEqual(page.get_text(), source[0].get_text())
                            self.assertEqual(sum(kind == 'fill-image' for kind, _ in page.get_bboxlog()), 1)
                            pixels = page.get_pixmap(clip=fitz.Rect(110, 220, 485, 620))
                            self.assertLess(min(pixels.samples), 230)
                            # The top margin is outside the centred watermark.
                            rect = fitz.Rect(0, 0, 595, 80)
                            a, b = page.get_pixmap(clip=rect), source[0].get_pixmap(clip=rect)
                            difference = ImageChops.difference(
                                Image.frombytes('RGB', (a.width, a.height), a.samples),
                                Image.frombytes('RGB', (b.width, b.height), b.samples))
                            self.assertLessEqual(max(hi for lo, hi in difference.getextrema()), 2)
                            states = reader.pages[index]['/Resources']['/ExtGState']
                            self.assertAlmostEqual(float(states['/ChemyExportWatermark']['/ca']), .18)
                            self.assertEqual(states['/ChemyExportWatermark']['/BM'], '/Multiply')


class CleanBookPixelEvidenceTests(unittest.TestCase):
    def test_changed_image_mask_duplicate_or_local_line_stays_rejected(self):
        for change in ({'copies': 0}, {'mask': 255}, {'copies': 2}, {'line': True}):
            with self.subTest(change=change), fitz.open('pdf', image_sample()) as expected, \
                    fitz.open('pdf', image_sample(**change)) as actual:
                result = book_pixels.compare_page(expected[0], actual[0])
                self.assertGreater(result['maxDelta'], 8)
                self.assertEqual(result['imageSamplingProof']['matched'], 0)

    def test_image_identity_requires_both_full_page_sampling_phases(self):
        # Keep actual image bytes, native paint and clips unchanged, then inject
        # controlled renderer sampling noise. The real structural proof runs;
        # only the rasterizer is replaced to exercise both phase outcomes.
        raw = image_sample()
        native_pixmap = fitz.Page.get_pixmap
        native_no_cache = book_pixels.render_no_tile_cache

        def perturb(pixmap, amount):
            image = Image.frombytes('RGB', (pixmap.width, pixmap.height), pixmap.samples)
            pixel = image.getpixel((82, 90))
            image.putpixel((82, 90), tuple(value + amount if value <= 255 - amount else value - amount for value in pixel))
            buffer = BytesIO()
            image.save(buffer, format='PNG')
            return fitz.Pixmap(buffer.getvalue())

        for second_phase_delta in (0, 9):
            with self.subTest(second_phase_delta=second_phase_delta), fitz.open('pdf', raw) as expected, \
                    fitz.open('pdf', raw) as actual:
                def cached(page, *args, **kwargs):
                    pix = native_pixmap(page, *args, **kwargs)
                    return perturb(pix, 20) if page.parent is actual else pix

                def uncached(page, *args, **kwargs):
                    pix = native_no_cache(page, *args, **kwargs)
                    if page.parent is not actual:
                        return pix
                    offset = kwargs.get('offset', (0, 0))
                    amount = 20 if offset == (0, 0) else second_phase_delta if offset == (.73, .61) else 0
                    return perturb(pix, amount) if amount else pix

                with patch.object(fitz.Page, 'get_pixmap', cached), \
                        patch.object(book_pixels, 'render_no_tile_cache', side_effect=uncached):
                    result = book_pixels.compare_page(expected[0], actual[0])
                self.assertEqual(result['initialMaxDelta'], 20)
                self.assertEqual(result['imageSamplingProof']['matched'], 1)
                self.assertEqual(result['imageSamplingPhaseDeltas'], [0, second_phase_delta])
                self.assertEqual(result['maxDelta'], 0 if second_phase_delta == 0 else 20)


if __name__ == '__main__':
    unittest.main()
