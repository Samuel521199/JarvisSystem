"""Seed status is evidence, never an authorization or an extension loader."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'adapters/models/provider-native')]
from jarvis_core.runtime_catalog import RuntimeCatalog, MANIFEST, ASSETS
from jarvis_core.chat import ChatService
from jarvis_core.service import CoreService


class RuntimeCatalogTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(); self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        for name in (MANIFEST, *ASSETS):
            target=self.root/name;target.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(ROOT/name,target)
        (self.root/'input').mkdir()
        self.core=CoreService(self.root/'data');self.core.initialize(self.root/'input')
        self.catalog=RuntimeCatalog(self.core,root=self.root)

    def test_valid_seed_has_provenance_but_no_chat_executors(self):
        result=self.catalog.snapshot()
        self.assertEqual(result['status'],'ready')
        self.assertEqual(len(result['knowledge']),5)
        self.assertEqual(len(result['skills']),4)
        states={c['id']:c['status'] for c in result['capabilities']}
        self.assertEqual(states,{'system.status.v1':'available','filesystem.read_sample.v1':'conditional',
                               'artifact.write.v1':'internal','build.candidate.v1':'planned'})
        self.assertTrue(all(not c['chat_callable'] for c in result['capabilities']))
        self.assertTrue(all(c['source'] and c['digest'] for c in result['capabilities']))

    def test_corruption_removal_and_manifest_self_rehash_never_reuse_valid_snapshot(self):
        self.assertEqual(self.catalog.snapshot()['status'],'ready')
        path=self.root/ASSETS[0];path.write_text('tampered',encoding='utf-8')
        invalid=self.catalog.snapshot()
        self.assertEqual(invalid['status'],'unavailable');self.assertEqual(invalid['knowledge'],[])
        from jarvis_core.policy import digest
        path=self.root/MANIFEST;manifest=json.loads(path.read_text())
        for asset in manifest['assets']:
            if asset['path']==ASSETS[0]:asset['sha256']=digest(b'tampered')
        path.write_text(json.dumps(manifest))
        self.assertEqual(self.catalog.snapshot()['status'],'unavailable')
        path.unlink();self.assertEqual(self.catalog.snapshot()['capabilities'],[])

    def test_link_and_oversize_rejected_without_opening_extra_files(self):
        target=self.root/ASSETS[0];target.unlink()
        other=self.root/'outside.json';other.write_bytes((ROOT/ASSETS[0]).read_bytes())
        os.link(other,target)
        self.assertEqual(self.catalog.snapshot()['status'],'unavailable')
        target.unlink();target.write_bytes(b'x'*65537)
        self.assertEqual(self.catalog.snapshot()['status'],'unavailable')

    def test_stopped_core_only_reports_unavailable_without_mutation(self):
        with patch.object(self.core,'assert_running',side_effect=RuntimeError('private error')):
            result=self.catalog.snapshot()
        states={c['status'] for c in result['capabilities']}
        self.assertEqual(states,{'planned','unavailable'})
        self.assertNotIn('private error',json.dumps(result))

    def test_chat_reads_fresh_status_but_never_exports_local_seed_body(self):
        chat=ChatService(self.core);chat.runtime_catalog=self.catalog
        with patch('jarvis_core.chat.gateway.probe',return_value={
                'status':'SUCCEEDED','text':'answer','outcome_uncertain':False}) as probe:
            self.assertEqual(chat.reply('hello',provider='vertex')['status'],'SUCCEEDED')
            instructions=probe.call_args.kwargs['instructions']
            self.assertIn('Seed catalog: ready',instructions)
            for row in self.catalog.snapshot()['knowledge']:
                self.assertNotIn(row['content'],instructions)
            (self.root/ASSETS[1]).write_bytes(b'broken')
            self.assertEqual(chat.reply('hello',provider='vertex')['status'],'SUCCEEDED')
            self.assertIn('Seed catalog: unavailable',probe.call_args.kwargs['instructions'])
            self.assertNotIn(str(self.root),instructions)


if __name__=='__main__':unittest.main()
