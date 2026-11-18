"""Shared PDF validation inputs; never modify the delivered PDF files."""
import hashlib
from io import BytesIO
from pathlib import Path

import fitz
from pypdf import PdfReader, PdfWriter
from pypdf.generic import ContentStream, NameObject

ROOT = Path(__file__).resolve().parents[1]


def open_without_browser_watermark(path):
    reader=PdfReader(path)
    writer=PdfWriter()
    jpeg=(ROOT/'dist/assets/chemy-watermark.jpg').read_bytes()
    digest=hashlib.sha256(jpeg).digest()
    for original in reader.pages:
        page=writer.add_page(original)
        resources=page['/Resources']
        names=set()
        for name,ref in resources.get('/XObject',{}).items():
            obj=ref.get_object()
            if obj.get('/Subtype')=='/Image' and hashlib.sha256(obj.get_data()).digest()==digest:
                names.add(name)
        content=ContentStream(page.get('/Contents'),writer)
        removed=sum(op==b'Do' and args[0] in names for args,op in content.operations)
        assert removed==1, ('Expected one known watermark draw per page',path,removed)
        content.operations=[(args,op) for args,op in content.operations if not (op==b'Do' and args[0] in names)]
        page[NameObject('/Contents')]=writer._add_object(content)
    raw=BytesIO();writer.write(raw)
    return fitz.open('pdf',raw.getvalue())
