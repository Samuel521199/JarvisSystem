"""Compare the improved adapter against the exact frozen 0.1.45 fixtures."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'tools'), str(ROOT/'runtime/node-host')]
from evaluate_rea_effectiveness import sources
from jarvis_core import __version__, rea
from jarvis_core.policy import CoreError
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService


def main():
    baseline_path = ROOT/'evals/reports/rea-effectiveness-2026-10-18.json'
    baseline = json.loads(baseline_path.read_bytes())
    specs = [('literal_1', sources()), ('literal_5', sources(5)), ('literal_12', sources(12)), ('literal_20', sources(20)),
             ('dynamic_channel', sources(dynamic=True)), ('dead_handler', sources(dead=True)),
             ('dist_only', {'package.json': json.dumps({'name':'dist-fixture','main':'dist/main.js'}),
                            **{'dist/'+k:v for k,v in sources().items() if k!='package.json'}}),
             ('many_files', {'package.json': json.dumps({'name':'many-fixture','main':'file0.js'}),
                            **{f'file{i}.js':f'exports.value = {i};\n' for i in range(129)}})]
    output = ROOT/'artifacts/rea-improvement-corpus'; output.mkdir(exist_ok=True)
    cases = []
    with tempfile.TemporaryDirectory(prefix='jarvis-rea-comparison-') as temporary:
        root = Path(temporary); project = root/'project'; project.mkdir()
        core = CoreService(root/'data'); core.initialize(project)
        registered = WorkspaceService(core).open_project({'path':str(project)})
        for name, body in specs:
            expected = next(row for row in baseline['cases'] if row['name']==name)
            hashes = {k:hashlib.sha256(v.encode('utf-8')).hexdigest() for k,v in body.items()}
            assert hashes == expected['fixture_sha256'], 'Frozen inputs changed: '+name
            target = project/name; target.mkdir()
            for path, content in body.items():
                file = target/path; file.parent.mkdir(exist_ok=True, parents=True); file.write_text(content, encoding='utf-8')
            case = {'name':name, 'same_input':True, 'baseline_status':expected['status'],
                    'baseline_error':expected.get('error'), 'fixture_sha256':hashes}
            started = time.perf_counter()
            try:
                result = rea.analyze(core, {'project_id':registered['id'],'target_path':name,
                                           'prompt':'分析 Electron 应用目录的 IPC 调用链'}, lambda:None)
                case.update(status='SUCCEEDED',summary=result['analysis']['summary'],runtime=result['runtime'])
                (output/(name+'.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
            except CoreError as exc: case.update(status='FAILED',error=exc.code)
            case['end_to_end_seconds'] = round(time.perf_counter()-started,3)
            cases.append(case)
            print(json.dumps({k:v for k,v in case.items() if k not in {'fixture_sha256','runtime','summary'}},ensure_ascii=True),flush=True)
    rows = {c['name']:c for c in cases}
    checks = {name+'_pairs':rows[name].get('summary',{}).get('ipc',{}).get('paired_renderer_transmissions')==n
              for name,n in [('literal_1',1),('literal_5',5),('literal_12',12),('literal_20',20),('dist_only',1)]}
    checks.update(dynamic_remains_unknown=rows['dynamic_channel']['summary']['ipc']['paired_renderer_transmissions']==0,
                  dead_code_remains_static_only=rows['dead_handler']['summary']['ipc']['paired_renderer_transmissions']==1,
                  file_budget_preserved=rows['many_files'].get('error')=='rea_input_limit')
    record = {'version':__version__,'observed_at':datetime.now(timezone.utc).isoformat(),
              'baseline_path':str(baseline_path.relative_to(ROOT)),
              'baseline_sha256':hashlib.sha256(baseline_path.read_bytes()).hexdigest(),
              'cases':cases,'checks':checks,'passed':all(checks.values()),'model_calls':0,'target_executed':False,
              'source_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in [
                  'runtime/node-host/jarvis_core/rea.py','runtime/node-host/jarvis_core/rea_process.py',
                  'runtime/node-host/jarvis_core/rea_evidence.py','runtime/node-host/jarvis_core/skill_tasks.py',
                  'tools/evaluate_rea_improvement.py']},
              'limitations':['Synthetic corpus only; not real software success-rate or model accuracy evidence.',
                             'This corpus calls the adapter; receipt/API/UI delivery is separately verified.',
                             'Static links still do not prove runtime reachability.']}
    (ROOT/'evals/reports/rea-improvement-comparison-2026-10-18.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if not record['passed']: raise SystemExit('Comparison failed; inspect retained report')


if __name__=='__main__': main()
