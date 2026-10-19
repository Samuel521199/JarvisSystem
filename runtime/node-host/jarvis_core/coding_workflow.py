"""Bounded single-file Python edits, frozen examples, LPAC execution and reversible apply."""
import difflib
import hashlib
import json
import re
import threading
from pathlib import Path

from . import policy
from .project_files import ProjectFiles
from .skills import catalog
from .evolution.runner import IsolatedRunner, validate_code
from .evolution.provider import ModelCodingProvider

GUIDES = ('matt-pocock.diagnosing-bugs','matt-pocock.tdd','matt-pocock.codebase-design','matt-pocock.code-review')
MAX_ATTEMPTS = 2
APPLY_LOCK = threading.RLock()


def validate(args):
    if type(args.get('coding',False)) is not bool:
        raise policy.CoreError('coding_invalid','编程执行开关无效。')
    if not args.get('coding'):
        if any(k in args for k in ('cases','heldout_cases','entrypoint','coding_provider','coding_executor_binding','build_recipe','coding_demand')):raise policy.CoreError('coding_invalid','验收案例与编码选项仅用于编程执行。')
        return
    from .coding_bundle import layout
    from .coding_build import recipe, SOURCE, DEPENDENCY, executable
    selected_recipe = recipe(args.get('build_recipe', SOURCE))
    if 'coding_executor_binding' in args and (not isinstance(args['coding_executor_binding'],str) or not re.fullmatch(r'sha256:[a-f0-9]{64}',args['coding_executor_binding'])):
        raise policy.CoreError('coding_invalid','执行器绑定格式无效。')
    layout(args['paths'], args.get('entrypoint', next(iter(args['paths']), '')))
    if args.get('skill_id') not in GUIDES or not isinstance(args.get('coding_provider','gateway'),str) or args.get('coding_provider','gateway') not in {'gateway','codex'}:
        raise policy.CoreError('coding_invalid','请选择排错、TDD、模块设计或代码审阅及可用编码提供者。')
    if (args.get('coding_provider','gateway') == 'gateway' and '::' not in args.get('model','')) or args.get('output_path') or args.get('explain'):
        raise policy.CoreError('coding_invalid','请选择明确编码模型；候选工作区由系统创建。')
    cases=args.get('cases')
    if not isinstance(cases,list) or not 2 <= len(cases) <= 24:
        raise policy.CoreError('coding_invalid','填写 2—24 条独立验收案例，输入为 JSON，预期为字符串。')
    try:
        if len(json.dumps(cases,ensure_ascii=False,allow_nan=False).encode())>16384:raise ValueError()
        for c in cases:
            if not isinstance(c,dict) or set(c)!={'input','expected'} or not isinstance(c['expected'],str) or len(c['expected'].encode())>4096:raise ValueError()
    except (TypeError,ValueError,RecursionError,UnicodeError):
        raise policy.CoreError('coding_invalid','验收案例必须是有界 JSON 和字符串预期。') from None
    if 'heldout_cases' in args:
        other = {**args, 'cases': args['heldout_cases']}
        other.pop('heldout_cases')
        # Validate the private set with the same quotas without recursive multi-file requirement.
        other['paths'] = [args['paths'][0]]; other.pop('entrypoint', None); other.pop('build_recipe', None)
        validate(other)
        public = {policy.canonical_json(c['input']) for c in cases}
        if any(policy.canonical_json(c['input']) in public for c in args['heldout_cases']):
            raise policy.CoreError('coding_invalid','独立验收输入不能与公开示例重复。')
    elif len(args['paths']) > 1 or executable(selected_recipe):
        raise policy.CoreError('coding_invalid','多文件或可运行工具包还需要 2—24 条不发送给编码模型的独立验收案例。')
    if selected_recipe == DEPENDENCY:
        from .coding_dependencies import members
        members()  # Missing/corrupt closure fails admission, before any model call.


def composition(service,args):
    decisions=[]
    for ident in GUIDES:
        ctx={'explicit':ident,'project_id':args['project_id']}
        if args.get('conversation_id'):ctx['conversation_id']=args['conversation_id']
        d=service.manager.select(args['prompt'],ctx,purpose='task')
        if not d['selected']:raise policy.CoreError('coding_skill_disabled','组合中的技能不可用：'+ident)
        decisions.append(d)
    items={x['id']:x for x in catalog()[0]['skills']}
    # Jarvis adaptations are small enough to compose within the existing 4 KiB budget.
    return decisions,{ident:items[ident]['guide'] for ident in GUIDES}


