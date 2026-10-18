"""Bounded local review hints. No model, vector index or authority to edit facts."""
import re
import unicodedata

CHANGE = re.compile(r'改成|改为|不再|偏好变|以前.{0,50}现在|原来.{0,50}现在')
ASSISTANT = re.compile(r'你(?:刚才|之前|先前)?(?:说|猜|认为|推测)|助手.{0,8}(?:说|猜)|AI.{0,8}(?:说|猜)', re.I)
REJECT = re.compile(r'猜错|猜测|推测|没有说过|没说过|没告诉|没有透露|从未透露|没有提供|并未提供|不要猜|别猜')
ASSERTION = re.compile(r'我(?:其实|实际|现在|目前|真正|并|确实)?(?:不)?(?:住在|居住|叫|是|喜欢|偏好|从事)|其实.{0,12}(?:是|喜欢)|不是.{1,20}[，,]是')


def correction_only(text):
    """Narrow observed correction-of-assistant pattern, not general negation."""
    match = ASSISTANT.search(text)
    if not match or not REJECT.search(text):
        return False
    # A fresh first-person assertion after the quoted/attributed guess is evidence
    # in its own right. Never classify 'I don't like sugar' as an empty correction.
    if ASSERTION.search(text[:match.start()]):
        return False
    tail = re.split(r'[，,；;。]', text[match.start():], maxsplit=1)
    rejection = REJECT.search(text, match.start())
    return not ASSERTION.search((tail[1] if len(tail) > 1 else '') + text[rejection.end():])


def body(document):
    text = unicodedata.normalize('NFKC', document['content']).strip().rstrip('。.!！;；')
    if (document.get('classification') or {}).get('subject') == 'owner':
        text = re.sub(r'^(?:用户|主人|本人|我|User\b)\s*', '', text)
    return re.sub(r'\s+', ' ', text)


def same_subject(a, b):
    x, y = a.get('classification'), b.get('classification')
    return bool(x and y and all(x[k] == y[k] for k in ('kind', 'subject', 'subject_label')))


def duplicate(a, b):
    return a['project_id'] == b['project_id'] and same_subject(a, b) and body(a) == body(b)


def topic(document):
    kind = document['classification']['kind']
    text = document['title'] + document['content']
    if kind == 'preference':
        if re.search(r'茶|咖啡|饮品|饮料|可乐', text): return 'drink'
        if re.search(r'回答|回复|答复|结论', text) and re.search(r'简短|简洁|详细|长篇|精简', text): return 'answer_style'
    if kind == 'personal_fact' and re.search(r'称呼|叫我|名字|名叫', text): return 'name'
    return None


def compare(document, quote, facts):
    matches = []; skipped = 0
    for row in facts:
        old = row['document']
        if old['project_id'] != document['project_id']: continue
        if row.get('provenance', {}).get('state', 'independent') not in {'independent', 'current'}:
            skipped += 1; continue
        if not same_subject(document, old):
            if old.get('classification') is None and document['content'].strip() == old['content'].strip():
                relation, reason, rank = 'unclassified', '内容相同，但旧记忆未分类；不能推断主体或直接更新。', 2
            else: continue
        elif duplicate(document, old):
            relation, reason, rank = 'duplicate', '同范围、同类型和主体，正文仅有称谓或末尾标点差别。', 0
        else:
            new, previous = body(document), body(old)
            shared_topic = topic(document) is not None and topic(document) == topic(old)
            pairs = lambda text: {text[i:i+2] for i in range(len(text)-1)}
            a, b = pairs(new), pairs(previous)
            overlap = len(a & b) / max(1, len(a | b))
            if not (shared_topic or document['title'] == old['title'] or overlap >= .5): continue
            if CHANGE.search(quote):
                relation, reason = 'possible_change', '原句含变化表达，且与旧记忆主题或用词接近；请判断是否替代。'
            elif min(len(new), len(previous)) >= 6 and (new in previous or previous in new):
                relation, reason = 'possible_addition', '正文有包含关系，可能补充，也可能改变含义；不会自动合并。'
            else:
                relation, reason = 'related', '名称、主题或用词接近，尚不能判断重复或矛盾。'
            rank = 1
        matches.append({'id': row['id'], 'revision': row['revision'], 'document': old,
                        'provenance': row.get('provenance'), 'relation': relation, 'reason': reason, '_rank': rank})
    matches.sort(key=lambda row: (row['_rank'], row['id']))
    total = len(matches)
    for row in matches: row.pop('_rank')
    return {'matches': matches[:5], 'total_matches': total, 'truncated': total > 5,
            'source_unusable': skipped, 'method': 'local_rules_v1', 'model_used': False,
            'note': '只比对目标范围中的已分类同主体记录；词项提示不证明语义相同。未分类记录只提示完全相同正文。'}
