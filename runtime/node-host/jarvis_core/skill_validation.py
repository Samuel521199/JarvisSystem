"""Version-bound evidence and last confirmed deliveries; availability is separate."""
import json
from . import policy, __version__
from .workspace import timestamp

INDEX=policy.REPOSITORY_ROOT/'config/skills/validation.json'
COMMON=('runtime/node-host/jarvis_core/skills.py','runtime/node-host/jarvis_core/skill_tasks.py','runtime/node-host/jarvis_core/skill_validation.py','contracts/schemas/skill-report.schema.json')

def fingerprint(item):
    paths=list(COMMON)
    if item['id'] in {'matt-pocock.diagnosing-bugs','matt-pocock.tdd','matt-pocock.codebase-design','matt-pocock.code-review','anatomy.explainer'}:
        paths+=['runtime/node-host/jarvis_core/'+name+'.py' for name in ('coding_task','coding_bundle','coding_build','coding_apply','coding_demand','coding_codex','coding_settings','coding_dependencies','coding_dependency_launcher','coding_package','coding_files','coding_js','coding_scene','coding_secrets')]
        paths+=['adapters/skills/anatomy/candidate-viewer.html','config/coding-runtime.json','config/codex-proposal-model.json']
    if item['workflow']=='game':paths+=['runtime/node-host/jarvis_core/web_game.py','adapters/skills/games/tank-defense.html']
    if item['workflow']=='rea':
        paths+=['runtime/node-host/jarvis_core/'+name+'.py' for name in ('rea','rea_process','rea_evidence','rea_asar','rea_focus','rea_explanation')]
        paths+=['config/skills/rea-runtime.json']
    elif item['workflow']=='anatomy':paths+=['runtime/node-host/jarvis_core/skill_renderer.py','config/skills/runtime.json']
    else:paths+=['runtime/node-host/jarvis_core/chat.py','runtime/node-host/jarvis_core/coding_workflow.py','runtime/node-host/jarvis_core/dialogue_process.py','runtime/node-host/jarvis_core/dialogue_worker.py','runtime/node-host/jarvis_core/evolution/runner.py','runtime/node-host/jarvis_core/evolution/provider.py','adapters/models/provider-native/jarvis_models/gateway.py','adapters/models/provider-native/jarvis_models/catalog.py']
    return policy.digest(policy.canonical_json({'id':item['id'],'version':item['version'],'guide':item.get('guide',''),
        'files':{p:policy.digest((policy.REPOSITORY_ROOT/p).read_bytes()) for p in paths}}).encode())

def table(db):
    db.execute('CREATE TABLE IF NOT EXISTS skill_success(skill_id TEXT PRIMARY KEY, task_id TEXT, binding TEXT, version TEXT, created_at TEXT, scope TEXT)')

def confirmed(db,item,task_id,binding,scope):
    table(db)
    db.execute('INSERT INTO skill_success VALUES(?,?,?,?,?,?) ON CONFLICT(skill_id) DO UPDATE SET task_id=excluded.task_id,binding=excluded.binding,version=excluded.version,created_at=excluded.created_at,scope=excluded.scope',
        (item['id'],task_id,binding,__version__,timestamp(),scope))

def statuses(core,items):
    try:
        index=json.loads(INDEX.read_text(encoding='utf-8'))
        if index.get('schema_version')!=1:raise ValueError()
        records=index['skills']
    except (OSError,ValueError,KeyError):records={}
    with core.ledger.connection() as db:
        exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='skill_success'").fetchone()
        latest={r['skill_id']:dict(r) for r in db.execute('SELECT * FROM skill_success')} if exists else {}
    result={}
    for item in items:
        binding=fingerprint(item);record=records.get(item['id']);last=latest.get(item['id'])
        valid=isinstance(record,dict) and record.get('binding')==binding
        state='stale' if record and not valid else 'verified_scope' if valid and record.get('status')=='passed' else 'needs_review' if valid else 'unverified'
        result[item['id']]={'state':state,'binding':binding,'evidence':record,
            'source_changed':bool(record and not valid),'latest_success':{**last,'current':last['binding']==binding} if last else None,
            'note':'质量证据只覆盖列出的案例与模型；最近成功表示交付与流程检查成功。'}
    return result
