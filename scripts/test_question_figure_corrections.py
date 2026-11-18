"""Regression tests for the missing polymer NMR plot and its source provenance."""
import hashlib
from io import BytesIO
import json
import unittest

import fitz
from PIL import Image

from question_figure_corrections import ROOT, RECIPE, patch_page, png_bytes, replace_figures, verified_asset


class RepeatedPromptFigureTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.c = json.loads(RECIPE.read_text(encoding='utf8'))['corrections'][0]

    def test_archived_sources_and_reviewed_pixels_are_unchanged(self):
        c = self.c
        for file, expected in [(c['originalSource'], c['originalSourceSha256']),
                               (c['repeatedPromptSource'], c['repeatedPromptSha256'])]:
            self.assertEqual(hashlib.sha256((ROOT / 'sources' / file).read_bytes()).hexdigest(), expected)
        with Image.open(verified_asset(c)) as image, Image.open(BytesIO(png_bytes(c))) as png:
            self.assertEqual(image.convert('RGB').tobytes(), png.tobytes())
            self.assertEqual(image.size, (1505, 533))

    def test_both_web_views_have_one_complete_plot(self):
        c = self.c
        bank = json.loads((ROOT / 'dist/questions.json').read_text(encoding='utf8'))
        body = next(q['body'] for q in bank if q['id'] == c['id'])
        presentation = json.loads((ROOT / 'dist/presentation.json').read_text(encoding='utf8'))[c['id']]['body']
        for html in [body, presentation]:
            self.assertEqual(html.count('src="assets/' + c['asset'] + '"'), 1)
            self.assertTrue(all(old not in html for old in c['replaces']))
            self.assertEqual(replace_figures(html, c), html)
        # Refuse a future layout where deleting placeholders would delete text.
        broken = '<figure>assets/' + c['replaces'][0] + '</figure><p>preserve</p><figure>assets/' + c['replaces'][1] + '</figure>'
        with self.assertRaises(ValueError):
            replace_figures(broken, c)

    def test_source_page_repair_preserves_prompt_and_removes_duplicate_labels(self):
        c = self.c
        with fitz.open(ROOT / 'sources' / c['originalSource']) as source, fitz.open() as doc:
            doc.insert_pdf(source, from_page=c['page'] - 1, to_page=c['page'] - 1)
            self.assertTrue(patch_page(doc[0], c, c['box']))
            self.assertFalse(patch_page(doc[0], c, c['box']))
            page = doc[0]
            self.assertIn('4-3-3-1', page.get_text())
            self.assertIn('第5', page.get_text())
            self.assertEqual(page.get_text(clip=fitz.Rect(c['box'])).strip(), '')
            inserted = [im for im in page.get_images(full=True) if im[2:4] == (1505, 533)]
            self.assertEqual(len(inserted), 1)
            pix = fitz.Pixmap(doc, inserted[0][0])
            with Image.open(verified_asset(c)) as reviewed:
                self.assertEqual(pix.samples, reviewed.convert('RGB').tobytes())

    def test_published_book_has_unsplittable_complete_plot(self):
        c = self.c
        layout = json.loads((ROOT / 'data/continuous-books/polymer-questions.json').read_text(encoding='utf8'))
        index = json.loads((ROOT / 'dist/export-index/polymer.json').read_text(encoding='utf8'))
        self.assertEqual(layout['questions'][c['id']], index['questions'][c['id']])
        path = ROOT / 'dist/downloads/polymer-questions.pdf'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), layout['sha256'])
        with fitz.open(path) as doc:
            self.assertEqual(len(doc), layout['pages'])
            matches = []
            for region in index['questions'][c['id']]:
                page = doc[region['page']]
                for im in page.get_images(full=True):
                    if im[2:4] != (1505, 533):
                        continue
                    for rect in page.get_image_rects(im[0]):
                        if any(a - .01 <= rect.y0 and b + .01 >= rect.y1 for a, b in region['bands']):
                            matches.append(rect)
            self.assertEqual(len(matches), 1)
            self.assertGreater(matches[0].height, 160)


if __name__ == '__main__':
    unittest.main()
