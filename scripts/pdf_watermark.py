"""Add a separate, removable Chemy watermark layer without changing question content."""
import argparse
import hashlib
from io import BytesIO
from pathlib import Path

from PIL import Image
from pypdf import PdfReader, PdfWriter
from pypdf.generic import (ArrayObject, BooleanObject, DecodedStreamObject,
                           DictionaryObject, FloatObject, NameObject,
                           NumberObject, TextStringObject)

ROOT = Path(__file__).resolve().parents[1]
ASSET = ROOT / 'dist/assets/chemy-watermark.jpg'
MARKER = '/ChemyWatermark'
OPACITY = .18
WIDTH_RATIO = .62


def contents(page):
    value = page.get('/Contents')
    if value is None:
        return []
    resolved = value.get_object()
    return list(resolved) if isinstance(resolved, ArrayObject) else [value]


def strip_watermark(page):
    streams = contents(page)
    clean = [s for s in streams if not s.get_object().get(MARKER)]
    if len(clean) != len(streams):
        page[NameObject('/Contents')] = ArrayObject(clean)
        return True
    return False


def unwatermarked_bytes(path):
    """Give the crop-index builder original ink, excluding decorative watermark ink."""
    raw = Path(path).read_bytes()
    if MARKER.encode() not in raw:
        return raw
    writer = PdfWriter(BytesIO(raw), incremental=True)
    changed = any([strip_watermark(page) for page in writer.pages])
    if not changed:
        return raw
    result = BytesIO()
    writer.write(result)
    return result.getvalue()


def stamp_pdf(path):
    path = Path(path)
    image_bytes = ASSET.read_bytes()
    version = hashlib.sha256(image_bytes + f'{OPACITY}:{WIDTH_RATIO}'.encode()).hexdigest()
    writer = PdfWriter(path, incremental=True)
    if all(any(s.get_object().get('/ChemyWatermarkVersion') == version
               for s in contents(page)) for page in writer.pages):
        return len(writer.pages), False

    with Image.open(ASSET) as image:
        iw, ih = image.size
        assert image.mode == 'RGB', 'Watermark must be an RGB JPEG'
    jpeg = DecodedStreamObject()
    jpeg.set_data(image_bytes)
    jpeg.update({NameObject('/Type'): NameObject('/XObject'),
                 NameObject('/Subtype'): NameObject('/Image'),
                 NameObject('/Width'): NumberObject(iw), NameObject('/Height'): NumberObject(ih),
                 NameObject('/ColorSpace'): NameObject('/DeviceRGB'),
                 NameObject('/BitsPerComponent'): NumberObject(8),
                 NameObject('/Filter'): NameObject('/DCTDecode')})
    image_ref = writer._add_object(jpeg)
    state = DictionaryObject({NameObject('/Type'): NameObject('/ExtGState'),
                              NameObject('/ca'): FloatObject(OPACITY),
                              NameObject('/CA'): FloatObject(OPACITY),
                              NameObject('/BM'): NameObject('/Multiply')})
    form = DecodedStreamObject()
    form.set_data(f'q /WMState gs {iw} 0 0 {ih} 0 0 cm /WMImage Do Q\n'.encode())
    form.update({NameObject('/Type'): NameObject('/XObject'),
                 NameObject('/Subtype'): NameObject('/Form'),
                 NameObject('/BBox'): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(iw), NumberObject(ih)]),
                 NameObject('/Resources'): DictionaryObject({
                     NameObject('/XObject'): DictionaryObject({NameObject('/WMImage'): image_ref}),
                     NameObject('/ExtGState'): DictionaryObject({NameObject('/WMState'): state})})})
    form_ref = writer._add_object(form)
    for page in writer.pages:
        strip_watermark(page)
        box = page.mediabox
        width = min(float(box.width) * WIDTH_RATIO, float(box.height) * .60 * iw / ih)
        height = width * ih / iw
        x = float(box.left) + (float(box.width) - width) / 2
        y = float(box.bottom) + (float(box.height) - height) / 2
        resources = DictionaryObject(page['/Resources'].get_object())
        xobjects = DictionaryObject(resources.get('/XObject', DictionaryObject()).get_object())
        xobjects[NameObject(MARKER)] = form_ref
        resources[NameObject('/XObject')] = xobjects
        page[NameObject('/Resources')] = resources
        layer = DecodedStreamObject()
        layer.set_data(f'q {width/iw:.8f} 0 0 {height/ih:.8f} {x:.4f} {y:.4f} cm {MARKER} Do Q\n'.encode())
        layer[NameObject(MARKER)] = BooleanObject(True)
        layer[NameObject('/ChemyWatermarkVersion')] = TextStringObject(version)
        page[NameObject('/Contents')] = ArrayObject(contents(page) + [writer._add_object(layer)])
    # Incremental writing retains the original PDF bytes and vector operators.
    target = path.with_suffix('.watermark.tmp')
    try:
        with target.open('wb') as stream:
            writer.write(stream)
        assert len(PdfReader(target).pages) == len(writer.pages)
        target.replace(path)
    finally:
        if target.exists():
            target.unlink()
    return len(writer.pages), True


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('files', nargs='*', type=Path)
    args = parser.parse_args()
    for path in args.files or sorted((ROOT / 'dist/downloads').glob('*.pdf')):
        pages, changed = stamp_pdf(path)
        print(('STAMPED' if changed else 'UNCHANGED'), path.name, pages, 'pages', flush=True)
