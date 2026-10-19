"""Project-scoped K3 artifacts on the existing growth lane and SQLite ledger.

No model, package installation, Host execution or new scheduler lives here.
Publication retains old acceptance cases; invocations pin a package/generation.
"""
import copy
import json
import re
import time

from .. import policy
from ..coding_build import bytes_from, ZIPAPP, DEPENDENCY
from ..coding_package import RECIPES
from ..coding_demand import archive
from ..project_files import ProjectFiles
from .store import now

RECIPES = {ZIPAPP, DEPENDENCY, *RECIPES}
FAULTS = {'tool_regression','tool_result_mismatch','tool_package_changed','coding_build_invalid',
          'candidate_invalid','candidate_execution_failed','candidate_reply_invalid',
          'worker_timeout','worker_cpu_limit','worker_output_limit'}


def fail(message, code='tool_invalid'):
    raise policy.CoreError(code, message)


def encoded(value, limit=8192):
    try:
        raw=json.dumps(value,ensure_ascii=False,allow_nan=False,sort_keys=True,separators=(',',':')).encode()
        if len(raw)>limit:raise ValueError()
        return raw
    except (ValueError,TypeError,RecursionError):fail('JSON 输入无效或超出大小限制。')


def merge_cases(old, new):
    result={}
    for case in old+new:
        key=encoded(case['input'],16384)
        if key in result and result[key]['expected']!=case['expected']:
            fail('升级不能改变旧输入的预期结果；用途不兼容时请使用新的工具标识。')
        result[key]=case
    values=list(result.values())
    if len(values)>64:fail('累计验收案例超过 64 条，请拆分工具用途。')
    encoded(values,65536)
    return values


def runtime_binding():
    from ..skill_tasks import SkillTaskService
    paths=('catalog','manager','store','runner','tool_intent','tool_contract','provider','demand')
    return policy.digest(policy.canonical_json({'coding':SkillTaskService.binding(),
        'tools':{p:policy.digest((policy.REPOSITORY_ROOT/'runtime/node-host/jarvis_core/evolution'/f'{p}.py').read_bytes()) for p in paths}}).encode())


