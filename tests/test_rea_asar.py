"""ASAR acquisition, task focus and real pinned parser delivery."""
import json
import os
from pathlib import Path
import struct
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tests'),str(ROOT/'runtime/node-host'),str(ROOT/'adapters/computer-use')]
import test_skills
from rea_fixtures import pack, raw_archive
from jarvis_core import rea
from jarvis_core import rea_asar, rea_focus
from jarvis_core.policy import CoreError


class AsarTests(test_skills.TaskTests):
    def setUp(self):
        super().setUp()
        self.archive=pack(self.root/'pack-source',self.source/'app.asar')
        self.args={'project_id':self.project['id'],'target_path':'app.asar','prompt':'分析 ASAR 中的 fixture:op1'}

    def wait(self, item):
        # Align the integration observer with the product's existing task deadline.
        from jarvis_core.skill_tasks import TIMEOUT_SECONDS
        return super().wait(item, timeout_seconds=TIMEOUT_SECONDS + 10)

    def test_packed_delivery_and_focus(self):
        item=self.submit(skill_id='rea.software-analysis',paths=[],**{k:v for k,v in self.args.items() if k!='project_id'})
        detail=self.wait(item);self.assertEqual(detail['action_status'],'CONFIRMED',detail.get('error'))
        report=detail['report'];manifest=report['input_manifest']
        self.assertEqual(manifest['format'],'asar')
        self.assertEqual(manifest['parser_input_format'],'directory')
        self.assertEqual(len(manifest['files']),3)
        self.assertTrue(all(r['origin']['declared_hash_checked'] for r in manifest['files']))
        self.assertTrue(any(r['path']=='secrets.json' for r in manifest['omitted']))
        focus=report['analysis']['focus'];self.assertEqual(focus['query'],'fixture:op1')
        self.assertTrue(focus['matched']);self.assertGreater(focus['link_count'],0)
        self.assertNotIn('fixture-secret-never-parsed',json.dumps(self.bridge.skill_evidence(self.cid,item['task_id'])))
        self.assertIn('## 本次关注：fixture:op1',report['text'])
        page=self.bridge.skill_evidence(self.cid,item['task_id'],section='links',query='fixture:op1')
        self.assertEqual(page['total'],focus['link_count'])
        self.assertFalse(any('fixture:op2' in json.dumps(r) for r in page['items']))
        self.assertEqual(report['checks']['model_calls'],0)
        self.assertFalse(self.model.calls)

    def test_unpacked_member_delivery_and_missing_companion(self):
        pack(self.root/'unpack-source',self.source/'external.asar',unpack='preload.js')
        item=self.submit(skill_id='rea.software-analysis',paths=[],target_path='external.asar',focus='fixture:op2')
        detail=self.wait(item);self.assertEqual(detail['action_status'],'CONFIRMED',detail.get('error'))
        row=next(r for r in detail['report']['input_manifest']['files'] if r['path']=='preload.js')
        self.assertTrue(row['origin']['unpacked']);self.assertIsNone(row['origin']['byte_offset'])
        self.assertEqual(detail['report']['analysis']['summary']['ipc']['paired_renderer_transmissions'],3)
        (self.source/'external.asar.unpacked/preload.js').unlink()
        with self.assertRaises(CoreError): rea.snapshot(self.core,{**self.args,'target_path':'external.asar'},lambda:None)

    def test_invalid_headers_ranges_links_and_names(self):
        for header in [
            {'files':{'../escape.js':{'size':0,'offset':'0'}}},
            {'files':{'main.js':{'size':5,'offset':'99999'}}},
            {'files':{'main.js':{'link':'outside'}}},
            {'files':{'Main.js':{'size':0,'offset':'0'},'main.js':{'size':0,'offset':'0'}}},
            {'files':{'CON.js':{'size':0,'offset':'0'}}},
            {'files':{'main.js':{'size':True,'offset':'0'}}},
        ]:
            raw_archive(self.archive,header)
            with self.assertRaises(CoreError): rea.snapshot(self.core,self.args,lambda:None)
        self.archive.write_bytes(struct.pack('<4I',4,rea_asar.MAX_HEADER+1,4,0))
        with self.assertRaises(CoreError): rea.snapshot(self.core,self.args,lambda:None)

    def test_corruption_budget_and_hardlinks(self):
        raw_archive(self.archive,{'files':{'main.js':{'size':1,'offset':'0','integrity':{'algorithm':'SHA256','hash':'0'*64}}}},b'x')
        with self.assertRaises(CoreError): rea.snapshot(self.core,self.args,lambda:None)
        pack(self.root/'pack-source',self.archive)
        with patch.object(rea_asar,'MAX_ARCHIVE',16):
            with self.assertRaises(CoreError): rea.snapshot(self.core,self.args,lambda:None)
        os.link(self.archive,self.source/'hard.asar')
        with self.assertRaises(CoreError): rea.snapshot(self.core,self.args,lambda:None)

    def test_unpacked_changes_cancel_and_recheck(self):
        pack(self.root/'unpack-source',self.source/'external.asar',unpack='preload.js')
        companion=self.source/'external.asar.unpacked/preload.js'
        original=rea.snapshot;calls=[]
        def changing(*a,**kw):
            value=original(*a,**kw);calls.append(True)
            if len(calls)==2: companion.write_text('exports.changed=1;',encoding='utf-8')
            return value
        with patch.object(rea,'snapshot',side_effect=changing):
            detail=self.wait(self.submit(skill_id='rea.software-analysis',paths=[],target_path='external.asar'))
        self.assertEqual(detail['task']['status'],'FAILED')
        def stop(): raise CoreError('cancelled','test cancel')
        with self.assertRaises(CoreError) as caught: rea.snapshot(self.core,self.args,stop)
        self.assertEqual(caught.exception.code,'cancelled')

    def test_literal_focus_validation(self):
        self.assertTrue(rea_focus.matches({'channel':'fixture:op1'},'fixture:op1'))
        self.assertFalse(rea_focus.matches({'channel':'fixture:op10'},'fixture:op1'))
        self.assertEqual(rea_focus.query({'prompt':'解释 `sum` 的用途'})[0],'sum')
        self.assertEqual(rea_focus.query({'prompt':'解释 `'+('测'*100)+'`'})[0],'')
        from jarvis_core.skills import infer_skill
        self.assertEqual(infer_skill('分析 ASAR 里的模块'), 'rea.software-analysis')
        self.assertIsNone(infer_skill('不要分析 ASAR 里的模块'))
        for focus in (123,'x'*257,'one\ntwo'):
            with self.assertRaises(CoreError): self.submit(skill_id='rea.software-analysis',paths=[],target_path='app.asar',focus=focus)

    def test_no_match_and_filtered_pages(self):
        from jarvis_core.rea_evidence import page
        evidence={'evidence_id':'fixture','normalized_result':{'graph':{'nodes':[],
            'edges':[{'edge_id':str(i),'relation':'invokes','properties':{'channel':'app:op'+str(i)}} for i in range(12)]}}}
        focus=rea_focus.inspect(evidence,{'focus':'missing:op'})
        self.assertFalse(focus['matched'])
        self.assertIn('不能据此认定功能不存在', '\n'.join(rea_focus.lines(focus)))
        result=page(evidence,{},'links',query='app:op1')
        self.assertEqual(result['total'],1);self.assertEqual(result['total_before_filter'],12)
        self.assertIsNone(result['next_offset'])
        for invalid in ('x'*257,'one\ntwo',42):
            with self.assertRaises(CoreError):page(evidence,{},'links',query=invalid)


for name in list(test_skills.TaskTests.__dict__):
    if name.startswith('test_'):setattr(AsarTests,name,None)

if __name__=='__main__':unittest.main()
