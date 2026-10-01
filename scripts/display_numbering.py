"""One stable topic ordinal shared by the website and printed books."""
import hashlib,json,os,re
from collections import Counter
from library_config import ROOT

def numbering(bank):
    counts=Counter();numbers={}
    for question in bank:
        counts[question['topic']]+=1;numbers[question['id']]=counts[question['topic']]
    version=hashlib.sha256(json.dumps(numbers,sort_keys=True).encode()).hexdigest()[:12]
    return {'scope':'per-topic','version':'topic-numbering-v1-'+version,'numberById':numbers,'countsByTopic':dict(counts)}

def write_numbering(bank=None):
    if bank is None:bank=json.loads((ROOT/'dist/questions.json').read_text(encoding='utf8'))
    data=numbering(bank)
    path=ROOT/'dist/numbering.json';temporary=path.with_suffix(f'.{os.getpid()}.tmp')
    temporary.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8');os.replace(temporary,path)
    return data

def renumber_attributes(html,old,new):
    def attribute(m):
        value=m.group(2)
        # Edition/paper/question strings are explicit source attribution.
        if re.search(r'第\s*\d+\s*届',value):return m.group()
        value=re.sub(r'(?<![\dA-Za-z,，])'+str(old)+r'(?=-\d)',str(new),value)
        return m.group(1)+'="'+value+'"'
    return re.sub(r'(alt|aria-label)="([^"]*)"',attribute,html)

if __name__=='__main__':
    result=write_numbering();print('Numbered',len(result['numberById']),'questions across',len(result['countsByTopic']),'topics')
