"""Optional Codex proposal adapter. It never builds or applies candidate code."""
import hashlib
import json
import os
from pathlib import Path
import uuid
from . import policy
from .coding_settings import CodingSettings
from .network_policy import NetworkPolicy


def profile():
    return json.loads((policy.REPOSITORY_ROOT/'config/coding-runtime.json').read_text(encoding='utf-8'))


def executable():
    if os.name!='nt': raise policy.CoreError('codex_unavailable','此适配器当前仅支持已核对的 Windows CLI。')
    path=Path(os.environ['USERPROFILE'])/'AppData/Roaming/npm/node_modules/@openai/codex/node_modules/@openai/codex-win32-x64/vendor/x86_64-pc-windows-msvc/bin/codex.exe'
    if not path.is_file(): raise policy.CoreError('codex_unavailable','未找到已核对的 Codex CLI；不会自动安装或降级。')
    path=policy.safe_path(path,directory=False)
    with path.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
    if digest!=profile()['windows_sha256']: raise policy.CoreError('codex_version_changed','Codex CLI 版本或文件已变化，须核对适配器后再启用。')
    return path


def command(exe,stage,settings,schema):
    args=[str(exe),'exec','--ignore-user-config','--ignore-rules','--ephemeral','--skip-git-repo-check',
          '--json','--color','never','-C',str(stage),'--output-schema',str(schema),
          '-c','default_permissions="jarvis-proposal"',
          '-c','permissions.jarvis-proposal.filesystem={":root"="deny"}',
          '-c','permissions.jarvis-proposal.network.enabled=false',
          '-m',settings['model'],'-c','model_reasoning_effort='+json.dumps(settings['reasoning']),
          '-c','model_catalog_json='+json.dumps(str(stage/'models.json'))]
    for name in profile()['disabled_features']: args+=['--disable',name]
    for value in ['approval_policy="never"','web_search="disabled"','tools.view_image=false',
                  'skills.include_instructions=false','skills.bundled.enabled=false','project_doc_max_bytes=0',
                  'history.persistence="none"','model_provider="jarvis-codex"',
                  'model_providers.jarvis-codex.name="OpenAI"',
                  'model_providers.jarvis-codex.wire_api="responses"',
                  'model_providers.jarvis-codex.requires_openai_auth=true',
                  'model_providers.jarvis-codex.request_max_retries=0',
                  'model_providers.jarvis-codex.stream_max_retries=0']:
        args+=['-c',value]
    return args+['-']


def parse_events(raw,exit_code):
    """An external claim is never an independent check; tool effects are forbidden."""
    text,usage,thread,complete='',{},None,False
    for line in raw.decode('utf-8').splitlines():
        if not line.strip(): continue
        value=json.loads(line)
        if not isinstance(value,dict): raise ValueError('event')
        event=value.get('type')
        if event=='thread.started':thread=value.get('thread_id')
        elif event=='turn.completed':complete=True;usage=value.get('usage',{})
        elif event in {'turn.failed','error'}: raise policy.CoreError('model_unknown','Codex 调用未得到确定成功回执；不自动重发。')
        elif event in {'item.started','item.updated','item.completed'}:
            item=value.get('item',{})
            if item.get('type') not in {'agent_message','reasoning','plan','error'}:
                raise policy.CoreError('codex_tool_violation','外部执行器出现不允许的工具事件，拒绝交付。')
            if item.get('type')=='agent_message' and event=='item.completed': text=item.get('text','')
    if not complete or exit_code or not text: raise policy.CoreError('model_unknown','Codex 回执不完整，未自动重发。')
    return {'status':'SUCCEEDED','text':text,'usage':usage,'request_id':thread}


