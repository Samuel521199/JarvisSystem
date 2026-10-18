"""Self-owned acceptance corpus for usefulness, not an arbitrary-app benchmark.

Runs the installed static parser only. No target execution or model calls.
Candidate probes keep the same process bounds and save raw evidence outside
the production 2 MiB receipt, to measure the value of a future delivery change.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'runtime/node-host'))
from jarvis_core import __version__, rea
from jarvis_core.policy import CoreError
from jarvis_core.rea_process import run
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService


def sources(channels=1, *, dynamic=False, dead=False):
    main = "const {ipcMain}=require('electron');\n"
    preload = "const {contextBridge,ipcRenderer}=require('electron');\n"
    if dynamic: preload += "const prefix=process.env.APP_PREFIX;\n"
    members = []
    for i in range(channels):
        channel = 'fixture:op'+str(i)
        body = f"ipcMain.handle('{channel}',(_event,a,b)=>a+b);"
        main += (f'if(false){{{body}}}' if dead else body) + '\n'
        value = f"prefix+'{i}'" if dynamic else repr(channel)
        members.append(f"op{i}:(a,b)=>ipcRenderer.invoke({value},a,b)")
    preload += "contextBridge.exposeInMainWorld('fixture',{\n" + ',\n'.join(members) + '\n});\n'
    return {'package.json':json.dumps({'name':'jarvis-rea-effectiveness-fixture','version':'1.0.0','main':'main.js'}),
            'main.js':main, 'preload.js':preload}


def main():
    output = ROOT/'artifacts/rea-effectiveness'; output.mkdir(parents=True, exist_ok=True)
    runtime, runtime_digest = rea.runtime(verify=True)
    specs = [('literal_1', sources()), ('literal_5',sources(5)), ('literal_12',sources(12)), ('literal_20',sources(20)),
             ('dynamic_channel',sources(dynamic=True)), ('dead_handler',sources(dead=True)),
             ('dist_only',{'package.json':json.dumps({'name':'dist-fixture','main':'dist/main.js'}),
                           **{'dist/'+k:v for k,v in sources().items() if k!='package.json'}}),
             ('many_files',{'package.json':json.dumps({'name':'many-fixture','main':'file0.js'}),
                            **{f'file{i}.js':f'exports.value = {i};\n' for i in range(129)}})]
    cases = []
    with tempfile.TemporaryDirectory(prefix='jarvis-rea-effectiveness-') as temporary:
        root = Path(temporary); project = root/'project'; project.mkdir()
        core = CoreService(root/'data'); core.initialize(project)
        registered = WorkspaceService(core).open_project({'path':str(project)})
        for name, body in specs:
            target = project/name; target.mkdir()
            for path, content in body.items():
                file = target/path; file.parent.mkdir(parents=True,exist_ok=True); file.write_text(content,encoding='utf-8')
            start = time.perf_counter()
            case = {'name':name,'fixture_files':len(body),'fixture_bytes':sum(len(v.encode('utf-8')) for v in body.values()),
                    'fixture_sha256':{k:hashlib.sha256(v.encode('utf-8')).hexdigest() for k,v in body.items()}}
            try:
                result = rea.analyze(core,{'project_id':registered['id'],'target_path':name,'prompt':'分析 Electron 应用目录的 IPC 调用链'},lambda:None)
                case.update(status='SUCCEEDED',summary=result['analysis']['summary'],statistics=result['analysis']['statistics'],
                            key_links_omitted=result['analysis']['key_links_omitted'],runtime=result['runtime'],
                            evidence_bytes=len(json.dumps(result['evidence'],ensure_ascii=False).encode('utf-8')))
                (output/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            except CoreError as exc: case.update(status='FAILED',error=exc.code,message=str(exc))
            case['end_to_end_seconds']=round(time.perf_counter()-start,3)
            cases.append(case); print(json.dumps({k:v for k,v in case.items() if k not in {'fixture_sha256','summary','runtime','statistics'}},ensure_ascii=True),flush=True)
        # Isolate host delivery limits from the parser's actual ability.
        candidates = []
        for name in ('literal_20','dist_only'):
            target = project/name
            argv=[str(runtime/'node.exe'),'--max-old-space-size=384',str(runtime/'node_modules/rea-agents/scripts/rea.mjs'),
                  'analyze-javascript-application',str(target),'--artifact-format','directory','--max-heap-mb','256',
                  '--analysis-timeout-ms','15000','--json']
            result=run(argv,root,lambda:None,output_limit=8*1024*1024)
            evidence=json.loads(result['stdout']) if result['exit_code']==0 else None
            view=rea.projection(evidence) if evidence else None
            row={'name':name,'candidate_only':True,'production_limits_unchanged':True,'exit_code':result['exit_code'],
                 'raw_bytes':len(result['stdout']),'summary':view['summary'] if view else None,'process':result['process']}
            candidates.append(row)
            (output/(name+'-candidate.json')).write_bytes(result['stdout'])
            print(json.dumps(row,ensure_ascii=True),flush=True)
        by_name={c['name']:c for c in cases}; candidate_by_name={c['name']:c for c in candidates}
        checks={
            'literal_1_pair':by_name['literal_1'].get('summary',{}).get('ipc',{}).get('paired_renderer_transmissions')==1,
            'literal_5_pairs':by_name['literal_5'].get('summary',{}).get('ipc',{}).get('paired_renderer_transmissions')==5,
            'literal_12_pairs':by_name['literal_12'].get('summary',{}).get('ipc',{}).get('paired_renderer_transmissions')==12,
            'dynamic_unresolved':by_name['dynamic_channel'].get('summary',{}).get('ipc',{}).get('dynamic_channel_operations')==1 and by_name['dynamic_channel'].get('summary',{}).get('ipc',{}).get('paired_renderer_transmissions')==0,
            'dead_handler_static_pair_not_runtime_proof':by_name['dead_handler'].get('summary',{}).get('ipc',{}).get('paired_renderer_transmissions')==1,
            'dist_excluded_by_host':by_name['dist_only'].get('error')=='rea_input_unsupported',
            'file_count_rejected_by_host':by_name['many_files'].get('error')=='rea_input_limit',
            'output_limit_rejected_by_host':by_name['literal_20'].get('error')=='rea_output_limit',
            'same_20_channels_parse_with_larger_evidence_sink':candidate_by_name['literal_20']['exit_code']==0 and candidate_by_name['literal_20']['summary']['ipc']['paired_renderer_transmissions']==20,
            'same_dist_tree_parse_without_host_exclusion':candidate_by_name['dist_only']['exit_code']==0 and candidate_by_name['dist_only']['summary']['ipc']['paired_renderer_transmissions']==1,
        }
        record={'version':__version__,'observed_at':datetime.now(timezone.utc).isoformat(),'scope':'self-owned synthetic JS/Electron corpus',
                'runtime_manifest_digest':runtime_digest,'model_calls':0,'target_executed':False,'cases':cases,'candidate_probes':candidates,
                'checks':checks,'measurement_checks_passed':all(checks.values()),
                'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['runtime/node-host/jarvis_core/rea.py','runtime/node-host/jarvis_core/rea_process.py','tools/evaluate_rea_effectiveness.py']},
                'limitations':['No real third-party application, ASAR or native binary was analyzed.','Candidate probes are experiments, not production integration or end-to-end delivery.','Static pairs do not prove runtime reachability.','No model quality or time-saving claim measured.']}
        (ROOT/'evals/reports/rea-effectiveness-2026-10-18.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        if not all(checks.values()): raise SystemExit('An evaluation hypothesis did not match observation; inspect the report')


if __name__=='__main__':main()
