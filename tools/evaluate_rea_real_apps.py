"""Fixed public source samples; download only text under src, never execute the apps."""
import argparse
import hashlib
import io
import json
import re
from pathlib import Path
import sys
import tarfile
import tempfile
import time

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host')]
SAMPLES = [
    ('webtorrent/webtorrent-desktop', '6c91af345d4bd62603d7063ea02a50394d64af0d'),
    ('agalwood/Motrix', '7012040fec926e16fe8f6c403cf038527f5c18b9'),
]


def fetch(destination):
    records = []
    for repo, commit in SAMPLES:
        target = destination/repo.split('/')[-1]/commit
        target.mkdir(parents=True, exist_ok=True)
        url = f'https://codeload.github.com/{repo}/tar.gz/{commit}'
        with httpx.stream('GET', url, timeout=60, follow_redirects=False) as response:
            response.raise_for_status()
            raw = bytearray()
            for chunk in response.iter_bytes():
                raw.extend(chunk)
                if len(raw) > 64*1024*1024:
                    raise RuntimeError('Archive limit exceeded')
        files = []
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:gz') as archive:
            for member in archive:
                path = Path(*member.name.split('/')[1:])
                if not member.isfile() or '..' in path.parts or path.is_absolute():
                    continue
                if not (path.parts and path.parts[0]=='src' or str(path) in {'LICENSE','LICENSE.txt','package.json'}):
                    continue
                if member.size > 2*1024*1024 or path.suffix.lower() not in {'.js','.json','.vue','.html','.css','.txt',''}:
                    continue
                out = target/path
                if not out.resolve().is_relative_to(target.resolve()):
                    raise RuntimeError('Source path escaped root')
                content = archive.extractfile(member).read()
                content.decode('utf-8')
                out.parent.mkdir(parents=True, exist_ok=True)
                if out.exists() and out.read_bytes() != content:
                    raise RuntimeError('Existing pinned source changed')
                out.write_bytes(content)
                files.append({'path': path.as_posix(), 'bytes':len(content),'sha256':hashlib.sha256(content).hexdigest()})
        records.append({'repository':repo,'commit':commit,'archive_url':url,'archive_sha256':hashlib.sha256(raw).hexdigest(),
                        'root':str(target),'selection':'src text + license + package.json; no dependencies/bundles', 'files':files})
        print(repo, len(files), 'files', flush=True)
    output = destination/'sources.json'
    output.write_text(json.dumps(records,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(output)


def analyze(destination):
    from jarvis_core.service import CoreService
    from jarvis_core.workspace import WorkspaceService
    from jarvis_core.rea import analyze as run
    from jarvis_core.policy import CoreError
    records = json.loads((destination/'sources.json').read_bytes())
    outcomes = []
    with tempfile.TemporaryDirectory() as temporary:
        core = CoreService(Path(temporary)/'data')
        seed = Path(temporary)/'seed'; seed.mkdir()
        core.initialize(seed)
        for record in records:
            project = WorkspaceService(core).open_project({'path':record['root']})
            for target in ['src', 'src/main']:
                started=time.monotonic()
                key=record['repository'].split('/')[-1]+'-'+target.replace('/','-')
                row = {k:record[k] for k in ('repository','commit','archive_sha256')}
                row.update(target=target,model_calls=0,target_executed=False)
                try:
                    result=run(core,{'project_id':project['id'],'target_path':target,'prompt':'分析软件结构','focus':''},lambda:None)
                    evidence = destination/(key+'-evidence.json')
                    evidence.write_text(json.dumps(result.pop('evidence'),ensure_ascii=False),encoding='utf-8')
                    (destination/(key+'-report.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
                    row.update(status='analyzed',analysis=result['analysis'],input_manifest=result['input_manifest'],evidence_path=str(evidence))
                    print(key, 'analyzed',len(result['input_manifest']['files']),'files',flush=True)
                except CoreError as exc:
                    row.update(status='rejected',error={'code':exc.code,'message':str(exc)})
                    print(key,exc.code,str(exc),flush=True)
                row['seconds']=round(time.monotonic()-started,2)
                outcomes.append(row)
    (destination/'analysis-results.json').write_text(json.dumps(outcomes,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def audit(destination, live=False):
    from datetime import datetime, timezone
    from jarvis_core import __version__, rea, rea_focus, rea_evidence, rea_explanation, policy
    from jarvis_core.service import CoreService
    from jarvis_core.skill_tasks import SkillTaskService
    sources=json.loads((destination/'sources.json').read_bytes())
    attempts=json.loads((destination/'analysis-results.json').read_bytes())
    report={'version':__version__,'observed_at':datetime.now(timezone.utc).isoformat(),
            'scope':'two pinned public Electron main-process source directories; not installed binaries or whole-app accuracy',
            'target_executed':False,'cases':[],'rejected_full_scopes':[{k:r[k] for k in ('repository','commit','target','error','seconds')} for r in attempts if r['status']=='rejected']}
    with tempfile.TemporaryDirectory() as temporary:
        base=Path(temporary);seed=base/'seed';seed.mkdir();core=CoreService(base/'data');core.initialize(seed)
        for source in sources:
            name=source['repository'].split('/')[-1];root=Path(source['root'])/'src/main'
            # Independently enumerate visible literal registrations in pinned source.
            expected=[]
            for path in sorted(root.rglob('*.js')):
                text=path.read_text(encoding='utf-8')
                for match in re.finditer(r"ipcMain\.(on|once|handle|handleOnce)\s*\(\s*['\"]([^'\"]+)['\"]",text):
                    expected.append((path.relative_to(root).as_posix(),text[:match.start()].count('\n')+1,match[1],match[2]))
            assert len(expected)==(29 if name=='webtorrent-desktop' else 3), 'Pinned ground truth changed'
            result=json.loads((destination/(name+'-src-main-report.json')).read_bytes())
            evidence=json.loads((destination/(name+'-src-main-evidence.json')).read_bytes())
            assert policy.digest(policy.canonical_json(evidence).encode())==result['runtime']['evidence_digest']
            for row in result['input_manifest']['files']:
                assert policy.digest((root/row['path']).read_bytes())==row['digest']
            observed=[]
            for node in evidence['normalized_result']['graph']['nodes']:
                if node['kind']!='ipc-handler':continue
                for observation in node['observations']:
                    location=observation['evidence']['location']['value'];props=observation['properties']
                    observed.append((location['source'],location['start']['line'],props['operation'],props['channel']))
            missing=sorted(set(expected)-set(observed));unexpected=sorted(set(observed)-set(expected))
            focus='openFiles' if name=='webtorrent-desktop' else 'get-app-config'
            view=rea.projection(evidence);view['focus']=rea_focus.inspect(evidence,{'focus':focus})
            old_relations={'invokes','maps_to','imports','loads'}
            old_matches=sum(e['relation'] in old_relations and rea_focus.matches(e,focus) for e in evidence['normalized_result']['graph']['edges'])
            pages=rea_evidence.page(evidence,result,'links',query=focus)
            args={'prompt':'解释 '+focus+' 的静态注册位置与证据能确定的事实；明确当前证据未包含哪些实现细节。','model':'','focus':focus}
            result.update(analysis=view,evidence=evidence)
            packet,_=rea_explanation.packet(result,args)
            row={'repository':source['repository'],'commit':source['commit'],'source_url':'https://github.com/'+source['repository']+'/tree/'+source['commit']+'/src/main',
                 'archive_sha256':source['archive_sha256'],'target':'src/main','input_files':len(result['input_manifest']['files']),
                 'input_digest':result['input_manifest']['digest'],'evidence_digest':result['runtime']['evidence_digest'],
                 'ground_truth_method':'literal ipcMain on/once/handle/handleOnce registrations independently counted in pinned files; source locations inspected',
                 'expected_handlers':expected,'observed_handlers':observed,'missing':missing,'unexpected':unexpected,
                 'focus':focus,'before_focus_links':old_matches,'after_focus_links':view['focus']['link_count'],
                 'source_page_matches':pages['total'],'explanation_sources':len(packet['sources']),
                 'limitations':['Only main-process files are in this successful scope; renderer-to-main pairing was not evaluated.',
                    'No runtime reachability, security, download behavior or private server reconstruction is proven.',
                    'Library dependencies, bundled aliases, extensionless ESM imports and dynamic dispatch may remain unresolved.',
                    'This handler-level count is not whole-application recall or general accuracy.']}
            if live:
                sys.path.insert(0,str(ROOT/'tools'))
                from eval_policy import default_route
                args['model']=default_route();deadline=time.monotonic()+90
                def check():
                    if time.monotonic()>deadline:raise policy.CoreError('limit_exceeded','evaluation deadline')
                try:row['explanation']=rea_explanation.explain(SkillTaskService(core),result,args,check)
                except Exception as exc:row['explanation_error']={'code':getattr(exc,'code','failed'),'message':str(exc)}
                print(name, row.get('explanation',{}).get('status') or row.get('explanation_error'),flush=True)
            report['cases'].append(row)
    report['model_calls']=sum(r.get('explanation',{}).get('model_calls',0) for r in report['cases'])
    report['handler_check_passed']=all(not r['missing'] and not r['unexpected'] for r in report['cases'])
    report['focus_regression_passed']=all(r['before_focus_links']==0 and r['after_focus_links']==r['source_page_matches']==r['explanation_sources']==1 for r in report['cases'])
    report['status']='bounded_scope_verified' if report['handler_check_passed'] and report['focus_regression_passed'] else 'needs_review'
    path=ROOT/'evals/reports/rea-real-apps-2026-10-18.json'
    path.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8');print(path,report['status'])


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fetch',action='store_true')
    parser.add_argument('--analyze',action='store_true')
    parser.add_argument('--audit',action='store_true')
    parser.add_argument('--live',action='store_true',help='two official-route model explanations over verified public evidence')
    parser.add_argument('--root',type=Path,default=Path('H:/JarvisData/evals/rea-real-apps'))
    args=parser.parse_args()
    if args.fetch: fetch(args.root)
    if args.analyze: analyze(args.root)
    if args.audit: audit(args.root,args.live)
