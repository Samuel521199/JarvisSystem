"""Deterministic contract observations; never infer independent expectations."""
from .catalog import encoded, fail


def inspect_contract(public, heldout, retained=()):
    seen = {}; overlaps = 0; conflicts = 0; duplicates = 0; flags = set(); kinds = set(); outputs = set()
    def visit(value):
        kinds.add(type(value).__name__)
        if value in (None, '', [], {}): flags.add('empty_or_null')
        if type(value) in (int, float):
            if value == 0: flags.add('zero')
            if value < 0: flags.add('negative')
        if isinstance(value, str) and any(ord(c) > 127 for c in value): flags.add('unicode')
        if isinstance(value, (list, dict)):
            if len(value) == 1: flags.add('singleton')
            for child in (value.values() if isinstance(value, dict) else value): visit(child)
    for group, cases in (('retained',retained),('public',public),('heldout',heldout)):
        for case in cases:
            key = encoded(case['input']); expected = case['expected']
            if key in seen:
                conflicts += seen[key][1] != expected
                overlaps += group == 'heldout' and seen[key][0] == 'public'
                duplicates += group!='retained' and seen[key][0]==group
            seen[key] = (group, expected); outputs.add(expected); visit(case['input'])
    blockers = []
    if conflicts: blockers.append('相同输入存在矛盾预期，不能通过改写旧契约解决。')
    if overlaps: blockers.append('公开输入与独立留出输入重合，不能作为独立留出。')
    if duplicates: blockers.append('同组验收输入重复，不能虚增案例数量。')
    if not public or not heldout: blockers.append('缺少公开或独立留出案例。')
    questions = ['请独立核对单位、精度、顺序、格式和不适用输入；本检查不能判断业务预期正确。']
    if len(outputs) <= 1: questions.append('所有预期相同：请核对是否遗漏能区分正确/错误实现的输入。')
    if 'empty_or_null' not in flags: questions.append('未观察到空值/空集合样本；请核对它是否属于用途边界。')
    if 'negative' not in flags and kinds & {'int','float'}: questions.append('未观察到负数；请核对数值域与边界。')
    return {'structurally_consistent':not blockers,'semantic_truth_verified':False,'model_calls':0,
            'public_cases':len(public),'heldout_cases':len(heldout),'retained_cases':len(retained),
            'distinct_inputs':len(seen),'distinct_outputs':len(outputs),'observed_types':sorted(kinds),
            'observed_features':sorted(flags),'blockers':blockers,'review_questions':questions,
            'basis':'只检查来源分组、案例一致性和已观察形状，不自动创造预期或给通用契约质量打分。'}


def require_consistent(report):
    if not report['structurally_consistent']: fail('；'.join(report['blockers']))
