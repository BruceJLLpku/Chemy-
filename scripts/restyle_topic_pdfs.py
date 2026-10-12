"""Update generated type only; keep every compact book placement unchanged."""
import argparse,hashlib,json,shutil
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor
from io import BytesIO
from pathlib import Path
from fast_pdf import pikepdf,share_streams
from pdf_typography import frame,style_form,STYLE
from build_continuous_books import ROOT,DATA,sync_pdf_version

BACKUP=ROOT/'tmp/typography/source'

def build(path):
    name=path.name;slug,kind=path.stem.rsplit('-',1)
    bank=json.loads((ROOT/'dist/questions.json').read_text(encoding='utf8'));questions={q['id']:q for q in bank}
    numbers=json.loads((ROOT/'dist/numbering.json').read_text(encoding='utf8'))['numberById']
    layout_path=DATA/path.with_suffix('.json').name
    layout=json.loads(layout_path.read_text(encoding='utf8'))
    BACKUP.mkdir(parents=True,exist_ok=True)
    backup=BACKUP/name
    if not backup.exists():shutil.copyfile(path,backup)
    old_layout=BACKUP/layout_path.name
    if not old_layout.exists():shutil.copyfile(layout_path,old_layout)
    baseline=json.loads(old_layout.read_text(encoding='utf8'))
    assert all(layout[key]==baseline[key] for key in ['records','placements','questions','pages']), 'Source backup belongs to a different book layout'
    owners=defaultdict(list)
    for placement in layout['placements']:
        if placement['first']:owners[placement['sourcePage']].append(placement['id'])
    topic=questions[layout['records'][0]['id']]['topic'];changed=set()
    with pikepdf.open(backup) as pdf:
        for index,page in enumerate(pdf.pages):
            objects=page.obj['/Resources']['/XObject']
            for key,form in list(objects.items()):
                if not str(key).startswith('/Source'):continue
                source=int(str(key).removeprefix('/Source'))
                if source in changed:continue
                if style_form(pdf,form,owners[source],questions,numbers,pikepdf):changed.add(source)
            with pikepdf.open(BytesIO(frame(topic,kind,len(layout['records']),index+1,len(pdf.pages)))) as header:
                new=pdf.copy_foreign(header.pages[0].as_form_xobject())
                objects['/ChemyPageFrame']=new
            contents=list(page.obj['/Contents'])
            contents[0]=pdf.make_stream(b'q /ChemyPageFrame Do Q\n')
            contents[0]['/ChemyTypography']=STYLE
            page.obj['/Contents']=pikepdf.Array(contents)
        pdf.docinfo['/ChemyTypography']=STYLE
        share_streams(pdf)
        target=path.with_suffix('.typeset.pdf')
        pdf.save(target,compress_streams=True,object_stream_mode=pikepdf.ObjectStreamMode.generate,deterministic_id=True)
    target.replace(path)
    layout['typography']=STYLE;layout['sha256']=hashlib.sha256(path.read_bytes()).hexdigest()
    layout_path.write_text(json.dumps(layout,ensure_ascii=False,separators=(',',':')),encoding='utf8')
    print('TYPESET',name,len(layout['records']),'headings',layout['pages'],'pages',flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--topics',nargs='+');args=parser.parse_args()
    paths=[p for p in sorted((ROOT/'dist/downloads').glob('*.pdf')) if not args.topics or p.stem.rsplit('-',1)[0] in args.topics]
    with ProcessPoolExecutor(max_workers=3) as pool:list(pool.map(build,paths))
    sync_pdf_version()
