"""Independent edition workers; merge only after every display and print part is ready."""
import argparse,json,subprocess,sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from display_numbering import renumber_attributes
ROOT=Path(__file__).resolve().parents[1]

def edition(e):
    for script in ['renumber_library.py','build_numbered_pdfs.py']:
        subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts'/script),'--edition',str(e)],cwd=ROOT,check=True)

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--presentation-only',action='store_true');args=ap.parse_args()
    if not args.presentation_only:
        with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(edition,[39,36,35]))
    display={}
    for e in [39,36,35]:
        cache=ROOT/'tmp'/('library' if e==39 else f'library{e}')/'numbered/presentation.json'
        display.update(json.loads(cache.read_text(encoding='utf8')))
    bank=json.loads((ROOT/'dist/questions.json').read_text(encoding='utf8'));assert set(display)=={q['id'] for q in bank}
    numbers=json.loads((ROOT/'dist/numbering.json').read_text(encoding='utf8'))['numberById']
    for q in bank:
        for field in ['body','answer']:display[q['id']][field]=renumber_attributes(display[q['id']][field],q['number'],numbers[q['id']])
    (ROOT/'dist/presentation.json').write_text(json.dumps(display,ensure_ascii=False,separators=(',',':')),encoding='utf8')
    print('WEBSITE',len(display),'presentation entries ready',flush=True)
    if not args.presentation_only:subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/build_numbered_pdfs.py'),'--merge-only'],cwd=ROOT,check=True)
