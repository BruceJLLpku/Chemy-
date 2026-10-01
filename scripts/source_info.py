"""Human source names for annual mocks, special collections and league papers."""
import json
from functools import lru_cache
from pathlib import Path

@lru_cache(maxsize=1)
def editions():
    return json.loads((Path(__file__).resolve().parents[1]/'data/editions.json').read_text(encoding='utf8'))

def paper_name(edition,paper):
    return editions()[str(edition)].get('paperLabels',{}).get(str(paper),f'模拟试题{paper}')

def source_name(edition,paper,compact=False):
    if edition==0:return f'第{paper}届 Chemy联赛'
    return f'第{edition}届'+('' if compact else ' · ')+paper_name(edition,paper)

def question_source(q):
    result=f'来源：{source_name(q.get("edition",39),q["paper"])} · 原第{q["number"]}题'
    if q.get('answerCorrectionPages'):result+=' · 官方答案补正第'+q['answerCorrectionPages']+'页'
    return result

def score_text(q):
    if q.get('points') is None:return ''
    percent='' if q.get('percent') is None else f'，占 {q["percent"]}%'
    return f'（{q["points"]} 分{percent}）'

def set_source_color(canvas,color):
    if isinstance(color,(list,tuple)):
        if len(color)==1:canvas.setFillGray(color[0])
        elif len(color)==3:canvas.setFillColorRGB(*color)
        elif len(color)==4:canvas.setFillColorCMYK(*color)
        else:raise ValueError(f'Unsupported source color components: {len(color)}')
    else:canvas.setFillGray(color or 0)
