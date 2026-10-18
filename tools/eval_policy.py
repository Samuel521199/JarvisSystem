"""Shared live-evaluation preference; provider-specific checks explicitly override it."""
import hashlib
import json
from pathlib import Path
import re

ROOT=Path(__file__).resolve().parents[1]

def default_route():
    data=json.loads((ROOT/'config/eval-policy.json').read_text(encoding='utf-8'))
    route=data.get('preferred_live_route')
    if data.get('schema_version')!=1 or not isinstance(route,str) or not re.fullmatch(r'[a-zA-Z0-9_.-]+::[a-zA-Z0-9_./-]+',route):
        raise ValueError('Invalid live-evaluation route')
    return route

def route_name(prefix,route):
    slug=re.sub(r'[^a-zA-Z0-9_.-]','-',route)[:100]
    return prefix+'-'+slug+'-'+hashlib.sha256(route.encode()).hexdigest()[:8]

def report_path(prefix,route):
    return ROOT/'evals/reports'/(route_name(prefix,route)+'.json')
