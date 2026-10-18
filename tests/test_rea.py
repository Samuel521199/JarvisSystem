"""Real pinned REA parser, negative boundaries and receipt delivery (no model)."""
import json
import os
from pathlib import Path
import sys
import time
import unittest
import subprocess
import uuid
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tests'), str(ROOT / 'runtime/node-host'), str(ROOT / 'adapters/computer-use')]
import test_skills
from jarvis_core import rea
from jarvis_core.policy import CoreError
from jarvis_core.rea_process import run


def fixture(root):
    root.mkdir(exist_ok=True)
    sources = json.loads((ROOT / 'artifacts/rea-review/probe.json').read_text(encoding='utf-8'))['fixture_sources']
    for name, body in sources.items(): (root / name).write_text(body, encoding='utf-8')


class ReaTests(test_skills.TaskTests):
    # Inherit setup and task helpers, not the original model/renderer cases.
    def setUp(self):
        super().setUp(); fixture(self.source / 'application')
        self.args = {'project_id': self.project['id'], 'target_path': 'application', 'prompt': '分析 Electron 应用目录'}

    def wait(self, item):
        # Real parser + repeated bundle hashing uses the existing 120s task budget.
        from jarvis_core.skill_tasks import TIMEOUT_SECONDS
        return super().wait(item, timeout_seconds=TIMEOUT_SECONDS + 10)

    def test_rea_real_delivery(self):
        item = self.submit(skill_id='rea.software-analysis', prompt=self.args['prompt'], paths=[], target_path='application')
        detail = self.wait(item)
        self.assertEqual(detail['task']['status'], 'SUCCEEDED', detail.get('error'))
        report = json.loads(self.bridge.artifact(self.cid, item['task_id']))
        self.assertEqual(report['analysis']['summary']['context_bridge_apis'], 1)
        self.assertEqual(report['analysis']['summary']['ipc']['paired_renderer_transmissions'], 1)
        self.assertTrue(any(e['properties'].get('channel') == 'jarvis:sum' for e in report['analysis']['key_links']))
        self.assertEqual(report['input_manifest']['digest'], rea.snapshot(self.core, self.args, lambda: None)['digest'])
        self.assertFalse(report['checks']['target_executed']); self.assertFalse(self.model.calls)
        self.assertEqual(Path(report['output']['path']).read_text(encoding='utf-8'), report['text'])
        self.assertTrue(report['runtime']['kill_on_close']); self.assertFalse(report['runtime']['os_sandbox'])
        self.assertNotIn('evidence', report)
        self.assertLess(len(self.bridge.artifact(self.cid, item['task_id'])), 128 * 1024)
        evidence = self.bridge.skill_evidence(self.cid, item['task_id'])
        self.assertEqual(evidence['evidence']['evidence_id'], report['evidence_ref']['evidence_id'])
        page = self.bridge.skill_evidence(self.cid, item['task_id'], section='links', limit=1)
        self.assertEqual(len(page['items']), 1); self.assertEqual(page['next_offset'], 1)
        with self.assertRaises(CoreError): self.bridge.skill_evidence(uuid.uuid4().hex, item['task_id'])
        path = self.core.ledger.artifact_dir / report['evidence_ref']['path']
        raw = path.read_bytes(); path.write_bytes(raw.replace(b'ev_', b'xx_', 1))
        with self.assertRaises(CoreError): self.bridge.skill_evidence(self.cid, item['task_id'])

    def test_rea_large_published_directory_delivery(self):
        sys.path.insert(0, str(ROOT / 'tools'))
        from evaluate_rea_effectiveness import sources
        app = self.source / 'published'; app.mkdir(); (app / 'dist').mkdir()
        body = sources(20)
        (app / 'package.json').write_text(json.dumps({'name':'fixture','main':'dist/main.js'}), encoding='utf-8')
        for name, content in body.items():
            if name != 'package.json': (app / 'dist' / name).write_text(content, encoding='utf-8')
        (app / 'dist' / '.env').write_text('SECRET=excluded', encoding='utf-8')
        item = self.submit(skill_id='rea.software-analysis', paths=[], target_path='published')
        detail = self.wait(item)
        self.assertEqual(detail['action_status'], 'CONFIRMED', detail.get('error'))
        report = detail['report']; self.assertNotIn('evidence', report)
        self.assertEqual(report['analysis']['summary']['ipc']['paired_renderer_transmissions'], 20)
        self.assertGreater(report['runtime']['stdout_bytes'], 1200 * 1024)
        self.assertTrue(any(r['path']=='dist/.env' for r in report['input_manifest']['omitted']))
        self.assertLess(len(self.bridge.artifact(self.cid, item['task_id'])), 256 * 1024)
        offset, rows = 0, []
        while offset is not None:
            page = self.bridge.skill_evidence(self.cid, item['task_id'], section='links', offset=offset, limit=7)
            rows.extend(page['items']); offset = page['next_offset']
        self.assertEqual(len(rows), page['total'])
        self.assertEqual(len({r['value']['edge_id'] for r in rows}), len(rows))
        self.assertGreater(len(rows), 40)
        # The REA exception does not expand the ordinary project editor.
        from jarvis_core.project_files import ProjectFiles
        with self.assertRaises(CoreError): ProjectFiles(self.core).target(self.source, 'published/dist')
        direct = rea.snapshot(self.core, {**self.args, 'target_path':'published/dist'}, lambda:None)
        self.assertEqual(len(direct['files']), 2)

    def test_rea_evidence_write_failure_is_not_confirmed(self):
        with patch('jarvis_core.rea_evidence.save', side_effect=OSError('fixture disk failure')):
            item = self.submit(skill_id='rea.software-analysis', paths=[], target_path='application')
            detail = self.wait(item)
        self.assertEqual(detail['action_status'], 'UNKNOWN')
        with self.assertRaises(CoreError): self.bridge.skill_evidence(self.cid, item['task_id'])

    def test_rea_paging_legacy_and_bounds(self):
        from jarvis_core.rea_evidence import page, load, read
        evidence = {'evidence_id':'ev_fixture', 'normalized_result':{'graph':{'edges':[
            {'edge_id':'e1', 'relation':'invokes', 'properties':{'text':'汉'*20000}}]}}}
        report = {'kind':'jarvis.skill-report','skill_id':'rea.software-analysis','evidence':evidence,'input_manifest':{'files':[],'omitted':[]}}
        self.assertEqual(load(self.core, report, 'act_'+'0'*32), evidence)
        result = page(evidence, report, 'links')
        self.assertTrue(result['items'][0]['truncated'])
        self.assertLess(len(json.dumps(result, ensure_ascii=False).encode('utf-8')), 12000)
        for kwargs in ({'section':'unknown'}, {'section':'links','offset':-1}, {'section':'links','limit':51}):
            with self.assertRaises(CoreError): page(evidence, report, **kwargs)
        with self.assertRaises(CoreError): read(self.core, {'path':'../other','size_bytes':1}, 'act_'+'0'*32)

    def test_rea_invalid_target(self):
        for target in ('../outside', 'C:/outside', 'missing', 'application/main.js'):
            with self.assertRaises(CoreError): self.submit(skill_id='rea.software-analysis', paths=[], target_path=target)

    def test_rea_exclusions_and_empty(self):
        app = self.source / 'application'
        (app / '.env').write_text('SECRET=not-for-parser'); (app / 'app.exe').write_bytes(b'fake')
        result = rea.snapshot(self.core, self.args, lambda: None)
        self.assertEqual({r['path'] for r in result['omitted']}, {'.env', 'app.exe'})
        self.assertEqual(len(result['files']), 4)
        empty = self.source / 'empty'; empty.mkdir(); (empty / 'app.asar').write_bytes(b'fake')
        with self.assertRaises(CoreError): rea.snapshot(self.core, {**self.args, 'target_path': 'empty'}, lambda: None)

    def test_rea_hardlink_and_budget(self):
        os.link(self.source / 'application/main.js', self.source / 'application/hard.js')
        with self.assertRaises(CoreError): rea.snapshot(self.core, self.args, lambda: None)
        (self.source / 'application/hard.js').unlink()
        with patch.object(rea, 'MAX_FILES', 1):
            with self.assertRaises(CoreError): rea.snapshot(self.core, self.args, lambda: None)

    def test_rea_changed_source_no_delivery(self):
        original = rea.snapshot; calls = []
        def changing(*args, **kw):
            value = original(*args, **kw); calls.append(True)
            if len(calls) == 2: (self.source / 'application/math.js').write_text('exports.sum = () => 99;')
            return value
        with patch.object(rea, 'snapshot', side_effect=changing):
            detail = self.wait(self.submit(skill_id='rea.software-analysis', paths=[], target_path='application'))
        self.assertEqual(detail['task']['status'], 'FAILED', detail)
        self.assertEqual(detail['error']['code'], 'rea_source_changed')
        self.assertFalse(list(self.source.glob('技能产物*')))

    def test_rea_missing_runtime_and_invalid_evidence(self):
        with patch.object(rea, 'PROFILE', self.root / 'missing.json'):
            with self.assertRaises(CoreError): self.submit(skill_id='rea.software-analysis', paths=[], target_path='application')
        with self.assertRaises(CoreError): rea.projection({'evidence_id': 'ev_fake'})

    def test_rea_syntax_failure(self):
        (self.source / 'application/main.js').write_text('function broken( {', encoding='utf-8')
        detail = self.wait(self.submit(skill_id='rea.software-analysis', paths=[], target_path='application'))
        self.assertEqual(detail['task']['status'], 'FAILED')
        self.assertFalse(list(self.source.glob('技能产物*')))

    def test_rea_runtime_change_and_cancel(self):
        runtime, _ = rea.runtime()
        profile = json.loads(rea.PROFILE.read_text(encoding='utf-8'))
        bad = self.root / 'bad-runtime.json'; bad.write_text(json.dumps({**profile, 'manifest_digest': 'sha256:' + '0' * 64}))
        with patch.object(rea, 'PROFILE', bad):
            with self.assertRaises(CoreError): rea.runtime(verify=True)
        def stop(): raise CoreError('cancelled', 'cancel runtime verification')
        with self.assertRaises(CoreError) as caught: rea.runtime(verify=True, checkpoint=stop)
        self.assertEqual(caught.exception.code, 'cancelled')

    def test_rea_job_host_crash_kills_children(self):
        import ctypes
        runtime, _ = rea.runtime(); marker = self.root / 'child.json'
        js = self.root / 'child.cjs'
        js.write_text("const {spawn}=require('child_process');const fs=require('fs');const child=spawn(process.execPath,['-e','setInterval(()=>{},1000)'],{stdio:'ignore'});fs.writeFileSync(process.argv[2],JSON.stringify([process.pid,child.pid]));setInterval(()=>{},1000);", encoding='utf-8')
        launcher = self.root / 'launcher.py'
        launcher.write_text('import sys,os\nfrom pathlib import Path\nsys.path.insert(0,' + repr(str(ROOT/'runtime/node-host')) + ')\nfrom jarvis_core.rea_process import run\ndef checkpoint():\n if Path(sys.argv[4]).exists(): os._exit(0)\nrun([sys.argv[1],sys.argv[2],sys.argv[4]],Path(sys.argv[3]),checkpoint)\n', encoding='utf-8')
        result = subprocess.run([sys.executable, str(launcher), str(runtime/'node.exe'), str(js), str(self.root), str(marker)], timeout=10, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        pids = json.loads(marker.read_text()); self.assertEqual(len(pids), 2)
        for pid in pids:
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if handle:
                ctypes.windll.kernel32.WaitForSingleObject(handle, 5000)
                code = ctypes.c_ulong(); ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
                ctypes.windll.kernel32.CloseHandle(handle); self.assertNotEqual(code.value, 259)

    def test_rea_policy_applies_and_dispatch_cancel(self):
        self.skills.put_policy({'skill_id':'rea.software-analysis', 'scope':'global', 'revision':0, 'mode':'disabled'})
        with self.assertRaises(CoreError): self.submit(skill_id='rea.software-analysis', paths=[], target_path='application')
        self.skills.put_policy({'skill_id':'rea.software-analysis', 'scope':'global', 'revision':1, 'mode':'auto'})
        def cancelled(*a, **kw): raise CoreError('cancelled', 'cancelled parser')
        with patch('jarvis_core.rea_process.run', side_effect=cancelled):
            detail = self.wait(self.submit(skill_id='rea.software-analysis', paths=[], target_path='application'))
        self.assertEqual(detail['task']['status'], 'CANCELLED')
        self.assertFalse(list(self.source.glob('技能产物*')))

    def test_rea_job_cancel_and_limits(self):
        import ctypes
        runtime, _ = rea.runtime(); node = str(runtime / 'node.exe'); pids = []
        started = time.monotonic()
        def checkpoint():
            if time.monotonic() - started > .3: raise CoreError('cancelled', 'fixture cancellation')
        with self.assertRaises(CoreError):
            run([node, '-e', 'setInterval(()=>{},1000)'], self.root, checkpoint, on_started=pids.append)
        self.assertTrue(pids)
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pids[0])
        if handle:
            status = ctypes.c_ulong()
            ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(status))
            ctypes.windll.kernel32.CloseHandle(handle)
            self.assertNotEqual(status.value, 259)
        with self.assertRaises(CoreError) as caught:
            run([node, '-e', 'console.log("x".repeat(10000))'], self.root, lambda: None, output_limit=100)
        self.assertEqual(caught.exception.code, 'rea_output_limit')
        with self.assertRaises(CoreError) as caught:
            run([node, '-e', 'setInterval(()=>{},1000)'], self.root, lambda: None, seconds=.1)
        self.assertEqual(caught.exception.code, 'rea_timeout')
        output = self.root / 'streamed.json'
        result = run([node, '-e', 'console.log("x".repeat(2000000))'], self.root, lambda:None,
                     output_limit=3*1024*1024, output_path=output)
        self.assertEqual(result['stdout'], b'')
        self.assertEqual(output.stat().st_size, result['stdout_bytes'])
        with self.assertRaises(CoreError) as caught:
            run([node, '-e', 'console.log("x".repeat(10000))'], self.root, lambda:None,
                output_limit=100, output_path=self.root/'too-large.json')
        self.assertEqual(caught.exception.code, 'rea_output_limit')


# Keep the shared fixture conveniences without duplicating its test suite.
for name in list(test_skills.TaskTests.__dict__):
    if name.startswith('test_'): setattr(ReaTests, name, None)

if __name__ == '__main__': unittest.main()