class CodexCodingProvider:
    def __init__(self,core): self.core=core;self.settings=CodingSettings(core);self.network=NetworkPolicy(core.data_dir)
    def binding(self):
        return policy.digest(policy.canonical_json(self.settings.read()).encode())
    def snapshot(self):
        settings=self.settings.read()
        try: path=executable();available=True;reason='已找到并核对本机 CLI。'
        except policy.CoreError as exc: path=None;available=False;reason=str(exc)
        return {'settings':settings,'available':available,'reason':reason,'version':profile()['version'],
                'executable':str(path) if path else None,'offline':self.network.snapshot()['offline'],
                'authentication':'使用本机 Codex 已有登录；实际账户可用性以调用结果为准。',
                'scope':'只生成候选文本，禁用命令、MCP、插件、浏览器和子 Agent；Jarvis 单独隔离验收。',
                'billing':'由 Codex 登录账户计费；回执记录 token，金额不计入 Jarvis API 费用估算。'}
    def preflight(self):
        self.network.require_online()
        settings=self.settings.read()
        if not settings['enabled']:raise policy.CoreError('codex_disabled','请先在设置 → 编码协作启用外部 Codex。')
        return settings,executable()
    def generate(self,prompt,instructions,checkpoint,*,paths,multi):
        settings,exe=self.preflight();revision=self.network.require_online()
        stage=policy.safe_path(self.core.data_dir/'coding-external'/uuid.uuid4().hex,must_exist=False)
        stage.mkdir(parents=True,exist_ok=False)
        schema={'type':'object','required':['files' if multi else 'code','notes'],'additionalProperties':False,
                'properties':{'notes':{'type':'string'},**({'files':{'type':'object','properties':{p:{'type':'string'} for p in paths},'required':paths,'additionalProperties':False}} if multi else {'code':{'type':'string'}})}}
        schema_path=stage/'schema.json';schema_path.write_text(policy.canonical_json(schema),encoding='utf-8')
        model=json.loads((policy.REPOSITORY_ROOT/'config/codex-proposal-model.json').read_text(encoding='utf-8'))
        model.update(slug=settings['model'],display_name=settings['model'])
        (stage/'models.json').write_text(policy.canonical_json({'models':[model]}),encoding='utf-8')
        input_path=stage/'request.txt';input_path.write_text(instructions+'\n\n'+prompt,encoding='utf-8')
        def guard():
            checkpoint();self.network.require_online(revision)
            if self.settings.read()!=settings:raise policy.CoreError('coding_settings_changed','编码设置已修改，本次调用停止；请核对结果后重新发起。')
        from .rea_process import run
        codex_home=policy.safe_path(Path(os.environ.get('CODEX_HOME',str(Path(os.environ['USERPROFILE'])/'.codex'))),directory=True)
        receipt={'status':'UNKNOWN','outcome_uncertain':True,'provider':'codex-cli','model':settings['model'],'billing':{'amount':None,'basis':'external_codex_account'},
                 'executor':{'version':profile()['version'],'settings_revision':settings['revision'],'stage':str(stage),
                             'candidate_execution':False,'tool_policy':'proposal-only','command_sandbox':'deny-filesystem'}}
        try:
            guard()
            result=run(command(exe,stage,settings,schema_path),stage,guard,seconds=profile()['wall_seconds'],
                       output_limit=512*1024,stdin_file=input_path,environment_extra={'CODEX_HOME':str(codex_home)})
            guard();receipt['executor']['process']=result['process']
            parsed=parse_events(result['stdout'],result['exit_code'])
            receipt.update(parsed)
            receipt['outcome_uncertain']=False
        except (ValueError,UnicodeError,KeyError):
            receipt.update(status='UNKNOWN',outcome_uncertain=True,error='invalid_codex_events')
        except policy.CoreError as exc:
            # Cancellation/permission/source changes keep their original shared task state.
            if exc.code not in {'model_unknown','rea_timeout','rea_output_limit','codex_tool_violation'}:raise
            receipt.update(status='UNKNOWN',outcome_uncertain=True,error=exc.code)
        finally:
            # Receipts intentionally omit raw stderr and prompts; no auth material is copied.
            safe={k:v for k,v in receipt.items() if k!='text'}
            (stage/'receipt.json').write_text(policy.canonical_json(safe),encoding='utf-8')
        return receipt
