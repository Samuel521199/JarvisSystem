"""Schemas and deterministic scope checks; model messages cannot edit scope."""
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[3]


class ComputerError(RuntimeError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def strict_json(raw):
    if len(raw) > 65536:
        raise ComputerError('invalid_message', 'JSON message exceeds size limit')
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('Duplicate key')
            result[key] = value
        return result
    def constant(value):
        raise ValueError('Nonfinite number')
    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)
    except (ValueError, RecursionError, UnicodeError) as exc:
        raise ComputerError('invalid_message', 'Expected one strict JSON object') from exc


def validate_schema(value, name):
    schema = json.loads((ROOT / 'contracts/schemas' / name).read_text(encoding='utf-8'))
    if next(Draft202012Validator(schema).iter_errors(value), None):
        raise ComputerError('invalid_message', 'Task/action does not match its fixed schema')


def origin(url):
    try:
        if not isinstance(url, str) or any(ord(c) <= 32 or ord(c) == 127 for c in url):
            raise ValueError('Invalid URL characters')
        parsed = urlsplit(url)
        if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password or '\\' in url:
            raise ValueError('Invalid browser URL')
        port = parsed.port or (443 if parsed.scheme == 'https' else 80)
        host = parsed.hostname.lower()
        if ':' in host:
            host = '[' + host + ']'
        return f'{parsed.scheme}://{host}' + (f':{port}' if port != (443 if parsed.scheme == 'https' else 80) else '')
    except (ValueError, TypeError) as exc:
        raise ComputerError('url_denied', 'Only explicit HTTP(S) origins without credentials are supported') from exc


def validate_task(task):
    validate_schema(task, 'computer-task.schema.json')
    if any(type(task[key]) is not int for key in ('schema_version','max_steps','timeout_seconds')):
        raise ComputerError('invalid_task', 'Budgets and version must be integers')
    if len(canonical(task).encode()) > 32768:
        raise ComputerError('invalid_task', 'Task exceeds size limit')
    for item in task['allowed_origins']:
        if item != origin(item):
            raise ComputerError('invalid_task', 'Allowed origins must be canonical, without paths or wildcards')
    if origin(task['url']) not in task['allowed_origins']:
        raise ComputerError('url_denied', 'Initial URL is outside the explicit task scope')
    identifiers = [item['id'] for item in task['targets']]
    if len(set(identifiers)) != len(identifiers):
        raise ComputerError('invalid_task', 'Target IDs must be unique')
    for target in task['targets']:
        for op in target['actions']:
            compatible = {'fill': {'textbox'}, 'select': {'combobox'}, 'check': {'checkbox','radio'},
                          'click': {'button','link','checkbox','radio'}}
            if target['role'] not in compatible[op]:
                raise ComputerError('invalid_task', 'Target action does not match its role')
        if any(op != 'click' for op in target['actions']) and not target['values']:
            raise ComputerError('invalid_task', 'Input actions require explicitly allowed values')
    return json.loads(canonical(task))


def validate_action(action, task, observation):
    validate_schema(action, 'computer-action.schema.json')
    if action['observation_id'] != observation['id']:
        raise ComputerError('stale_observation', 'Action does not refer to the current observation')
    target = next((item for item in task['targets'] if item['id'] == action['target']), None)
    if target is None or action['op'] not in target['actions']:
        raise ComputerError('action_denied', 'Action/target is outside the owner task scope')
    if not any(item['id'] == target['id'] and item['available'] for item in observation['targets']):
        raise ComputerError('action_denied', 'Target is not currently available')
    op, value = action['op'], action['value']
    if op == 'click':
        valid = value is None
    else:
        valid = any(type(value) is type(item) and value == item for item in target['values'])
        valid = valid and (type(value) is bool if op == 'check' else isinstance(value, str))
    if not valid:
        raise ComputerError('action_denied', 'Value is not explicitly permitted for this target')
    return action
