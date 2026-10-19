"""Startup failover before business effects; actual data, fault-injected packages."""
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core.service import CoreService
from jarvis_core.policy import CoreError
from jarvis_core.releases import RuntimeSlots
import test_runtime_releases as helpers


class RuntimeStartTests(unittest.TestCase):
    install = helpers.RuntimeReleaseTests.install
    health = helpers.RuntimeReleaseTests.health

    def setUp(self):
        helpers.RuntimeReleaseTests.setUp(self)
        self.input = self.base/'input';self.input.mkdir()
        self.data = self.base/'data'
        self.core = CoreService(self.data);self.core.initialize(self.input)
        self.previous = self.install('0.1.16');self.active = self.install('0.1.17')
        self.health(self.previous,'0.1.16');self.health(self.active,'0.1.17')
        self.slots.select(self.previous);self.slots.select(self.active)
        self.launches = [];self.health_calls = [];self.events = []

    def process(self, command, **kwargs):
        ident = Path(kwargs['cwd']).name
        if '-c' in command:
            self.health_calls.append(ident)
            version = '0.1.17' if ident == self.active else '0.1.16'
            return subprocess.CompletedProcess(command,0,json.dumps({'status':'passed','version':version}),'')
        self.launches.append(ident)
        self.assertEqual(command[-2:],['--data-dir',str(self.data)])
        with self.assertRaises(CoreError):self.slots.select(self.previous)
        return subprocess.CompletedProcess(command,0)

    def start(self):
        return self.slots.start(data_dir=self.data,mode='status',notify=self.events.append)

    def damage(self, ident):
        (self.slots.slots/ident/'source/hello.txt').write_text('corrupt',encoding='utf-8')

    def test_healthy_active_starts_once_and_keeps_selection(self):
        before=self.slots.status()['generation']
        with patch('jarvis_core.releases.subprocess.run',side_effect=self.process):result=self.start()
        self.assertEqual(self.health_calls,[self.active]);self.assertEqual(self.launches,[self.active])
        self.assertFalse(result['fallback']);self.assertEqual(result['exit_code'],0)
        self.assertEqual(self.events[0]['event'],'runtime_launching')
        self.assertEqual(self.slots.status()['generation'],before)
        self.assertEqual(self.slots.status()['starts'][0]['status'],'exited')

    def test_corrupt_active_falls_back_and_preserves_business_data(self):
        record=self.core.prepare_inventory(request_id='must-stay-prepared')
        # SQLite mode=ro can create empty WAL and shared-memory index files.
        # Compare every durable file byte and assert any new WAL has no frames.
        before={p.relative_to(self.data):p.read_bytes() for p in self.data.rglob('*')
                if p.is_file() and not p.name.endswith(('-wal','-shm'))}
        self.damage(self.active)
        with patch('jarvis_core.releases.subprocess.run',side_effect=self.process):result=self.start()
        self.assertEqual(self.launches,[self.previous]);self.assertEqual(self.health_calls,[self.previous])
        self.assertTrue(result['fallback']);self.assertTrue(result['selection_committed'])
        self.assertEqual([a['state'] for a in result['attempts']],['failed','verified'])
        state=self.slots.status();self.assertEqual(state['active'],self.previous)
        self.assertEqual(state['history'][0]['operation'],'startup_fallback')
        after={p.relative_to(self.data):p.read_bytes() for p in self.data.rglob('*')
               if p.is_file() and not p.name.endswith(('-wal','-shm'))}
        self.assertEqual(before,after)
        self.assertEqual(record,self.core.ledger.record(record['action']['action_id']))
        self.assertTrue(all(p.stat().st_size==0 for p in self.data.rglob('*-wal')))

    def test_health_timeout_is_bounded_then_previous_is_checked(self):
        def process(command,**kwargs):
            if '-c' in command and Path(kwargs['cwd']).name==self.active:
                raise subprocess.TimeoutExpired(command,60)
            return self.process(command,**kwargs)
        with patch('jarvis_core.releases.subprocess.run',side_effect=process):result=self.start()
        self.assertTrue(result['fallback']);self.assertEqual(self.launches,[self.previous])

    def test_both_bad_preserve_pointer_and_record_failure_without_business_launch(self):
        self.damage(self.active);self.damage(self.previous)
        with patch('jarvis_core.releases.subprocess.run',side_effect=self.process):
            with self.assertRaises(ValueError):self.start()
        self.assertEqual(self.launches,[]);self.assertEqual(self.health_calls,[])
        state=self.slots.status();self.assertEqual(state['active'],self.active)
        self.assertEqual(state['generation'],2)
        self.assertEqual(len(state['starts'][0]['attempts']),2)
        self.assertFalse(state['starts'][0]['selection_committed'])

    def test_no_previous_or_unverified_previous_is_not_guessed(self):
        with self.slots.connection() as db:db.execute('UPDATE selection SET previous=NULL')
        self.damage(self.active)
        with patch('jarvis_core.releases.subprocess.run',side_effect=self.process):
            with self.assertRaises(ValueError):self.start()
        self.assertEqual(len(self.slots.status()['starts'][0]['attempts']),1)
        with self.slots.connection() as db:
            db.execute('UPDATE selection SET previous=?',(self.previous,))
            db.execute("UPDATE releases SET state='installed' WHERE id=?",(self.previous,))
        with patch('jarvis_core.releases.subprocess.run',side_effect=self.process):
            with self.assertRaises(ValueError):self.start()
        self.assertEqual(self.launches,[]);self.assertEqual(self.health_calls,[])

    def test_failed_selection_transaction_never_launches_or_changes_pointer(self):
        self.damage(self.active)
        with self.slots.connection() as db:
            db.execute("CREATE TRIGGER synthetic_start_crash BEFORE INSERT ON history WHEN NEW.operation='startup_fallback' BEGIN SELECT RAISE(ABORT,'test'); END")
        with patch('jarvis_core.releases.subprocess.run',side_effect=self.process):
            with self.assertRaises(sqlite3.IntegrityError):self.start()
        self.assertEqual(self.launches,[]);state=self.slots.status()
        self.assertEqual(state['active'],self.active);self.assertEqual(state['generation'],2)
        self.assertFalse(state['starts'][0]['selection_committed'])

    def test_nonzero_business_exit_or_spawn_failure_does_not_retry(self):
        def failing(command,**kwargs):
            result=self.process(command,**kwargs)
            return result if '-c' in command else subprocess.CompletedProcess(command,37)
        with patch('jarvis_core.releases.subprocess.run',side_effect=failing):result=self.start()
        self.assertEqual(result['exit_code'],37);self.assertEqual(self.launches,[self.active])
        self.assertFalse(result['fallback']);self.assertEqual(self.slots.status()['active'],self.active)
        self.launches.clear()
        def cannot_spawn(command,**kwargs):
            if '-c' not in command:raise OSError('synthetic spawn failure')
            return self.process(command,**kwargs)
        with patch('jarvis_core.releases.subprocess.run',side_effect=cannot_spawn):
            with self.assertRaises(OSError):self.start()
        self.assertEqual(self.launches,[]);self.assertEqual(len(self.slots.status()['starts'][0]['attempts']),1)

    def test_changed_data_version_or_identity_never_triggers_a_downgrade(self):
        for sql in ('PRAGMA user_version=99', "UPDATE control SET config_digest='changed'"):
            db=sqlite3.connect(self.data/'control.db')
            try:
                db.execute('PRAGMA user_version=2');db.execute(sql);db.commit()
            finally:db.close()
            with patch('jarvis_core.releases.subprocess.run',side_effect=self.process):
                with self.assertRaises(ValueError):self.start()
        self.assertEqual(self.health_calls,[]);self.assertEqual(self.launches,[])
        self.assertEqual(self.slots.status()['active'],self.active)

    def test_unknown_release_compatibility_does_not_guess_previous(self):
        unknown=self.install('0.2.0');self.health(unknown,'0.2.0');self.slots.select(unknown)
        with patch('jarvis_core.releases.subprocess.run',side_effect=self.process):
            with self.assertRaises(ValueError):self.start()
        self.assertEqual(self.health_calls,[]);self.assertEqual(self.slots.status()['active'],unknown)

    def test_old_latched_state_is_not_cleared_by_start(self):
        self.core.stop('legacy fixture')
        before=self.core.ledger.control()
        with patch('jarvis_core.releases.subprocess.run',side_effect=self.process):self.start()
        self.assertEqual(before,self.core.ledger.control())

    def test_personal_store_blocks_historical_fallback_and_unknown_schema(self):
        from jarvis_core.persona import PersonaStore
        PersonaStore(self.core).change('preferred_name','小林',request_id='a'*32)
        original=(self.data/'persona.db').read_bytes()
        with patch('jarvis_core.releases.subprocess.run',side_effect=self.process):
            with self.assertRaises(ValueError):self.start()
        self.assertEqual(self.launches,[]);self.assertEqual(self.health_calls,[])
        self.assertEqual((self.data/'persona.db').read_bytes(),original)
        data_format=self.slots._data_format(self.data)
        self.assertTrue(self.slots._compatible('0.1.62',data_format))
        self.assertFalse(self.slots._compatible('0.1.22',data_format))
        db=sqlite3.connect(self.data/'persona.db')
        try:db.execute('PRAGMA user_version=99');db.commit()
        finally:db.close()
        with self.assertRaises(ValueError):self.slots._data_format(self.data)


if __name__=='__main__':unittest.main()
