"""Apply visually reviewed whole-image ownership at original question boundaries."""
import json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
# Original PDF coordinates; no chemical diagram is redrawn.
FIXES=[
 (38,6,6,40,[190,596,422,727],'band'),
 (38,16,6,115,[419,71,519,272],'float'),
 (38,18,4,126,[370,69,498,141],'float'),
 (37,6,10,37,[400,70,509,327],'float'),
 (37,10,7,61,[448,78,490,134],'float'),
 (37,13,5,78,[390,349,508,493],'float'),
 (37,18,2,102,[447,77,505,133],'float'),
 (34,1,6,6,[384,538,509,663],'float'),
 (34,4,4,19,[386,71,508,188],'float'),
 (34,7,7,34,[363,70,509,211],'float'),
 (34,7,8,34,[397,320,509,426],'float'),
 (34,15,2,72,[450,390,506,447],'float'),
 (33,8,5,33,[359,268,509,379],'float'),
 (33,11,6,47,[402,414,506,494],'float'),
 (33,12,9,52,[418,72,507,279],'float'),
 (32,1,4,3,[349,135,509,299],'float'),
 (32,3,6,11,[409,276,509,374],'float'),
 (0,13,7,59,[373,70,509,268],'float'),
 (0,15,8,69,[397,239,509,334],'float'),
 (0,19,12,90,[397,377,509,498],'float'),
]
if __name__=='__main__':
    path=ROOT/'data/source_exceptions.json';data=json.loads(path.read_text(encoding='utf8'))
    for e,p,q,n,box,mode in FIXES:
        key=(e,p,q,'q',n)
        data['captures']=[f for f in data['captures'] if (f['edition'],f['paper'],f['number'],f['kind'],f['page'])!=key]
        data['captures'].append(dict(edition=e,paper=p,number=q,kind='q',page=n,box=box,mode=mode))
    data['omittedGeneralNotes']=[dict(edition=38,paper=17,number=6,kind='q',page=121,reason='Generic organic abbreviations table, not question content'),dict(edition=38,paper=11,number=7,kind='q',page=80,afterTop=403.8,reason='Generic organic abbreviations, not crystal question content')]
    data['finalBoundaryReview']={'originalCandidates':33,'sourcePagesInspected':20,'wholeDiagramFixes':len(FIXES),'chemicalRedrawing':False}
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
    papers=sorted({(e,p) for e,p,_,_,_,_ in FIXES}|{(38,17)},key=lambda ep:(-ep[0],ep[1]))
    for e,p in papers:
        env=os.environ.copy();env['CHEMY_EDITION']=str(e)
        subprocess.run([sys.executable,'-X','utf8',str(ROOT/'scripts/import_library.py'),str(p)],cwd=ROOT,env=env,check=True)
    print('FINAL BOUNDARIES',len(papers),'papers refreshed',flush=True)
