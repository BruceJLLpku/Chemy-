"""Subset existing embedded font programs without rewriting PDF character maps.

MuPDF's fallback subsetter skips already tagged subset fonts. Source libraries
also contain inline font dictionaries. This pass handles both, retains glyph
IDs, and leaves Encoding, widths, CIDToGIDMap and ToUnicode untouched. It uses
only the embedded font bytes; no locally installed fonts are consulted.
"""
from functools import lru_cache
from io import BytesIO
import re
import zlib

import pymupdf as fitz
from fontTools import subset
from fontTools.ttLib import TTFont, TTLibError
from PIL import Image, ImageChops
from pypdf import PdfReader, PdfWriter


def compact_pdf_objects(raw: bytes) -> bytes:
    """Deduplicate resources without MuPDF's image/mask reference corruption.

    MuPDF garbage levels 3/4 can remap a valid image reference to a different
    object when duplicate images have independently allocated alpha masks.
    Keep native saves at garbage=1 and deduplicate with pypdf instead. Cloning
    the complete document retains Info metadata, outlines, page labels and
    other catalog entries that a page-by-page copy would silently discard.
    """
    writer = PdfWriter(clone_from=PdfReader(BytesIO(raw)))
    writer.compress_identical_objects(remove_duplicates=True, remove_unreferenced=True)
    output = BytesIO()
    writer.write(output)
    return output.getvalue()


def _name(value):
    text = re.sub(r'#([0-9a-fA-F]{2})',lambda m: chr(int(m[1],16)),str(value).lstrip('/'))
    return re.sub(r'^[A-Z]{6}\+','',text)


@lru_cache(maxsize=64)
def _subset_program(program, glyphs, hinting):
    font = TTFont(BytesIO(program),recalcTimestamp=False)
    options = subset.Options()
    options.retain_gids = True
    # Simple TrueType fonts in the source use Macintosh-only character maps.
    # FontTools otherwise drops them even with retain_gids, so PDF text still
    # extracts through ToUnicode but every displayed character becomes .notdef.
    options.legacy_cmap = True
    options.symbol_cmap = True
    options.hinting = hinting
    options.layout_features = []  # PDF content already supplies glyph placement.
    options.ignore_missing_glyphs = True
    options.notdef_outline = True
    options.recalc_timestamp = False
    # Some embedded CID font programs deliberately have no Unicode cmap.
    options.prune_unicode_ranges = False
    options.prune_codepage_ranges = False
    # Keep every name/copyright/license record, including non-English records.
    options.name_IDs = ['*']
    options.name_languages = ['*']
    worker = subset.Subsetter(options=options)
    worker.populate(gids=glyphs)
    worker.subset(font)
    output = BytesIO()
    font.save(output)
    font.close()
    return output.getvalue()


def _program_usage(raw, doc):
    # Glyph IDs must come from this document's own font streams, too.
    fitz.TOOLS.store_shrink(100)
    wanted = {}
    for page in doc:
        for span in page.get_texttrace():
            wanted.setdefault(_name(span['font']),set()).update(c[1] for c in span['chars'] if c[1]>=0)
    reader = PdfReader(BytesIO(raw))
    programs = {}
    for page in reader.pages:
        resources = page.get('/Resources',{})
        if hasattr(resources,'get_object'):
            resources = resources.get_object()
        fonts = resources.get('/Font',{})
        if hasattr(fonts,'get_object'):
            fonts = fonts.get_object()
        for font in fonts.values():
            font = font.get_object()
            names = {_name(font.get('/BaseFont',''))}
            descendants = font.get('/DescendantFonts',[font])
            if hasattr(descendants,'get_object'):
                descendants = descendants.get_object()
            for descendant in descendants:
                descendant = descendant.get_object()
                names.add(_name(descendant.get('/BaseFont','')))
                descriptor = descendant.get('/FontDescriptor')
                if descriptor is None:
                    continue
                descriptor = descriptor.get_object()
                for key in ('/FontFile2','/FontFile3'):
                    ref = descriptor.get(key)
                    if ref is None or not hasattr(ref,'idnum'):
                        continue
                    item = programs.setdefault(ref.idnum,{'gids':set(),'names':set(),'length1':False})
                    item['length1'] |= key == '/FontFile2'
                    item['names'].update(names)
                    for name in names:
                        item['gids'].update(wanted.get(name,set()))
    return programs


