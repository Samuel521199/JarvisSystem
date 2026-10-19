"""Bounded lexical ranking shared by facts and explicit topic suggestions.

No network, model or write. Eligibility and provenance must be checked first.
This is a transparent recall baseline, not semantic similarity.
"""
from .knowledge import normalized, terms

STOP = frozenset(('什么','可以','一下','怎么','帮我','请问','知道','这个','我们','我的','一个','现在','然后','还是','之前','最近'))
BACKGROUND_TITLES = frozenset(('语言偏好','回复偏好','回复风格','交流风格','回答风格','preferred language','response style'))
TOPICS = (('饮品','饮食偏好','喝水','喝点','喝什么','口渴','饮料','茶','咖啡','普洱','正山小种','金骏眉','白开水','drink','thirsty'),
          ('晚饭','晚餐','dinner'), ('早餐','早饭','breakfast'), ('英语','英文','english'))


def tokens(value):
    result = set(terms(value)) - STOP
    value = normalized(value)
    for index, group in enumerate(TOPICS):
        if any(word in value for word in group): result.add('topic:'+str(index))
    return result


def score(query, title, body):
    words=tokens(query)
    return 3*len(words & tokens(title)) + len(words & tokens(body))


def followup_ids(query, references):
    # Only explicit short anaphora; no arbitrary historical text is searched or
    # promoted to instructions. Current scope/provider filtering still wins.
    if normalized(query).rstrip('。？！.!?') not in {'继续','然后呢','接着说','按现在的偏好回答','请按现在的偏好回答','continue','go on'}:
        return set()
    for refs in reversed(references[-4:]):
        if refs: return {ref['id'] for ref in refs[:3]}
    return set()


def select_facts(facts, query, *, preferred_ids=()):
    ranked=[]
    for row in facts:
        doc=row['document']; relevance=score(query,doc['title'],doc['content'])
        background=doc['project_id'] is None and normalized(doc['title']) in BACKGROUND_TITLES
        if relevance or background or row['id'] in preferred_ids: ranked.append((relevance,row))
    ranked.sort(key=lambda value:-value[0])
    return [row for _,row in ranked]
