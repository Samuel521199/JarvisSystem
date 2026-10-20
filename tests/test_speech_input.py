"""Local ASR admission, privacy, cancellation and HTTP regressions."""
import base64
import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from types import SimpleNamespace

import test_web
from jarvis_core.speech_input import SpeechInput, validate
from jarvis_core.speech_contract import SpeechError


def payload(ident='a'*32):
    return dict(action='transcribe', id=ident, language='auto', pcm=base64.b64encode(b'\0\0'*8000).decode())


class SpeechInputTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.core = test_web.FakeCore()
        self.core.data_dir = Path(self.tmp.name)
        self.calls = 0
        self.hold = threading.Event()
        self.hold.set()
        def runner(pcm, language, cancel):
            self.calls += 1
            self.hold.wait(2)
            return dict(text='你好', backend='fixture')
        self.service = SpeechInput(self.core, runner=runner)
        self.addCleanup(self.service.close)

    def wait(self):
        end = time.monotonic()+3
        while self.service.active and time.monotonic()<end:
            time.sleep(.01)
        self.assertIsNone(self.service.active)

    def test_idle_does_not_load_or_write(self):
        self.assertFalse(self.service.snapshot()['busy'])
        self.assertEqual(self.calls, 0)
        self.assertEqual(list(self.core.data_dir.iterdir()), [])

    def test_same_receipt_never_repeats_and_consumption_erases_text(self):
        p = payload()
        self.service.submit(p)
        self.wait()
        self.assertEqual(self.service.submit(p)['text'], '你好')
        self.assertEqual(self.calls, 1)
        self.assertNotIn('pcm', str(self.service.rows))
        self.service.submit(dict(action='forget', id=p['id']))
        self.assertNotIn('text', self.service.snapshot(p['id']))
        self.assertEqual(self.service.submit(p)['status'], 'FORGOTTEN')
        self.assertEqual(self.calls, 1)
        self.assertEqual(list(self.core.data_dir.iterdir()), [])

    def test_cancel_before_late_start_and_changed_audio_rejected(self):
        self.service.submit(dict(action='cancel', id='a'*32))
        with self.assertRaises(SpeechError): self.service.submit(payload())
        self.service.submit(payload('b'*32))
        self.wait()
        changed = payload('b'*32)
        changed['language'] = 'en'
        with self.assertRaises(SpeechError): self.service.submit(changed)

    def test_cancelled_result_cannot_return_or_cancel_other_job(self):
        self.hold.clear()
        self.service.submit(payload())
        with self.assertRaises(SpeechError): self.service.submit(payload('b'*32))
        self.service.submit(dict(action='cancel', id='b'*32))
        self.assertEqual(self.service.active, 'a'*32)
        self.service.submit(dict(action='cancel', id='a'*32))
        self.hold.set()
        self.wait()
        self.assertEqual(self.service.snapshot('a'*32)['status'], 'CANCELLED')
        self.assertNotIn('text', self.service.snapshot('a'*32))

    def test_closed_or_stopped_host_cannot_publish_late_result(self):
        self.hold.clear()
        self.service.submit(payload())
        self.service.close()
        self.hold.set()
        self.wait()
        self.assertNotIn('text', self.service.rows['a'*32])
        with self.assertRaises(SpeechError): self.service.submit(payload('b'*32))

    def test_retention_capacity_expiry_and_restart(self):
        for n in range(64):
            self.service.submit(dict(action='cancel', id=f'{n:032x}'))
        with self.assertRaises(SpeechError): self.service.submit(payload())
        for row in self.service.rows.values(): row['_at'] = 0
        self.assertEqual(self.service.snapshot('0'*32)['status'], 'MISSING')
        self.assertEqual(self.service.rows, {})
        self.service.submit(payload())
        self.wait()
        self.assertEqual(SpeechInput(self.core).snapshot('a'*32)['status'], 'MISSING')

    def test_contract_invalid_unknown_or_oversized_audio(self):
        for mutation in ({'language': []}, {'pcm': '!'}, {'pcm': 'AA=='},
                         {'pcm': base64.b64encode(b'\0'*640002).decode()}, {'path': 'secret'},
                         {'sample_rate': 48000}, {'id': '../'}, {'action': 'start'}):
            with self.subTest(mutation=list(mutation)):
                with self.assertRaises(SpeechError): validate({**payload(), **mutation})
        self.assertEqual(self.calls, 0)


class SpeechInputHTTPTests(test_web.WebTests):
    def setUp(self):
        super().setUp()
        self.service = SpeechInput(self.server.core, runner=lambda *a:dict(text='测试', backend='fixture'))
        self.server.modules = SimpleNamespace(speech_input=self.service, close=self.service.close)
        self.addCleanup(self.service.close)

    def test_input_nonce_and_origin_and_assets(self):
        p = payload()
        self.assertEqual(self.request('POST', '/api/speech/input', p, headers={'X-Jarvis-Nonce':'wrong'})[0],403)
        self.assertEqual(self.request('POST', '/api/speech/input', p, headers={'Origin':'http://foreign.invalid'})[0],403)
        self.assertEqual(self.request('POST', '/api/speech/input', p)[0],202)
        self.assertEqual(self.request('GET', '/api/speech/input/'+p['id'], headers={'X-Jarvis-Nonce':self.server.nonce})[0],200)
        for url in ('/voice-input.js','/voice-capture.js'):
            self.assertEqual(self.request('GET', url)[0],200)


# Do not rerun inherited unrelated WebTests as a new subclass suite.
for name in list(test_web.WebTests.__dict__):
    if name.startswith('test_'):
        setattr(SpeechInputHTTPTests, name, None)
