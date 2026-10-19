"""Local Codex review packets and validated imports. No external API or key.

prepare: emits source text, image paths and contact sheets for direct AI reading.
import: validates source fingerprints, references and evidence before saving.
Only the coordinator should publish while reviewers work in parallel.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
from PIL import Image, ImageDraw
import analyze_knowledge as a


def load():
    return json.loads((a.DIST/'questions.json').read_text(encoding='utf8'))


def reviewed(q):
    path=a.CACHE/(q['id']+'.json')
    try:
        r=json.loads(path.read_text(encoding='utf8'))
        return r['sourceHash']==a.source_hash(q) and r['promptVersion']==a.PROMPT_VERSION and bool(a.validate_record(r,q))
    except (OSError,KeyError,ValueError,TypeError):
        return False


def contacts(q,folder):
    images=a.Content(q['body']).images+a.Content(q['answer']).images
    sheets=[]
    width=1400
    current=[]
    height=20
    def save():
        nonlocal current,height
        sheet=Image.new('RGB',(width+20,height),'white')
        draw=ImageDraw.Draw(sheet)
        y=10
        for src,im in current:
            draw.text((10,y),src,fill='black')
            sheet.paste(im,(10,y+24));y+=im.height+36
        path=folder/f'{q["id"]}-images-{len(sheets)+1}.png'
        sheet.save(path);sheets.append(str(path.resolve()))
        current=[];height=20
    for src in images:
        image_path=a.DIST/src
        if image_path.suffix.lower()=='.svg':
            image_path=a.ROOT/'output/knowledge-review/svg'/(image_path.name+'.png')
            if not image_path.exists():
                raise ValueError('SVG preview missing: run scripts/render_review_svgs.cjs once')
        im=Image.open(image_path).convert('RGB')
        im.thumbnail((width,1500))
        if current and height+im.height+36>4200:
            save()
        current.append((src,im.copy()));height+=im.height+36
    if current:
        save()
    return sheets


def prepare(args):
    bank=load()
    selected=[]
    for q in bank:
        if (not args.topics or q['topic'] in args.topics) and (not args.ids or q['id'] in args.ids) and not reviewed(q):
            selected.append(q)
            if len(selected)==args.limit:
                break
    folder=(a.ROOT/'output/knowledge-review'/args.group).resolve()
    if not folder.is_relative_to((a.ROOT/'output/knowledge-review').resolve()):
        raise ValueError('Group must stay inside the review workspace')
    folder.mkdir(parents=True,exist_ok=True)
    records=[]
    for q in selected:
        records.append({'id':q['id'],'number':q['number'],'topic':q['topic'],'title':q.get('title',''),
                        'sourceHash':a.source_hash(q),'bodyText':a.text(q['body']),'answerText':a.text(q['answer']),
                        'bodyImages':a.Content(q['body']).images,'answerImages':a.Content(q['answer']).images,
                        'contactSheets':contacts(q,folder)})
    packet=folder/'packet.json'
    a.atomic_json(packet,{'instructions':'Read all source text and ALL images. Return an array of {id, sourceHash, links}; each link follows analyze_knowledge.validate_record. Use original subquestion numbers, actual evidence, confidence 0..1, strength 1..3. Never fabricate answers or infer a reaction from keywords alone.',
                          'catalogue':[{'name':n,'aliases':v} for n,v in a.CATALOGUE],'questions':records})
    print(json.dumps({'packet':str(packet),'questions':[{k:r[k] for k in ('id','topic','contactSheets')} for r in records]},ensure_ascii=False),flush=True)


def import_records(args):
    bank={q['id']:q for q in load()}
    records=json.loads(args.file.read_text(encoding='utf8'))
    if not isinstance(records,list):
        raise ValueError('Review file must be an array')
    validated=[]
    for record in records:
        q=bank[record['id']]
        if record.get('sourceHash')!=a.source_hash(q):
            raise ValueError(f'{q["id"]}: input changed since packet creation')
        try:
            a.validate_record(record,q)
        except (ValueError,KeyError,TypeError) as exc:
            for link in record.get('links',[]):
                try:
                    a.validate_record({'links':[link]},q)
                except (ValueError,KeyError,TypeError) as detail:
                    raise ValueError(f'{q["id"]} / {link.get("concept", "unknown")}: {detail}') from None
            raise ValueError(f'{q["id"]}: {exc}') from None
        record.update({'promptVersion':a.PROMPT_VERSION,'model':'codex-source-review',
                       'reviewMethod':'Direct AI reading of source text and question/answer images.',
                       'analyzedAt':datetime.now(timezone.utc).isoformat()})
        validated.append(record)
    for record in validated:
        path=a.CACHE/(record['id']+'.json')
        if path.exists() and not args.replace:
            raise ValueError(f'{record["id"]}: already saved; --replace is required to overwrite')
        a.atomic_json(path,record)
    print(json.dumps({'saved':[r['id'] for r in validated]},ensure_ascii=False),flush=True)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    commands=parser.add_subparsers(dest='command',required=True)
    p=commands.add_parser('prepare')
    p.add_argument('--topics',nargs='+');p.add_argument('--ids',nargs='+')
    p.add_argument('--group',required=True);p.add_argument('--limit',type=int,default=5)
    i=commands.add_parser('import')
    i.add_argument('file',type=Path);i.add_argument('--replace',action='store_true')
    commands.add_parser('publish');commands.add_parser('status')
    args=parser.parse_args()
    if args.command=='prepare':
        if not 1<=args.limit<=30:parser.error('batch limit must be 1..30')
        prepare(args)
    elif args.command=='import':import_records(args)
    elif args.command=='publish':a.publish(load())
    else:
        bank=load()
        counts={}
        for q in bank:
            counts.setdefault(q['topic'],{'reviewed':0,'total':0})['total']+=1
            counts[q['topic']]['reviewed']+=int(reviewed(q))
        print(json.dumps(counts,ensure_ascii=False),flush=True)


if __name__=='__main__':
    try:main()
    except (ValueError,KeyError,TypeError) as exc:
        print(str(exc),file=sys.stderr);sys.exit(1)