def check_code(runner,source,cases,checkpoint):
    checkpoint()
    try:
        outputs,evidence=runner.run(source,[c['input'] for c in cases],checkpoint)
        if len(outputs)!=len(cases):raise policy.CoreError('candidate_invalid','测试输出数量不符。')
        failures=[{'case':i+1,'expected':c['expected'],'actual':v[:4096],
            **({'actual_truncated':True,'actual_digest':policy.digest(v.encode()),'actual_characters':len(v)} if len(v)>4096 else {})}
            for i,(c,v) in enumerate(zip(cases,outputs)) if v!=c['expected']]
        return {'passed':not failures,'cases':len(cases),'failures':failures,'worker':evidence}
    except policy.CoreError as exc:
        if exc.code not in {'candidate_invalid','candidate_execution_failed','candidate_reply_invalid'}:raise
        return {'passed':False,'cases':len(cases),'error':exc.code,'message':str(exc)}


def execute(service,args,checkpoint,action_id,task_id):
    from .coding_task import execute as run
    return run(service,args,checkpoint,action_id,task_id)

def apply_result(core,report,action):
    if action not in {'apply','rollback'} or not isinstance(report.get('coding'),dict) or not report['coding']['passed']:
        raise policy.CoreError('coding_invalid','仅通过验收的编程候选可以应用或回退。')
    value=report['coding'];original=value['original'];project=report['output']['project_id']
    if 'originals' in value:
        from .coding_apply import apply_bundle
        return apply_bundle(core, report, action)
    files=ProjectFiles(core)
    if str(files.root(project))!=original['project_root']:raise policy.CoreError('file_conflict','项目位置变化，候选不能应用到其他位置。')
    candidate=value['candidate']
    # Original BOM is part of the frozen byte digest; captured separately in source snapshot.
    original_bom=original.get('bom',False)
    candidate_digest=policy.digest((b'\xef\xbb\xbf' if original_bom else b'')+candidate.encode())
    content=candidate if action=='apply' else original['content']
    expected=original['digest'] if action=='apply' else candidate_digest
    target_digest=candidate_digest if action=='apply' else original['digest']
    with APPLY_LOCK:
        current=files.read({'project_id':project,'path':original['path']})
        if current['digest']==target_digest:
            with core.ledger.transaction() as db:
                exists=db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='coding_changes'").fetchone()
                if exists:db.execute('UPDATE coding_changes SET state=? WHERE output_id=? AND action=? AND after_digest=? AND state IN (?,?)',
                    ('CONFIRMED_OBSERVED',report['output']['request_id'],action,target_digest,'PREPARED','REVIEW_REQUIRED'))
            return {'status':'already_applied' if action=='apply' else 'already_restored','digest':target_digest}
        if current['digest']!=expected:raise policy.CoreError('file_conflict','源码已被其他编辑修改，未覆盖；请重新核对差异。')
        with core.ledger.transaction() as db:
            db.execute('CREATE TABLE IF NOT EXISTS coding_changes(id INTEGER PRIMARY KEY, output_id TEXT, action TEXT, before_digest TEXT, after_digest TEXT, state TEXT)')
            change=db.execute('INSERT INTO coding_changes(output_id,action,before_digest,after_digest,state) VALUES(?,?,?,?,?)',
                (report['output']['request_id'],action,expected,target_digest,'PREPARED')).lastrowid
        try:
            result=files.write({'project_id':project,'path':original['path'],'content':content,'digest':expected,'bom':original_bom})
        except Exception:
            with core.ledger.transaction() as db:db.execute('UPDATE coding_changes SET state=? WHERE id=?',('REVIEW_REQUIRED',change))
            raise
        with core.ledger.transaction() as db:db.execute('UPDATE coding_changes SET state=? WHERE id=?',('CONFIRMED',change))
        return {'status':'applied' if action=='apply' else 'restored','digest':result['digest']}
