"""Union scope, destination filtering, bounded reads and source freshness."""
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService
from jarvis_core.memory_view import MemoryView
from jarvis_core.knowledge import KnowledgeError, validate
from jarvis_core.chat import ChatService
from jarvis_core.conversations import validate_document


class MemoryViewTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name); self.sample = self.base/'sample'; self.sample.mkdir()
        self.core = CoreService(self.base/'data'); self.core.initialize(self.sample)
        self.view = MemoryView(self.core); self.ids = []; self.files = []; self.sources = []; self.facts = []
        for name in ('alpha', 'beta', 'excluded'):
            folder = self.base/name; folder.mkdir(); file = folder/'design.md'
            file.write_text('# 登录设计\n'+name+' 登录方案采用 '+name+'协议。\n', encoding='utf-8')
            project = WorkspaceService(self.core).open_project({'path': str(folder)})['id']
            source = uuid.uuid4().hex; fact = uuid.uuid4().hex
            self.view.knowledge.put(source, {'revision': 0, 'document': {'project_id': project, 'path': 'design.md', 'providers': ['vertex']}})
            self.view.memory.put(fact, {'revision': 0, 'document': {'project_id': project, 'title': '登录决定', 'content': name+' FACT', 'providers': ['vertex']}})
            self.ids.append(project); self.files.append(file); self.sources.append(source); self.facts.append(fact)
        self.global_id = uuid.uuid4().hex
        self.view.memory.put(self.global_id, {'revision': 0, 'document': {'project_id': None, 'title': '语言偏好', 'content': '使用中文', 'providers': ['vertex']}})
        self.ctx = {'enabled': True, 'project_id': self.ids[0], 'project_ids': self.ids[:2]}

    def query(self, provider='vertex', budget=14000):
        facts, sources = self.view.snapshot(self.ctx, self.ctx, provider)
        return self.view.context(self.ctx, provider, facts, sources, '比较登录设计', max_bytes=budget)

    def test_union_has_both_projects_and_one_global_preference(self):
        text, memory, knowledge, view = self.query()
        self.assertIn('alpha协议', text); self.assertIn('beta协议', text); self.assertNotIn('excluded', text)
        self.assertEqual(text.count('使用中文'), 1)
        self.assertEqual(len(memory['references']), 3)
        self.assertEqual({c['project_id'] for c in knowledge['citations']}, set(self.ids[:2]))
        self.assertEqual([c['status'] for c in view['coverage']], ['matched', 'matched'])
        self.assertLessEqual(view['bytes'], view['max_bytes'])
        validate('citations', knowledge['citations'])

    def test_destination_exclusion_precedes_file_read_and_fact_ranking(self):
        with patch.object(self.view.knowledge, 'read_file', side_effect=AssertionError('private read')):
            text, memory, knowledge, report = self.query('openai')
        self.assertEqual(text, ''); self.assertEqual(memory['available'], 0)
        self.assertFalse(knowledge['references']); self.assertEqual(report['coverage'][0]['status'], 'no_evidence')

    def test_unknown_duplicate_oversized_and_ambiguous_scope_rejected(self):
        for ids in ([uuid.uuid4().hex], [self.ids[0]]*2, [uuid.uuid4().hex for _ in range(5)], [self.ids[1]], [self.ids[0],uuid.uuid4().hex]):
            with self.subTest(ids=ids), self.assertRaises((KnowledgeError, ValueError)):
                self.view.snapshot(dict(self.ctx, project_ids=ids), dict(self.ctx, project_ids=ids), 'local')

    def test_shared_read_budget_and_per_project_coverage(self):
        sizes = []
        original = self.view.knowledge.read_file
        def read(*args):
            result = original(*args); sizes.append(result['bytes']); return result
        with patch('jarvis_core.knowledge.MAX_READ_BYTES', 256*1024), patch.object(self.view.knowledge, 'read_file', side_effect=read):
            _, _, knowledge, report = self.query()
        self.assertEqual(len(sizes), 1); self.assertEqual(knowledge['read_bytes'], sum(sizes))
        self.assertEqual(report['coverage'][1]['status'], 'partial')
        self.assertEqual(self.query(budget=40)[0], '')

    def test_revocation_during_read_does_not_leave_excerpt(self):
        original = self.view.knowledge.read_file
        def read(root, path):
            result = original(root, path)
            if root.name == 'alpha':
                self.view.knowledge.delete(self.sources[0], {'revision': 1})
            return result
        with patch.object(self.view.knowledge, 'read_file', side_effect=read):
            text, _, knowledge, report = self.query()
        self.assertNotIn('alpha协议', text); self.assertIn('beta协议', text)
        self.assertEqual(report['coverage'][0]['status'], 'partial')
        self.assertTrue(any(i['code']=='source_changed' for i in knowledge['issues']))

    def test_missing_file_is_reported_without_suppressing_other_project(self):
        self.files[0].unlink()
        text, _, _, report = self.query()
        self.assertIn('beta协议', text); self.assertNotIn('alpha协议', text)
        self.assertEqual(report['coverage'][0]['status'], 'partial')

    def test_citation_targets_original_project_and_survives_archive(self):
        _, _, info, _ = self.query()
        citation = next(c for c in info['citations'] if c['project_id']==self.ids[1])
        result = self.view.knowledge.read_excerpt({k:citation[k] for k in ('project_id','reference','start_line','end_line')})
        self.assertIn('beta协议', result['text'])
        row = {'role':'assistant','content':'answer','meta':'','short_meta':'','attachments_omitted':False,'incomplete':False,'knowledge_refs':info['references'],'knowledge_citations':info['citations']}
        validate_document({'title':'compare','project_id':self.ids[0],'context_note':'','messages':[row]})
        self.files[1].write_text('new login', encoding='utf-8')
        with self.assertRaises(KnowledgeError):
            self.view.knowledge.read_excerpt({k:citation[k] for k in ('project_id','reference','start_line','end_line')})

    def chat(self):
        config = json.loads((ROOT/'config/model-profiles/providers.json').read_text(encoding='utf-8'))
        config.update(default_provider='vertex', automatic_fallback=True, fallback_order=['openai'])
        path = self.base/'providers.json'; path.write_text(json.dumps(config),encoding='utf-8')
        return ChatService(self.core,path)

    def test_route_fallback_rebuilds_union_and_removes_derived_history(self):
        _, memory, knowledge, _ = self.query(); calls = []
        def probe(config, provider, message, *args, **kwargs):
            calls.append((message, kwargs['history']))
            return {'status':'FAILED','error_category':'quota_exhausted','outcome_uncertain':False} if provider=='vertex' else {'status':'SUCCEEDED','text':'ok','outcome_uncertain':False}
        with patch('jarvis_core.chat.gateway.probe',side_effect=probe):
            result = self.chat().reply('比较登录设计',memory_context=self.ctx,knowledge_context=self.ctx,
                history=[{'role':'user','content':'old'},{'role':'assistant','content':'DERIVED_SECRET'}],
                history_memory=[[],memory['references']],history_knowledge=[[],knowledge['references']])
        self.assertEqual(result['status'],'SUCCEEDED'); self.assertIn('beta协议',calls[0][0])
        self.assertNotIn('beta协议',calls[1][0]); self.assertEqual(calls[1][1],[])
        self.assertEqual(result['history_info']['memory_view']['provider'],'openai')

    def test_scope_shrink_and_fact_correction_drop_dependent_turn(self):
        _, memory, knowledge, _ = self.query()
        options = dict(history=[{'role':'user','content':'old'},{'role':'assistant','content':'DERIVED_SECRET'}],history_memory=[[],memory['references']],history_knowledge=[[],knowledge['references']])
        single = dict(self.ctx, project_ids=self.ids[:1])
        with patch('jarvis_core.chat.gateway.probe',return_value={'status':'SUCCEEDED','text':'ok','outcome_uncertain':False}) as gateway:
            result = self.chat().reply('登录',provider='vertex',memory_context=single,knowledge_context=single,**options)
        self.assertEqual(gateway.call_args.kwargs['history'],[])
        self.view.memory.delete(self.global_id, {'revision':1})
        with patch('jarvis_core.chat.gateway.probe',return_value={'status':'SUCCEEDED','text':'ok','outcome_uncertain':False}) as gateway:
            self.chat().reply('登录',provider='vertex',memory_context=self.ctx,knowledge_context=self.ctx,**options)
        self.assertEqual(gateway.call_args.kwargs['history'],[])

    def test_disabled_view_never_reads_and_preview_does_not_mutate_sharing(self):
        disabled = dict(self.ctx, enabled=False)
        with patch.object(self.view.memory,'connection',side_effect=AssertionError('fact read')), patch.object(self.view.knowledge,'read_file',side_effect=AssertionError('file read')):
            facts, sources = self.view.snapshot(disabled,disabled,'local')
        self.assertFalse(facts); self.assertFalse(sources['documents'])
        before = self.view.knowledge.list(self.ids[1])
        result = self.view.preview({'project_id':self.ids[0],'project_ids':self.ids[:2],'query':'登录','memory_enabled':True})
        self.assertEqual(result['view']['provider'],'local'); self.assertEqual(len(result['facts']),3)
        self.assertEqual(before,self.view.knowledge.list(self.ids[1]))


if __name__ == '__main__': unittest.main()
