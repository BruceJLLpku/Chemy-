"""Keep static source graphics in a PDF Form so changing labels never reparses them."""
import os,copy
from pypdf import PdfReader,PdfWriter
from pypdf.generic import NameObject,NumberObject,DictionaryObject,DecodedStreamObject,ArrayObject

def wrap_template(path,fingerprint):
    stamp=path.with_suffix('.form.sha256')
    if stamp.exists() and stamp.read_text()=='form-v1-'+fingerprint:return
    reader=PdfReader(path);writer=PdfWriter();writer.append(reader)
    for page in writer.pages:
        form=DecodedStreamObject();form.set_data(page.get_contents().get_data())
        form.update({NameObject('/Type'):NameObject('/XObject'),NameObject('/Subtype'):NameObject('/Form'),NameObject('/FormType'):NumberObject(1),NameObject('/BBox'):ArrayObject(page.mediabox),NameObject('/Resources'):page['/Resources']})
        if '/Group' in page:form[NameObject('/Group')]=page['/Group']
        ref=writer._add_object(form)
        page[NameObject('/Resources')]=DictionaryObject({NameObject('/XObject'):DictionaryObject({NameObject('/Static'):ref})})
        stream=DecodedStreamObject();stream.set_data(b'q /Static Do Q\n');page[NameObject('/Contents')]=stream
    writer.compress_identical_objects(remove_duplicates=True,remove_unreferenced=True)
    temporary=path.with_suffix('.form-writing.pdf');writer.write(temporary);os.replace(temporary,path);stamp.write_text('form-v1-'+fingerprint)
