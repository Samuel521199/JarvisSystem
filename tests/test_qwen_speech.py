"""Primary TTS boundaries, damaged streams, and independent owned child cleanup."""
import base64
import io
import json
from pathlib import Path
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import test_web
from jarvis_core.qwen_protocol import NativeProtocol
from jarvis_core.qwen_speech import QwenSpeechService
from jarvis_core.qwen_speech_contract import validate, expression_plan
from jarvis_core.speech_contract import SpeechError


class QwenTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.core=test_web.FakeCore(); self.core.data_dir=Path(self.temp.name)
        self.service=QwenSpeechService(self.core); self.addCleanup(self.service.close)

    def test_observation_never_launches_or_connects_and_missing_profile_is_optional(self):
        with patch.object(self.service,'_call',side_effect=AssertionError()),patch.object(self.service,'launcher',side_effect=AssertionError()):
            value=self.service.snapshot()
        self.assertEqual(value['usage_role'],'primary'); self.assertFalse(value['auto_start'])
        self.assertEqual(len(value['capabilities']['voices']),9); self.assertFalse(value['capabilities']['cloning'])
        self.assertIsNone(value['gpu_memory']); self.assertFalse(self.service.data.exists())
        service=QwenSpeechService(self.core,config_path=self.core.data_dir/'missing.json'); self.addCleanup(service.close)
        self.assertFalse(service.snapshot()['installed'])
        with self.assertRaises(SpeechError): service.submit({'action':'start'})
        self.assertFalse(self.core.stopped)

    def test_public_input_cannot_change_paths_instructions_device_or_clone(self):
        self.assertEqual(validate({'action':'synthesize','text':'你好'})['voice'],'serena')
        for change in ({'voice':[]},{'emotion':'unknown'},{'language':{}},{'text':'好'*181},
                       {'instructions':'arbitrary'},{'reference_path':'C:/x'},{'device':'cpu'},{'mode':'clone'}):
            with self.subTest(change=change),self.assertRaises(SpeechError): validate(dict(action='synthesize',text='你好')|change)

    def test_broker_must_report_owned_native_child(self):
        self.service.engine=SimpleNamespace(pid=10,poll=lambda:None,contains=lambda pid:pid==11,stop=lambda:None)
        for pid in (10,12,None,True):
            with self.subTest(pid=pid),self.assertRaises(SpeechError):
                self.service._validate_health({'pid':11,'ready':True,'inference_pid':pid,'protocol':3},11)
        self.service.engine.contains=lambda pid:pid in (11,12)
        self.service._validate_health({'pid':11,'ready':True,'inference_pid':12,'protocol':3},11)

    def test_one_leading_tag_overrides_selector_without_becoming_spoken_text(self):
        for text in ['[开心] 今天见到你真好！','【开心】今天见到你真好！','[HAPPY]今天见到你真好！']:
            result=validate(dict(action='synthesize',text=text,emotion='sad'))
            segment=expression_plan(result)['segments'][0]
            self.assertEqual(segment['text'],'今天见到你真好！');self.assertEqual(segment['emotion'],'happy')
            # The broker validates again: normalization must be idempotent.
            self.assertEqual(validate(dict(result,action='synthesize')),result)
        result=validate(dict(action='synthesize',text='[自然]你好',emotion='angry'))
        self.assertEqual(expression_plan(result)['segments'][0]['emotion'],'neutral')
        self.assertEqual(validate(dict(action='synthesize',text='普通正文'))['emotion'],'neutral')

    def test_unknown_empty_or_malformed_emotion_tags_are_not_silently_spoken(self):
        for text in ['[撒娇]你好','[laugh]你好','[开心]','[开心][CPU]你好','[开心你好','你好。【悲伤']:
            with self.subTest(text=text),self.assertRaises(SpeechError):validate(dict(action='synthesize',text=text))

    def test_snapshot_rejects_lost_native_child_and_does_not_measure_arbitrary_pid(self):
        killed=threading.Event()
        self.service.engine=SimpleNamespace(pid=10,poll=lambda:None,contains=lambda pid:pid==11,stop=killed.set)
        self.service.worker_pid=11; self.service.health={'pid':11,'inference_pid':12}; self.service.state='ready'
        with patch('jarvis_core.qwen_speech.process_memory',side_effect=AssertionError()): value=self.service.snapshot()
        self.assertTrue(killed.is_set()); self.assertEqual(value['state'],'failed'); self.assertIsNone(value['pid'])

    def test_restart_does_not_treat_previous_health_as_new_native_child(self):
        killed=threading.Event()
        self.service.engine=SimpleNamespace(pid=20,poll=lambda:None,contains=lambda pid:pid==20,stop=killed.set)
        self.service.worker_pid=None; self.service.health={'pid':11,'inference_pid':12}; self.service.state='loading'
        value=self.service.snapshot()
        self.assertTrue(value['owned']); self.assertEqual(value['state'],'loading'); self.assertIsNone(value['pid'])
        self.assertFalse(killed.is_set())

    def test_stop_during_native_inference_keeps_core_running_and_fences_late_wav(self):
        entered=threading.Event(); release=threading.Event(); killed=threading.Event()
        self.service.engine=SimpleNamespace(pid=10,poll=lambda:None,stop=killed.set); self.service.state='ready'
        def call(*args,**kwargs): entered.set(); release.wait(2); return {'audio_seconds':1}
        with patch.object(self.service,'_call',side_effect=call):
            self.service.submit({'action':'synthesize','text':'你好','emotion':'happy'}); self.assertTrue(entered.wait(1))
            self.service.stop(); release.set(); time.sleep(.05)
        value=self.service.snapshot(); self.assertTrue(killed.is_set()); self.assertFalse(self.core.stopped)
        self.assertEqual(value['job']['status'],'CANCELLED'); self.assertEqual(value['uses'],0)
        self.assertNotIn('result',value['job'])

    def test_pcm_stream_requires_order_identity_completion_and_duration_bound(self):
        chunk=dict(type='chunk',id='x',seq=0,pcm=base64.b64encode(b'\0\0'*24).decode())
        end=dict(type='end',id='x',samples=24,stop='complete')
        def reader(rows): return NativeProtocol(io.BytesIO(b''.join(json.dumps(r).encode()+b'\n' for r in rows)))
        pcm,first=reader([chunk,end]).audio('x',1,1); self.assertEqual(len(pcm),48); self.assertGreaterEqual(first,0)
        bad=[[dict(chunk,id='other'),end],[dict(chunk,seq=1),end],[chunk,dict(end,stop='max_seconds')],
             [chunk,dict(end,samples=1)],[dict(chunk,pcm='bad!'),end],
             [dict(chunk,pcm=base64.b64encode(b'0'*48002).decode()),end],[{'type':'error','id':'x'}]]
        for rows in bad:
            with self.subTest(rows=str(rows)[:100]),self.assertRaises(SpeechError): reader(rows).audio('x',1,1)
