"""Publish a local evidence index only after explicitly supplied successful checks."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sys
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'runtime/node-host'))
from jarvis_core import __version__
from jarvis_core.skills import catalog
from jarvis_core.skill_validation import fingerprint

def main():
    p=argparse.ArgumentParser();p.add_argument('--test-log',required=True,type=Path);a=p.parse_args()
    log=a.test_log.read_text(encoding='utf-8-sig');match=re.search(r'Ran (\d+) tests in ([\d.]+)s',log)
    if not match or not re.search(r'\nOK\s*$',log):p.error('The supplied final suite did not pass')
    review=json.loads((ROOT/'evals/reports/skill-coverage-review-2026-10-19.json').read_text(encoding='utf-8'))
    live=json.loads((ROOT/'evals/reports/coding-workflow-live-r5-2026-10-19.json').read_text(encoding='utf-8'))
    assert live['status']=='passed' and len({x['task_id'] for x in live['results']})==2
    records={};observed=datetime.now(timezone.utc).isoformat()
    for item in catalog()[0]['skills']:
        if not item.get('presentation'):continue
        rows=[x for x in review['results'] if x['skill_id']==item['id'] and x['arm']=='with_skill']
        if rows:
            models={}
            for route in sorted({x['route'] for x in rows}):
                values=[r for r in rows if r['route']==route]
                models[route]={s:sum(r['assessment']==s for r in values) for s in ['pass','partial','fail']}
            complete=[route for route,counts in models.items() if counts['pass']==3]
            assert complete
            scope='每模型3个场景，另有无技能配对。Sol本批3项满足预声明要点；Google '+str(models['vertex::gemini-3.8-flash']['pass'])+' 项满足、'+str(models['vertex::gemini-3.8-flash']['partial'])+' 项部分满足、'+str(models['vertex::gemini-3.8-flash']['fail'])+' 项未满足。由本轮Agent审阅，无独立人工盲评；不代表普遍质量或当前可用余额。'
            reports=['evals/reports/skill-coverage-review-2026-10-19.json'];cases=3
        else:
            models={};cases=1
            scope=('当前专项覆盖固定齿轮数值、LPAC、实际浏览器与产物摘要；不是自由机械CAD或视频验证。' if item['workflow']=='anatomy' else '当前专项覆盖目录/ASAR、证据分页、关注项与中文引用边界。历史两应用32处理器证据仍仅代表限定范围，不代表整包或实际运行行为。')
            reports=['evals/reports/skills-completion-baseline-2026-10-19.json']
        records[item['id']]={'binding':fingerprint(item),'version':__version__,'observed_at':observed,'status':'passed','cases':cases,'models':list(models),'model_results':models,'scope':scope,'reports':reports}
    index={'schema_version':1,'skills':records}
    (ROOT/'config/skills/validation.json').write_text(json.dumps(index,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    baseline={'version':__version__,'observed_at':observed,'status':'local_verified_pending_deployment','engineering_tests':{'count':int(match[1]),'seconds':float(match[2]),'status':'passed','log_path':str(a.test_log),'sha256':hashlib.sha256(a.test_log.read_bytes()).hexdigest()},
        'quality':review['summary'],'quality_method':review['method'],'coding_live_report':'evals/reports/coding-workflow-live-r5-2026-10-19.json',
        'failures_preserved':['evals/reports/coding-workflow-live-2026-10-19.json','evals/reports/coding-workflow-live-r2-2026-10-19.json','evals/reports/coding-workflow-live-r3-2026-10-19.json','evals/reports/coding-workflow-live-r4-2026-10-19.json'],
        'failure_notes':'Initial UI handler hid cases; then missing guard return prevented dispatch; Google formatting failed bounded validation; a probe selector reused a prior task. Fixed without loosening code/test contracts. Final live probe checks distinct task IDs and exact model identity. Invalid/unfinished debug results are not counted as successful deliveries; remote charges for an unfinished debug task are not inferred.',
        'scope':'Single-file data transformations only. Nine guidance skills retained; comparative evidence is case-level and model-dependent. Low-memory injection and bounded local soak are separate from physical low-end and multi-day acceptance.',
        'bindings':{k:v['binding'] for k,v in records.items()}}
    (ROOT/'evals/reports/skills-completion-baseline-2026-10-19.json').write_text(json.dumps(baseline,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'tests':match[1],'skills':len(records),'version':__version__}))

if __name__=='__main__':main()
