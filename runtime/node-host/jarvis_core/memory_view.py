"""Request-scoped union of explicit facts and registered project documents.

No new database, extraction model or persistent sharing policy. Callers are the
local owner UI/Host, never model-generated scope. Each route builds a fresh view.
"""
from .knowledge import KnowledgeStore, KnowledgeError, terms, normalized
from .memory import MemoryStore
from .memory_policy import purpose
from .relevance import select_facts


def project_scope(request):
    """Context schemas validate types; this enforces one unambiguous scope."""
    request = request or {}
    current = request.get('project_id')
    projects = request.get('project_ids', [current] if current else [])
    if current and current not in projects:
        raise KnowledgeError('invalid_knowledge', '联合范围必须包含当前项目。')
    return projects if request.get('enabled') else []


class MemoryView:
    def __init__(self, core, *, memory=None, knowledge=None):
        self.memory = memory or MemoryStore(core)
        self.knowledge = knowledge or KnowledgeStore(core)

    def snapshot(self, memory_context, knowledge_context, provider):
        facts = self.memory.view_facts(memory_context, provider)
        sources = self.knowledge.snapshot(knowledge_context, provider)
        return facts, sources

    def context(self, memory_context, provider, facts, sources, query, *, max_bytes, preferred_ids=()):
        # Rank relevant facts before background preferences; ties keep recency.
        # Provider/scope exclusion already happened before candidate scoring.
        ranked = select_facts(facts, query, preferred_ids=preferred_ids)
        memory_budget = min(2048, max_bytes//3) if sources['documents'] else min(6144, max_bytes)
        text, memory = self.memory.context(memory_context, provider, max_bytes=memory_budget, facts=ranked)
        memory['relevance_omitted'] = len(facts)-len(ranked)
        excerpts, knowledge = self.knowledge.context(sources, query, max_bytes=min(8192, max_bytes-memory['bytes']))
        coverage = []
        for project in sources.get('project_ids', []):
            count = sum(c['project_id'] == project for c in knowledge['citations'])
            issues = [i for i in knowledge['issues'] if i.get('project_id') == project]
            coverage.append({'project_id': project, 'citations': count,
                             'status': 'partial' if issues else 'matched' if count else 'no_evidence'})
        report = {'schema_version': 1, 'provider': provider,
                  'purpose': purpose(memory_context),
                  'memory_project_ids': project_scope(memory_context),
                  'knowledge_project_ids': sources.get('project_ids', []),
                  'bytes': memory['bytes']+knowledge['bytes'], 'max_bytes': max_bytes,
                  'coverage': coverage, 'retrieval': 'lexical', 'snapshot_atomic': False}
        return text+excerpts, memory, knowledge, report

    def preview(self, payload):
        from .knowledge import validate
        validate('view', payload)
        request = {'enabled': True, 'project_id': payload['project_id'], 'project_ids': payload['project_ids']}
        memory_request = dict(request, enabled=payload['memory_enabled'])
        facts, sources = self.snapshot(memory_request, request, 'local')
        _, memory, knowledge, report = self.context(memory_request, 'local', facts, sources, payload['query'], max_bytes=14336)
        used = {r['id'] for r in memory['references']}
        return {'view': report, 'memory': memory, 'knowledge': knowledge,
                'facts': [r for r in facts if r['id'] in used]}
