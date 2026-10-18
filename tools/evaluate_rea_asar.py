"""Repeat ASAR/focus and existing skill regression suites without cloud calls."""
from datetime import datetime, timezone
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
    results=[]
    for name in ('test_rea_asar.py','test_rea.py','test_skills.py','test_project_resources.py','test_conversation_tasks.py'):
        start=time.monotonic()
        proc=subprocess.run([sys.executable,'-X','utf8','-m','unittest','discover','-s','tests','-p',name,'-v'],
                            cwd=ROOT,capture_output=True,text=True,encoding='utf-8',timeout=300)
        output=proc.stdout+proc.stderr
        count=re.search(r'Ran (\d+) tests?',output)
        results.append({'suite':name,'passed':proc.returncode==0,'tests':int(count[1]) if count else None,
                        'seconds':round(time.monotonic()-start,3),'output':output})
        print(json.dumps({k:v for k,v in results[-1].items() if k!='output'}),flush=True)
    files=['runtime/node-host/jarvis_core/'+name for name in
           ('rea.py','rea_asar.py','rea_focus.py','rea_evidence.py','rea_process.py','skill_tasks.py')]
    files+=['apps/web/skills.js','config/skills/catalog.json','adapters/skills/rea/SKILL.md']
    record={'version':__version__,'observed_at':datetime.now(timezone.utc).isoformat(),
            'status':'passed' if all(r['passed'] for r in results) else 'failed','results':results,
            'tests':sum(r['tests'] or 0 for r in results),'model_calls':0,'target_executed':False,
            'source_digests':{f:'sha256:'+hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files},
            'scope':'Self-owned official @electron/asar 4.2.0 packed/unpacked fixtures; bounded malformed inputs. No general real-world accuracy claim.'}
    (ROOT/'evals/reports/rea-asar-focus-baseline-2026-10-18.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    if record['status']!='passed':raise SystemExit(1)


if __name__=='__main__':main()
