"""Independent purpose policies; configuration is copied into each admitted job."""
import copy

from .. import policy
from . import recipes

PURPOSES = ('inspect', 'heal', 'evolve')
INTERVALS = (300, 900, 1800, 3600, 21600)
FALLBACK_ERRORS = frozenset({'authentication', 'quota_exhausted', 'rate_limited',
                             'model_unavailable', 'provider_unavailable'})


def migrate(value):
    if value.get('schema_version') == 2:
        return value
    return {**value, 'schema_version': 2, 'revision': 0, 'auto_heal': False,
            'models': {name: {'primary': {'route': value['route'], 'reasoning': None},
                              'fallback': None} for name in PURPOSES}}


def purpose(action):
    return 'inspect' if action in ('check', 'analyze') else 'heal' if action in ('heal', 'rollback') else 'evolve'


def validate(payload, current, provider):
    if not isinstance(payload, dict):
        raise policy.CoreError('evolution_request_invalid', '成长设置必须是对象。')
    # Old local clients can still change their three fields. This never grants
    # automatic healing, overwrites other purposes, or drops fallback settings.
    if set(payload) == {'enabled', 'route', 'target_revision'}:
        value = copy.deepcopy(current)
        value.update(payload)
        value['models']['evolve']['primary'] = {'route': payload['route'], 'reasoning': None}
    else:
        fields = {'revision', 'enabled', 'interval_seconds', 'auto_heal', 'target_revision', 'models'}
        if set(payload) != fields:
            raise policy.CoreError('evolution_request_invalid', '成长设置字段不完整或不支持。')
        value = {**copy.deepcopy(payload), 'schema_version': 2}
    if (type(value['revision']) is not int or value['revision'] < 0
            or type(value['enabled']) is not bool or type(value['auto_heal']) is not bool
            or type(value['interval_seconds']) is not int or value['interval_seconds'] not in INTERVALS):
        raise policy.CoreError('evolution_request_invalid', '检查开关、修复开关、间隔或配置版本无效。')
    recipes.specification(value['target_revision'])
    models = value['models']
    if not isinstance(models, dict) or set(models) != set(PURPOSES):
        raise policy.CoreError('evolution_request_invalid', '自检、自愈和进化需要独立模型策略。')
    for item in models.values():
        if not isinstance(item, dict) or set(item) != {'primary', 'fallback'} or item['primary'] is None:
            raise policy.CoreError('evolution_request_invalid', '每种用途需要主模型和可选备选模型。')
        for selection in (item['primary'], item['fallback']):
            if selection is None: continue
            if (not isinstance(selection, dict) or set(selection) != {'route', 'reasoning'}
                    or not isinstance(selection['route'], str)
                    or selection['reasoning'] is not None and not isinstance(selection['reasoning'], str)):
                raise policy.CoreError('evolution_request_invalid', '模型或推理档位无效。')
            provider.configuration(selection['route'], reasoning=selection['reasoning'])
        if item['primary'] == item['fallback']:
            raise policy.CoreError('evolution_request_invalid', '备选不能与主模型及档位完全相同。')
    value['route'] = models['evolve']['primary']['route']
    return value


def can_fallback(receipt):
    return (receipt.get('status') == 'FAILED' and not receipt.get('outcome_uncertain')
            and not receipt.get('output_incomplete') and receipt.get('error_category') in FALLBACK_ERRORS)