def _matches(original, candidate):
    """Compare pages without cross-document reuse of inline font dictionaries.

    MuPDF's PDF store compares direct resource dictionaries by their contents.
    Equal indirect-reference numbers inside those dictionaries can collide even
    when the references belong to different PDFs and point to different font
    streams. Reopening serialized bytes alone does not isolate that store.
    Complete text extraction and rendering on each side before clearing it and
    switching documents. Keep only one page pair of raster samples in memory.
    """
    if len(original) != len(candidate):
        return False, 'page count changed', None
    maximum = 0
    for index in range(len(original)):
        source, result = original[index], candidate[index]
        if source.rect != result.rect:
            return False, f'page {index+1}: text or geometry changed', None
        fitz.TOOLS.store_shrink(100)
        fitz.TOOLS.mupdf_warnings(reset=True)
        source_text = source.get_text()
        a = source.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
        source_warnings = fitz.TOOLS.mupdf_warnings(reset=True)
        fitz.TOOLS.store_shrink(100)
        result_text = result.get_text()
        b = result.get_pixmap(matrix=fitz.Matrix(2,2),alpha=False)
        result_warnings = fitz.TOOLS.mupdf_warnings(reset=True)
        fitz.TOOLS.store_shrink(100)
        if result_warnings and result_warnings != source_warnings:
            return False, f'page {index+1}: new renderer warnings: {result_warnings}', None
        if source_text != result_text:
            return False, f'page {index+1}: text or geometry changed', None
        first = Image.frombytes('RGB',(a.width,a.height),a.samples)
        second = Image.frombytes('RGB',(b.width,b.height),b.samples)
        delta = max(pair[1] for pair in ImageChops.difference(first,second).getextrema())
        maximum = max(maximum,delta)
        if delta > 8:
            return False, f'page {index+1}: rendered channel delta {delta}/255', maximum
    return True, None, maximum


def subset_pdf_fonts(raw: bytes, *, diagnostics=None) -> bytes:
    """Return a verified smaller PDF, or the original bytes if unsafe/unhelpful.

    All font IDs and PDF character maps are retained. Hint removal is attempted
    first; any visual difference retries with hinting retained. If that also
    differs, the original bytes are returned and diagnostics explains why.
    Unsupported font formats are left intact. Every accepted replacement is
    checked for identical extracted text and rendered appearance at 144 dpi.
    """
    report = diagnostics if diagnostics is not None else {}
    report.update(before_bytes=len(raw),after_bytes=len(raw),changed_fonts=0)
    original = fitz.open('pdf',raw)
    try:
        programs = _program_usage(raw,original)
        for hinting in (False,True):
            doc = fitz.open('pdf',raw)
            count = 0
            skipped = []
            try:
                for xref,item in programs.items():
                    if not item['gids']:
                        continue
                    program = doc.xref_stream(xref)
                    try:
                        smaller = _subset_program(program,tuple(sorted(item['gids'])),hinting)
                    except (TTLibError,KeyError,ValueError,AssertionError) as error:
                        skipped.append({'fonts':sorted(item['names']),'reason':str(error)})
                        continue
                    if len(zlib.compress(smaller)) >= len(doc.xref_stream_raw(xref)):
                        continue
                    doc.update_stream(xref,smaller,compress=True)
                    if item['length1']:
                        doc.xref_set_key(xref,'Length1',str(len(smaller)))
                    count += 1
                if not count:
                    report.update(skipped_fonts=skipped)
                    return raw
                result = doc.tobytes(garbage=1,deflate=True,use_objstms=1,no_new_id=True)
            finally:
                doc.close()
            candidate = fitz.open('pdf',result)
            try:
                valid, reason, delta = _matches(original,candidate)
            finally:
                candidate.close()
            if valid and len(result) < len(raw):
                report.pop('retained_original_reason',None)
                report.update(after_bytes=len(result),changed_fonts=count,hinting_retained=hinting,
                              render_max_delta=delta,skipped_fonts=skipped)
                return result
            report['retained_original_reason'] = reason or 'No file-size reduction'
        return raw
    finally:
        original.close()
