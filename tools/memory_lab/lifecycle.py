"""Offline multi-turn replay against the real candidate, fact and context stores.

The supplied model responses are fixtures, not an extraction-quality evaluation.
Each scenario has its own temporary core; no production data or model is opened.
"""
from copy import deepcopy
import json
from pathlib import Path
import sys
import uuid

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'runtime/node-host'))
from jarvis_core.conversations import ConversationStore
from jarvis_core.memory import MemoryError, MemoryStore
from jarvis_core.personal_candidates import PersonalCandidates
from jarvis_core.semantic_candidates import SemanticCandidates
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService


class FixtureChat:
    def __init__(self):
        self.answer = []
        self.during = None
        self.calls = 0

    def reply(self, prompt, **kwargs):
        assert kwargs['_purpose'] == 'memory_candidates'
        assert kwargs['_route_attempt_limit'] == 1
        self.calls += 1
        if self.during:
            self.during()
        return {'status': 'SUCCEEDED', 'provider': 'local', 'model': 'lifecycle-fixture',
                'text': json.dumps({'candidates': self.answer}, ensure_ascii=False),
                'usage': {'fixture': True}}


class Replay:
    def __init__(self, directory):
        self.base = Path(directory)
        source = self.base / 'source'
        source.mkdir()
        self.core = CoreService(self.base / 'data')
        self.core.initialize(source)
        self.projects, self.sources, self.previews, self.facts, self.snapshots = {}, {}, {}, {}, {}
        self.events = []
        self.chat = FixtureChat()
        self._services()

    def _services(self):
        self.memory = MemoryStore(self.core)
        self.archives = ConversationStore(self.core)
        self.semantic = SemanticCandidates(self.core, self.chat)

    def project(self, name):
        if name is None:
            return None
        if name not in self.projects:
            directory = self.base / ('project-' + str(len(self.projects)))
            directory.mkdir()
            self.projects[name] = WorkspaceService(self.core).open_project({'path': str(directory)})['id']
        return self.projects[name]

    def row(self, name):
        # Tests may inspect all rows; production retrieval still uses its own filters.
        with self.memory.connection() as db:
            row = db.execute('SELECT * FROM facts WHERE id=? AND deleted=0', (self.facts[name],)).fetchone()
            assert row is not None, f'Missing fact: {name}'
            return self.memory._public(row)

    def request(self, step):
        return {'enabled': True, 'project_id': self.project(step.get('project')),
                'purpose': step.get('purpose', 'personal_chat')}

    def step(self, step):
        expected_error = step.get('error')
        try:
            result = self._step(step)
        except MemoryError as error:
            if error.code != expected_error:
                raise AssertionError(f"{step['op']}: expected {expected_error!r}, got {error.code!r}") from error
            self.events.append({'op': step['op'], 'error': error.code})
            return
        if expected_error:
            raise AssertionError(f"{step['op']}: expected rejection {expected_error!r}, but succeeded")
        self.events.append({'op': step['op'], **(result or {})})

    def _step(self, s):
        op = s['op']
        if op == 'source':
            cid = uuid.uuid4().hex
            project = self.project(s.get('project'))
            document = {'title': '合成多轮记忆验证', 'project_id': project, 'context_note': '',
                        'messages': [{'role': 'user', 'content': s['text'], 'meta': '', 'short_meta': '',
                                      'attachments_omitted': False, 'incomplete': False}]}
            self.archives.put(cid, {'revision': 0, 'document': document})
            self.sources[s['name']] = {'source': {'conversation_id': cid, 'message_index': 0}, 'project_id': project}
        elif op == 'preview':
            self.chat.answer = deepcopy(s['candidates'])
            self.chat.during = (lambda: self.step(s['during'])) if s.get('during') else None
            try:
                result = self.semantic.suggest({**self.sources[s['source']], 'provider': 'local',
                    'model': 'lifecycle-fixture', 'reasoning': None, 'request_id': uuid.uuid4().hex})
            finally:
                self.chat.during = None
            self.previews[s['name']] = result
            if s.get('result_error'):
                assert result['result']['status'] == 'FAILED'
                assert result['result']['error_category'] == s['result_error']
                assert result['candidates'] == [] and 'preview_token' not in result
                assert result['result']['usage'] == {'fixture': True}, 'Lost call receipt'
            else:
                assert result['result']['status'] == 'SUCCEEDED', result['result']
                assert len(result['candidates']) == len(s['candidates'])
            return {'candidates': len(result['candidates']), 'result_error': s.get('result_error')}
        elif op == 'confirm':
            preview = self.previews[s['preview']]
            candidate = preview['candidates'][s.get('index', 0)]
            payload = {k: deepcopy(candidate[k]) for k in ('candidate_id', 'title', 'content', 'classification')}
            payload.update(s.get('edit', {}))
            result = self.semantic.confirm({**payload, 'preview_token': preview['preview_token'], 'scope': s.get('scope', 'current')})
            if 'replayed' in s:
                assert result['receipt']['replayed'] == s['replayed']
            if 'name' in s:
                self.facts[s['name']] = result['receipt']['id']
            return {'replayed': result['receipt']['replayed']}
        elif op == 'rule_confirm':
            service = PersonalCandidates(self.core)
            preview = service.suggest(self.sources[s['source']])
            candidate = preview['candidates'][s.get('index', 0)]
            service.confirm({**{k: preview[k] for k in ('source', 'project_id', 'source_digest')},
                             'candidate': candidate, 'scope': 'current'})
        elif op == 'remember':
            receipt = self.memory.command('remember', s['title'], s['content'],
                project_id=self.project(s.get('project')), request_id=uuid.uuid4().hex)
            self.facts[s['name']] = receipt['id']
        elif op in ('correct', 'permit', 'classify', 'reaffirm'):
            row = self.row(s['fact'])
            document = deepcopy(row['document'])
            if op == 'correct':
                document['content'] = s['content']
            elif op == 'permit':
                document['providers'] = s['providers']
            elif op == 'classify':
                document['classification'].update(s['patch'])
            self.memory.put(row['id'], {'revision': row['revision'], 'document': document,
                                       **({'reaffirm_source': True} if op == 'reaffirm' else {})})
        elif op == 'forget':
            row = self.row(s['fact'])
            self.memory.delete(row['id'], {'revision': row['revision']})
        elif op in ('edit_source', 'delete_source'):
            cid = self.sources[s['source']]['source']['conversation_id']
            row = self.archives.get(cid)
            if op == 'edit_source':
                row['document']['messages'][0]['content'] = s['text']
                self.archives.put(cid, {'revision': row['revision'], 'document': row['document']})
            else:
                self.archives.delete(cid, {'revision': row['revision']})
        elif op == 'snapshot':
            self.snapshots[s['name']] = self.memory.view_facts(self.request(s), s.get('provider', 'local'))
        elif op == 'context':
            text, report = self.memory.context(self.request(s), s.get('provider', 'local'),
                facts=self.snapshots[s['snapshot']] if 'snapshot' in s else None)
            actual = {r['id'] for r in report['references']}
            expected = {self.facts[name] for name in s['facts']}
            assert actual == expected, f"Context leaked or lost facts: expected {s['facts']}, got {len(actual)}"
            for value in s.get('contains', []):
                assert value in text, f'Missing current content: {value}'
            for value in s.get('excludes', []):
                assert value not in text, f'Stale content in context: {value}'
            return {'fact_count': len(actual)}
        elif op == 'state':
            with self.memory.connection() as db:
                count = db.execute('SELECT count(*) FROM facts WHERE deleted=0').fetchone()[0]
                assert count == s['facts'], (count, s['facts'])
                if s.get('forgotten_body_cleared'):
                    assert db.execute('SELECT count(*) FROM facts WHERE deleted=1 AND (document IS NOT NULL OR search_text IS NOT NULL OR digest IS NOT NULL)').fetchone()[0] == 0
            if 'review_revision' in s:
                assert self.memory.review_revision() == s['review_revision']
        elif op == 'restart':
            self.core = CoreService(self.base / 'data')
            self._services()
        else:
            raise ValueError(f'Unknown replay operation: {op}')


def load_cases(path):
    raw = Path(path).read_bytes()
    if len(raw) > 256 * 1024:
        raise ValueError('Lifecycle corpus exceeds 256 KiB')
    document = json.loads(raw)
    assert document['schema'] == 'memory-lifecycle-pilot-v1'
    cases = document['cases']
    assert 1 <= len(cases) <= 32
    assert len({c['id'] for c in cases}) == len(cases)
    for case in cases:
        assert 1 <= len(case['steps']) <= 80
    return document
