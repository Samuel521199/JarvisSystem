"""Readout ownership, retries, expiry and text preparation without real inference."""
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_web
from jarvis_core.qwen_speech import QwenSpeechService
from jarvis_core.readout_text import prepare
from jarvis_core.qwen_speech_contract import validate,expression_plan
from jarvis_core.speech import SpeechService
from jarvis_core.speech_contract import SpeechError


class ReadoutTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        core=test_web.FakeCore();core.data_dir=Path(self.temp.name)
        self.service=QwenSpeechService(core);self.addCleanup(self.service.close);self.lane=self.service.reader
        self.service.state='ready';self.calls=[]

    def start(self,ident='a'*32,text='[轻声][慢速]别担心。[停顿350ms][自然][开心]一起试试看！'):
        return self.lane.submit(dict(action='start',id=ident,text=text))

    def fake(self,service,payload):
        self.calls.append(payload);job=dict(id=str(len(self.calls)).zfill(32),status='RUNNING')
        service.job=job;service.state='busy';return dict(job=job)

    def complete(self):
        self.service.job.update(status='SUCCEEDED',result={'audio_url':'/api/speech/primary/audio/'+'f'*32,'audio_seconds':1})
        self.service.last_job=self.service.job.copy();self.service.job=None;self.service.state='ready'

    def test_start_observation_is_light_and_metadata_is_not_a_model_call(self):
        value=self.start();self.assertEqual(value['total'],2);self.assertFalse(self.service.data.exists())
        self.assertTrue(self.service.snapshot()['readout_active']);self.assertFalse(self.service.snapshot()['owned'])

    def test_same_index_gets_receipt_without_duplicating_inference(self):
        self.start()
        with patch.object(SpeechService,'submit',autospec=True,side_effect=self.fake):
            first=self.lane.submit(dict(action='next',id='a'*32,index=0))
            repeat=self.lane.submit(dict(action='next',id='a'*32,index=0))
            self.assertEqual(first['items'],repeat['items']);self.assertEqual(len(self.calls),1)
            self.complete();self.lane.view('a'*32)
            self.lane.submit(dict(action='next',id='a'*32,index=1));self.assertEqual(len(self.calls),2)

    def test_start_is_idempotent_but_content_changes_and_reuse_after_finish_are_rejected(self):
        first=self.start();self.assertEqual(first,self.start())
        with self.assertRaises(SpeechError):self.start(text='另一个请求')
        self.lane.submit(dict(action='stop',id='a'*32))
        with self.assertRaises(SpeechError):self.start()

    def test_stop_before_delayed_start_leaves_tombstone_without_stopping_another_reader(self):
        self.lane.submit(dict(action='stop',id='a'*32))
        with self.assertRaises(SpeechError):self.start()
        self.start('b'*32)
        self.lane.submit(dict(action='stop',id='a'*32));self.assertTrue(self.lane.view('b'*32)['active'])

    def test_settings_cannot_take_lane_but_preview_and_global_stop_are_available(self):
        self.start()
        with self.assertRaises(SpeechError):self.service.submit({'action':'synthesize','text':'另一个合成'})
        self.assertIn('preview',self.service.submit({'action':'preview','text':'[开心]你好'}))
        self.service.submit({'action':'stop'});self.assertFalse(self.lane.view('a'*32)['active'])

    def test_reader_does_not_preempt_existing_settings_job(self):
        self.service.job=dict(id='f'*32,status='RUNNING')
        with self.assertRaises(SpeechError):self.start()
        self.assertEqual(self.service.job['id'],'f'*32);self.assertIsNone(self.lane.current)

    def test_stop_idle_keeps_model_ready_and_busy_stop_cancels_only_owned_operation(self):
        self.start();self.lane.submit(dict(action='stop',id='a'*32));self.assertEqual(self.service.state,'ready')
        self.start('b'*32)
        with patch.object(SpeechService,'submit',autospec=True,side_effect=self.fake):self.lane.submit(dict(action='next',id='b'*32,index=0))
        self.lane.submit(dict(action='stop',id='b'*32));self.assertIsNone(self.service.job);self.assertEqual(self.service.state,'stopped')
        self.assertFalse(self.service.core.stopped)

    def test_expiry_is_lazy_bounded_and_never_replays(self):
        self.start();self.lane.current['deadline']=0
        self.assertEqual(self.lane.view('a'*32)['status'],'EXPIRED')
        with self.assertRaises(SpeechError):self.lane.submit(dict(action='next',id='a'*32,index=0))

    def test_finish_requires_all_complete_and_bad_indexes_do_not_start_work(self):
        self.start(text='你好。')
        for index in (True,-1,3):
            with self.assertRaises(SpeechError):self.lane.submit(dict(action='next',id='a'*32,index=index))
        with self.assertRaises(SpeechError):self.lane.submit(dict(action='finish',id='a'*32))
        with patch.object(SpeechService,'submit',autospec=True,side_effect=self.fake):self.lane.submit(dict(action='next',id='a'*32,index=0))
        self.complete();self.assertEqual(self.lane.submit(dict(action='finish',id='a'*32))['status'],'FINISHED')

    def test_markdown_code_links_and_chunks_preserve_readable_text_and_dimensions(self):
        p=prepare(dict(text='# 提醒\n[轻声][慢速]'+('别担心，我们一步一步来。'*10)+'\n```python\nsecret = 123\n```\n[自然][开心][说明](https://example.com)'))
        self.assertGreater(len(p['chunks']),1);self.assertNotIn('secret',str(p['chunks']));self.assertNotIn('https://',str(p['chunks']))
        self.assertIn('代码块已略过',p['notices'])
        controlled=next(c for c in p['chunks'] if '别担心' in c['text'])
        first=expression_plan(validate(dict(controlled,action='synthesize')))['segments'][0]
        self.assertEqual((first['delivery'],first['pace']),('soft','slow'))
        self.assertTrue(all(len(c['text'])<=180 for c in p['chunks']))

    def test_unclosed_code_and_oversized_text_do_not_speak_or_silently_truncate(self):
        p=prepare(dict(text='你好\n```python\nprint(123)'));self.assertNotIn('print',str(p['chunks']))
        for text in ('a'*16001,'字'*1801):
            with self.assertRaises(SpeechError):prepare(dict(text=text))
