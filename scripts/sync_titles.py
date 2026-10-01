"""Restore source heading subscripts/spaces without reimporting bodies or images."""
import json
from import_library import ROOT,INDEX,heading_title
from library_config import EDITION,edition_of

if __name__=='__main__':
    path=ROOT/'dist/questions.json';bank=json.loads(path.read_text(encoding='utf8'))
    headings={(h['paper'],h['number']):h for h in INDEX['q']['questions']};count=0
    for q in bank:
        if edition_of(q)!=EDITION or EDITION==39 and q['paper']==1:continue
        title,html=heading_title(headings[(q['paper'],q['number'])])
        if (q.get('title'),q.get('titleHtml'))!=(title,html):
            q.update(title=title,titleHtml=html);count+=1
    path.write_text(json.dumps(bank,ensure_ascii=False,indent=2),encoding='utf8')
    print('Source titles synchronized',EDITION,count,flush=True)
