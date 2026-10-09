"""Record final review only when source, numbering and PDF audits agree."""
import hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(name):return json.loads((ROOT/name).read_text(encoding='utf8'))
def save(name,data):(ROOT/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf8')
if __name__=='__main__':
    bank=read('dist/questions.json');source=read('data/audit_report.json')
    numbering=read('data/numbering-audit.json');structure=read('data/print_structure_check.json');chapters=read('data/print-chapter-audit.json')
    assert len(bank)==1933 and source['automatedPassed'] and not source['issues'] and not source['reviewCandidates']
    assert source['checks']['source_questions']==len(bank) and source['methods']['losslessSourcePixelComparison']
    assert numbering.get('passed') and structure['passed'] and chapters['passed']
    assert len(chapters['books'])==18
    for name,item in chapters['books'].items():
        digest=hashlib.sha256((ROOT/'dist/downloads'/name).read_bytes()).hexdigest()
        assert digest==item['sha256']==structure['books'][name]['sha256'],name
    review={'complete':True,'questions':len(bank),'collections':196,'topicBooks':18,'printPages':structure['pages'],
        'method':'Automatic source pairing, native glyph coverage, original crop pixel comparison and full print drawing resource comparison; visual inspection of flagged source boundaries, all topic booklet samples, edition transitions and official errata samples. Not a manual rereading of every printed page.',
        'visuallyInspectedBoundaryPages':22,'questionWholeDiagramFixes':20,'answerWholeDiagramFixes':1,
        'bookletFirstPagesInspected':18,'additionalSamplePagesRendered':58,'officialErrataSourcePagesInspected':6,'chemicalRedrawing':False,
        'resolved':['Cross-question floating original diagrams','Footer-cut original answer diagram','Greek-letter expressions mistaken for subquestion numbers','Three-digit number spacing','Small-font answer subquestion labels','Chemical diagram glyphs mistaken for a question title','Original practice 5-4 label referring to its own fourth subquestion','Trailing general abbreviation tables'],
        'official32Corrections':sorted(read('data/answer_corrections32.json')['corrections'])}
    source['visualReviewComplete']=True;source['finalReview']=review;source['methods']['printChapterContentComparison']=True;source['methods']['nativeDrawingResourcesCompared']=True
    source['checks']['topic_pdfs']=18;source['checks']['print_pages']=structure['pages'];save('data/audit_report.json',source)
    structure['fullContentReviewComplete']=True;structure['reviewMethod']=review['method'];save('data/print_structure_check.json',structure)
    manifest=read('data/library_manifest.json')
    for paper in manifest['papers'].values():paper['reviewed']=True
    manifest['finalReview']=review;save('data/library_manifest.json',manifest)
    save('data/final_review.json',review)
    with (ROOT/'WORK_STATE.md').open('a',encoding='utf8') as file:
        file.write('\n最终本地复核完成：1933题、196份卷子，原始题答来源和字形全量自动对照、原图逐像素对照、18册4110页原生绘图资源与章节对照均通过。目视检查边界异常、各专题册首、跨届与官方补正样页；修复20处题图边界、1处答案页底完整图、题号及标题问题。未宣称逐页人工重读全部内容。第32届10题官方补正均保留正确来源。下一步仅最终发布与18个公开PDF下载字节核对，完成后关闭续做定时。\n')
    print('FINAL LOCAL REVIEW',len(bank),'questions',structure['pages'],'print pages',flush=True)
