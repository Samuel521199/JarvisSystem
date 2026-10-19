"""Real Codex development scenarios and offline executable-artifact reconstruction."""
import argparse
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtime/node-host'), str(ROOT/'adapters/computer-use')]
from jarvis_core import __version__, policy
from jarvis_core.service import CoreService
from jarvis_core.workspace import WorkspaceService
from jarvis_core.conversation_tasks import ConversationTasks
from jarvis_computer.web import ComputerWeb
from jarvis_core.coding_settings import CodingSettings
from jarvis_core.coding_workflow import apply_result
from jarvis_core.coding_build import ZIPAPP
from jarvis_core.network_policy import NetworkPolicy


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--directory', required=True, type=Path)
    parser.add_argument('--dataset', type=Path, default=ROOT/'evals/cases/k3-coding-v2.json')
    parser.add_argument('--improvement', action='store_true', help='Exercise saved improvement -> coding -> verified receipt')
    parser.add_argument('--without-guides', action='store_true', help='Controlled evaluation only: same adapter and budget, no engineering guide text')
    args = parser.parse_args(); root = args.directory.resolve()
    if root.exists(): parser.error('Use a new directory; unknown outcomes must not be replayed')
    root.mkdir(parents=True)
    dataset = args.dataset.resolve(); raw = dataset.read_bytes()
    cases = json.loads(raw)['cases']
    result = {'version': __version__, 'started': datetime.now(timezone.utc).isoformat(),
              'dataset_digest': policy.digest(raw), 'status': 'running', 'cases': [], 'engineering_guides':not args.without_guides}
    def save(): (root/'report.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    save()
    for case in cases:
        from jarvis_core.coding_bundle import layout
        from jarvis_core import coding_package,coding_js
        selected=case.get('recipe',ZIPAPP)
        (coding_js.layout if selected==coding_js.RECIPE else coding_package.layout if selected in coding_package.RECIPES else layout)(list(case['files']), case['entry'])
        if not case['id'].replace('-', '').isalnum(): raise ValueError('Unsafe fixture identifier')
        folder = root/case['id']; source = folder/'project'; source.mkdir(parents=True)
        for name, content in case['files'].items():
            if name in case.get('new_paths',[]):continue
            target = source/name; target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding='utf-8')
        originals = {p: (source/p).read_bytes() if (source/p).exists() else None for p in case['files']}
        core = CoreService(folder/'data'); core.initialize(source)
        workspace = WorkspaceService(core); project = workspace.open_project({'path': str(source)})
        settings = CodingSettings(core); settings.write({**settings.read(), 'enabled': True, 'reasoning': 'medium'})
        manager = ComputerWeb(core, None); bridge = ConversationTasks(core, manager)
        row = {'id': case['id'], 'category': case.get('category', 'acceptance'), 'status': 'running'}
        result['cases'].append(row); save()
        guide_patch=None
        if args.without_guides:
            from unittest.mock import patch
            from jarvis_core import coding_task
            original_composition=coding_task.composition
            def no_guides(service,arguments):
                decisions,guides=original_composition(service,arguments)
                return decisions,{k:'' for k in guides}
            guide_patch=patch.object(coding_task,'composition',no_guides);guide_patch.start()
        try:
            cid = uuid.uuid4().hex
            payload = {'mode': 'skill', 'request_id': 'web-'+uuid.uuid4().hex,
                'prompt': case['goal'], 'project_id': project['id'], 'skill_id': 'matt-pocock.tdd',
                'paths': list(case['files']), 'entrypoint': case['entry'], 'coding': True,
                'coding_provider': 'codex', 'model': 'auto', 'build_recipe': case.get('recipe', ZIPAPP),
                'cases': case['public'], 'heldout_cases': case['private']}
            if case.get('new_paths'):payload['new_paths']=case['new_paths']
            if args.improvement:
                from jarvis_core.conversations import ConversationStore
                from jarvis_core.coding_demand import CodingDemands
                ConversationStore(core).put(cid, {'revision': 0, 'document': {
                    'title': '编码改进验收', 'project_id': project['id'], 'context_note': '', 'messages': [
                        {'role': 'user', 'content': case['goal'], 'meta': '', 'short_meta': '',
                         'attachments_omitted': False, 'incomplete': False}]}})
                demands = CodingDemands(core, bridge)
                proposal = demands.propose(cid, {'request_id': uuid.uuid4().hex, 'prompt': case['goal'],
                    'coding': {k: payload[k] for k in ('paths','entrypoint','coding_provider','model','build_recipe','cases','heldout_cases','new_paths') if k in payload}})
                assert proposal['status'] == 'PROPOSED' and proposal['task_id'] is None
                row['proposal'] = proposal; save()
                item = demands.start(cid, proposal['id'], {})
            else:
                item = bridge.submit(cid, payload)
            row.update(task=item, conversation_id=cid, project=project); save()
            deadline = time.monotonic()+310
            while time.monotonic() < deadline:
                detail = bridge.detail(cid, item['task_id'])
                if detail['task']['status'] not in {'READY', 'RUNNING', 'CANCELLING'}: break
                time.sleep(.2)
            row['task_status'] = detail; save()
            if detail['action_status'] != 'CONFIRMED': raise RuntimeError('Task not confirmed; no automatic replay')
            report = json.loads(bridge.artifact(cid, item['task_id'])); value = report['coding']
            (folder/'delivery.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
            row.update(passed=value['passed'], baseline_passed=value['baseline']['passed'],
                       validation=value['validation'], build_validation=value.get('build_validation'),
                       model_receipts=[a['model'] for a in value['attempts']])
            save(); assert value['passed']
            if args.improvement:
                done = CodingDemands(core, bridge).bound(cid, proposal['id'])
                assert done['status'] == 'SUCCEEDED' and done['result']['verified']
                assert done['result']['artifact_digest'] == detail['artifact']['digest']
                assert not done['result']['automatically_applied']
                assert demands.start(cid, proposal['id'], {})['task_id'] == item['task_id']
                row['improvement_result'] = done
            assert all(((source/p).read_bytes() if (source/p).exists() else None)==s for p,s in originals.items())
            row['apply'] = apply_result(core, report, 'apply')
            assert all((source/p).read_text()==s for p,s in value.get('candidates',{case['entry']:value['candidate']}).items())
            row['rollback'] = apply_result(core, report, 'rollback')
            assert all(((source/p).read_bytes() if (source/p).exists() else None)==s for p,s in originals.items())
            row['original_bytes_restored'] = True
            artifact = folder/value['build']['filename']; artifact.write_bytes(base64.b64decode(value['build']['base64']))
            checks = folder/'private-cases.json'; checks.write_text(json.dumps(case['private'], ensure_ascii=False), encoding='utf-8')
            NetworkPolicy(core.data_dir).change(True, 0)
            rebuilt = folder/'rebuilt.pyz'; evidence = folder/'offline-build.json'
            subprocess.run([sys.executable, '-X', 'utf8', '-B', str(ROOT/'tools/coding_build.py'),
                '--archive', str(artifact), '--sha256', value['build']['sha256'], '--cases', str(checks),
                '--output', str(rebuilt), '--report', str(evidence)], capture_output=True, timeout=45, check=True)
            assert rebuilt.read_bytes() == artifact.read_bytes()
            row['offline_build'] = json.loads(evidence.read_text(encoding='utf-8'))
            row['artifact_bytes'] = artifact.stat().st_size; row['status'] = 'passed'; save()
            print(json.dumps({'case': row['id'], 'status': row['status'], 'calls': len(value['attempts'])}), flush=True)
        except Exception as exc:
            row.update(status='failed', error=type(exc).__name__+': '+str(exc)); result['status']='failed'; save(); raise
        finally:
            manager.close()
            if guide_patch:guide_patch.stop()
    result['status'] = 'passed'; save()
    print(json.dumps({'status': result['status'], 'report': str(root/'report.json')}))


if __name__ == '__main__': main()
