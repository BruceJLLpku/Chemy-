"""Verify a complete relocated placement on two native PDFium pixel grids.

The caller supplies the already loaded source and actual pages. This oracle
never extracts, rewrites, or saves a PDF page and never resamples a bitmap.
PDFium applies the page's intrinsic display matrix before the supplied matrix:
https://pdfium.googlesource.com/pdfium/+/refs/heads/main/fpdfsdk/fpdf_view.cpp
"""
import ctypes
import hashlib
import math

import pypdfium2 as pdfium
import pypdfium2.raw as raw
from PIL import ImageChops


DPIS = (144, 288)
MAX_CHANNEL_DELTA = 8


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _loaded(page):
    document = page.parent
    _require(document is not None and not document.is_closed, 'Page has no open parent')
    _require(not document.is_dirty and not document.is_repaired,
             'Original loaded PDF is dirty or repaired')
    data, index = document.stream, page.number
    _require(isinstance(data, bytes) and bool(data), 'Original loaded PDF bytes unavailable')
    _require(type(index) is int and 0 <= index < len(document), 'Invalid original page index')
    rectangle = tuple(page.rect)
    _require(all(math.isfinite(v) for v in rectangle) and page.rect.width > 0 and page.rect.height > 0,
             'Invalid original page dimensions')
    _require(page.rotation == 0 and rectangle[:2] == (0, 0), 'Unsupported original page rotation or origin')
    return data, index, {
        'inputSha256': hashlib.sha256(data).hexdigest(), 'pageIndex': index,
        'pageCount': len(document), 'pageRect': list(rectangle),
        'input': 'unchanged_loaded_parent_stream',
    }


def _render_original(data, index, identity, size, matrix):
    """Render the original document/index directly into a fixed device clip."""
    _require(all(math.isfinite(v) for v in matrix), 'Nonfinite placement matrix')
    _require(abs(matrix[0] * matrix[3] - matrix[1] * matrix[2]) > 0,
             'Singular placement matrix')
    width, height = size
    _require(width > 0 and height > 0, 'Empty placement bitmap')
    with pdfium.PdfDocument(data) as document:
        _require(len(document) == identity['pageCount'], 'Original document page count differs')
        page = document[index]
        try:
            w, h = page.get_size()
            _require(all(math.isfinite(v) and v > 0 for v in (w, h)), 'Invalid PDFium page size')
            _require(page.get_rotation() == 0, 'Unsupported PDFium page rotation')
            expected_box = (0, 0, w, h)
            for box in (page.get_mediabox(), page.get_cropbox()):
                _require(all(math.isfinite(v) and abs(v - target) <= 1e-4
                             for v, target in zip(box, expected_box)),
                         'Unsupported PDFium media/crop geometry')
            _require(abs(w - identity['pageRect'][2]) <= 1e-4 and
                     abs(h - identity['pageRect'][3]) <= 1e-4,
                     'Loaded page and PDFium geometry differ')
            bitmap = pdfium.PdfBitmap.new_native(width, height, format=raw.FPDFBitmap_BGR)
            try:
                bitmap.fill_rect((255, 255, 255, 255), 0, 0, width, height)
                transform = raw.FS_MATRIX(*matrix)
                clip = raw.FS_RECTF(0, 0, width, height)
                raw.FPDF_RenderPageBitmapWithMatrix(
                    bitmap, page, ctypes.byref(transform), ctypes.byref(clip), raw.FPDF_ANNOT)
                return bitmap.to_pil().convert('RGB').copy()
            finally:
                bitmap.close()
        finally:
            page.close()


def compare_placement_pdfium(source, actual, source_rect, x, top, scale):
    """Fail closed unless both unmasked full-placement rasters differ by <=8."""
    result = {
        'passed': False, 'checks': [], 'requiredDpis': list(DPIS),
        'maxAllowedChannelDelta': MAX_CHANNEL_DELTA,
        'renderer': 'PDFium.FPDF_RenderPageBitmapWithMatrix',
        'unmaskedFullPlacement': True, 'resampledBitmap': False,
        'clonedPageDuringOracle': False,
    }
    try:
        source_raw, source_index, source_identity = _loaded(source)
        actual_raw, actual_index, actual_identity = _loaded(actual)
        result.update(source=source_identity, actual=actual_identity)
        _require(source.parent is not actual.parent and source_identity['inputSha256'] != actual_identity['inputSha256'],
                 'Source and actual must have independent original inputs')
        rectangle = tuple(source_rect)
        _require(len(rectangle) == 4 and all(math.isfinite(v) for v in (*rectangle, x, top, scale))
                 and scale > 0 and source_rect.width > 0 and source_rect.height > 0,
                 'Invalid placement geometry')
        _require(source.rect.contains(source_rect), 'Source rectangle outside original source page')
        target = (x, top, x + source_rect.width * scale, top + source_rect.height * scale)
        _require(target[0] >= 0 and target[1] >= 0 and target[2] <= actual.rect.width
                 and target[3] <= actual.rect.height, 'Placement outside actual page')
        result.update(sourceRect=list(rectangle), targetRect=list(target), scale=scale)
        for dpi in DPIS:
            zoom = dpi / 72
            left, upper = math.floor(target[0] * zoom), math.floor(target[1] * zoom)
            right, lower = math.ceil(target[2] * zoom), math.ceil(target[3] * zoom)
            size = right - left, lower - upper
            expected_matrix = (scale * zoom, 0, 0, scale * zoom,
                               (x - source_rect.x0 * scale) * zoom - left,
                               (top - source_rect.y0 * scale) * zoom - upper)
            actual_matrix = (zoom, 0, 0, zoom, -left, -upper)
            expected = _render_original(source_raw, source_index, source_identity, size, expected_matrix)
            observed = _render_original(actual_raw, actual_index, actual_identity, size, actual_matrix)
            _require(expected.mode == observed.mode == 'RGB' and expected.size == observed.size == size,
                     'Placement bitmap geometry differs')
            maximum = max(high for _, high in ImageChops.difference(expected, observed).getextrema())
            result['checks'].append({
                'dpi': dpi, 'maxDelta': maximum, 'passed': maximum <= MAX_CHANNEL_DELTA,
                'bitmapSize': list(size), 'deviceBounds': [left, upper, right, lower],
                'expectedMatrix': list(expected_matrix), 'actualMatrix': list(actual_matrix),
            })
        _require(source.parent.stream is source_raw and actual.parent.stream is actual_raw,
                 'Original loaded PDF bytes changed during rendering')
        _require(not source.parent.is_dirty and not actual.parent.is_dirty and
                 not source.parent.is_repaired and not actual.parent.is_repaired,
                 'Original PDF changed during rendering')
        result['passed'] = (len(result['checks']) == 2 and
                            tuple(check['dpi'] for check in result['checks']) == DPIS and
                            all(check['passed'] for check in result['checks']))
    except Exception as error:
        result['error'] = f'{type(error).__name__}: {error}'
    return result