class ProjectTools:
    def __init__(self, manager, tasks=None):
        self.manager, self.store, self.core, self.tasks=manager,manager.store,manager.core,tasks

    def scope(self, cid):
        doc=archive(self.core,cid)
        return {'conversation_id':cid,'project_id':doc['project_id'],
                'root':str(ProjectFiles(self.core).root(doc['project_id']))}

    def selected(self, project, tool):
        with self.store.connection() as db:
            row=db.execute('SELECT * FROM project_tools WHERE project_id=? AND tool_id=?',(project,tool)).fetchone()
        return dict(row) if row else {'project_id':project,'tool_id':tool,'active':None,'previous':None,'generation':0}

    def package(self, ident, scope=None):
        with self.store.connection() as db:
            row=db.execute('SELECT document,state FROM tool_versions WHERE id=?',(ident,)).fetchone()
        if row is None:fail('工具版本未登记。','tool_package_changed')
        try:doc=json.loads(row['document'])
        except (ValueError,TypeError):fail('工具版本记录损坏。','tool_package_changed')
        if policy.digest(policy.canonical_json(doc).encode())[7:]!=ident:
            fail('工具包或冻结验收发生变化。','tool_package_changed')
        if scope and any(doc.get(k)!=scope[k] for k in ('project_id','tool_id')):
            fail('工具包不属于当前项目和用途。','tool_package_changed')
        bytes_from(doc['build'])
        return doc,row['state']

    def bound_job(self,cid,ident):
        scope=self.scope(cid);job=self.store.job(ident)
        if job['request'].get('action')!='project-tool' or job['request']['scope']!=scope:
            fail('未找到本会话的工具任务。','not_found')
        return job

    def snapshot(self,cid):
        scope=self.scope(cid);tools=[]
        with self.store.connection() as db:
            rows=db.execute('SELECT * FROM project_tools WHERE project_id=? ORDER BY tool_id',(scope['project_id'],)).fetchall()
            jobs=[json.loads(r[0]) for r in db.execute("SELECT document FROM jobs WHERE json_extract(document,'$.request.action')='project-tool' AND json_extract(document,'$.request.scope.project_id')=? ORDER BY rowid DESC LIMIT 1000",(scope['project_id'],))]
        for raw in rows:
            row=dict(raw);meta=None;issue=None
            try:
                if row['active'] or row['previous']:meta=self.package(row['active'] or row['previous'],row)[0]
            except policy.CoreError as exc:issue=exc.code
            uses=[j for j in jobs if j['request']['submission']['tool_id']==row['tool_id'] and j['request']['submission']['operation']=='run']
            tools.append({**row,'metadata':meta['metadata'] if meta else None,'issue':issue,
                          'example_input':meta['cases'][0]['input'] if meta else None,
                          'cases':len(meta['cases']) if meta else 0,
                          'usage':{'calls':len(uses),'succeeded':sum(j['status']=='SUCCEEDED' for j in uses),
                                   'verified_results':sum(bool((j.get('result') or {}).get('result_verified')) and j['status']=='SUCCEEDED' for j in uses),
                                   'model_calls':0}})
        return {'tools':tools,'jobs':[j for j in jobs if j['request']['scope']==scope][:20],
                'scope':'project','busy':self.manager.busy,'limits':{'tools':32,'versions':64,'cases':64,'input_bytes':8192},
                'note':'运行成功与结果正确分别记录；只有提供独立预期并一致才记为结果已验证。'}

    def submit(self,cid,payload):
        scope=self.scope(cid)
        if not isinstance(payload,dict):fail('工具请求必须是对象。')
        op=payload.get('operation');required={'operation','request_id','tool_id','generation'}
        if op=='publish':required|={'task_id','name','when_to_use','when_not_to_use'}
        elif op=='run':required|={'input'}
        elif op not in {'rollback','disable'}:fail('工具动作不支持。')
        if not required<=set(payload) or set(payload)-required-({'expected'} if op=='run' else set()):fail('工具请求字段不完整。')
        if not isinstance(payload['request_id'],str) or not re.fullmatch('[a-f0-9]{32}',payload['request_id']):fail('请求编号无效。')
        if not isinstance(payload['tool_id'],str) or not re.fullmatch('[a-z][a-z0-9-]{1,47}',payload['tool_id']):fail('工具标识使用 2—48 位小写字母、数字或短横线。')
        if type(payload['generation']) is not int or payload['generation']<0:fail('工具代际无效。')
        request='project-tool-'+payload['request_id']
        existing=self.store.existing_job(request)
        if existing:
            if existing['request']['scope']!=scope or existing['request']['submission']!=payload:fail('请求编号已用于其他内容。','evolution_conflict')
            return existing
        base=self.selected(scope['project_id'],payload['tool_id'])
        if base['generation']!=payload['generation']:fail('工具版本已变化，请刷新后重试。','evolution_conflict')
        frozen={'action':'project-tool','request_id':request,'scope':scope,'submission':copy.deepcopy(payload),'base':base,'runtime_binding':runtime_binding()}
        if op=='publish':
            metadata={k:payload[k] for k in ('name','when_to_use','when_not_to_use')}
            if any(not isinstance(v,str) or not v.strip() or len(v.encode())>512 or '\0' in v for v in metadata.values()):fail('请填写名称、适用和不适用说明（每项最多 512 字节）。')
            if self.tasks is None:fail('编码任务模块不可用。')
            record=self.tasks._bound(cid,payload['task_id'])
            report=json.loads(self.tasks.artifact(cid,payload['task_id']))
            coding=report.get('coding',{});args=record['action']['arguments']
            if args.get('project_id')!=scope['project_id'] or not coding.get('passed') or not coding.get('build_validation',{}).get('passed'):
                fail('只能登记本项目已经独立验收和构建成功的编码产物。')
            build=coding.get('build',{});bytes_from(build)
            if build['manifest'].get('recipe') not in RECIPES:fail('首期工具库只支持可执行 Python 配方；源码包和动画场景保留原交付方式。')
            if not args.get('heldout_cases'):fail('发布需要独立留出验收。')
            prior=self.package(base['active'],base)[0]['cases'] if base['active'] else self.package(base['previous'],base)[0]['cases'] if base['previous'] else []
            frozen['package']={'build':build,'cases':merge_cases(prior,args['cases']+args['heldout_cases']),
                               'metadata':metadata,'origin':{'task_id':payload['task_id'],'artifact_digest':record['artifact']['digest']},
                               'project_id':scope['project_id'],'tool_id':payload['tool_id']}
        elif op=='run':
            encoded(payload['input'])
            if 'expected' in payload and (not isinstance(payload['expected'],str) or len(payload['expected'].encode())>16384):fail('独立预期必须是最多 16 KiB 的文本。')
            if not base['active']:fail('工具未启用。')
        elif op=='rollback' and not base['previous']:fail('没有可恢复的上一版本。')
        return self.manager._enqueue(frozen)

    def checkpoint(self,job):
        self.manager._checkpoint()
        if job['request']['runtime_binding']!=runtime_binding():
            fail('执行器已更新，请重新提交工具任务。','tool_runtime_changed')
        if self.scope(job['request']['scope']['conversation_id'])!=job['request']['scope']:
            fail('会话或项目范围已变化。','tool_scope_changed')

    def evaluate(self,doc,checkpoint):
        self.manager._resources();self.manager.runner.preflight()
        outputs,evidence=self.manager.runner.run_build(doc['build'],[x['input'] for x in doc['cases']],checkpoint)
        if outputs!=[x['expected'] for x in doc['cases']]:fail('工具未通过保留的独立回归，旧验收不会被新版本删除。','tool_regression')
        return {'passed':True,'cases':len(outputs),'isolation':evidence}

    def select(self,job,target,previous,*,observing=False,quarantine=None):
        base=job['request']['base'];checkpoint=lambda:self.checkpoint(job);checkpoint()
        with self.core.effect_guard(),self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            row=db.execute('SELECT * FROM project_tools WHERE project_id=? AND tool_id=?',(base['project_id'],base['tool_id'])).fetchone()
            current=dict(row) if row else {**base,'generation':0,'active':None,'previous':None}
            if current!=base:fail('活动工具已变化，未覆盖其他版本。','evolution_conflict')
            if row is None and db.execute('SELECT COUNT(*) FROM project_tools').fetchone()[0]>=32:fail('工具目录达到 32 项上限。')
            db.execute('INSERT INTO project_tools VALUES(?,?,?,?,?) ON CONFLICT(project_id,tool_id) DO UPDATE SET active=excluded.active,previous=excluded.previous,generation=excluded.generation',
                       (base['project_id'],base['tool_id'],target,previous,base['generation']+1))
            if quarantine:db.execute("UPDATE tool_versions SET state='QUARANTINED' WHERE id=?",(quarantine,))
            job['tool_activation']={'project_id':base['project_id'],'tool_id':base['tool_id'],'version':target,'generation':base['generation']+1}
            job['tool_activation_confirmed']=not observing
            if observing:job['status']='OBSERVING'
            job['events'].append({'at':now(),'phase':'TOOL_SELECTED','version':target})
            self.store.write_job(db,job)

    def abort(self,job):
        pending=job.get('tool_activation')
        if not pending or job.get('tool_activation_confirmed'):return
        with self.store.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('UPDATE project_tools SET active=NULL,generation=generation+1 WHERE project_id=? AND tool_id=? AND active=? AND generation=?',
                       (pending['project_id'],pending['tool_id'],pending['version'],pending['generation']))
            db.execute("UPDATE tool_versions SET state='QUARANTINED' WHERE id=?",(pending['version'],))

    def execute(self,job):
        request=job['request'];payload=request['submission'];base=request['base'];op=payload['operation']
        checkpoint=lambda:self.checkpoint(job);checkpoint()
        if self.selected(base['project_id'],base['tool_id'])!=base:fail('工具基线已变化。','evolution_conflict')
        start=time.monotonic()
        if op=='publish':
            doc=request['package'];proof=self.evaluate(doc,checkpoint);checkpoint()
            ident=policy.digest(policy.canonical_json(doc).encode())[7:]
            with self.store.connection() as db:
                if db.execute('SELECT COUNT(*) FROM tool_versions').fetchone()[0]>=64:fail('工具版本达到 64 项保留上限。')
                db.execute('INSERT OR IGNORE INTO tool_versions VALUES(?,?,?)',(ident,'VERIFIED',policy.canonical_json(doc)))
                if db.execute('SELECT state FROM tool_versions WHERE id=?',(ident,)).fetchone()[0]!='VERIFIED':fail('该版本已隔离，不能重新启用。')
            if ident==base['active']:return {'version':ident,'already_active':True,'validation':proof,'model_calls':0}
            self.select(job,ident,base['active'] or base['previous'],observing=True)
            self.evaluate(self.package(ident,base)[0],checkpoint)
            # Persist observation before finishing; restart never exposes an unobserved version.
            self.store.update(job,'TOOL_OBSERVED',tool_activation_confirmed=True)
            return {'version':ident,'validation':proof,'model_calls':0,'benefit':{'new_capability':base['active'] is None,'retained_cases':len(doc['cases']),'real_use_verified':False}}
        if op=='disable':
            self.select(job,None,base['active'] or base['previous'])
            return {'disabled':True,'model_calls':0}
        if op=='rollback':
            doc,state=self.package(base['previous'],base)
            if state!='VERIFIED':fail('旧版本已隔离。')
            proof=self.evaluate(doc,checkpoint);self.select(job,base['previous'],None)
            return {'restored':base['previous'],'validation':proof,'model_calls':0}
        regression_checked=False
        try:
            doc,state=self.package(base['active'],base)
            if state!='VERIFIED':fail('活动版本未验证。','tool_package_changed')
            proof=self.evaluate(doc,checkpoint)
            regression_checked=True
            outputs,evidence=self.manager.runner.run_build(doc['build'],[payload['input']],checkpoint)
            if len(outputs)!=1:fail('执行结果不完整。','tool_result_mismatch')
            if 'expected' in payload and outputs!=[payload['expected']]:fail('真实输入结果与独立预期不符。','tool_result_mismatch')
            checkpoint();self.package(base['active'],base)
            return {'version':base['active'],'text':outputs[0],'result_verified':'expected' in payload,
                    'regression':proof,'isolation':evidence,'elapsed_seconds':round(time.monotonic()-start,3),
                    'result_digest':policy.digest(outputs[0].encode()),'model_calls':0}
        except policy.CoreError as exc:
            if exc.code not in FAULTS:raise
            if regression_checked and 'expected' not in payload and exc.code not in {'tool_package_changed','coding_build_invalid'}:
                raise  # Out-of-domain input alone is not proof of a broken tool.
            replacement=None
            if base['previous']:
                try:
                    old,state=self.package(base['previous'],base)
                    if state=='VERIFIED':self.evaluate(old,checkpoint);replacement=base['previous']
                except policy.CoreError as old_error:
                    if old_error.code not in FAULTS:raise
            self.select(job,replacement,None,quarantine=base['active'])
            self.store.update(job,'TOOL_AUTO_ROLLBACK',rollback={'from':base['active'],'to':replacement})
            raise  # Keep the failed invocation failed; never replay its input.
