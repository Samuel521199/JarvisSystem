"""Real Windows process fault isolation; no credentials or live providers."""
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'runtime/node-host'))
from jarvis_core.service import CoreService
from jarvis_core.chat import ChatService
from jarvis_core.dialogue_process import DialogueProcesses, in_dialogue
from jarvis_core.turns import invoke_reply


@unittest.skipUnless(os.name == 'nt', 'Verified Windows Job backend')
class DialogueProcessTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory(prefix='jarvis-dialogue-process-')
        self.addCleanup(tmp.cleanup)
        self.base = Path(tmp.name)
        sample = self.base / 'sample'; sample.mkdir()
        (sample / 'example.txt').write_text('bounded task fixture')
        self.core = CoreService(self.base / 'data'); self.core.initialize(sample)
        self.pool = DialogueProcesses(self.core); self.addCleanup(self.pool.close)
        self.config = json.loads((ROOT / 'config/model-profiles/providers.json').read_text(encoding='utf-8'))

    def mode(self, mode):
        self.pool._command = [sys._base_executable, '-u', str(ROOT / 'tests/dialogue_process_fixture.py'), mode]

    def probe(self, **kwargs):
        return self.pool.probe(self.config, 'local', 'hello', self.core.data_dir,
                               self.core.assert_running, **kwargs)

    def wait_active(self, count=1):
        end = time.monotonic()+3
        while time.monotonic()<end:
            state = self.pool.snapshot()
            if state['active'] == count and all(p['phase']=='waiting' for p in state['processes']): return state
            time.sleep(.01)
        self.fail('child did not start')

    def test_real_gateway_journal_and_no_idle_process(self):
        self.mode('gateway')
        result = self.probe()
        self.assertEqual(result['status'], 'SUCCEEDED', result)
        self.assertEqual(result['text'], 'isolated gateway reply')
        self.assertTrue(result['dispatch_admitted'])
        with closing(sqlite3.connect(self.core.data_dir / 'model-probes.db')) as db:
            self.assertEqual(db.execute('SELECT status FROM probes').fetchall(), [('SUCCEEDED',)])
        self.assertEqual(self.pool.snapshot()['active'], 0)
        self.assertEqual(self.pool.snapshot()['last']['reason'], 'succeeded')

    def test_crash_invalid_oversize_no_replay_and_next_request_recovers(self):
        for mode in ('crash', 'invalid', 'wrong_id', 'oversize'):
            with self.subTest(mode=mode):
                self.mode(mode); result = self.probe()
                self.assertEqual(result['status'], 'UNKNOWN', result)
                self.assertFalse(result['automatic_retry'])
                self.assertNotIn('text', result)
                self.assertEqual(self.pool.snapshot()['active'], 0)
        self.mode('ok'); self.assertEqual(self.probe()['text'], 'child reply')
        self.assertEqual(self.pool.snapshot()['completed'], 5)

    def test_hang_has_wall_limit_and_releases_slot(self):
        self.mode('hang'); start=time.monotonic()
        result=self.probe(deadline_seconds=-19)  # Synthetic one-second supervisor bound.
        self.assertEqual(result['error'], 'dialogue_process_timeout')
        self.assertLess(time.monotonic()-start, 3)
        self.assertEqual(self.pool.snapshot()['active'], 0)

    def test_two_hung_children_do_not_block_control_or_real_inventory(self):
        self.mode('hang'); cancel=threading.Event()
        with ThreadPoolExecutor(2) as executor:
            futures=[executor.submit(self.probe, cancel_event=cancel) for _ in range(2)]
            try:
                state=self.wait_active(2)
                self.assertEqual(len({p['pid'] for p in state['processes']}), 2)
                self.assertNotIn(os.getpid(), [p['pid'] for p in state['processes']])
                self.assertEqual(self.probe()['error'], 'dialogue_process_busy')
                start=time.monotonic(); self.core.assert_running()
                self.assertLess(time.monotonic()-start, .5)
                record=self.core.inventory(relative_path='.')
                self.assertEqual(record['action']['status'], 'CONFIRMED')
                self.assertEqual(self.pool.snapshot()['active'], 2)
            finally: cancel.set()
            for future in futures:
                result=future.result(3)
                self.assertTrue(result['cancel_requested']); self.assertTrue(result['outcome_uncertain'])
        self.assertEqual(self.pool.snapshot()['active'], 0)

    def test_close_and_pre_cancel_do_not_leave_children(self):
        cancel=threading.Event(); cancel.set()
        self.assertEqual(self.probe(cancel_event=cancel)['status'], 'CANCELLED')
        self.assertEqual(self.pool.snapshot()['completed'], 0)
        self.mode('hang')
        with ThreadPoolExecutor(1) as executor:
            future=executor.submit(self.probe)
            self.wait_active(); self.pool.close()
            self.assertEqual(future.result(3)['status'], 'UNKNOWN')
        self.assertEqual(self.pool.snapshot()['active'], 0)
        self.assertEqual(self.probe()['status'], 'FAILED')

    def test_only_dialogue_scope_uses_process_personal_and_background_remain_host_owned(self):
        self.mode('gateway')
        chat=ChatService(self.core); chat.dialogue_models=self.pool
        with patch('jarvis_core.chat.gateway.probe', return_value={'status':'SUCCEEDED','text':'background', 'outcome_uncertain':False}) as direct:
            self.assertEqual(chat.reply('hello', provider='local')['text'], 'background')
            result=invoke_reply(self.core,chat,{'message':'hello','provider':'local'},threading.Event(),'a'*32)
            self.assertEqual(result['text'],'isolated gateway reply', result)
            self.assertEqual(direct.call_count,1)
            result=invoke_reply(self.core,chat,{'message':'/计算 14*3'},threading.Event(),'b'*32)
            self.assertEqual(result['text'],'14*3 = 42')
            result=invoke_reply(self.core,chat,{'message':'查看交流设置', 'personal_context':{'temporary':False}},threading.Event(),'c'*32)
            self.assertEqual(result['provider'],'builtin',result)
        self.assertFalse(in_dialogue.get())
        self.assertEqual(self.pool.snapshot()['completed'],1)

    def test_stopped_core_cannot_dispatch(self):
        self.mode('gateway')
        self.core.ledger.stop('test')
        result=self.probe()
        self.assertEqual(result['status'],'FAILED')
        self.assertFalse((self.core.data_dir/'model-probes.db').exists())

    def test_production_entry_rejects_invalid_input_before_credentials(self):
        # The vault is per user, not per data_dir. Never assume temp core data
        # means no credentials. Empty input is rejected before vault loading.
        result=self.pool.probe(self.config,'vertex','',self.core.data_dir,self.core.assert_running)
        self.assertEqual(result['status'],'UNKNOWN',result)
        self.assertEqual(self.pool.snapshot()['last']['reason'],'crashed')
        self.assertFalse((self.core.data_dir/'model-probes.db').exists())

    def test_parent_hard_exit_kills_owned_child(self):
        from jarvis_core.process_usage import process_usage
        result=subprocess.run([sys.executable,str(ROOT/'tests/dialogue_process_fixture.py'),'parent_exit'],
            input=json.dumps({'config':self.config,'data_dir':str(self.core.data_dir)}).encode(),
            stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=10,creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(result.returncode,31)
        pid=int(result.stdout.strip())
        end=time.monotonic()+3
        while time.monotonic()<end:
            try: process_usage(pid)
            except OSError: break
            time.sleep(.02)
        else: self.fail('Owned child survived Host exit')

    def test_stop_while_running_reclaims_process_without_replay(self):
        self.mode('hang')
        with ThreadPoolExecutor(1) as executor:
            future=executor.submit(self.probe)
            self.wait_active(); self.core.ledger.stop('test active stop')
            result=future.result(3)
            self.assertEqual(result['status'],'UNKNOWN')
        self.assertEqual(self.pool.snapshot()['active'],0)

    def test_context_hang_is_reaped_and_personal_commands_stay_available(self):
        self.mode('context_hang'); self.pool.context_seconds=1.5
        chat=ChatService(self.core);chat.dialogue_models=self.pool
        with ThreadPoolExecutor(1) as executor:
            future=executor.submit(invoke_reply,self.core,chat,{'message':'hello','provider':'local'},threading.Event(),'d'*32)
            end=time.monotonic()+2
            while not self.pool.snapshot()['active'] and time.monotonic()<end:time.sleep(.01)
            result=invoke_reply(self.core,chat,{'message':'/计算 12*7'},threading.Event(),'e'*32)
            self.assertEqual(result['text'],'12*7 = 84')
            result=future.result(4)
            self.assertEqual(result['error'],'dialogue_context_timeout',result)
        self.assertFalse((self.core.data_dir/'model-probes.db').exists())
        self.assertEqual(self.pool.snapshot()['active'],0)
        self.mode('gateway')
        self.assertEqual(invoke_reply(self.core,chat,{'message':'hello','provider':'local'},threading.Event(),'f'*32)['status'],'SUCCEEDED')

    def test_background_pool_has_own_capacity_and_cancellation(self):
        background=DialogueProcesses(self.core,capacity=1);self.addCleanup(background.close)
        background._command=[sys._base_executable,'-u',str(ROOT/'tests/dialogue_process_fixture.py'),'model_hang']
        self.mode('gateway'); chat=ChatService(self.core);chat.dialogue_models=self.pool
        cancel=threading.Event()
        with ThreadPoolExecutor(1) as executor:
            future=executor.submit(background.reply,chat,'plan',provider='local',cancel_event=cancel,_purpose='sample_report')
            end=time.monotonic()+3
            while not background.snapshot()['active'] and time.monotonic()<end:time.sleep(.01)
            try:
                self.assertEqual(background.reply(chat,'another',provider='local')['error'],'dialogue_process_busy')
                result=invoke_reply(self.core,chat,{'message':'still chatting','provider':'local'},threading.Event(),'1'*32)
                self.assertEqual(result['status'],'SUCCEEDED',result)
                self.assertEqual(background.snapshot()['active'],1)
            finally:cancel.set()
            self.assertTrue(future.result(3)['outcome_uncertain'])
        self.assertEqual(background.snapshot()['active'],0)

    def test_child_refuses_personal_write_and_task_cancel_fences_dispatch(self):
        self.mode('gateway');chat=ChatService(self.core)
        result=self.pool.reply(chat,'记住：不应保存',provider='local',personal_context={'temporary':False})
        self.assertEqual(result['status'],'UNKNOWN')
        self.assertFalse((self.core.data_dir/'memory.db').exists())
        record=self.core.prepare_inventory(relative_path='.')
        tid=record['task']['task_id'];self.core.cancel(tid)
        from jarvis_core.sample_tasks import ScopedCore
        scoped=ScopedCore(self.core,lambda:None,task_id=tid)
        # The worker independently checks task cancellation even when the
        # synthetic parent checkpoint intentionally does not.
        result=self.pool.reply(ChatService(scoped),'plan',provider='local',_purpose='sample_report')
        self.assertNotEqual(result['status'],'SUCCEEDED')
        self.assertFalse((self.core.data_dir/'model-probes.db').exists())
