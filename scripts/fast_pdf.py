"""Lossless native PDF copying/stamping; original chemistry stays vector data."""
import sys,hashlib
from io import BytesIO
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if (ROOT/'tmp/pdf-engine').exists():sys.path.insert(0,str(ROOT/'tmp/pdf-engine'))
import pikepdf

def page_count(path):
    with pikepdf.open(path) as pdf:return len(pdf.pages)

def clip_stamp(source,holes,overlay,dest):
    """Keep source operators intact and mask only the replaced label glyphs."""
    with pikepdf.open(source) as pdf,pikepdf.open(BytesIO(overlay)) as extra:
        page=pdf.pages[0];w=float(page.mediabox[2]);h=float(page.mediabox[3])
        contents=page.obj['/Contents']
        raw=b'\n'.join(stream.read_bytes() for stream in contents) if isinstance(contents,pikepdf.Array) else contents.read_bytes()
        page.obj['/Contents']=pdf.make_stream(('q\n'+f'0 0 {w} {h} re\n'+''.join(holes)+'W* n\n').encode()+raw+b'\nQ\n')
        page.add_overlay(extra.pages[0])
        pdf.save(dest,compress_streams=True,object_stream_mode=pikepdf.ObjectStreamMode.generate,deterministic_id=True)

def share_streams(pdf):
    """Share only byte-identical streams whose complete rendering dictionaries agree."""
    memo={};visiting=set()
    def signature(value):
        ident=getattr(value,'objgen',(0,0))
        if ident!=(0,0):
            if ident in memo:return memo[ident]
            if ident in visiting:return ('cycle:'+str(ident)).encode()
            visiting.add(ident)
        if isinstance(value,pikepdf.Stream):
            bits=[b'stream',hashlib.sha256(value.read_raw_bytes()).digest()]
            for key,item in sorted(value.items(),key=lambda p:str(p[0])):
                if str(key)!='/Length':bits.extend([str(key).encode(),signature(item)])
        elif isinstance(value,pikepdf.Dictionary):
            bits=[b'dict']
            for key,item in sorted(value.items(),key=lambda p:str(p[0])):bits.extend([str(key).encode(),signature(item)])
        elif isinstance(value,pikepdf.Array):bits=[b'array']+[signature(item) for item in value]
        elif isinstance(value,pikepdf.String):bits=[b'string',bytes(value)]
        else:bits=[type(value).__name__.encode(),str(value).encode()]
        digest=hashlib.sha256(b'\0'.join(bits)).digest()
        if ident!=(0,0):visiting.remove(ident);memo[ident]=digest
        return digest
    unique={};aliases={};objects=list(pdf.objects)
    for obj in objects:
        if not isinstance(obj,pikepdf.Stream):continue
        key=signature(obj)
        if key in unique:aliases[obj.objgen]=unique[key]
        else:unique[key]=obj
    def replace(value):
        if isinstance(value,(pikepdf.Dictionary,pikepdf.Stream)):
            for key,item in list(value.items()):
                ident=getattr(item,'objgen',(0,0))
                if ident in aliases:value[key]=aliases[ident]
                elif ident==(0,0) and isinstance(item,(pikepdf.Dictionary,pikepdf.Array)):replace(item)
        elif isinstance(value,pikepdf.Array):
            for i,item in enumerate(value):
                ident=getattr(item,'objgen',(0,0))
                if ident in aliases:value[i]=aliases[ident]
                elif ident==(0,0) and isinstance(item,(pikepdf.Dictionary,pikepdf.Array)):replace(item)
    for obj in objects:replace(obj)

def stamp_template(template,overlay,dest):
    with pikepdf.open(template) as pdf,pikepdf.open(BytesIO(overlay)) as numbers:
        assert len(pdf.pages)==len(numbers.pages)
        for page,extra in zip(pdf.pages,numbers.pages):page.add_overlay(extra)
        # The source template already shares its resources. Deduplicate once when merging the final booklet.
        pdf.save(dest,compress_streams=True,object_stream_mode=pikepdf.ObjectStreamMode.generate,deterministic_id=True)

def merge_parts(paths,records,dest,metadata):
    pdf=pikepdf.Pdf.new()
    for path in paths:
        with pikepdf.open(path) as part:pdf.pages.extend(part.pages)
    share_streams(pdf)
    for key,value in metadata.items():pdf.docinfo[key]=value
    with pdf.open_outline() as outline:
        for entry in records:
            from source_info import source_name
            title=f'第{entry["number"]}题 · {source_name(entry["sourceEdition"],entry["sourcePaper"],compact=True)}原第{entry["sourceNumber"]}题'
            outline.root.append(pikepdf.OutlineItem(title,entry['firstPage']-1))
    count=len(pdf.pages);pdf.save(dest,compress_streams=True,object_stream_mode=pikepdf.ObjectStreamMode.generate,deterministic_id=True);pdf.close();return count
