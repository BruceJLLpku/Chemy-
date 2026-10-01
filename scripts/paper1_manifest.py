"""Reviewed boundaries in ORIGINAL PDF page coordinates (points from top).

Keep a complete major question under one primary topic. Coordinates are data,
not model-generated diagrams. Body ranges omit the title already shown by UI;
print ranges retain it. Answer ranges omit the repeated question statements.
"""
from pathlib import Path
import os

ROOT = Path(__file__).resolve().parents[1]
SOURCE_DIR = Path(os.environ.get('CHEMY_SOURCE_DIR', ROOT / 'sources'))
if not SOURCE_DIR.exists():
    SOURCE_DIR = Path('C:/Users/Prettibruce/Downloads')
Q_SOURCE = SOURCE_DIR / '第39届Chemy化学奥林匹克竞赛模拟试题题目合集.pdf'
A_SOURCE = SOURCE_DIR / '第39届Chemy化学奥林匹克竞赛模拟试题参考答案合集.pdf'
SLUGS = {'有机化学':'organic','高分子化学':'polymer','晶体化学':'crystal',
         '结构推断':'inference','元素化学':'elements','热力学与化学平衡':'equilibrium',
         '电化学':'electrochemistry','动力学':'kinetics','分析化学':'analysis'}

PAPER = [
 dict(number=1, title='元素化学', topic='元素化学', points=22, percent=12,
      question=[(4,319,600)], printQuestion=[(4,302,600)],
      answer=[(3,523,597),(3,696,714),(4,73,164),(4,216,259),(4,373,466)]),
 dict(number=2, title='氟代试剂', topic='元素化学', points=7, percent=4,
      question=[(4,631,708)], printQuestion=[(4,614,708)],
      answer=[(4,561,604),(4,625,734)]),
 dict(number=3, title='有趣的锗和锡化合物', topic='结构推断', points=16, percent=8,
      question=[(5,90,387)], printQuestion=[(5,73,387)],
      answer=[(5,382,733)]),
 dict(number=4, title='钼配合物及其转化', topic='元素化学', points=28, percent=13,
      question=[(5,417,714)], printQuestion=[(5,401,714)],
      answer=[(6,309,367),(6,388,462),(6,482,573),(6,592,678),(6,703,717),(6,735,765)]),
 dict(number=5, title='未知配合物的测定', topic='分析化学', points=12, percent=6,
      question=[(6,90,293)], printQuestion=[(6,73,293)],
      answer=[(7,277,445),(7,466,530)]),
 dict(number=6, title='磷酸铁锂的 E–pH 图与回收', topic='电化学', points=23, percent=11,
      question=[(6,324,697),(7,73,233)], printQuestion=[(6,307,697),(7,73,233)],
      answer=[(8,262,338),(8,356,384),(8,467,558),(9,73,248)], approved=True),
 dict(number=7, title='有趣的复合氧化物', topic='晶体化学', points=30, percent=13,
      question=[(7,264,531)], printQuestion=[(7,247,531)],
      answer=[(9,466,746),(10,153,212)]),
 dict(number=8, title='二环化合物合成', topic='有机化学', points=21, percent=9,
      question=[(7,560,731),(8,73,337)], printQuestion=[(7,543,731),(8,73,337)],
      answer=[(11,73,367)], approved=True),
 dict(number=9, title='吡啶与苯环', topic='有机化学', points=23, percent=10,
      question=[(8,371,730),(9,73,417)], printQuestion=[(8,354,730),(9,73,417)],
      answer=[(12,86,508),(13,73,260),(13,512,754)]),
 dict(number=10, title='神奇的环丙烯', topic='有机化学', points=31, percent=14,
      question=[(9,449,769),(10,73,433)], printQuestion=[(9,432,769),(10,73,433)],
      answer=[(14,230,399),(15,73,369),(16,73,332)]),
]

# Captures preserve the actual rendered PDF, including thin arrows, masking,
# stereochemical bonds, original raster labels, and source table rules.
# (kind, original page, x0, top, x1, bottom, filename, accessible description)
FIGURES = [
 ('q',5,94,279,501,381,'q3-ligands','配体 L1、L2、TMC 与 Mg(I) 还原剂的原卷结构'),
 ('q',8,181,390,405,486,'q9-route1','9-1：吡啶转化为 A 的原卷反应路线'),
 ('q',8,89,617,507,707,'q9-route2','9-2：吡啶经 D 转化为 E 的原卷反应路线'),
 ('q',9,249,91,344,162,'q9-f','目标化合物 F 的原卷结构'),
 ('q',9,176,183,410,265,'q9-precursors','化合物 1 和 2 的原卷结构'),
 ('q',9,89,291,506,379,'q9-route3','9-3：生成 G、H 和最终吡啶的原卷反应路线'),
 ('q',9,89,511,505,567,'q10-route1','10-1：环丙烯酮经 A 转化的原卷反应路线'),
 ('q',9,184,604,411,646,'q10-carbene','10-2：酰基卡宾经 B 互变异构的原卷图'),
 ('q',9,150,681,445,769,'q10-lactone','铑催化生成五元环内酯的原卷反应路线'),
 ('q',10,101,198,487,283,'q10-route-d','10-3：环丙烯开环得到 D 的原卷反应路线'),
 ('q',10,135,322,458,382,'q10-route-e','苯基取代底物经 D′ 转化为 E 的原卷反应路线'),
 ('a',4,99,76,405,134,'a1-chain','黑色沉淀中一维无限长链阴离子的原参考答案'),
 ('a',4,219,638,331,707,'a2-anion','X 的阴离子三角双锥结构的原参考答案'),
 ('a',5,89,382,506,732,'a3-rubric','A–H 的完整原参考结构和逐项评分细则'),
 ('a',6,194,399,458,447,'a4-isomers','D 的顺反异构体原参考结构'),
 ('a',9,94,684,504,713,'a7-cs-height','Cs-O 高度计算中原卷的根号和分式'),
 ('a',12,89,86,507,191,'a9-1a','9-1-1：A 的原参考结构及评分'),
 ('a',12,89,198,506,396,'a9-1b','9-1-2：全部关键中间体与原评分说明'),
 ('a',12,94,420,319,506,'a9-1c','9-1-3：C 的原参考结构及立体化学评分说明'),
 ('a',13,94,107,352,194,'a9-2de','9-2-1：D 和 E 的原参考结构'),
 ('a',13,93,214,344,260,'a9-2reagent','9-2-2：所需试剂及原评分说明'),
 ('a',13,94,539,409,616,'a9-3gh','9-3-1：G 和 H 的原参考结构及评分'),
 ('a',13,129,650,464,754,'a9-3intermediates','9-3-2：关键中间体与原评分说明'),
 ('a',14,94,246,461,399,'a10-1','10-1：A 和三个关键中间体的原参考结构及评分'),
 ('a',15,94,99,458,242,'a10-2ab','10-2-1、10-2-2：B、中间体和过渡态原参考结构'),
 ('a',15,94,292,333,368,'a10-2c','10-2-4：C 的原参考结构与立体化学评分说明'),
 ('a',16,94,103,465,212,'a10-3e','10-3-1：E 及关键中间体原参考结构和评分'),
 ('a',16,94,227,408,332,'a10-3f','10-3-2：F 的原参考结构及评分说明'),
]
