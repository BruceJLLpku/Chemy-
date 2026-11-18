"""Verify lossless image recompression without changing original PDF inputs.

This module is for validators only. Canonical copies supply image identity
evidence; final pixel checks must still render the original loaded byte streams.
"""
from hashlib import sha256
from io import BytesIO
import zlib

import pymupdf as fitz
from pypdf import PdfReader, PdfWriter

from pdf_clip_cleanup import (
    _image_fingerprint,
    _image_resource_xrefs,
    _matched_image_difference,
)
from pdf_render_verify import image_paints


def _digest(raw):
    return sha256(raw).hexdigest()


def _page_semantics(page):
    fitz.TOOLS.store_shrink(100)
    return {
        'rect': tuple(page.rect),
        'media': tuple(page.mediabox),
        'crop': tuple(page.cropbox),
        'rotation': page.rotation,
        'text': page.get_text(),
        'paintBounds': page.get_bboxlog(),
        'imagePaints': image_paints(page),
    }


def _image_dictionary(document, xref):
    return {
        key: document.xref_get_key(xref, key)
        for key in document.xref_get_keys(xref)
        if key != 'Length'
    }


def _image_and_mask_xrefs(page):
    images = set(_image_resource_xrefs(page))
    pending = list(images)
    while pending:
        xref = pending.pop()
        for key in ('SMask', 'Mask'):
            kind, value = page.parent.xref_get_key(xref, key)
            if kind == 'xref':
                child = int(value.split()[0])
                if child not in images:
                    images.add(child)
                    pending.append(child)
    return sorted(images)


def _canonical_copy(page):
    """Return an independently audited single-page proof copy and its record."""
    parent = page.parent
    original_raw = parent.stream
    number = page.number
    if (parent.is_dirty or parent.is_repaired
            or not isinstance(original_raw, bytes) or not original_raw
            or type(number) is not int or not 0 <= number < len(parent)):
        raise ValueError('Unchanged original byte stream and page identity required')
    original_semantics = _page_semantics(page)
    reader = PdfReader(BytesIO(original_raw))
    writer = PdfWriter()
    writer.add_page(reader.pages[number])
    buffer = BytesIO()
    writer.write(buffer)
    copied = fitz.open(stream=buffer.getvalue(), filetype='pdf')
    evidence = {
        'originalStreamSha256': _digest(original_raw),
        'originalPageIndex': number,
        'operations': [],
        'oracleUseForbidden': True,
    }
    try:
        if _page_semantics(copied[0]) != original_semantics:
            raise ValueError('Page extraction changed original geometry, text or paint')
        for xref in _image_and_mask_xrefs(copied[0]):
            if copied.xref_get_key(xref, 'Subtype') != ('name', '/Image'):
                continue
            if copied.xref_get_key(xref, 'Filter') != ('name', '/FlateDecode'):
                continue
            if copied.xref_get_key(xref, 'DecodeParms') != ('null', 'null'):
                continue
            if _image_fingerprint(copied, xref) is None:
                continue
            attributes = _image_dictionary(copied, xref)
            encoded = copied.xref_stream_raw(xref)
            decoded = copied.xref_stream(xref)
            if zlib.decompress(encoded) != decoded:
                raise ValueError('Independent Flate decoding differs from native bytes')
            canonical = zlib.compress(decoded, 9)
            if zlib.decompress(canonical) != decoded:
                raise ValueError('Lossless image round trip changed decoded bytes')
            copied.update_stream(xref, canonical, compress=False)
            copied.xref_set_key(xref, 'Filter', '/FlateDecode')
            if 'DecodeParms' in attributes:
                # update_stream removes null DecodeParms; xref_set_key(null)
                # also deletes it. Restore its original explicit null spelling.
                text = copied.xref_object(xref)
                if not text.endswith('>>'):
                    raise ValueError('Image stream no longer has a dictionary')
                copied.update_object(xref, text[:-2] + ' /DecodeParms null\n>>')
            if (_image_dictionary(copied, xref) != attributes
                    or copied.xref_stream(xref) != decoded):
                raise ValueError('Image dictionary or decoded bytes changed')
            evidence['operations'].append({
                'xref': xref,
                'decodedSha256': _digest(decoded),
                'beforeEncodedSha256': _digest(encoded),
                'canonicalEncodedSha256': _digest(canonical),
                'dictionaryUnchanged': True,
                'decodedUnchanged': True,
            })
        if _page_semantics(copied[0]) != original_semantics:
            raise ValueError('Canonicalization changed original geometry, text or paint')
        canonical_raw = copied.tobytes(garbage=0, deflate=False, no_new_id=True)
    finally:
        copied.close()
    result = fitz.open(stream=canonical_raw, filetype='pdf')
    try:
        if _page_semantics(result[0]) != original_semantics:
            raise ValueError('Serialized proof copy changed original page semantics')
        if parent.is_dirty or parent.stream is not original_raw:
            raise ValueError('Original PDF input changed during image verification')
    except BaseException:
        result.close()
        raise
    evidence['canonicalCopySha256'] = _digest(canonical_raw)
    return result, evidence


def canonical_image_proof(expected, actual, original_difference):
    """Run the unchanged complete image proof on independent lossless copies.

    Only explicit FlateDecode streams without nonempty DecodeParms are re-encoded.
    Dictionary semantics, native pixels/masks and page paint are unchanged.
    Ambiguous resources, changed masks, paint, geometry and clipping remain
    subject to the original matcher. This does not authorize a pixel exception.
    """
    left = right = None
    try:
        left, reference = _canonical_copy(expected)
        right, delivered = _canonical_copy(actual)
        proof = _matched_image_difference(left[0], right[0], original_difference)
        return proof, {'reference': reference, 'actual': delivered}
    finally:
        if left is not None:
            left.close()
        if right is not None:
            right.close()
