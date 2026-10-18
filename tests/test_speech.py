"""Offline contract, cancellation and HTTP tests; native inference is separately measured."""
from pathlib import Path
from types import SimpleNamespace
import argparse
import base64
import io
import json
import tempfile
import threading
import time
import unittest
import wave
from unittest.mock import patch

import test_web
from jarvis_core.speech import SpeechService
from jarvis_core.fast_speech import FastSpeechService
from jarvis_core.qwen_speech import QwenSpeechService
from jarvis_core.speech_contract import SpeechError, reference_info, validate_synthesis


def wav(seconds=1):
    stream = io.BytesIO()
    with wave.open(stream, 'wb') as output:
        output.setnchannels(1); output.setsampwidth(2); output.setframerate(16000)
        output.writeframes(b'\0\0' * int(16000 * seconds))
    return stream.getvalue()


class SpeechTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.core = test_web.FakeCore(); self.core.data_dir = Path(self.temp.name)
        self.service = SpeechService(self.core); self.addCleanup(self.service.close)

    def wait(self):
        end = time.monotonic() + 3
        while self.service.job and time.monotonic() < end: time.sleep(.01)
        self.assertIsNone(self.service.job)

    def test_observation_does_not_create_store_load_model_or_contact_worker(self):
        with patch.object(self.service, '_call', side_effect=AssertionError('must not call')):
            value = self.service.snapshot()
        self.assertFalse(value['owned']); self.assertEqual(value['state'], 'stopped')
        self.assertFalse(self.service.data.exists())

    def test_start_accepts_random_token_beginning_with_hyphen(self):
        environment=self.core.data_dir/'test-environment';(environment/'Scripts').mkdir(parents=True)
        (environment/'Scripts/python.exe').write_bytes(b'fixture')
        self.service.cfg['environment_root']=str(environment)
        self.service.probe=lambda:dict(available_bytes=100*1024**3,commit_available_bytes=100*1024**3)
        def launch(argv):
            parser=argparse.ArgumentParser()
            for name in ('config','data-dir','ready-file','token'):parser.add_argument('--'+name,required=True)
            parsed=parser.parse_args(argv[2:])
            self.assertEqual(parsed.token,'-component-test')
            Path(parsed.ready_file).write_text(json.dumps(dict(pid=123,port=12345)),encoding='utf-8')
            return SimpleNamespace(pid=123,poll=lambda:None,contains=lambda pid:pid==123,stop=lambda:None)
        with patch.object(self.service,'_prepare'),patch.object(self.service,'installed',return_value=True),\
             patch.object(self.service,'launcher',side_effect=launch),\
             patch.object(self.service,'_call',return_value=dict(pid=123,ready=True)),\
             patch('jarvis_core.speech.secrets.token_urlsafe',return_value='-component-test'):
            self.service._start(self.service.epoch)
        self.assertEqual(self.service.state,'ready')

    def test_missing_optional_profile_does_not_break_host_or_load_old_profile(self):
        service=SpeechService(self.core,config_path=self.core.data_dir/'absent.json')
        self.addCleanup(service.close)
        self.assertFalse(service.snapshot()['installed'])
        with self.assertRaises(SpeechError):service.submit({'action':'start'})
        self.assertFalse(self.core.stopped)

    def test_audio_contract_and_custom_clone_requires_matching_text(self):
        encoded = base64.b64encode(wav()).decode('ascii')
        self.assertEqual(reference_info(wav())['seconds'], 1)
        with self.assertRaises(SpeechError): validate_synthesis({'action':'synthesize','text':'你好','mode':'clone','reference_audio':encoded})
        parsed = validate_synthesis({'action':'synthesize','text':'你好','mode':'clone','reference_audio':encoded,'reference_text':'你好'})
        self.assertEqual(parsed['reference_data'], wav())
        for payload in ({'action':'synthesize','text':'a','reference_path':'C:/private.wav'},
                        {'action':'synthesize','text':'a','mode':'clone','emotion':'happy'},
                        {'action':'synthesize','text':'a','emotion':[]},
                        {'action':'synthesize','text':'a','reference_audio':'!invalid'},
                        {'action':'synthesize','text':'a'*301}):
            with self.subTest(payload=payload), self.assertRaises(SpeechError): validate_synthesis(payload)
        for data in (b'not wav', wav(.5), wav(16)):
            with self.assertRaises(SpeechError): reference_info(data)

    def test_stop_fences_late_start_before_process_creation(self):
        entered, release = threading.Event(), threading.Event()
        def start(epoch): entered.set(); release.wait(2); self.service._checkpoint(epoch)
        with patch.object(self.service, '_start', side_effect=start):
            self.service.submit({'action':'start'}); self.assertTrue(entered.wait(1))
            with self.assertRaises(SpeechError): self.service.submit({'action':'start'})
            self.service.submit({'action':'stop'}); release.set(); time.sleep(.05)
        value = self.service.snapshot()
        self.assertEqual(value['state'],'stopped'); self.assertEqual(value['job']['status'],'CANCELLED')
        self.assertFalse(value['owned'])

    def test_stop_fences_late_inference_and_deletes_temporary_reference(self):
        entered, release = threading.Event(), threading.Event()
        self.service.data.joinpath('references').mkdir(parents=True)
        engine = SimpleNamespace(pid=999999, poll=lambda:None, stop=lambda:None)
        self.service.engine = engine; self.service.state = 'ready'
        def call(*args, **kwargs): entered.set(); release.wait(2); return {'elapsed_seconds':1}
        with patch.object(self.service, '_call', side_effect=call):
            self.service.submit({'action':'synthesize','text':'你好','reference_audio':base64.b64encode(wav()).decode('ascii')})
            self.assertTrue(entered.wait(1)); self.assertEqual(len(list((self.service.data/'references').glob('*.wav'))),1)
            self.service.stop(); release.set()
            end = time.monotonic()+2
            while list((self.service.data/'references').glob('*.wav')) and time.monotonic()<end:time.sleep(.01)
        self.assertEqual(self.service.snapshot()['job']['status'],'CANCELLED')
        self.assertEqual(list((self.service.data/'references').glob('*.wav')),[])

    def test_memory_admission_and_inference_timeout_do_not_stop_core(self):
        self.service.probe = lambda:{'available_bytes':1024,'commit_available_bytes':1024}
        self.service.submit({'action':'start'}); self.wait()
        self.assertEqual(self.service.snapshot()['job']['status'],'FAILED'); self.assertFalse(self.core.stopped)
        engine = SimpleNamespace(pid=999999,poll=lambda:None,stop=lambda:None)
        self.service.engine = engine; self.service.state = 'ready'
        with patch.object(self.service,'_call',side_effect=TimeoutError('private details')):
            self.service.submit({'action':'synthesize','text':'你好'}); self.wait()
        value = self.service.snapshot()
        self.assertEqual(value['state'],'failed'); self.assertFalse(value['owned'])
        self.assertNotIn('private details',json.dumps(value)); self.assertFalse(self.core.stopped)

    def test_core_stop_reclaims_inflight_owned_component(self):
        entered, release, killed = threading.Event(), threading.Event(), threading.Event()
        self.service.engine = SimpleNamespace(pid=999999,poll=lambda:None,stop=killed.set)
        self.service.state = 'ready'
        def call(*args, **kwargs):entered.set();release.wait(2);return {}
        with patch.object(self.service,'_call',side_effect=call):
            self.service.submit({'action':'synthesize','text':'你好'});self.assertTrue(entered.wait(1))
            self.core.stopped=True
            try:self.assertTrue(killed.wait(1))
            finally:release.set()
        self.assertEqual(self.service.snapshot()['state'],'stopped')
        self.assertEqual(self.service.snapshot()['job']['status'],'CANCELLED')


