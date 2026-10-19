"""Offline validation of annotation integrity and actual Gemini request assembly."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import analyze_knowledge as a


class KnowledgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bank = json.loads((a.DIST/'questions.json').read_text(encoding='utf8'))
        cls.q = next(q for q in cls.bank if q['id']=='chemy35-10-8')
        cls.record = json.loads((a.CACHE/'chemy35-10-8.json').read_text(encoding='utf8'))

    def test_source_evidence_valid(self):
        self.assertIs(a.validate_record(self.record,self.q),self.record)

    def test_invented_quote_rejected(self):
        record=copy.deepcopy(self.record)
        record['links'][0]['evidence']=[{'kind':'body','quote':'这句话并不存在于本题'}]
        with self.assertRaises(ValueError):a.validate_record(record,self.q)

    def test_other_question_image_rejected(self):
        record=copy.deepcopy(self.record)
        record['links'][0]['evidence']=[{'kind':'image','path':'assets/e35-p03-a10-02-03cc0854194a.webp'}]
        with self.assertRaises(ValueError):a.validate_record(record,self.q)

    def test_wrong_subquestion_number_rejected(self):
        record=copy.deepcopy(self.record)
        record['links'][0]['subquestions']=['99-1']
        with self.assertRaises(ValueError):a.validate_record(record,self.q)

    def test_source_changes_invalidate_hash(self):
        q={**self.q,'body':self.q['body']+'<p>修正</p>'}
        self.assertNotEqual(a.source_hash(q),a.source_hash(self.q))

    def test_publisher_excludes_stale_records(self):
        temp_root=a.ROOT/'output/ai-paper'
        temp_root.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=temp_root) as folder:
            cache=Path(folder)/'cache'
            dest=Path(folder)/'dist'
            dest.mkdir();cache.mkdir()
            (dest/'numbering.json').write_bytes((a.DIST/'numbering.json').read_bytes())
            stale={**self.record,'sourceHash':'not-the-current-source'}
            a.atomic_json(cache/(self.q['id']+'.json'),stale)
            # source_hash still uses the real immutable input images.
            with patch.object(a,'CACHE',cache),patch.object(a,'DIST',dest),patch.object(a,'source_hash',return_value=self.record['sourceHash']):
                result=a.publish([self.q])
            self.assertEqual(result['entries'],[])
            self.assertFalse(result['complete'])

    def test_request_contains_all_source_images_and_structured_output(self):
        record=self.record
        seen={}
        class Fake:
            BASE='https://generativelanguage.googleapis.com'
            @staticmethod
            def request(key,url,payload,timeout):
                seen.update({'key':key,'url':url,'payload':payload})
                return {'candidates':[{'finishReason':'STOP','content':{'parts':[{'text':json.dumps({'links':record['links']})}]}}]},{}
        result=a.analyze(self.q,Fake,'test-only-key','test-model')
        parts=seen['payload']['contents'][0]['parts']
        expected=set(a.Content(self.q['body']).images+a.Content(self.q['answer']).images)
        self.assertEqual(sum('inlineData' in p for p in parts),len(expected))
        self.assertEqual(seen['payload']['generationConfig']['responseMimeType'],'application/json')
        self.assertEqual(result['model'],'test-model')
        self.assertNotIn('test-only-key',json.dumps(result))

    def test_truncated_generation_is_not_published(self):
        class Fake:
            BASE='https://generativelanguage.googleapis.com'
            @staticmethod
            def request(*args,**kwargs):
                return {'candidates':[{'finishReason':'MAX_TOKENS','content':{'parts':[{'text':'{}'}]}}]},{}
        with self.assertRaises(ValueError):a.analyze(self.q,Fake,'test-only-key','test-model')

    def test_all_answer_indices_cover_bank_and_current_pdf_version(self):
        numbers=json.loads((a.DIST/'numbering.json').read_text(encoding='utf8'))
        ids=set()
        for path in (a.DIST/'export-index').glob('*-answers.json'):
            index=json.loads(path.read_text(encoding='utf8'))
            self.assertEqual(index['bookVersion'],numbers['pdfVersion'])
            for qid,regions in index['questions'].items():
                self.assertNotIn(qid,ids);ids.add(qid)
                self.assertTrue(regions)
                for region in regions:
                    self.assertGreaterEqual(region['page'],0)
                    self.assertTrue(all(b>a for a,b in region['bands']))
        self.assertEqual(ids,{q['id'] for q in self.bank})


if __name__=='__main__':unittest.main()
