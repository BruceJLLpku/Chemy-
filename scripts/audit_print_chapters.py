"""Verify every merged page against its native chapter, including drawing resources."""
import hashlib,json
from functools import lru_cache
from pypdf import PdfReader
from paper1_manifest import ROOT,SLUGS
from audit_library import part
def digest(raw):return hashlib.sha256(raw).hexdigest()
def resource_fingerprinter():
    cache={}
    def fingerprint(resources,ancestors=()):
        if resources is None:return ()
        resources=resources.get_object();key=id(resources)
        if key in ancestors:return ('cycle',)
        if key in cache:return cache[key]
        result=[]
        for name,obj in sorted(resources.get('/XObject',{}).get_object().items() if '/XObject' in resources else []):
            obj=obj.get_object();nested=fingerprint(obj.get('/Resources'),ancestors+(key,))
            masks=tuple((k,digest(obj[k].get_object().get_data())) for k in ['/SMask','/Mask'] if k in obj and hasattr(obj[k].get_object(),'get_data'))
            result.append((name,str(obj.get('/Subtype')),digest(obj.get_data()),nested,masks))
        cache[key]=tuple(result);return cache[key]
    return fingerprint
if __name__=='__main__':
    bank=json.loads((ROOT/'dist/questions.json').read_text(encoding='utf8'));report={'passed':False,'books':{},'issues':[],'nativeDrawingResourcesCompared':True}
    for topic,slug in SLUGS.items():
        chapters=sorted({(q.get('edition',39),q['paper']) for q in bank if q['topic']==topic},key=lambda ep:(-ep[0],ep[1]))
        for k,kind in [('q','questions'),('a','answers')]:
            target=ROOT/'dist/downloads'/f'{slug}-{kind}.pdf';book=PdfReader(target);bf=resource_fingerprinter();offset=0
            for e,p in chapters:
                reader=PdfReader(part(e,p,slug,k));cf=resource_fingerprinter()
                for page in reader.pages:
                    merged=book.pages[offset]
                    assert page.mediabox==merged.mediabox and digest(page.get_contents().get_data())==digest(merged.get_contents().get_data()),(target.name,offset+1,'page content')
                    assert cf(page.get('/Resources'))==bf(merged.get('/Resources')),(target.name,offset+1,'native drawing resource')
                    offset+=1
            assert offset==len(book.pages)
            report['books'][target.name]={'pages':offset,'sha256':digest(target.read_bytes())}
            print('PRINT CHAPTER AUDIT',target.name,offset,flush=True)
    report['passed']=True;(ROOT/'data/print-chapter-audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
