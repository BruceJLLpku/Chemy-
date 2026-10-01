"""Reconstruct diagram-only SVG from original PDF vector paths and labels.

The original PDFs are never altered. Page decoration is not imported.
"""
from pathlib import Path
from html import escape
import base64
from pypdf import PdfReader
import pdfplumber
from paper1_manifest import Q_SOURCE, A_SOURCE

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'dist' / 'assets'
Q = Q_SOURCE
A = A_SOURCE

def inside(obj, box):
    x0, y0, x1, y1 = box
    return obj['x0'] >= x0-.3 and obj['x1'] <= x1+.3 and obj['top'] >= y0-.3 and obj['bottom'] <= y1+.3

def color(value):
    if isinstance(value,(list,tuple)) and len(value)==3:return 'rgb('+','.join(str(round(float(c)*255)) for c in value)+')'
    if isinstance(value,(int,float)):return 'rgb('+','.join([str(round(value*255))]*3)+')'
    return '#000'

def svg(page, box, name, label, original_images=None):
    x0,y0,x1,y1=box
    parts=[f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0} {y0} {x1-x0} {y1-y0}" role="img" aria-labelledby="title"><title id="title">{escape(label)}</title><g stroke-linecap="round" stroke-linejoin="round">']
    # PDF arrow shafts can be thin filled rectangles rather than stroked lines.
    # Keep all three geometric primitives so the source arrow remains complete.
    for obj in page.curves + page.lines + page.rects:
        if not inside(obj,box): continue
        path=obj.get('path')
        if path:
            d=' '.join(op[0].upper()+' '+ ' '.join(f'{v:.4f}' for pt in op[1:] for v in pt) for op in path)
        else:
            pts=obj['pts'];d='M '+' L '.join(f'{x:.4f} {y:.4f}' for x,y in pts)
        stroke=color(obj.get('stroking_color')) if obj.get('stroke') else 'none'
        fill=color(obj.get('non_stroking_color')) if obj.get('fill') else 'none'
        width=obj.get('linewidth',.5)
        parts.append(f'<path d="{d}" fill="{fill}" stroke="{stroke}" stroke-width="{width:.3f}"/>')
    # PDF chemical-label characters are positioned individually, preserving subscripts.
    for c in page.chars:
        if not inside(c,box) or not c['text'].strip():continue
        parts.append(f'<text x="{c["x0"]:.4f}" y="{c["bottom"]-c["size"]*.19:.4f}" font-size="{c["size"]:.4f}" font-family="Arial, sans-serif" fill="{color(c.get("non_stroking_color"))}">{escape(c["text"])}</text>')
    # Retain the source's original small bitmap chemical labels byte for byte.
    for im in page.images:
        if not inside(im,box) or im['name'] not in (original_images or {}):continue
        src=(original_images or {})[im['name']]
        mime='image/png' if src.name.endswith('.png') else 'image/jpeg'
        data=base64.b64encode(src.data).decode('ascii')
        parts.append(f'<image x="{im["x0"]:.4f}" y="{im["top"]:.4f}" width="{im["width"]:.4f}" height="{im["height"]:.4f}" href="data:{mime};base64,{data}"/>')
    parts.append('</g></svg>')
    (OUT/name).write_text('\n'.join(parts),encoding='utf-8')

OUT.mkdir(parents=True,exist_ok=True)
with pdfplumber.open(Q) as p:
    svg(p.pages[6],(91,575,505,698),'organic-route.svg','二环化合物合成：由起始氨基醇经 A 至 F 得到二环产物')
    svg(p.pages[7],(94,120,490,168),'organic-g.svg','反应 G：酸促进的环化反应')
    svg(p.pages[7],(96,179,490,243),'organic-h.svg','反应 H：BPA 催化的环化反应')
    svg(p.pages[7],(96,252,490,334),'organic-i.svg','反应 I：TFAA 和 TFA 促进的环化反应')
with pdfplumber.open(A) as p:
    original_images={im.name.split('.')[0]:im for im in PdfReader(A).pages[10].images if not im.name.startswith('Image1.')}
    boxes={'a':(107,106,209,164),'b':(247,106,350,164),'c':(383,106,488,164),'d':(106,186,211,260),'e':(247,186,351,260),'f':(380,186,490,260),'g':(105,277,219,351),'h':(247,277,351,351),'i':(380,277,490,351)}
    for letter,box in boxes.items():svg(p.pages[10],box,f'answer-{letter}.svg',f'化合物 {letter.upper()} 的参考结构',original_images)
print('Extracted 13 original diagrams, preserving source paths and bitmap labels.')
