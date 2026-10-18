"""On-demand cached module observations and one independent maintenance lane.

Observations never load model weights, read credentials, start services or
contact cloud providers. Maintenance prepares future launches, never live swaps.
"""
from contextlib import closing
from datetime import datetime, timezone
from importlib import metadata
import copy
import json
import os
from pathlib import Path
import re
import sqlite3
import threading
import time
import uuid

import httpx

from . import __version__, policy
from .runtime_catalog import RuntimeCatalog


def now():
    return datetime.now(timezone.utc).isoformat()


class ModuleError(ValueError):
    pass


class ModuleMonitor:
    TTL = 8

    def __init__(self, core, activity, *, config_path=None, root=None, model_root=None, releases_root=None):
        self.core, self.activity = core, activity
        self.root = Path(root or policy.REPOSITORY_ROOT)
        self.config_path = config_path or self.root/'config/model-profiles/providers.json'
        self.model_root = Path(model_root) if model_root else None
        self.releases_root = Path(releases_root or Path(os.environ.get('LOCALAPPDATA', '.'))/'Jarvis/runtime')
        self.lock = threading.Lock()
        self.closed = False
        self.refreshing = False
        self.updated = 0.0
        self.cache = {'observed_at': None, 'modules': [], 'releases': {'releases': [], 'active': None, 'previous': None}}
        self.job = None
        self.job_path = Path(core.data_dir)/'module-maintenance.json'
        self.jobs = self._load_jobs()
        self.catalog = RuntimeCatalog(core, root=self.root)
        from .local_model import LocalModel
        self.local_model = LocalModel(core, model_root=self.model_root, activity=activity)
        from .speech import SpeechService
        self.speech = SpeechService(core)
        from .fast_speech import FastSpeechService
        self.fast_speech = FastSpeechService(core)
        from .qwen_speech import QwenSpeechService
        self.primary_speech = QwenSpeechService(core)

    def _load_jobs(self):
        try:
            path = policy.safe_path(self.job_path, directory=False)
            if path.stat().st_size > 65536: return []
            jobs = json.loads(path.read_text(encoding='utf-8'))
            if not isinstance(jobs, list): return []
            rows = [r for r in jobs[-20:] if isinstance(r, dict) and isinstance(r.get('id'), str)]
            for row in rows:
                if row.get('status') == 'RUNNING':
                    row.update(status='UNKNOWN', message='上次进程已退出，维护结果需核对；没有自动重放。')
            return rows
        except (OSError, ValueError, policy.CoreError):
            return []

    def _save_jobs(self):
        # Called under self.lock; one fixed small file outside business databases.
        policy.safe_path(self.job_path, must_exist=False)
        temporary = self.job_path.with_suffix('.tmp')
        policy.safe_path(temporary, must_exist=False)
        temporary.write_text(json.dumps(self.jobs[-20:], ensure_ascii=False), encoding='utf-8')
        os.replace(temporary, self.job_path)

    def close(self):
        with self.lock: self.closed = True
        self.local_model.close()
        self.speech.close()
        self.fast_speech.close()
        self.primary_speech.close()

    def snapshot(self, *, refresh=False):
        with self.lock:
            age = time.monotonic() - self.updated
            if not self.closed and not self.refreshing and (age >= self.TTL or (refresh and age >= 2)):
                self.refreshing = True
                threading.Thread(target=self._refresh, name='jarvis-module-observer', daemon=True).start()
            return {**copy.deepcopy(self.cache), 'refreshing': self.refreshing,
                    'stale': not self.updated or age > self.TTL * 3,
                    'poll_seconds': self.TTL, 'maintenance': copy.deepcopy(self.jobs[-20:][::-1]),
                    'maintenance_busy': self.job is not None, 'version': __version__}

    def _refresh(self):
        try:
            rows = []
            groups = {
                'host': [('host','核心宿主','bundled')],
                'models': [('models','模型路由','configuration'),('local-llm','本地小模型','external')],
                'calculator': [('calculator','本地精确计算','bundled')],
                'tasks': [('browser','浏览器执行','bundled'),('worker','目录元数据 Worker','bundled')],
                'workspace': [('workspace','项目资源与文件','bundled')],
                'memory': [('memory','明确事实记忆','bundled')],
                'knowledge': [('knowledge','项目资料检索','bundled')],
                'mcp': [('mcp-registration','MCP 登记','bundled')],
                'skills': [('skill-registration','技能登记','bundled')],
                'sample-report': [('sample-report','自然语言目录报告','bundled')],
                'speech': [('stt','语音识别 STT','external'),('tts','语音合成 TTS','external'),
                           ('speaker','声纹特征','external'),('vad','语音活动检测','external'),
                           ('cosyvoice3','CosyVoice3 克隆与情绪语音','external'),
                           ('zipvoice','ZipVoice 备用语音','external'),('qwen-tts','Qwen 主力语音','external')],
            }
            for ident, collector in (('host', self._host), ('models', self._models), ('calculator',self._calculator),
                                      ('tasks', self._tasks), ('workspace', self._workspace),
                                      ('memory', self._memory), ('knowledge', self._knowledge),
                                      ('mcp', self._mcp), ('skills', self._skills),
                                      ('sample-report', self._sample_report),
                                      ('speech', self._speech)):
                try: rows.extend(collector())
                except Exception:
                    rows.extend(self._row(key,name,health='unknown',update=mode,
                                          message='本模块观察失败；其他模块继续采集，原服务未被停止。')
                                for key,name,mode in groups[ident])
            catalog = self.catalog.snapshot()
            rows.append(self._row('seed-catalog', '初始知识、规则与技能', installed=catalog['status']=='ready',
                                 enabled=catalog['status']=='ready', version=catalog['seed_version'],
                                 health='ready' if catalog['status']=='ready' else 'unavailable',
                                 activity='on_demand', message=catalog['message']))
            rows.extend([self._row('extension-runtime', '通用 MCP / 外部技能执行', installed=False, health='not_implemented', enabled=False,
                                  activity='not_integrated', update='planned', message='任意扩展执行尚未开放；Context7 只读文档查询已接入，连接与调用记录见技能与工具；原生技能另列状态。'),
                         self._row('federation', '多设备共同体', installed=False, health='not_implemented', enabled=False,
                                   activity='not_integrated', update='planned', message='当前为本机实例，共同体尚未实现。')])
            try: releases = self._releases()
            except Exception: releases = {'releases': [], 'active': None, 'previous': None, 'error': '版本登记暂不可读。'}
            with self.lock:
                self.cache = {'observed_at': now(), 'modules': rows, 'releases': releases, 'catalog': catalog}
                self.updated = time.monotonic()
        finally:
            with self.lock: self.refreshing = False

    @staticmethod
    def _row(ident, name, *, installed=None, health='ready', enabled=None, activity='unknown',
             active=0, count=None, last_used=None, version=None, message='', update='bundled', count_scope='recent_records'):
        return dict(id=ident, name=name, installed=installed, health=health, enabled=enabled,
                    activity=activity, active=active, recent_uses=count, last_used=last_used,
                    version=version, message=message, update_mode=update, count_scope=count_scope)

    def _read(self, path, query):
        if not path.exists(): return []
        path = policy.safe_path(path, directory=False)
        for suffix in ('-wal', '-shm', '-journal'):
            policy.safe_path(str(path)+suffix, must_exist=False)
        with closing(sqlite3.connect(path.absolute().as_uri()+'?mode=ro', uri=True, timeout=.25)) as db:
            db.execute('PRAGMA query_only=ON')
            return db.execute(query).fetchall()

    def _host(self):
        try: self.core.assert_running(); health='ready'
        except Exception: health='unavailable'
        return [self._row('host', '核心宿主', installed=True, health=health, enabled=health=='ready',
                         activity='running' if health=='ready' else 'offline', version=__version__, message='本机常驻。设置监控不参与聊天和任务准入。')]

    def _calculator(self):
        from .calculator import ENGINE
        return [self._row('calculator','本地精确计算',installed=True,enabled=True,
                         activity='on_demand',version=ENGINE,count=self.activity().get('calculator_uses'),count_scope='host_lifetime',
                         message='完整算式按需计算，无模型或网络依赖；成功次数属于本次宿主启动，不含直接 CLI 调用。')]

    def _models(self):
        from jarvis_models.registry import effective_config
        config = effective_config(self.config_path, self.core.data_dir)
        providers = config['providers']
        active = self.activity().get('chat', 0)
        records = self._read(Path(self.core.data_dir)/'model-probes.db',
                             'SELECT provider,created_at FROM probes ORDER BY rowid DESC LIMIT 1000')
        cloud = [p for p, c in providers.items() if c.get('adapter', p) != 'local' and c.get('enabled', True)]
        local = [p for p, c in providers.items() if c.get('adapter', p) == 'local' and c.get('enabled', True)]
        used = [r for r in records if r[0] in local]
        router = self._row('models', '模型路由', installed=True, enabled=True, activity='busy' if active else 'standby',
                           active=active, count=len(records), last_used=records[0][1] if records else None,
                           version=__version__, message=f'{len(cloud)} 条云端线路已启用；未调用云模型探测余额或健康。', update='configuration')
        try:
            with httpx.Client(timeout=.8, trust_env=False, follow_redirects=False) as client:
                response = client.get('http://127.0.0.1:18180/health')
            health = 'ready' if response.status_code == 200 else 'unavailable'
        except httpx.HTTPError: health='offline'
        assets = self._assets('qwen3-0.6b')
        row = self._row('local-llm', '本地小模型', installed=assets['installed'], health=health,
                enabled=bool(local), activity='service_online' if health=='ready' else 'offline', count=len(used),
                last_used=used[0][1] if used else None, version=providers[local[0]]['model'] if local else 'qwen3-0.6b',
                message=assets['message']+' 健康端点只证明服务响应，不证明正在推理或模型质量。', update='external')
        row['runtime'] = self.local_model.snapshot()
        row['message'] += ' 启动仅使用已下载且摘要校验通过的 CPU 组件；停止仅处理本实例拥有的进程。'
        return [router,row]

    def _tasks(self):
        activity = self.activity()
        active = set(activity.get('tasks', []))
        records = self._read(Path(self.core.data_dir)/'control.db',
                            'SELECT task_id,document FROM tasks ORDER BY rowid DESC LIMIT 1000')
        parsed = [(tid, json.loads(raw)) for tid, raw in records]
        result = []
        for ident, name, capability in (('browser','浏览器执行','browser.operate.v1'),
                                         ('worker','目录元数据 Worker','filesystem.read_sample.v1')):
            used = [(tid, d) for tid, d in parsed if capability in d.get('required_capabilities', [])]
            running = sum(tid in active for tid, _ in used)
            if ident == 'browser':
                try: version=metadata.version('playwright'); installed=True
                except metadata.PackageNotFoundError: version=None; installed=False
                enabled = bool(activity.get('computer')) and installed
                message='独立浏览器进程按需启动。未启动浏览器作探测；文件存在不代表网站操作成功。'
            else:
                profile=json.loads((self.root/'config/worker-profile.json').read_text(encoding='utf-8'))
                directory=profile['runtime_directory']
                if Path(directory).name != directory: raise ValueError('Invalid worker directory')
                installed=any(p.is_file() for p in (self.root/'runtime-bundle'/directory/'bundle.json',
                    Path(os.environ.get('USERPROFILE','.'))/'.jarvis/worker-runtimes'/directory/'bundle.json'))
                enabled=installed and bool(activity.get('computer'));version=directory
                message='固定目录元数据任务。这里只检查登记文件，执行前仍由 Worker 校验摘要与隔离。'
            result.append(self._row(ident,name,installed=installed,enabled=enabled,
                health='ready' if enabled else 'unavailable',activity='busy' if running else 'offline' if not enabled else 'standby' if used else 'unused',
                active=running,count=len(used),last_used=used[0][1].get('updated_at') if used else None,version=version,message=message))
        return result

    def _workspace(self):
        rows=self._read(Path(self.core.data_dir)/'workspace.db',
                        "SELECT completed_at FROM outputs WHERE state='SAVED' ORDER BY rowid DESC LIMIT 1000")
        return [self._row('workspace','项目资源与文件',installed=True,enabled=True,activity='on_demand',
                         version=__version__,count=len(rows),last_used=rows[0][0] if rows else None,
                         message='文件树与文本编辑按需执行；近期次数仅统计回答导出，无常驻子进程。')]

    def _store(self, ident, name, filename, query, flag, label, message, *, versions=(1,)):
        """Observe metadata only. Never initialize, migrate or read record bodies."""
        enabled = bool(self.activity().get(flag, False))
        row = self._row(ident, name, installed=True, enabled=enabled, version=__version__,
                        health='ready' if enabled else 'unavailable',
                        activity='on_demand' if enabled else 'not_integrated', message=message)
        path = policy.safe_path(Path(self.core.data_dir) / filename, must_exist=False)
        # Missing lazy storage is expected, whereas an unreadable existing DB is not.
        if not path.exists():
            row.update(storage_state='not_created', record_count=0, records_label=label, last_changed=None)
            row['message'] += ' 存储按首次使用创建；观察不会创建数据库。'
            return row
        path = policy.safe_path(path, directory=False)
        if path.stat().st_nlink != 1:
            raise ValueError('Linked database')
        for suffix in ('-wal', '-shm', '-journal'):
            policy.safe_path(str(path) + suffix, must_exist=False)
        with closing(sqlite3.connect(path.absolute().as_uri()+'?mode=ro', uri=True, timeout=.05)) as db:
            db.execute('PRAGMA query_only=ON')
            deadline = time.monotonic() + .15
            db.set_progress_handler(lambda: int(time.monotonic() > deadline), 100)
            if db.execute('PRAGMA user_version').fetchone()[0] not in versions:
                raise ValueError('Unsupported store version')
            records = db.execute(query).fetchall()
        row.update(storage_state='ready', record_count=len(records), records_label=label,
                   last_changed=max((r[0] for r in records), default=None))
        return row

    def _memory(self):
        return [self._store('memory', '明确事实记忆', 'memory.db',
                'SELECT updated_at FROM facts WHERE deleted=0 ORDER BY rowid DESC LIMIT 1000',
                'memory', '已保存事实', '已接入明确记忆、分类用途与候选来源；此处不核对原文有效性，不表示自动提取或完整长期记忆。', versions=(1,2,3))]

    def _knowledge(self):
        return [self._store('knowledge', '项目资料检索', 'project-sources.db',
                'SELECT updated_at FROM sources WHERE deleted=0 ORDER BY rowid DESC LIMIT 1000',
                'knowledge', '有效资料登记', '已接入有界跨项目词法检索；观察不读原文，不验证每份源文件是否仍可访问。')]

    def _mcp(self):
        return [self._store('mcp-registration', 'MCP 登记', 'extensions.db',
                "SELECT updated_at FROM entries WHERE deleted=0 AND kind='mcp' ORDER BY rowid DESC LIMIT 1000",
                'extensions', '有效 MCP 登记', '只观察登记存储；不连接远端、不启动命令、不读取端点或凭据。')]

    def _skills(self):
        from .skills import catalog
        data, _ = catalog()
        complete=sum('presentation' in s for s in data['skills'])
        return [self._row('native-skills', '原生技能工作流', installed=True, enabled=True,
                         activity='on_demand', count=complete,count_scope='catalog',
                         message=str(complete)+' 个完整技能，具体执行范围以已准入目录为准；内部组件和未接通条目不计为用户技能。'),
                self._store('skill-registration', '技能登记', 'extensions.db',
                "SELECT updated_at FROM entries WHERE deleted=0 AND kind='skill' ORDER BY rowid DESC LIMIT 1000",
                'extensions', '有效技能登记', '只观察登记存储；不读取 SKILL.md，不运行技能。')]

    def _sample_report(self):
        records=self._read(Path(self.core.data_dir)/'control.db',
            "SELECT task_id,json_extract(document,'$.status') FROM actions WHERE json_extract(document,'$.capability_id')='sample.report.v1' ORDER BY rowid DESC LIMIT 1000")
        active=set(self.activity().get('tasks',[]))
        running=sum(ident in active for ident,_ in records)
        installed=(self.root/'runtime/node-host/jarvis_core/sample_tasks.py').is_file()
        enabled=installed and bool(self.activity().get('computer'))
        return [self._row('sample-report','自然语言目录报告',installed=installed,enabled=enabled,
            health='ready' if enabled else 'unavailable',activity='busy' if running else 'on_demand' if enabled else 'not_integrated',
            active=running,count=len(records),version=__version__,
            message='目录报告使用模型规划、固定 Worker 与本机统计；原生技能和 Context7 文档工具有各自的显式任务入口，普通聊天尚无通用工具循环。')]

    def _assets(self, component):
        manifest=json.loads((self.root/'config/model-profiles/local-candidates.json').read_text(encoding='utf-8'))
        model_root=self.model_root or Path(manifest['default_root'])
        files=[f for f in manifest['files'] if f['component']==component]
        present=0
        for f in files:
            relative=Path(f['path'])
            if relative.is_absolute() or '..' in relative.parts: raise ValueError('Invalid component path')
            try:
                path=policy.safe_path(model_root/relative,directory=False)
                present += path.stat().st_size == f['size_bytes']
            except (OSError,policy.CoreError): pass
        return {'installed':bool(files) and present==len(files), 'message':f'文件大小匹配 {present}/{len(files)}；未加载权重或做本轮摘要验证。'}

    def _speech(self):
        try: engine=metadata.version('sherpa-onnx')
        except metadata.PackageNotFoundError: engine=None
        result=[]
        for ident, name, component in (('stt','语音识别 STT','sensevoice-int8'),('tts','语音合成 TTS','vits-aishell3-low'),
                                        ('speaker','声纹特征','campplus-zh'),('vad','语音活动检测','silero-vad')):
            assets=self._assets(component);installed=bool(engine) and assets['installed']
            result.append(self._row(ident,name,installed=installed,enabled=False,health='ready' if installed else 'unavailable',
                          activity='not_integrated',version=component+' / '+(engine or '引擎未安装'),update='external',
                          message=assets['message']+' 当前仅文件诊断，未接入工作台实时语音；不推断外部诊断进程状态。'))
        status = self.speech.snapshot()
        row = self._row('cosyvoice3', 'CosyVoice3 克隆与情绪语音', installed=status['installed'],
            enabled=status['owned'], health='ready' if status['installed'] and status['state'] != 'failed' else 'unavailable',
            activity='busy' if status['busy'] else 'running' if status['owned'] else 'on_demand',
            active=int(status['busy']), count=status['uses'], count_scope='host_lifetime',
            version='Fun-CosyVoice3-0.5B-2512 / CPU', update='external',
            message='独立 CPU 组件；打开本页不加载权重。下方可加载、停止、试听和下载；启动时校验固定摘要。')
        row['runtime'] = status; result.append(row)
        status = self.fast_speech.snapshot()
        row = self._row('zipvoice', 'ZipVoice 备用语音', installed=status['installed'],
            enabled=status['owned'], health='ready' if status['installed'] and status['state'] != 'failed' else 'unavailable',
            activity='busy' if status['busy'] else 'running' if status['owned'] else 'on_demand',
            active=int(status['busy']), count=status['uses'], count_scope='host_lifetime',
            version='ZipVoice-Distill int8 / CPU / 4 steps', update='external',
            message='备用组件，默认不启动；需要时手动加载，用完可停止释放内存。不提供通用文字情绪指令。')
        row['runtime'] = status; result.append(row)
        status = self.primary_speech.snapshot()
        row = self._row('qwen-tts', 'Qwen 主力语音', installed=status['installed'],
            enabled=status['owned'], health='ready' if status['installed'] and status['state'] != 'failed' else 'unavailable',
            activity='busy' if status['busy'] else 'running' if status['owned'] else 'on_demand',
            active=int(status['busy']), count=status['uses'], count_scope='host_lifetime',
            version='Qwen3-TTS 1.7B Q5_K / ' + status['device'], update='external',
            message='主力语音；9 种预设音色与情绪指令。手动加载，可独立停止；内存和 GPU 分项见主力面板。')
        row['runtime'] = status; result.append(row)
        return result

    def _releases(self):
        path=self.releases_root/'releases.db'
        selection=self._read(path,'SELECT active,previous FROM selection WHERE singleton=1')
        rows=self._read(path,'SELECT id,version,state,created_at FROM releases ORDER BY created_at DESC LIMIT 40')
        return {'active':selection[0][0] if selection else None,'previous':selection[0][1] if selection else None,
                'releases':[dict(zip(('id','version','state','created_at'),r)) for r in rows]}

    def submit(self, payload):
        if not isinstance(payload,dict): raise ModuleError('维护请求必须是对象。')
        action=payload.get('action')
        fields={'install':{'action','archive'},'health':{'action','release_id'},
                'select':{'action','release_id'},'rollback':{'action'},
                'local-start':{'action'},'local-stop':{'action'}}
        if not isinstance(action,str) or action not in fields or set(payload)!=fields[action]: raise ModuleError('不支持的维护操作或字段。')
        if action=='install':
            archive=payload['archive']
            if not isinstance(archive,str) or len(archive)>4096 or not Path(archive).is_absolute() or Path(archive).suffix.lower()!='.zip':
                raise ModuleError('请选择本机可信的绝对路径 ZIP 运行包。')
        if action in {'health','select'} and (not isinstance(payload['release_id'],str) or not re.fullmatch(r'release-[0-9a-f]{24}',payload['release_id'])):
            raise ModuleError('候选版本标识无效。')
        self.core.assert_running()
        with self.lock:
            if self.closed: raise ModuleError('本实例正在退出。')
            if self.job is not None: raise ModuleError('已有维护操作在执行；聊天和任务不受此限制。')
            row={'id':uuid.uuid4().hex,'action':action,'status':'RUNNING','started_at':now(),
                 'release_id':payload.get('release_id'),'message':'正在处理；当前运行版本保持不变。'}
            previous=self.jobs
            self.jobs=self.jobs[-19:]+[row]
            try:self._save_jobs()
            except Exception:
                self.jobs=previous
                raise
            self.job=row['id']
            try:threading.Thread(target=self._maintain,args=(dict(payload),row),name='jarvis-module-maintenance',daemon=True).start()
            except Exception:
                self.job=None;row.update(status='FAILED',message='维护线程未启动，未执行操作。');self._save_jobs()
                raise
            return copy.deepcopy(row)

    def _maintain(self, payload, row):
        update={'status':'UNKNOWN','finished_at':now(),'message':'维护意外中断，请核对候选版本；没有自动重放。'}
        try:
            from .releases import RuntimeSlots
            self.core.assert_running()
            action=payload['action']
            if action in {'local-start','local-stop'}:
                message = self.local_model.start() if action=='local-start' else self.local_model.stop()
                update={'status':'SUCCEEDED','finished_at':now(),'message':message}
                return
            slots=RuntimeSlots(self.releases_root)
            if action=='install': result=slots.install(Path(payload['archive']))
            elif action=='health': result=slots.health(payload['release_id'])
            else: result=slots.select(payload.get('release_id'),rollback=action=='rollback')
            failed=result.get('state')=='failed'
            update={'status':'FAILED' if failed else 'SUCCEEDED', 'finished_at':now(),
                    'release_id':result.get('id',result.get('active',payload.get('release_id'))),
                    'message':'候选验证失败，保留当前版本。' if failed else
                              '已更新下次启动选择；当前源码服务不会自动切换。' if action in {'select','rollback'} else
                              '候选已登记，下一步运行验证。' if action=='install' else '候选验证通过，可以选择下次启动版本。'}
        except Exception as exc:
            from .local_model import LocalModelError
            update={'status':'FAILED','finished_at':now(),'error_type':type(exc).__name__,
                    'message':str(exc) if isinstance(exc,LocalModelError) else
                    '本地模型操作未完成：请检查文件摘要、内存、端口和运行环境；未自动下载或重试。' if payload['action'].startswith('local-') else
                    '维护未完成：请检查包、版本状态或正在占用的运行槽位。当前服务保持运行。'}
        finally:
            with self.lock:
                row.update(update);self.job=None;self.updated=0
                try:self._save_jobs()
                except (OSError,policy.CoreError):row.update(status='UNKNOWN',message='维护回执未能持久保存，请核对版本列表后再操作。')
