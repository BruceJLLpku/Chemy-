"""One edition namespace per import process; source PDFs are never modified."""
import json,os
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
EDITION=int(os.environ.get('CHEMY_EDITION','39'))
config=json.loads((ROOT/'data/editions.json').read_text(encoding='utf8'))[str(EDITION)]
Q_SOURCE=ROOT/'sources'/config['q'];A_SOURCE=ROOT/'sources'/config['a']
CACHE=ROOT/'tmp'/('library' if EDITION==39 else f'library{EDITION}')
def paper_key(paper):return str(paper) if EDITION==39 else f'{EDITION}-{paper}'
def edition_of(q):return q.get('edition',39)