class SpeechHTTPTests(unittest.TestCase):
    request = test_web.WebTests.request

    def setUp(self):
        test_web.WebTests.setUp(self)
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.server.core.data_dir = Path(self.temp.name)
        self.speech = SpeechService(self.server.core)
        self.fast = FastSpeechService(self.server.core)
        self.primary = QwenSpeechService(self.server.core)
        self.server.modules = SimpleNamespace(speech=self.speech,fast_speech=self.fast,primary_speech=self.primary,
            close=lambda:(self.speech.close(),self.fast.close(),self.primary.close()))

    def test_primary_route_is_protected_and_audio_stores_are_isolated(self):
        self.assertEqual(self.request('GET','/api/speech/primary')[0],403)
        headers={'X-Jarvis-Nonce':self.server.nonce}
        status,_,body=self.request('GET','/api/speech/primary',headers=headers)
        self.assertEqual(status,200); self.assertEqual(json.loads(body)['usage_role'],'primary')
        self.primary.data.joinpath('audio').mkdir(parents=True)
        (self.primary.data/'audio'/('b'*32+'.wav')).write_bytes(wav())
        for endpoint,expected in [('/api/speech/primary',200),('/api/speech/fast',404),('/api/speech',404)]:
            self.assertEqual(self.request('GET',endpoint+'/audio/'+'b'*32,headers=headers)[0],expected)
        self.assertEqual(self.request('POST','/api/speech/primary',{'action':'synthesize','text':'你好','instructions':'x'})[0],400)
        self.assertEqual(self.request('POST','/api/speech/primary',{'action':'stop'})[0],202)
        self.assertFalse(self.server.core.stopped)

    def test_expression_preview_is_protected_pure_and_does_not_need_an_installed_model(self):
        payload={'action':'preview','text':'[轻声][慢速]我在。[停顿300ms][自然][开心]一起走吧。'}
        with patch.object(self.primary,'launcher',side_effect=AssertionError('must not start')):
            status,_,body=self.request('POST','/api/speech/primary',payload)
        self.assertEqual(status,200);plan=json.loads(body)['preview']
        self.assertEqual(plan['speech_segments'],2);self.assertEqual(plan['pause_ms'],300)
        self.assertEqual(plan['segments'][0]['delivery'],'soft');self.assertFalse(self.primary.data.exists())
        self.assertNotIn('instructions',plan['segments'][0]);self.assertFalse(self.primary.snapshot()['owned'])

    def test_readout_routes_require_nonce_and_cannot_preempt_the_reserved_lane(self):
        ident='c'*32
        self.assertEqual(self.request('GET','/api/speech/readout/'+ident)[0],403)
        self.primary.state='ready'
        status,_,body=self.request('POST','/api/speech/readout',dict(action='start',id=ident,text='你好。'))
        self.assertEqual(status,200);self.assertTrue(json.loads(body)['active']);self.assertFalse(self.primary.data.exists())
        self.assertEqual(self.request('POST','/api/speech/primary',dict(action='synthesize',text='别的请求'))[0],400)
        status,_,body=self.request('POST','/api/speech/readout',dict(action='stop',id=ident))
        self.assertEqual(status,200);self.assertFalse(json.loads(body)['active'])
        self.assertEqual(self.request('GET','/readout.js')[0],200)

    def test_fast_route_keeps_observation_independent_and_rejects_emotion_escalation(self):
        self.assertEqual(self.request('GET','/api/speech/fast')[0],403)
        status,_,body=self.request('GET','/api/speech/fast',headers={'X-Jarvis-Nonce':self.server.nonce})
        self.assertEqual(status,200);self.assertEqual(json.loads(body)['id'],'zipvoice')
        self.assertEqual(json.loads(body)['usage_role'],'fallback');self.assertFalse(json.loads(body)['auto_start'])
        with self.assertRaises(SpeechError):self.fast.parse_synthesis({'action':'synthesize','text':'你好','mode':'instruct','emotion':'happy'})
        with self.assertRaises(SpeechError):self.fast.parse_synthesis({'action':'synthesize','text':'好'*181,'mode':'clone'})
        value=self.fast.parse_synthesis({'action':'synthesize','text':'你好','mode':'clone'})
        self.assertIsNone(value['reference_data']);self.assertFalse(self.fast.data.exists())
        self.fast.data.joinpath('audio').mkdir(parents=True)
        (self.fast.data/'audio'/('a'*32+'.wav')).write_bytes(wav())
        self.assertEqual(self.request('GET','/api/speech/fast/audio/'+'a'*32,
            headers={'X-Jarvis-Nonce':self.server.nonce})[0],200)
        self.assertEqual(self.request('GET','/api/speech/audio/'+'a'*32,
            headers={'X-Jarvis-Nonce':self.server.nonce})[0],404)
        self.assertEqual(self.request('POST','/api/speech/fast',{'action':'stop'})[0],202)
        self.assertFalse(self.speech.closed);self.assertFalse(self.server.core.stopped)

    def test_speech_routes_require_nonce_and_keep_chat_independent(self):
        status,_,_ = self.request('GET','/api/speech'); self.assertEqual(status,403)
        status,_,body = self.request('GET','/api/speech',headers={'X-Jarvis-Nonce':self.server.nonce})
        self.assertEqual(status,200); self.assertEqual(json.loads(body)['state'],'stopped')
        status,_,_ = self.request('POST','/api/speech',{'action':'synthesize','text':'你好'},headers={'X-Jarvis-Nonce':self.server.nonce})
        self.assertEqual(status,400)
        status,_,_ = self.request('GET','/speech.js'); self.assertEqual(status,200)
        status,headers,body = self.request('GET','/settings')
        self.assertEqual(status,200); self.assertIn(b'speech-panel',body)
        self.assertIn("media-src 'self' blob:",dict(headers)['Content-Security-Policy'])
        entered, release = threading.Event(), threading.Event()
        def start(epoch): entered.set(); release.wait(2); self.speech._checkpoint(epoch); return {}
        with patch.object(self.speech,'_start',side_effect=start):
            self.assertEqual(self.request('POST','/api/speech',{'action':'start'})[0],202)
            self.assertTrue(entered.wait(1))
            self.assertEqual(self.request('POST','/api/chat',{'message':'hello'})[0],200)
            self.assertEqual(self.request('POST','/api/speech',{'action':'stop'})[0],202)
            release.set()


if __name__ == '__main__': unittest.main()
