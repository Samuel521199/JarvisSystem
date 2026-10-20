"""Reserve each planned model call before transport using the configured price.

These are conservative price-table estimates, not a provider invoice guarantee.
Unknown prices, image inputs and opaque external executors are not budgetable.
"""
import json
import math
from contextvars import ContextVar
from datetime import date
from pathlib import Path
import sqlite3

from . import policy
from .assistant_plan_store import connection, read

current_task = ContextVar('assistant_plan_task', default=None)


def reserve(data_dir, request_id, item, provider, input_bytes, output_tokens, *, images=0, task_id=None):
    task_id = task_id or current_task.get()
    if not task_id or not (Path(data_dir) / 'assistant-plans.db').exists(): return
    # Resolve the immutable request key without opening/initializing another Host.
    from .assistant_plans import task_request_key
    key = task_request_key(data_dir, task_id)
    with connection(data_dir, write=True) as db:
        plan = None
        for row in db.execute('SELECT document FROM plans'):
            value = json.loads(row[0])
            if any(s['request_id'] == key for s in value['steps']):
                plan = value
                break
        if plan is None: return
        if plan['state'] != 'ACTIVE':
            raise policy.CoreError('plan_paused', '计划已暂停或撤回，未派发新的模型请求。')
        budget = db.execute('SELECT * FROM plan_budget WHERE plan_id=?', (plan['id'],)).fetchone()
        if budget is None: raise policy.CoreError('plan_budget', '计划预算未授权。')
        if db.execute('SELECT 1 FROM plan_calls WHERE request_id=?', (request_id,)).fetchone():
            raise policy.CoreError('plan_budget', '模型请求已经预留，不能重复派发。')
        prior = db.execute('SELECT currency,reserved FROM plan_calls WHERE plan_id=?', (plan['id'],)).fetchall()
        if len(prior) >= budget['max_calls']:
            raise policy.CoreError('plan_budget', '计划模型调用次数已用完。')
        amount, currency = 0., 'USD'
        if item.get('adapter', provider) != 'local':
            price = item.get('price') or {}
            currency = price.get('currency')
            if (images or currency not in ('USD', 'CNY') or
                    any(type(price.get(k)) not in (int, float) or not math.isfinite(price[k]) or price[k] < 0
                        for k in ('input', 'output')) or
                    (price.get('valid_until') and price['valid_until'] < date.today().isoformat())):
                raise policy.CoreError('plan_unpriced', '模型价格未知、过期或含图片，不能在计划预算内自动派发。')
            # UTF-8 bytes is a deliberately conservative text-token allowance.
            # Reserve a separate reasoning allowance as well; receipts retain actual usage.
            token_bound = input_bytes + 4096
            if price.get('max_input_tokens') and token_bound > price['max_input_tokens']:
                raise policy.CoreError('plan_unpriced', '输入超出当前价表适用层级。')
            amount = (token_bound * max(price['input'], price.get('cache_write') or 0)
                      + (output_tokens + 32768) * price['output']) / 1_000_000
            amount *= 1 + (price.get('fee_percent') or 0) / 100
        used = sum(r['reserved'] for r in prior if r['currency'] == currency)
        if used + amount > budget[currency.lower()] + 1e-9:
            raise policy.CoreError('plan_budget', '计划费用预留达到上限，未派发；可调整预算后明确继续。')
        db.execute('INSERT INTO plan_calls VALUES(?,?,?,?,?)',
                   (request_id, plan['id'], currency, amount,
                    policy.canonical_json({'model': item['model'], 'provider': provider, 'task_id': task_id,
                                           'basis': 'conservative_configured_price', 'settled': False})))


def settle(data_dir, request_id, billing, status):
    if not (Path(data_dir) / 'assistant-plans.db').exists(): return
    with connection(data_dir, write=True) as db:
        row = db.execute('SELECT * FROM plan_calls WHERE request_id=?', (request_id,)).fetchone()
        if row:
            doc = json.loads(row['document'])
            doc.update(billing=billing, status=status, settled=True)
            # Never refund an uncertain request or use estimates as settled invoices.
            db.execute('UPDATE plan_calls SET document=? WHERE request_id=?',
                       (policy.canonical_json(doc), request_id))
