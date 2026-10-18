"""Repeatable local regression for the conversation/task process boundary."""
import hashlib
import json
from pathlib import Path
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'runtime/node-host'),str(ROOT/'apps/web'),str(ROOT/'adapters/models/provider-native')]
from jarvis_core import __version__


def main():
    names='test_dialogue_process test_dialogue_recovery test_dialogue_turns test_conversations test_web test_chat test_readout test_resources test_runtime_metrics test_conversation_tasks test_personal_core test_continuity test_semantic_candidates test_sample_tasks test_skills test_rea_explanation'.split()
    paths=['runtime/node-host/jarvis_core/'+name+'.py' for name in
           ['__init__','dialogue_process','dialogue_worker','turns','chat','sample_tasks','skill_tasks','rea_explanation']]
    paths+=['apps/web/server.py','apps/web/resources.js','adapters/computer-use/jarvis_computer/web.py',
            'tests/test_dialogue_process.py','tests/dialogue_process_fixture.py','tools/check_conversation_lanes.py',
            'tests/test_semantic_candidates.py','tests/test_skills.py','tests/test_rea_explanation.py',
            'runtime/node-host/jarvis_core/task_queue.py','adapters/computer-use/jarvis_computer/task_queue.py']
    hashes=lambda:{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    before=hashes(); started=time.monotonic()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    after=hashes(); changed=[p for p in paths if before[p]!=after[p]]
    destination=ROOT/'evals/reports/conversation-lanes-baseline-2026-10-18.json'
    previous=[]
    if destination.exists():
        prior=json.loads(destination.read_text(encoding='utf-8'))
        previous=prior.get('previous_runs',[])
        previous.append({k:prior[k] for k in ('status','source_version','tests','failures','errors','skipped')})
    report=dict(status=('SOURCE_CHANGED' if changed else 'SUCCEEDED') if result.wasSuccessful() else 'FAILED',source_version=__version__,tests=result.testsRun,
        failures=len(result.failures),errors=len(result.errors),skipped=len(result.skipped),modules=names,
        previous_runs=previous,failed_tests=[t.id() for t,_ in result.failures+result.errors],
        elapsed_seconds=round(time.monotonic()-started,3),source_sha256=before,
        source_changes_during_run=changed,source_sha256_after=after if changed else {})
    destination.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'modules','source_sha256','source_sha256_after'}}))
    return not result.wasSuccessful() or bool(changed)


if __name__=='__main__':sys.exit(main())
