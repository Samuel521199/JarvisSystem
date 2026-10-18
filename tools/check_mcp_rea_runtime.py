"""Offline MCP/REA, shared queue and conversation regression; no cloud calls."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core import __version__


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--candidates',action='store_true')
    args=parser.parse_args()
    results=[]
    suites=('test_mcp_candidates.py','test_mcp_runtime.py','test_mcp_catalog.py','test_conversation_tasks.py','test_computer_queue.py') if args.candidates else (
        'test_mcp_runtime.py','test_mcp_catalog.py','test_rea_projection.py','test_conversation_tasks.py',
        'test_computer_queue.py','test_resources.py','test_rea_explanation.py','test_rea_asar.py','test_rea.py')
    for name in suites:
        start=time.monotonic()
        process=subprocess.run([sys.executable,'-X','utf8','-m','unittest','discover','-s','tests','-p',name,'-v'],
            cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=700)
        output=process.stdout+process.stderr;count=re.search(r'Ran (\d+) tests?',output)
        row={'suite':name,'passed':process.returncode==0,'tests':int(count[1]) if count else None,
             'seconds':round(time.monotonic()-start,2),'output':output}
        results.append(row);print(json.dumps({k:v for k,v in row.items() if k!='output'}),flush=True)
    files=['runtime/node-host/jarvis_core/'+x+'.py' for x in ('mcp_client','mcp_tasks','mcp_catalog','rea','rea_focus','rea_evidence','rea_explanation','task_queue','conversation_tasks')]
    files+=['adapters/computer-use/jarvis_computer/web.py','adapters/computer-use/jarvis_computer/task_queue.py',
            'apps/web/conversation_tasks.js','apps/web/mcp_manager.js','apps/web/skills.js','config/resource-profile.json']
    if args.candidates:files+=['runtime/node-host/jarvis_core/mcp_candidates.py','apps/web/server.py','apps/web/index.html']
    report={'version':__version__,'observed_at':datetime.now(timezone.utc).isoformat(),'status':'passed' if all(r['passed'] for r in results) else 'failed',
            'tests':sum(r['tests'] or 0 for r in results),'model_calls':0,'real_mcp_calls':0,'results':results,
            'source_digests':{f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files}}
    filename='mcp-candidates-baseline-2026-10-18.json' if args.candidates else 'mcp-rea-runtime-baseline-2026-10-18.json'
    (ROOT/'evals/reports'/filename).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return 0 if report['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
