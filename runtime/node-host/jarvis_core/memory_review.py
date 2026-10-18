"""Signed review of edited semantic candidates; facts remain in MemoryStore."""
import hashlib
import time
import uuid

from .memory import MemoryStore, fail
from .memory_comparison import compare
from .semantic_candidates import encoded, TTL


class MemoryReview:
    def __init__(self, semantic):
        self.semantic = semantic
        self.store = MemoryStore(semantic.core)

    def review(self, payload):
        draft, item, doc, origin = self.semantic.prepare_confirmation(payload)
        if self.store.review_revision() != draft['review_revision']:
            fail('candidate_review_changed', '记忆已被修改或忘记，请重新整理；当前编辑没有保存。')
        facts = self.store.list(project_id=doc['project_id'])['facts'] if self.store.path.exists() else []
        result = compare(doc, item['quote'], facts)
        if self.store.review_revision() != draft['review_revision']:
            fail('candidate_review_changed', '核对期间记忆发生变化，请重新整理。')
        targets = [{k: row[k] for k in ('id', 'revision', 'relation')} | {
            'digest': hashlib.sha256(encoded(row['document'])).hexdigest()} for row in result['matches']]
        token = self.semantic.sign({'purpose': 'memory-review-v1', 'document': doc, 'origin': origin,
            'targets': targets, 'review_revision': draft['review_revision'],
            'expires': min(draft['expires'], int(time.time()) + TTL)})
        return {**result, 'review_token': token, 'committed': False}

    def resolve(self, payload):
        if not isinstance(payload, dict) or set(payload) != {'review_token', 'decision', 'target_id'}:
            fail('invalid_candidate', '记忆核对操作字段无效。')
        draft = self.semantic.open_token(payload['review_token'])
        if draft.get('purpose') != 'memory-review-v1' or payload['decision'] not in ('new', 'keep', 'replace'):
            fail('invalid_candidate', '记忆核对操作无效。')
        target = None
        if payload['decision'] == 'new':
            if payload['target_id'] is not None: fail('invalid_candidate', '新记忆不能指定旧目标。')
        else:
            targets = [t for t in draft['targets'] if t['id'] == payload['target_id']]
            if len(targets) != 1: fail('invalid_candidate', '只能选择本次核对列出的记忆。')
            target = targets[0]
            if payload['decision'] == 'keep' and target['relation'] not in ('duplicate', 'unclassified'):
                fail('invalid_candidate', '不同内容不能按完全重复处理。')
            if payload['decision'] == 'replace' and target['relation'] in ('duplicate', 'unclassified'):
                fail('invalid_candidate', '相同或未分类记录不能直接替代，请核对记忆面板。')
            target = {k: target[k] for k in ('id', 'revision', 'digest')} | {'mode': payload['decision']}
        doc = draft['document']
        ident = {'document': doc, 'origin': {k: v for k, v in draft['origin'].items() if k != 'archive_revision'},
                 'decision': payload['decision'], 'target': target}
        receipt = self.store.command('remember', doc['title'], doc['content'], project_id=doc['project_id'],
            classification=doc['classification'], candidate_source=draft['origin'],
            candidate_review_revision=draft['review_revision'], candidate_target=target, candidate_deduplicate=True,
            request_id=uuid.uuid5(uuid.NAMESPACE_URL, 'memory-review-v1'+encoded(ident).decode()).hex)
        texts = {'new': '已保存新记忆，默认仅本地使用。',
                 'keep': '已沿用已有记忆，没有新增或改写事实，保留原用途和权限。',
                 'replace': '已更新这条记忆的内容和来源，保留原名称、分类、用途及接入方权限。'}
        return {'receipt': receipt, 'text': '此确认已处理，请在记忆面板核对。' if receipt['replayed'] else texts[payload['decision']]}
