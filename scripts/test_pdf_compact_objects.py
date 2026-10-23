"""Pure synthetic whole-document compaction regression.

The 101-image reference topology was minimized from organic questions page181.
Every payload is replaced with generated 2x2 colours: no exam content remains.
Deleting any one resource loses the pinned MuPDF deduplication failure.
"""
from io import BytesIO
from collections import Counter
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
import pymupdf as fitz
from PIL import Image,ImageChops
from pypdf import PdfReader,PdfWriter
from pypdf.generic import ArrayObject,DecodedStreamObject,DictionaryObject,Fit,NameObject,NumberObject
from pdf_font_subset import compact_pdf_objects
from build_export_parts import make_clean_book, make_part


def write(writer):
    stream=BytesIO();writer.write(stream);return stream.getvalue()


def image_topology():
    rows=json.loads((ROOT/'scripts/fixtures/pdf-image-topology.json').read_text())
    writer=PdfWriter();page=writer.add_blank_page(width=500,height=500);images=DictionaryObject()
    def fill(obj,data,colour):
        obj.set_data(data)
        obj.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Image'),
                    NameObject('/Width'):NumberObject(2),NameObject('/Height'):NumberObject(2),
                    NameObject('/BitsPerComponent'):NumberObject(8),NameObject('/ColorSpace'):NameObject(colour)})
    for number,colour,alpha in rows:
        # Allocate the parent before its mask, retaining the failing reference
        # order and the equivalence classes of duplicate image/mask payloads.
        image=DecodedStreamObject();reference=writer._add_object(image)
        fill(image,bytes([colour,128,255-colour])*4,'/DeviceRGB')
        if alpha is not None:
            mask=DecodedStreamObject();mask_ref=writer._add_object(mask)
            fill(mask,bytes([255,alpha,128,0]),'/DeviceGray');image[NameObject('/SMask')]=mask_ref
        images[NameObject('/Clean'+str(number))]=reference
    page[NameObject('/Resources')]=DictionaryObject({NameObject('/XObject'):images})
    content=DecodedStreamObject()
    content.set_data('\n'.join(f'q 20 0 0 20 {20+(i%20)*23} {20+(i//20)*25} cm /Clean{row[0]} Do Q'
                               for i,row in enumerate(rows)).encode())
    page[NameObject('/Contents')]=writer._add_object(content)
    return write(writer)


def catalog_evidence(raw):
    reader=PdfReader(BytesIO(raw));outline=[]
    def walk(items,level=0):
        for item in items:
            if isinstance(item,list):walk(item,level+1)
            else:outline.append((item.title,reader.get_destination_page_number(item),level,
                                 item.get('/Type'),item.get('/Left'),item.get('/Top'),item.get('/Zoom')))
    walk(reader.outline)
    return (dict(reader.metadata),outline,[tuple(p.mediabox)for p in reader.pages],
            reader.page_labels,reader.trailer['/Root'].get('/PageMode'))


def image_evidence(raw, *, fixture_only=False):
    reader=PdfReader(BytesIO(raw));result={}
    for name,ref in reader.pages[0]['/Resources']['/XObject'].items():
        if fixture_only:
            # Mini-page resource names gain a collision-safe namespace. Books
            # also contain the intended watermark, which is not this fixture.
            if 'Clean' not in name:
                continue
            name = '/Clean' + name.rsplit('Clean', 1)[1]
        obj=ref.get_object()
        if not isinstance(obj,DictionaryObject) or obj.get('/Subtype')!='/Image':
            raise AssertionError(f'{name} does not reference an image')
        mask=obj.get('/SMask');mask=mask.get_object()if mask else None
        if mask is not None and (not isinstance(mask,DictionaryObject)or mask.get('/Subtype')!='/Image'):
            raise AssertionError(f'{name} has a damaged alpha mask')
        result[name]=(obj['/Width'],obj['/Height'],obj['/ColorSpace'],obj['/BitsPerComponent'],
                      obj.get_data(),mask.get_data()if mask is not None else None)
    return result


class DocumentCompactionTests(unittest.TestCase):
    def compact(self,raw):
        compacted=compact_pdf_objects(raw)
        with fitz.open('pdf',compacted)as doc:
            return doc.tobytes(garbage=1,deflate=True,use_objstms=1)

    def assert_pixels(self,before,after):
        with fitz.open('pdf',before)as old,fitz.open('pdf',after)as new:
            self.assertEqual(len(old),len(new))
            for scale in (2,4):
                for number in range(len(old)):
                    images=[]
                    for doc in (old,new):
                        fitz.TOOLS.store_shrink(100);fitz.TOOLS.mupdf_warnings(reset=True)
                        pix=doc[number].get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False)
                        self.assertFalse(fitz.TOOLS.mupdf_warnings(reset=True))
                        images.append(Image.frombytes('RGB',(pix.width,pix.height),pix.samples))
                    self.assertIsNone(ImageChops.difference(*images).getbbox())

    def test_image_and_independent_alpha_references_survive_compaction(self):
        before=image_topology();after=self.compact(before)
        self.assertEqual(image_evidence(before),image_evidence(after))
        self.assert_pixels(before,after)

    def test_part_and_book_serialization_keep_every_image_and_mask(self):
        before = image_topology()
        bands = [{'sourcePage': 0, 'box': [0, 0, 500, 500]}]
        part = make_part(lambda _: before, bands, 'synthetic-image-topology')
        # clip_to_rect assigns native Im names before browser namespacing. The
        # complete value multiset plus exact pixels proves each alias survived.
        self.assertEqual(Counter(image_evidence(before).values()), Counter(image_evidence(part).values()))
        self.assert_pixels(before, part)
        book = make_clean_book(lambda _: before, 1, 'Synthetic image topology', [[1, 'Question', 1]])
        self.assertEqual(image_evidence(before), image_evidence(book, fixture_only=True))
        with fitz.open('pdf', book) as doc:
            self.assertEqual(doc.get_toc(), [[1, 'Question', 1]])

    def test_info_precise_nested_outlines_and_page_catalog_survive(self):
        writer=PdfWriter();writer.add_metadata({'/Title':'中文专题册','/Author':'Chemy',
            '/ChemyExtra':'自定义信息','/CreationDate':'D:20261023000000Z'})
        for n in range(3):
            page=writer.add_blank_page(width=300+n*10,height=400)
            content=DecodedStreamObject();content.set_data(f'{n/3} 0 .5 rg 30 40 100 200 re f'.encode())
            page[NameObject('/Contents')]=writer._add_object(content)
        parent=writer.add_outline_item('专题甲',0,bold=True)
        writer.add_outline_item('子题精确位置',1,parent=parent,fit=Fit.xyz(30,140,1.25))
        writer.add_outline_item('专题乙',2,fit=Fit.fit_horizontally(150))
        writer._root_object[NameObject('/PageMode')]=NameObject('/UseOutlines')
        writer._root_object[NameObject('/PageLabels')]=DictionaryObject({NameObject('/Nums'):ArrayObject([
            NumberObject(0),DictionaryObject({NameObject('/S'):NameObject('/r')}),
            NumberObject(1),DictionaryObject({NameObject('/S'):NameObject('/D'),NameObject('/St'):NumberObject(1)})])})
        before=write(writer);after=self.compact(before)
        self.assertEqual(catalog_evidence(before),catalog_evidence(after));self.assert_pixels(before,after)


if __name__=='__main__':unittest.main()
