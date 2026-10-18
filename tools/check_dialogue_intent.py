"""Local intent, chat and receipt regression; no paid calls."""
import hashlib
import argparse
import json
from pathlib import Path
import sys
import time
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'runtime/node-host'),str(ROOT/'apps/web'),str(ROOT/'adapters/models/provider-native')]
from jarvis_core import __version__


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--automatic',action='store_true');args=parser.parse_args()
    names=['test_intent','test_chat','test_dialogue_turns','test_dialogue_recovery','test_dialogue_process',
           'test_web','test_conversation_tasks','test_mcp_candidates']
    if args.automatic:names+=['test_documentation_admission','test_mcp_runtime','test_mcp_catalog']
    paths=['runtime/node-host/jarvis_core/'+n+'.py' for n in ['__init__','intent','chat','turns','dialogue_process','dialogue_worker','assistant_context','mcp_candidates','conversation_tasks']]
    paths+=['apps/web/dialogue.js','apps/web/index.html','apps/web/server.py','apps/web/conversation_tasks.js',
            'tests/test_intent.py','tests/dialogue_process_fixture.py','tools/check_dialogue_intent.py']
    if args.automatic:paths+=['runtime/node-host/jarvis_core/'+n+'.py' for n in ['documentation_admission','mcp_tasks','mcp_catalog','task_queue']]+['tests/test_documentation_admission.py','config/mcp/automation.json']
    hashes=lambda:{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in paths}
    before=hashes();started=time.monotonic()
    result=unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromNames(names))
    changed=before!=hashes()
    report={'status':('SOURCE_CHANGED' if changed else 'SUCCEEDED') if result.wasSuccessful() else 'FAILED',
            'source_version':__version__,'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),
            'skipped':len(result.skipped),'failed_tests':[t.id() for t,_ in result.failures+result.errors],
            'elapsed_seconds':round(time.monotonic()-started,3),'modules':names,'source_sha256':before,'source_changed':changed,
            'cloud_calls':0,'limits':'Mocks verify failure and authority boundaries, not semantic accuracy.'}
    filename='documentation-auto-baseline-2026-10-18.json' if args.automatic else 'dialogue-intent-baseline-2026-10-18.json'
    (ROOT/'evals/reports'/filename).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k!='source_sha256'}))
    return not result.wasSuccessful() or changed


if __name__=='__main__':sys.exit(main())
